# Progress - Small improvements + /plan
Branch: feature/small-improvements
Last updated: 2026-11-14 14:55 (Hobart)

## Plan
1. Chat fixes: follow-ups reuse the previous notes; no invented steps; mention unverified claims
2. /todo in pages (10 per page, Prev/Next buttons) + /todo high|normal|low filter
3. /plan N: turn a note into a ready-to-paste Claude prompt (ART format)
4. Resurface an old note once a week
5. Monthly learning summary (1st of each month) + /month
6. README, help text, BotFather list

## Done
- Step 1: is_follow_up() so "which one first?" reuses the previous question's notes; chat prompt forbids invented steps/settings and flags "Claims to check" (8 new tests)

- Step 2: /todo in pages of 10 with Prev/Next buttons, counts per priority, real /todo numbers kept; /todo high|normal|low and /todo 2 (4 new tests)

- Step 3: /plan N [my goal] - turns a note into a ready-to-paste Claude prompt in ART format (Act as / Request / Terms: Instructions, Constraints, Output), built only from the note (open actions, key points, links, claims to verify); creator-promo actions left out; very long plans sent as a .txt file (3 new tests)

- Step 4: Weekly resurface (Wednesday 7 pm, RESURFACE=off to disable) + /remember: one note older than 7 days, rotating weekly; shows its key quote, a key point or lesson; '🔁 Another one' button; /note 1 opens it (4 new tests)

- Step 5: Monthly learning summary on the 1st at 9:30 am (previous month) + /month and /month last: topics learned (top tags), reels saved by category, actions done/skipped with the finished ones listed; weekly_stats refactored into stats_between (3 new tests)

## In progress
- (none)

## Next step
- Step 6: README, .env.example (RESURFACE), BotFather list

## Decisions
- /plan uses a fixed template, not the AI, so the plan only contains what's really in the note; Claude does the thinking when the user pastes it.
- /plan added to this batch: the user asked about it and it's small.
- Follow-up = short message (<= 4 meaningful words) with a pointing word (it, that, which, first, more...).

## Problems / questions for the user
- (none yet)
