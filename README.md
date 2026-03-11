# oped-dl

Simple GUI tool to scrape opening/ending themes from a MyAnimeList anime page and download them from YouTube as MP3.

## Requirements

- Python 3.10+
- `ffmpeg` either:
  - Installed and available on your PATH, or
  - Placed as `ffmpeg.exe` next to `opeddl.py` (or `bin/ffmpeg.exe`)

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```powershell
python opeddl.py
```

## Usage

1. Open **App -> Settings**
2. Set:
   - Download folder (temporary video location)
   - MP3 output folder
   - MP3 bitrate
3. Paste a `https://myanimelist.net/anime/...` URL
4. Click **Fetch OP/ED**
5. Click **Start**
6. For each song:
   - Confirm or edit the YouTube URL
   - Click **Use URL + Download** (or **Skip**)

## Notes / Limitations

- TVDB integration is limited to showing a TVDB search link.
- yt-dlp may warn about missing a supported JavaScript runtime for YouTube extraction. Installing a runtime like Node.js (LTS) or Deno can improve reliability.
- ID3 tags are applied as-entered to every downloaded file. The app does not auto-populate tags (except default Album Artist and Genre).
