import queue
import threading
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import tkinter.ttk as ttk
import webbrowser
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .mal import scrape_mal_title_and_themes, tvdb_search_url
from .media import ID3Tags, download_url_to_mp3, yt_search_first
from .settings import AppSettings, ensure_dir, load_settings, save_settings


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, settings: AppSettings):
        super().__init__(master)
        self.title("Settings")
        self.resizable(False, False)
        self.settings = settings
        self.result: Optional[AppSettings] = None

        self.var_download = tk.StringVar(value=settings.download_dir)
        self.var_mp3 = tk.StringVar(value=settings.mp3_dir)
        self.var_bitrate = tk.IntVar(value=settings.mp3_bitrate_kbps)
        self.var_album_artist = tk.StringVar(value=settings.default_album_artist)
        self.var_genre = tk.StringVar(value=settings.default_genre)
        self.var_debug = tk.BooleanVar(value=bool(settings.debug))

        frm = ttk.Frame(self, padding=10)
        frm.grid(row=0, column=0, sticky="nsew")

        def browse_dir(var: tk.StringVar):
            d = fd.askdirectory(parent=self)
            if d:
                var.set(d)

        r = 0
        ttk.Label(frm, text="Download folder").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_download, width=55).grid(row=r, column=1, sticky="we")
        ttk.Button(frm, text="Browse", command=lambda: browse_dir(self.var_download)).grid(row=r, column=2)
        r += 1

        ttk.Label(frm, text="MP3 output folder").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_mp3, width=55).grid(row=r, column=1, sticky="we")
        ttk.Button(frm, text="Browse", command=lambda: browse_dir(self.var_mp3)).grid(row=r, column=2)
        r += 1

        ttk.Label(frm, text="MP3 bitrate (kbps)").grid(row=r, column=0, sticky="w")
        ttk.Spinbox(frm, from_=64, to=320, increment=16, textvariable=self.var_bitrate, width=10).grid(row=r, column=1, sticky="w")
        r += 1

        ttk.Label(frm, text="Default Album Artist").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_album_artist, width=55).grid(row=r, column=1, sticky="we")
        r += 1

        ttk.Label(frm, text="Default Genre").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_genre, width=55).grid(row=r, column=1, sticky="we")
        r += 1

        ttk.Checkbutton(frm, text="Debug mode (more logging)", variable=self.var_debug).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self._cancel).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(btns, text="Save", command=self._save).grid(row=0, column=1)

        self.bind("<Escape>", lambda e: self._cancel())
        self.grab_set()
        self.wait_visibility()
        self.transient(master)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _save(self) -> None:
        s = AppSettings(
            download_dir=self.var_download.get().strip(),
            mp3_dir=self.var_mp3.get().strip(),
            mp3_bitrate_kbps=int(self.var_bitrate.get()),
            default_album_artist=self.var_album_artist.get().strip() or "Openings and Endings",
            default_genre=self.var_genre.get().strip() or "Anime",
            debug=bool(self.var_debug.get()),
        )
        self.result = s
        self.destroy()


