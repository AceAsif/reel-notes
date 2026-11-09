# Reel Notes 📝

A personal Telegram bot that turns Instagram and Facebook reels (motivation, tech, programming) into notes with action items, so the useful stuff from reels doesn't get lost.

Send the bot a **reel link** or a **reel video**, and about a minute later you get back:

- a title, category and short summary
- key points
- resources (GitHub repos, tools, links), with a GitHub search link for anything without a URL
- action items you can tick off

Everything runs **free and locally** on your own computer. No paid APIs.

## How it works

```
Reel link ──► yt-dlp downloads the video ─┐
Reel video ───────────────────────────────┤
                                          ▼
              faster-whisper  ──► transcript of what is said
              ffmpeg + Tesseract ──► text shown on screen (repo names, URLs)
                                          ▼
              Ollama (local AI) ──► summary, key points, resources, action items
                                          ▼
              Markdown note saved in notes/  +  reply in Telegram
```

| Part | What it does |
|---|---|
| `bot.py` | Telegram bot: receives links/videos, commands, weekly reminder |
| `processor.py` | Download, transcribe, OCR, summarise, save notes, track actions |
| `notes/` | One `.md` file per reel (not committed to Git) |

## Bot commands

| Command | What it does |
|---|---|
| *(send a reel link)* | Downloads the reel and makes a note |
| *(send a reel video)* | Makes a note from the video (add the link as caption to enable the duplicate check) |
| `/start` | Shows your Telegram user ID |
| `/todo` | Numbered list of open action items, grouped by reel |
| `/done 2` | Ticks off item 2 (or several: `/done 1 3 4`) |

The bot also sends a **weekly review** of open action items every Sunday at 9:00 am, and it skips reels that already have a note.

## Requirements

- Windows, macOS or Linux
- Python 3.12 (3.14 is too new for some dependencies)
- [ffmpeg](https://ffmpeg.org/)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- [Ollama](https://ollama.com/) with a model, e.g. `qwen2.5:7b`
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

A GPU helps (Ollama uses it automatically) but is not required.

## Setup (Windows)

```powershell
# 1. Tools
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install UB-Mannheim.TesseractOCR
winget install Ollama.Ollama
ollama pull qwen2.5:7b

# 2. Project
cd "D:\Python projects\reel-notes"
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Settings
copy .env.example .env
notepad .env        # add TELEGRAM_BOT_TOKEN and TESSERACT_CMD
```

## Run

```powershell
.venv\Scripts\activate
python bot.py
```

The first time, send `/start` to the bot, put your user ID in `.env` as `ALLOWED_USER_ID`, and restart. After that, only you can use the bot.

### Run in the background with a tray icon (Windows)

Double-click `start_bot_hidden.vbs`. A coloured **R** icon appears next to the clock: green = running, yellow = starting, red = stopped. Right-click it to open notes, open the log, restart, stop or quit. It restarts the bot automatically if it crashes, and output goes to `bot.log`.

To start it at login, put a shortcut to `start_bot_hidden.vbs` in the Startup folder (`Win+R` → `shell:startup`). `stop_bot.bat` force-stops everything if the icon isn't responding.

The bot only works while it is running. Messages sent while it's off wait on Telegram for up to 24 hours and are processed when it starts again.

## Settings (`.env`)

| Setting | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | From BotFather. Keep secret |
| `ALLOWED_USER_ID` | — | Your Telegram ID, so only you can use the bot |
| `OLLAMA_MODEL` | `llama3.2` | `qwen2.5:7b` gives much better notes |
| `WHISPER_MODEL` | `small` | `medium` is more accurate but slower |
| `TESSERACT_CMD` | — | Windows: `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| `NOTES_DIR` | `notes` | Where notes are saved |
| `TIMEZONE` | `Australia/Hobart` | For the weekly reminder |
| `FRAME_EVERY_SECONDS` | `2` | How often a frame is read for on-screen text |
| `COOKIES_FILE` | — | Only if Instagram/Facebook downloads need a login |

## Known limits

- Telegram bots can only download videos up to 20 MB (links have no limit).
- On-screen text from busy backgrounds or stylised captions can be noisy. The AI usually fixes obvious typos.
- Instagram may sometimes block downloads without a logged-in cookies file.
- Reel claims (free tokens, "official" plugins) are not checked. The notes include a "verify first" action for big claims.
- For personal use only. Downloading reels may go against Meta's terms of service.

## Troubleshooting

| Problem | Fix |
|---|---|
| `open() got an unexpected keyword argument 'metadata_errors'` | `pip install "av>=12,<14"` |
| Hugging Face symlink warnings | Harmless. Add `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to `.env` |
| `tesseract not found` | Set `TESSERACT_CMD` in `.env` |
| Bot stops right after "Bot is running" | Check `.env` exists and the token is correct |
