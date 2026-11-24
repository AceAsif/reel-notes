# Progress - fix "A hook gave no usable answer"
Branch: fix/pretooluse-hook
Last updated: 2026-11-24

## Done
- Step 1: the cause. `.claude/settings.json` ran `graphify hook-guard search --strict` (Bash, Grep) and
  `graphify hook-guard read --strict` (Read, Glob) as bare commands. Where `graphify` is not on PATH the
  shell exits 127 "command not found", which is not a valid hook answer, so Claude Code says "A hook gave
  no usable answer" on every git status. `pre_commit_check.py` itself was fine (exit 0, no output).
- Step 2: new `.claude/hooks/graphify_guard.py`. All 3 graphify hooks (also SessionStart compact) now run
  `python "$CLAUDE_PROJECT_DIR/.claude/hooks/graphify_guard.py" <args>`. It always gives a valid answer:
  graphify missing, crashing or slow = exit 0 and no output; graphify block (exit 2) = still a block;
  graphify JSON = passed on, but an "allow" is removed (it would skip the deny rules); plain text =
  valid JSON `additionalContext`. Plain Python: Windows and Linux.
- Step 3: `pre_commit_check.py` now also blocks any Bash command that force-deletes (`rm -rf` in any flag
  order, PowerShell `Remove-Item -Recurse -Force`, cmd `rd /s`) or names a private file (.env, cookies.txt,
  bot.log, the JSON state files, notes/). `.env.example` is allowed. Allowed commands: exit 0, no output.
  No deny rule in settings.json was changed (a test checks all 66).
- Step 4: 57 new tests in tests/test_hooks.py. Tests: 510 passed. CLAUDE.md updated.

## Next step
- Owner: merge, then restart Claude Code on the PC. Run `git status`: no hook warning.
- If you run `graphify install` again, check that settings.json still uses graphify_guard.py.

## Decisions
- I could not install graphify here, so I could not see what `graphify hook-guard` prints on the PC.
  The wrapper handles every case (missing, error, block, JSON, text), and tests use a fake graphify.
- The new private-file check blocks a command that only mentions a private file too (for example in a
  commit message). That is on purpose: it is the safe side.
