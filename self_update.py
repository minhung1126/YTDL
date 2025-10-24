import sys
sys.dont_write_bytecode = True
import os
import io
import subprocess
import traceback
import platform
import socket
import shutil
from zipfile import ZipFile

try:
    import requests
except ImportError:
    print("[FATAL] requests library not found. Cannot proceed with update.", file=sys.stderr)
    sys.exit(1)

def report_error_updater(message: str, webhook_url: str):
    """
    A self-contained error reporter for the updater script.
    Prints the error and sends it to a Discord webhook if configured.
    """
    try:
        user = os.getlogin()
    except OSError:
        user = os.environ.get("USERNAME", "N/A")
    computer_info = f"**Computer:** `{socket.gethostname()}` (`{user}`) | **OS:** `{platform.system()} {platform.release()}`"

    print(f"[ERROR] An error occurred during update:\n{computer_info}\n{message}", file=sys.stderr)
    
    if webhook_url:
        try:
            payload = {"content": f"🚨 **YTDL Updater Error:**\n{computer_info}\n**Error:**\n```\n{message[:1600]}\n```"}
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            print(f"[CRITICAL] Failed to send updater error report to Discord: {e}", file=sys.stderr)

def update_binary(YTDL_module, webhook_url: str):
    """Updates binary dependencies like yt-dlp and deno based on versions in the YTDL module."""
    # --- yt-dlp Update ---
    try:
        yt_dlp_channel = YTDL_module.YT_DLP_VERSION_CHANNEL
        yt_dlp_tag = YTDL_module.YT_DLP_VERSION_TAG

        if yt_dlp_channel and yt_dlp_tag:
            print(f"Updating yt-dlp to {yt_dlp_channel}@{yt_dlp_tag}...")
            subprocess.run(['yt-dlp', '--update-to', f'{yt_dlp_channel}@{yt_dlp_tag}'], check=True)
        else:
            report_error_updater("yt-dlp version info is empty in YTDL.py. Skipping update.", webhook_url)

    except AttributeError:
         report_error_updater("Version variables for yt-dlp not found in YTDL.py. Skipping update.", webhook_url)
    except subprocess.CalledProcessError as e:
        report_error_updater(f"yt-dlp update failed: {e}", webhook_url)
    except FileNotFoundError:
        report_error_updater("`yt-dlp` command not found. Skipping yt-dlp update.", webhook_url)
    except Exception:
        report_error_updater(f"An unexpected error occurred during yt-dlp update.\n{traceback.format_exc()}", webhook_url)

    # --- Deno Update ---
    try:
        deno_version = YTDL_module.DENO_VERSION
        if deno_version:
            print(f"Attempting to update deno to version {deno_version}...")
            subprocess.run(['deno', 'upgrade', '--version', deno_version], check=True)
            print("Deno update successful.")
    except AttributeError:
        print("DENO_VERSION not found in YTDL.py. Skipping Deno update.")
    except subprocess.CalledProcessError as e:
        report_error_updater(f"Deno upgrade failed: {e}", webhook_url)
    except FileNotFoundError:
        report_error_updater("`deno` command not found. Skipping Deno update.", webhook_url)
    except Exception:
        report_error_updater(f"An unexpected error occurred during Deno update.\n{traceback.format_exc()}", webhook_url)

def program_files_update(webhook_url: str):
    cwd = os.getcwd()
    api_url = "https://api.github.com/repos/minhung1126/YTDL"

    try:
        print("Fetching latest release information...")
        resp = requests.get(f"{api_url}/releases/latest", timeout=10)
        resp.raise_for_status()
        release_data = resp.json()
        zipfile_url = release_data['zipball_url']
        print(f'Release zip url: {zipfile_url}')

        print("Downloading latest release zip...")
        zipfile_content_resp = requests.get(zipfile_url, timeout=30)
        zipfile_content_resp.raise_for_status()
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
            os.execv(sys.executable, [sys.executable, caller_script_path])
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