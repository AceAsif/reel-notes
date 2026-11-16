# Progress - Batch 3 (action types, one action per reel, clean-up)
Branch: feature/batch3-action-types
Last updated: 2026-11-16

## Done
- Step 1: Action types 🤖 (AI can do it), 🧠 (habit), 🔗 (look up / set up). The AI picks one;
  a keyword guess is used when it does not and for older notes. Saved in the note line after
  the priority icon, e.g. `- [ ] 🔥 🤖 Ask Claude ...`. /todo shows the icon, counts, and
  filters: /todo ai, /todo habit, /todo lookup.
- Step 2: "Comment X / DM me / link in bio" are no longer actions. They go to "From the creator".
  Each reel keeps ONE main action (best priority first). Extra actions become "## Other ideas"
  (plain bullets, not on /todo).
- Step 3: Removed the A/B/C pick buttons (and pick_action, skip_note_actions, note_key).

- Step 4: /cleanup (skip junk "comment X" actions + extra actions, keep the best per note, due-dated
  ones and habits; confirm button). Sunday review hints at it above 30 open actions.
- Step 5: README, HANDOVER, BotFather command list.

## In progress
- nothing

## Next step
- Merge the PR, git pull, restart the bot, send /cleanup once, then use the bot for a week.

## Decisions
- Old actions without an icon get a guessed type for display only; their note lines are not
  rewritten until you change their priority or due date.
- Action ids ignore the type icon, so reminders keep working.
