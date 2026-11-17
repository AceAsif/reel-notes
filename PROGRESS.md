# Progress - Threads: share links, /media links, better log
Branch: fix/threads-share-and-media-links
Last updated: 2026-11-18

## What went wrong (from a real bot.log)
- Link 1 was `threads.com/share/...` (the app's Share button). The bot only knew `/post/` links, so it
  said "This is a profile link" and made NO request. Bug in my code.
- Link 2 was `.../post/CODE/media?xmt=...`. The bot asked for the `/media` page. Threads answered
  HTTP 200, but the page had no video address, no text and no meta tags. The reason is not known for
  sure: the `/media` page may be an empty picture viewer, or Threads may give non-browser clients an
  empty or login page.

## Done
- Step 1: share links (`/share/CODE`, `/t/CODE`) are accepted. The bot asks for the link as it is (still
  ONE request) and Threads sends it to the post. The creator name can come from the address it ended at.
- Step 2: a link that ends in `/media` now asks for the post page (`/@user/post/CODE`). Same post key
  for the duplicate check.
- Step 3: when the page has no video, bot.log now says what the page looked like: HTTP status, where it
  ended, size, title, meta names, counts of `video_versions` and `.mp4`, login words. It does not copy
  the post text.
- Step 4: 11 new tests (made-up names, network mocked). Tests: 312 passed.

## Next step
- Owner: pull, restart, send the same two links again.
- If it fails again, send the new `threads:` line. It will show if the page is a login page, an empty
  page, or a new format.
- If Threads gives an empty page to non-browser clients, this feature cannot work without a login or
  extra requests. Both are against the rules for this project. Then the file fallback is the way.

## Decisions
- No new requests and no login. The same rules as before.
- The sandbox where this was written cannot reach threads.com (proxy 403), so nothing here is checked
  against a live page.