@dataclass
class QueueItem:
    kind: str
    query: str


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("oped-dl")
        self.geometry("950x700")

        self.settings = load_settings()

        self.worker_to_ui: queue.Queue = queue.Queue()
        self.ui_to_worker: queue.Queue = queue.Queue()

        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        self.waiting_for_confirm = threading.Event()

        self.mal_url_var = tk.StringVar()
        self.tvdb_url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.current_song_var = tk.StringVar(value="")
        self.song_url_var = tk.StringVar()

        self.progress_var = tk.DoubleVar(value=0.0)

        self.tag_song = tk.StringVar(value="")
        self.tag_artist = tk.StringVar(value="")
        self.tag_album = tk.StringVar(value="")
        self.tag_album_artist = tk.StringVar(value=self.settings.default_album_artist or "Openings and Endings")
        self.tag_genre = tk.StringVar(value=self.settings.default_genre or "Anime")
        self.tag_year = tk.StringVar(value="")
        self.tag_track = tk.StringVar(value="")
        self.tag_disk = tk.StringVar(value="")

        self._queue_metadata: dict[int, ID3Tags] = {}
        self._current_queue_index: Optional[int] = None

        self._build_ui()
        self.after(100, self._poll_worker_queue)

    def _build_ui(self) -> None:
        menubar = tk.Menu(self)
        m_app = tk.Menu(menubar, tearoff=0)
        m_app.add_command(label="Settings", command=self._open_settings)
        m_app.add_separator()
        m_app.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="App", menu=m_app)
        self.config(menu=menubar)

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        frm_in = ttk.LabelFrame(root, text="MyAnimeList")
        frm_in.pack(fill="x")

        ttk.Label(frm_in, text="Anime URL").grid(row=0, column=0, sticky="w", padx=(8, 6), pady=8)
        ttk.Entry(frm_in, textvariable=self.mal_url_var).grid(row=0, column=1, sticky="we", pady=8)
        ttk.Button(frm_in, text="Fetch OP/ED", command=self._fetch_themes).grid(row=0, column=2, padx=8, pady=8)

        ttk.Label(frm_in, text="TVDB").grid(row=1, column=0, sticky="w", padx=(8, 6), pady=(0, 8))
        ent_tvdb = ttk.Entry(frm_in, textvariable=self.tvdb_url_var)
        ent_tvdb.grid(row=1, column=1, sticky="we", pady=(0, 8))
        ttk.Button(frm_in, text="Open", command=self._open_tvdb).grid(row=1, column=2, padx=8, pady=(0, 8))
        ent_tvdb.configure(state="readonly")

        frm_in.columnconfigure(1, weight=1)

        mid = ttk.PanedWindow(root, orient="horizontal")
        mid.pack(fill="both", expand=True, pady=(10, 0))

        left = ttk.Frame(mid)
        right = ttk.Frame(mid)
        mid.add(left, weight=2)
        mid.add(right, weight=3)

        frm_queue = ttk.LabelFrame(left, text="OP/ED")
        frm_queue.pack(fill="both", expand=True)

        self.queue_list = tk.Listbox(frm_queue, height=20)
        self.queue_list.pack(fill="both", expand=True, padx=8, pady=8)
        self.queue_list.bind('<<ListboxSelect>>', self._on_queue_select)

        q_btns = ttk.Frame(frm_queue)
        q_btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(q_btns, text="Search YouTube", command=self._search_current_item).pack(side="left")
        ttk.Button(q_btns, text="Download", command=self._download_current_item).pack(side="left", padx=(8, 0))
        ttk.Button(q_btns, text="Clear", command=self._clear_queue).pack(side="left", padx=(8, 0))

        frm_song = ttk.LabelFrame(right, text="Current / Direct Download")
        frm_song.pack(fill="x")

        ttk.Label(frm_song, textvariable=self.current_song_var, wraplength=560).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0)
        )

        ttk.Label(frm_song, text="YouTube URL").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(frm_song, textvariable=self.song_url_var).grid(row=1, column=1, sticky="we", pady=8)
        ttk.Button(frm_song, text="Open", command=self._open_song_url).grid(row=1, column=2, padx=8, pady=8)
        frm_song.columnconfigure(1, weight=1)

        song_btns = ttk.Frame(frm_song)
        song_btns.grid(row=2, column=0, columnspan=3, sticky="e", padx=8, pady=(0, 8))
        ttk.Button(song_btns, text="Use URL + Download", command=self._use_url_download).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(song_btns, text="Skip", command=self._skip_current_song).grid(row=0, column=1)

        frm_prog = ttk.Frame(right)
        frm_prog.pack(fill="x", pady=(6, 0))
        self.progress = ttk.Progressbar(frm_prog, maximum=100.0, variable=self.progress_var)
        self.progress.pack(fill="x", padx=2)

        frm_tags = ttk.LabelFrame(right, text="ID3 tags (applied to each downloaded MP3)")
        frm_tags.pack(fill="x", pady=(10, 0))
        self._tag_entries(frm_tags)

        frm_log = ttk.LabelFrame(right, text="Log")
        frm_log.pack(fill="both", expand=True, pady=(10, 0))

        self.log = tk.Text(frm_log, height=12, state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        status = ttk.Label(root, textvariable=self.status_var)
        status.pack(fill="x", pady=(10, 0))

    def _tag_entries(self, parent: ttk.LabelFrame) -> None:
        def add_row(row: int, label: str, var: tk.StringVar):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            ent = ttk.Entry(parent, width=45)
            ent.grid(row=row, column=1, sticky="we", padx=8, pady=4)
            ent.configure(textvariable=var)
            ent.bind("<FocusIn>", self._on_tag_field_focus)
            return ent

        parent.columnconfigure(1, weight=1)

        add_row(0, "Song", self.tag_song)
        add_row(1, "Artist", self.tag_artist)
        add_row(2, "Album", self.tag_album)
        add_row(3, "Album Artist", self.tag_album_artist)
        add_row(4, "Genre", self.tag_genre)
        add_row(5, "Year", self.tag_year)
        add_row(6, "Track", self.tag_track)
        add_row(7, "Disk", self.tag_disk)

    def _on_tag_field_focus(self, event=None) -> None:
        if self._current_queue_index is not None and self.queue_list.size() > 0:
            if not self.queue_list.curselection():
                self.queue_list.selection_set(self._current_queue_index)
                self.queue_list.see(self._current_queue_index)
        if self._current_queue_index is not None:
            self._queue_metadata[self._current_queue_index] = self._snapshot_tags()

    def _load_metadata_for_index(self, idx: int) -> None:
        tags = self._queue_metadata.get(idx)
        if tags:
            self.tag_song.set(tags.song)
            self.tag_artist.set(tags.artist)
            self.tag_album.set(tags.album)
            self.tag_album_artist.set(tags.album_artist or self.settings.default_album_artist or "Openings and Endings")
            self.tag_genre.set(tags.genre or self.settings.default_genre or "Anime")
            self.tag_year.set(tags.year)
            self.tag_track.set(tags.track)
            self.tag_disk.set(tags.disk)
        else:
            self._reset_tags_for_new_track()
            song_text = self.queue_list.get(idx)
            song_name = song_text.split(":", 1)[-1].strip() if ":" in song_text else song_text.strip()
            self.tag_song.set(song_name)

    def _on_queue_select(self, event=None) -> None:
        selection = self.queue_list.curselection()
        if not selection:
            return
        new_idx = selection[0]
        if new_idx == self._current_queue_index:
            return
        self._save_current_metadata()
        self._current_queue_index = new_idx
        self._load_metadata_for_index(new_idx)
        song_text = self.queue_list.get(new_idx)
        self.current_song_var.set(song_text)
        self._set_status(f"Selected: {song_text} - Edit metadata and click Search YouTube or Download")

    def _search_current_item(self) -> None:
        selection = self.queue_list.curselection()
        if not selection:
            if self.queue_list.size() > 0:
                self.queue_list.selection_set(0)
                self.queue_list.see(0)
                self._on_queue_select()
            else:
                mb.showinfo("No Items", "No OP/ED items in the list")
                return
        idx = selection[0]
        song_text = self.queue_list.get(idx)
        song = song_text.split(":", 1)[-1].strip() if ":" in song_text else song_text.strip()
        tags = self._queue_metadata.get(idx)
        anime_title = tags.album if tags else ""
        self._set_status(f"Searching YouTube: {song}")
        self._log(f"Searching: {song}")

        def run():
            try:
                url = yt_search_first(song, anime_title=anime_title)
                self.worker_to_ui.put(("search_result", (idx, song, url)))
            except Exception as e:
                self.worker_to_ui.put(("error", f"Search failed: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _download_current_item(self) -> None:
        selection = self.queue_list.curselection()
        if not selection:
            if self.queue_list.size() > 0:
                self.queue_list.selection_set(0)
                self.queue_list.see(0)
                self._on_queue_select()
            else:
                mb.showinfo("No Items", "No OP/ED items in the list")
                return
        idx = selection[0]
        url = self.song_url_var.get().strip()
        if not url:
            mb.showerror("Missing URL", "Enter a YouTube URL first or click Search YouTube")
            return
        tags = self._snapshot_tags()

        def run():
            try:
                song_text = self.queue_list.get(idx)
                song = song_text.split(":", 1)[-1].strip() if ":" in song_text else song_text.strip()

                def log_cb(m: str) -> None:
                    self.worker_to_ui.put(("log", m))

                def stage_cb(stage: str) -> None:
                    self.worker_to_ui.put(("status", stage))

                def progress_cb(frac: float, label: str) -> None:
                    self.worker_to_ui.put(("progress", (frac, label)))

                download_url_to_mp3(
                    url,
                    display_name=song,
                    settings=self.settings,
                    tags=tags,
                    log_cb=log_cb,
                    stage_cb=stage_cb,
                    progress_cb=progress_cb,
                )
                self.worker_to_ui.put(("status", f"Downloaded: {tags.song or song}"))
            except Exception as e:
                self.worker_to_ui.put(("error", str(e)))

        threading.Thread(target=run, daemon=True).start()
        self._reset_tags_for_new_track()

    def _snapshot_tags(self) -> ID3Tags:
        return ID3Tags(
            song=self.tag_song.get().strip(),
            artist=self.tag_artist.get().strip(),
            album=self.tag_album.get().strip(),
            album_artist=self.tag_album_artist.get().strip(),
            genre=self.tag_genre.get().strip(),
            year=self.tag_year.get().strip(),
            track=self.tag_track.get().strip(),
            disk=self.tag_disk.get().strip(),
        )

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _set_progress(self, pct: float) -> None:
        self.progress_var.set(max(0.0, min(100.0, pct)))

    def _progress_start_indeterminate(self) -> None:
        try:
            self.progress.configure(mode="indeterminate")
            self.progress.start(10)
        except Exception:
            pass

    def _progress_stop_indeterminate(self) -> None:
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate")
        except Exception:
            pass

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self.settings = dlg.result
        save_settings(self.settings)
        self.tag_album_artist.set(self.settings.default_album_artist or "Openings and Endings")
        self.tag_genre.set(self.settings.default_genre or "Anime")
        self._set_status("Settings saved")

    def _open_tvdb(self) -> None:
        url = self.tvdb_url_var.get().strip()
        if not url:
            return
        webbrowser.open(url)

    def _fetch_themes(self) -> None:
        url = self.mal_url_var.get().strip()
        if not url.startswith("https://myanimelist.net/"):
            mb.showerror("Invalid URL", "Please enter a https://myanimelist.net/ anime URL")
            return

        self._set_status("Scraping MyAnimeList...")
        self._log(f"Scraping: {url}")
        self._progress_start_indeterminate()

        debug = bool(getattr(self.settings, "debug", False))
        if debug:
            self._log("Debug: MAL scrape started")
            self._log(f"Debug: URL: {url}")

        def run() -> None:
            try:
                import time

                t0 = time.perf_counter()

                def mal_log(m: str) -> None:
                    if debug:
                        self.worker_to_ui.put(("log", m))

                title, openings, endings, year = scrape_mal_title_and_themes(url, timeout_s=20, log_cb=mal_log if debug else None)
                dt_ms = int((time.perf_counter() - t0) * 1000)
                if debug:
                    self.worker_to_ui.put(("log", f"Debug: MAL scrape finished in {dt_ms}ms"))
                    self.worker_to_ui.put(("log", f"Debug: Title: {title}"))
                    self.worker_to_ui.put(("log", f"Debug: Openings: {len(openings)}"))
                    self.worker_to_ui.put(("log", f"Debug: Endings: {len(endings)}"))
                self.worker_to_ui.put(("themes_loaded", (title, openings, endings, year)))
            except Exception as e:
                self.worker_to_ui.put(("error", f"Scrape failed: {e}"))
            finally:
                self.worker_to_ui.put(("scrape_done", None))

        threading.Thread(target=run, daemon=True).start()

    def _clear_queue(self) -> None:
        if self.worker and self.worker.is_alive():
            mb.showwarning("Busy", "Stop processing before clearing")
            return
        self.queue_list.delete(0, "end")
        self._queue_metadata.clear()
        self._current_queue_index = None
        self.tvdb_url_var.set("")
        self.current_song_var.set("")
        self.song_url_var.set("")
        self._set_progress(0)
        self._set_status("Queue cleared")

    def _start_processing(self) -> None:
        if self.worker and self.worker.is_alive():
            mb.showwarning("Busy", "Already processing")
            return

        if self.queue_list.size() == 0:
            mb.showinfo("Empty", "Queue is empty")
            return

        if not self.settings.download_dir or not self.settings.mp3_dir:
            mb.showerror("Settings required", "Set Download folder and MP3 output folder in Settings")
            return

        ensure_dir(self.settings.download_dir)
        ensure_dir(self.settings.mp3_dir)

        self.stop_flag.clear()
        self.waiting_for_confirm.clear()

        items = [self.queue_list.get(i) for i in range(self.queue_list.size())]
        self.worker = threading.Thread(target=self._worker_loop, args=(items,), daemon=True)
        self.worker.start()
        self._set_status("Processing...")

    def _stop_processing(self) -> None:
        self.stop_flag.set()
        self.waiting_for_confirm.set()
        self._set_status("Stopping...")

    def _open_song_url(self) -> None:
        url = self.song_url_var.get().strip()
        if not url:
            return
        webbrowser.open(url)

    def _use_url_download(self) -> None:
        url = self.song_url_var.get().strip()
        if not url:
            mb.showerror("Missing URL", "Enter a YouTube URL first")
            return

        if self.waiting_for_confirm.is_set():
            self.ui_to_worker.put(("confirm", (url, self._snapshot_tags())))
            return

        if self.worker and self.worker.is_alive():
            mb.showwarning("Busy", "Already processing the queue. Use Stop first, or wait until it asks for confirmation.")
            return

        self.stop_flag.clear()
        self._set_progress(0)
        self.current_song_var.set("Direct download")

        def run() -> None:
            try:
                def log_cb(m: str) -> None:
                    self.worker_to_ui.put(("log", m))

                def stage_cb(stage: str) -> None:
                    self.worker_to_ui.put(("status", stage))

                def progress_cb(frac: float, label: str) -> None:
                    self.worker_to_ui.put(("progress", (frac, label)))

                tags = self._snapshot_tags()
                download_url_to_mp3(
                    url,
                    display_name="download",
                    settings=self.settings,
                    tags=tags,
                    log_cb=log_cb,
                    stage_cb=stage_cb,
                    progress_cb=progress_cb,
                )
                self.worker_to_ui.put(("status", "Done"))
            except Exception as e:
                self.worker_to_ui.put(("error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _skip_current_song(self) -> None:
        if self.waiting_for_confirm.is_set():
            self.ui_to_worker.put(("skip", None))
            return

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_to_ui.get_nowait()
                if kind == "themes_loaded":
                    title, openings, endings, year = payload
                    self.tvdb_url_var.set(tvdb_search_url(title))
                    self.queue_list.delete(0, "end")
                    self._queue_metadata.clear()
                    self._current_queue_index = None
                    for i, s in enumerate(openings):
                        self.queue_list.insert("end", f"OP: {s}")
                        self._queue_metadata[i] = ID3Tags(
                            song=s,
                            album=title,
                            album_artist=self.settings.default_album_artist or "Openings and Endings",
                            genre=self.settings.default_genre or "Anime",
                            year=year or "",
                        )
                    for i, s in enumerate(endings, start=len(openings)):
                        self.queue_list.insert("end", f"ED: {s}")
                        self._queue_metadata[i] = ID3Tags(
                            song=s,
                            album=title,
                            album_artist=self.settings.default_album_artist or "Openings and Endings",
                            genre=self.settings.default_genre or "Anime",
                            year=year or "",
                        )
                    self._set_status(f"Loaded {len(openings)} OP and {len(endings)} ED")
                elif kind == "search_result":
                    idx, song, url = payload
                    if self.queue_list.curselection() and self.queue_list.curselection()[0] == idx:
                        self.song_url_var.set(url or "")
                        if url:
                            self._set_status(f"Found YouTube URL for {song}")
                        else:
                            self._set_status(f"No YouTube results for {song}")
                    else:
                        self._log(f"Search result for item {idx}: {url or 'No results'}")
                elif kind == "scrape_done":
                    self._progress_stop_indeterminate()
                elif kind == "need_confirm":
                    song, url = payload
                    self.current_song_var.set(song)
                    self.song_url_var.set(url or "")
                    self._set_progress(0)
                    self._reset_tags_for_new_track()
                    self._set_status("Confirm YouTube URL then click 'Use URL + Download' (or Skip)")
                elif kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self._set_status(str(payload))
                elif kind == "progress":
                    frac, label = payload
                    self._set_progress(frac * 100.0)
                    if label:
                        self._set_status(label)
                elif kind == "done":
                    self.waiting_for_confirm.clear()
                    self._set_status("Done")
                    self.current_song_var.set("")
                    self.song_url_var.set("")
                    self._set_progress(0)
                elif kind == "error":
                    self.waiting_for_confirm.clear()
                    self._set_progress(0)
                    self._set_status("Error")
                    mb.showerror("Error", str(payload))
        except queue.Empty:
            pass

        self.after(100, self._poll_worker_queue)

    def _wait_for_user_action(self) -> Tuple[str, Optional[str]]:
        self.waiting_for_confirm.set()
        while True:
            if self.stop_flag.is_set():
                self.waiting_for_confirm.clear()
                return "stop", None
            try:
                kind, payload = self.ui_to_worker.get(timeout=0.1)
                if kind in ("confirm", "skip"):
                    self.waiting_for_confirm.clear()
                    return kind, payload
            except queue.Empty:
                continue

    def _worker_loop(self, items: List[str]) -> None:
        try:
            for item in items:
                if self.stop_flag.is_set():
                    break

                song = item.split(":", 1)[-1].strip()

                self.worker_to_ui.put(("status", f"Searching YouTube: {song}"))
                self.worker_to_ui.put(("log", f"Searching: {song}"))

                url = None
                try:
                    url = yt_search_first(song)
                except Exception as e:
                    self.worker_to_ui.put(("log", f"Search failed for '{song}': {e}"))

                self.worker_to_ui.put(("need_confirm", (song, url)))
                action, payload = self._wait_for_user_action()
                if action == "stop":
                    break
                if action == "skip":
                    self.worker_to_ui.put(("log", f"Skipped: {song}"))
                    continue

                youtube_url = ""
                tags = ID3Tags(
                    album_artist=self.settings.default_album_artist or "Openings and Endings",
                    genre=self.settings.default_genre or "Anime",
                )
                if isinstance(payload, tuple) and len(payload) == 2:
                    youtube_url = str(payload[0])
                    if isinstance(payload[1], ID3Tags):
                        tags = payload[1]
                else:
                    youtube_url = str(payload)

                def log_cb(m: str) -> None:
                    self.worker_to_ui.put(("log", m))

                def stage_cb(stage: str) -> None:
                    self.worker_to_ui.put(("status", stage))

                def progress_cb(frac: float, label: str) -> None:
                    self.worker_to_ui.put(("progress", (frac, label)))

                download_url_to_mp3(
                    youtube_url,
                    display_name=song,
                    settings=self.settings,
                    tags=tags,
                    log_cb=log_cb,
                    stage_cb=stage_cb,
                    progress_cb=progress_cb,
                )

            self.worker_to_ui.put(("done", None))
        except Exception as e:
            self.worker_to_ui.put(("error", str(e)))


def main() -> None:
    app = App()
    app.mainloop()
