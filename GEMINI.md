# GEMINI.md

## 工具使用

* 你可以隨時使用你手邊的工具，包括但不限於GoogleSearch,MCP Servers。

---

## 開發與發布慣例

這份文件記錄了我們為此專案建立的開發與維護流程。

### 1. 版本管理

- **檔案**: `YTDL.py`
- **變數**: `__version__`

專案的版本號由 `YTDL.py` 檔案中的 `__version__` 變數統一管理。

- **開發環境 (自動檢測)**:
  ```python
  if os.path.exists('.gitignore'):
      __version__ = "dev"
  ```
  程式會自動檢查 `.gitignore` 檔案是否存在。如果存在，版本號會被自動設為 `"dev"`。這會讓程式在啟動時跳過版本更新檢查，避免干擾開發工作。

- **發布版本**:
  當您準備好要發布新版本時，只需修改 `__version__` 的主要版本號字串即可，例如 `"v2025.09.05"`。當程式碼被推送到 `main` 分支後，CI/CD 流程會使用這個版本號進行發布。

### 2. 發布流程 (CI/CD)

- **檔案**: `.github/workflows/auto-release.yml`

本專案使用 GitHub Actions 實現自動化發布。

1.  當您將帶有新版本號的 `YTDL.py` 推送到 `main` 分支後，`auto-release` 工作流程會自動觸發。
2.  它會自動讀取 `YTDL.py` 中的 `__version__` 字串。
3.  使用這個字串作為標籤 (Tag)，在 GitHub 上建立一個對應的 Release。

這個流程確保了版本號的單一事實來源，並實現了全自動發布。

### 3. 使用者更新流程

- **觸發**: 使用者執行的 `YTDL.py` 或 `YTDL_mul.py`。
- **執行**: `self_update.py`

為了提供流暢的使用者體驗，我們設計了無縫的自動更新與重啟機制，此機制同時管理 Python 腳本與核心二進位依賴。

1.  當使用者啟動 `YTDL.py` 或 `YTDL_mul.py` 時，程式會首先檢查 GitHub 上的最新版本。
2.  如果發現新版本，程式會自動下載 `self_update.py` 並執行它，同時主程式退出。
3.  `self_update.py` 會從最新的 Release 中下載並覆蓋 `YTDL.py` 和 `YTDL_mul.py` 等腳本檔案。
4.  接著，`self_update.py` 會讀取**新的 `YTDL.py`** 中定義的 `YT_DLP_VERSION_TAG` 和 `DENO_VERSION`。
5.  它會執行系統指令 (例如 `yt-dlp --update-to`, `deno upgrade`) 來確保 `yt-dlp` 和 `deno` 符合 `YTDL.py` 中指定的版本，如果指令不存在甚至會嘗試自動安裝。
6.  完成所有更新後，`self_update.py` 會**自動重新啟動**使用者當初執行的那個腳本 (`YTDL.py` 或 `YTDL_mul.py`)。

這個設計確保了主程式與其關鍵依賴版本的一致性，並讓使用者幾乎感受不到更新過程。

### 4. 依賴處理

本專案採用混合策略來管理依賴，以最大化使用者便利性。

- **Python 套件 (執行時安裝)**: 
  - **方法**: 在 `import` 套件 (如 `requests`, `pyperclip`) 時使用 `try...except ImportError` 區塊。如果捕捉到錯誤，則使用 `subprocess` 呼叫 `pip` 來安裝該套件。
  - **理由**: 這種「開箱即用」的模式對非開發者使用者最為友好，降低了使用門檻。

- **二進位依賴 (更新時管理)**:
  - **檔案**: `YTDL.py` (定義版本), `self_update.py` (執行更新)
  - **方法**: 核心的二進位依賴 (如 `yt-dlp`, `deno`) 的版本被明確定義在 `YTDL.py` 中。在自動更新流程裡，`self_update.py` 會強制將這些工具更新或降級到指定的版本。
  - **理由**: 這確保了所有使用者的執行環境一致，避免了因 `yt-dlp` 等工具自身更新而導致的非預期行為或錯誤，提高了穩定性。