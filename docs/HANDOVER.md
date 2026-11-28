# Reel Notes: Handover Document

Last updated: 2026-11-28 (see section 13 for everything since 23 Nov). This document explains what the bot does, how it works,
and where it is weak, so a new reader (human or AI) can understand it fast and
suggest improvements. Read it together with `README.md` (user guide) and the code.

## 1. What it is

A **personal, single-user Telegram bot** that turns short videos
(Instagram, Facebook, YouTube Shorts, TikTok) and screenshots into **Markdown notes**
with a summary, key points, resources, claims to check and action items. It then helps
the user *use* the notes: to-do list, due dates, reminders, a daily nudge, search, chat
over the notes, and ready-made prompts for Claude.

**Why it exists:** people save many tech / programming / motivation reels and never
act on them. The goal is not only to store notes but to turn them into actions.

**Hard constraints (do not break these):**
- 100% **free and local**. No paid APIs. AI runs on local Ollama (`qwen3:8b`).
- **Private**. Notes live in a synced folder outside the repo (`NOTES_DIR` in `.env`). Never read or
  commit the private files listed in `CLAUDE.md` (all in `.gitignore`).
- Only the allowed user can use it (`ALLOWED_USER_ID`).
- Bot messages must stay short and in simple English.

## 2. Environment

- A normal Windows PC with a mid-size graphics card (the local models must fit in it). Python 3.12 venv.
- Notes folder: a synced cloud folder, read on the phone.
- Starts with Windows through a tray icon (`tray.py`). Runs only while the PC is on.
- Repo: public, MIT. Workflow: feature branch, then a pull request that the maintainer
  squash-merges. Plain commit messages.

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
| `bot.py` (~1900 lines) | Telegram layer: handlers, inline buttons, jobs, formatting replies |
| `processor.py` (~3200 lines) | Everything else (see section 5) |
| `tray.py` | Windows tray icon: start/stop the bot, open log |
| `tests/` | pytest, about 680 tests (stubs for pytesseract and faster_whisper, Ollama mocked) |
| `tools/chat_sim.py` | Chat simulator: real handlers, sample notes, temp files, local Ollama only |
| `tool_catalog.json` | Tool aliases, official links, stoplist and types for `/tools` and new notes |
| `PROGRESS.md` | Checkpoint file for the current task (see "checkpoint-and-report" workflow) |
| `.env` | Settings (see section 8) |

