# ver 1.1
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import colorama
    from colorama import Fore, Style
except ImportError:
    import subprocess
    subprocess.run(['pip', 'install', 'colorama'])
finally:
    import colorama
    from colorama import Fore, Style


try:
    import pyperclip
except:
    import os
    os.system("pip install pyperclip")

try:
    # Dont generate __pycache__
    # Use try to force not format the sequence of import
    import sys
    sys.dont_write_bytecode = True
except:
    ...

import YTDL


def parse_and_dl_info(raw_text):
    DOMAINS = [
        'youtube.com/watch?v=',
        'youtu.be/',
        'youtube.com/playlist?list=',
        'youtube.com/shorts/'
    ]
    IDLENGTH = {
        'youtube.com/watch?v=': 11,
        'youtu.be/': 11,
        'youtube.com/playlist?list=': 34,
        'youtube.com/shorts/': 11
    }

    urls = []
    for DOMAIN in DOMAINS:
        while DOMAIN in raw_text:
            url = f"https://{DOMAIN}{raw_text[raw_text.find(DOMAIN)+len(DOMAIN): raw_text.find(DOMAIN)+len(DOMAIN)+IDLENGTH[DOMAIN]]}"
            raw_text = raw_text.replace(
                f"{DOMAIN}{raw_text[raw_text.find(DOMAIN)+len(DOMAIN): raw_text.find(DOMAIN)+len(DOMAIN)+IDLENGTH[DOMAIN]]}", "")
            print(f"URL Parsed: {url}")
            if url not in urls:
                urls.append(url)

    videos = []
    for url in urls:
        videos.append(YTDL.Video(url=url))

    return videos


def watch_clipboard():
    pool = ThreadPoolExecutor()

    try:
        pyperclip.copy("")
    except pyperclip.PyperclipWindowsException:
        print("ERROR. Wait 3 seconds.")
        time.sleep(3)
        print("Restart")

    # print("Copy to start downloading")

    # while pyperclip.paste() == "":
    #     time.sleep(1)

    old_raw = ""
    to_parse = []
    result = []
    try:
        while True:
            raw = pyperclip.paste()
            # print(raw)
            if raw != old_raw:
                print(f"Text detected: {raw[:36]}...")
                # result.append(pool.submit(parse_and_dl_info, raw))
                to_parse.append(raw)
                # parse_and_dl_info(raw)
                old_raw = raw
    except KeyboardInterrupt:
        print('End Watching, start download')

    pool_result = [pool.submit(parse_and_dl_info, p) for p in to_parse]
    pool.shutdown()

    time.sleep(3)
    print(Fore.GREEN + 'All url has been parsed' + Style.RESET_ALL)

    videos = []
    for process in as_completed(pool_result):
        video_list = process.result()

        videos += video_list

    for video in videos:
        video.download()

    print(Fore.GREEN + "All parsed videos are downloaded" + Style.RESET_ALL)

    return


def main():
    explanation = [
        "這個程式可以自動分析文字中的YouTube網址並下載",
        "使用方式為：開啟程式後再複製文字",
        "若要開始下載，點一下本程式視窗後，按下ctrl+C",
        "可以分多次複製",
        "若分析完畢後關閉程式，請直接開啟YTDL.py並依指示繼續下載",
        "若尚未分析完畢而關閉程式，則要重新分析",
    ]
    print("\n".join(f"{explanation.index(e)+1}. {e}" for e in explanation))
    print("=" * 72)

    while True:
        watch_clipboard()
        # YTDL.info_dl(urls)
        # YTDL.start_dl()


if __name__ == "__main__":
    main()
