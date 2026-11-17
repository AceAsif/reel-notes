# Reel Notes: Handover Document

Last updated: 2026-11-16. This document explains what the bot does, how it works,
and where it is weak, so a new reader (human or AI) can understand it fast and
suggest improvements. Read it together with `README.md` (user guide) and the code.

## 1. What it is

A **personal, single-user Telegram bot** (@Asif_reel_notes_bot) that turns short videos
(Instagram, Facebook, YouTube Shorts, TikTok) and screenshots into **Markdown notes**
with a summary, key points, resources, claims to check and action items. It then helps
the owner *use* the notes: to-do list, due dates, reminders, a daily nudge, search, chat
over the notes, and ready-made prompts for Claude.

**Why it exists:** the owner saves many tech / programming / motivation reels and never
acts on them. The goal is not only to store notes but to turn them into actions.

**Hard constraints (do not break these):**
- 100% **free and local**. No paid APIs. AI runs on local Ollama (`qwen3:8b`).
- **Private**. Notes live in a Google Drive folder. Never commit `.env`, `notes/`,
  `bot.log`, `cookies.txt`, `reminders.json` or `sent_jobs.json` (all in `.gitignore`).
- Only the owner can use it (`ALLOWED_USER_ID`).
- The owner reads simple English (English is not his first language). Bot messages
  must stay short and simple.

## 2. Owner and environment

- Owner: Asif ("Boss"). Works in IT/data; this is a learning + productivity project.
- Windows PC: Ryzen 7 7700, 32 GB RAM, RTX 5060 Ti 8 GB. Python 3.12 venv.
- Project folder: `D:\Python projects\reel-notes`.
- Notes folder: `G:\My Drive\Reel Notes` (Google Drive for desktop), read on the phone.
- Starts with Windows through a tray icon (`tray.py`). Runs only while the PC is on.
- Repo: github.com/AceAsif/reel-notes (public, MIT). Workflow: feature branch, then a pull
  request that the owner squash-merges himself. Plain commit messages.

## 3. Architecture

```
Telegram (phone/PC)
   │  link / video / photo(s) / commands / chat text
   ▼
bot.py  ── handlers, buttons, scheduled jobs (python-telegram-bot v22, long polling)
   │  asyncio.to_thread(...)  (heavy work off the event loop)
   ▼
processor.py ── all logic (no Telegram code)
   ├─ yt-dlp ............ download video / carousel slides / photos + caption + creator
   ├─ faster-whisper .... transcript (medium model, CPU int8); non-English → English
   ├─ ffmpeg+Tesseract .. on-screen text (a frame every 2 s) and photo/screenshot OCR
   ├─ Ollama (HTTP) ..... /api/generate JSON (notes, /ask), /api/chat (chat mode)
   ├─ GitHub REST API ... repo lookup, stars, last update, archived, licence
   └─ Markdown files .... the ONLY database (one .md per note in NOTES_DIR)
```

| File | Role |
|---|---|
| `bot.py` (~1280 lines) | Telegram layer: handlers, inline buttons, jobs, formatting replies |
| `processor.py` (~1770 lines) | Everything else (see section 5) |
| `tray.py` | Windows tray icon: start/stop the bot, open log |
| `tests/` | pytest, 262 tests (stubs for pytesseract and faster_whisper) |
| `PROGRESS.md` | Checkpoint file for the current task (see "checkpoint-and-report" workflow) |
| `.env` | Settings (see section 8) |

**No database.** State = Markdown files + `reminders.json` + `sent_jobs.json` (which
scheduled messages were already sent). Every command re-reads and
parses the notes folder. Simple and easy to inspect/edit by hand, but it is O(notes)
per command and has no index.

## 4. Pipeline: from link to note

1. Message arrives. Handler order matters: link handler, video handler, photo handler,
   then free-text chat (anything that is not a command).
2. **Duplicate check** (`find_note_by_source`, `normalise_url`; YouTube by video ID).
3. `download_media` (yt-dlp; carousels up to 10 slides; photo slides via thumbnails;
   `MAX_MINUTES` limit; optional cookies file). Returns slides, caption, creator.
4. `process_videos`: per slide, `transcribe` (+ `has_audio` for silent carousels) and
   `screen_text` / `image_text` (OCR). Several slides become ONE note, labelled
   `[Slide n]`.
5. `summarise` builds the prompt (`PROMPT`) and calls `ask_ollama_json` (temperature 0.2,
   `num_ctx` 8192, or 16384 for long prompts; `think:false` for qwen3).
6. Post-processing (this is where most quality work lives):
   `clean_actions`, `clean_claims`, `clean_tags`, `clean_motivation_fields`,
   `drop_invented_links` (links kept only if seen in the video/OCR/caption),
   `enrich_with_github` (adds real repo info; GitHub search only when the video talks
   about code, and never for course/doc-like names), `repo_warnings`.
