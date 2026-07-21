import sys
sys.dont_write_bytecode = True
import os
import io
import json
import re
import time
import subprocess
import traceback
import platform
import shutil
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from zipfile import ZipFile
from typing import Optional

MAX_DIAGNOSTIC_BYTES = 8 * 1024 * 1024

try:
    import requests
except ImportError:
    print("[FATAL] requests library not found. Cannot proceed with update.", file=sys.stderr)
    sys.exit(1)

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

def report_error_updater(message: str, webhook_url: str, operation: str = "Self-update") -> str:
    """
    Report an updater failure with an ID that is shared by its console output,
    local Discord notification, and attached diagnostic text.
    """
    error_id = f"UPD-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6].upper()}"
    environment = f"OS: {platform.system()} {platform.release()}"

    print(
        f"[ERROR] {error_id} | {operation}\n{environment}\n{message}",
        file=sys.stderr,
    )
    
    if webhook_url:
        try:
            diagnostic_bytes = message.encode("utf-8")
            if len(diagnostic_bytes) > MAX_DIAGNOSTIC_BYTES:
                marker = (
                    b"[Diagnostic output exceeded 8 MiB; the beginning was omitted. "
                    b"The remainder below is the most recent output.]\n\n"
                )
                diagnostic_bytes = marker + diagnostic_bytes[-(MAX_DIAGNOSTIC_BYTES - len(marker)):]
            content = (
                f"🚨 **YTDL Updater Error** `{error_id}`\n"
                f"**Operation:** {operation}\n"
                f"**Environment:** {environment}\n"
                "**Diagnostic:** attached `updater_error.txt`\n"
                f"**Error:**\n```\n{message}\n```"
            )
            content_limit = 1900
            if len(content) > content_limit:
                suffix = "\n…訊息過長，完整內容請見附加的診斷檔。"
                content = content[:content_limit - len(suffix)] + suffix
            response = requests.post(
                webhook_url,
                data={"payload_json": json.dumps({"content": content})},
                files={"file": ("updater_error.txt", io.BytesIO(diagnostic_bytes), "text/plain")},
                timeout=10,
            )
            response.raise_for_status()
        except Exception as e:
            print(f"[CRITICAL] {error_id} | Failed to send updater error report to Discord: {e}", file=sys.stderr)

    return error_id

