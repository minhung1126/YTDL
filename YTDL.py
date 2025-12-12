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
import logging
import io

sys.dont_write_bytecode = True

# --- App Versioning ---
# 在開發環境中，版本號會被設為 "dev"。
# 發布時，版本號會被更新為具體的版本字串，例如 "v2025.09.05"。
__version__ = "v2025.12.12.01"
if os.path.exists('.gitignore'):
    __version__ = "dev"
# --- End App Versioning ---

# --- yt-dlp Versioning ---
YT_DLP_VERSION_CHANNEL = "stable"
YT_DLP_VERSION_TAG = "2025.12.08"
# --- End yt-dlp Versioning ---

# --- Deno Versioning ---
DENO_VERSION = "2.5.4"
# --- End Deno Versioning ---

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

# Validation Regex
YOUTUBE_REGEX = r'(?:https?://)?(?:www\.)?(?:m\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|embed/|v/|shorts/|playlist\?|channel/|c/|user/|@)?[\w\-?=&%]+'

def is_youtube_url(url: str) -> bool:
    """
    Checks if the provided URL is a valid YouTube URL.
    """
    if not url:
        return False
    return bool(re.search(YOUTUBE_REGEX, url, re.IGNORECASE))


def setup_logging():
    """
    Sets up logging to file and console.
    """
    log_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s')
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    logger.addHandler(console_handler)
    
    # Redirect stderr to logging
    class StderrLogger(object):
        def write(self, message):
            if message.strip():
                logging.error(message.strip())
        def flush(self):
            pass
    
    # sys.stderr = StderrLogger() # Optional: Redirect all stderr to log


def report_error(message: str, context: dict = None):
    """
    Logs the error message and sends it to a Discord webhook if configured.
    If a log or traceback is present in the context, it's sent as a file attachment.
    """
    # --- Gather Context Information ---
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USERNAME", "N/A")
    computer_info = f"**Computer:** `{socket.gethostname()}` (`{user}`) | **OS:** `{platform.system()} {platform.release()}` | **Ver:** `{__version__}`"

    full_message = f"{message}"
    log_content = None
    log_key = None

    # --- Identify and Extract Log Content ---
    if context:
        # Find a key that contains a log or traceback
        for key, value in context.items():
            is_log = str(value).startswith("```")
            is_traceback = key == "Traceback"
            if (is_log or is_traceback):
                log_key = key
                if is_log:
                    log_content = re.sub(r'```(.*?)\n|```', '', str(value), flags=re.DOTALL)
                else:  # is_traceback
                    log_content = str(value)
                break  # Found a log, stop searching

    # --- Build Context Message ---
    context_message = ""
    if context:
        temp_context = context.copy()
        if log_key:
            # Replace log in context with a placeholder
            del temp_context[log_key]
            context_message += f"**{log_key}:** See attached `{log_key.replace(' ', '_').lower()}.txt`\n"

        for key, value in temp_context.items():
            context_message += f"**{key}:** `{value}`\n"

    # --- Log to File/Console ---
    logging.error(f"An error occurred:\n{computer_info}\n{context_message.replace('**', '').replace('`', '')}{full_message}")
    if log_content:
        logging.error(f"--- Full {log_key} Log ---\n{log_content}")

    # --- Send to Discord ---
    if DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in DISCORD_WEBHOOK:
        try:
            final_report = f"🚨 **YTDL Error Report:**\n{computer_info}\n{context_message}**Error:**\n```\n{full_message}\n```"
            discord_payload = {"content": final_report}

            if log_content:
                log_filename = f"{log_key.replace(' ', '_').lower()}.txt"
                log_stream = io.BytesIO(log_content.encode('utf-8'))
                files = {"file": (log_filename, log_stream, "text/plain")}
                response = requests.post(DISCORD_WEBHOOK, data={
                                            "payload_json": json.dumps(discord_payload)}, files=files, timeout=10)
            else:
                response = requests.post(
                    DISCORD_WEBHOOK, json=discord_payload, timeout=10)

            response.raise_for_status()

        except Exception as e:
            logging.critical(f"Failed to send error report to Discord: {e}")


def send_discord_notification(message: str):
    """
    發送一個簡單的通知到 Discord Webhook (如果已設定)。
    """
    if DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in DISCORD_WEBHOOK:
        try:
            discord_payload = {"content": f"ℹ️ **YTDL 通知:**\n{message}"}
            requests.post(DISCORD_WEBHOOK, json=discord_payload, timeout=10)
        except Exception as e:
            logging.warning(f"發送通知到 Discord 失敗: {e}")


