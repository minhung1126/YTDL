# Using yt-dlp

import json
import os
from datetime import datetime
import sys
import shutil
import subprocess

try:
    import colorama
    from colorama import Fore, Style
except ImportError:
    import subprocess
    subprocess.run(['pip', 'install', 'colorama'])
finally:
    import colorama
    from colorama import Fore, Style


class YTDLError(BaseException):
    pass


class Video:
    def __init__(self, *args, url: str = "", meta_path: str = "", dest_dir: str = "") -> None:
        """A video entity. A url or meta_path must be provided.

        Args:
            url (str, optional): _description_. Defaults to "".
            meta_path (str, optional): _description_. Defaults to "".
        """
        self._VCODECS = ["avc1", "vp09", "vp9", "av01"]
        self._SDR_FILENAME_TEMPLATE = r"%(title)s.%(id)s.%(ext)s"
        self._HDR_FILENAME_TEMPLATE = r"%(title)s.HDR.%(id)s.%(ext)s"

        self._valid = True
        self._invalid_msg = ""

        try:
            if url == "" and meta_path == "":
                raise YTDLError("URL or meta_path must be provided by kargs")
            elif meta_path != "":
                self._meta_path = os.path.join(
                    '.', os.path.normpath(meta_path))
                self._meta = self._read_meta()
                self.webpage_url = self._get_webpage_url()
            else:
                self._meta_path = self._dl_meta(url=url)
                self._meta = self._read_meta()
                self.webpage_url = self._get_webpage_url()
        except YTDLError as e:
            self._valid = False
            self._invalid_msg = str(e)
            with open('./ERROR_MESSAGE.txt', 'w+', encoding="utf-8") as f:
                f.write(self._invalid_msg + '\n')
            print(
                Fore.RED + f"Fail download: {self._invalid_msg}" + Style.RESET_ALL)
            return
        else:
            print(f"Start download: {self.webpage_url}")

        # If destdir="", then it will generate '.'
        self.custom_dest_dir = os.path.normpath(dest_dir)
        self._dest_dir_template = self._get_dest_dir_template()

        self.id = self._meta['id']
        self.title = self._meta['title']
        self.is_hdr = self._get_is_hdr()
        self._SDR_height = self._get_SDR_height()
        self._HDR_height = self._get_HDR_height()

        self._targets = self._get_target_formats()

        # Stimulate the result filepath, use to judge if downloaded
        # Can be accessed
        self.SDR_dest_filepath = self._get_dest_filepath(is_HDR=False)
        self.HDR_dest_filepath = self._get_dest_filepath(is_HDR=True)

    def _cleanup_temp(self) -> None:
        for dirpath, dirnames, filenames in os.walk("./temp/"):
            if os.listdir(dirpath) == []:
                shutil.rmtree(dirpath)
        if os.path.isdir("./temp/") and os.listdir("./temp/") == []:
            shutil.rmtree("./temp/")

        return

    def _dl_meta(self, url) -> str:
        # In Wondows, upper case and lowercase is considered same
        # To prevent case-problems, add a isotime.
        # e.g. AAABBBCCC.info.json & AAABBBccc.info.json
        args = [
            'yt-dlp',
            '--encoding', 'utf-8',
            '--print', fr"./temp/{datetime.now().strftime(r'%Y%m%d%H%M%S%f')}.%(id)s.info.json",
            '--print', '%()j',
            url
        ]

        result = subprocess.run(
            args,
            capture_output=True,
            encoding='utf-8'
        )

        if not result.returncode == 0:
            raise YTDLError(
                f"Can't download the meta of this video (url: {url})")

        lines = result.stdout.splitlines()

        if not os.path.isdir(os.path.join('.', 'temp')):
            os.mkdir(os.path.join('.', 'temp'))

        meta_path = os.path.join('.', os.path.normpath(lines[0]))
        with open(meta_path, 'w', encoding='utf-8', errors='ignore') as f:
            f.write(lines[1])

        return meta_path

    def _read_meta(self) -> dict:
        with open(self._meta_path, 'r', encoding='utf-8') as f:
            data = json.loads(f.read())
        return data

    def _renew_formats(self) -> None:
        result = subprocess.run(
            [
                'yt-dlp',
                '--print', '%()j',
                '--encoding', 'utf-8',
                self.webpage_url
            ],
            capture_output=True,
            encoding='utf-8'
        )
        if not result.returncode == 0:
            #! Error
            ...

        # [1:-2] remove '"'
        self._meta['formats'] = json.loads(result.stdout.strip())['formats']
        with open(self._meta_path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(self._meta))

        return None

    def _dump_info(self, path) -> str:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(json.dumps(self._meta, ensure_ascii=False))

        return path

    def _get_webpage_url(self) -> str:
        return self._meta.get('webpage_url', '')

    def _get_is_hdr(self) -> bool:
        return not self._meta['dynamic_range'] == "SDR"

    def _get_SDR_height(self) -> int:
        # Filter out SDR formats
        SDR_formats = filter(
            lambda x: x.get('dynamic_range', 'SDR') == "SDR",
            self._meta['formats']
        )

        # Make height list
        SDR_format_height = [f.get('height', 0)
                             for f in SDR_formats] + [0]

        # Remove None
        while None in SDR_format_height:
            SDR_format_height.remove(None)

        return max(SDR_format_height)

    def _get_HDR_height(self) -> int:
        # Filter out HDR formats
        HDR_formats = filter(
            lambda x: x.get('dynamic_range', 'SDR') != "SDR",
            self._meta['formats']
        )

        # Make height list
        HDR_format_height = [f.get('height', 0)
                             for f in HDR_formats] + [0]

        # Remove None
        while None in HDR_format_height:
            HDR_format_height.remove(None)

        return max(HDR_format_height)

    def _get_dest_dir_template(self):
        if 'playlist' in self._meta and self._meta['playlist'] is not None:
            return os.path.join(self.custom_dest_dir, r"%(playlist)s")
        else:
            return self.custom_dest_dir

    def _get_dest_filepath(self, is_HDR: bool):
        args = [
            'yt-dlp',
            '--load-info-json', self._meta_path,
            '--encoding', 'utf-8',
            '--print', os.path.join(
                self._dest_dir_template,
                self._HDR_FILENAME_TEMPLATE if is_HDR else self._SDR_FILENAME_TEMPLATE
            )
        ]

        result = subprocess.run(
            args,
            capture_output=True,
            encoding='utf-8',
        )

        if not result.returncode == 0:
            #! Fail
            ...

        else:
            return os.path.splitext(result.stdout.strip())[0] + ".mkv"

    def _get_target_formats(self):
        all_formats = self._meta['formats']

        # Filter out coresponse height
        SDR_formats = [
            f
            for f in all_formats
            if f.get('height', 0) == self._SDR_height
            and f.get('dynamic_range', 'SDR') == "SDR"
        ]
        HDR_formats = [
            f
            for f in all_formats
            if f.get('height', 0) == self._HDR_height
            and f.get('dynamic_range', 'SDR') != "SDR"
        ]

        # Choose target based on vcodec
        targets = []
        for formats in [SDR_formats, HDR_formats]:
            # Youtube Premium: Higher bit rate is priority
            premium_formats = list(filter(
                lambda f: "Premium" in f.get('format_note', ''),
                formats
            ))

            if premium_formats:  # Having premium bitrate
                targets += premium_formats
                break

            vcodecs_to_format_hash = {
                f.get('vcodec').split('.')[0]: f
                for f in formats
            }

            for vcodec in self._VCODECS:
                if vcodec in vcodecs_to_format_hash:
                    targets.append(
                        vcodecs_to_format_hash[vcodec]
                    )
                    break

        return targets

    def download(self):
        def gen_format_code(f: dict) -> str:
            vcodec_code = f.get('format_id')
            if "avc1" in f.get('vcodec'):
                acodec_code = 140
            else:
                acodec_code = 251

            return f"{vcodec_code}+{acodec_code}"

        def gen_path(f: dict) -> str:
            if self.custom_dest_dir != "":
                path = self.custom_dest_dir
            else:
                path = "."
                if "playlist" in self._meta:
                    path += "%(playlist)s/"

            path = os.path.join(path, "%(title)s")
            if target['dynamic_range'] != "SDR":
                path += ".HDR"
            path += ".%(id)s"
            path += ".%(ext)s"

            return path

        # check if valid
        if not self._valid:
            return

        # check if download
        dest_dir = os.path.split(self.SDR_dest_filepath)[0]
        if os.path.isdir(dest_dir):
            no_ext_filename = os.path.splitext(
                os.path.split(self.SDR_dest_filepath)[-1])[0]
            video_filenames = os.listdir(dest_dir)
            if (
                no_ext_filename + ".mkv" in video_filenames and
                no_ext_filename + ".temp.mkv" not in video_filenames
            ):
                print(f"Video ({self.webpage_url}) is downloaded")
                os.remove(self._meta_path)
                self._cleanup_temp()
                return

        # The download url will expire
        self._renew_formats()

        # Dump to temp meta file after renew, then use this meta file to download
        temp_meta_path = self._dump_info(f'./temp/temp.{self.id}.info.json')

        result_codes = []
        for target in self._targets:
            args = [
                'yt-dlp',
                '--load-info-json', temp_meta_path,
                '--embed-subs',
                '--sub-langs', 'all,-live_chat',
                '--embed-thumbnail',
                '--embed-metadata',
                '--merge-output-format', 'mkv',
                '--remux-video', 'mkv',
                '--no-playlist',
                '--encoding', 'utf-8',
                '--concurrent-fragments', '8',
                '--no-post-overwrites',
                '-f', gen_format_code(target),
                # gen_path(target),
                # '-o', self.HDR_dest_filepath if target['dynamic_range'] != "SDR" else self.SDR_dest_filepath
            ]

            if target['dynamic_range'] != "SDR":
                args.extend([
                    '-o',
                    os.path.join(self._dest_dir_template,
                                 self._HDR_FILENAME_TEMPLATE)
                ])
            else:
                args.extend([
                    '-o',
                    os.path.join(self._dest_dir_template,
                                 self._SDR_FILENAME_TEMPLATE)
                ])

            result = subprocess.run(args)

            result_codes.append(result.returncode)

        if all([result == 0 for result in result_codes]):
            os.remove(self._meta_path)
            os.remove(temp_meta_path)

        self._cleanup_temp()

        return


