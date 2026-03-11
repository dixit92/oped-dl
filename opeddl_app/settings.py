import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import APP_NAME


@dataclass
class AppSettings:
    download_dir: str = ""
    mp3_dir: str = ""
    mp3_bitrate_kbps: int = 320
    default_album_artist: str = "Openings and Endings"
    default_genre: str = "Anime"
    debug: bool = False


def _settings_path() -> Path:
    base = Path(os.environ.get("APPDATA", str(Path.home())))
    return base / APP_NAME / "settings.json"


def load_settings() -> AppSettings:
    p = _settings_path()
    if not p.exists():
        return AppSettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AppSettings()

        allowed = {f.name for f in fields(AppSettings)}
        filtered = {k: v for k, v in data.items() if k in allowed}
        
        if "mp3_bitrate_kbps" in filtered:
            try:
                filtered["mp3_bitrate_kbps"] = int(filtered["mp3_bitrate_kbps"])
            except Exception:
                filtered.pop("mp3_bitrate_kbps", None)

        if "debug" in filtered:
            filtered["debug"] = bool(filtered["debug"])

        return AppSettings(**filtered)
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
