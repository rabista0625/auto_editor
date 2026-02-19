# Auto Editor — ゲーム実況向け無音カット Web アプリ

ゲーム実況動画の無言区間を自動カットするローカル Web アプリです。  
完全ローカル動作・外部 API 不使用・Windows 向け。  
GPU（NVIDIA / AMD / Intel）があれば自動的に GPU エンコードを使用し、処理を高速化します。

---

## 機能

| モード | 向き | 内容 |
|--------|------|------|
| **Mode A** | ✂️ 切り抜き・ショート向き | すべての無音区間を削除 |
| **Mode B** | 🎮 実況本編向き | 指定秒数以上の無音のみ削除（デフォルト・おすすめ） |
| **Mode C** | 🎬 編集済み風動画向き | 短い間は保持・中間は0.3秒に短縮・長い無音は削除 |

### Mode C の詳細ルール（固定）

| 無音の長さ | 処理 |
|-----------|------|
| 0.3秒未満 | そのまま保持（自然な間を残す） |
| 0.3〜1.5秒 | 末尾の0.3秒だけ残して短縮 |
| 1.5秒以上 | 削除 |

---

## 起動方法（2通り）

| 方法 | 向いている人 |
|------|------------|
| **① Docker（推奨）** | 環境構築なしにすぐ使いたい人 |
| **② 直接インストール** | Docker を使わない / GPU エンコードを使いたい人 |

---

## ① Docker で起動（推奨・環境構築不要）