class Playlist:
    def __init__(self, url) -> None:
        self._url = url

        self._meta_dir = self._dl_meta()

    def _dl_meta(self):
        args = [
            'yt-dlp',
            '--write-info-json',
            '--skip-download',
            '--no-playlist',
            '--no-write-playlist-metafiles',
            '--encoding', 'utf-8',
            '-o', './temp/%(playlist_id)s/%(id)s',
            self._url
        ]

        result = subprocess.run(args)
        if not result.returncode == 0:
            #! Error
            ...

        args = [
            'yt-dlp',
            '--playlist-items', '1',
            '--print', './temp/%(playlist_id)s',
            self._url
        ]
        playlist_dir_result = subprocess.run(
            args,
            capture_output=True,
            encoding='utf-8'
        )
        if not playlist_dir_result.returncode == 0:
            #! Error
            ...

        playlist_dir = playlist_dir_result.stdout.strip()

        return playlist_dir

    def download(self):
        for filename in os.listdir(self._meta_dir):
            filepath = os.path.join(self._meta_dir, filename)
            Video(meta_path=filepath).download()

        return


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

    input(Fore.GREEN + 'Update done. Press ENTER to close. Restart it manually.' + Style.RESET_ALL)


def download_video_url(url):
    """

    Args:
        urls
    """
    if "playlist?list=" in url:
        playlist = Playlist(url)
        playlist.download()
    else:
        video = Video(url=url)
        video.download()
    return


