import os
import io
import subprocess

from zipfile import ZipFile
import requests

try:
    # Dont generate __pycache__
    # Use try to force not format the sequence of import
    import sys
    sys.dont_write_bytecode = True
except:
    ...


def program_files_update():
    cwd = os.getcwd()
    api_url = "https://api.github.com/repos/minhung1126/YTDL"

    resp = requests.get(f"{api_url}/releases/latest")
    if not resp.ok:
        #! Fail
        print("Fail to download release_data")
        return
    else:
        print("Download the info successfully")

    release_data = resp.json()
    zipfile_url = release_data['zipball_url']
    print(f'Release zip url: {zipfile_url}')

    zipfile_content_resp = requests.get(zipfile_url)
    if not zipfile_content_resp.ok:
        #! Fail
        print("Fail to download zipfile of the latest release code")
        return
    else:
        print("Download the zipfile successfully")

    zipfile_content = io.BytesIO(zipfile_content_resp.content)

    must_extract_filenames = [
        'ytdlp_version_info.py'
    ]
    # Replace only if originally exists
    to_extract_filenames = [
        "YTDL.py", "YTDL_mul.py",
    ]
    for filename in to_extract_filenames:
        if filename not in os.listdir(cwd):
            to_extract_filenames.remove(filename)

    to_extract_filenames += must_extract_filenames

    with ZipFile(zipfile_content, 'r') as zipfile:
        for filepath in zipfile.namelist():
            print(filepath, end='')
            filename = os.path.split(filepath)[-1]
            if filename in to_extract_filenames:
                file_content = zipfile.read(filepath)
                with open(os.path.join(cwd, filename), 'wb') as f:
                    f.write(file_content)
                print(" ...Extracted")
            else:
                print(" ...Skipped")

    # Update yt-dlp.exe
    from ytdlp_version_info import (
        YT_DLP_VERSION_CHANNEL,
        YT_DLP_VERSION_TAG
    )
    print(
        f"yt-dlp.exe: Channel:{YT_DLP_VERSION_CHANNEL}; Tag: {YT_DLP_VERSION_TAG}")
    subprocess.run([
        'yt-dlp', '--update-to', f'{YT_DLP_VERSION_CHANNEL}@{YT_DLP_VERSION_TAG}',
    ])

    os.remove('ytdlp_version_info.py')

    # Get update_yt_dlp.cmd
    # resp = requests.get(f"{api_url}/contents/update_yt_dlp.cmd")
    # if not resp.ok:
    #     print("Fail to download 'update_yt_dlp.cmd' info")
    #     return

    # data = resp.json()
    # download_url = data['download_url']

    # cmd_resp = requests.get(download_url)
    # if not cmd_resp.ok:
    #     print("Fail to download 'update_yt_dlp.cmd'")
    #     return

    # with open('update_yt_dlp.cmd', 'wb') as f:
    #     f.write(cmd_resp.content)

    # subprocess.run(['update_yt_dlp.cmd'], cwd=os.getcwd())

    # os.remove(os.path.join(cwd, 'update_yt_dlp.cmd'))

    print("==================================================")
    print("如果發生任何錯誤，請截圖此CMD視窗並連絡開發者。\n"
          "If any error occured, please screenshot this cmd and contact the developer.")
    print("==================================================")
    return


def main():
    program_files_update()


if __name__ == "__main__":
    main()
