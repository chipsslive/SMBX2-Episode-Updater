from __future__ import annotations

import threading
import queue
from tkinter import Tk, StringVar, BooleanVar, Toplevel, filedialog, messagebox
from tkinter import font as tkfont
from tkinter import ttk
import os
import smbx2_episode_updater as smbx
from urllib.parse import unquote
from pathlib import Path
from logger import setup_logging, get_logger, log_tkinter_exception


APP_NAME = "SMBX2 Episode Updater"


def center_window(win):
    """Center a Tk/Toplevel window on the current screen."""
    try:
        win.update_idletasks()
        w = win.winfo_width() or win.winfo_reqwidth()
        h = win.winfo_height() or win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw // 2) - (w // 2))
        y = max(0, (sh // 2) - (h // 2))
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pass


# Format a size in bytes to a human-readable string
def _fmt_size(n: int) -> str:
    try:
        units = ["B", "KB", "MB", "GB"]
        s = float(n)
        i = 0
        while s >= 1024 and i < len(units) - 1:
            s /= 1024.0
            i += 1
        return f"{s:.1f} {units[i]}"
    except Exception:
        return str(n)


def setup_styles(root: Tk):
    style = ttk.Style()
    # Fonts
    base = tkfont.nametofont("TkDefaultFont")
    title_font = base.copy(); title_font.configure(size=14, weight="bold")
    section_font = base.copy(); section_font.configure(size=11, weight="bold")
    status_font = base.copy(); status_font.configure(size=9)

    # Register named fonts so ttk can reference them
    root.tk.call("font", "create", "AppTitleFont", "-family", title_font.cget("family"), "-size", title_font.cget("size"), "-weight", title_font.cget("weight"))
    root.tk.call("font", "create", "AppSectionFont", "-family", section_font.cget("family"), "-size", section_font.cget("size"), "-weight", section_font.cget("weight"))
    root.tk.call("font", "create", "AppStatusFont", "-family", status_font.cget("family"), "-size", status_font.cget("size"))

    # Labels
    style.configure("Title.TLabel", font="AppTitleFont")
    style.configure("Section.TLabel", font="AppSectionFont")
    style.configure("Status.TLabel", font="AppStatusFont")

    # Buttons spacing
    style.configure("TButton", padding=(10, 6))

    # Progressbar color (may vary by theme support)
    style.configure("Phase.Horizontal.TProgressbar", thickness=14)


class UpdaterGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.minsize(520, 300)

        self.cfg = None
        self.state = None

        self.status_text = StringVar(value="Ready.")
        self.remote_name = StringVar(value="Unknown")
        self.last_updated = StringVar(value="Never")
        self.url_ok = BooleanVar(value=False)

        setup_styles(self.root)
        self._build()
        self.refresh()
        center_window(self.root)

    # UI setup
    def _build(self):
        self.container = ttk.Frame(self.root, padding=12)
        self.container.pack(fill="both", expand=True)

        # Setup frame (shown when config incomplete)
        self.setup_frame = ttk.Frame(self.container)
        self.ep_dir_var = StringVar()
        self.url_var = StringVar()
        
        ttk.Label(self.setup_frame, text="Initial Setup", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,6))

        ttk.Separator(self.setup_frame).grid(row=1, column=0, columnspan=3, sticky="we", pady=(0,6))

        ttk.Label(self.setup_frame, text="SMBX2 Episodes Directory:", style="Section.TLabel").grid(row=2, column=0, sticky="w", padx=(0,6), pady=6)
        ttk.Entry(self.setup_frame, textvariable=self.ep_dir_var, width=50).grid(row=2, column=1, sticky="we", pady=6)
        ttk.Button(self.setup_frame, text="Browse", command=self._browse_ep_dir).grid(row=2, column=2, padx=(6,0))

        ttk.Label(self.setup_frame, text="Episode ZIP URL:", style="Section.TLabel").grid(row=3, column=0, sticky="w", padx=(0,6), pady=6)
        ttk.Entry(self.setup_frame, textvariable=self.url_var, width=50).grid(row=3, column=1, sticky="we", pady=6)

        ttk.Button(self.setup_frame, text="Save", command=self._save_setup).grid(row=4, column=1, sticky="e", pady=12)
        self.setup_frame.columnconfigure(1, weight=1)

        # Main frame (shown when config present)
        self.main_frame = ttk.Frame(self.container)

        row = 0
        ttk.Label(self.main_frame, text="SMBX2 Episode Updater", style="Title.TLabel").grid(row=row, column=0, columnspan=2, sticky="w"); row+=1
        ttk.Separator(self.main_frame).grid(row=row, column=0, columnspan=2, sticky="we", pady=(0,6)); row+=1

        ttk.Label(self.main_frame, text="Details", style="Section.TLabel").grid(row=row, column=0, sticky="w"); row+=1

        ttk.Label(self.main_frame, text="Remote file name:").grid(row=row, column=0, sticky="w")
        ttk.Label(self.main_frame, textvariable=self.remote_name).grid(row=row, column=1, sticky="w", padx=(16,0)); row+=1

        ttk.Label(self.main_frame, text="Last update:").grid(row=row, column=0, sticky="w")
        ttk.Label(self.main_frame, textvariable=self.last_updated).grid(row=row, column=1, sticky="w", padx=(16,0)); row+=1

        ttk.Label(self.main_frame, text="URL status:").grid(row=row, column=0, sticky="w")
        self.url_status_label = ttk.Label(self.main_frame, text="Checking...", style="Status.TLabel")

        self.url_status_label.grid(row=row, column=1, sticky="w", padx=(16,0)); row+=1

        btns = ttk.Frame(self.main_frame)
        ttk.Button(btns, text="Update", command=self._on_update).pack(side="left", padx=(0,8))
        ttk.Button(btns, text="Settings", command=self._open_settings).pack(side="left")
        btns.grid(row=row, column=0, columnspan=2, pady=12)

        self.progress = ttk.Progressbar(self.main_frame, mode="determinate", style="Phase.Horizontal.TProgressbar")
        self.progress.grid(row=row+1, column=0, columnspan=2, sticky="we")
        self.progress_label = ttk.Label(self.main_frame, textvariable=self.status_text, style="Status.TLabel")
        self.progress_label.grid(row=row+2, column=0, columnspan=2, sticky="w", pady=(6,0))

        self.main_frame.columnconfigure(1, weight=1)

    # Refreshes UI state (update time, URL status, etc.)
    def refresh(self):
        smbx.ensure_dirs()
        self.cfg = smbx.read_config()
        self.state = smbx.read_state()

        missing = not self.cfg.get("episodes_dir") or not self.cfg.get("episode_url")
        self.setup_frame.pack_forget(); self.main_frame.pack_forget()
        if missing:
            self.ep_dir_var.set(self.cfg.get("episodes_dir", ""))
            self.url_var.set(self.cfg.get("episode_url", ""))
            self.setup_frame.pack(fill="both", expand=True)
            return

        # Populate main screen
        self.last_updated.set(self.state.get("installed_at") or "-")
        self.status_text.set("Checking URL...")
        self.url_status_label.configure(text="Checking...")
        self.main_frame.pack(fill="both", expand=True)
        self.root.after(50, self._async_probe)

    # Setup helpers
    def _browse_ep_dir(self):
        d = filedialog.askdirectory(mustexist=True)
        if d:
            self.ep_dir_var.set(d)

    def _save_setup(self):
        episodes_dir = self.ep_dir_var.get().strip()
        url = self.url_var.get().strip()
        if not episodes_dir or not os.path.isdir(episodes_dir):
            messagebox.showerror(APP_NAME, "Please select a valid Episodes directory.")
            return
        if not url:
            messagebox.showerror(APP_NAME, "Please enter the Episode ZIP URL.")
            return
        cfg = smbx.read_config()
        cfg["episodes_dir"] = episodes_dir
        cfg["episode_url"] = url
        if not cfg.get("preserve_globs"):
            cfg["preserve_globs"] = smbx.DEFAULT_PRESERVE
        smbx.save_json(smbx.CONFIG_PATH, cfg)
        self.refresh()

    # Probe URL in background
    def _async_probe(self):
        def work():
            try:
                name, size = smbx.probe_remote_metadata(self.cfg["episode_url"])
                # Make filename readable: decode %xx sequences
                clean = os.path.basename(unquote(name))
                self.remote_name.set(clean)
                self.url_ok.set(True)
                self._set_url_status(True, size)
            except Exception as e:
                self.remote_name.set("-")
                self.url_ok.set(False)
                self._set_url_status(False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _set_url_status(self, ok: bool, extra: str):
        def ui():
            if ok:
                # Format Content-Length prettily when numeric
                size_txt = extra
                try:
                    if isinstance(extra, str) and extra.isdigit():
                        size_txt = _fmt_size(int(extra))
                except Exception:
                    size_txt = extra
                self.url_status_label.configure(text=f"File exists and is valid (Size: {size_txt})")
                self.status_text.set("Ready to update.")
            else:
                self.url_status_label.configure(text=f"File was not found or is invalid")
                self.status_text.set("URL check failed. Ensure that it leads directly to a ZIP file.")
        self.root.after(0, ui)

    # Update flow
    def _on_update(self):
        if not self.url_ok.get():
            messagebox.showerror(APP_NAME, "The URL is not valid. Fix it in Settings.")
            return
        episodes_dir_str = self.cfg["episodes_dir"]
        if not os.path.isdir(episodes_dir_str):
            messagebox.showerror(APP_NAME, "Episodes directory is invalid. Fix it in Settings.")
            return

        episodes_dir = Path(episodes_dir_str)

        # Run in background thread
        self.progress.configure(mode="indeterminate")
        self.progress.start(8)
        self.status_text.set("Downloading episode...")

        # Queue and event to communicate with UI for prompts
        prompt_q: queue.Queue = queue.Queue()
        prompt_event = threading.Event()
        prompt_result = {"ok": True}

        def ask_yes_no(msg: str) -> bool:
            def ui():
                res = messagebox.askyesno(APP_NAME, msg, icon="question")
                prompt_result["ok"] = res
                prompt_event.set()
            self.root.after(0, ui)
            prompt_event.wait()
            prompt_event.clear()
            return prompt_result["ok"]

        def worker():
            try:
                # Download with byte-wise progress
                first_seen = {"set": False}
                def on_dl(downloaded: int, total: int):
                    def ui():
                        if total > 0:
                            if not first_seen["set"]:
                                # switch to determinate when we know total
                                self.progress.stop()
                                self.progress.configure(mode="determinate", maximum=total)
                                first_seen["set"] = True
                            self.progress.configure(value=downloaded)
                            self.status_text.set(f"Downloading... {_fmt_size(downloaded)} / {_fmt_size(total)}")
                        else:
                            # unknown size: keep indeterminate but update text
                            self.status_text.set(f"Downloading... {_fmt_size(downloaded)}")
                    self.root.after(0, ui)

                zip_path, server_name, sha = smbx.download_zip(self.cfg["episode_url"], on_progress=on_dl)  # type: ignore[attr-defined]
                def ui_extract():
                    # switch to extracting spinner
                    try:
                        self.progress.stop()
                    except Exception:
                        pass
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(8)
                    self.status_text.set("Extracting ZIP file...")
                self.root.after(0, ui_extract)

                # Unzip and pick episode root
                stage, _ = smbx.unzip_to_stage(zip_path)
                episode_root = smbx.find_episode_root(stage)

                # Decide install dir: ALWAYS use directory containing .wld
                target_name = episode_root.name
                install_dir = episodes_dir / target_name

                # Prompt if fresh install
                if not install_dir.exists():
                    if not ask_yes_no(f"Fresh install will be created at:\n{install_dir}\n\nProceed?"):
                        return

                # Indicate merging phase before per-file callbacks arrive
                def ui_premerge():
                    try:
                        self.progress.stop()
                    except Exception:
                        pass
                    self.progress.configure(mode="indeterminate")
                    self.progress.start(8)
                    self.status_text.set("Checking for new files to install...")
                self.root.after(0, ui_premerge)

                # Merge with accurate progress via backend callback
                def on_progress(phase, rel, idx, total):
                    def ui():
                        # initialize determinate bar when first progress arrives
                        try:
                            self.progress.stop()
                        except Exception:
                            pass
                        self.progress.configure(mode="determinate", maximum=total)
                        self.progress.configure(value=idx)
                        self.status_text.set(f"{('Writing' if phase=='write' else 'Deleting')} {idx}/{total}: {rel}")
                    self.root.after(0, ui)

                changed = smbx.merge_stage_into_install(
                    episode_root,
                    install_dir,
                    self.cfg.get("preserve_globs") or [],
                    on_progress=on_progress,
                )

                # Ensure bar shows complete
                self.root.after(0, lambda: self.progress.configure(value=self.progress["maximum"]))

                # Save state
                st = smbx.read_state()
                st["last_zip_name"] = server_name
                st["last_zip_sha256"] = sha
                st["install_dir_name"] = target_name
                st["installed_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
                smbx.save_json(smbx.STATE_PATH, st)

                num_changes = len(changed)
                msg = f"Update complete. {num_changes} files changed."
                if num_changes == 0:
                    msg = "Your current install is already up to date."
                self.root.after(0, lambda: self.status_text.set(msg))
                # Refresh labels (e.g., Last update) after saving state
                self.root.after(0, self.refresh)
                self.root.after(0, lambda: messagebox.showinfo(APP_NAME, msg))
            except Exception as e:
                logger = get_logger(__name__)
                logger.error(f"Update failed: {e}", exc_info=True)
                msg = f"Update failed: {e}"
                self.root.after(0, lambda m=msg: messagebox.showerror(APP_NAME, m))
            finally:
                self.root.after(0, self.progress.stop)

        threading.Thread(target=worker, daemon=True).start()

    def _open_settings(self):
        win = Toplevel(self.root)
        win.title("Settings")
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ep_var = StringVar(value=self.cfg.get("episodes_dir", ""))
        url_var = StringVar(value=self.cfg.get("episode_url", ""))

        ttk.Label(frm, text="Settings", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Separator(frm).grid(row=1, column=0, columnspan=3, sticky="we", pady=(0,6))
        ttk.Label(frm, text="SMBX2 Episodes Directory:", style="Section.TLabel").grid(row=2, column=0, sticky="w", padx=(0,6), pady=6)
        ttk.Entry(frm, textvariable=ep_var, width=50).grid(row=2, column=1, sticky="we", pady=6)
        def browse():
            d = filedialog.askdirectory(mustexist=True)
            if d:
                ep_var.set(d)
        ttk.Button(frm, text="Browse", command=browse).grid(row=2, column=2, padx=(6,0))

        ttk.Label(frm, text="Episode ZIP URL:", style="Section.TLabel").grid(row=3, column=0, sticky="w", padx=(0,6), pady=6)
        ttk.Entry(frm, textvariable=url_var, width=50).grid(row=3, column=1, sticky="we", pady=6)

        def save():
            cfg = smbx.read_config()
            cfg["episodes_dir"] = ep_var.get().strip()
            cfg["episode_url"] = url_var.get().strip()
            if not cfg.get("preserve_globs"):
                cfg["preserve_globs"] = smbx.DEFAULT_PRESERVE
            smbx.save_json(smbx.CONFIG_PATH, cfg)
            self.cfg = cfg
            self.refresh()
            win.destroy()
        ttk.Button(frm, text="Save", command=save).grid(row=4, column=1, sticky="e", pady=12)
        frm.columnconfigure(1, weight=1)
        center_window(win)


def main():
    # Initialize logging for GUI
    setup_logging()
    logger = get_logger(__name__)
    logger.info("Starting SMBX2 Episode Updater GUI")
    
    root = Tk()
    
    # Set up Tkinter exception handling
    root.report_callback_exception = log_tkinter_exception

    # Use themed widgets
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    UpdaterGUI(root)
    center_window(root)
    root.mainloop()


if __name__ == "__main__":
    main()