# Progress - X (x.com and twitter.com) video links
Branch: feature/x-links
Last updated: 2026-11-18

## Done
- Step 1: `LINK_PATTERN` in bot.py accepts `x.com` and `twitter.com` (also `www.`, `mobile.`, `m.`).
  It does not accept look-alikes such as `linux.com`, `fixupx.com` or `vxtwitter.com`.
  The `/start` text mentions X.
- Step 2: `processor.download_media` sends X links through yt-dlp like the other sites (yt-dlp has an
  X extractor). For X links the cookies file is NEVER used, and no login option is set.
- Step 3: if yt-dlp fails for any reason (no video in the post, needs a login, too long, network), the
  bot replies "I could not get this X video. Please save the video and send me the file." The real
  yt-dlp error goes to bot.log on a line that starts with `x: yt-dlp failed:` (the address is logged
  without the ?s=... tracking part). Other sites keep their old error messages.
- Step 4: `normalise_url`: x.com, twitter.com and mobile links to one post are the same post
  (duplicate check).
- Step 5: 34 new tests with a fake yt-dlp (no network). README. Tests: 346 passed.

## Next step
- Test with one public X video link (see the pull request text).
- If it fails, send the `x: yt-dlp failed:` line from bot.log. Often `/update` (new yt-dlp) fixes it.

## Decisions
- The message says "X video", not "Threads video". Same sentence, right name.
- Any failure for an X link gives that message. A text-only or picture-only post gets it too (yt-dlp
  cannot tell us more, and the real reason is in bot.log).
- No browser, no login, no cookies, no extra requests: only yt-dlp.
- Not done on purpose: look-alike domains (fixupx, vxtwitter), t.co short links, X profile links.
