# Progress - Claude Code automations (CLAUDE.md, deny rules, hooks)
Branch: chore/claude-code-automations
Last updated: 2026-11-17

## Done
- Step 1: `CLAUDE.md` with the working rules from docs/HANDOVER.md section 12, in simple English.
- Step 2: `.claude/settings.json` deny rules for .env, notes/, cookies.txt, bot.log, reminders.json,
  sent_jobs.json, bot_state.json, cleanup_undo.json. Read and Edit rules (18), plus shell rules (48):
  `cat`, `type`, `head`, `tail`, `grep`, `rg` on those names. Checked in a live session: `cat .env`,
  `head ./notes/x.md` and `grep ... bot.log` are refused, `cat README.md` still works.
  `.claude/settings.local.json` is in .gitignore.
- Step 3: SessionStart hook `.claude/hooks/session_start.py`. Cloud only (CLAUDE_CODE_REMOTE=true).
  Installs the test packages (not whisper, tesseract, av or pystray: the tests stub them).
  Skips the install when nothing changed.
- Step 4: PreToolUse hook `.claude/hooks/pre_commit_check.py` on commit commands. Blocks: trailer lines
  in the message, private files staged (at any depth, e.g. `backup/.env`, `old/notes/a.md`),
  force-adding files, Telegram or GitHub tokens in changed files, failing tests.
- Step 5: 18 tests in `tests/test_hooks.py` (2 are new for nested private files).
- Step 6: test count in docs/HANDOVER.md fixed (it said 198).
- Step 7: personal details removed from the repo (names, paths, location, language, hardware).
  The commands file is now `botfather-commands.txt`. The default time zone is now `UTC`.
- Tests: 262 passed.

## Next step
- Review and merge the pull request. After merging, new cloud sessions use the hooks.
- Not tested on Windows. Check once on the PC that `python` finds Python when Claude Code runs a hook.

## Decisions
- Hooks are small Python scripts (no bash), so they work on Windows and in the cloud.
- The deny rules stop Claude's file tools and the six shell readers above. They do not stop every
  way to read a file (for example a one-line Python command that opens `.env`).
- The shell rules also block `cat .env.example` (the pattern is `*.env*`). Use the Read tool for that file.
- The hook looks at the whole command text. A command that only mentions the trailer words or a
  force-add is blocked too. Use the file tools to write such text into a file.
- The real notes folder is outside the repo, so these rules do not cover it.
- No auto-commit, no auto-push, no auto-format.
