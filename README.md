# YTDL
Download youtube videos with the best resolution and vcodec.

## Download
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