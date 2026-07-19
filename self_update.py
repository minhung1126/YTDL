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

def update_ffmpeg(YTDL_module, webhook_url: str, version_tag: str = None):
    """Updates FFmpeg/FFprobe binaries if needed."""
    try:
        # 1. Configuration
        ffmpeg_tag = version_tag
        if not ffmpeg_tag:
            if hasattr(YTDL_module, 'Config'):
                ffmpeg_tag = getattr(YTDL_module.Config, 'FFMPEG_VERSION_TAG', None)

        if not ffmpeg_tag:
            return

        # 2. Target Directory
        # Resolve yt-dlp location to find where to put ffmpeg
        yt_dlp_path = shutil.which('yt-dlp')
        target_dir = os.getcwd() 
        if yt_dlp_path:
            target_dir = os.path.dirname(yt_dlp_path)
            
        ffmpeg_exe = os.path.join(target_dir, 'yt-dlp-ffmpeg.exe')
        
        # 3. Version Check
        should_update = False
        if not os.path.exists(ffmpeg_exe):
            print(f"FFmpeg not found at {ffmpeg_exe}. Downloading...")
            should_update = True
        else:
            try:
                # Run ffmpeg -version
                res = subprocess.run([ffmpeg_exe, '-version'], capture_output=True, text=True, encoding='utf-8', errors='ignore')
                
                # Extract --extra-version=YYYYMMDD
                match = re.search(r'--extra-version=(\d+)', res.stdout)
                
                if match:
                    installed_ver = int(match.group(1))
                    if ffmpeg_tag and ffmpeg_tag.isdigit():
                         target_ver = int(ffmpeg_tag)
                         if target_ver > installed_ver:
                             print(f"FFmpeg version outdated ({installed_ver} < {target_ver}). Updating...")
                             should_update = True
                         else:
                             print(f"FFmpeg is up to date ({installed_ver} >= {target_ver}).")
                    else:
                        # Fallback for non-numeric tags
                         if ffmpeg_tag.lower() not in res.stdout.lower():
                            print(f"FFmpeg version match failed (Expected: {ffmpeg_tag}). Updating...")
                            should_update = True
                else:
                    print("Could not determine FFmpeg version (no --extra-version). Updating...")
                    should_update = True
                    
            except Exception:
                print("Error checking FFmpeg version. Force updating...")
                should_update = True
        
        if not should_update:
            return

        # 4. Download and Extract
        print(f"Downloading FFmpeg {ffmpeg_tag}...")
        
        download_tag = "latest"
        zip_url = f"https://github.com/yt-dlp/FFmpeg-Builds/releases/download/{download_tag}/ffmpeg-master-{download_tag}-win64-gpl.zip"
        
        print(f"Download URL: {zip_url}")
        resp = _http_get_with_retry(zip_url, timeout=(10, 300))
        
        print("Extracting FFmpeg binaries...")
        with ZipFile(io.BytesIO(resp.content)) as z:
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
                        
        print(f"FFmpeg update completed. Binaries placed in {target_dir}")

        # TODO: Remove this legacy cleanup in future versions (e.g. after 2026.06)
        # Cleanup legacy non-prefixed binaries
        for legacy_bin in ['ffmpeg.exe', 'ffprobe.exe', 'ffplay.exe']:
            legacy_path = os.path.join(target_dir, legacy_bin)
            if os.path.exists(legacy_path):
                try:
                    os.remove(legacy_path)
                    print(f"Removed legacy binary: {legacy_bin}")
                except OSError as e:
                    print(f"Failed to remove legacy binary {legacy_bin}: {e}")

    except Exception as e:
        report_error_updater(f"FFmpeg update failed: {e}\n{traceback.format_exc()}", webhook_url)

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


def _extract_source_archive(archive_bytes: bytes, destination: str):
    """Extract a GitHub source archive while rejecting path traversal and links."""
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        files = [info for info in archive.infolist() if info.filename and not info.is_dir()]
        roots = {info.filename.split("/", 1)[0] for info in files if "/" in info.filename}
        if len(roots) != 1:
            raise ValueError("Provider source archive has an unexpected root layout.")
        root = roots.pop() + "/"
        destination_abs = os.path.abspath(destination)
        for info in files:
            if not info.filename.startswith(root):
                raise ValueError(f"Unexpected archive entry: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Provider source archive contains a symbolic link: {info.filename}")
            relative_path = info.filename[len(root):]
            target_path = os.path.abspath(os.path.join(destination_abs, *relative_path.split("/")))
            if os.path.commonpath([destination_abs, target_path]) != destination_abs:
                raise ValueError(f"Unsafe archive entry: {info.filename}")
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with archive.open(info) as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)


