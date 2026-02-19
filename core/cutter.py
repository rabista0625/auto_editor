"""動画カット処理パイプライン"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from core.ffmpeg_utils import (
    concat_videos,
    create_concat_list,
    cut_segment_encoded,
    extract_audio,
    get_duration,
    get_video_encoder_opts,
)
from core.modes import apply_mode
from core.vad import detect_speech_segments

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str], None]


def run_pipeline(
    job_id: str,
    params: dict,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    """カット処理全体を実行するパイプライン関数。

    処理ステップと progress 値の対応:
        10%  音声抽出完了
        40%  VAD 解析完了
        60%  保持区間算出完了
        65〜95%  セグメント切り出し（N/M 区間完了）
        95〜99%  動画結合
        100% 処理完了

    Args:
        job_id: ジョブ識別子（ディレクトリ名に使用）。
        params: 処理パラメータ辞書。以下のキーを含む:
            - input_path (str|Path): 入力動画
            - output_path (str|Path): 出力動画
            - temp_dir (str|Path): 一時ディレクトリ
            - mode (str): A / B / C
            - threshold (float): Mode B の閾値
            - pre_buffer (float): 発話前余白
            - post_buffer (float): 発話後余白
            - vad_level (int): VAD 感度
        progress_callback: progress(int, message: str) を受け取るコールバック。

    Returns:
        出力動画ファイルのパス。

    Raises:
        RuntimeError: 処理失敗時。
    """
    def _progress(value: int, message: str) -> None:
        logger.info("[%s] %d%% - %s", job_id, value, message)
        if progress_callback:
            progress_callback(value, message)

    input_path = Path(params["input_path"])
    output_path = Path(params["output_path"])
    temp_dir = Path(params["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)

    mode = params.get("mode", "B")
    threshold = float(params.get("threshold", 2.0))
    pre_buffer = float(params.get("pre_buffer", 0.2))
    post_buffer = float(params.get("post_buffer", 0.3))
    vad_level = int(params.get("vad_level", 2))

    # Step 1: 音声抽出
    _progress(5, "音声を抽出中...")
    wav_path = temp_dir / "audio.wav"
    extract_audio(input_path, wav_path)
    total_duration = get_duration(input_path)
    _progress(10, "音声抽出完了")

    # Step 2: VAD 解析
    _progress(15, "音声解析中（VAD）...")
    speech_segments = detect_speech_segments(wav_path, vad_level=vad_level)
    _progress(40, f"VAD 完了: 発話区間 {len(speech_segments)} 件")

    # Step 3: 保持区間算出
    _progress(45, f"Mode {mode} で保持区間を算出中...")
    keep_segments = apply_mode(
        mode,
        speech_segments,
        total_duration,
        threshold=threshold,
        pre_buffer=pre_buffer,
        post_buffer=post_buffer,
    )
    _progress(60, f"保持区間算出完了: {len(keep_segments)} 件")

    if not keep_segments:
        raise RuntimeError("保持区間が 0 件です。パラメータを見直してください。")

    # Step 4: セグメントごとに再エンコードで切り出し（65〜95%、並列処理）
    # 再エンコードにより非キーフレーム境界でも正確に切り出せ、
    # タイムスタンプを 0 基準にリセットするため連結時の重複・ズレが発生しない
    encoder_opts = get_video_encoder_opts()
    encoder_name = encoder_opts[1]  # "-c:v" の次がエンコーダー名
    n = len(keep_segments)
    suffix = input_path.suffix

    # 並列数の決定:
    #   NVENC はコンシューマー GPU で同時エンコードセッション数が制限されるため 3 に抑える
    #   CPU エンコード時は論理コア数の半分を使用（サーバー処理との競合を避ける）
    if "nvenc" in encoder_name or "amf" in encoder_name or "qsv" in encoder_name:
        max_workers = 3
    else:
        max_workers = max(1, os.cpu_count() // 2)
    logger.info("並列処理数: %d [%s]", max_workers, encoder_name)

    # インデックス付きで並列実行し、完了順ではなくインデックス順で結合するため
    # part_paths は事前にサイズを確保しておく
    valid_indices = [
        i for i, (start, end) in enumerate(keep_segments) if end - start >= 0.01
    ]
    part_paths: list[Path | None] = [None] * len(keep_segments)
    completed = 0

    _progress(65, f"0/{len(valid_indices)} 区間完了 [{encoder_name}] (並列{max_workers})")

    def _cut(i: int, start: float, end: float) -> int:
        out = temp_dir / f"part_{i:04d}{suffix}"
        cut_segment_encoded(input_path, start, end, out)
        return i

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_cut, i, keep_segments[i][0], keep_segments[i][1]): i
            for i in valid_indices
        }
        for future in as_completed(futures):
            i = future.result()  # 例外があればここで再送出される
            out = temp_dir / f"part_{i:04d}{suffix}"
            part_paths[i] = out
            completed += 1
            pct = 65 + int(completed / len(valid_indices) * 30)  # 65 → 95%
            _progress(pct, f"{completed}/{len(valid_indices)} 区間完了 [{encoder_name}]")

    # None（スキップ済み）を除去しつつインデックス順を維持
    ordered_parts = [p for p in part_paths if p is not None]

    if not ordered_parts:
        raise RuntimeError("切り出せたセグメントが 0 件です。")

    # Step 5: 結合（ストリームコピー、95〜99%）
    _progress(95, f"動画を結合中... ({len(ordered_parts)} パート)")
    list_path = temp_dir / "concat_list.txt"
    create_concat_list(ordered_parts, list_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_videos(list_path, output_path)

    _progress(100, "処理完了")
    return output_path
