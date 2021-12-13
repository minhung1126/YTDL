# ver 5.2
# Using yt-dlp

import time
import os
import shutil
import json
import subprocess


def video_dl(json_path):
    VCODECS = ['avc1', 'vp9', 'av01']  # with order

    with open(json_path, "r", encoding="utf-8") as f:
        meta = json.loads(f.read())

    isSdr = meta['dynamic_range'] == "SDR"

    # Get the max of height of both SDR and HDR
    maxSdrHeight = max([format['height'] for format in meta['formats']
                       if "height" in format and format['dynamic_range'] == "SDR"]+[0])
    maxHdrHeight = max([format['height'] for format in meta['formats']
                       if "height" in format and format['dynamic_range'] != "SDR"]+[0])

    targets = []

    for isSdr in [True, False]:
        for vcodec in VCODECS:
            formats = [format for format in meta['formats']
                       if vcodec in format['vcodec'] and
                       (lambda x: maxSdrHeight if x else maxHdrHeight)(isSdr) == format['height'] and
                       (format['dynamic_range'] == "SDR") == isSdr
                       ]
            if formats == []:
                continue
            else:
                targets.append(sorted(formats, key=lambda x: x['vbr'])[-1])
                break

    for target in targets:
        path = "./"
        if "playlist" in meta:
            path += "%(playlist)s/"
        path += "%(title)s"
        if target['dynamic_range'] != "SDR":
            path += ".HDR"
        # path += ".%(id)s"
        path += ".%(ext)s"

        codec = f"{target['format_id']}+{(lambda x :140 if 'avc1' in x else 251)(target['vcodec'])}"

        args = []
        args.append(f"--load-info-json \"{json_path}\"")
        args.append("--embed-subs")
        args.append("--embed-thumbnail")
        args.append("--embed-metadata")
        args.append("--merge-output-format mkv")
        args.append("--remux-video mkv")
        args.append("--no-playlist")
        args.append(f"-f {codec}")
        args.append(f"-o \"{path}\"")

        print(f"cmd: yt-dlp {' '.join(args)}")
        print("-"*72)
        subprocess.run(f"yt-dlp {' '.join(args)}")

    for dirpath, dirnames, filenames in os.walk("./"):
        if 'temp' in dirpath.replace("\\", "/").split("/")[0:2]:
            continue
        if os.path.split(dirpath)[-1] not in json_path.replace("\\", "/").split("/")[0:-1] or os.path.split(dirpath)[-1] == "":
            continue
        for filename in filenames:
            if os.path.splitext(filename)[-1] in ['.webp', '.part', '.jpg', '.vtt']:
                os.remove(os.path.join(dirpath, filename))
                continue
            if os.path.splitext(filename)[0] == os.path.splitext(os.path.split(json_path)[-1])[0].replace(".info", ""):

                os.remove(json_path)
                continue
                

    for dirpath, dirnames, filenames in os.walk("./temp/"):
        if os.listdir(dirpath) == []:
            shutil.rmtree(dirpath)
    if os.path.isdir("./temp/") and os.listdir("./temp/") == []:
        shutil.rmtree("./temp/")

    print("="*72)


def start_dl():
    try:
        for dirname, dirnames, filenames in os.walk("./temp/"):
            for filename in filenames:
                video_dl(os.path.join(dirname, filename))
    except KeyboardInterrupt:
        try:
            print(
                f"\n\n\n{'='*72}\n冷卻中......稍後開始重新下載\n如要結束程式，請再次按Ctrl-c\n{'='*72}\n\n\n")
            for i in range(5):
                print(f"  {5-i}  ", end="\r")
                time.sleep(1)

        except KeyboardInterrupt:
            return
        else:
            return start_dl()


def info_dl(urls):
    if type(urls) == str:
        urls = [urls]

    for url in urls:
        args = []
        args.append("--write-info-json")
        args.append("--skip-download")
        args.append("--no-playlist")
        args.append("--no-write-playlist-metafiles")
        if "playlist?list=" in url:
            args.append("-o \"/temp/%(playlist)s/%(title)s.%(ext)s\"")
        else:
            args.append("-o \"/temp/%(title)s.%(ext)s\"")
        args.append(url)

        subprocess.run(f"yt-dlp {' '.join(args)}")

        print("="*72)


def add_media():
    """
    Auto trigger info download
    """
    url = input("URL:")
    return info_dl(url)


def main():
    explanation = [
        "這是下載YouTube影片或播放清單的程式，請在下方貼上網址或選擇是否繼續下載",
        "播放清單會自動下載到資料夾中",
        "下載過的檔案會自動跳過，不會重新下載",
        "若下載失敗，會自動跳過",
        "過程中如果下載速度降至kb等級，可以按一次Ctrl+C冷卻",
        "但若進度條後方有 (frag xx/xx) 則效果不大",
        "如果要結束下載，請按兩次Ctrl+C",
        "若要繼續下載，請在系統詢問時按'Y'後按'ENTER'即可",
        "若不要繼續下載，請在系統詢問時按'N'後按'ENTER'即可",
    ]
    print("\n".join(f"{explanation.index(e)+1}. {e}" for e in explanation))
    print("=" * 72)

    while True:
        if os.path.isdir("./temp/") and os.listdir("./temp/") != []:
            resp = input("Continue downloading?(Y/N) ").lower()
            if resp == "y":
                pass
            else:
                shutil.rmtree("./temp/")
                continue
        else:
            for dirname, dirnames, filenames in os.walk("./"):
                if dirname == "./temp":
                    continue
                if dirname == "./":
                    continue
                for filename in filenames:
                    if os.path.splitext(filename)[-1] != ".mkv":
                        os.remove(os.path.join(dirname, filename))
            add_media()

        start_dl()


if __name__ == "__main__":
    main()
