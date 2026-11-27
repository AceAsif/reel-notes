# Progress - link index: find duplicates by video ID
Branch: feature/link-index
Last updated: 2026-11-28

## Done
- Step 1: processor.py. `normalise_url()` now gives a video ID key: `instagram:ID` (/reel/, /reels/,
  /p/, /tv/, also after a user name), `tiktok:ID`, `youtube:ID` (watch, shorts, youtu.be), `facebook:ID`
  (reel, watch?v=, videos, fb.watch), `x:ID`, and the Threads key. Else the clean URL. IDs keep their
  case (Instagram IDs are case-sensitive).
- Step 2: link index (private file in the bot folder, `LINK_INDEX_FILE` in .env can move it):
  {version, files, links: {video key: [{file, saved, folder}]}}. It lists the note files it was built
  from. If the file is missing, broken, an old version, or the note files on disk differ (added, moved,
  deleted, folder away), it is rebuilt from the notes' Source lines. Real notes: 165 files, 163 videos,
  rebuild 0.6 s, normal check under 10 ms.
- Step 3: `write_note_file` adds each new note to the index (no rebuild). `sync_pending` rebuilds after
  moving notes. `/redo` moves and deletions are caught by the file-list check.
- Step 4: `find_note_by_source` uses the index (newest existing note). All download paths already call it
  first (link, video caption, screenshots). Only Save again and /redo download on purpose.
- Step 5: /dupes lists videos with more than one note (file, date, pending). Deletes nothing.
- Step 6: Show old note sends title, Summary, Key points, Resources and Action items, with a Full note
  button for the whole note (transcript and on-screen text, split if long).
- Step 7: the index file is private: .gitignore, pre_commit_check.py, .claude/settings.json deny rules,
  CLAUDE.md. Tests never write it (conftest moves it to a temp folder).
- Step 8: tests/test_link_index.py (IDs per platform, /reel/ vs /reels/, tracking bits, missing and old
  index, deleted note, hand-added note, pending move, /dupes, no download). Show old note tests updated.
  README, /start and botfather-commands.txt updated. Tests: 621 passed.

## Next step
- Owner: merge, pull, restart. Send /dupes (1 video on the real notes). Send a /reels/ link of a saved reel.

## Decisions
- /cleanup never deletes note files (it only skips actions), so it needs no index update.
- Short links (vm.tiktok.com, facebook share links) can't be opened offline, so they only match the same
  short link.
- The old test that matched /reel/ABC with /reel/abc was changed: those are two different posts.
