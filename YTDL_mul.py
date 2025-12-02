import sys
import time
import traceback
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font
import subprocess

import YTDL  # Import the core logic

sys.dont_write_bytecode = True


try:
    import pyperclip
except ImportError:
    # YTDL.report_error("Pyperclip library is not installed. Please run 'pip install pyperclip'.")
    # root = tk.Tk()
    # root.withdraw()
    # messagebox.showerror("依賴錯誤 | Dependency Error", "Pyperclip 函式庫未安裝.\n請在終端機執行 'pip install pyperclip'.")
    # sys.exit(1)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pyperclip"])
    import pyperclip



# --- UI Text Dictionary ---
UI_TEXT = {
    "window_title": "YouTube 網址自動下載器 | YouTube URL Auto-Downloader",
    "instructions": "點擊「開始偵測」後，程式會自動尋找您複製的 YouTube 網址。\n網址會顯示在下方列表中，您可以隨時點擊「全部下載」。",
    "detected_urls": "偵測到的網址 | Detected URLs",
    "start_detecting": "開始偵測 | Start Detecting",
    "stop_detecting": "停止偵測 | Stop Detecting",
    "download_all": "全部下載 | Download All",
    "status_ready": "就緒。請點擊「開始偵測」。 | Ready. Click 'Start Detecting' to begin.",
    "status_stopped": "已停止。點擊「開始偵測」以繼續。 | Stopped. Click 'Start Detecting' to resume.",
    "status_watching": "正在偵測剪貼簿中的網址... | Detecting URLs in clipboard...",
    "status_starting_download": "開始下載流程... | Starting download process...",
    "status_processing_meta": "正在處理 {count} 個網址的元數據... | Processing {count} URLs for metadata...",
    "status_meta_done": "元數據處理完畢，開始下載... | Metadata processed. Starting downloads...",
    "status_downloading": "正在下載 ({i}/{total}): {title}... | Downloading ({i}/{total}): {title}...",
    "status_all_done": "所有下載已完成！可開始新一輪任務。 | All downloads complete! Ready for next session.",
    "status_error": "發生錯誤，請檢查日誌。 | An error occurred. Check logs.",
    "status_clipboard_error": "錯誤：無法存取剪貼簿。 | Error: Could not access clipboard.",
    "msg_download_in_progress_title": "下載進行中 | Download In Progress",
    "msg_download_in_progress_body": "一個下載任務正在執行中。 | A download process is already running.",
    "msg_no_urls_title": "沒有網址 | No URLs",
    "msg_no_urls_body": "尚未偵測到任何網址。 | No URLs have been detected yet.",
    "msg_quit_title": "退出 | Quit",
    "msg_quit_body": "下載正在進行中，您確定要退出嗎？ | A download is in progress. Are you sure you want to quit?",
    "msg_fatal_error_title": "嚴重錯誤 | Fatal Error",
    "msg_fatal_error_body": "啟動時發生嚴重錯誤，請檢查日誌。 | A critical error occurred on startup. Please check the logs.",
    "msg_resume_download_title": "繼續下載 | Resume Download",
    "msg_resume_download_body": "偵測到未完成的下載任務，是否繼續？ | Unfinished downloads detected. Continue?"
}

