import json
import subprocess


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
            with open(self.meta_filepath, 'r') as f:
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
            'yt-dlp', '-F',
            '-S', 'res,hdr,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:avc1:m4a,+codec:av01:opus,vbr',
            self.url,
        ]
        subprocess.run(
            args
        )


class Playlist:
    ...


def download_from_url(url: str):
    ...


def main():
    Video("https://www.youtube.com/watch?v=YTO65C2Brg4").download()
    Video("https://www.youtube.com/watch?v=2n0OS1R0JFc").download()


if __name__ == "__main__":
    main()
