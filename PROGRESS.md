# Progress - Threads link support
Branch: feature/threads-links
Last updated: 2026-11-17

## Done
- Step 1: `LINK_PATTERN` in bot.py accepts `threads.com` and `threads.net` (not `notthreads.com`).
  The `/start` text mentions Threads.
- Step 2: new `threads_link.py`. yt-dlp has no Threads support, so the bot reads the public page
  with ONE request (no login, no cookies, `threads.net` is rewritten to `threads.com` first, so there
  is no redirect). It looks for the video address in the page data (`video_versions`), then in the
  `og:video` tag, then in a `<video>` tag. Then it downloads the video file (Meta servers only,
  https only, max 200 MB) and the normal pipeline makes the note.
  The post text becomes the caption. The creator comes from the page title.
- Step 3: messages (short, simple English). No video found: "I could not get this Threads video.
  Please save the video and send me the file." Text-only and picture-only posts and profile links
  get their own message. The real reason goes to bot.log (`threads:` lines).
- Step 4: `processor.download_media` sends Threads links to `threads_link`. `normalise_url` treats
  threads.com and threads.net links to one post as the same post (duplicate check).
  `note_from_link` shows the Threads message as it is (no "Something went wrong" and no cookies hint).
- Step 5: 39 new tests (network always mocked), README, CLAUDE.md code map.
- Tests: 301 passed.

## Next step
- Test with one real Threads video link (see the pull request text). I could not see a live Threads
  page from here, so the page reader is written from known page formats and tested on mocked pages.
- If it fails, send the `threads:` lines from bot.log. They say what the page contained.

## Decisions
- Separate small file `threads_link.py`, so processor.py does not grow.
- Only the first video of a post is taken. A Threads page also holds replies, and the first video
  in the page is the main post.
- The text-only / picture-only message is only used when the page clearly shows it. When the bot is not
  sure (for example a video it cannot read), it uses the "could not get this video" message.
- A video address must be https and on a Meta server (cdninstagram.com, fbcdn.net, instagram.com,
  facebook.com, fbsbx.com, threads.com, threads.net). Other hosts are refused and logged.
- Not done on purpose (other items): carousels with several videos, picture posts, text posts as notes.
