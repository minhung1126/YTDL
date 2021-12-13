# ver 1.1
import time


try:
    import pyperclip
except:
    import os
    os.system("pip install pyperclip")

import YTDL


def parse():
    pyperclip.copy("")

    print("Copy to start downloading")

    while pyperclip.paste() == "":
        time.sleep(1)

    raw = pyperclip.paste()

    DOMAINS = ['youtube.com/watch?v=',
               'youtu.be/', 'youtube.com/playlist?list=']
    IDLENGTH = {
        'youtube.com/watch?v=': 11, 'youtu.be/': 11, 'youtube.com/playlist?list=': 34,
    }

    urls = []
    for DOMAIN in DOMAINS:
        while DOMAIN in raw:
            url = f"https://{DOMAIN}{raw[raw.find(DOMAIN)+len(DOMAIN): raw.find(DOMAIN)+len(DOMAIN)+IDLENGTH[DOMAIN]]}"
            raw = raw.replace(
                f"{DOMAIN}{raw[raw.find(DOMAIN)+len(DOMAIN): raw.find(DOMAIN)+len(DOMAIN)+IDLENGTH[DOMAIN]]}", "")
            print(f"URL Parsed: {url}")
            if url not in urls:
                urls.append(url)

    return urls


def main():
    explanation = [
        "這個程式可以自動分析文字中的YouTube網址並下載",
        "使用方式為：開啟程式後再複製文字",
        "若分析完畢後關閉程式，請直接開啟YTDL.py並依指示繼續下載",
        "若尚未分析完畢而關閉程式，則要重新分析",
    ]
    print("\n".join(f"{explanation.index(e)+1}. {e}" for e in explanation))
    print("=" * 72)

    while True:
        urls = parse()
        YTDL.info_dl(urls)
        YTDL.start_dl()


if __name__ == "__main__":
    main()
