import os
import io
import subprocess
import sys
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

try:
    sys.dont_write_bytecode = True
except (ImportError, AttributeError):
    pass

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

def program_files_update(webhook_url: str):
    try:
        cwd = os.getcwd()
        api_url = "https://api.github.com/repos/minhung1126/YTDL"

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

        must_extract_filenames = ['ytdlp_version_info.py']
        to_extract_filenames = ["YTDL.py", "YTDL_mul.py"]
        
        final_extract_list = [f for f in to_extract_filenames if os.path.exists(os.path.join(cwd, f))] + must_extract_filenames

        print("Extracting files...")
        with ZipFile(zipfile_content, 'r') as zipfile:
            for filepath in zipfile.namelist():
                filename = os.path.split(filepath)[-1]
                if filename in final_extract_list:
                    print(f"  - Extracting {filename}...")
                    file_content = zipfile.read(filepath)
                    with open(os.path.join(cwd, filename), 'wb') as f:
                        f.write(file_content)

        from ytdlp_version_info import YT_DLP_VERSION_CHANNEL, YT_DLP_VERSION_TAG
        print(f"Updating yt-dlp to {YT_DLP_VERSION_CHANNEL}@{YT_DLP_VERSION_TAG}...")
        subprocess.run(['yt-dlp', '--update-to', f'{YT_DLP_VERSION_CHANNEL}@{YT_DLP_VERSION_TAG}'], check=True)

        os.remove('ytdlp_version_info.py')

        print("==================================================")
        print("Update process completed successfully.")
        print("==================================================")

        print("Cleaning up...")
        if os.path.exists("__pycache__"):
            try:
                shutil.rmtree("__pycache__")
                print("Removed __pycache__ directory.")
            except OSError as e:
                print(f"Error removing __pycache__: {e}")

        return True

    except Exception:
        error_message = f"An error occurred in program_files_update.\n{traceback.format_exc()}"
        report_error_updater(error_message, webhook_url)
        return False

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
            if platform.system() == "Windows":
                # Use subprocess.Popen with DETACHED_PROCESS for a more robust restart
                subprocess.Popen(
                    [sys.executable, caller_script_path],
                    creationflags=subprocess.DETACHED_PROCESS,
                    close_fds=True
                )
            else:
                subprocess.Popen([sys.executable, caller_script_path])
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