7. `save_note` writes `YYYY-MM-DD_HHMM_title.md`; bot replies with a formatted summary.

**Screenshots:** a photo (or album, grouped by `media_group_id`, max 10) goes through the
same pipeline as photo slides: OCR → Ollama → one note. Telegram downloads use long
timeouts and 3 retries.

## 5. Note format (the contract everything else parses)

```
# Title
- Date: ...        - Category: tech|programming|motivation|other
- Source: <url or "screenshot">     - Creator: Name (@handle) url
- Language: ...    - Slides: ...    - Tags: #a #b
## Summary / Key quote / Main lesson / Habit to try   (motivation only)
## Claims to check      ## From the creator (offers: "comment X", "link in bio")
## Key points           ## Resources
## Action items         ## Transcript   ## On-screen text (fenced)   ## Post caption
```

Action line formats (Obsidian Tasks style):
`- [ ] 🔥 text 📅 2026-11-20` (high / due date), `- [ ] text` normal, `- [ ] 🔽 text` low,
`- [x] ... ✅ date` done, `- [-] ... ❌ date` skipped.
Only lines under "Action items" and "Habit to try" count as actions.
`action_id` = md5(file name + action text)[:10]. It does not use the line number, so it
survives hand edits and priority / due-date changes. Old `hash:line` ids in saved
reminders still work (`legacy_action_id`).
`/todo` numbers: the bot saves the list it last showed (`todo_map` in `user_data`).
`/done 3`, `/due 3`, `/remind 3`... mean the action shown as 3, until the next `/todo`.

## 6. Features (commands)

- **Capture:** link, video file, carousel link, screenshot(s).
- **Actions:** `/todo` (paged, ⏰ DUE SOON, 🔥/▫️/🔽 groups), `/done`, `/skip`, `/high` `/normal`
  `/low`, `/due` (dates), `/remind` (+ `/reminders`, `/unremind`; natural-language dates via
  `parse_when`), `/nudge`.
- **Find:** `/search`, `/notes`, `/note`, `/file`, `/tags`, `/tag`, `/retag`, `/renametag`.
- **Ask:** `/ask` (answers from notes only, lists sources), plain-text **chat mode** with
  follow-ups (`is_follow_up`, last 6 turns, `/newchat` resets).
- **Reflect:** `/stats` (weekly), `/month`, `/remember` (spaced-repetition style resurfacing).
- **Plans:** `/plan 2`, `/plan 1 3 5`, `/plan #tag` build an ART-format prompt for Claude
  from the note(s) only (no AI call, nothing invented).
- **Ops:** `/redo` (rebuild a note, old one moved to `old/`), `/health`, `/update`
  (yt-dlp), nightly yt-dlp auto-update.
- **New note:** one main action (`split_actions`: best priority first). Extra actions go to
  `## Other ideas` (plain bullets). "Comment X / DM me" offers are not actions: they go to
  `## From the creator`. No buttons (the A/B/C pick buttons were removed in batch 3).
- **Action types:** `🤖 ai`, `🧠 habit`, `🔗 lookup`. The AI sets `type`; `guess_kind` is the
  fallback and is used for older notes. Saved after the priority icon: `- [ ] 🔥 🤖 text`.
  `action_id` ignores the icon. `/todo ai|habit|lookup` filters.
- **Doing help (batch 4):** `nudge_message` shows `action_details` (link, 2 key points) and
  buttons 📖 Open note / 🤖 Get prompt (`make_action_prompt` = `plan_text(..., focus=action)`);
  `/prompt N` uses the saved `/todo` numbers. `save_one_candidate`: after a new note, if nothing
  was ticked in 7 days, one older action is offered (once a day, state in `bot_state.json`).
  `LOW_PRIORITY_RE` now needs "link in bio", "DM me" etc. (not "LinkedIn bio", "DM your manager").
  `/undocleanup` restores the last clean-up (`cleanup_undo.json`). `/usage` counts command
  names only (`count_use`, group -2 handler). `question_words` keeps short topic words (ai, uv).
- **Private files (all in .gitignore):** `.env`, `reminders.json`, `sent_jobs.json`,
  `bot_state.json`, `cleanup_undo.json`. Tests redirect them to a temp folder (`tests/conftest.py`).
- **Clean-up:** `/cleanup` (`cleanup_plan`, `skip_actions_by_id`) skips junk offers and extra
  actions (keeps the best per note, due-dated ones and "Habit to try"), after a confirm button.
  The Sunday review hints at it above 30 open actions.
