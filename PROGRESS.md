# Progress - "Already saved" warning with a Save again button
Branch: feature/already-saved-warning
Last updated: 2026-11-25

## Done
- Step 1: found the old check. `processor.find_note_by_source()` already looked in the notes folder and the
  pending folder, and `normalise_url()` already ignored ?tracking bits, #, trailing slash and case.
  The bot already replied "Already saved", but there was no way to save again except deleting the file.
- Step 2: bot.py. For a pasted link, `already_saved()` now shows "Save again" and "Cancel" buttons. The link
  waits in `user_data["save_again_url"]` (too long for callback_data). New `save_again_pressed()` handler
  (`again:` buttons) downloads only on "Save again". Video and screenshot messages keep the old text.
- Step 3: tests in tests/test_bot.py: new link, same link, same link with tracking bits, Save again,
  Cancel. README updated. Tests: 537 passed.

## Next step
- Owner: merge, pull, restart. Send a link twice. The second time should show the Save again button.

## Decisions
- No "saved job history" is checked: the scheduled-jobs file only stores times of scheduled messages, not
  links. The notes and the pending folder are the only record of saved links.
- Save again makes a second note (name gets _2). The old note is not moved. /redo still replaces a note.
