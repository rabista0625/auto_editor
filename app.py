"""Auto Editor — FastAPI エントリポイント"""

from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"
LOGS_DIR = BASE_DIR / "logs"

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".ts", ".m4v"}

# MIME タイプ: video/* を基本とし、ブラウザが octet-stream で送る場合も許容
ALLOWED_MIME_PREFIXES = ("video/",)
ALLOWED_MIME_FALLBACKS = {"application/octet-stream"}

# ファイルサイズ上限: 20 GB（3時間級のゲーム実況動画を想定）
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB ずつ読み取り

# ---------------------------------------------------------------------------
# ロギング設定
# ---------------------------------------------------------------------------

LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOGS_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 起動時チェック
# ---------------------------------------------------------------------------

from core.ffmpeg_utils import check_ffmpeg  # noqa: E402

try:
    check_ffmpeg()
except RuntimeError as e:
    logger.critical("FFmpeg チェック失敗: %s", e)
    sys.exit(1)

from services.job_manager import (  # noqa: E402
    cleanup_temp,
    create_job,
    get_job,
    update_job,
)

# ---------------------------------------------------------------------------
# FastAPI アプリ
# ---------------------------------------------------------------------------

app = FastAPI(title="Auto Editor", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 必要なディレクトリを作成
for d in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------

@app.get("/", response_class=templates.TemplateResponse.__class__)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# POST /process
# ---------------------------------------------------------------------------

@app.post("/process")
async def process(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("B"),
    threshold: float = Form(2.0),
    pre_buffer: float = Form(0.2),
    post_buffer: float = Form(0.3),
    vad_level: int = Form(2),
):
    # --- 拡張子チェック ---
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"非対応の形式です: '{suffix}'。対応形式: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # --- MIME タイプチェック ---
    content_type = (file.content_type or "").lower()
    if not (
        any(content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES)
        or content_type in ALLOWED_MIME_FALLBACKS
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"非対応の Content-Type です: '{content_type}'。"
                "動画ファイルを選択してください。"
            ),
        )

    # --- その他パラメータバリデーション ---
    mode_upper = mode.upper()
    if mode_upper not in ("A", "B", "C"):
        raise HTTPException(status_code=400, detail="mode は A / B / C のいずれかを指定してください。")

    if not (0.0 < threshold <= 600.0):
        raise HTTPException(status_code=400, detail="threshold は 0 より大きく 600 以下で指定してください。")

    if not (0 <= vad_level <= 3):
        raise HTTPException(status_code=400, detail="vad_level は 0〜3 の整数で指定してください。")

    # --- ファイル名サニタイズ ---
    safe_name = _sanitize_filename(file.filename or "upload")
    input_path = INPUT_DIR / safe_name
    output_path = OUTPUT_DIR / f"edited_{safe_name}"

    # --- ストリーミング保存 + ファイルサイズ上限チェック ---
    # メモリに全量を乗せず 1MB チャンク単位でディスクに書き出す
    written = 0
    try:
        with input_path.open("wb") as fp:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_FILE_SIZE_BYTES:
                    fp.close()
                    input_path.unlink(missing_ok=True)
                    limit_gb = MAX_FILE_SIZE_BYTES // (1024 ** 3)
                    raise HTTPException(
                        status_code=413,
                        detail=f"ファイルサイズが上限（{limit_gb} GB）を超えています。",
                    )
                fp.write(chunk)
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"ファイル保存に失敗しました: {e}") from e

    logger.info("ファイル受信: %s (%d bytes)", safe_name, written)

    # --- ジョブ登録 ---
    job = create_job(input_path, output_path)
    temp_job_dir = TEMP_DIR / job.job_id
    update_job(job.job_id, status="waiting", progress=0, message="待機中")

    params = {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "temp_dir": str(temp_job_dir),
        "mode": mode_upper,
        "threshold": threshold,
        "pre_buffer": pre_buffer,
        "post_buffer": post_buffer,
        "vad_level": vad_level,
    }

    background_tasks.add_task(_run_job, job.job_id, params)
    return JSONResponse({"job_id": job.job_id})


# ---------------------------------------------------------------------------
# GET /progress/{job_id}
# ---------------------------------------------------------------------------

@app.get("/progress/{job_id}")
async def progress(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    return JSONResponse({
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
    })


# ---------------------------------------------------------------------------
# GET /download/{job_id}
# ---------------------------------------------------------------------------

@app.get("/download/{job_id}")
async def download(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません。")
    if job.status != "done":
        raise HTTPException(status_code=400, detail="処理が完了していません。")

    output_path = Path(job.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="出力ファイルが見つかりません。")

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=output_path.name,
    )


# ---------------------------------------------------------------------------
# バックグラウンドジョブ実行
# ---------------------------------------------------------------------------

def _run_job(job_id: str, params: dict) -> None:
    """BackgroundTasks から呼ばれるパイプライン実行関数。"""
    from core.cutter import run_pipeline

    temp_dir = Path(params["temp_dir"])

    def _progress_cb(value: int, message: str) -> None:
        update_job(job_id, progress=value, message=message)

    try:
        update_job(job_id, status="processing", progress=0, message="処理開始")
        run_pipeline(job_id, params, progress_callback=_progress_cb)
        update_job(job_id, status="done", progress=100, message="処理完了")
        logger.info("ジョブ完了: %s", job_id)
        # 処理成功時: 1時間後に出力ファイルを自動削除
        _schedule_cleanup(Path(params["output_path"]), delay=OUTPUT_CLEANUP_DELAY_SEC)
    except Exception as e:
        logger.exception("ジョブ失敗: %s", job_id)
        update_job(job_id, status="error", error=str(e), message="エラーが発生しました")
    finally:
        cleanup_temp(temp_dir)
        input_path = Path(params["input_path"])
        input_path.unlink(missing_ok=True)
        logger.info("入力ファイルを削除しました: %s", input_path)


# ---------------------------------------------------------------------------
# 自動クリーンアップ
# ---------------------------------------------------------------------------

OUTPUT_CLEANUP_DELAY_SEC = 60 * 60  # 処理完了から1時間後に出力ファイルを削除


def _schedule_cleanup(path: Path, delay: int = OUTPUT_CLEANUP_DELAY_SEC) -> None:
    """指定ファイルを delay 秒後に削除するタイマーをセットする。"""
    def _do_cleanup() -> None:
        path.unlink(missing_ok=True)
        logger.info("出力ファイルを自動削除しました（%d 分経過）: %s", delay // 60, path)

    timer = threading.Timer(delay, _do_cleanup)
    timer.daemon = True
    timer.start()
    logger.info("出力ファイルの自動削除を %d 分後にスケジュール: %s", delay // 60, path)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _sanitize_filename(filename: str) -> str:
    """ファイル名から危険な文字を除去して安全な名前を返す。"""
    name = Path(filename).name
    name = re.sub(r"[^\w\-. ]", "_", name)
    name = name.strip(". ")
    if not name:
        name = "upload"
    return name
