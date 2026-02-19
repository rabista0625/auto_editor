/** Auto Editor — フロントエンドロジック */

const POLL_INTERVAL_MS = 1500;

// DOM 参照
const fileInput       = document.getElementById("file-input");
const fileLabel       = document.getElementById("file-label");
const fileText        = document.getElementById("file-text");
const modeRadios      = document.querySelectorAll("input[name='mode']");
const thresholdRow    = document.getElementById("threshold-row");
const modeCNote       = document.getElementById("mode-c-note");
const thresholdInput  = document.getElementById("threshold");
const preBufferInput  = document.getElementById("pre-buffer");
const postBufferInput = document.getElementById("post-buffer");
const vadLevelSelect  = document.getElementById("vad-level");
const runBtn          = document.getElementById("run-btn");
const btnText         = document.getElementById("btn-text");

const progressSection = document.getElementById("progress-section");
const progressBar     = document.getElementById("progress-bar");
const progressPercent = document.getElementById("progress-percent");
const statusText      = document.getElementById("status-text");
const elapsedTimeEl   = document.getElementById("elapsed-time");
const infoFilename    = document.getElementById("info-filename");
const infoFilesize    = document.getElementById("info-filesize");

const errorSection    = document.getElementById("error-section");
const errorMessage    = document.getElementById("error-message");
const retryBtn        = document.getElementById("retry-btn");

const downloadSection = document.getElementById("download-section");
const downloadLink    = document.getElementById("download-link");
const doneStats       = document.getElementById("done-stats");
const resetBtn        = document.getElementById("reset-btn");

const toastEl         = document.getElementById("toast");
const expiryNote      = document.getElementById("expiry-note");
const expiryCountdown = document.getElementById("expiry-countdown");

let pollTimer          = null;
let elapsedTimer       = null;
let startTime          = null;
let expiryTimer        = null;
let expiryCountdownTimer = null;

const FILE_EXPIRY_MS = 60 * 60 * 1000; // 出力ファイルの有効期限（1時間）

// ---------------------------------------------------------------------------
// ファイル選択
// ---------------------------------------------------------------------------

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) {
    fileText.textContent = `${file.name}  (${_formatSize(file.size)})`;
    fileLabel.classList.add("selected");
    runBtn.disabled = false;
    btnText.textContent = "無音カットを開始";
  }
});

// ドラッグ&ドロップ
fileLabel.addEventListener("dragover", (e) => {
  e.preventDefault();
  fileLabel.classList.add("dragover");
});
fileLabel.addEventListener("dragleave", () => fileLabel.classList.remove("dragover"));
fileLabel.addEventListener("drop", (e) => {
  e.preventDefault();
  fileLabel.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event("change"));
  }
});

// ---------------------------------------------------------------------------
// モード切替 — パラメータ欄の表示/非表示
// ---------------------------------------------------------------------------

// data-modes="A B" のように対応モードが書かれた param-row 要素を全取得
const allParamRows = document.querySelectorAll(".param-row[data-modes]");

function updateParamVisibility() {
  const mode = _getMode();

  allParamRows.forEach((row) => {
    const validModes = (row.dataset.modes || "").split(" ");
    const visible = validModes.includes(mode);
    row.hidden = !visible;
    // hidden でも input を disabled にしてフォーム送信に含まれないようにする
    row.querySelectorAll("input, select").forEach((el) => {
      el.disabled = !visible;
    });
  });

  // Mode C の固定ルール説明ボックスを表示
  modeCNote.hidden = mode !== "C";
}

modeRadios.forEach((r) => r.addEventListener("change", updateParamVisibility));
updateParamVisibility();

// ---------------------------------------------------------------------------
// フォーム送信
// ---------------------------------------------------------------------------

runBtn.addEventListener("click", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  // ファイル情報バーに表示
  infoFilename.textContent = file.name;
  infoFilesize.textContent = _formatSize(file.size);

  _setProcessing(true);
  _showSection("progress");
  _startElapsedTimer();

  const formData = new FormData();
  formData.append("file", file);
  formData.append("mode", _getMode());
  formData.append("threshold", thresholdInput.value);
  formData.append("pre_buffer", preBufferInput.value);
  formData.append("post_buffer", postBufferInput.value);
  formData.append("vad_level", vadLevelSelect.value);

  try {
    const res = await fetch("/process", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || `HTTPエラー: ${res.status}`);
    }
    const { job_id } = await res.json();
    _startPolling(job_id);
  } catch (err) {
    _showError(err.message);
  }
});

// ---------------------------------------------------------------------------
// 進捗ポーリング
// ---------------------------------------------------------------------------

