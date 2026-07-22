import os
import json
import shutil
import subprocess
import re
import threading
from urllib.parse import parse_qs, urlparse
import sys
import traceback
import platform
import base64
import logging
import io
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any, Tuple, List, Optional, Dict, Callable
from dataclasses import dataclass, field

sys.dont_write_bytecode = True

# --- App Versioning ---
__version__ = "v2026.07.22.02"
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

    # Supported YouTube URL families.  Keep this list structural rather than
    # accepting arbitrary paths below a YouTube hostname.
    _YOUTUBE_WEB_HOSTS = frozenset({
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    })
    _YOUTUBE_MUSIC_HOSTS = frozenset({"music.youtube.com"})
    _YOUTUBE_NOCOOKIE_HOSTS = frozenset({
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    })
    _YOUTUBE_CHANNEL_TABS = frozenset({
        "featured",
        "videos",
        "shorts",
        "streams",
        "live",
        "playlists",
        "community",
    })
    _YOUTUBE_URL_CANDIDATE_RE = re.compile(
        r"""(?ix)
        (?<![\w.-])
        (?:https?://)?
        (?:
            (?:www\.)?youtu\.be
            |(?:www\.|m\.)?youtube\.com
            |music\.youtube\.com
            |(?:www\.)?youtube-nocookie\.com
        )
        [^\s<>\"']*
        """
    )

    @staticmethod
    def _youtube_url_kind(url: str) -> Optional[str]:
        """Classify a supported YouTube URL as video, playlist, or channel."""
        if not url or not url.strip():
            return None

        candidate = url.strip()
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None

        host = parsed.hostname.lower()
        path_parts = tuple(part for part in parsed.path.split("/") if part)
        query = parse_qs(parsed.query)

        if host in {"youtu.be", "www.youtu.be"}:
            return "video" if len(path_parts) == 1 else None

        if host in Config._YOUTUBE_NOCOOKIE_HOSTS:
            return "video" if len(path_parts) == 2 and path_parts[0] == "embed" else None

        if host in Config._YOUTUBE_MUSIC_HOSTS:
            if path_parts == ("watch",) and query.get("v"):
                return "video"
            if path_parts == ("playlist",) and query.get("list"):
                return "playlist"
            return None

        if host not in Config._YOUTUBE_WEB_HOSTS:
            return None

        if path_parts == ("watch",) and query.get("v"):
            return "video"
        if len(path_parts) == 2 and path_parts[0] in {"embed", "v", "shorts", "live", "clip"}:
            return "video"
        if path_parts == ("playlist",) and query.get("list"):
            return "playlist"

        if len(path_parts) >= 2 and path_parts[0] in {"channel", "c", "user"}:
            if len(path_parts) == 2:
                return "channel"
            if len(path_parts) == 3 and path_parts[2] in Config._YOUTUBE_CHANNEL_TABS:
                return "channel"
        if path_parts and path_parts[0].startswith("@"):
            if len(path_parts) == 1:
                return "channel"
            if len(path_parts) == 2 and path_parts[1] in Config._YOUTUBE_CHANNEL_TABS:
                return "channel"

        return None

    @staticmethod
    def is_youtube_url(url: str) -> bool:
        return Config._youtube_url_kind(url) is not None

    @classmethod
    def extract_youtube_urls(cls, text: str) -> List[str]:
        """Extract supported YouTube URLs from arbitrary clipboard text."""
        if not isinstance(text, str):
            return []

        urls = []
        for candidate in cls._YOUTUBE_URL_CANDIDATE_RE.findall(text):
            # Common surrounding prose punctuation is not part of a URL.
            url = candidate.rstrip(".,;:!?)]}")
            if cls.is_youtube_url(url):
                urls.append(url)
        return urls

    @staticmethod
    def is_playlist_or_channel_url(url: str) -> bool:
        """Check if a URL points to a playlist or channel."""
        return Config._youtube_url_kind(url) in {"playlist", "channel"}

    @classmethod
    def get_yt_dlp_dir(cls) -> str:
        """Return the directory that owns the portable yt-dlp dependencies."""
        yt_dlp_path = shutil.which(cls.EXECUTABLE)
        if yt_dlp_path:
            return os.path.dirname(os.path.abspath(yt_dlp_path))
        return cls._APP_DIR

    @classmethod
    def get_deno_path(cls) -> str:
        """Return the portable Deno executable installed next to yt-dlp."""
        return os.path.join(cls.get_yt_dlp_dir(), "deno.exe")

    @classmethod
    def deno_status(cls) -> Tuple[bool, str]:
        """Check that the pinned portable Deno runtime can be used by yt-dlp."""
        deno_path = cls.get_deno_path()
        if not os.path.isfile(deno_path):
            return False, f"Missing portable Deno: {deno_path}"
        try:
            result = subprocess.run(
                [deno_path, "--version"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"Unable to run portable Deno: {e}"
        match = re.search(r"^deno\s+(\S+)", result.stdout, re.MULTILINE)
        if result.returncode != 0 or not match:
            return False, "Unable to read portable Deno version"
        if match.group(1) != cls.DENO_VERSION:
            return False, (
                "Portable Deno version mismatch: "
                f"expected {cls.DENO_VERSION}, got {match.group(1)}"
            )
        return True, "ready"

    @classmethod
    def get_youtube_js_runtime_args(cls) -> Tuple[List[str], str]:
        """Return yt-dlp's portable Deno runtime option for YouTube JS challenges."""
        ready, reason = cls.deno_status()
        if not ready:
            return [], reason
        return ["--js-runtimes", f"deno:{cls.get_deno_path()}"], "ready"

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


class PreferredFormatSelector:
    """Choose a video/audio pair using the application's format policy.

    yt-dlp's ``-S`` option cannot express a custom order for repeated codec
    fields.  The selector therefore resolves the pair from the metadata's
    format list and passes the resulting format IDs back to yt-dlp.
    """

    _CODEC_PRIORITY = {
        "vp9": 3,
        "avc": 2,
        "av1": 1,
    }
    _REQUIRED_AUDIO_CODEC = {
        "vp9": "opus",
        "avc": "mp4a",
        "av1": "opus",
    }
    _HDR_PRIORITY = {
        "DV": -1,  # Preserve yt-dlp's hdr:12 compatibility preference.
        "SDR": 0,
        "HLG": 1,
        "HDR10": 2,
        "HDR10+": 3,
        "HDR12": 4,
    }
    _PROTOCOL_PRIORITY = {
        "https": 5,
        "ftps": 5,
        "http": 4,
        "ftp": 4,
        "m3u8_native": 3,
        "m3u8": 2,
        "http_dash_segments": 1,
    }

    @classmethod
    def select(cls, formats: Any) -> Optional[str]:
        """Return ``video_id+audio_id`` for the preferred matching pair.

        The order is resolution, FPS, dynamic range, codec family, and
        transport.  Codec family only participates after the visual
        properties are tied: VP9+Opus, then AVC+M4A, then AV1+Opus.
        """
        if not isinstance(formats, list):
            return None

        video_formats = [fmt for fmt in formats if cls._is_video_only(fmt)]
        audio_formats = [fmt for fmt in formats if cls._is_audio_only(fmt)]
        candidates = []
        for video in video_formats:
            family = cls._video_family(video)
            if family is None:
                continue
            matching_audio = [
                audio for audio in audio_formats
                if cls._matches_required_audio(audio, family)
            ]
            if not matching_audio:
                continue
            audio = max(matching_audio, key=cls._audio_sort_key)
            candidates.append((video, audio, family))

        if not candidates:
            return None

        video, audio, _ = max(candidates, key=cls._pair_sort_key)
        video_id = cls._format_id(video)
        audio_id = cls._format_id(audio)
        if not video_id or not audio_id:
            return None
        return f"{video_id}+{audio_id}"

    @classmethod
    def _pair_sort_key(cls, candidate: Tuple[dict, dict, str]) -> tuple:
        video, audio, family = candidate
        return (
            cls._resolution(video),
            cls._number(video.get("fps")),
            cls._hdr_priority(video),
            cls._CODEC_PRIORITY[family],
            cls._protocol_priority(video),
            cls._audio_sort_key(audio),
            cls._format_id(video),
        )

    @classmethod
    def _audio_sort_key(cls, audio: dict) -> tuple:
        return (
            not cls._is_drc(audio),
            cls._number(audio.get("audio_channels")),
            cls._number(audio.get("asr")),
            cls._number(audio.get("abr")),
            cls._protocol_priority(audio),
            cls._format_id(audio),
        )

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _resolution(cls, fmt: dict) -> float:
        width = cls._number(fmt.get("width"))
        height = cls._number(fmt.get("height"))
        if width and height:
            return min(width, height)
        return height or width

    @classmethod
    def _hdr_priority(cls, fmt: dict) -> int:
        dynamic_range = str(fmt.get("dynamic_range") or "SDR").upper()
        return cls._HDR_PRIORITY.get(dynamic_range, 0)

    @classmethod
    def _protocol_priority(cls, fmt: dict) -> int:
        return cls._PROTOCOL_PRIORITY.get(str(fmt.get("protocol") or "").lower(), 0)

    @staticmethod
    def _format_id(fmt: dict) -> str:
        format_id = fmt.get("format_id")
        return str(format_id) if format_id is not None else ""

    @classmethod
    def _is_drc(cls, fmt: dict) -> bool:
        """Avoid dynamic-range-compressed audio when an equivalent track exists."""
        return "drc" in " ".join((
            cls._format_id(fmt),
            str(fmt.get("format_note") or ""),
            str(fmt.get("format") or ""),
        )).lower()

    @staticmethod
    def _is_video_only(fmt: Any) -> bool:
        if not isinstance(fmt, dict):
            return False
        return (
            str(fmt.get("vcodec") or "none").lower() != "none"
            and str(fmt.get("acodec") or "none").lower() == "none"
        )

    @staticmethod
    def _is_audio_only(fmt: Any) -> bool:
        if not isinstance(fmt, dict):
            return False
        return (
            str(fmt.get("vcodec") or "none").lower() == "none"
            and str(fmt.get("acodec") or "none").lower() != "none"
        )

    @staticmethod
    def _video_family(fmt: dict) -> Optional[str]:
        vcodec = str(fmt.get("vcodec") or "").lower()
        if re.match(r"^vp0?9", vcodec):
            return "vp9"
        if re.match(r"^(avc1|avc|h264)", vcodec):
            return "avc"
        if re.match(r"^(av01|av1)", vcodec):
            return "av1"
        return None

    @classmethod
    def _matches_required_audio(cls, audio: dict, family: str) -> bool:
        acodec = str(audio.get("acodec") or "").lower()
        required_codec = cls._REQUIRED_AUDIO_CODEC[family]
        if required_codec == "opus":
            return acodec == "opus"
        return acodec.startswith("mp4a") and str(audio.get("ext") or "").lower() == "m4a"

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
        
        selected_format = PreferredFormatSelector.select(self.meta.get("formats"))
        if selected_format:
            format_args = ['-f', selected_format]
            logging.info("Selected preferred format pair: %s", selected_format)
        else:
            # Keep the former behaviour for sites whose metadata has no
            # compatible video-only/audio-only pair.
            format_args = ['-f', 'bv+ba', '-S', 'res,fps,hdr:12,proto']
            logging.warning("No preferred codec pair found; falling back to yt-dlp format sorting.")

        args = [
            Config.EXECUTABLE,
            *format_args,
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
            js_runtime_args, reason = Config.get_youtube_js_runtime_args()
            if js_runtime_args:
                args.extend(js_runtime_args)
            else:
                logging.warning("Portable Deno is unavailable; downloading without a JS runtime: %s", reason)

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

            if Config.is_youtube_url(url):
                js_runtime_args, reason = Config.get_youtube_js_runtime_args()
                if js_runtime_args:
                    args.extend(js_runtime_args)
                else:
                    logging.warning("Portable Deno is unavailable; fetching metadata without a JS runtime: %s", reason)

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
    def ensure_deno():
        """Repair the portable Deno runtime used by yt-dlp JavaScript challenges."""
        return YTDLManager._ensure_component_with_updater(
            Config.deno_status,
            "--ensure-deno",
            "Portable Deno is ready.",
            "Portable Deno runtime",
            "Deno",
            "Deno repair completed but the runtime is not ready: %s",
            "Unable to repair portable Deno runtime.\n%s",
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
        report_progress("正在檢查或修復 Deno JavaScript runtime…")
        deno_ready = YTDLManager.ensure_deno()
        report_progress("正在檢查或修復 FFmpeg 與 FFprobe…")
        ffmpeg_ready = YTDLManager.ensure_ffmpeg()
        return {
            "deno": deno_ready,
            "ffmpeg": ffmpeg_ready,
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
