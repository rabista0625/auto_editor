"""ジョブ管理モジュール（メモリ管理）"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["waiting", "processing", "done", "error"]

# メモリ上のジョブストア（job_id -> JobData）
_jobs: dict[str, "JobData"] = {}


@dataclass
class JobData:
    job_id: str
    status: JobStatus = "waiting"
    progress: int = 0
    message: str = ""
    input_path: str = ""
    output_path: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: _now())


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_job(
    input_path: str | Path,
    output_path: str | Path,
) -> JobData:
    """新しいジョブを登録して返す。

    Args:
        input_path: 入力動画ファイルのパス。
        output_path: 出力動画ファイルのパス（予定地）。

    Returns:
        生成された JobData オブジェクト。
    """
    job_id = str(uuid.uuid4())
    job = JobData(
        job_id=job_id,
        input_path=str(input_path),
        output_path=str(output_path),
    )
    _jobs[job_id] = job
    logger.info("ジョブ登録: %s", job_id)
    return job


def get_job(job_id: str) -> JobData | None:
    """ジョブを取得する。存在しない場合は None を返す。"""
    return _jobs.get(job_id)


def update_job(
    job_id: str,
    status: JobStatus | None = None,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
) -> None:
    """ジョブの状態を更新する。

    Args:
        job_id: 更新対象のジョブ ID。
        status: 新しいステータス（None の場合は変更しない）。
        progress: 新しい進捗値 0–100（None の場合は変更しない）。
        message: 状態メッセージ（None の場合は変更しない）。
        error: エラーメッセージ（None の場合は変更しない）。
    """
    job = _jobs.get(job_id)
    if job is None:
        logger.warning("update_job: job_id が見つかりません: %s", job_id)
        return
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    if error is not None:
        job.error = error


# ---------------------------------------------------------------------------
# クリーンアップ
# ---------------------------------------------------------------------------

def cleanup_temp(temp_dir: str | Path) -> None:
    """指定された一時ディレクトリを削除する。

    Args:
        temp_dir: 削除する一時ディレクトリのパス。
    """
    temp_path = Path(temp_dir)
    if temp_path.exists():
        shutil.rmtree(temp_path, ignore_errors=True)
        logger.info("一時ディレクトリを削除: %s", temp_path)