def handle_updates_and_cleanup(caller_script: str):
    """
    處理程式自身的更新、yt-dlp 的版本檢查以及相關的清理工作。
    此函數不應在 dev 版本中被呼叫。
    """
    # 1. 檢查 YTDL 本身的更新
    logging.info(f"目前版本: {__version__}")
    try:
        repo = "minhung1126/YTDL"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        latest_version = response.json()["tag_name"]
        if latest_version != __version__:
            logging.info(f"發現新版本: {latest_version}。開始更新...")
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
            logging.info("您目前使用的是最新版本。" )
    except Exception:
        report_error(traceback.format_exc())

    # 2. 檢查並刪除 self_update.py (如果存在)
    updater_script_name = "self_update.py"
    updater_script_path = os.path.join(os.getcwd(), updater_script_name)
    if os.path.exists(updater_script_path):
        try:
            os.remove(updater_script_path)
            logging.info(f"已刪除舊的 {updater_script_name}")
        except Exception as e:
            logging.error(f"無法刪除 {updater_script_name}: {e}")


def _run_subprocess(args: list, context: dict = None):
    """Helper to run a subprocess and stream its output, hiding debug messages."""
    if context is None:
        context = {}
    try:
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')

        stdout_lines = []
        stderr_lines = []

        def stream_reader(stream, line_list, output_file):
            for line in iter(stream.readline, ''):
                line_list.append(line)
                if '[debug]' not in line:
                    print(line.strip(), file=output_file)
            stream.close()

        import threading
        stdout_thread = threading.Thread(
            target=stream_reader, args=(process.stdout, stdout_lines, sys.stdout))
        stderr_thread = threading.Thread(
            target=stream_reader, args=(process.stderr, stderr_lines, sys.stderr))

        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()

        process.wait()

        full_log = "".join(stdout_lines) + "".join(stderr_lines)
        return process.returncode, full_log 
    except Exception:
        report_error(f"An unexpected error occurred during subprocess execution.", context={
                     "Traceback": traceback.format_exc(), **context})
        return -1, traceback.format_exc()


def extract_yt_dlp_error(log_text: str) -> str:
    """
    Extracts the main error message from the yt-dlp log.
    Returns the first line starting with 'ERROR:', or the last non-empty line.
    """
    if not log_text:
        return "Unknown Error (No Log)"
    
    # Remove ANSI color codes
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    
    for line in log_text.splitlines():
        clean_line = ansi_escape.sub('', line).strip()
        if clean_line.startswith("ERROR:"):
            return clean_line
            
    # Fallback: return the last non-empty line
    lines = [ansi_escape.sub('', l).strip() for l in log_text.splitlines() if l.strip()]
    if lines:
        return lines[-1]
    return "Unknown Error"


class Video:
    def __init__(self, meta_filepath: str):
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"
        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        
        # Check for playlist or channel to set the correct template
        is_playlist = self.meta and 'playlist' in self.meta
        
        webpage_url = self.meta.get("webpage_url", "")
        parsed_url = urlparse(webpage_url)
        is_channel = '/channel/' in parsed_url.path or \
                     '/c/' in parsed_url.path or \
                     parsed_url.path.startswith('/@')
        
        self.template = PLAYLIST_TEMPLATE if is_playlist or is_channel else VIDEO_TEMPLATE
        
        self.url = self.meta.get("webpage_url", "")
        if self.meta.get("playlist_id"):
            self.url += f"&list={self.meta.get('playlist_id')}"

    def _read_meta(self):
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                return json.loads(f.read())
        except Exception:
            report_error(f"Failed to read or parse meta file: {self.meta_filepath}", context={
                         "Traceback": traceback.format_exc()})
            return {}

    def download(self):
        logging.info(f"--- Downloading: {self.meta.get('title', 'N/A')} ---")
        context = {"Video Title": self.meta.get(
            'title', 'N/A'), "Video URL": self.meta.get('webpage_url', 'N/A')}
        try:
            args = [
                EXECUTABLE,
                '-f', 'bv+ba',
                '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
                '--embed-subs',
                '--sub-langs',                 'all,-live_chat',
                '--embed-thumbnail',
                '--embed-metadata',
                '--merge-output-format', 'mkv',
                '--remux-video', 'mkv',
                '--encoding', 'utf-8',
                '--concurrent-fragments', CONCURRENT_FRAGMENTS,
                '--progress-delta', PROGRESS_BAR_SECONDS,
                '-o', self.template,
                '--load-info-json', self.meta_filepath,
                '--verbose'
                ]

            returncode, full_log = _run_subprocess(args, context)

            if returncode == 0:
                os.remove(self.meta_filepath)
                return True, None

            # If download failed, report error
            error_message = f"Download failed. yt-dlp exited with code {returncode}."
            extracted_error = extract_yt_dlp_error(full_log)
            
            context['Terminal Log'] = f"```\n{full_log}\n```"
            report_error(error_message, context=context)
            
            return False, extracted_error

        except Exception as e:
            report_error(f"An unexpected error occurred during download.", context={
                         "Traceback": traceback.format_exc(), **context})
            return False, str(e)

