import os
import json
import shutil
import subprocess
import re
import threading
from urllib.parse import urlparse
import sys
import traceback
import platform
import socket
import base64
import logging
import io
import time
from typing import Tuple, List, Optional, Dict, Any

sys.dont_write_bytecode = True

# --- App Versioning ---
__version__ = "v2026.02.18.07"
if os.path.exists('.gitignore'):
    __version__ = "dev"
# ----------------------

class DependencyManager:
    @staticmethod
    def check_and_install(package_name: str, import_name: Optional[str] = None):
        """Checks if a package is installed, if not, installs it."""
        if import_name is None:
            import_name = package_name
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installing missing dependency: {package_name}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"{package_name} installed successfully.")
            # Re-import to ensure it's available in the current session if needed by caller
            # (Though usually caller does the import after calling this)

# Initial dependency check
DependencyManager.check_and_install("requests")
import requests

def _http_get_with_retry(url, max_retries=3, **kwargs):
    """GET request with exponential backoff retry."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_exc

class Config:
    # yt-dlp Versioning
    YT_DLP_VERSION_CHANNEL = "nightly"
    # YT_DLP_VERSION_TAG is no longer used; always checks latest nightly
    
    # Deno Versioning
    DENO_VERSION = "2.5.4"

    # FFmpeg Configuration
    FFMPEG_VERSION_TAG = "20260218"
    
    _yt_dlp_path = shutil.which('yt-dlp')
    _yt_dlp_dir = os.path.dirname(_yt_dlp_path) if _yt_dlp_path else None
    
    # Try to find ffmpeg/ffprobe next to yt-dlp first
    FFMPEG_BINARY = None
    if _yt_dlp_dir:
        _local_ffmpeg = os.path.join(_yt_dlp_dir, 'yt-dlp-ffmpeg.exe')
        if os.path.exists(_local_ffmpeg):
            FFMPEG_BINARY = _local_ffmpeg
        else:
            print("CRITICAL: FFmpeg binary not found in yt-dlp directory.")
            print("Please perform a manual update or reinstall to fetch missing dependencies.")
    
    # We do NOT fallback to PATH as per user request
    
    FFPROBE_BINARY = None
    if _yt_dlp_dir:
        _local_ffprobe = os.path.join(_yt_dlp_dir, 'yt-dlp-ffprobe.exe')
        if os.path.exists(_local_ffprobe):
            FFPROBE_BINARY = _local_ffprobe
    
    # We do NOT fallback to PATH as per user request

    # Discord Webhook
    _DISCORD_WEBHOOK_ENCODED = "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTQxMzc0NjU0MTY4MzkzNzM5MC9tWm9ZRy1mS211cnhFMFhPNWhjUmhITzBJWEREaWgyeDF2QnJ4dEFzQ0VTdEZ3M0FFTnNYamt3djQzbWFoaHhOQzFybw=="
    DISCORD_WEBHOOK = base64.b64decode(_DISCORD_WEBHOOK_ENCODED).decode('utf-8') if _DISCORD_WEBHOOK_ENCODED else ""

    # Paths and Environment
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    META_DIR = os.path.join(_APP_DIR, 'meta')
    EXECUTABLE = 'yt-dlp'
    CONCURRENT_FRAGMENTS = "2"
    PROGRESS_BAR_SECONDS = "2"

    # Regex
    YOUTUBE_REGEX = r'(?:https?://)?(?:www\.)?(?:m\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|embed/|v/|shorts/|playlist\?|channel/|c/|user/|@)?[\w\-?=&%]+'

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        if not url:
            return False
        return bool(re.search(Config.YOUTUBE_REGEX, url, re.IGNORECASE))

    @staticmethod
    def is_playlist_or_channel_url(url: str) -> bool:
        """Check if a URL points to a playlist or channel."""
        parsed = urlparse(url)
        return '/playlist' in parsed.path or '/channel/' in parsed.path or '/c/' in parsed.path or parsed.path.startswith('/@')

class YTDLError(Exception):
    """Base class for YTDL exceptions."""
    pass

class DownloadError(YTDLError):
    """Raised when download or metadata fetching fails."""
    pass

class PrivateVideoError(DownloadError):
    """Raised when video is private."""
    pass

class VideoUnavailableError(DownloadError):
    """Raised when video is 404/deleted."""
    pass

class AgeRestrictedError(DownloadError):
    """Raised when video requires age verification."""
    pass

class PremiumRequiredError(DownloadError):
    """Raised when video requires membership."""
    pass

class MetadataError(YTDLError):
    """Raised when metadata file operations fail."""
    pass

class UpdateError(YTDLError):
    """Raised when self-update fails."""
    pass

class SubprocessError(YTDLError):
    """Raised when a subprocess execution fails unexpectedly."""
    pass

class Logger:
    @staticmethod
    def setup():
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        # Clear existing handlers to avoid duplicates if setup is called multiple times
        if logger.hasHandlers():
            logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)

    @staticmethod
    def _get_system_info() -> str:
        try:
            user = os.getlogin()
        except OSError:
            user = os.environ.get("USERNAME", "N/A")
        return f"**Computer:** `{socket.gethostname()}` (`{user}`) | **OS:** `{platform.system()} {platform.release()}` | **Ver:** `{__version__}`"

    @staticmethod
    def report_error(message: str, context: dict = None):
        if context is None:
            context = {}
        
        computer_info = Logger._get_system_info()
        full_message = f"{message}"
        log_content = None
        log_key = None
        error_type = "Generic Error"

        # Check for Exception object in context to determine Error Type
        if "Exception" in context and isinstance(context["Exception"], Exception):
            error_type = type(context["Exception"]).__name__

        # Extract log/traceback for attachment
        for key, value in context.items():
            is_log = str(value).startswith("```")
            is_traceback = key == "Traceback"
            if is_log or is_traceback:
                log_key = key
                if is_log:
                    log_content = re.sub(r'```(.*?)\n|```', '', str(value), flags=re.DOTALL)
                else: 
                    log_content = str(value)
                break

        context_message = ""
        temp_context = context.copy()
        if log_key:
            del temp_context[log_key]
            context_message += f"**{log_key}:** See attached `{log_key.replace(' ', '_').lower()}.txt`\n"
        
        if "Exception" in temp_context:
             # Don't print the raw exception object in the message body if it's just repeating
             del temp_context["Exception"]

        for key, value in temp_context.items():
            context_message += f"**{key}:** `{value}`\n"

        # Local log
        logging.error(f"An error occurred ({error_type}):\n{computer_info}\n{context_message.replace('**', '').replace('`', '')}{full_message}")
        if log_content:
            logging.error(f"--- Full {log_key} Log ---\n{log_content}")

        # Discord Notification
        if Config.DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in Config.DISCORD_WEBHOOK:
            try:
                final_report = f"🚨 **YTDL Error Report:**\n{computer_info}\n**Error Type:** `{error_type}`\n{context_message}**Error:**\n```\n{full_message}\n```"
                discord_payload = {"content": final_report}

                if log_content:
                    log_filename = f"{log_key.replace(' ', '_').lower()}.txt"
                    log_stream = io.BytesIO(log_content.encode('utf-8'))
                    files = {"file": (log_filename, log_stream, "text/plain")}
                    requests.post(Config.DISCORD_WEBHOOK, data={"payload_json": json.dumps(discord_payload)}, files=files, timeout=10)
                else:
                    requests.post(Config.DISCORD_WEBHOOK, json=discord_payload, timeout=10)
            except Exception as e:
                logging.critical(f"Failed to send error report to Discord: {e}")

class SubprocessRunner:
    @staticmethod
    def run(args: list, context: dict = None) -> Tuple[int, str]:
        if context is None:
            context = {}
        try:
            # Using Popen to stream output (removing [debug] lines if needed)
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')

            stdout_lines = []
            stderr_lines = []

            def stream_reader(stream, line_list, output_file):
                for line in iter(stream.readline, ''):
                    line_list.append(line)
                    if '[debug]' not in line:
                         # Print to console for user feedback
                        print(line.strip(), file=output_file)
                stream.close()

            stdout_thread = threading.Thread(target=stream_reader, args=(process.stdout, stdout_lines, sys.stdout))
            stderr_thread = threading.Thread(target=stream_reader, args=(process.stderr, stderr_lines, sys.stderr))

            stdout_thread.start()
            stderr_thread.start()
            stdout_thread.join()
            stderr_thread.join()
            process.wait()

            full_log = "".join(stdout_lines) + "".join(stderr_lines)
            return process.returncode, full_log
        except FileNotFoundError:
            error_msg = f"Executable not found: {args[0] if args else 'N/A'}. Ensure it is installed and in PATH."
            Logger.report_error(error_msg, context={
                         "Exception": SubprocessError(error_msg), **context})
            return -1, error_msg
        except Exception as e:
            Logger.report_error(f"An unexpected error occurred during subprocess execution.", context={
                         "Traceback": traceback.format_exc(), "Exception": SubprocessError(str(e)), **context})
            return -1, traceback.format_exc()

    @staticmethod
    def extract_yt_dlp_error(log_text: str) -> str:
        if not log_text:
            return "Unknown Error (No Log)"
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        for line in log_text.splitlines():
            clean_line = ansi_escape.sub('', line).strip()
            if clean_line.startswith("ERROR:"):
                return clean_line
        lines = [ansi_escape.sub('', l).strip() for l in log_text.splitlines() if l.strip()]
        return lines[-1] if lines else "Unknown Error"

class Video:
    def __init__(self, meta_filepath: str):
        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.is_valid = bool(self.meta)
        
        self.webpage_url = self.meta.get("webpage_url", "")
        self.title = self.meta.get("title", "N/A")
        
    def _read_meta(self) -> dict:
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            Logger.report_error(f"Failed to read or parse meta file: {self.meta_filepath}", context={
                         "Traceback": traceback.format_exc(), "Exception": MetadataError(str(e))})
            return {}

    def get_download_args(self) -> list:
        # Determine template based on content type
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"
        
        is_playlist = 'playlist' in self.meta or Config.is_playlist_or_channel_url(self.webpage_url)
        template = PLAYLIST_TEMPLATE if is_playlist else VIDEO_TEMPLATE
        
        args = [
            Config.EXECUTABLE,
            '-f', 'bv+ba',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            '--embed-subs', '--sub-langs', 'all,-live_chat',
            '--embed-thumbnail', '--embed-metadata',
            '--merge-output-format', 'mkv', '--remux-video', 'mkv',
            '--encoding', 'utf-8',
            '--concurrent-fragments', Config.CONCURRENT_FRAGMENTS,
            '--progress-delta', Config.PROGRESS_BAR_SECONDS,
            '-o', template,
            '--load-info-json', self.meta_filepath,
            '--verbose'
        ]

        if Config.FFMPEG_BINARY:
            args.extend(['--ffmpeg-location', Config.FFMPEG_BINARY])
        
        return args

class YTDLManager:
    @staticmethod
    def _detect_specific_error(log_text: str) -> Optional[YTDLError]:
        if not log_text:
            return None
        
        if "Private video" in log_text:
            return PrivateVideoError("Video is private.")
        if "Video unavailable" in log_text or "404 Not Found" in log_text:
            return VideoUnavailableError("Video is unavailable or not found.")
        if "Sign in to confirm your age" in log_text:
            return AgeRestrictedError("Video is age-restricted.")
        if "members-only" in log_text or "join this channel" in log_text:
            return PremiumRequiredError("Video requires membership.")
        
        return None

    @staticmethod
    def dl_meta_from_url(url: str) -> Tuple[bool, Optional[str]]:
        context = {"URL": url}
        try:
            if not os.path.exists(Config.META_DIR):
                os.makedirs(Config.META_DIR)
            
            args = [
                Config.EXECUTABLE,
                '--no-download',
                '--no-write-playlist-metafiles', '-o',
                os.path.join(Config.META_DIR, f"%(title)s.%(id)s"),
                '--write-info-json', '--encoding', 'utf-8', '--verbose',
                '--concurrent-fragments', Config.CONCURRENT_FRAGMENTS,
                url
            ]
            
            if not Config.is_playlist_or_channel_url(url):
                args.append('--no-playlist')

            returncode, full_log = SubprocessRunner.run(args, context)

            if returncode == 0:
                return True, None

            context["Terminal Output"] = f"```\n{full_log}\n```"
            error_msg = f"Failed to download metadata. yt-dlp exited with code {returncode}"
            
            specific_error = YTDLManager._detect_specific_error(full_log)
            if specific_error:
                exception_to_report = specific_error
                error_msg = str(specific_error)
            else:
                exception_to_report = DownloadError(error_msg)

            Logger.report_error(error_msg, context={**context, "Exception": exception_to_report})
            return False, SubprocessRunner.extract_yt_dlp_error(full_log)

        except Exception as e:
            Logger.report_error(f"Error fetching metadata.", context={"URL": url, "Error": str(e), "Traceback": traceback.format_exc(), "Exception": DownloadError(str(e))})
            return False, str(e)

    @staticmethod
    def load_videos() -> List[Video]:
        if not os.path.isdir(Config.META_DIR):
            return []
        videos = []
        for f in os.listdir(Config.META_DIR):
            if not f.endswith('.json'):
                continue
            v = Video(os.path.join(Config.META_DIR, f))
            if v.is_valid:
                videos.append(v)
        return videos

    @staticmethod
    def download_video(video: Video) -> Tuple[bool, Optional[str]]:
        logging.info(f"--- Downloading: {video.title} ---")
        context = {"Video Title": video.title, "Video URL": video.webpage_url}
        try:
            args = video.get_download_args()
            returncode, full_log = SubprocessRunner.run(args, context)

            if returncode == 0:
                os.remove(video.meta_filepath)
                return True, None
            
            error_message = f"Download failed. yt-dlp exited with code {returncode}."
            extracted_error = SubprocessRunner.extract_yt_dlp_error(full_log)
            context['Terminal Log'] = f"```\n{full_log}\n```"
            
            specific_error = YTDLManager._detect_specific_error(full_log)
            if specific_error:
                exception_to_report = specific_error
                error_message = str(specific_error)
            else:
                exception_to_report = DownloadError(error_message)

            Logger.report_error(error_message, context={**context, "Exception": exception_to_report})
            return False, extracted_error

        except Exception as e:
            Logger.report_error(f"Unexpected error during download.", context={"Traceback": traceback.format_exc(), "Exception": DownloadError(str(e)), **context})
            return False, str(e)

    @staticmethod
    def cleanup_meta():
        if os.path.isdir(Config.META_DIR) and not os.listdir(Config.META_DIR):
            try:
                os.rmdir(Config.META_DIR)
                logging.info("Empty meta directory deleted.")
            except OSError as e:
                Logger.report_error(f"Error deleting empty meta directory.", context={"Error": str(e), "Exception": MetadataError(str(e))})

    @staticmethod
    def update_self():
        """Checks for updates and updates if necessary. (Simplified logic)"""
        if __version__ == "dev":
            logging.info("Dev version, skipping update check.")
            return

        logging.info(f"Current version: {__version__}")
        try:
            repo = "minhung1126/YTDL"
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            response = _http_get_with_retry(api_url, timeout=5)
            latest_version = response.json()["tag_name"]
            
            if latest_version != __version__:
                logging.info(f"New version found: {latest_version}. Updating...")
                updater_script_name = "self_update.py"
                base_url = f"https://raw.githubusercontent.com/{repo}/main/"
                resp = _http_get_with_retry(f"{base_url}{updater_script_name}", timeout=15)
                with open(updater_script_name, 'wb') as f:
                    f.write(resp.content)
                subprocess.Popen([sys.executable, updater_script_name, os.path.abspath(sys.argv[0]), Config.DISCORD_WEBHOOK])
                sys.exit(0)
            else:
                logging.info("You are using the latest version.")
                
            # Cleanup old updater
            if os.path.exists("self_update.py"):
                os.remove("self_update.py")
                
        except Exception:
            Logger.report_error(traceback.format_exc(), context={"Exception": UpdateError("Self-update failed")})

    @staticmethod
    def update_yt_dlp():
        """Checks for yt-dlp updates (dynamic nightly check)."""
        try:
            channel = Config.YT_DLP_VERSION_CHANNEL
            logging.info(f"Checking for yt-dlp updates ({channel})...")
            # We use --update-to [channel] which automatically checks if a newer version is available
            subprocess.run([Config.EXECUTABLE, '--update-to', channel], check=True)
        except Exception as e:
             logging.error(f"Failed to check/update yt-dlp: {e}")



def main():
    Logger.setup()
    try:
        YTDLManager.update_self()
        YTDLManager.update_yt_dlp() # Ensure yt-dlp is always latest nightly
        while True:
            # Simple CLI Interaction
            if os.path.isdir(Config.META_DIR) and os.listdir(Config.META_DIR):
                resp = input("Found temp files. Continue downloading? (Y/N) ").lower()
                if resp == 'n':
                    shutil.rmtree(Config.META_DIR)
                elif resp != 'y':
                    sys.exit(1)

            resp = input("Enter YouTube URL (or 'exit'): ")
            if resp.lower() == 'exit':
                sys.exit(0)
            
            if Config.is_youtube_url(resp):
                success, error = YTDLManager.dl_meta_from_url(resp)
                if not success:
                    print(f"ERROR: {error}")
                    continue
                
                videos = YTDLManager.load_videos()
                for vid in videos:
                    success, error = YTDLManager.download_video(vid)
                    if not success:
                        print(f"Error downloading {vid.title}: {error}")
                
                YTDLManager.cleanup_meta()
                logging.info("Batch complete.")
            else:
                logging.warning("Invalid URL.")

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        Logger.report_error("Critical error in main loop", context={"Traceback": traceback.format_exc(), "Exception": YTDLError(f"Critical: {e}")})
        input("Press ENTER to exit.")

if __name__ == "__main__":
    main()