def update_pot_provider(YTDL_module, webhook_url: str, deno_path: str) -> bool:
    """Install the pinned BgUtils plugin and Deno script source atomically."""
    version = _config_value(YTDL_module, "BGUTIL_POT_PROVIDER_VERSION")
    plugin_filename = _config_value(YTDL_module, "BGUTIL_POT_PLUGIN_FILENAME")
    provider_dirname = _config_value(YTDL_module, "BGUTIL_POT_PROVIDER_DIRNAME")
    marker_filename = _config_value(YTDL_module, "BGUTIL_POT_MARKER_FILENAME")
    if not all((version, plugin_filename, provider_dirname, marker_filename)):
        report_error_updater("BgUtils PO provider configuration is incomplete.", webhook_url, "PO provider update")
        return False

    target_dir = _portable_target_dir(YTDL_module)
    plugin_dir = os.path.join(target_dir, "yt-dlp-plugins")
    plugin_path = os.path.join(plugin_dir, plugin_filename)
    provider_dir = os.path.join(target_dir, provider_dirname)
    stage_dir = tempfile.mkdtemp(prefix=".ytdl-bgutil-", dir=target_dir)
    backup_dir = None
    provider_replaced = False
    try:
        os.makedirs(plugin_dir, exist_ok=True)
        plugin_url = (
            "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/"
            f"{version}/{plugin_filename}"
        )
        source_url = (
            "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/refs/tags/"
            f"{version}.zip"
        )
        print(f"Downloading BgUtils PO provider {version}...")
        plugin_response = _http_get_with_retry(plugin_url, timeout=(10, 120))
        source_response = _http_get_with_retry(source_url, timeout=(10, 120))

        with ZipFile(io.BytesIO(plugin_response.content)) as plugin_archive:
            if not any(name.startswith("yt_dlp_plugins/") for name in plugin_archive.namelist()):
                raise ValueError("Provider plugin archive does not contain yt_dlp_plugins.")

        stage_plugin = os.path.join(stage_dir, plugin_filename)
        with open(stage_plugin, "wb") as f:
            f.write(plugin_response.content)

        stage_provider = os.path.join(stage_dir, provider_dirname)
        _extract_source_archive(source_response.content, stage_provider)
        server_home = os.path.join(stage_provider, "server")
        script_path = os.path.join(server_home, "src", "generate_once.ts")
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Provider Deno script is missing: {script_path}")

        print("Initializing BgUtils PO provider with portable Deno...")
        result = subprocess.run(
            [deno_path, "install", "--allow-scripts=npm:canvas", "--frozen"],
            cwd=server_home,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Deno dependency installation failed:\n{result.stdout[-8000:]}")
        if not os.path.isdir(os.path.join(server_home, "node_modules")):
            raise FileNotFoundError("Deno did not create the provider node_modules directory.")

        if os.path.isdir(provider_dir):
            backup_dir = os.path.join(stage_dir, "previous-provider")
            os.replace(provider_dir, backup_dir)
        os.replace(stage_provider, provider_dir)
        provider_replaced = True
        os.replace(stage_plugin, plugin_path)
        marker_path = os.path.join(provider_dir, marker_filename)
        with open(marker_path, "w", encoding="utf-8") as marker:
            json.dump({"version": version, "installed_at": datetime.now(timezone.utc).isoformat()}, marker)

        if backup_dir and os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir, ignore_errors=True)
        print(f"BgUtils PO provider {version} is ready.")
        return True
    except Exception:
        if provider_replaced and backup_dir and os.path.isdir(backup_dir):
            try:
                shutil.rmtree(provider_dir, ignore_errors=True)
                os.replace(backup_dir, provider_dir)
            except OSError:
                pass
        report_error_updater(
            f"Failed to install BgUtils PO provider.\n{traceback.format_exc()}",
            webhook_url,
            "PO provider update",
        )
        return False
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def ensure_pot_provider(YTDL_module, webhook_url: str) -> bool:
    deno_path = ensure_portable_deno(YTDL_module, webhook_url)
    return bool(deno_path and update_pot_provider(YTDL_module, webhook_url, deno_path))


def update_binary(YTDL_module, webhook_url: str):
    """Updates portable Deno, the PO provider, and FFmpeg after an app update."""
    ensure_pot_provider(YTDL_module, webhook_url)
    update_ffmpeg(YTDL_module, webhook_url)

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

    update_binary(YTDL, webhook_url)
    
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
    if len(sys.argv) > 1 and sys.argv[1] == "--ensure-pot-provider":
        webhook_url = sys.argv[2] if len(sys.argv) > 2 else ""
        try:
            import YTDL
        except ImportError:
            report_error_updater(
                f"Failed to import YTDL.py for PO provider setup.\n{traceback.format_exc()}",
                webhook_url,
                "PO provider update",
            )
            sys.exit(1)
        sys.exit(0 if ensure_pot_provider(YTDL, webhook_url) else 1)

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