function _startPolling(jobId) {
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/progress/${jobId}`);
      if (!res.ok) throw new Error(`ステータス取得失敗: ${res.status}`);
      const data = await res.json();

      _updateProgress(data.progress, data.message || data.status);

      if (data.status === "done") {
        _stopPolling();
        _stopElapsedTimer();
        _showDownload(jobId);
      } else if (data.status === "error") {
        _stopPolling();
        _stopElapsedTimer();
        _showError(data.error || "処理中にエラーが発生しました。");
      }
    } catch (err) {
      _stopPolling();
      _stopElapsedTimer();
      _showError(err.message);
    }
  }, POLL_INTERVAL_MS);
}

function _stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// ---------------------------------------------------------------------------
// 経過時間タイマー
// ---------------------------------------------------------------------------

function _startElapsedTimer() {
  startTime = Date.now();
  elapsedTimeEl.textContent = "経過: 0:00";
  elapsedTimer = setInterval(() => {
    elapsedTimeEl.textContent = `経過: ${_formatElapsed(Date.now() - startTime)}`;
  }, 1000);
}

function _stopElapsedTimer() {
  if (elapsedTimer !== null) {
    clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
}

// ---------------------------------------------------------------------------
// UI 状態更新
// ---------------------------------------------------------------------------

function _updateProgress(percent, message) {
  const p = Math.min(100, Math.max(0, percent));
  progressBar.style.width = `${p}%`;
  progressPercent.textContent = `${p}%`;
  statusText.textContent = message || "";
}

function _showDownload(jobId) {
  _updateProgress(100, "処理完了！");

  // 完了統計（経過時間・ファイル情報）
  const elapsed = startTime ? _formatElapsed(Date.now() - startTime) : "-";
  doneStats.innerHTML =
    `ファイル: <strong>${infoFilename.textContent}</strong> (${infoFilesize.textContent})<br>` +
    `処理時間: <strong>${elapsed}</strong>`;

  // ダウンロードボタンをリセット（リトライ時のために）
  downloadLink.href = `/download/${jobId}`;
  downloadLink.textContent = "ダウンロード";
  downloadLink.classList.remove("btn-download-expired");

  expiryNote.innerHTML =
    `⏱ 出力ファイルは処理完了から <strong>1時間後</strong> に自動削除されます（残り <span id="expiry-countdown">60:00</span>）`;

  _showSection("download");
  _setProcessing(false);
  _showToast("処理が完了しました！", "success");
  _startExpiryCountdown();
}

function _showError(message) {
  errorMessage.textContent = message;
  _showSection("error");
  _setProcessing(false);
  _showToast("エラーが発生しました", "error");
}

function _showSection(name) {
  progressSection.hidden = name !== "progress";
  errorSection.hidden    = name !== "error";
  downloadSection.hidden = name !== "download";
}

function _setProcessing(active) {
  runBtn.disabled = active;
  btnText.textContent = active ? "処理中..." : "無音カットを開始";
  [fileInput, thresholdInput, preBufferInput, postBufferInput, vadLevelSelect].forEach(
    (el) => (el.disabled = active)
  );
  modeRadios.forEach((r) => (r.disabled = active));
  if (!active) updateParamVisibility();
}

// ---------------------------------------------------------------------------
// トースト通知
// ---------------------------------------------------------------------------

let toastTimeout = null;

function _showToast(message, type = "info") {
  if (toastTimeout) clearTimeout(toastTimeout);
  toastEl.textContent = message;
  toastEl.className = `toast toast-${type}`;
  toastEl.hidden = false;
  toastTimeout = setTimeout(() => {
    toastEl.hidden = true;
  }, 3500);
}

// ---------------------------------------------------------------------------
// 出力ファイル有効期限カウントダウン
// ---------------------------------------------------------------------------

function _startExpiryCountdown() {
  _stopExpiryCountdown();
  const endTime = Date.now() + FILE_EXPIRY_MS;

  expiryCountdownTimer = setInterval(() => {
    const remaining = endTime - Date.now();
    const el = document.getElementById("expiry-countdown");
    if (!el) return;
    if (remaining <= 0) {
      _onFileExpired();
    } else {
      const mins = Math.floor(remaining / 60000);
      const secs = String(Math.floor((remaining % 60000) / 1000)).padStart(2, "0");
      el.textContent = `${mins}:${secs}`;
    }
  }, 1000);

  expiryTimer = setTimeout(_onFileExpired, FILE_EXPIRY_MS);
}

function _stopExpiryCountdown() {
  clearInterval(expiryCountdownTimer);
  clearTimeout(expiryTimer);
  expiryCountdownTimer = null;
  expiryTimer = null;
}

function _onFileExpired() {
  _stopExpiryCountdown();
  // ダウンロードボタンを無効化
  downloadLink.removeAttribute("href");
  downloadLink.textContent = "ダウンロード（期限切れ）";
  downloadLink.classList.add("btn-download-expired");
  // メッセージを期限切れ表示に変更
  expiryNote.innerHTML =
    "⏰ 出力ファイルは自動削除されました。再度アップロードして処理してください。";
  expiryNote.classList.add("expiry-expired");
}

// ---------------------------------------------------------------------------
// リセット / リトライ
// ---------------------------------------------------------------------------

resetBtn.addEventListener("click", _resetUI);
retryBtn.addEventListener("click", _resetUI);

function _resetUI() {
  _stopPolling();
  _stopElapsedTimer();
  _stopExpiryCountdown();
  _showSection("none");
  _setProcessing(false);
  fileInput.value = "";
  fileText.textContent = "クリックまたはドラッグ＆ドロップ";
  fileLabel.classList.remove("selected");
  runBtn.disabled = true;
  btnText.textContent = "動画を選択してください";
  _updateProgress(0, "待機中...");
  elapsedTimeEl.textContent = "経過: 0:00";
  updateParamVisibility();
}

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------

function _getMode() {
  return [...modeRadios].find((r) => r.checked)?.value ?? "B";
}

function _formatSize(bytes) {
  if (bytes < 1024)        return `${bytes} B`;
  if (bytes < 1024 ** 2)   return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3)   return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function _formatElapsed(ms) {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = String(totalSec % 60).padStart(2, "0");
  return `${m}:${s}`;
}
