"""カットモード別の保持区間算出ロジック"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

Segment = tuple[float, float]


# ---------------------------------------------------------------------------
# 共通ベース処理
# ---------------------------------------------------------------------------

def _apply_buffers(
    speech_segments: list[Segment],
    total_duration: float,
    pre_buffer: float,
    post_buffer: float,
) -> list[Segment]:
    """発話区間に pre_buffer / post_buffer を付与し、重複をマージして返す。

    Args:
        speech_segments: 発話区間リスト [(start, end), ...]。
        total_duration: 動画の総時間（秒）。
        pre_buffer: 発話開始前に追加する余白（秒）。
        post_buffer: 発話終了後に追加する余白（秒）。

    Returns:
        バッファ付きでマージされた保持区間リスト。
    """
    if not speech_segments:
        return []

    buffered = [
        (max(0.0, s - pre_buffer), min(total_duration, e + post_buffer))
        for s, e in speech_segments
    ]

    merged: list[Segment] = [buffered[0]]
    for start, end in buffered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    return merged


# ---------------------------------------------------------------------------
# Mode A: 全無音削除
# ---------------------------------------------------------------------------

def apply_mode_a(
    speech_segments: list[Segment],
    total_duration: float,
    pre_buffer: float = 0.2,
    post_buffer: float = 0.3,
) -> list[Segment]:
    """Mode A: すべての無音区間を削除し、発話区間のみ保持する。

    Args:
        speech_segments: VAD で検出した発話区間リスト。
        total_duration: 動画の総時間（秒）。
        pre_buffer: 発話開始前の余白（秒）。
        post_buffer: 発話終了後の余白（秒）。

    Returns:
        保持区間リスト [(keep_start, keep_end), ...]。
    """
    keep = _apply_buffers(speech_segments, total_duration, pre_buffer, post_buffer)
    logger.debug("Mode A: 保持区間 %d 件", len(keep))
    return keep


# ---------------------------------------------------------------------------
# Mode B: 閾値指定削除（Phase 1 主要モード）
# ---------------------------------------------------------------------------

def apply_mode_b(
    speech_segments: list[Segment],
    total_duration: float,
    threshold: float = 2.0,
    pre_buffer: float = 0.2,
    post_buffer: float = 0.3,
) -> list[Segment]:
    """Mode B: 指定秒数以上の無音区間のみ削除する。

    threshold 未満の無音区間はそのまま保持し、
    threshold 以上の無音区間だけを取り除いた保持区間リストを返す。

    Args:
        speech_segments: VAD で検出した発話区間リスト。
        total_duration: 動画の総時間（秒）。
        threshold: この秒数以上の無音を削除する閾値。
        pre_buffer: 発話開始前の余白（秒）。
        post_buffer: 発話終了後の余白（秒）。

    Returns:
        保持区間リスト [(keep_start, keep_end), ...]。
    """
    buffered = _apply_buffers(speech_segments, total_duration, pre_buffer, post_buffer)

    if not buffered:
        return [(0.0, total_duration)]

    keep: list[Segment] = []
    prev_end = 0.0

    for start, end in buffered:
        silence_dur = start - prev_end
        if silence_dur < threshold:
            # 閾値未満の無音は前の区間に吸収して保持
            if keep:
                keep[-1] = (keep[-1][0], end)
            else:
                keep.append((0.0, end))
        else:
            keep.append((start, end))
        prev_end = end

    # 末尾の無音処理
    if prev_end < total_duration:
        tail_silence = total_duration - prev_end
        if tail_silence < threshold:
            if keep:
                keep[-1] = (keep[-1][0], total_duration)
            else:
                keep.append((0.0, total_duration))

    logger.debug("Mode B (threshold=%.1f s): 保持区間 %d 件", threshold, len(keep))
    return keep


# ---------------------------------------------------------------------------
# Mode C: テンポ改善
# ---------------------------------------------------------------------------

_C_SHORT  = 0.3   # これ未満の無音: そのまま保持
_C_LONG   = 1.5   # これ以上の無音: 削除
_C_KEEP   = 0.3   # 中間無音（_C_SHORT〜_C_LONG）: この秒数だけ末尾を残す


def apply_mode_c(
    speech_segments: list[Segment],
    total_duration: float,
) -> list[Segment]:
    """Mode C: テンポ改善モード（再エンコードなし）。

    無音区間の長さに応じて以下のルールを適用し、保持区間リストを生成する:

    - 無音 < 0.3 秒  → そのまま保持（前後の発話区間とまとめて保持）
    - 0.3 秒 <= 無音 < 1.5 秒 → 無音末尾の 0.3 秒だけ残して圧縮
    - 無音 >= 1.5 秒 → 削除

    「圧縮」とは無音区間全体を短縮することではなく、
    発話直前の 0.3 秒を保持することで自然な間を演出する実装。
    再エンコードは一切行わない。

    Args:
        speech_segments: VAD で検出した発話区間リスト。
        total_duration: 動画の総時間（秒）。

    Returns:
        保持区間リスト [(keep_start, keep_end), ...]。
    """
    if not speech_segments:
        return []

    # keep_segments を (start, end) のリストとして構築する
    # 可変で扱いたいため [start, end] のリストを使い、最後にタプルに変換する
    keep: list[list[float]] = []

    def _add_or_merge(start: float, end: float) -> None:
        """区間を追加。直前区間と重複・隣接する場合はマージする。"""
        if keep and start <= keep[-1][1]:
            keep[-1][1] = max(keep[-1][1], end)
        else:
            keep.append([start, end])

    prev_end = 0.0  # 前の発話区間の終端（初期値 = 動画の先頭）

    for speech_start, speech_end in speech_segments:
        silence_dur = speech_start - prev_end

        if silence_dur < _C_SHORT:
            # 短い無音: 前の区間とまとめて保持（prev_end からつなげる）
            seg_start = keep[-1][0] if keep else prev_end
            _add_or_merge(seg_start, speech_end)
        elif silence_dur < _C_LONG:
            # 中間無音: 発話直前の _C_KEEP 秒だけ残す
            compressed_start = max(prev_end, speech_start - _C_KEEP)
            _add_or_merge(compressed_start, speech_end)
        else:
            # 長い無音: 無音を完全に削除し、発話区間だけ追加
            _add_or_merge(speech_start, speech_end)

        prev_end = speech_end

    # 末尾の無音処理
    trailing = total_duration - prev_end
    if trailing > 0:
        if trailing < _C_SHORT:
            # 短い末尾無音: 最後の区間に吸収
            if keep:
                keep[-1][1] = total_duration
        elif trailing < _C_LONG:
            # 中間末尾無音: 末尾 _C_KEEP 秒だけ残す
            _add_or_merge(total_duration - _C_KEEP, total_duration)
        # 長い末尾無音: 何もしない（削除）

    result = [(s, e) for s, e in keep]
    logger.debug("Mode C: 保持区間 %d 件 (total=%.2f s)", len(result), total_duration)
    return result


# ---------------------------------------------------------------------------
# ファサード
# ---------------------------------------------------------------------------

def apply_mode(
    mode: str,
    speech_segments: list[Segment],
    total_duration: float,
    threshold: float = 2.0,
    pre_buffer: float = 0.2,
    post_buffer: float = 0.3,
) -> list[Segment]:
    """モード文字列から対応する算出関数へディスパッチする。

    Args:
        mode: "A", "B", または "C"（大文字・小文字どちらも可）。
        speech_segments: VAD で検出した発話区間リスト。
        total_duration: 動画の総時間（秒）。
        threshold: Mode B で使用する無音閾値（秒）。
        pre_buffer: 発話開始前の余白（秒）。
        post_buffer: 発話終了後の余白（秒）。

    Returns:
        保持区間リスト [(keep_start, keep_end), ...]。

    Raises:
        ValueError: 未知のモード文字列が指定された場合。
    """
    m = mode.upper()
    if m == "A":
        return apply_mode_a(speech_segments, total_duration, pre_buffer, post_buffer)
    if m == "B":
        return apply_mode_b(speech_segments, total_duration, threshold, pre_buffer, post_buffer)
    if m == "C":
        return apply_mode_c(speech_segments, total_duration)
    raise ValueError(f"不明なモード: '{mode}'。A / B / C のいずれかを指定してください。")
