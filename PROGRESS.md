# Progress - /redo fast (make a note again from its saved text)
Branch: feature/fast-redo (built on docs/feature-todo-update, which is not merged yet)
Last updated: 2026-11-21

## Done
- Step 1: `saved_inputs(path)` reads back what a note was made from: `## Transcript`, `## On-screen text`
  (inside its code fence, so a "## " line in the OCR text is safe; older notes without a fence work too),
  `## Post caption` (the last section, so a "## " line in the caption is safe), and the header: Source,
  Creator, Language, Slides, Date, tags. "(no speech)" and "(none)" mean empty. None = nothing to work from.
- Step 2: `redo_from_saved(path)`: runs only `summarise` (the AI). No download, no Whisper, no OCR. Keeps
  the note's date (file name and "- Date:") and your tags. The old note moves to old/. If the AI fails the
  old note is not touched; if saving fails it is put back. `save_note(..., keep_existing=True)` never
  overwrites another note with the same name (it adds _2).
- Step 3: `carry_over`: done and skipped lines (with their "Learned" line) go into the new note. A new open
  action that is the same idea as one of them (`similar_idea`) is replaced by the old line, so it is not
  opened again. The rest go to the end of "## Action items". Habits too.
- Step 4: Telegram: `/redo fast`, `/redo fast 2`, `/redo fast <title words>`; a confirm button
  (`redo:fast`); the reply shows the new note with "⏱ ... (AI ...)". Plain `/redo` on a screenshot note now
  suggests `/redo fast`. /start text, BotFather list, README, HANDOVER (section 6 and the to-do list).
- Step 5: 19 new tests (the download, Whisper and OCR functions fail if called). Tests: 451 passed.

## Next step
- Owner: merge docs/feature-todo-update first (this branch is built on it), then this one.
- Try `/redo fast` on one old note. Check: same date, your tags, done actions still done.

## Decisions
- Open actions are made new by the AI; their due dates and reminders are not carried over (said in the
  confirm message). Done and skipped history is always kept, so /cleanup work is not undone.
- One note at a time. A "/redo fast all" for every old note is possible later (about 15-25 s per note).
- Found, not fixed here: a normal new note overwrites another note with the same file name (same minute,
  same title). /redo fast avoids it with `keep_existing`.
