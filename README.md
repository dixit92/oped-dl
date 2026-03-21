# oped-dl

A simple Python GUI tool to scrape opening and ending themes from a MyAnimeList (MAL) page and download them from YouTube as high-quality MP3s.

## Features

- Scrapes song titles and artists directly from MyAnimeList.
- Searches for and downloads audio using `yt-dlp`.
- Automatically applies ID3 tags (Artist, Album, Genre) using `mutagen`.
- Integrated GUI for managing downloads and settings.

## Requirements

- **Python 3.10+**
- **FFmpeg**: Must be available on your system `PATH` or placed in a `/bin` folder in the project root.
  - *Note: Binaries are ignored by Git and must be added manually.*
- **JavaScript Runtime (Optional)**: Installing Node.js (LTS) or Deno can improve `yt-dlp` reliability for YouTube extraction.

## Installation

1. **Clone the repository**:
   ```powershell
   git clone https://github.com/your-repo/oped-dl
   cd oped-dl
   ```

2. **Create a virtual environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

## Usage

1. **Start the app**:
   ```powershell
   python opeddl.py
   ```

2. **Configure folders**: Go to `App -> Settings` to set your Temporary Video and Final MP3 output folders.

3. **Fetch music**: Paste a MyAnimeList URL (e.g., `https://myanimelist.net/anime/...`) and click **Fetch OP/ED**.

4. **Download**: Select an OP/ED item, click **Search YouTube** to find a URL, then click **Download**.

## Dependencies

- `requests`: HTTP requests
- `beautifulsoup4`: HTML parsing
- `yt-dlp`: YouTube downloading
- `mutagen`: ID3 tagging

## Notes

- TVDB integration is limited to a search link.
- ID3 tags are applied as entered in the UI.
- Network dependency on MyAnimeList and YouTube availability.
