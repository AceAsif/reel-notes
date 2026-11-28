# Reel Notes Bot: Handover (28 Nov 2026)

## 1. Where everything lives

- Bot: @Asif_reel_notes_bot, running locally on Boss's Windows PC (python-telegram-bot, yt-dlp, faster-whisper, ffmpeg, Tesseract, Ollama qwen3:8b)
- Repo: AceAsif/reel-notes (public, MIT licence); local folder `D:\Python projects\reel-notes`
- Notes folder: Google Drive "Reel Notes" folder (fallback: `notes\pending`, auto-moved when Drive is back)
- Main files: `bot.py`, `processor.py`, `tray.py`, `tool_catalog.json`, `tools/chat_sim.py`; BotFather list in `botfather-commands.txt`
- Rules: `CLAUDE.md` and `.claude/` (deny rules, SessionStart and PreToolUse hooks, graphify guard wrapper)
- Repo handover: `docs/HANDOVER.md` (section 13 has the latest state)
- Never committed: `.env`, `notes/`, `bot.log`, `cookies.txt`, `reminders.json`, `sent_jobs.json`, `bot_state.json`, `cleanup_undo.json`, `link_index.json`, `tools-export*.csv`, and the personal file `how to update the bot using pyton command.txt` (being removed from the repo)
- Tests: about 680 passing (`python -m pytest -q`); chat simulator: `python tools/chat_sim.py` (sample notes; `--copy-real-notes` only when Boss runs it himself)
- `gh` is not installed on the PC, so Claude Code gives a `pull/new/...` link and Boss opens and squash-merges the PR himself.

## 2. Done since 23 Nov (PRs #26 to #42)

- Real yt-dlp error shown in chat, cleaned (#26)
- PreToolUse hook fixed: graphify wrapper, force-delete and private-file guard (#27)
- Tool and plugin names checked against the transcript, "(unverified)" mark (#28)
- "No repo found" instead of search links (#29)
- "Already saved" warning with Save again / Show old note / Cancel, note name and saved date (#30, later PR)
- /tools command, tool catalog cleanup, totals and type counts, /tools all (#31 to #34)
- Link index by video ID (/reel/ and /reels/ match) and /dupes (#36)
- New notes' resources cleaned with the catalog; "No link found" for unseen links (#37)
- Chat actions: tick, skip, todo, stats, tools, find by plain English, always with a Yes button; claim guard so the AI never says it did something it didn't (#38)
- Local chat simulator (#38)
- Ponytail audit fixes: intent AI only for task words, shared catalog helper, dead code removed
- Chat task matching searches the whole note; 5 closest actions when nothing matches (#40)
- No more empty Action items: retry, then a default action with a warning (#39)
- /redo replaces the note instead of adding a copy; repo sub-links folded into the repo line (#41)
- Handover updated (#42)

## 3. Open questions to check

- /redo still saved under a new file name in the last test (`_2022_` then `_2026_`). /dupes showed no duplicates. Check after a bot restart that /redo keeps the same file name and leaves no old copy in the notes folder.
- New notes show "No link found" for tools that older notes already linked (Claude Drawing Skill, Bang Motion). Idea: reuse links from past notes.

## 4. Remaining features and effort

| Feature | Effort | Why |
|---|---|---|
| Search by meaning (/search and chat) | Big | Find notes by topic, not exact words; local embeddings |
| Safe file writes (audit item 1) | Medium | A crash or sleep during a save can wipe a note or all reminders |
| Write a prompt from a note, by chat | Medium | "Write me a prompt for the Hallmark task" gives an ART prompt for Claude Code |
| Reuse links from past notes | Small | Fewer "No link found" lines |
| Long video blocks other messages | Medium | Test first: send a long video, then /todo |
| Fuzzy name matching | Medium | Catches unknown mishearings like "Cloud Code" |
| /add (note or task by hand) | Small | For links that cannot download |
| "Other idea" button | Small | Quick extra option |
| Review old notes | Medium | Brings old notes back |
| 7-day habit check | Medium | Checks if notes are acted on |
| Always-on hosting | Big | Works when the PC is off |
| Housekeeping: install gh, LICENSE name, GitHub email privacy, BotFather list | Small | Tidy up |

## 5. Next steps, in order

1. Gitignore the personal file (prompt below).
2. Search by meaning: plan first, then small PRs.
3. Safe file writes straight after.
4. Write a prompt from a note.

## 6. Working rules

- Greet with "Assalamualaikum", reply "Wa alaikum salam", call him "Boss".
- For each file, say which folder it goes in and give a suggested commit message; plain messages only (no Co-Authored-By or Claude-Session lines).
- Prompts for Claude Code: short, ART format, no personal details inside.
- PowerShell commands in code boxes.
- Free local AI only; never send notes outside.
- Workflow: feature branch, `python -m pytest -q` after each step, run the chat simulator after chat changes, update PROGRESS.md, push; never merge (Boss squash-merges).
- After each batch: a status report under 250 words and a to-do list with effort.
- Skills in Claude Code: use the checkpoint skill (small commits and PROGRESS.md handoff), check Claude-Mem for past decisions before starting, and run /ponytail:ponytail-review on each branch's diff before pushing.

## 7. First message for the new chat

Read the Reel Notes Bot handover. I am Boss. Start with search by meaning. Give me a short Claude Code prompt.
