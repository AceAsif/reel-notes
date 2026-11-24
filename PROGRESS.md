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

## Next step
- Owner: merge, pull, restart. Send a private or deleted reel link. The reply should show a "Reason:" line.

## Decisions
- The cookie sentence is removed from the reason. The old "see COOKIES_FILE in .env" hint is not shown for a
  download error any more; it is still in the generic error for other problems.
- The reason is cleaned only for the chat. bot.log keeps the full error, as before.
- graphify has no graph and no `graphify` command in this environment, so its rules could not be followed here.
