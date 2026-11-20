# Reel Notes: rules for Claude Code

A personal Telegram bot. It turns reels and screenshots into Markdown notes with action
items, and helps the user DO the actions. Read `docs/HANDOVER.md` first, then `README.md`.

## How to work

- Work on a feature branch. Make small commits. Push the branch.
- Do not merge into `main`. The maintainer squash-merges the pull request.
- Open a pull request only when asked. `gh pr create` is blocked here. Use
  `gh api repos/<owner>/<repo>/pulls` instead.
- Commit messages are plain: one short line. Do not add `Co-Authored-By` or
  `Claude-Session` lines, in commits or anywhere else.
- Update `PROGRESS.md` after each step.
- Run `python -m pytest -q` after each step and before each commit. All tests must pass.
  The tests need no network.
- A hook (`.claude/hooks/pre_commit_check.py`) blocks `git commit` when a test fails, a
  private file is staged, a token is found, or the message has a trailer line. Fix the
  problem it names. Do not work around it.
- Always say which folder each file goes in, and suggest a commit message.
- Do not write code when only ideas or a review are asked for.

## Talking to the user

- Use simple English: short sentences, easy words.
- Bot messages and notes are English only. Keep them short and simple.
- Say "I'm not sure" when you are not sure. Do not guess.

## Hard limits

- 100% free and local. No paid APIs. AI is local Ollama (`qwen3:8b`), plus Whisper,
  yt-dlp and Tesseract. If something is paid, mark it optional and give a free option.
- The bot runs on a normal PC that is not always on. Do not suggest always-on hosting.
- Do not suggest anything that needs an Instagram or Facebook login or cookies.
- Never read, print or commit private files: `.env`, `notes/`, `bot.log`, `cookies.txt`,
  `reminders.json`, `sent_jobs.json`, `bot_state.json`, `cleanup_undo.json`.
  The real notes folder is outside the repo. Do not open it.
- Never put a token or private data in the repo, in a test, or in a message.
- Keep personal details out of the repo (names, paths, location, language, hardware).
  The repo is public. Use neutral examples such as `UTC` and `C:\path\to\reel-notes`.

## Code map

- `bot.py` is the Telegram layer: handlers, buttons, scheduled jobs.
- `processor.py` is all the logic. It has no Telegram code.
- `threads_link.py` handles Threads links (public page, one request, no login). It has no Telegram code.
- `tray.py` is the Windows tray icon.
- The note format is a contract. `open_actions`, `save_note`, `note_sections` and
  `plan_parts` all parse it. Do not change a heading or an action line format without
  changing the parsers and the tests.
- When you add a command: update the `/start` text, `README.md`, the BotFather list in
  `botfather-commands.txt`, and add tests.
- The tests use stubs for `pytesseract` and `faster_whisper`. Ollama and GitHub are mocked.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