**必要なもの：** [Docker Desktop](https://www.docker.com/products/docker-desktop/) のみ

### 手順

1. **Docker Desktop をインストール** して起動しておく
2. ターミナル（PowerShell / コマンドプロンプト）で `auto_editor` フォルダに移動して実行：

```
cd auto_editor
docker compose up --build
```

3. 初回はイメージのビルドで数分かかります
4. `Application startup complete.` と表示されたらブラウザで http://localhost:8000 を開く

```
初回起動時のログ例:
 => [1/4] FROM docker.io/library/python:3.11-slim   ← ダウンロード中
 => [2/4] RUN apt-get install ffmpeg ...             ← FFmpeg インストール中
 => [3/4] RUN pip install ...                        ← Python パッケージ導入中
 ...
INFO:     Application startup complete.              ← 起動完了
```

> 2回目以降はキャッシュが使われるため数秒で起動します。

### 停止方法

ターミナルで `Ctrl+C` を押すか、別のターミナルで以下を実行します：

```
docker compose down
```

### GPU（NVIDIA）を使いたい場合

Docker でも NVIDIA GPU エンコードを使えますが、追加セットアップが必要です：

1. [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) をインストール
2. `docker-compose.yml` を開き、コメントの指示に従って GPU 設定に切り替える

> ⚠️ Docker での GPU 利用は設定が複雑なため、GPU を使いたい場合は **② 直接インストール** の方が簡単です。

---

## ② 直接インストール

## 必要なもの（インストール一覧）

このアプリを動かすには以下の **2 つ** をインストールする必要があります。

| # | ソフトウェア | 用途 |
|---|------------|------|
| 1 | **Python 3.11 以上** | アプリ本体の実行環境 |
| 2 | **FFmpeg** | 動画の音声抽出・カット・結合処理 |

---

## インストール手順

### 1. Python のインストール

1. https://www.python.org/downloads/ を開く
2. 「Download Python 3.x.x」ボタンをクリックしてインストーラーをダウンロード
3. インストーラーを起動し、**「Add Python to PATH」に必ずチェックを入れてから** Install Now をクリック

   > ⚠️ 「Add Python to PATH」のチェックを忘れると次のステップで動かなくなります

4. インストール完了後、コマンドプロンプト（または PowerShell）を開いて確認：
   ```
   python --version
   ```
   → `Python 3.11.x` のように表示されれば OK

---

### 2. FFmpeg のインストール

1. https://www.gyan.dev/ffmpeg/builds/ を開く
2. 「release builds」の `ffmpeg-release-full.7z` をダウンロード
3. 7-Zip（https://7-zip.org/）などで解凍し、任意のフォルダへ配置  
   例: `C:\ffmpeg`
4. 環境変数 PATH に `C:\ffmpeg\bin` を追加する
   1. スタートメニューで「環境変数」と検索 →「システム環境変数の編集」を開く
   2. 「環境変数」ボタン → 「Path」を選択して「編集」
   3. 「新規」ボタンで `C:\ffmpeg\bin` を追加 → OK を押して閉じる
5. コマンドプロンプトを**再起動**してから確認：
   ```
   ffmpeg -version
   ```
   → `ffmpeg version x.x.x ...` のように表示されれば OK

---

### 3. アプリの依存パッケージをインストール

**コマンドプロンプト または PowerShell** で `auto_editor` フォルダに移動してから実行：

```
pip install -r requirements.txt
```

> ⚠️ Windows 環境では `webrtcvad` のビルドにコンパイラが必要なため、  
> `requirements.txt` では自動的に `webrtcvad-wheels`（ビルド済みバイナリ版）を使用しています。  
> 追加作業は不要です。

---

## 起動方法（直接インストールの場合）

> ℹ️ 以下のコマンドは **コマンドプロンプト** または **PowerShell** で実行してください。  
> Git Bash をお使いの場合は `winpty` を先頭に付けてください（後述）。

**コマンドプロンプト / PowerShell の場合：**

```
cd auto_editor
python -m uvicorn app:app --no-access-log
```

**Git Bash の場合：**

```bash
cd auto_editor
winpty python -m uvicorn app:app --no-access-log
```

ブラウザで http://127.0.0.1:8000 を開く。

> `--no-access-log` を付けると HTTP リクエストの繰り返しログが非表示になり、  
> 処理進捗（「結合中 240/2413 区間完了」など）のログが見やすくなります。  
> 省略しても動作には影響ありません。

> 起動時に FFmpeg が見つからない場合は「2. FFmpeg のインストール」を確認してください。

---

## 使い方

1. 「動画ファイル」欄からカットしたい動画を選択（またはドラッグ＆ドロップ）
2. カットモードを選ぶ（迷ったら **Mode B** のままで OK）
3. 選択したモードに対応したパラメータを必要に応じて調整
4. 「無音カットを開始」ボタンをクリック
5. 処理完了後「ダウンロード」ボタンで保存

---

## パラメータ説明

モードによって画面に表示されるパラメータが異なります。

| パラメータ | デフォルト | 対応モード | 説明 |
|-----------|-----------|-----------|------|
| 無音閾値 (秒) | 2.0 | **B のみ** | この秒数以上の無音を削除 |
| 発話前バッファ (秒) | 0.2 | **A / B** | 発話が始まる直前に残す余白 |
| 発話後バッファ (秒) | 0.3 | **A / B** | 発話が終わった直後に残す余白 |
| VAD 感度 | 2 | **A / B / C** | 0=寛容（ノイズを発話と判定しやすい）〜 3=厳格 |

> Mode C はルールが固定（0.3秒 / 1.5秒）のため、VAD 感度のみ調整できます。

---

## 対応動画形式

`.mp4` `.mov` `.avi` `.mkv` `.webm` `.flv` `.ts` `.m4v`

---

## ファイルの自動削除について

サーバーのディスク容量を圧迫しないよう、処理に使ったファイルは自動で削除されます。

| ファイル | 削除タイミング |
|---------|--------------|
| `input/` アップロードした動画 | 処理完了後すぐに削除 |
| `output/` カット済み動画 | 処理完了から **1時間後** に自動削除 |
| `temp/` 中間ファイル | 処理完了後すぐに削除 |

> ⚠️ 出力動画は処理完了から1時間以内にダウンロードしてください。  
> 1時間を過ぎると自動削除されます。ダウンロードに失敗した場合は再度アップロードして処理してください。

---

## ディレクトリ構成

```
auto_editor/
├── app.py               # FastAPI エントリポイント
├── requirements.txt     # 依存パッケージ一覧
├── README.md            # このファイル
├── Dockerfile           # Docker イメージ定義
├── docker-compose.yml   # Docker Compose 設定
├── .dockerignore        # Docker ビルドから除外するファイル一覧
├── core/
│   ├── ffmpeg_utils.py  # FFmpeg ラッパー
│   ├── vad.py           # 音声区間検出（VAD）
│   ├── modes.py         # カットモードロジック（A/B/C）
│   └── cutter.py        # カット処理パイプライン
├── services/
│   └── job_manager.py   # ジョブ管理
├── templates/
│   └── index.html       # Web UI
├── static/
│   ├── style.css
│   └── script.js
├── input/               # アップロードされた動画（処理完了後に即削除）
├── output/              # 処理済み動画（処理完了から1時間後に自動削除）
├── temp/                # 中間ファイル（処理完了後に即削除）
└── logs/                # ログファイル（自動生成）
```

---

## GPU エンコードについて

起動時に GPU エンコーダーを自動検出し、利用可能なものを使用します。

| GPU | 使用エンコーダー |
|-----|----------------|
| NVIDIA（GeForce / Quadro など） | h264_nvenc |
| AMD（Radeon など） | h264_amf |
| Intel 内蔵グラフィックス | h264_qsv |
| GPU なし / 非対応 | libx264（CPU） |

起動ログで確認できます：

```
GPUエンコード使用: NVIDIA NVENC (h264_nvenc)   ← GPU が使われている
CPUエンコード使用: libx264 (GPUエンコーダーが利用できません)  ← CPU にフォールバック
```

> GPU エンコードは CPU エンコード（libx264）より数倍〜10倍以上高速です。  
> GPU がある場合は適切なドライバーをインストールしておくと自動的に有効になります。

---

## トラブルシューティング

| 症状 | 確認ポイント |
|------|------------|
| `uvicorn: command not found`（Git Bash） | `winpty python -m uvicorn app:app --no-access-log` を使用する |
| `uvicorn` が起動しない | `pip install -r requirements.txt` を実行したか確認 |
| `python` コマンドが動かない | Windows の「アプリ実行エイリアス」で `python.exe` がオンになっていないか確認。または PATH で Python のパスが先頭にあるか確認 |
| 「FFmpeg が見つかりません」エラー | FFmpeg の PATH 設定を確認。コマンドプロンプトで `ffmpeg -version` が動くか確認 |
| アップロードで「非対応の形式」エラー | 対応形式（上記一覧）の動画ファイルか確認 |
| 処理後も無音が残っている | 「無音閾値」を小さく、「VAD 感度」を大きく調整してみる |
| 発話が途切れた | 「発話前/後バッファ」を大きくするか、「VAD 感度」を小さくしてみる |
| GPU があるのに CPU で処理される | GPU ドライバーが最新か確認。起動ログの詳細を確認する |
| ダウンロードできない（1時間以上経過） | 出力ファイルは処理完了から1時間後に自動削除されます。再度アップロードして処理してください |
