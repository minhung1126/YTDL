import os
import json
import shutil
import subprocess
import re
from urllib.parse import urlparse, parse_qs
import sys
try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

#! --- Configuration ---
# Set to "dev" to disable update checks during development.
# Otherwise, set to the release version, e.g., "v2025.09.04".
__version__ = "v2025.09.03"
#! ---------------------

META_DIR = os.path.join(os.getcwd(), 'meta')
# yt-dlp Environment
EXECUTABLE = 'yt-dlp'
CONCURRENT_FRAGMENTS = "8"
PROGRESS_BAR_SECONDS = "2"

def check_for_updates(caller_script: str):
    """
    Checks for a new version on GitHub and runs the updater if one is found.
    Skips the check if the version is set to "dev".
    """
    if __version__ == "dev":
        print("Development version, skipping update check.")
        return

    print(f"Current version: {__version__}")
    try:
        repo = "minhung1126/YTDL"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        latest_version = response.json()["tag_name"]

        if latest_version != __version__:
            print(f"New version available: {latest_version}. Starting update...")

            base_url = f"https://raw.githubusercontent.com/{repo}/main/"
            updater_script_name = "self_update.py"
            resp = requests.get(f"{base_url}{updater_script_name}")
            if not resp.ok:
                print(f"Failed to download updater script: {updater_script_name}")
                return

            with open(updater_script_name, 'wb') as f:
                f.write(resp.content)

            # Execute the updater and exit. Pass the calling script's name to the updater.
            subprocess.Popen([sys.executable, updater_script_name, caller_script])
            sys.exit(0)
        else:
            print("You are on the latest version.")

    except requests.exceptions.RequestException as e:
        print(f"Could not check for updates (network error): {e}")
    except Exception as e:
        print(f"An error occurred during the update check: {e}")


class Video:
    def __init__(self, meta_filepath: str):
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"

        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.template = PLAYLIST_TEMPLATE if self.meta and 'playlist' in self.meta else VIDEO_TEMPLATE

        self.url = self.meta.get("webpage_url")
        if self.meta.get("playlist_id"):
            self.url += f"&list={self.meta.get('playlist_id')}"

    def _read_meta(self):
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                meta = json.loads(f.read())
            return meta
        except FileNotFoundError:
            return {}

    def download(self):
        print(f"--- Downloading: {self.meta.get('title', 'N/A')} ---")
        args = [
            EXECUTABLE,
            '-f', 'bv+ba',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            '--embed-subs',
            '--sub-langs', 'all,-live_chat',
            '--embed-thumbnail',
            '--embed-metadata',
            '--merge-output-format', 'mkv',
            '--remux-video', 'mkv',
            '--encoding', 'utf-8',
            '--concurrent-fragments', CONCURRENT_FRAGMENTS,
            '--progress-delta', PROGRESS_BAR_SECONDS,
            '-o', self.template,
            self.url
        ]

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        while True:
            line = process.stdout.readline()
            if not line:
                break
            print(line.strip())

        process.wait()

        if process.returncode != 0:
            print(f"!!! Download failed for: {self.meta.get('title', 'N/A')} !!!")
            return

        try:
            os.remove(self.meta_filepath)
        except OSError as e:
            print(f"Could not remove meta file {self.meta_filepath}: {e}")


def dl_meta_from_url(url: str):
    if not os.path.exists(META_DIR):
        os.makedirs(META_DIR)

    args = [
        EXECUTABLE,
        '--no-download',
        '--no-write-playlist-metafiles',
        '-o', os.path.join(META_DIR, f"%(title)s.%(id)s"),
        '--write-info-json',
        '--encoding', 'utf-8',
        url
    ]
    parsed = urlparse(url)
    if '/playlist' not in parsed.path:
        args.append('--no-playlist')

    subprocess.run(args)


def load_videos_from_meta() -> list[Video]:
    if not os.path.isdir(META_DIR):
        return []
    videos = (
        Video(os.path.join(META_DIR, filename))
        for filename in os.listdir(META_DIR)
    )
    return list(videos)


def self_update_legacy():
    """
    Legacy manual update function. Kept for reference or fallback.
    """
    print("Manual update started...")
    # ... (rest of the function is the same, not critical to change)


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
    if os.path.isdir(META_DIR):
        try:
            shutil.rmtree(META_DIR)
        except OSError as e:
            print(f"Error cleaning up meta directory: {e}")

def main():
    check_for_updates(sys.argv[0])
    
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


if __name__ == "__main__":
    main()