def _ffmpeg_build_date(executable_path: str) -> Optional[int]:
    """Return an FFmpeg build's YYYYMMDD extra-version, if it is runnable."""
    try:
        result = subprocess.run(
            [executable_path, "-version"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"--extra-version=(\d{8})", result.stdout)
    return int(match.group(1)) if result.returncode == 0 and match else None


def update_ffmpeg(YTDL_module, webhook_url: str, minimum_build_date: str = None):
    """Repair portable FFmpeg tools below the verified minimum build date."""
    try:
        # 1. Configuration
        configured_minimum = minimum_build_date
        if not configured_minimum:
            if hasattr(YTDL_module, 'Config'):
                configured_minimum = getattr(YTDL_module.Config, 'FFMPEG_MIN_BUILD_DATE', None)

        if not isinstance(configured_minimum, str) or not re.fullmatch(r"\d{8}", configured_minimum):
            report_error_updater(
                "FFMPEG_MIN_BUILD_DATE must be an eight-digit YYYYMMDD value in YTDL.py.",
                webhook_url,
                "FFmpeg update",
            )
            return False
        try:
            datetime.strptime(configured_minimum, "%Y%m%d")
        except ValueError:
            report_error_updater(
                "FFMPEG_MIN_BUILD_DATE must contain a valid calendar date in YTDL.py.",
                webhook_url,
                "FFmpeg update",
            )
            return False
        minimum_build_date_value = int(configured_minimum)

        # 2. Target Directory
        target_dir = _portable_target_dir(YTDL_module)

        ffmpeg_exe = os.path.join(target_dir, 'yt-dlp-ffmpeg.exe')
        ffprobe_exe = os.path.join(target_dir, 'yt-dlp-ffprobe.exe')
        
        # 3. Availability and verified-build-date check
        should_update = False
        missing_binaries = [
            name for name, path in (("FFmpeg", ffmpeg_exe), ("FFprobe", ffprobe_exe))
            if not os.path.isfile(path)
        ]
        if missing_binaries:
            print(f"{' and '.join(missing_binaries)} not found. Downloading...")
            should_update = True
        else:
            build_dates = {
                "FFmpeg": _ffmpeg_build_date(ffmpeg_exe),
                "FFprobe": _ffmpeg_build_date(ffprobe_exe),
            }
            unreadable = [name for name, build_date in build_dates.items() if build_date is None]
            outdated = [
                f"{name} ({build_date} < {minimum_build_date_value})"
                for name, build_date in build_dates.items()
                if build_date is not None and build_date < minimum_build_date_value
            ]
            if unreadable or outdated:
                details = unreadable + outdated
                print(f"Portable FFmpeg tools need repair: {', '.join(details)}.")
                should_update = True
            else:
                print(
                    "Portable FFmpeg tools meet the verified minimum build date "
                    f"({minimum_build_date_value})."
                )
        
        if not should_update:
            return True

        # 4. Download and Extract
        print(
            "Downloading the latest FFmpeg build "
            f"(minimum verified build date: {minimum_build_date_value})..."
        )
        
        download_tag = "latest"
        zip_url = f"https://github.com/yt-dlp/FFmpeg-Builds/releases/download/{download_tag}/ffmpeg-master-{download_tag}-win64-gpl.zip"
        
        print(f"Download URL: {zip_url}")
        resp = _http_get_with_retry(zip_url, timeout=(10, 300))
        
        print("Extracting FFmpeg binaries...")
        with ZipFile(io.BytesIO(resp.content)) as z:
            extracted_binaries = set()
            for member in z.namelist():
                # Extract all .exe files in 'bin/'
                if '/bin/' in member and member.endswith('.exe'):
                    filename = os.path.basename(member)
                    if not filename: continue
                    
                    # Rename to yt-dlp- prefix
                    if filename.lower() == 'ffmpeg.exe':
                        new_filename = 'yt-dlp-ffmpeg.exe'
                    elif filename.lower() == 'ffprobe.exe':
                        new_filename = 'yt-dlp-ffprobe.exe'
                    else:
                        continue # Skip other files if any
                    
                    target_path = os.path.join(target_dir, new_filename)
                    # print(f"Extracting {filename} as {new_filename} to {target_dir}...")
                    
                    with z.open(member) as source, open(target_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    extracted_binaries.add(new_filename)

        expected_binaries = {'yt-dlp-ffmpeg.exe', 'yt-dlp-ffprobe.exe'}
        if extracted_binaries != expected_binaries:
            raise RuntimeError(
                "Downloaded FFmpeg archive is missing required binaries: "
                f"{', '.join(sorted(expected_binaries - extracted_binaries))}"
            )
        if not all(os.path.isfile(path) for path in (ffmpeg_exe, ffprobe_exe)):
            raise RuntimeError("FFmpeg update did not install both FFmpeg and FFprobe.")
        installed_build_dates = {
            "FFmpeg": _ffmpeg_build_date(ffmpeg_exe),
            "FFprobe": _ffmpeg_build_date(ffprobe_exe),
        }
        invalid_binaries = [
            name for name, build_date in installed_build_dates.items()
            if build_date is None or build_date < minimum_build_date_value
        ]
        if invalid_binaries:
            raise RuntimeError(
                "Downloaded FFmpeg archive did not meet the verified minimum build date "
                f"{minimum_build_date_value}: {', '.join(invalid_binaries)}"
            )
                        
        print(f"FFmpeg update completed. Binaries placed in {target_dir}")

        return True

    except Exception as e:
        report_error_updater(f"FFmpeg update failed: {e}\n{traceback.format_exc()}", webhook_url)
        return False

def _config_value(YTDL_module, name, default=None):
    config = getattr(YTDL_module, "Config", YTDL_module)
    return getattr(config, name, default)


def _portable_target_dir(YTDL_module) -> str:
    executable = _config_value(YTDL_module, "EXECUTABLE", "yt-dlp")
    yt_dlp_path = shutil.which(executable)
    if yt_dlp_path:
        return os.path.dirname(os.path.abspath(yt_dlp_path))
    return os.getcwd()


def _installed_deno_version(deno_path: str) -> Optional[str]:
    if not os.path.isfile(deno_path):
        return None
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
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"^deno\s+(\S+)", result.stdout, re.MULTILINE)
    return match.group(1) if result.returncode == 0 and match else None


def ensure_portable_deno(YTDL_module, webhook_url: str) -> Optional[str]:
    """Install the pinned Deno executable next to yt-dlp without touching PATH."""
    deno_version = _config_value(YTDL_module, "DENO_VERSION")
    if not deno_version:
        report_error_updater("DENO_VERSION not found in YTDL.py.", webhook_url, "Deno update")
        return None
    if platform.system() != "Windows":
        report_error_updater(
            f"Portable Deno auto-installation is only supported on Windows. Your OS: {platform.system()}",
            webhook_url,
            "Deno update",
        )
        return None

    target_dir = _portable_target_dir(YTDL_module)
    deno_path = os.path.join(target_dir, "deno.exe")
    if _installed_deno_version(deno_path) == deno_version:
        print(f"Portable Deno is up to date ({deno_version}).")
        return deno_path

    stage_dir = tempfile.mkdtemp(prefix=".ytdl-deno-", dir=target_dir)
    try:
        deno_zip_url = (
            "https://github.com/denoland/deno/releases/download/"
            f"v{deno_version}/deno-x86_64-pc-windows-msvc.zip"
        )
        print(f"Downloading portable Deno {deno_version}...")
        response = _http_get_with_retry(deno_zip_url, timeout=(10, 120))
        stage_deno = os.path.join(stage_dir, "deno.exe")
        with ZipFile(io.BytesIO(response.content)) as archive:
            with archive.open("deno.exe") as source, open(stage_deno, "wb") as destination:
                shutil.copyfileobj(source, destination)
        if _installed_deno_version(stage_deno) != deno_version:
            raise RuntimeError("Downloaded deno.exe did not report the requested version.")
        os.replace(stage_deno, deno_path)
        print(f"Portable Deno installed at {deno_path}")
        return deno_path
    except Exception:
        report_error_updater(
            f"Failed to download and install portable Deno.\n{traceback.format_exc()}",
            webhook_url,
            "Deno update",
        )
        return None
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def remove_legacy_pot_provider_files(YTDL_module) -> None:
    """Remove obsolete PO Provider artifacts from yt-dlp's portable directory."""
    # TODO(Sakamoto): Remove this temporary compatibility cleanup after legacy
    # installations have had sufficient time to migrate away from PO Provider.
    target_dir = _portable_target_dir(YTDL_module)
    provider_dir = os.path.join(target_dir, "bgutil-ytdlp-pot-provider")
    plugin_path = os.path.join(
        target_dir, "yt-dlp-plugins", "bgutil-ytdlp-pot-provider.zip"
    )
    try:
        if os.path.isdir(provider_dir):
            shutil.rmtree(provider_dir)
            print(f"Removed obsolete PO Provider directory: {provider_dir}")
        if os.path.isfile(plugin_path):
            os.remove(plugin_path)
            print(f"Removed obsolete PO Provider plugin: {plugin_path}")
    except OSError as e:
        print(f"Unable to remove obsolete PO Provider artifacts: {e}", file=sys.stderr)


def program_files_update(webhook_url: str):
    cwd = os.getcwd()
    api_url = "https://api.github.com/repos/minhung1126/YTDL"

    try:
        print("Fetching latest release information...")
        resp = _http_get_with_retry(f"{api_url}/releases/latest", timeout=10)
        release_data = resp.json()
        zipfile_url = release_data['zipball_url']
        print(f'Release zip url: {zipfile_url}')

        print("Downloading latest release zip...")
        zipfile_content_resp = _http_get_with_retry(zipfile_url, timeout=(10, 60))
        zipfile_content = io.BytesIO(zipfile_content_resp.content)

        to_extract_filenames = ["YTDL.py", "YTDL_mul.py"]
        final_extract_list = [f for f in to_extract_filenames if os.path.exists(os.path.join(cwd, f))]
        if "YTDL.py" not in final_extract_list:
            final_extract_list.append("YTDL.py")

        print("Extracting files...")
        with ZipFile(zipfile_content, 'r') as zipfile:
            for filepath in zipfile.namelist():
                filename = os.path.split(filepath)[-1]
                if filename in final_extract_list:
                    print(f"  - Extracting {filename}...")
                    file_content = zipfile.read(filepath)
                    with open(os.path.join(cwd, filename), 'wb') as f:
                        f.write(file_content)

    except Exception:
        error_message = f"Failed to download or extract program files.\n{traceback.format_exc()}"
        report_error_updater(error_message, webhook_url)
        return False

    try:
        import YTDL
        # Since this script is a separate process, we can safely import the newly downloaded module.
        # If this script were part of a larger, long-running app, we'd use importlib.reload().
    except ImportError:
        report_error_updater(f"Failed to import the updated YTDL.py module.\n{traceback.format_exc()}", webhook_url)
        return False

    remove_legacy_pot_provider_files(YTDL)
    ensure_portable_deno(YTDL, webhook_url)
    update_ffmpeg(YTDL, webhook_url)
    
    # --- Final Cleanup ---
    print("==================================================")
    print("Update process completed.")
    print("Non-critical errors might have occurred. Please check the log.")
    print("==================================================")

    print("Cleaning up...")
    if os.path.exists("__pycache__"):
        try:
            shutil.rmtree("__pycache__")
            print("Removed __pycache__ directory.")
        except OSError as e:
            print(f"Error removing __pycache__: {e}")

    return True

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--ensure-ffmpeg":
        webhook_url = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            import YTDL
        except ImportError:
            report_error_updater(
                f"Failed to import YTDL.py for FFmpeg repair.\n{traceback.format_exc()}",
                webhook_url,
                "FFmpeg update",
            )
            sys.exit(1)
        sys.exit(0 if update_ffmpeg(YTDL, webhook_url) else 1)

    if len(sys.argv) > 1 and sys.argv[1] == "--ensure-deno":
        webhook_url = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            import YTDL
        except ImportError:
            report_error_updater(
                f"Failed to import YTDL.py for Deno setup.\n{traceback.format_exc()}",
                webhook_url,
                "Deno update",
            )
            sys.exit(1)
        sys.exit(0 if ensure_portable_deno(YTDL, webhook_url) else 1)

    caller_script_path = sys.argv[1] if len(sys.argv) > 1 else None
    webhook_url = sys.argv[2] if len(sys.argv) > 2 else ""

    update_succeeded = program_files_update(webhook_url)

    if not update_succeeded:
        print("Update failed. The application will not be restarted.")
        input("Press ENTER to exit.")
        sys.exit(1)

    print("Update complete. Restarting application...")
    if caller_script_path and os.path.exists(caller_script_path):
        try:
            subprocess.Popen([sys.executable, caller_script_path])
            sys.exit(0)
        except Exception:
            error_message = f"Failed to restart the application at {caller_script_path}.\n{traceback.format_exc()}"
            report_error_updater(error_message, webhook_url)
            input("Press ENTER to exit.")
    else:
        error_message = f"Could not restart application: Invalid path provided ('{caller_script_path}')."
        report_error_updater(error_message, webhook_url)
        input("Press ENTER to exit.")

if __name__ == "__main__":
    main()
