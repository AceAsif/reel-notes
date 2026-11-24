# Progress - Batch 5, item 1: show the real yt-dlp error
Branch: feature/batch5-real-ytdlp-error
Last updated: 2026-11-24

## Done
- Step 1: the problem (review item B11). yt-dlp runs with `ignoreerrors`, `quiet` and `no_warnings`, so for
  every site except X its error was lost. The chat said "❌ Something went wrong: Nothing could be
  downloaded from this post. (Videos longer than 10 minutes are skipped...)", which was often wrong.
- Step 2: processor.py. `download_media` now gives every yt-dlp run the `YtdlpErrors` logger (before: X only).
  On a failure it logs `download: yt-dlp failed: ...` (or `x: ...`) and raises `VideoNotSaved` with
  `download_failed_text(reason)`. The bot already shows `VideoNotSaved` as it is, so bot.py is not changed.
  - Normal link: "❌ I could not download this video." / "Reason: <yt-dlp error>" / "Try /update (a new
    yt-dlp often fixes it), or send me the video file."
  - X link: the old X sentence stays first; the "Reason:" line is added under it.
  - No yt-dlp error (e.g. a crash): the crash text. Nothing downloaded and no error: the old
    "Nothing could be downloaded..." text (then it is the real reason, e.g. a long video).
- Step 3: `clean_ytdlp_error(text)`: removes colour (ANSI) codes and "ERROR:"/"WARNING:", replaces links with
  [link] and file paths with [file], drops any sentence about cookies, passwords, netrc, credentials or
  tokens, joins spaces, cuts to 300 characters with "…". Empty gives "unknown error".
- Step 4: tests. New tests/test_download_errors.py (21 tests). 5 tests in tests/test_x_links.py changed to the
  new reply: they still check the X sentence word for word, the reason, and no token in the log.
  Threads is not changed (a test checks its reply word for word). README updated. Tests: 473 passed.
- Step 5: merged main (with the hook fix, PR #27) into this branch. Only PROGRESS.md had a conflict;
  both parts are kept below. No hook or deny rule changed. Tests: 530 passed.

## Next step
- Owner: merge, pull, restart. Send a private or deleted reel link. The reply should show a "Reason:" line.

## Decisions
- The cookie sentence is removed from the reason. The old "see COOKIES_FILE in .env" hint is not shown for a
  download error any more; it is still in the generic error for other problems.
- The reason is cleaned only for the chat. bot.log keeps the full error, as before.
- graphify has no graph and no `graphify` command in this environment, so its rules could not be followed here.

---

## Already in main: fix "A hook gave no usable answer" (PR #27)
Branch: fix/pretooluse-hook (merged)

### Done
- Step 1: the cause. `.claude/settings.json` ran `graphify hook-guard search --strict` (Bash, Grep) and
  `graphify hook-guard read --strict` (Read, Glob) as bare commands. Where `graphify` is not on PATH the
  shell exits 127 "command not found", which is not a valid hook answer, so Claude Code says "A hook gave
  no usable answer" on every git status. `pre_commit_check.py` itself was fine (exit 0, no output).
- Step 2: new `.claude/hooks/graphify_guard.py`. All 3 graphify hooks (also SessionStart compact) now run
  `python "$CLAUDE_PROJECT_DIR/.claude/hooks/graphify_guard.py" <args>`. It always gives a valid answer:
  graphify missing, crashing or slow = exit 0 and no output; graphify block (exit 2) = still a block;
  graphify JSON = passed on, but an "allow" is removed (it would skip the deny rules); plain text =
  valid JSON `additionalContext`. Plain Python: Windows and Linux.
- Step 3: `pre_commit_check.py` now also blocks any Bash command that force-deletes (`rm -rf` in any flag
  order, PowerShell `Remove-Item -Recurse -Force`, cmd `rd /s`) or names a private file (.env, cookies.txt,
  bot.log, the JSON state files, notes/). `.env.example` is allowed. Allowed commands: exit 0, no output.
  No deny rule in settings.json was changed (a test checks all 66).
- Step 4: 57 new tests in tests/test_hooks.py. Tests: 510 passed. CLAUDE.md updated.

### Next step
- Owner: merge, then restart Claude Code on the PC. Run `git status`: no hook warning.
- If you run `graphify install` again, check that settings.json still uses graphify_guard.py.

### Decisions
- I could not install graphify here, so I could not see what `graphify hook-guard` prints on the PC.
  The wrapper handles every case (missing, error, block, JSON, text), and tests use a fake graphify.
- The new private-file check blocks a command that only mentions a private file too (for example in a
  commit message). That is on purpose: it is the safe side.
