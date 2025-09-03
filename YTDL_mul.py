# ver 1.1
import time
import os
from concurrent.futures import ThreadPoolExecutor
import sys
import traceback

# Make sure YTDL is imported to access its functions
import YTDL

try:
    import pyperclip
except ImportError:
    YTDL.report_error("Pyperclip library is not installed. Please run 'pip install pyperclip'.")
    input("Press ENTER to exit.")
    sys.exit(1)

try:
    sys.dont_write_bytecode = True
except (ImportError, AttributeError):
    pass

def parse_and_dl_info(raw_text):
    context = {"Input Text": raw_text[:1000]} # Provide the text being parsed as context
    try:
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

        for url in urls:
            YTDL.dl_meta_from_url(url)
    except Exception:
        YTDL.report_error("Failed during URL parsing and metadata download.", context={"Traceback": traceback.format_exc(), **context})


def watch_clipboard():
    try:
        pyperclip.copy("")
    except pyperclip.PyperclipWindowsException:
        YTDL.report_error(f"Could not access the clipboard.\n{traceback.format_exc()}")
        print("Restarting clipboard watch in 5 seconds...")
        time.sleep(5)
        return

    old_raw = ""
    to_parse = []
    print("Watching clipboard for YouTube URLs. Press Ctrl+C to stop watching and start downloading.")
    try:
        while True:
            raw = pyperclip.paste()
            if raw and raw != old_raw:
                print(f"Text detected: {raw[:70]}...")
                to_parse.append(raw)
                old_raw = raw
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nStopped watching clipboard. Starting download process...')

    if not to_parse:
        print("No new URLs were detected.")
        return

    with ThreadPoolExecutor() as pool:
        list(pool.map(parse_and_dl_info, to_parse))

    print('All URLs have been processed.')

    videos_to_download = YTDL.load_videos_from_meta()
    if not videos_to_download:
        print("No videos found to download.")
        return

    for video in videos_to_download:
        video.download()

    print("All parsed videos are downloaded.")
    YTDL.cleanup()


def main():
    try:
        YTDL.check_for_updates(sys.argv[0])
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
            print("\nReturning to clipboard watch mode. Press Ctrl+C again to exit, or copy new links.")
    except SystemExit:
        pass
    except Exception:
        YTDL.report_error(f"A critical error occurred in YTDL_mul.", context={"Traceback": traceback.format_exc()})
        input("Press ENTER to exit.")

if __name__ == "__main__":
    main()
