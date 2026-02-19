"""FFmpeg / ffprobe ラッパー関数群"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".ts", ".m4v"}

# 起動時に一度だけ検出してキャッシュする
_video_encoder_opts: list[str] | None = None


def check_ffmpeg() -> None:
    """FFmpeg と ffprobe が PATH に存在するか確認する。

    Raises:
        RuntimeError: どちらかが見つからない場合。
    """
    for cmd in ("ffmpeg", "ffprobe"):
        try:
            result = subprocess.run(
                [cmd, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            first_line = result.stdout.decode(errors="replace").splitlines()[0]
            logger.info("%s が見つかりました: %s", cmd, first_line)
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise RuntimeError(
                f"{cmd} が見つかりません。FFmpeg をインストールして PATH を通してください。"
            ) from e


def get_duration(video_path: str | Path) -> float:
    """ffprobe で動画の総再生時間（秒）を取得する。

    Args:
        video_path: 動画ファイルのパス。

    Returns:
        総再生時間（秒、float）。

    Raises:
        RuntimeError: ffprobe が失敗した場合。
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        logger.debug("動画時間: %.3f 秒 (%s)", duration, video_path)
        return duration
    except (subprocess.CalledProcessError, KeyError, ValueError) as e:
        raise RuntimeError(f"動画時間の取得に失敗しました: {video_path}") from e


def extract_audio(input_path: str | Path, output_wav_path: str | Path) -> None:
    """動画からモノラル 16kHz の PCM WAV を抽出する。

    Args:
        input_path: 入力動画ファイルのパス。
        output_wav_path: 出力 WAV ファイルのパス。

    Raises:
        RuntimeError: ffmpeg が失敗した場合。
    """
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        str(output_wav_path),
        "-y",
    ]
    logger.info("音声抽出開始: %s -> %s", input_path, output_wav_path)
    _run_ffmpeg(cmd, "音声抽出")


def get_video_encoder_opts() -> list[str]:
    """利用可能な最適なビデオエンコーダーオプションを返す（初回のみ実際に検証）。

    NVIDIA NVENC → AMD AMF → Intel QSV → libx264 の順で試す。
    実際にダミーエンコードを実行して動作確認するため、確実に使えるものを返す。

    Returns:
        ffmpeg に渡すビデオエンコーダーオプションのリスト。
    """
    global _video_encoder_opts
    if _video_encoder_opts is not None:
        return _video_encoder_opts

    candidates = [
        (
            "NVIDIA NVENC (h264_nvenc)",
            "h264_nvenc",
            ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "18"],
        ),
        (
            "AMD AMF (h264_amf)",
            "h264_amf",
            ["-c:v", "h264_amf", "-quality", "balanced", "-qp_i", "18", "-qp_p", "20"],
        ),
        (
            "Intel QSV (h264_qsv)",
            "h264_qsv",
            ["-c:v", "h264_qsv", "-global_quality", "18"],
        ),
    ]

    try:
        enc_result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        encoders_text = enc_result.stdout.decode(errors="replace")

        for label, enc_name, opts in candidates:
            if f" {enc_name} " not in encoders_text:
                continue
            # ダミーエンコードで実際に動作するか確認
            # 注意: NVENC は最小解像度 145×145 以上が必要なため 320×240 を使用
            test = subprocess.run(
                [
                    "ffmpeg", "-hide_banner",
                    "-f", "lavfi",
                    "-i", "testsrc=size=320x240:rate=25:duration=0.1",
                    "-vf", "format=yuv420p",
                ] + opts + ["-f", "null", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if test.returncode == 0:
                logger.info("GPUエンコード使用: %s", label)
                _video_encoder_opts = opts
                return _video_encoder_opts
            stderr_msg = test.stderr.decode(errors="replace").splitlines()
            reason = next((l for l in stderr_msg if "Error" in l or "error" in l), "不明")
            logger.debug("%s は利用不可: %s", label, reason)

    except Exception as e:
        logger.warning("エンコーダー検出中にエラー: %s", e)

    _video_encoder_opts = ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]
    logger.info("CPUエンコード使用: libx264 (GPUエンコーダーが利用できません)")
    return _video_encoder_opts


def cut_segment_encoded(
    input_path: str | Path,
    start: float,
    end: float,
    output_path: str | Path,
) -> None:
    """動画の指定区間を再エンコードで切り出す。

    -ss を -i の前に置いてキーフレームへ高速シークした後、再エンコードで
    フレーム精度を確保する。-c copy では不可能な非キーフレーム境界での
    正確な切り出しが可能になり、連続するセグメント間の重複も発生しない。
    setpts/asetpts でタイムスタンプを 0 基準にリセットし、concat 時の
    タイムスタンプずれを防ぐ。

    Args:
        input_path: 入力動画ファイルのパス。
        start: 開始時刻（秒）。
        end: 終了時刻（秒）。
        output_path: 出力ファイルのパス。

    Raises:
        RuntimeError: ffmpeg が失敗した場合。
    """
    duration = end - start
    video_opts = get_video_encoder_opts()
    cmd = [
        "ffmpeg",
        "-ss", f"{start:.6f}",     # -i の前に置いて高速シーク（キーフレームへ）
        "-i", str(input_path),
        "-t", f"{duration:.6f}",
        *video_opts,
        "-vf", "setpts=PTS-STARTPTS",   # 映像タイムスタンプを 0 基準にリセット
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", "asetpts=PTS-STARTPTS",  # 音声タイムスタンプを 0 基準にリセット
        str(output_path),
        "-y",
    ]
    logger.debug("セグメント切り出し: %.3f -> %.3f", start, end)
    _run_ffmpeg(cmd, f"セグメント切り出し ({start:.2f}s - {end:.2f}s)")


def create_concat_list(part_paths: list[str | Path], list_path: str | Path) -> None:
    """ffmpeg concat デマクサー用のテキストリストファイルを生成する。

    Args:
        part_paths: 結合するパートファイルのパスリスト。
        list_path: 出力するリストファイルのパス。
    """
    lines = [f"file '{Path(p).as_posix()}'" for p in part_paths]
    Path(list_path).write_text("\n".join(lines), encoding="utf-8")
    logger.debug("concat リスト作成: %d 件 -> %s", len(part_paths), list_path)


def concat_videos(list_path: str | Path, output_path: str | Path) -> None:
    """concat リストに基づいて動画を結合する（ストリームコピー）。

    cut_segment_encoded で出力された各セグメントはタイムスタンプが 0 基準に
    揃っているため、concat デマクサーが正しくタイムスタンプを調整でき、
    重複や映像のズレが発生しない。

    Args:
        list_path: concat リストファイルのパス。
        output_path: 出力動画ファイルのパス。

    Raises:
        RuntimeError: ffmpeg が失敗した場合。
    """
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(output_path),
        "-y",
    ]
    logger.info("動画結合開始: %s -> %s", list_path, output_path)
    _run_ffmpeg(cmd, "動画結合")


def _run_ffmpeg(cmd: list[str], label: str) -> None:
    """ffmpeg コマンドを実行し、失敗時に RuntimeError を送出する。"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            logger.error("%s 失敗:\n%s", label, stderr)
            raise RuntimeError(f"ffmpeg {label} 失敗: {stderr[-500:]}")
        logger.debug("%s 完了", label)
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg が見つかりません。PATH を確認してください。") from e