def download_video_meta_dir():
    if not os.path.isdir('./temp'):
        return

    for dirpath, dirnames, filenames in os.walk('./temp'):
        for filename in filenames:
            meta_path = os.path.join(dirpath, filename)
            if filename.startswith('temp.'):
                os.remove(meta_path)
            else:
                video = Video(meta_path=meta_path)
                video.download()

    return


def user_input_dispatcher():
    """
    Auto trigger info download
    """
    url = input("URL:")
    if url.lower() == 'update':
        self_update()
        sys.exit()
    else:
        return download_video_url(url)


def main():
    explanation = [
        "這是下載YouTube影片或播放清單的程式，請在下方貼上網址或選擇是否繼續下載",
        "優先下載高解析度（8K>4K>2K>1080>720p>480p...）",
        "相同解析度時，優先下載AVC>VP9>AV1編碼",
        "遇有HDR影片，則依上述二規則下載HDR和非HDR影片",
        "輸入'update'可以更新",
        "播放清單會自動下載到資料夾中",
        "下載過的檔案會自動跳過，不會重新下載",
        "若下載失敗，會自動跳過",
        "若要繼續下載，請在系統詢問時按'Y'後按'ENTER'即可",
        "若不要繼續下載，請在系統詢問時按'N'後按'ENTER'即可",
    ]
    print("\n".join(f"{explanation.index(e)+1}. {e}" for e in explanation))
    print("=" * 72)
    while True:
        if os.path.isdir("./temp/") and os.listdir("./temp/") != []:
            resp = input("Continue downloading?(Y/N) ").lower()
            if resp == "y":
                download_video_meta_dir()
            else:
                shutil.rmtree("./temp/")
                continue
        else:
            user_input_dispatcher()


if __name__ == "__main__":
    main()
