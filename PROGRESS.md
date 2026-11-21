# Progress - Feature to-do list update
Branch: docs/feature-todo-update
Last updated: 2026-11-21

## Done
- "Done, with one line of what I learned" is merged (#23) and tested by the owner in Telegram: the
  question appears after a Done, the reply is saved in the note, `/month` shows it.
- docs/HANDOVER.md section 10 is now a status list: Done / To do (ranked) / Small fixes and checks /
  Later / Not now. Section 6 and section 9 had old facts and are fixed (X and Threads capture, notes
  folder fallback, habit merge, real timings, file sizes, test count 262 -> 432).
- docs/FEATURE_IDEAS_BY_FABLE.md has a status line that points to the handover list.
- No code was changed. Tests: 432 passed.

## Next step
- Owner: choose the next feature. My order: 1) Pick 3 for this week, 2) Keep or drop after 3 nudges,
  3) /review old notes. Reason: about half of the open actions are 🔥, so priority tells very little.

## Decisions
- One live to-do list: HANDOVER section 10. FEATURE_IDEAS_BY_FABLE.md is history.
- graphify (added by the owner) has no graph and no `graphify` command in this environment, so normal
  search was used.
