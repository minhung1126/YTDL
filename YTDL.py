import os
import json
import shutil
import subprocess
import re
from urllib.parse import urlparse, parse_qs
import sys
import traceback
import platform
import socket
import base64

# --- Versioning ---
# 在開發環境中，版本號會被設為 "dev"。
# 發布時，版本號會被更新為具體的版本字串，例如 "v2025.09.05"。
__version__ = "v2025.09.14"
if os.path.exists('.gitignore'):
    __version__ = "dev"
# --- End Versioning ---

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

#! --- Configuration ---
# Webhook URL 已使用 Base64 編碼儲存，以避免明文暴露。
DISCORD_WEBHOOK_ENCODED = "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTQxMzc0NjU0MTY4MzkzNzM5MC9tWm9ZRy1mS211cnhFMFhPNWhjUmhITzBJWEREaWgyeDF2QnJ4dEFzQ0VTdEZ3M0FFTnNYamt3djQzbWFoaHhOQzFybw=="
DISCORD_WEBHOOK = base64.b64decode(DISCORD_WEBHOOK_ENCODED).decode('utf-8') if DISCORD_WEBHOOK_ENCODED else ""
#! ---------------------

META_DIR = os.path.join(os.getcwd(), 'meta')
# yt-dlp Environment
EXECUTABLE = 'yt-dlp'
CONCURRENT_FRAGMENTS = "8"
PROGRESS_BAR_SECONDS = "2"


def report_error(message: str, context: dict = None):
    """
    Prints the error message to the console and sends it to a Discord webhook if configured,
    including computer and execution context.
    """
    # --- Gather Context Information ---
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USERNAME", "N/A")
    computer_info = f"**Computer:** `{socket.gethostname()}` (`{user}`) | **OS:** `{platform.system()} {platform.release()}` | **Ver:** `{__version__}`"

    # --- Build Message ---
    full_message = f"{message}"
    context_message = ""
    if context:
        for key, value in context.items():
            context_message += f"**{key}:** `{value}`\n"

    # --- Print to Console ---
    print(
        f"[ERROR] An error occurred:\n{computer_info}\n{context_message}{full_message}", file=sys.stderr)

    # --- Send to Discord ---
    if DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in DISCORD_WEBHOOK:
        try:
            discord_payload = {
                "content": f"🚨 **YTDL Error Report:**\n{computer_info}\n{context_message}**Error:**\n```\n{full_message[:1500]}\n```"}
            requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=10)
        except Exception as e:
            print(
                f"[CRITICAL] Failed to send error report to Discord: {e}", file=sys.stderr)


def send_discord_notification(message: str):
    """
    發送一個簡單的通知到 Discord Webhook (如果已設定)。
    """
    if DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in DISCORD_WEBHOOK:
        try:
            discord_payload = {"content": f"ℹ️ **YTDL 通知:**\n{message}"}
            requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=10)
        except Exception as e:
            print(f"[警告] 發送通知到 Discord 失敗: {e}", file=sys.stderr)


def check_yt_dlp_update():
    """
    檢查是否有新版本的 yt-dlp 可用（不更新），並在需要時發送通知。
    """
    print("正在檢查 yt-dlp 是否有新版本...")
    try:
        # 1. 取得本機目前版本
        local_version_proc = subprocess.run([EXECUTABLE, '--version'], capture_output=True, text=True, check=True, encoding='utf-8')
        local_version = local_version_proc.stdout.strip()

        # 2. 從 GitHub 取得最新版本
        repo = "yt-dlp/yt-dlp"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        release_data = response.json()
        latest_version = release_data["tag_name"]
        release_url = release_data["html_url"]

        # 3. 比較並通知
        print(f"本機 yt-dlp 版本: {local_version}, 最新版本: {latest_version}")
        if local_version != latest_version:
            print(f"發現新的 yt-dlp 版本: {latest_version}")
            send_discord_notification(f"發現新的 `yt-dlp` 版本！\n- 目前版本: `{local_version}`\n- 最新版本: `{latest_version}`\n- Release URL: {release_url}")
        else:
            print("您的 yt-dlp 已是最新版本。")

    except FileNotFoundError:
        print(f"[警告] 找不到 '{EXECUTABLE}'。無法檢查 yt-dlp 更新。", file=sys.stderr)
    except Exception:
        report_error("檢查 yt-dlp 版本失敗。", context={"Traceback": traceback.format_exc()})


def handle_updates_and_cleanup(caller_script: str):
    """
    處理程式自身的更新、yt-dlp 的版本檢查以及相關的清理工作。
    此函數不應在 dev 版本中被呼叫。
    """
    # 1. 檢查 YTDL 本身的更新
    print(f"目前版本: {__version__}")
    try:
        repo = "minhung1126/YTDL"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        latest_version = response.json()["tag_name"]
        if latest_version != __version__:
            print(f"發現新版本: {latest_version}。開始更新...")
            base_url = f"https://raw.githubusercontent.com/{repo}/main/"
            updater_script_name = "self_update.py"
            resp = requests.get(f"{base_url}{updater_script_name}")
            if not resp.ok:
                report_error(
                    f"下載更新腳本失敗: {updater_script_name}。狀態碼: {resp.status_code}")
                return
            with open(updater_script_name, 'wb') as f:
                f.write(resp.content)
            subprocess.Popen(
                [sys.executable, updater_script_name, caller_script, DISCORD_WEBHOOK])
            sys.exit(0)
        else:
            print("您目前使用的是最新版本。" )
    except Exception:
        report_error(traceback.format_exc())

    # 2. 順便檢查 yt-dlp 的更新
    check_yt_dlp_update()

    # 3. 檢查並刪除 self_update.py (如果存在)
    updater_script_name = "self_update.py"
    updater_script_path = os.path.join(os.getcwd(), updater_script_name)
    if os.path.exists(updater_script_path):
        try:
            os.remove(updater_script_path)
            print(f"已刪除舊的 {updater_script_name}")
        except Exception as e:
            print(f"無法刪除 {updater_script_name}: {e}", file=sys.stderr)