**No database.** State = Markdown files + `reminders.json` + `sent_jobs.json` (which
scheduled messages were already sent) + `link_index.json` (video ID to note, rebuilt from the notes). Every command re-reads and
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
A done action can have ONE indented line under it: `  - 💡 Learned: text` (your reply to "What did you
learn?"). It is not an action and the to-do code ignores it (`LEARNED_PREFIX`, `add_learning`).
`action_id` = md5(file name + action text)[:10]. It does not use the line number, so it
survives hand edits and priority / due-date changes. Old `hash:line` ids in saved
reminders still work (`legacy_action_id`).
`/todo` numbers: the bot saves the list it last showed (`todo_map` in `user_data`).
`/done 3`, `/due 3`, `/remind 3`... mean the action shown as 3, until the next `/todo`.

## 6. Features (commands)

- **Capture:** link (Instagram, Facebook, YouTube Shorts, TikTok, X video posts), video file,
  carousel link, screenshot(s). Threads links are coded (`threads_link.py`) but gave no video in a
  real test: the bot then asks for the video file.
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
  `/redo fast` (`redo_from_saved`): rebuilds from the note's own `## Transcript`, `## On-screen text`
  (fenced) and `## Post caption` (`saved_inputs`), so only the AI runs. Keeps the date and tags;
  done/skipped lines and learnings are copied over (`carry_over`); a new action that is the same idea
  as a finished one is not opened again. Never overwrites another note (`keep_existing`).
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
- **Notes folder missing** (Google Drive not running): the note is saved in `notes/pending` on the PC
  and moved back by `sync_pending` (the 5-minute check) when the folder is back. Nothing is lost.
- **One idea, one to-do:** a habit that says the same as an action is merged (`merge_habit_and_actions`);
  old notes are handled by `/cleanup`.
- **Learning:** after ONE Done (button or `/done N`) the bot asks "What did you learn?" with a
  `ForceReply`. Only a reply to that question is saved (`bot.save_learning`); `ASK_LEARNING=off`
  turns it off. `/month` shows the learnings.
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
  user has a way to find the real link when the bot's link is wrong.
- Repo health: archived, no update for over a year, not found, licence shown.
- Silent videos detected (no hallucinated transcript); Hindi etc. translated to English.
- 403 rate limits from GitHub are not reported as "repo not found".

## 8. Settings (`.env`)

`TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`, `TIMEZONE`, `NOTES_DIR`, `WHISPER_MODEL=medium`,
`OLLAMA_MODEL=qwen3:8b`, `FRAME_EVERY_SECONDS`, `TESSERACT_CMD`, `NUDGE_TIME`, `RESURFACE`,
`MAX_MINUTES`, `YTDLP_UPDATE_TIME`, optional `COOKIES_FILE`, `GITHUB_TOKEN`.

## 9. Known weaknesses and open questions

These are the real pain points and honest gaps. Good places to start.

1. **Note quality depends on one 8B local model.** It can still mislabel, merge wrong
   details, or miss the main point (a recurring issue with long roadmap-style reels).
   There is no automatic quality check or second pass.
2. **Whisper runs on CPU** (`device="cpu"`, int8) even though the PC has a graphics card.
   The timing logs show it is the biggest step: "listen" is about 11 to 37 s of 30 to 61 s per
   reel. GPU use is untested.
3. **OCR is noisy** (see "On-screen text" in notes). Frame sampling every 2 s is a blunt
   tool; duplicate frames and low-quality text are common. It is not slow: 2 to 9 s per reel.
4. **Regex-based promo/offer filter** (`LOW_PRIORITY_RE`) is fragile and English-only.
5. **No database/index.** `/search`, chat retrieval (`relevant_notes`) and stats scan
   every file each time. Retrieval is keyword-based, not semantic (no embeddings),
   so chat mode can miss relevant notes.
6. (Fixed) `action_id` no longer uses line numbers, and `/todo` numbers stay the same until
   the next `/todo`. The saved list is in memory only, so it is lost when the bot restarts.
7. **Single process, single user, PC must be on.** No queue: two long jobs at once can
   slow the PC. If the PC is off, nothing runs; missed reminders and scheduled messages are sent when it
   is back (a missed daily nudge only on the same day).
8. **Instagram/Facebook changes break yt-dlp** often; cookies are needed sometimes. **Threads**
   gave no video from its public page in a real test (login wall or empty page).
9. (Fixed) Resources no longer get Google search links. A link stays only if the video showed it or
   the catalog has it; otherwise "No link found".
10. **Security:** the bot token and cookies are local files; bot trusts `ALLOWED_USER_ID`
    only. No rate limiting; prompt-injection through video text into the notes/chat
    prompt is not specifically handled.
11. Several large functions in `processor.py` (about 2500 lines) and `bot.py` (about 1600 lines);
    one file per layer is getting big.
12. **"High" priority means little:** in a real list, about half of the open actions were 🔥. The AI
    marks too many. "Pick 3 for this week" (section 10) is the planned fix.

## 10. Feature to-do list (updated 2026-11-21)

How it is ranked: does it help the user DO the actions that were saved? Real numbers from the
bot on 2026-11-21: about 105 reels saved in a month, 2 actions done, 110 open actions. Of the
open ones, 56 are 🔥 high (so "high" tells very little) and 32 are habits (🧠).

### Done

- **Capture:** Instagram, Facebook, YouTube Shorts, TikTok, X (video posts), screenshots, a video
  file. Threads: coded, but a real test gave no video (see section 9), so it is not reliable.
- **Do-features:** one action per reel, action types (🤖 🧠 🔗), `/cleanup` and `/undocleanup`,
  "save one, do one" after a new note, a nudge with the link and key points, 🤖 Get prompt
  (`/prompt`), "What did you learn?" after a Done (shown in `/month`), habit and action merged into
  one to-do, `/redo fast` (rebuild a note from its saved text, no download), stable `/todo` numbers, catch-up of missed messages when the PC starts.
- **Reliability and tools:** timing in the reply and `bot.log`, notes kept on the PC when Google Drive
  is missing (and moved back later), search that keeps short words (ai, uv), `/usage`, rules and
  hooks for Claude Code (`CLAUDE.md`, `.claude/`).

### To do, in the order I suggest

| # | Feature | Effort | Why |
|---|---|---|---|
| 1 | **Pick 3 for this week.** The Sunday review shows your top actions as buttons. Tap up to 3. The nudge uses only those. | 🟡 | Half of the open actions are 🔥, so priority is not a plan. Three is a plan. |
| 2 | **Keep or drop after 3 nudges.** Count the nudges per action. After 3 with no Done, ask: Keep / Drop. | 🟢 | An action ignored 3 times will not be done by a 4th message. |
| 3 | **`/review` old notes.** One old note at a time with Keep / Drop buttons. | 🟡 | You choose your list, 5 notes per round. |
| 4 | **Bring back an "Other idea".** `/note` shows a button to move an idea into the to-do list. | 🟢 | Extra ideas are plain bullets. You cannot bring one back from Telegram. |
| 5 | **7-day habit check** for 🧠 actions. | 🟡 | 32 of the 110 open actions are habits. A habit is not a one-time tick. |
| 6 | (Done 2026-11-26) **`/tools` list.** All tools and repos from all notes, with the number of notes that mention each. | 🟢 | A tool in 4 reels is a strong sign to try it first. |
| 7 | **"You already saved this topic".** One line under a new note when older notes share 2 or more tags. | 🟢 | Saving the same idea again and again is a hint to act on it. |
| 8 | **Topic cheat sheet** (`/topic claude`). Merge the key points of one tag into one page. | 🟡 | Ten small notes become one page. Limit to 8 notes and show the sources. |
| 9 | **`/add`.** Add your own action. | 🟢 | One list for everything. Low rank: your problem is doing, not adding. |

### Small fixes and checks

- `/month`: show the action next to each learning (today it shows only the learning). 🟢
- README: say that Threads video may not work. 🟢
- Speed: "listen" (Whisper on the CPU) is the biggest step, about 11 to 37 s of 30 to 61 s per reel.
  OCR is only 2 to 9 s. Test Whisper on the GPU (`WHISPER_DEVICE` with a fallback to CPU).
  It shares the graphics card with Ollama, so measure first. 🟡
- After 2 weeks of `/usage`: hide the commands nobody uses. Candidates: `/ask` (chat does the same),
  `/high` `/normal` `/low`, `/tags`, `/retag`, `/renametag`, `/file`, `/update`. Decide from the counts.
- (Done) Skip junk resources that are file names (.xlsx).
- Show `/health` in the weekly review. 🟢
- Backup copy before `/renametag` and `/retag`. 🟢
- Check: send one Facebook share link again. The failure on 2026-11-19 was the missing Google Drive,
  not Facebook.
- Check: paste the BotFather list (`botfather-commands.txt`) into BotFather when commands are added.

### Later (after the do-features)

Voice note to action, web articles, quiz from notes, projects (group actions under one goal).
These add more things to save or are about remembering. They do not fix "I do not act".

### Not now

- Always-on hosting: against the rules (free, local, the PC is not always on).
- Threads video: the public page gives no video without a login. Use the file fallback.
- Obsidian export and a stats dashboard: Telegram is the only screen.
- Anything that needs an Instagram or Facebook login or cookies.

## 11. How to run and test

```
python -m venv .venv ; .venv\Scripts\activate ; pip install -r requirements.txt
copy .env.example .env      # fill in token and ALLOWED_USER_ID
python bot.py               # or run tray.py
pip install -r requirements-dev.txt ; python -m pytest -q   # about 680 tests, no network needed
python tools/chat_sim.py --file tests/chat_scenarios.txt     # chat check with the local model
```

Tests use stubs for `pytesseract` and `faster_whisper`; Ollama and GitHub calls are
mocked. Always run the tests before committing.

## 12. Working rules for contributors

- Work on a feature branch, small commits, update `PROGRESS.md`, push. Do not merge to
  `main`; the maintainer squash-merges the pull request.
- Plain commit messages (no `Co-Authored-By` or session trailer lines).
- Always say which folder each file goes in and give a suggested commit message.
- Keep replies simple, short, and in plain English.
- Never add paid services. Prefer free/local options and explain trade-offs.

## 13. Handover 2026-11-28

### Where everything lives

| What | Where |
|---|---|
| Telegram layer (handlers, buttons, jobs, chat routing) | `bot.py` |
| All logic: pipeline, note format, `/tools` cleaning, link index, chat intent and task matching | `processor.py` |
| Threads links (public page, one request) | `threads_link.py` |
| Tray icon | `tray.py` |
| Tool aliases, official links, stoplist, types | `tool_catalog.json` |
| Chat simulator (sample notes, temp files, local Ollama only) | `tools/chat_sim.py` |
| Chat scenarios for the simulator | `tests/chat_scenarios.txt` |
| Tests (no network) | `tests/` (`conftest.py` keeps every private file in a temp folder and blocks Ollama) |
| Rules for Claude Code, hooks | `CLAUDE.md`, `.claude/settings.json`, `.claude/hooks/` |
| BotFather command list | `botfather-commands.txt` |
| Current task checkpoint | `PROGRESS.md` (rewritten for each branch) |
| Private, never read or committed | `.env`, the notes folder, `bot.log`, `cookies.txt`, `reminders.json`, `sent_jobs.json`, `bot_state.json`, `cleanup_undo.json`, `link_index.json` |

### Working rules (short version of `CLAUDE.md`)

- One feature branch per task, small commits, push. Never merge; the owner squash-merges.
- Plain one-line commit messages, no trailer lines. `gh pr create` is blocked; give the
  `pull/new/<branch>` link or use `gh api`.
- `python -m pytest -q` before every commit (the hook blocks a commit when a test fails).
- After changing chat or intent code: `python tools/chat_sim.py --file tests/chat_scenarios.txt`.
- Never read private files or the real notes. The hook blocks any command that names one.
- A new command: update `/start`, `README.md`, `botfather-commands.txt`, and add tests.
- Free and local only. Simple English. Say "I'm not sure" instead of guessing.

### Done since 23 Nov (pull request numbers)

- #26 The real yt-dlp error is shown when a download fails. #27 Hooks work without graphify.
- #28 Tool names not in the transcript, OCR or caption are marked "(unverified)".
- #29 No Google or GitHub search links in resources.
- #30, #35 "Already saved" warning: title, file, saved time, folder; Save again, Show old note (short,
  with a Full note button), Cancel.
