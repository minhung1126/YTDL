import os
import json
import shutil
import subprocess
import re
from urllib.parse import urlparse, parse_qs

# Script Configuration
META_DIR = os.path.join(os.getcwd(), 'meta')
# yt-dlp Environment
EXECUTABLE = 'yt-dlp'
CONCURRENT_FRAGMENTS = "8"
PROGRESS_BAR_SECONDS = "2"

class Video:
    def __init__(self, meta_filepath: str):
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"

        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.template = PLAYLIST_TEMPLATE if self.meta and 'playlist' in self.meta else VIDEO_TEMPLATE

        self.logs = ""

    def _read_meta(self):
        try:
            with open(self.meta_filepath, 'r', encoding='utf-8') as f:
                meta = json.loads(f.read())
            return meta
        except FileNotFoundError:
            ...
            return {}

    def logging(self, log: str):
        self.logs += log + "\n"
        print(log)
        return

    def dump_error_msg(self, error_msg: str):
        ...

    def download(self):
        args = [
            EXECUTABLE,
            '-f', 'bv+ba',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            '--load-info-json', self.meta_filepath,
            '--embed-subs',
            '--sub-langs', 'all,-live_chat',
            '--embed-thumbnail',
            '--embed-metadata',
            '--merge-output-format', 'mkv',
            '--remux-video', 'mkv',
            '--encoding', 'utf-8',
            '--concurrent-fragments', CONCURRENT_FRAGMENTS,
            '--progress-delta', PROGRESS_BAR_SECONDS,
            '-o', self.template
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
            ...
            return

        try:
            os.remove(self.meta_filepath)
        except:
            ...

        return


class Playlist:
    ...


def dl_meta_from_url(url: str):
    args = [
        EXECUTABLE,
        '--no-download',
        '--no-write-playlist-metafiles',
        '-o', os.path.join(META_DIR, f"%(title)s.%(id)s.info.json"),
        '--write-info-json',
        '--encoding', 'utf-8',
        url
    ]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if '/playlist' in parsed.path:  # is desired to download as a playlist
        pass
    else:
        args.append('--no-playlist')

    subprocess.run(args)


def load_videos_from_meta() -> list[Video]:
    videos = (
        Video(os.path.join(META_DIR, filename))
        for filename in os.listdir(META_DIR)
    )

    return videos


def self_update():
    try:
        import requests
    except:
        subprocess.run(["pip", "install", "requests"])
        import requests

    cwd = os.getcwd()

    # Download the update file
    base_url = "https://raw.githubusercontent.com/minhung1126/YTDL/main/"

    # Self update python file
    resp = requests.get(f"{base_url}self_update.py")
    if not resp.ok:
        #! Skip
        print("Fail to download self_update.py")

    self_update_file_path = os.path.join(cwd, "self_update.py")
    with open(self_update_file_path, 'wb') as f:
        f.write(resp.content)

    subprocess.run(["python", "self_update.py"], cwd=os.getcwd())

    os.remove(self_update_file_path)

    input('Update done. Press ENTER to close. Restart it manually.')


def parse_user_action():
    if os.path.isdir(META_DIR):
        # Ask if resume download
        resp = input("Continue downloading?(Y/N) ").lower()
        if resp == 'y':
            videos = load_videos_from_meta()
            for v in videos:
                v.download()
        elif resp == 'n':
            # Clear meta directory
            shutil.rmtree(META_DIR)
        else:
            print("Invalid input. Exiting.")
            return parse_user_action()


    resp = input("URL: ")
    if resp == "update":
        self_update()

    dl_meta_from_url(resp)


def main():
    parse_user_action()
    videos = load_videos_from_meta()
    for vid in videos:
        vid.download()
    # Video("https://www.youtube.com/watch?v=YTO65C2Brg4").download()
    # Video("https://www.youtube.com/watch?v=2n0OS1R0JFc").download()


if __name__ == "__main__":
    main()
