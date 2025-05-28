import os
import json
import subprocess
import re
import logging
from urllib.parse import urlparse, parse_qs

META_DIR = os.path.join(os.getcwd(), 'meta')
logging.getLogger().setLevel(logging.DEBUG)

class Video:
    def __init__(self, meta_filepath: str):
        VIDEO_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        PLAYLIST_TEMPLATE = r"%(playlist)s/%(title)s.%(id)s.%(ext)s"

        self.meta_filepath = meta_filepath
        self.meta = self._read_meta()
        self.title = self.meta.get('title', 'N/A')
        self.url = self.meta.get('webpage_url', 'N/A')
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


    def dump_error_msg(self, error_msg: str):
        ...

    def download(self):
        args = [
            'yt-dlp',
            '-f', 'bv+ba',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            '--load-info-json', self.meta_filepath,
        ]

        logging.info(f"Downloading {self.title} from {self.url}")
        logging.debug(f"args: {args}")
        result = subprocess.run(
            args,
            capture_output=True,
            encoding='utf-8',
            errors='ignore'
        )
        logging.debug(f"stdout: {result.stdout}")
        logging.debug(f"stderr: {result.stderr}")

        if result.returncode != 0:
            self.dump_error_msg(result.stdout + "\n" + result.stderr)
            return

        else:
            logging.info(f"Downloaded {self.title} successfully.")
            try:
                os.remove(self.meta_filepath)
                logging.info(
                    f"Deleted meta file {self.meta_filepath} after download.")
            except FileNotFoundError:
                logging.error(
                    f"Meta file {self.meta_filepath} not found for deletion.")
                self.dump_error_msg(
                    f"Meta file {self.meta_filepath} not found for deletion.")
            finally:
                if os.path.isdir(META_DIR) and not os.listdir(META_DIR):
                    logging.info(f"Deleting empty directory {META_DIR}")
                    os.rmdir(META_DIR)
                return

class Playlist:
    ...


def download_from_url(url: str):
    args = [
        'yt-dlp',
        '--no-download',
        '--no-write-playlist-metafiles',
        '-o', os.path.join(META_DIR, f"%(title)s.%(id)s.%(ext)s"),
        '--write-info-json',
        url
    ]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if '/playlist' in parsed.path:  # is desired to download as a playlist
        pass
    else:
        args.append('--no-playlist')

    subprocess.run(args)


def load_videos() -> list[Video]:
    videos = (
        Video(os.path.join(META_DIR, filename))
        for filename in os.listdir(META_DIR)
    )

    return videos


def parse_user_action():
    if os.path.isdir(META_DIR):
        # Ask if resume download
        ...

    resp = input("URL: ")
    download_from_url(resp)


def main():
    parse_user_action()
    videos = load_videos()
    for vid in videos:
        vid.download()
    # Video("https://www.youtube.com/watch?v=YTO65C2Brg4").download()
    # Video("https://www.youtube.com/watch?v=2n0OS1R0JFc").download()


if __name__ == "__main__":
    main()
