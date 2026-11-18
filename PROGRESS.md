# Progress - One idea, one to-do (habit and action duplicates)
Branch: fix/habit-action-duplicate
Last updated: 2026-11-18

## The problem (seen in a real note)
A motivation reel gave a "Habit to try" AND an action with the same meaning ("Every morning, write
down one limiting belief..." and "Write down one belief that limits you..."). Both are open to-dos
(`open_actions` counts both sections), so /todo showed the same idea twice. /plan did too.

## Done
- Step 1: `similar_idea(a, b)`: two lines are the same idea when they share at least 3 words and at
  least 60% of the words of the shorter one. No AI. Words about WHEN ("every", "morning", weekdays,
  "one") and common filler words are ignored. Light stemming ("limiting", "limits" -> "limit").
- Step 2: new notes: `merge_habit_and_actions` (called in `summarise`). If the habit repeats an action,
  the action is dropped and the habit keeps ONE to-do with the action's priority and the 🧠 type,
  e.g. `- [ ] 🔥 🧠 Every morning, ...`. A repeated "other idea" is dropped too. A different action
  stays. The Telegram reply shows the habit once.
- Step 3: old notes: `/cleanup` counts and skips the pair ("dups"). It keeps the action and skips the
  habit, unless only the habit has a due date. A habit that repeats an action that /cleanup skips as an
  extra is not skipped (the idea stays once). Uses the normal confirm button and `/undocleanup`.
- Step 4: `/plan` lists a repeated line once.
- Step 5: 25 new tests, README. Tests: 371 passed.

## Next step
- Owner: pull, restart. Send /cleanup once. The text shows a new line "N are the same idea twice".
- Check one old motivation note after the clean-up: one of the two lines is marked ❌, the other is open.

## Decisions
- Deterministic rule (no AI call): fast, free and testable. Thresholds are in `similar_idea`.
- New notes keep the HABIT (it has the detail "every morning"); old notes keep the ACTION (it has the
  priority, type and maybe a due date, and the note is not rewritten).
- The prompt is not changed: the model's output is checked after the fact, which is more reliable.
- Not done: merging two different actions that look alike in different notes.
