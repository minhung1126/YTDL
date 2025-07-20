# YTDL
使用yt-dlp自動下載最好解析度和編碼格式的YouTube影片。

Download youtube videos with the best resolution and vcodec.

## Download
右方點擊`Release`，下載`zip`檔。解壓縮後保留`YTDL.py`和`YTDL_mul.py`即可。

Go to `Release` on thr right of the page.

## Deploy as submodules
1. Add this repo as a submodules.
    ```git
    git submodule add https://github.com/minhung1126/YTDL YTDL
    ```
2. Push to remote
    ```git
    git add .
    git commit -m "Add a submodule"
    git push
    ```
3. After on, once you want to clone or update, use the following command to deal with both the repo and submodules
    ```git
    git clone --recurse-submodules <remote_url>
    git pull --recurse-submodules <branch>
    ```

## Structure

* `metadata.json` based
* Modify `metadata.json`, then download videos by importing `metadata.json`

## Future
```
yt-dlp -S "res,vbr,codec:avc1:vp9:vp09:av01" -f "bv[vcodec^=avc1]+ba[acodec^=mp4a]/bv[vcodec^=vp9]+ba[acodec^=opus]/bv[vcodec^=vp09]+ba[acodec^=opus]/bv[vcodec^=av01]+ba[acodec^=opus]"
```
```
yt-dlp -v -F ^
-S "res,hdr,+codec:avc1:mp4,+codec:vp9.2:opus,+codec:vp9:opus,+codec:vp09:opus,+codec:av01:opus,vbr" ^
-f "bv+ba" ^
https://www.youtube.com/watch?v=3hLESh77fSg
```
