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
import base64
import logging
import io
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Tuple, List, Optional, Dict, Callable
from dataclasses import dataclass, field

sys.dont_write_bytecode = True

# --- App Versioning ---
__version__ = "v2026.07.20.06"
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
    DENO_VERSION = "2.9.3"

    # YouTube Proof of Origin (PO) Token provider. Keep this pinned so the
    # provider plugin and its JavaScript source are always installed together.
    BGUTIL_POT_PROVIDER_VERSION = "1.3.1"
    BGUTIL_POT_PLUGIN_FILENAME = "bgutil-ytdlp-pot-provider.zip"
    BGUTIL_POT_PROVIDER_DIRNAME = "bgutil-ytdlp-pot-provider"
    BGUTIL_POT_MARKER_FILENAME = ".ytdl-bgutil-pot-provider.json"
    # Keep this aligned with bgutil-ytdlp-pot-provider's internal script
    # version check.  A provider that cannot finish this probe will make
    # yt-dlp abort before it can select a YouTube format.
    POT_PROVIDER_PROBE_TIMEOUT_SECONDS = 15
    _pot_provider_status_cache: Optional[Tuple[bool, str]] = None

    # FFmpeg configuration. The upstream project distributes a rolling
    # "latest" archive, so this is the oldest build date verified to work
    # with this application rather than an upstream release tag.
    FFMPEG_MIN_BUILD_DATE = "20260712"
    
    _yt_dlp_path = shutil.which('yt-dlp')
    _yt_dlp_dir = os.path.dirname(_yt_dlp_path) if _yt_dlp_path else None
    
    # Try to find ffmpeg/ffprobe next to yt-dlp first. Missing files are
    # repaired at startup through self_update.py; do not fall back to PATH.
    FFMPEG_BINARY = (
        os.path.join(_yt_dlp_dir, "yt-dlp-ffmpeg.exe")
        if _yt_dlp_dir and os.path.isfile(os.path.join(_yt_dlp_dir, "yt-dlp-ffmpeg.exe"))
        else None
    )
    @classmethod
    def get_ffmpeg_paths(cls) -> Dict[str, str]:
        """Return the portable FFmpeg and FFprobe locations next to yt-dlp."""
        target_dir = cls.get_yt_dlp_dir()
        return {
            "ffmpeg": os.path.join(target_dir, "yt-dlp-ffmpeg.exe"),
            "ffprobe": os.path.join(target_dir, "yt-dlp-ffprobe.exe"),
        }

    @classmethod
    def refresh_ffmpeg_binaries(cls) -> bool:
        """Refresh the portable FFmpeg path after an FFmpeg repair or update."""
        paths = cls.get_ffmpeg_paths()
        cls.FFMPEG_BINARY = paths["ffmpeg"] if os.path.isfile(paths["ffmpeg"]) else None
        return bool(cls.FFMPEG_BINARY)

    @classmethod
    def ffmpeg_status(cls) -> Tuple[bool, str]:
        """Check that both portable tools run and meet the verified build date."""
        paths = cls.get_ffmpeg_paths()
        missing = [name for name, path in paths.items() if not os.path.isfile(path)]
        if missing:
            return False, f"Missing portable {', '.join(missing)}: " + ", ".join(
                paths[name] for name in missing
            )

        if not re.fullmatch(r"\d{8}", cls.FFMPEG_MIN_BUILD_DATE):
            return False, "Invalid FFMPEG_MIN_BUILD_DATE configuration"
        try:
            datetime.strptime(cls.FFMPEG_MIN_BUILD_DATE, "%Y%m%d")
        except ValueError:
            return False, "Invalid FFMPEG_MIN_BUILD_DATE calendar date"
        minimum_build_date = int(cls.FFMPEG_MIN_BUILD_DATE)

        for name, path in paths.items():
            try:
                result = subprocess.run(
                    [path, "-version"],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as e:
                return False, f"Unable to run portable {name}: {e}"

            match = re.search(r"--extra-version=(\d{8})", result.stdout)
            if result.returncode != 0 or not match:
                return False, f"Unable to read portable {name} build date"
            build_date = int(match.group(1))
            if build_date < minimum_build_date:
                return False, (
                    f"Portable {name} build is too old: {build_date} "
                    f"< required {minimum_build_date}"
                )

        return True, f"ready (build date >= {minimum_build_date})"

    # Discord Webhook
    _DISCORD_WEBHOOK_ENCODED = "aHR0cHM6Ly9kaXNjb3JkLmNvbS9hcGkvd2ViaG9va3MvMTQxMzc0NjU0MTY4MzkzNzM5MC9tWm9ZRy1mS211cnhFMFhPNWhjUmhITzBJWEREaWgyeDF2QnJ4dEFzQ0VTdEZ3M0FFTnNYamt3djQzbWFoaHhOQzFybw=="
    DISCORD_WEBHOOK = base64.b64decode(_DISCORD_WEBHOOK_ENCODED).decode('utf-8') if _DISCORD_WEBHOOK_ENCODED else ""

    # Paths and Environment
    _APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    META_DIR = os.path.join(_APP_DIR, 'meta')
    EXECUTABLE = 'yt-dlp'
    CONCURRENT_FRAGMENTS = "2"  # String: passed directly as CLI args to yt-dlp
    PROGRESS_BAR_SECONDS = "2"  # String: passed directly as CLI args to yt-dlp
    SUBPROCESS_HEARTBEAT_SECONDS = 60

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

    @classmethod
    def get_yt_dlp_dir(cls) -> str:
        """Return the directory that owns the portable yt-dlp dependencies."""
        yt_dlp_path = shutil.which(cls.EXECUTABLE)
        if yt_dlp_path:
            return os.path.dirname(os.path.abspath(yt_dlp_path))
        return cls._APP_DIR

    @classmethod
    def get_pot_provider_paths(cls) -> Dict[str, str]:
        """Return every portable path used by the BgUtils script provider."""
        target_dir = cls.get_yt_dlp_dir()
        provider_dir = os.path.join(target_dir, cls.BGUTIL_POT_PROVIDER_DIRNAME)
        return {
            "target_dir": target_dir,
            "deno": os.path.join(target_dir, "deno.exe"),
            "plugin": os.path.join(target_dir, "yt-dlp-plugins", cls.BGUTIL_POT_PLUGIN_FILENAME),
            "provider_dir": provider_dir,
            "server_home": os.path.join(provider_dir, "server"),
            "script": os.path.join(provider_dir, "server", "src", "generate_once.ts"),
            "node_modules": os.path.join(provider_dir, "server", "node_modules"),
            "marker": os.path.join(provider_dir, cls.BGUTIL_POT_MARKER_FILENAME),
        }

    @classmethod
    def _pot_provider_script_probe(cls, paths: Dict[str, str]) -> Tuple[bool, str]:
        """Run the exact local version check used by the Deno provider plugin."""
        home_dir = os.getenv("HOME") or os.getenv("USERPROFILE")
        xdg_cache = os.getenv("XDG_CACHE_HOME")
        if xdg_cache is not None:
            cache_dir = os.path.abspath(os.path.join(xdg_cache, cls.BGUTIL_POT_PROVIDER_DIRNAME))
        elif home_dir:
            cache_dir = os.path.abspath(os.path.join(home_dir, ".cache", cls.BGUTIL_POT_PROVIDER_DIRNAME))
        else:
            cache_dir = paths["server_home"]

        # The plugin escapes commas before passing paths to Deno.  Matching it
        # here makes this a meaningful preflight rather than a superficial
        # Deno executable check.
        def escpath(*values: str) -> str:
            return ",".join(value.replace(",", ",,") for value in values)

        environment = os.environ.copy()
        environment.update({
            "DENO_NO_PROMPT": "1",
            "DENO_NO_UPDATE_CHECK": "1",
            "FORCE_COLOR": "false",
        })
        command = [
            paths["deno"], "run", "--allow-env", "--allow-net",
            f"--allow-ffi={escpath(paths['node_modules'])}",
            f"--allow-write={escpath(cache_dir)}",
            f"--allow-read={escpath(cache_dir, paths['node_modules'])}",
            paths["script"], "--version",
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                timeout=cls.POT_PROVIDER_PROBE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return False, (
                "PO provider script version check timed out after "
                f"{cls.POT_PROVIDER_PROBE_TIMEOUT_SECONDS} seconds"
            )
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"Unable to run PO provider script version check: {e}"
        if result.returncode != 0:
            output = result.stdout.strip()
            detail = f": {output[-500:]}" if output else ""
            return False, f"PO provider script version check exited with code {result.returncode}{detail}"
        return True, "ready"

    @classmethod
    def pot_provider_status(cls, force_probe: bool = False) -> Tuple[bool, str]:
        """Verify the provider files and that its script can start within yt-dlp's limit."""
        if cls._pot_provider_status_cache is not None and not force_probe:
            return cls._pot_provider_status_cache
        paths = cls.get_pot_provider_paths()
        for name in ("deno", "plugin", "script"):
            if not os.path.isfile(paths[name]):
                result = False, f"Missing PO provider {name}: {paths[name]}"
                cls._pot_provider_status_cache = result
                return result
        if not os.path.isdir(paths["node_modules"]):
            result = False, f"Missing PO provider dependencies: {paths['node_modules']}"
            cls._pot_provider_status_cache = result
            return result
        try:
            deno_result = subprocess.run(
                [paths["deno"], "--version"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            deno_match = re.search(r"^deno\s+(\S+)", deno_result.stdout, re.MULTILINE)
            if deno_result.returncode != 0 or not deno_match:
                result = False, "Unable to read portable Deno version"
                cls._pot_provider_status_cache = result
                return result
            if deno_match.group(1) != cls.DENO_VERSION:
                result = False, (
                    "Portable Deno version mismatch: "
                    f"expected {cls.DENO_VERSION}, got {deno_match.group(1)}"
                )
                cls._pot_provider_status_cache = result
                return result
        except (OSError, subprocess.SubprocessError) as e:
            result = False, f"Unable to run portable Deno: {e}"
            cls._pot_provider_status_cache = result
            return result
        try:
            with open(paths["marker"], "r", encoding="utf-8") as f:
                marker = json.load(f)
        except (OSError, ValueError, TypeError) as e:
            result = False, f"Cannot read PO provider marker: {e}"
            cls._pot_provider_status_cache = result
            return result
        if marker.get("version") != cls.BGUTIL_POT_PROVIDER_VERSION:
            result = False, (
                "PO provider version mismatch: "
                f"expected {cls.BGUTIL_POT_PROVIDER_VERSION}, got {marker.get('version')!r}"
            )
            cls._pot_provider_status_cache = result
            return result

        result = cls._pot_provider_script_probe(paths)
        cls._pot_provider_status_cache = result
        return result

class YTDLError(Exception):
    """Base class for YTDL exceptions."""
    report = True
    reason_title_zh_tw = "發生未知的錯誤"

class DownloadError(YTDLError):
    """Raised when download or metadata fetching fails."""
    reason_title_zh_tw = "下載或獲取詮釋資料失敗"

class PrivateVideoError(DownloadError):
    """Raised when video is private."""
    report = False
    reason_title_zh_tw = "私人影片，無法下載"

class VideoUnavailableError(DownloadError):
    """Raised when video is 404/deleted."""
    report = False
    reason_title_zh_tw = "影片已遭刪除或無法存取"

class AgeRestrictedError(DownloadError):
    """Raised when video requires age verification."""
    report = False
    reason_title_zh_tw = "影片有年齡限制，無法下載"

class PremiumRequiredError(DownloadError):
    """Raised when video requires membership."""
    report = False
    reason_title_zh_tw = "此為會員專屬影片，無法下載"

class PoTokenProviderError(DownloadError):
    """Raised when yt-dlp cannot generate a YouTube PO Token."""
    reason_title_zh_tw = "YouTube PO Token 產生失敗"

class MetadataError(YTDLError):
    """Raised when metadata file operations fail."""
    reason_title_zh_tw = "讀取或寫入影片資訊操作失敗"

class UpdateError(YTDLError):
    """Raised when self-update fails."""
    reason_title_zh_tw = "程式自動更新失敗"

class SubprocessError(YTDLError):
    """Raised when a subprocess execution fails unexpectedly."""
    reason_title_zh_tw = "外部程式執行失敗"

@dataclass
class ErrorContext:
    """Standardized error context for Logger.report_error."""
    operation: str = ""
    url: str = ""
    title: str = ""
    traceback_str: str = ""
    log_output: str = ""
    exception: Optional[Exception] = None
    extra: Dict[str, str] = field(default_factory=dict)

class Logger:
    DISCORD_CONTENT_LIMIT = 1900
    MAX_DIAGNOSTIC_BYTES = 8 * 1024 * 1024

    @staticmethod
    def setup():
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)

        # Clear existing handlers to avoid duplicates if setup is called multiple times
        if logger.hasHandlers():
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()

        # A .py file can be associated with pythonw.exe on Windows. In that
        # case both standard streams are None, so console logging must be
        # optional rather than preventing the background download worker from
        # starting.
        console_stream = sys.stdout or sys.stderr
        if console_stream is not None:
            console_handler = logging.StreamHandler(console_stream)
            console_handler.setFormatter(log_formatter)
            logger.addHandler(console_handler)

    @staticmethod
    def _get_system_info() -> str:
        """Return diagnostic details that do not identify the user's machine."""
        return f"OS: {platform.system()} {platform.release()} | App version: {__version__}"

    @staticmethod
    def _new_error_id() -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"ERR-{timestamp}-{uuid4().hex[:6].upper()}"

    @staticmethod
    def _truncate_for_discord(value: str) -> str:
        if len(value) <= Logger.DISCORD_CONTENT_LIMIT:
            return value
        suffix = "\n…訊息過長，完整內容請見附加的診斷檔。"
        return value[:Logger.DISCORD_CONTENT_LIMIT - len(suffix)] + suffix

    @staticmethod
    def _diagnostic_attachment(log_content: str) -> io.BytesIO:
        """Keep an upload small enough for standard Discord webhook limits."""
        content_bytes = log_content.encode("utf-8")
        if len(content_bytes) <= Logger.MAX_DIAGNOSTIC_BYTES:
            return io.BytesIO(content_bytes)
        marker = (
            b"[Diagnostic output exceeded 8 MiB; the beginning was omitted. "
            b"The remainder below is the most recent output.]\n\n"
        )
        return io.BytesIO(marker + content_bytes[-(Logger.MAX_DIAGNOSTIC_BYTES - len(marker)):])

    @staticmethod
    def _send_discord_report(payload: dict, log_content: Optional[str], log_label: Optional[str]):
        """Send one bounded Discord notification and surface webhook failures locally."""
        if log_content:
            log_filename = f"{log_label.replace(' ', '_').lower()}.txt"
            log_stream = Logger._diagnostic_attachment(log_content)
            response = requests.post(
                Config.DISCORD_WEBHOOK,
                data={"payload_json": json.dumps(payload)},
                files={"file": (log_filename, log_stream, "text/plain")},
                timeout=10,
            )
        else:
            response = requests.post(Config.DISCORD_WEBHOOK, json=payload, timeout=10)
        response.raise_for_status()

    @staticmethod
    def report_error(message: str, ctx: Optional[ErrorContext] = None) -> str:
        """Log an error and return a short ID that links UI and Discord."""
        if ctx is None:
            ctx = ErrorContext()

        error_id = Logger._new_error_id()
        computer_info = Logger._get_system_info()
        error_type = type(ctx.exception).__name__ if ctx.exception else "Generic Error"

        # Determine log content for attachment
        log_content = None
        log_label = None
        if ctx.log_output:
            log_content = re.sub(r'```(.*?)\n|```', '', ctx.log_output, flags=re.DOTALL)
            log_label = "Terminal Log"
        elif ctx.traceback_str:
            log_content = ctx.traceback_str
            log_label = "Traceback"

        # Build a concise, actionable summary. Full subprocess output or a
        # traceback is attached separately so Discord's content limit cannot
        # hide the useful fields.
        context_lines = []
        if ctx.operation:
            context_lines.append(f"Operation: {ctx.operation}")
        if log_label and log_content:
            context_lines.append(f"Diagnostic: attached {log_label.replace(' ', '_').lower()}.txt")
        if ctx.url:
            context_lines.append(f"URL: {ctx.url}")
        if ctx.title:
            context_lines.append(f"Title: {ctx.title}")
        for key, value in ctx.extra.items():
            context_lines.append(f"{key}: {value}")
        context_message = "\n".join(context_lines)

        # Local log
        logging.error(
            "[%s] An error occurred (%s):\n%s\n%s%s",
            error_id,
            error_type,
            computer_info,
            f"{context_message}\n" if context_message else "",
            message,
        )
        if log_content:
            logging.error("[%s] --- Full %s ---\n%s", error_id, log_label, log_content)

        # Discord Notification
        should_report_discord = True
        if isinstance(ctx.exception, YTDLError) and not ctx.exception.report:
            should_report_discord = False

        if should_report_discord and Config.DISCORD_WEBHOOK and "YOUR_DISCORD_WEBHOOK_URL" not in Config.DISCORD_WEBHOOK:
            try:
                final_report = (
                    f"🚨 **YTDL Error Report** `{error_id}`\n"
                    f"**Type:** `{error_type}`\n"
                    f"**Environment:** {computer_info}\n"
                    f"**Error:**\n```\n{message}\n```\n"
                    f"{context_message}"
                )
                Logger._send_discord_report(
                    {"content": Logger._truncate_for_discord(final_report)}, log_content, log_label
                )
            except Exception as e:
                logging.critical("[%s] Failed to send error report to Discord: %s", error_id, e)

        return error_id

class SubprocessRunner:
    @staticmethod
    def run(args: list, context: dict = None) -> Tuple[int, str]:
        if context is None:
            context = {}
        process = None
        try:
            # stdin must not be inherited from a GUI/worker process. yt-dlp
            # launches FFmpeg for post-processing, and FFmpeg may otherwise
            # wait on an inherited console input handle.
            process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                bufsize=1,
            )
            started_at = time.monotonic()
            last_output_at = started_at
            last_output_line = ""
            output_lock = threading.Lock()
            logging.info(f"Started subprocess PID {process.pid}: {subprocess.list2cmdline(args)}")

            stdout_lines = []
            stderr_lines = []

            def stream_reader(stream, line_list, output_file):
                nonlocal last_output_at, last_output_line
                for line in iter(stream.readline, ''):
                    line_list.append(line)
                    with output_lock:
                        last_output_at = time.monotonic()
                        last_output_line = line.strip()
                    if '[debug]' not in line and output_file is not None:
                        # Console output is best-effort. Never let an absent,
                        # disconnected, or legacy-encoded Windows console stop
                        # draining this pipe. A UnicodeEncodeError otherwise
                        # terminates this reader, fills the pipe, and makes
                        # yt-dlp/FFmpeg look frozen in a postprocessor.
                        try:
                            print(line.strip(), file=output_file)
                        except (AttributeError, OSError, ValueError, UnicodeEncodeError):
                            logging.debug("Subprocess console stream is unavailable; continuing to drain output.")
                stream.close()

            stdout_thread = threading.Thread(target=stream_reader, args=(process.stdout, stdout_lines, sys.stdout), daemon=True)
            stderr_thread = threading.Thread(target=stream_reader, args=(process.stderr, stderr_lines, sys.stderr), daemon=True)

            stdout_thread.start()
            stderr_thread.start()
            next_heartbeat_at = started_at + Config.SUBPROCESS_HEARTBEAT_SECONDS
            while process.poll() is None:
                time.sleep(0.25)
                now = time.monotonic()
                if now >= next_heartbeat_at:
                    with output_lock:
                        idle_seconds = int(now - last_output_at)
                        latest_line = last_output_line
                    logging.warning(
                        "Subprocess heartbeat: PID %s is still running after %ss; "
                        "no output for %ss. Last output: %s",
                        process.pid,
                        int(now - started_at),
                        idle_seconds,
                        latest_line or "(none)",
                    )
                    next_heartbeat_at = now + Config.SUBPROCESS_HEARTBEAT_SECONDS

            stdout_thread.join()
            stderr_thread.join()

            full_log = "".join(stdout_lines) + "".join(stderr_lines)
            logging.info(f"Subprocess PID {process.pid} exited with code {process.returncode} after {int(time.monotonic() - started_at)}s")
            return process.returncode, full_log
        except KeyboardInterrupt:
            logging.warning("Process interrupted by user.")
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
            return -1, "Interrupted by user"
        except FileNotFoundError:
            error_msg = f"Executable not found: {args[0] if args else 'N/A'}. Ensure it is installed and in PATH."
            Logger.report_error(error_msg, ctx=ErrorContext(
                operation="Run external downloader", exception=SubprocessError(error_msg), extra=context))
            return -1, error_msg
        except Exception as e:
            Logger.report_error(f"An unexpected error occurred during subprocess execution.", ctx=ErrorContext(
                operation="Run external downloader", traceback_str=traceback.format_exc(), exception=SubprocessError(str(e)), extra=context))
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
    PRESERVED_METADATA_FIELDS = (
        "playlist",
        "playlist_id",
        "playlist_title",
        "playlist_uploader",
        "playlist_uploader_id",
        "playlist_channel",
        "playlist_channel_id",
        "playlist_webpage_url",
        "playlist_index",
        "playlist_count",
    )

    def __init__(self, meta_filepath: str):
        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.is_valid = bool(self.meta)
        
        self.webpage_url = self._clean_meta_value(self.meta.get("webpage_url")) or self._clean_meta_value(self.meta.get("original_url"))
        self.playlist = self._clean_meta_value(self.meta.get("playlist")) or self._clean_meta_value(self.meta.get("playlist_title"))
        self.playlist_id = self._clean_meta_value(self.meta.get("playlist_id"))
        self.playlist_url = self._clean_meta_value(self.meta.get("playlist_webpage_url")) or self._clean_meta_value(self.meta.get("playlist_url"))
        self.playlist_index = self.meta.get("playlist_index")
        self.title = self.meta.get("title", "N/A")
        
    def _read_meta(self) -> dict:
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            Logger.report_error(f"Failed to read or parse meta file: {self.meta_filepath}", ctx=ErrorContext(
                traceback_str=traceback.format_exc(), exception=MetadataError(str(e))))
            return {}

    def get_download_args(self) -> list:
        # Determine template based on content type
        # Check for truthy 'playlist' value; the key often exists with None for single videos
        is_playlist = bool(self.playlist) or bool(self.playlist_url) or Config.is_playlist_or_channel_url(self.webpage_url)
        template = self._get_output_template(is_playlist)
        
        args = [
            Config.EXECUTABLE,
            '-f', 'bv+ba',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            '--embed-subs', '--sub-langs', 'all,-live_chat',
            '--embed-thumbnail', '--embed-metadata',
            # Prevent FFmpeg from blocking on an inherited console handle when
            # this application is launched as a GUI process on Windows.
            '--postprocessor-args', 'FFmpeg:-nostdin',
            '--merge-output-format', 'mkv',
            '--encoding', 'utf-8',
            '--force-ipv4',
            '--concurrent-fragments', Config.CONCURRENT_FRAGMENTS,
            '--progress-delta', Config.PROGRESS_BAR_SECONDS,
            '-o', template,
            '--verbose'
        ]

        if Config.FFMPEG_BINARY:
            args.extend(['--ffmpeg-location', Config.FFMPEG_BINARY])

        source_url = self.webpage_url or self.playlist_url
        if Config.is_youtube_url(source_url):
            pot_provider_ready, reason = Config.pot_provider_status()
            if pot_provider_ready:
                paths = Config.get_pot_provider_paths()
                args.extend([
                    "--js-runtimes", f"deno:{paths['deno']}",
                    "--extractor-args",
                    f"youtubepot-bgutilscript:server_home={paths['server_home']}",
                ])
            else:
                logging.warning("YouTube PO Token provider is unavailable; downloading without it: %s", reason)

        if not (self.playlist_url and self.playlist_index is not None):
            args.extend(self._get_preserved_metadata_args())

        source_args = self._get_fresh_source_args()
        args.extend(source_args)
        
        return args

    def _get_preserved_metadata_args(self) -> list:
        args = []
        for field in self.PRESERVED_METADATA_FIELDS:
            value = self.meta.get(field)
            if self._clean_meta_value(value) == "":
                continue
            args.extend(['--parse-metadata', f"{self._metadata_constant_source(value)}:%({field})s"])

        if self.playlist:
            args.extend(['--parse-metadata', f"{self._metadata_constant_source(self.playlist)}:%(meta_album)s"])
        if self.playlist_index is not None:
            args.extend(['--parse-metadata', f"{self._metadata_constant_source(self.playlist_index)}:%(meta_track)s"])

        return args

    @staticmethod
    def _metadata_constant_source(value) -> str:
        value = str(value).replace('\\', '\\\\').replace('%', '%%').replace(':', '\\:').replace('\r', ' ').replace('\n', ' ')
        return f"%(id&{value}|)s"

    @staticmethod
    def _clean_meta_value(value) -> str:
        if value is None:
            return ""
        value = str(value).strip()
        return "" if value.upper() == "NA" else value

    def _get_fresh_source_args(self) -> list:
        if self.playlist_url and self.playlist_index is not None:
            return ['--playlist-items', str(self.playlist_index), self.playlist_url]

        if self.webpage_url:
            args = []
            if not Config.is_playlist_or_channel_url(self.webpage_url):
                args.append('--no-playlist')
            args.append(self.webpage_url)
            return args

        logging.warning(f"Missing webpage URL in meta file; falling back to stale info json: {self.meta_filepath}")
        return ['--load-info-json', self.meta_filepath]

    def _get_output_template(self, is_playlist: bool) -> str:
        video_template = r"%(title)s.%(id)s.%(ext)s"
        if not is_playlist:
            return video_template

        folder_name = self.playlist or self.playlist_id or "Playlist"
        folder_name = self._escape_output_template_value(self._sanitize_path_part(folder_name))
        return f"{folder_name}/{video_template}"

    @staticmethod
    def _escape_output_template_value(value: str) -> str:
        return value.replace('%', '%%')

    @staticmethod
    def _sanitize_path_part(value) -> str:
        value = str(value).strip()
        value = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', '_', value)
        value = re.sub(r'\s+', ' ', value).strip(' .')

        reserved_names = {
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        }
        if not value:
            return "Playlist"
        if value.upper() in reserved_names:
            return f"_{value}"
        return value

class YTDLManager:
    @staticmethod
    def _detect_specific_error(log_text: str) -> Optional[YTDLError]:
        if not log_text:
            return None

        pot_error_markers = (
            "PoTokenProviderError",
            "Unexpected error when fetching PO Token",
            "_get_pot_via_script failed",
            "Unable to run script",
            "The script did not respond with a po_token",
            "Failed to check script version",
        )
        if any(marker.lower() in log_text.lower() for marker in pot_error_markers):
            return PoTokenProviderError("yt-dlp could not generate a YouTube PO Token.")
        
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
    def _report_yt_dlp_failure(
        operation: str,
        failure_message: str,
        returncode: int,
        full_log: str,
        url: str = "",
        title: str = "",
    ) -> str:
        specific_error = YTDLManager._detect_specific_error(full_log)
        exception_to_report = specific_error or DownloadError(failure_message)
        message = str(specific_error) if specific_error else failure_message
        extracted_error = (
            f"{exception_to_report.reason_title_zh_tw}\n"
            f"詳細錯誤: {SubprocessRunner.extract_yt_dlp_error(full_log)}"
        )
        error_id = Logger.report_error(message, ctx=ErrorContext(
            operation=operation,
            url=url,
            title=title,
            log_output=f"```\n{full_log}\n```",
            exception=exception_to_report,
            extra={"Exit code": str(returncode)},
        ))
        return f"{extracted_error}\n錯誤代碼: {error_id}"

    @staticmethod
    def _report_download_exception(
        operation: str,
        message: str,
        exception: Exception,
        url: str = "",
        title: str = "",
    ) -> str:
        err_obj = DownloadError(str(exception))
        error_id = Logger.report_error(message, ctx=ErrorContext(
            operation=operation,
            url=url,
            title=title,
            traceback_str=traceback.format_exc(),
            exception=err_obj,
        ))
        return f"{err_obj.reason_title_zh_tw}\n詳細錯誤: {exception}\n錯誤代碼: {error_id}"

    @staticmethod
    def dl_meta_from_url(url: str) -> Tuple[bool, Optional[str]]:
        try:
            if not os.path.exists(Config.META_DIR):
                os.makedirs(Config.META_DIR)
            
            args = [
                Config.EXECUTABLE,
                '--no-download',
                '--no-write-playlist-metafiles', '-o',
                os.path.join(Config.META_DIR, "%(autonumber)s_%(id)s"),
                '--write-info-json', '--encoding', 'utf-8', '--verbose',
                '--force-ipv4',
                '--concurrent-fragments', Config.CONCURRENT_FRAGMENTS,
                url
            ]
            
            if not Config.is_playlist_or_channel_url(url):
                args.append('--no-playlist')

            returncode, full_log = SubprocessRunner.run(args, {"URL": url})

            if returncode == 0:
                return True, None

            return False, YTDLManager._report_yt_dlp_failure(
                "Fetch metadata",
                f"Failed to download metadata. yt-dlp exited with code {returncode}",
                returncode,
                full_log,
                url=url,
            )

        except Exception as e:
            return False, YTDLManager._report_download_exception(
                "Fetch metadata", "Error fetching metadata.", e, url=url
            )

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
        try:
            args = video.get_download_args()
            returncode, full_log = SubprocessRunner.run(args, {"Title": video.title, "URL": video.webpage_url})

            if returncode == 0:
                os.remove(video.meta_filepath)
                return True, None
            
            return False, YTDLManager._report_yt_dlp_failure(
                "Download video",
                f"Download failed. yt-dlp exited with code {returncode}.",
                returncode,
                full_log,
                url=video.webpage_url,
                title=video.title,
            )

        except Exception as e:
            return False, YTDLManager._report_download_exception(
                "Download video",
                "Unexpected error during download.",
                e,
                url=video.webpage_url,
                title=video.title,
            )

    @staticmethod
    def download_pending_videos():
        """Download every valid metadata file currently queued in the meta directory."""
        videos = YTDLManager.load_videos()
        for video in videos:
            success, error = YTDLManager.download_video(video)
            if not success:
                print(f"Error downloading {video.title}: {error}")

        YTDLManager.cleanup_meta()
        logging.info("Batch complete.")

    @staticmethod
    def cleanup_meta():
        if os.path.isdir(Config.META_DIR) and not os.listdir(Config.META_DIR):
            try:
                os.rmdir(Config.META_DIR)
                logging.info("Empty meta directory deleted.")
            except OSError as e:
                Logger.report_error(f"Error deleting empty meta directory.", ctx=ErrorContext(
                    exception=MetadataError(str(e)), extra={"Error": str(e)}))

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
            Logger.report_error(traceback.format_exc(), ctx=ErrorContext(
                traceback_str=traceback.format_exc(), exception=UpdateError("Self-update failed")))

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

    @staticmethod
    def _ensure_component_with_updater(
        status_check: Callable[[], Tuple[bool, str]],
        updater_flag: str,
        ready_message: str,
        repair_subject: str,
        output_label: str,
        verification_failure_message: str,
        repair_failure_message: str,
        on_ready: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Use self_update.py to repair one portable dependency when needed."""
        ready, reason = status_check()
        if ready:
            if on_ready:
                on_ready()
            logging.info(ready_message)
            return True

        logging.info("%s need repair: %s", repair_subject, reason)
        updater_path = os.path.join(Config._APP_DIR, "self_update.py")
        downloaded_updater = False
        try:
            if not os.path.isfile(updater_path):
                repo = "minhung1126/YTDL"
                updater_url = f"https://raw.githubusercontent.com/{repo}/main/self_update.py"
                response = _http_get_with_retry(updater_url, timeout=15)
                with open(updater_path, "wb") as f:
                    f.write(response.content)
                downloaded_updater = True

            result = subprocess.run(
                [sys.executable, updater_path, updater_flag, Config.DISCORD_WEBHOOK],
                cwd=Config._APP_DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=900,
            )
            output = result.stdout.strip()
            if output:
                logging.info("%s repair output:\n%s", output_label, output[-8000:])
            if result.returncode != 0:
                logging.error("%s repair exited with code %s.", output_label, result.returncode)
                return False
        except Exception:
            logging.error(repair_failure_message, traceback.format_exc())
            return False
        finally:
            if downloaded_updater:
                try:
                    os.remove(updater_path)
                except OSError:
                    logging.warning("Unable to remove temporary updater: %s", updater_path)

        ready, reason = status_check()
        if ready:
            if on_ready:
                on_ready()
        else:
            logging.error(verification_failure_message, reason)
        return ready

    @staticmethod
    def ensure_ffmpeg():
        """Repair portable FFmpeg tools when either required binary is missing."""
        return YTDLManager._ensure_component_with_updater(
            Config.ffmpeg_status,
            "--ensure-ffmpeg",
            "Portable FFmpeg and FFprobe are ready.",
            "Portable FFmpeg tools",
            "FFmpeg",
            "FFmpeg repair completed but tools are not ready: %s",
            "Unable to repair portable FFmpeg tools.\n%s",
            Config.refresh_ffmpeg_binaries,
        )

    @staticmethod
    def ensure_pot_provider():
        """Repair the portable provider when files or its script probe are unhealthy."""
        checks = 0

        def status_check() -> Tuple[bool, str]:
            # A failed pre-repair result is cached to avoid delaying every
            # download.  Re-probe after the updater has repaired or warmed it.
            nonlocal checks
            checks += 1
            return Config.pot_provider_status(force_probe=checks > 1)

        return YTDLManager._ensure_component_with_updater(
            status_check,
            "--ensure-pot-provider",
            "YouTube PO Token provider is ready.",
            "YouTube PO Token provider",
            "PO provider",
            "PO provider repair completed but is not ready: %s",
            "Unable to repair YouTube PO Token provider.\n%s",
        )

    @staticmethod
    def run_startup_maintenance(progress_callback: Optional[Callable[[str], None]] = None) -> Dict[str, bool]:
        """Run the shared update and dependency checks required before downloading.

        Both the command-line and GUI entry points must use this method so a
        release cannot receive different update or portable-dependency
        behaviour depending on how it is launched.  Individual repair
        failures are logged and intentionally do not prevent yt-dlp from
        attempting its normal fallback behaviour.
        """
        def report_progress(message: str):
            if progress_callback is None:
                return
            try:
                progress_callback(message)
            except Exception:
                logging.warning("Unable to report startup progress.\n%s", traceback.format_exc())

        report_progress("正在檢查程式更新…")
        YTDLManager.update_self()
        report_progress("正在檢查 yt-dlp nightly 更新…")
        YTDLManager.update_yt_dlp()
        report_progress("正在檢查或修復 FFmpeg 與 FFprobe…")
        ffmpeg_ready = YTDLManager.ensure_ffmpeg()
        report_progress("正在檢查或修復 YouTube PO Token provider…")
        pot_provider_ready = YTDLManager.ensure_pot_provider()
        return {
            "ffmpeg": ffmpeg_ready,
            "pot_provider": pot_provider_ready,
        }

def main():
    Logger.setup()
    try:
        YTDLManager.run_startup_maintenance()
        while True:
            # Simple CLI Interaction
            if os.path.isdir(Config.META_DIR) and os.listdir(Config.META_DIR):
                resp = input("Found temp files. Continue downloading? (Y/N) ").lower()
                if resp == 'n':
                    shutil.rmtree(Config.META_DIR)
                elif resp == 'y':
                    YTDLManager.download_pending_videos()
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
                
                YTDLManager.download_pending_videos()
            else:
                logging.warning("Invalid URL.")

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        Logger.report_error("Critical error in main loop", ctx=ErrorContext(
            traceback_str=traceback.format_exc(), exception=YTDLError(f"Critical: {e}")))
        input("Press ENTER to exit.")

if __name__ == "__main__":
    main()