class ClipboardWatcherApp:
    def __init__(self, master):
        self.master = master
        master.title(UI_TEXT["window_title"])
        master.geometry("750x550")
        master.resizable(False, False)

        self.is_watching = False
        self.detected_urls = set()
        self.clipboard_after_id = None
        self.download_thread = None

        self.setup_widgets()
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Check for incomplete downloads in meta directory
        self.check_and_handle_existing_meta()

    def check_and_handle_existing_meta(self):
        """Check if there are unfinished downloads and ask user if they want to continue."""
        import os
        import shutil
        
        if os.path.isdir(YTDL.META_DIR) and os.listdir(YTDL.META_DIR):
            # Create custom dialog with proper button order (Cancel left, Continue right)
            result = self._show_resume_dialog(
                UI_TEXT["msg_resume_download_title"],
                UI_TEXT["msg_resume_download_body"]
            )
            if not result:
                # User chose not to continue, remove meta directory
                try:
                    shutil.rmtree(YTDL.META_DIR)
                except Exception as e:
                    YTDL.report_error(
                        f"Failed to delete meta directory: {YTDL.META_DIR}",
                        context={"Error": str(e)}
                    )
    
    def _show_resume_dialog(self, title, message):
        """Custom dialog with Continue (default) on left, Cancel on right (Windows convention)."""
        dialog = tk.Toplevel(self.master)
        dialog.title(title)
        dialog.transient(self.master)
        dialog.grab_set()
        
        # Center the dialog
        dialog.geometry("400x150")
        dialog.resizable(False, False)
        
        # Message
        msg_label = ttk.Label(dialog, text=message, wraplength=350, justify=tk.CENTER, padding="20")
        msg_label.pack(expand=True)
        
        # Button frame
        btn_frame = ttk.Frame(dialog, padding="10")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        result = [False]  # Use list to allow modification in nested function
        
        def on_cancel():
            result[0] = False
            dialog.destroy()
        
        def on_continue():
            result[0] = True
            dialog.destroy()
        
        # Continue button on the left (PRIMARY ACTION - Windows convention)
        continue_btn = ttk.Button(btn_frame, text="繼續 | Continue", command=on_continue)
        continue_btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)
        
        # Cancel button on the right
        cancel_btn = ttk.Button(btn_frame, text="取消 | Cancel", command=on_cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=5, expand=True, fill=tk.X)
        
        # Set Continue as default (focused) button
        continue_btn.focus_set()
        
        # Bind Enter key to Continue
        dialog.bind('<Return>', lambda e: on_continue())
        dialog.bind('<Escape>', lambda e: on_cancel())
        
        # Wait for dialog to close
        self.master.wait_window(dialog)
        
        return result[0]
    
    def setup_widgets(self):
        main_frame = ttk.Frame(self.master, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Configure style for the instruction label
        style = ttk.Style(self.master)
        style.configure("Instructions.TLabel", font=("Microsoft JhengHei UI", 10))

        instructions_label = ttk.Label(main_frame, text=UI_TEXT["instructions"], justify=tk.LEFT, relief=tk.RIDGE, padding="5", style="Instructions.TLabel")
        instructions_label.pack(fill=tk.X, pady=(0, 10))

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)

        self.watch_button = ttk.Button(button_frame, text=UI_TEXT["start_detecting"], command=self.toggle_watching)
        self.watch_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        self.download_button = ttk.Button(button_frame, text=UI_TEXT["download_all"], command=self.start_download)
        self.download_button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=5)

        url_frame = ttk.LabelFrame(main_frame, text=UI_TEXT["detected_urls"])
        url_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.url_text = scrolledtext.ScrolledText(url_frame, wrap=tk.WORD, height=15)
        self.url_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.url_text.config(state=tk.DISABLED)

        self.status_var = tk.StringVar()
        self.status_var.set(UI_TEXT["status_ready"])
        status_bar = ttk.Label(self.master, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding="2 5")
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def toggle_watching(self):
        if self.is_watching:
            self.is_watching = False
            if self.clipboard_after_id:
                self.master.after_cancel(self.clipboard_after_id)
            self.watch_button.config(text=UI_TEXT["start_detecting"])
            self.status_var.set(UI_TEXT["status_stopped"])
        else:
            self.is_watching = True
            try:
                pyperclip.copy('')  # 清空剪貼簿
            except Exception as e:
                YTDL.report_error(f"無法清空剪貼簿 (Could not clear clipboard): {e}")
            self.watch_button.config(text=UI_TEXT["stop_detecting"])
            self.status_var.set(UI_TEXT["status_watching"])
            self.poll_clipboard()

    def poll_clipboard(self):
        if not self.is_watching: return
        try:
            current_clipboard = pyperclip.paste()
            if current_clipboard:
                import re
                found_urls = re.findall(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)[/\w\-?=&@%]+', current_clipboard)
                for url in found_urls:
                    if url not in self.detected_urls:
                        self.detected_urls.add(url)
                        self.update_url_display(url)
        except Exception:
            self.toggle_watching()
            YTDL.report_error(f"Failed to access clipboard.\n{traceback.format_exc()}")
            self.status_var.set(UI_TEXT["status_clipboard_error"])
        self.clipboard_after_id = self.master.after(1000, self.poll_clipboard)

    def update_url_display(self, text):
        self.url_text.config(state=tk.NORMAL)
        seq_num = len(self.detected_urls)
        self.url_text.insert(tk.END, f"{seq_num}. {text}\n")
        self.url_text.see(tk.END)
        self.url_text.config(state=tk.DISABLED)

    def start_download(self):
        if self.download_thread and self.download_thread.is_alive():
            messagebox.showwarning(UI_TEXT["msg_download_in_progress_title"], UI_TEXT["msg_download_in_progress_body"])
            return
        if not self.detected_urls:
            messagebox.showinfo(UI_TEXT["msg_no_urls_title"], UI_TEXT["msg_no_urls_body"])
            return

        self.watch_button.config(state=tk.DISABLED)
        self.download_button.config(state=tk.DISABLED)
        self.status_var.set(UI_TEXT["status_starting_download"])

        urls_to_download = list(self.detected_urls)
        self.detected_urls.clear()
        self.url_text.config(state=tk.NORMAL)
        self.url_text.delete(1.0, tk.END)
        self.url_text.config(state=tk.DISABLED)

        self.download_thread = threading.Thread(target=self._download_worker, args=(urls_to_download,), daemon=True)
        self.download_thread.start()
        self._check_download_thread()

    def _download_worker(self, urls):
        try:
            self.master.after(0, lambda: self.status_var.set(UI_TEXT["status_processing_meta"].format(count=len(urls))))
            for url in urls:
                YTDL.dl_meta_from_url(url)

            self.master.after(0, lambda: self.status_var.set(UI_TEXT["status_meta_done"]))
            videos_to_download = YTDL.load_videos_from_meta()
            total_videos = len(videos_to_download)
            for i, video in enumerate(videos_to_download):
                title = video.meta.get('title', 'N/A')[:25]
                self.master.after(0, lambda i=i, t=title: self.status_var.set(UI_TEXT["status_downloading"].format(i=i+1, total=total_videos, title=t)))
                video.download()

            self.master.after(0, lambda: self.status_var.set(UI_TEXT["status_all_done"]))
        except Exception:
            error_message = "A critical error occurred during the download process."
            self.master.after(0, lambda: self.status_var.set(UI_TEXT["status_error"]))
            YTDL.report_error(error_message, context={"Traceback": traceback.format_exc()})

    def _check_download_thread(self):
        if self.download_thread.is_alive():
            self.master.after(100, self._check_download_thread)
        else:
            self.watch_button.config(state=tk.NORMAL)
            self.download_button.config(state=tk.NORMAL)

    def on_closing(self):
        if self.download_thread and self.download_thread.is_alive():
            if messagebox.askokcancel(UI_TEXT["msg_quit_title"], UI_TEXT["msg_quit_body"]):
                self.master.destroy()
        else:
            self.master.destroy()

if __name__ == "__main__":
    try:
        # Clear clipboard at startup to avoid processing old URLs.
        pyperclip.copy('')

        YTDL.initialize_app(sys.argv[0])

        root = tk.Tk()
        app = ClipboardWatcherApp(root)
        root.mainloop()
    except Exception:
        YTDL.report_error("A critical error occurred on startup.", context={"Traceback": traceback.format_exc()})
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(UI_TEXT["msg_fatal_error_title"], UI_TEXT["msg_fatal_error_body"])
        finally:
            sys.exit(1)