- **Timing:** each note logs `timing: ...` in `bot.log` and shows `⏱` in the reply.
- **Catch-up:** all scheduled jobs go through `run_due_jobs` (exact time, 20 s after start,
  every 5 min). A message missed while the PC was off or asleep is sent when it is back.
- **Scheduled jobs:** daily nudge (08:00), weekly digest (Sun 09:00), weekly resurface
  (Wed 19:00), monthly summary (1st, 09:30), yt-dlp update (03:30), reminders reloaded
  on start.

## 7. Quality rules already built (and why)

- Invented links are dropped; only links seen in the video/OCR/caption survive.
- GitHub matching needs a confident match (install command, link in text, or exact name
  with at least 300 stars). Wrong namesake repos were a real problem.
- Plain "GitHub" in a learning roadmap is **not** a sign of a repo. Course/doc names
  are never searched on GitHub (they get a Google link).
- Creator offers ("comment X") are kept in "From the creator", not deleted, so the
  owner has a way to find the real link when the bot's link is wrong.
- Repo health: archived, no update for over a year, not found, licence shown.
- Silent videos detected (no hallucinated transcript); Hindi etc. translated to English.
- 403 rate limits from GitHub are not reported as "repo not found".

## 8. Settings (`.env`)

`TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`, `TIMEZONE`, `NOTES_DIR`, `WHISPER_MODEL=medium`,
`OLLAMA_MODEL=qwen3:8b`, `FRAME_EVERY_SECONDS`, `TESSERACT_CMD`, `NUDGE_TIME`, `RESURFACE`,
`MAX_MINUTES`, `YTDLP_UPDATE_TIME`, optional `COOKIES_FILE`, `GITHUB_TOKEN`.

## 9. Known weaknesses and open questions

These are the owner's real pain points and honest gaps. Good places to start.

1. **Note quality depends on one 8B local model.** It can still mislabel, merge wrong
   details, or miss the main point (a recurring issue with long roadmap-style reels).
   There is no automatic quality check or second pass.
2. **Whisper runs on CPU** (`device="cpu"`, int8) even though the PC has an RTX 5060 Ti.
   Transcription is probably the slowest step. GPU use is untested.
3. **OCR is noisy** (see "On-screen text" in notes). Frame sampling every 2 s is a blunt
   tool; duplicate frames and low-quality text are common.
4. **Regex-based promo/offer filter** (`LOW_PRIORITY_RE`) is fragile and English-only.
5. **No database/index.** `/search`, chat retrieval (`relevant_notes`) and stats scan
   every file each time. Retrieval is keyword-based, not semantic (no embeddings),
   so chat mode can miss relevant notes.
6. (Fixed) `action_id` no longer uses line numbers, and `/todo` numbers stay the same until
   the next `/todo`. The saved list is in memory only, so it is lost when the bot restarts.
7. **Single process, single user, PC must be on.** No queue: two long jobs at once can
   slow the PC. If the PC is off, nothing runs; missed reminders and scheduled messages are sent when it
   is back (a missed daily nudge only on the same day).
8. **Instagram/Facebook changes break yt-dlp** often; cookies are needed sometimes.
9. **Resources for non-code topics** are only Google search links (no real verification).
10. **Security:** the bot token and cookies are local files; bot trusts `ALLOWED_USER_ID`
    only. No rate limiting; prompt-injection through video text into the notes/chat
    prompt is not specifically handled.
11. Several large functions in `processor.py` (1770 lines) and `bot.py` (1280 lines);
    one file per layer is getting big.

## 10. Backlog (already agreed, with effort)

Small: skip junk resources that are file names (.xlsx), "Done" with a learning note,
`/addnote`, Obsidian export, `/health` in the weekly review, backup zip before
`/renametag` `/retag`.
Medium: voice notes, stats dashboard, projects, merge duplicates, web articles / X posts,
quiz from notes, topic summary.
Big: always-on hosting (VPS/Raspberry Pi) while staying free/private.

## 11. How to run and test

```
python -m venv .venv ; .venv\Scripts\activate ; pip install -r requirements.txt
copy .env.example .env      # fill in token and ALLOWED_USER_ID
python bot.py               # or run tray.py
pip install -r requirements-dev.txt ; python -m pytest      # 262 tests, no network needed
```

Tests use stubs for `pytesseract` and `faster_whisper`; Ollama and GitHub calls are
mocked. Always run the tests before committing.

## 12. Working rules for contributors

- Work on a feature branch, small commits, update `PROGRESS.md`, push. Do not merge to
  `main`; the owner squash-merges the pull request.
- Plain commit messages (no `Co-Authored-By` or session trailer lines).
- Always say which folder each file goes in and give a suggested commit message.
- Keep replies simple, short, and in plain English.
- Never add paid services. Prefer free/local options and explain trade-offs.