def dl_meta_from_url(url: str):
    context = {"URL": url}
    try:
        if not os.path.exists(META_DIR):
            os.makedirs(META_DIR)
        args = [
            EXECUTABLE,
            '--no-download',
            '--no-write-playlist-metafiles', '-o',
            os.path.join(META_DIR, f"%(title)s.%(id)s"),
            '--write-info-json',
            '--encoding', 'utf-8',
            '--verbose',
            '--concurrent-fragments', CONCURRENT_FRAGMENTS,
            url
        ]
        parsed_url = urlparse(url)
        is_playlist = '/playlist' in parsed_url.path
        is_channel = '/channel/' in parsed_url.path or '/c/' in parsed_url.path or parsed_url.path.startswith('/@')

        if not is_playlist and not is_channel:
            args.append('--no-playlist')

        returncode, full_log = _run_subprocess(args, context)

        if returncode == 0:
            return True, None

        # If download failed, report error
        context_with_output = {
            **context, "Terminal Output": f"```\n{full_log}\n```"}
        report_error(
            f"Failed to download metadata. yt-dlp exited with code {returncode}",
            context=context_with_output
        )
        return False, extract_yt_dlp_error(full_log)

    except Exception as e:
        # 捕獲其他可能的錯誤，例如 FileNotFoundError
        report_error(f"An unexpected error occurred while trying to get metadata.", context={
            "URL": url,
            "Error": str(e),
            "Traceback": traceback.format_exc()
        })
        return False, str(e)

def load_videos_from_meta() -> list[Video]:
    if not os.path.isdir(META_DIR):
        return []
    return [Video(os.path.join(META_DIR, f)) for f in os.listdir(META_DIR)]


def self_update_legacy():
    logging.info("Manual update started...")


def parse_user_action():
    if os.path.isdir(META_DIR) and os.listdir(META_DIR):
        resp = input("發現暫存檔。是否繼續下載上次的內容？(Y/N) | Meta files found. Continue downloading previous session?(Y/N) ").lower()
        if resp == 'y':
            return
        elif resp == 'n':
            shutil.rmtree(META_DIR)
        else:
            logging.warning("輸入無效。程式結束。 | Invalid input. Exiting.")
            sys.exit(1)
    while True:
        resp = input("請輸入影片、播放清單或頻道網址 (輸入 'exit' 離開，'update' 手動更新): | Enter a video, playlist, or channel URL (or type 'exit' to quit, 'update' for manual update): ")
        if resp.lower() == 'exit':
            sys.exit(0)
        if resp.lower() == "update":
            self_update_legacy()
            continue
        # Validate URL using regex
        if is_youtube_url(resp):
            success, error = dl_meta_from_url(resp)
            if not success:
                print(f"ERROR: {error}")
            break
        else:
            logging.warning("無效的網址。請輸入有效的 YouTube 網址。 | Invalid URL. Please enter a valid YouTube URL.")

def cleanup_empty_meta_dir():
    if os.path.isdir(META_DIR) and not os.listdir(META_DIR):
        try:
            os.rmdir(META_DIR)
            logging.info("Empty meta directory deleted.")
        except OSError as e:
            report_error(f"Error deleting empty meta directory: {META_DIR}", context= {
                         "Error": str(e)})


def initialize_app(caller_script_name: str):
    """
    檢查版本並處理更新（如果不是開發模式）。
    """
    if __version__ != "dev":
        handle_updates_and_cleanup(caller_script_name)
    else:
        logging.info("開發版本，跳過更新與清理程序。")


def main():
    setup_logging()
    try:
        initialize_app(sys.argv[0])
        while True:
            parse_user_action()
            videos = load_videos_from_meta()
            if not videos:
                logging.info("No videos to download.")
                continue
            for vid in videos:
                success, error = vid.download()
                if not success:
                    logging.error(f"Download Error: {error}")
                    # In CLI mode, we just log it to stderr (which setup_logging catches)
                    # You might want to print forcibly if you want the user to see it immediately
                    print(f"ERROR: {error}")

            cleanup_empty_meta_dir()

            logging.info("\nAll downloads complete. You can enter another URL or type 'exit'.")
    except SystemExit:
        pass
    except Exception:
        report_error(f"A critical error occurred in the main loop.",
                     context={"Traceback": traceback.format_exc()})
        logging.exception("Critical error in main loop")
        input("Press ENTER to exit.")


if __name__ == "__main__":
    main()
