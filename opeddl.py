import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import tkinter.ttk as ttk
import webbrowser
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from mutagen.id3 import ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from yt_dlp import YoutubeDL


APP_NAME = "opeddl"


@dataclass
class AppSettings:
    download_dir: str = ""
    mp3_dir: str = ""
    poster_dir: str = ""
    mp3_bitrate_kbps: int = 320
    default_album_artist: str = "Openings and Endings"
    default_genre: str = "Anime"
    tvdb_enabled: bool = False
    tvdb_api_key: str = ""


def _settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    return base / APP_NAME / "settings.json"


def load_settings() -> AppSettings:
    p = _settings_path()
    if not p.exists():
        return AppSettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return AppSettings(**data)
    except Exception:
        return AppSettings()


def save_settings(s: AppSettings) -> None:
    p = _settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")


def ensure_dir(path_str: str) -> None:
    if not path_str:
        return
    Path(path_str).mkdir(parents=True, exist_ok=True)


def parse_mal_themes_from_soup(soup: BeautifulSoup) -> Tuple[List[str], List[str]]:

    openings: List[str] = []
    endings: List[str] = []

    candidates = soup.select("div.theme-songs")
    text_blocks: List[str] = []
    for c in candidates:
        t = c.get_text("\n", strip=True)
        if t:
            text_blocks.append(t)

    if not text_blocks:
        full_text = soup.get_text("\n", strip=True)
        m = re.search(r"Theme Songs(.*?)(?:Edit\s*Theme\s*Songs|Characters & Voice Actors|Staff|Reviews)", full_text, re.IGNORECASE | re.DOTALL)
        if m:
            text_blocks = [m.group(1)]
        else:
            text_blocks = [full_text]

    section: Optional[str] = None
    for block in text_blocks:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if re.search(r"^Opening Theme", line, re.IGNORECASE):
                section = "op"
                continue
            if re.search(r"^Ending Theme", line, re.IGNORECASE):
                section = "ed"
                continue

            m = re.match(r"^(?:#\d+:\s*)?\"(.+?)\"\s*(?:by\s+(.+?))?(?:\s*\(.*\))?$", line)
            if m and section in ("op", "ed"):
                title = m.group(1).strip()
                artist = (m.group(2) or "").strip()
                query = f"{title} {artist}".strip()
                if section == "op":
                    openings.append(query)
                else:
                    endings.append(query)
                continue

            if section in ("op", "ed") and "\"" in line:
                m2 = re.search(r"\"(.+?)\"", line)
                if m2:
                    title = m2.group(1).strip()
                    rest = re.sub(r".*?\".+?\"", "", line).strip()
                    rest = re.sub(r"^by\s+", "", rest, flags=re.IGNORECASE)
                    rest = re.sub(r"\(.*\)$", "", rest).strip()
                    query = f"{title} {rest}".strip()
                    if section == "op":
                        openings.append(query)
                    else:
                        endings.append(query)

    def _dedupe(xs: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in xs:
            k = x.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    return _dedupe(openings), _dedupe(endings)


def scrape_mal_themes(mal_url: str, timeout_s: int = 20) -> Tuple[List[str], List[str]]:
    r = requests.get(mal_url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return parse_mal_themes_from_soup(soup)


def scrape_mal_title_and_themes(mal_url: str, timeout_s: int = 20) -> Tuple[str, List[str], List[str]]:
    r = requests.get(mal_url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    h1 = soup.select_one("h1.title-name")
    if h1:
        title = h1.get_text(" ", strip=True)
    if not title:
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            title = str(og.get("content")).strip()

    openings, endings = parse_mal_themes_from_soup(soup)
    return title, openings, endings


def tvdb_search_url(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return ""
    return f"https://thetvdb.com/search?query={requests.utils.quote(q)}"


def yt_search_first(query: str) -> Optional[str]:
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": True,
        "noplaylist": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        entries = info.get("entries") if isinstance(info, dict) else None
        if not entries:
            return None
        e0 = entries[0]
        if not isinstance(e0, dict):
            return None
        vid = e0.get("id")
        if not vid:
            url = e0.get("url")
            if url and str(url).startswith("http"):
                return str(url)
            return None
        return f"https://www.youtube.com/watch?v={vid}"


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def download_best_video(youtube_url: str, download_dir: str) -> Path:
    ensure_dir(download_dir)
    outtmpl = str(Path(download_dir) / "%(title)s [%(id)s].%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        fp = ydl.prepare_filename(info)
        p = Path(fp)
        if p.suffix.lower() != ".mp4":
            mp4 = p.with_suffix(".mp4")
            if mp4.exists():
                return mp4
        return p


def _resolve_ffmpeg_exe() -> str:
    here = Path(__file__).resolve().parent
    candidates = [
        here / "ffmpeg.exe",
        here / "bin" / "ffmpeg.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    return ""


def ffmpeg_extract_mp3(video_path: Path, mp3_path: Path, bitrate_kbps: int) -> None:
    ffmpeg_exe = _resolve_ffmpeg_exe()
    if not ffmpeg_exe:
        raise RuntimeError(
            "ffmpeg not found. Put ffmpeg.exe next to opeddl.py (or in bin/ffmpeg.exe), or install ffmpeg and add it to PATH."
        )

    mp3_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        f"{bitrate_kbps}k",
        str(mp3_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.strip() or p.stdout.strip()}")


def write_id3_tags(mp3_path: Path, tags: "ID3Tags") -> None:
    audio = MP3(str(mp3_path), ID3=ID3)
    if audio.tags is None:
        audio.add_tags()

    def _set(frame):
        audio.tags.setall(frame.FrameID, [frame])

    if tags.song:
        _set(TIT2(encoding=3, text=tags.song))
    if tags.artist:
        _set(TPE1(encoding=3, text=tags.artist))
    if tags.album:
        _set(TALB(encoding=3, text=tags.album))
    if tags.album_artist:
        _set(TPE2(encoding=3, text=tags.album_artist))
    if tags.genre:
        _set(TCON(encoding=3, text=tags.genre))
    if tags.year:
        _set(TDRC(encoding=3, text=tags.year))
    if tags.track:
        _set(TRCK(encoding=3, text=tags.track))
    if tags.disk:
        _set(TPOS(encoding=3, text=tags.disk))

    audio.save(v2_version=3)


@dataclass
class ID3Tags:
    song: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = "Openings and Endings"
    genre: str = "Anime"
    year: str = ""
    track: str = ""
    disk: str = ""


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, settings: AppSettings):
        super().__init__(master)
        self.title("Settings")
        self.resizable(False, False)
        self.settings = settings
        self.result: Optional[AppSettings] = None

        self.var_download = tk.StringVar(value=settings.download_dir)
        self.var_mp3 = tk.StringVar(value=settings.mp3_dir)
        self.var_poster = tk.StringVar(value=settings.poster_dir)
        self.var_bitrate = tk.IntVar(value=settings.mp3_bitrate_kbps)
        self.var_album_artist = tk.StringVar(value=settings.default_album_artist)
        self.var_genre = tk.StringVar(value=settings.default_genre)
        self.var_tvdb_enabled = tk.BooleanVar(value=settings.tvdb_enabled)
        self.var_tvdb_key = tk.StringVar(value=settings.tvdb_api_key)

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

        ttk.Label(frm, text="Poster folder (optional)").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_poster, width=55).grid(row=r, column=1, sticky="we")
        ttk.Button(frm, text="Browse", command=lambda: browse_dir(self.var_poster)).grid(row=r, column=2)
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

        ttk.Checkbutton(frm, text="Enable TVDB poster download (requires API key)", variable=self.var_tvdb_enabled).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Label(frm, text="TVDB API key").grid(row=r, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_tvdb_key, width=55, show="*").grid(row=r, column=1, sticky="we")
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
            poster_dir=self.var_poster.get().strip(),
            mp3_bitrate_kbps=int(self.var_bitrate.get()),
            default_album_artist=self.var_album_artist.get().strip() or "Openings and Endings",
            default_genre=self.var_genre.get().strip() or "Anime",
            tvdb_enabled=bool(self.var_tvdb_enabled.get()),
            tvdb_api_key=self.var_tvdb_key.get().strip(),
        )
        self.result = s
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("oped-dl")
        self.geometry("900x650")

        self.settings = load_settings()

        self.work_q: queue.Queue = queue.Queue()
        self.ui_q: queue.Queue = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()

        self.mal_url_var = tk.StringVar()
        self.tvdb_url_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.song_url_var = tk.StringVar()
        self.current_song_var = tk.StringVar(value="")

        self.tags = ID3Tags(
            album_artist=self.settings.default_album_artist or "Openings and Endings",
            genre=self.settings.default_genre or "Anime",
        )

        self._build_ui()
        self.after(100, self._poll_ui_queue)

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

        frm_queue = ttk.LabelFrame(left, text="Queue")
        frm_queue.pack(fill="both", expand=True)

        self.queue_list = tk.Listbox(frm_queue, height=20)
        self.queue_list.pack(fill="both", expand=True, padx=8, pady=8)

        q_btns = ttk.Frame(frm_queue)
        q_btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(q_btns, text="Start", command=self._start_processing).pack(side="left")
        ttk.Button(q_btns, text="Stop", command=self._stop_processing).pack(side="left", padx=(8, 0))
        ttk.Button(q_btns, text="Clear", command=self._clear_queue).pack(side="left", padx=(8, 0))

        frm_song = ttk.LabelFrame(right, text="Current song")
        frm_song.pack(fill="x")

        ttk.Label(frm_song, textvariable=self.current_song_var, wraplength=520).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))

        ttk.Label(frm_song, text="YouTube URL").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(frm_song, textvariable=self.song_url_var).grid(row=1, column=1, sticky="we", pady=8)
        ttk.Button(frm_song, text="Open", command=self._open_song_url).grid(row=1, column=2, padx=8, pady=8)
        frm_song.columnconfigure(1, weight=1)

        song_btns = ttk.Frame(frm_song)
        song_btns.grid(row=2, column=0, columnspan=3, sticky="e", padx=8, pady=(0, 8))
        ttk.Button(song_btns, text="Use URL + Download", command=self._confirm_current_song).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(song_btns, text="Skip", command=self._skip_current_song).grid(row=0, column=1)

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
        def add_row(row: int, label: str, getset):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            ent = ttk.Entry(parent, width=45)
            ent.grid(row=row, column=1, sticky="we", padx=8, pady=4)
            ent.insert(0, getset())

            def on_focus_out(_):
                getset(ent.get())

            ent.bind("<FocusOut>", on_focus_out)
            return ent

        parent.columnconfigure(1, weight=1)

        def gs(attr: str):
            def inner(v=None):
                if v is None:
                    return getattr(self.tags, attr)
                setattr(self.tags, attr, v)
                return v
            return inner

        add_row(0, "Song", gs("song"))
        add_row(1, "Artist", gs("artist"))
        add_row(2, "Album", gs("album"))
        add_row(3, "Album Artist", gs("album_artist"))
        add_row(4, "Genre", gs("genre"))
        add_row(5, "Year", gs("year"))
        add_row(6, "Track", gs("track"))
        add_row(7, "Disk", gs("disk"))

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self.settings = dlg.result
        save_settings(self.settings)
        self.tags.album_artist = self.settings.default_album_artist or "Openings and Endings"
        self.tags.genre = self.settings.default_genre or "Anime"
        self._set_status("Settings saved")

    def _fetch_themes(self) -> None:
        url = self.mal_url_var.get().strip()
        if not url.startswith("https://myanimelist.net/"):
            mb.showerror("Invalid URL", "Please enter a https://myanimelist.net/ anime URL")
            return

        self._set_status("Scraping MyAnimeList...")
        self._log(f"Scraping: {url}")

        def run() -> None:
            try:
                title, openings, endings = scrape_mal_title_and_themes(url, timeout_s=20)
                self.ui_q.put(("themes_loaded", (title, openings, endings)))
            except Exception as e:
                self.ui_q.put(("error", f"Scrape failed: {e}"))

        threading.Thread(target=run, daemon=True).start()

    def _open_tvdb(self) -> None:
        url = self.tvdb_url_var.get().strip()
        if not url:
            return
        webbrowser.open(url)

    def _clear_queue(self) -> None:
        if self.worker and self.worker.is_alive():
            mb.showwarning("Busy", "Stop processing before clearing")
            return
        self.queue_list.delete(0, "end")
        self.tvdb_url_var.set("")
        self.current_song_var.set("")
        self.song_url_var.set("")
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
        if self.settings.poster_dir:
            ensure_dir(self.settings.poster_dir)

        self.stop_flag.clear()

        items = [self.queue_list.get(i) for i in range(self.queue_list.size())]
        self.work_q = queue.Queue()
        for it in items:
            self.work_q.put(it)

        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self._set_status("Processing...")

    def _stop_processing(self) -> None:
        self.stop_flag.set()
        self._set_status("Stopping...")

    def _open_song_url(self) -> None:
        url = self.song_url_var.get().strip()
        if not url:
            return
        webbrowser.open(url)

    def _confirm_current_song(self) -> None:
        url = self.song_url_var.get().strip()
        if not url:
            mb.showerror("Missing URL", "Enter/confirm a YouTube URL first")
            return
        self.ui_q.put(("confirm", url))

    def _skip_current_song(self) -> None:
        self.ui_q.put(("skip", None))

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                if kind == "need_confirm":
                    song, url = payload
                    self.current_song_var.set(song)
                    self.song_url_var.set(url or "")
                    self._set_status("Confirm YouTube URL then click 'Use URL + Download' (or Skip)")
                elif kind == "log":
                    self._log(str(payload))
                elif kind == "status":
                    self._set_status(str(payload))
                elif kind == "themes_loaded":
                    title, openings, endings = payload
                    self.tvdb_url_var.set(tvdb_search_url(title))
                    self.queue_list.delete(0, "end")
                    for s in openings:
                        self.queue_list.insert("end", f"OP: {s}")
                    for s in endings:
                        self.queue_list.insert("end", f"ED: {s}")
                    self._set_status(f"Loaded {len(openings)} OP and {len(endings)} ED")
                elif kind == "done":
                    self._set_status("Done")
                    self.current_song_var.set("")
                    self.song_url_var.set("")
                elif kind == "error":
                    self._set_status("Error")
                    mb.showerror("Error", str(payload))
                else:
                    pass
        except queue.Empty:
            pass
        self.after(100, self._poll_ui_queue)

    def _wait_for_user_action(self) -> Tuple[str, Optional[str]]:
        while True:
            if self.stop_flag.is_set():
                return "stop", None
            try:
                kind, payload = self.ui_q.get(timeout=0.1)
                if kind in ("confirm", "skip"):
                    return kind, payload
            except queue.Empty:
                continue

    def _worker_loop(self) -> None:
        try:
            while not self.work_q.empty() and not self.stop_flag.is_set():
                item = self.work_q.get()
                song = item.split(":", 1)[-1].strip()

                self.ui_q.put(("status", f"Searching YouTube: {song}"))
                self.ui_q.put(("log", f"Searching: {song}"))

                url = None
                try:
                    url = yt_search_first(song)
                except Exception as e:
                    self.ui_q.put(("log", f"Search failed for '{song}': {e}"))

                self.ui_q.put(("need_confirm", (song, url)))
                action, payload = self._wait_for_user_action()
                if action == "stop":
                    break
                if action == "skip":
                    self.ui_q.put(("log", f"Skipped: {song}"))
                    continue

                youtube_url = str(payload)
                self.ui_q.put(("status", f"Downloading: {song}"))
                self.ui_q.put(("log", f"Downloading from: {youtube_url}"))

                video_path = download_best_video(youtube_url, self.settings.download_dir)
                self.ui_q.put(("log", f"Downloaded: {video_path}"))

                out_name = safe_filename(self.tags.song.strip() or song)
                mp3_path = Path(self.settings.mp3_dir) / f"{out_name}.mp3"

                self.ui_q.put(("status", f"Extracting MP3: {mp3_path.name}"))
                ffmpeg_extract_mp3(video_path, mp3_path, self.settings.mp3_bitrate_kbps)

                try:
                    write_id3_tags(mp3_path, self.tags)
                except Exception as e:
                    self.ui_q.put(("log", f"ID3 tagging failed (file is still valid MP3): {e}"))

                try:
                    video_path.unlink(missing_ok=True)
                except Exception:
                    pass

                self.ui_q.put(("log", f"MP3 ready: {mp3_path}"))

            self.ui_q.put(("done", None))
        except Exception as e:
            self.ui_q.put(("error", str(e)))


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
