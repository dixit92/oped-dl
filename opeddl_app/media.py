import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from mutagen.id3 import ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3
from yt_dlp import YoutubeDL

from .settings import AppSettings, ensure_dir


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


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


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


def _resolve_ffmpeg_exe() -> str:
    here = Path(__file__).resolve().parent.parent
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


def _resolve_ffmpeg_location() -> str:
    exe = _resolve_ffmpeg_exe()
    if not exe:
        return ""
    return str(Path(exe).parent)


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
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr.strip() or p.stdout.strip()}")


def write_id3_tags(mp3_path: Path, tags: ID3Tags) -> None:
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


ProgressCb = Callable[[float, str], None]


class _YdlLogger:
    def __init__(self, log_cb: Optional[Callable[[str], None]]):
        self._log_cb = log_cb

    def debug(self, msg):
        return

    def info(self, msg):
        return

    def warning(self, msg):
        if self._log_cb:
            self._log_cb(f"yt-dlp warning: {msg}")

    def error(self, msg):
        if self._log_cb:
            self._log_cb(f"yt-dlp error: {msg}")


def download_best_video(
    youtube_url: str,
    settings: AppSettings,
    progress_cb: Optional[ProgressCb] = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> Tuple[Path, str]:
    ensure_dir(settings.download_dir)
    outtmpl = str(Path(settings.download_dir) / "%(title)s [%(id)s].%(ext)s")

    def hook(d):
        if not progress_cb:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total:
                progress_cb(downloaded / total, "Downloading")
            else:
                progress_cb(0.0, "Downloading")
        elif status == "finished":
            progress_cb(1.0, "Download finished")

    ydl_opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "ffmpeg_location": _resolve_ffmpeg_location() or None,
        "logger": _YdlLogger(log_cb),
        "progress_hooks": [hook],
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        fp = ydl.prepare_filename(info)
        title = ""
        if isinstance(info, dict):
            title = str(info.get("title") or "").strip()
        p = Path(fp)
        if p.suffix.lower() != ".mp4":
            mp4 = p.with_suffix(".mp4")
            if mp4.exists():
                return mp4, title
        return p, title


def download_url_to_mp3(
    youtube_url: str,
    display_name: str,
    settings: AppSettings,
    tags: ID3Tags,
    log_cb: Callable[[str], None],
    stage_cb: Callable[[str], None],
    progress_cb: Optional[ProgressCb] = None,
) -> Path:
    if not settings.download_dir or not settings.mp3_dir:
        raise RuntimeError("Set Download folder and MP3 output folder in Settings")

    ensure_dir(settings.download_dir)
    ensure_dir(settings.mp3_dir)

    stage_cb("Downloading")
    log_cb(f"Downloading from: {youtube_url}")

    video_path, yt_title = download_best_video(
        youtube_url,
        settings,
        progress_cb=progress_cb,
        log_cb=log_cb,
    )
    log_cb(f"Downloaded: {video_path}")

    out_name = safe_filename(tags.song.strip() or yt_title or display_name)
    mp3_path = Path(settings.mp3_dir) / f"{out_name}.mp3"

    stage_cb("Extracting MP3")
    ffmpeg_extract_mp3(video_path, mp3_path, settings.mp3_bitrate_kbps)

    stage_cb("Tagging")
    try:
        write_id3_tags(mp3_path, tags)
    except Exception as e:
        log_cb(f"ID3 tagging failed (file is still valid MP3): {e}")

    stage_cb("Cleaning up")
    try:
        video_path.unlink(missing_ok=True)
    except Exception:
        pass

    stage_cb("Done")
    log_cb(f"MP3 ready: {mp3_path}")
    return mp3_path