- #31, #32, #34 `/tools` and `/tools all`: totals, counts per type, cleaned with `tool_catalog.json`
  (aliases, stoplist, official links, bad links dropped, "X GitHub" folded into X).
- #36 Duplicate links found by video ID (Instagram /reel/ /reels/ /p/ /tv/, TikTok, YouTube, Facebook,
  X, Threads) through `link_index.json`, which rebuilds itself. `/dupes` lists videos saved twice.
- #37 New notes: resources cleaned with the catalog; a link stays only if the video showed it.
- #38 Chat can do tasks: "I finished the X task" or "skip the X one" finds the action and asks
  Yes / Not this one / Cancel. "show my todo list", stats, tools, dupes, find and open note run the
  commands. Chat replies may not claim they changed anything. Intent AI is asked only when the message
  has a task word. Chat simulator added.
- #39 A new note always gets an action: the AI is asked again, then a default ("Try <tool>: <link>"
  or "Review this note") with a warning. Shared-link resources and repeated transcripts fixed.

Pushed, not merged yet (owner to merge):
- `fix/chat-task-matching`: task matching looks at the whole note (title, file name, summary, tags,
  resources); several matches or none show action buttons. main is merged into it.
- `fix/redo-and-repo-links`: `/redo` writes into the same file (no `old/` copy) and keeps done and
  skipped actions; links inside a GitHub repo join that repo's line as "also:".

### Open to-dos

| To-do | Effort |
|---|---|
| Save notes and state files safely: write to a temp file, then replace (a crash mid-save can empty a note or lose all reminders) | small |
| Paste the new `botfather-commands.txt` into BotFather (`/tools`, `/dupes`) | small |
| Install `gh` on the PC so pull requests can be opened from Claude Code | small |
| Short links (`vm.tiktok.com`, share links) only match the same short link | medium |
| "Not this one" and the pick list show at most 5 actions; a common word (e.g. "Claude") can fill them | medium |
| A task message without a task word ("I sent the card") goes to normal chat, no buttons | medium |
| Test Whisper on the graphics card (it is the slowest step) | medium |
| Pick 3 for this week; keep or drop after 3 nudges; `/review` old notes (section 10) | medium to big |
| Long video processing may block other messages until it is done (not tested) | big |

### First message for the new chat

"Read `CLAUDE.md`, then `docs/HANDOVER.md` section 13, then `PROGRESS.md`. Check which open branches
are merged (`git branch -r --no-merged origin/main`). Then tell me the open to-dos and wait."
