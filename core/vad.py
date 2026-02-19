"""WebRTC VAD を使った音声区間検出モジュール"""

import logging
import wave
from pathlib import Path

import webrtcvad

logger = logging.getLogger(__name__)

FRAME_DURATION_MS = 20  # webrtcvad が対応するフレーム長（10/20/30ms）
SAMPLE_RATE = 16000      # extract_audio() と一致させる


def detect_speech_segments(
    wav_path: str | Path,
    vad_level: int = 2,
) -> list[tuple[float, float]]:
    """WAV ファイルから発話区間リストを返す。

    処理フロー:
        1. WAV をフレーム分割（20ms 単位）
        2. 各フレームを webrtcvad で発話/無音判定
        3. 連続発話フレームをマージして区間リストを生成

    Args:
        wav_path: モノラル 16kHz PCM WAV ファイルのパス。
        vad_level: VAD 感度（0=寛容〜3=厳格）。

    Returns:
        発話区間リスト [(start_sec, end_sec), ...]。

    Raises:
        ValueError: WAV フォーマットが不正な場合。
        RuntimeError: VAD 処理が失敗した場合。
    """
    wav_path = Path(wav_path)
    logger.info("VAD 解析開始: %s (level=%d)", wav_path, vad_level)

    frames, total_duration = _read_wav_frames(wav_path)
    speech_flags = _classify_frames(frames, vad_level)
    segments = _merge_speech_frames(speech_flags)

    logger.info(
        "VAD 完了: %d 発話区間 / 総時間 %.2f 秒",
        len(segments),
        total_duration,
    )
    return segments


def get_silence_segments(
    speech_segments: list[tuple[float, float]],
    total_duration: float,
) -> list[tuple[float, float]]:
    """発話区間リストから無音区間リストを算出する。

    Args:
        speech_segments: 発話区間リスト [(start, end), ...]。
        total_duration: 動画の総再生時間（秒）。

    Returns:
        無音区間リスト [(start, end), ...]。
    """
    silence: list[tuple[float, float]] = []
    prev_end = 0.0

    for start, end in speech_segments:
        if start > prev_end:
            silence.append((prev_end, start))
        prev_end = end

    if prev_end < total_duration:
        silence.append((prev_end, total_duration))

    return silence


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _read_wav_frames(wav_path: Path) -> tuple[list[bytes], float]:
    """WAV ファイルを 20ms フレームに分割する。

    Returns:
        (frames, total_duration_sec) のタプル。

    Raises:
        ValueError: サンプルレートやチャンネル数が要件を満たさない場合。
    """
    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError(f"モノラル WAV が必要です（チャンネル数: {wf.getnchannels()}）")
        if wf.getsampwidth() != 2:
            raise ValueError(f"16bit PCM WAV が必要です（サンプル幅: {wf.getsampwidth()} bytes）")

        actual_rate = wf.getframerate()
        if actual_rate != SAMPLE_RATE:
            raise ValueError(
                f"サンプルレートが不一致です。期待値: {SAMPLE_RATE} Hz, 実際: {actual_rate} Hz"
            )

        n_frames = wf.getnframes()
        total_duration = n_frames / actual_rate
        raw_audio = wf.readframes(n_frames)

    frame_size = int(actual_rate * FRAME_DURATION_MS / 1000) * 2  # 2 bytes/sample
    frames = [
        raw_audio[i : i + frame_size]
        for i in range(0, len(raw_audio), frame_size)
        if len(raw_audio[i : i + frame_size]) == frame_size  # 端数フレームを除外
    ]

    logger.debug("WAV 読み込み: %d フレーム / %.2f 秒", len(frames), total_duration)
    return frames, total_duration


def _classify_frames(frames: list[bytes], vad_level: int) -> list[bool]:
    """各フレームを発話(True) / 無音(False) に分類する。"""
    vad = webrtcvad.Vad(vad_level)
    return [vad.is_speech(frame, SAMPLE_RATE) for frame in frames]


def _merge_speech_frames(speech_flags: list[bool]) -> list[tuple[float, float]]:
    """連続する発話フレームをマージして区間リストを生成する。

    Returns:
        発話区間リスト [(start_sec, end_sec), ...]。
    """
    frame_sec = FRAME_DURATION_MS / 1000.0
    segments: list[tuple[float, float]] = []
    in_speech = False
    start = 0.0

    for i, is_speech in enumerate(speech_flags):
        t = i * frame_sec
        if is_speech and not in_speech:
            start = t
            in_speech = True
        elif not is_speech and in_speech:
            segments.append((start, t))
            in_speech = False

    if in_speech:
        segments.append((start, len(speech_flags) * frame_sec))

    return segments
