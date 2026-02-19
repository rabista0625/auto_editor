FROM python:3.11-slim

# FFmpeg をインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存パッケージを先にインストール（コード変更時のキャッシュ再利用のため）
# webrtcvad-wheels は Windows / Linux 両対応のビルド済みバイナリ版のため
# コンパイラ不要でインストールできる
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY . .

# 実行時に必要なディレクトリを作成
RUN mkdir -p input output temp logs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log"]