class Video:
    def __init__(self, meta_filepath: str):
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"
        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.template = PLAYLIST_TEMPLATE if self.meta and 'playlist' in self.meta else VIDEO_TEMPLATE
        self.url = self.meta.get("webpage_url", "")
        if self.meta.get("playlist_id"):
            self.url += f"&list={self.meta.get('playlist_id')}"

    def _read_meta(self):
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                return json.loads(f.read())
        except Exception:
            report_error(f"Failed to read or parse meta file: {self.meta_filepath}", context= {
                         "Traceback": traceback.format_exc()})
            return {}

    def download(self):
        print(f"--- Downloading: {self.meta.get('title', 'N/A')} ---")
        context = {"Video Title": self.meta.get(
            'title', 'N/A'), "Video URL": self.meta.get('webpage_url', 'N/A')}
        try:
            args = [
                EXECUTABLE,
                '--verbose',
                '-f', 'bv+ba',
                '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
                '--embed-subs',
                '--sub-langs', 'all,-live_chat',
                '--no-playlist',
                '--embed-thumbnail',
                '--embed-metadata',
                '--merge-output-format', 'mkv',
                '--remux-video', 'mkv',
                '--encoding', 'utf-8',
                '--concurrent-fragments', CONCURRENT_FRAGMENTS,
                '--progress-delta', PROGRESS_BAR_SECONDS,
                '-o', self.template,
                '--load-info-json', self.meta_filepath
            ]
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                print(line.strip())
            process.wait()
            if process.returncode != 0:
                report_error(
                    f"Download failed. yt-dlp exited with code {process.returncode}", context=context)
                return False

            try:
                os.remove(self.meta_filepath)
                print(
                    f"Metafile for '{self.meta.get('title', 'N/A')}' deleted.")
            except OSError as e:
                report_error(f"CRITICAL: Failed to delete metafile {self.meta_filepath} after successful download.", context= {
                             "Error": str(e)})
                return False
            return True
        except Exception:
            report_error(f"An unexpected error occurred during download.", context= {
                         "Traceback": traceback.format_exc(), **context})
            return False

def dl_meta_from_url(url: str):
    context = {"URL": url}
    try:
        if not os.path.exists(META_DIR):
            os.makedirs(META_DIR)
        args = [EXECUTABLE, '--verbose', '--no-download', '--no-write-playlist-metafiles', '-o',
                os.path.join(META_DIR, f"%(title)s.%(id)s"), '--write-info-json', '--encoding', 'utf-8', url]
        if '/playlist' not in urlparse(url).path:
            args.append('--no-playlist')
        subprocess.run(args, check=True)
    except Exception:
        report_error(f"Failed to download metadata.", context= {
                     "Traceback": traceback.format_exc(), **context})

def load_videos_from_meta() -> list[Video]:
    if not os.path.isdir(META_DIR):
        return []
    return [Video(os.path.join(META_DIR, f)) for f in os.listdir(META_DIR)]


def self_update_legacy():
    print("Manual update started...")

def parse_user_action():
    if os.path.isdir(META_DIR) and os.listdir(META_DIR):
        resp = input("Meta files found. Continue downloading previous session?(Y/N) ").lower()
        if resp == 'y':
            return
        elif resp == 'n':
            shutil.rmtree(META_DIR)
        else:
            print("Invalid input. Exiting.")
            sys.exit(1)
    while True:
        resp = input("Enter URL (or type 'exit' to quit, 'update' for manual update): ")
        if resp.lower() == 'exit':
            sys.exit(0)
        if resp.lower() == "update":
            self_update_legacy()
            continue
        if "youtube.com" in resp or "youtu.be" in resp:
            dl_meta_from_url(resp)
            break
        else:
            print("Invalid URL. Please enter a valid YouTube URL.")

def cleanup():
    if os.path.isdir(META_DIR) and not os.listdir(META_DIR):
        try:
            os.rmdir(META_DIR)
            print("Empty meta directory deleted.")
        except OSError as e:
            report_error(f"Error deleting empty meta directory: {META_DIR}", context= {
                         "Error": str(e)})

def main():
    try:
        if __version__ != "dev":
            handle_updates_and_cleanup(sys.argv[0])
        else:
            print("開發版本，跳過更新與清理程序。" )
        while True:
            parse_user_action()
            videos = load_videos_from_meta()
            if not videos:
                print("No videos to download.")
                continue
            for vid in videos:
                vid.download()

            cleanup()

            print("\nAll downloads complete. You can enter another URL or type 'exit'.")
    except SystemExit:
        pass
    except Exception:
        report_error(f"A critical error occurred in the main loop.",
                     context={"Traceback": traceback.format_exc()})
        input("Press ENTER to exit.")


if __name__ == "__main__":
    main()
