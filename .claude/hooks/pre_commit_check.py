"""PreToolUse hook: checks before Claude Code runs `git commit`.

It blocks the commit (exit code 2) when:
  1. the commit command has a `Co-Authored-By` or `Claude-Session` line (owner's rule),
  2. a private file is staged, at any depth (.env, notes/, cookies.txt, bot.log, *.json state files),
  3. new or changed text looks like a Telegram bot token or a GitHub token,
  4. `python -m pytest -q` fails.
Other commands pass straight through. No auto-commit, no auto-push, no auto-format.
Plain Python, so it works on Windows and Linux. Free and local.

Set REEL_HOOK_SKIP_TESTS=1 to skip step 4 (used by the hook's own tests).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

COMMIT_RE = re.compile(r"\bgit\s+(?:-[Cc]\s+\S+\s+)*commit\b")
TRAILER_RE = re.compile(r"co-authored-by|claude-session", re.I)
FORCE_ADD_RE = re.compile(r"\bgit\s+add\b[^;&|\n]*(?:\s-f\b|\s--force\b)")
PRIVATE_NAMES = {".env", ".env.local", "cookies.txt", "bot.log", "reminders.json",
                 "sent_jobs.json", "bot_state.json", "cleanup_undo.json"}
SECRET_RES = {
    "a Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
}
MAX_FILE_BYTES = 1_000_000


def is_private(path: str) -> bool:
    path = path.replace("\\", "/")
    while path.startswith("./"):          # not lstrip("./"): that would also eat the dot of ".env"
        path = path[2:]
    *folders, name = path.split("/")
    # at ANY depth: backup/.env, old/reminders.json and x/notes/a.md are private too
    return (name in PRIVATE_NAMES or "notes" in folders
            or name.endswith((".log", ".redo")))


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    return result.stdout if result.returncode == 0 else ""


def secrets_in(text: str) -> list[str]:
    return [label for label, rx in SECRET_RES.items() if rx.search(text)]


def changed_text(root: Path) -> dict[str, str]:
    """{file: added text} for tracked changes (staged or not) and new, not-ignored files.
    Ignored files (.env, notes/...) are never read."""
    added: dict[str, list[str]] = {}
    diff = git(root, "diff", "HEAD", "-U0") or git(root, "diff", "--cached", "-U0")
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and current:
            added.setdefault(current, []).append(line[1:])
    result = {name: "\n".join(lines) for name, lines in added.items()}
    for name in git(root, "ls-files", "-z", "-o", "--exclude-standard").split("\0"):
        path = root / name
        if name and path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            try:
                result[name] = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                pass                                    # binary file: skip
    return result


def project_python(root: Path) -> str:
    for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def test_problem(root: Path) -> str:
    """'' if the tests pass, else a short reason."""
    result = subprocess.run([project_python(root), "-m", "pytest", "-q"], cwd=root,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=170)
    output = (result.stdout + result.stderr).strip()
    if result.returncode in (0, 5):                     # 5 = no tests found
        return ""
    if "No module named pytest" in output:
        return "pytest is not installed. Run: pip install -r requirements-dev.txt"
    return "the tests failed:\n    " + "\n    ".join(output.splitlines()[-15:])


def problems_for(command: str, root: Path = ROOT, run_tests: bool = True) -> list[str]:
    """Reasons to block this command. [] = let it run."""
    if not COMMIT_RE.search(command):
        return []
    problems = []
    if TRAILER_RE.search(command):
        problems.append("the commit message has a Co-Authored-By or Claude-Session line. "
                        "Owner's rule: plain commit messages only.")
    if FORCE_ADD_RE.search(command):
        problems.append("`git add -f` can add files that .gitignore hides. Do not force-add.")
    staged = [n for n in git(root, "diff", "--cached", "--name-only", "-z").split("\0") if n]
    problems += [f"private file is staged: {n}" for n in staged if is_private(n)]
    for name, text in changed_text(root).items():
        problems += [f"{name} looks like it has {label}" for label in secrets_in(text)]
    if run_tests and not problems and not os.environ.get("REEL_HOOK_SKIP_TESTS"):
        reason = test_problem(root)
        if reason:
            problems.append(reason)
    return problems


def main() -> int:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        command = str((data.get("tool_input") or {}).get("command", ""))
    except (ValueError, AttributeError):
        return 0                                        # not our kind of input: do not block
    problems = problems_for(command)
    if problems:
        print("Commit blocked:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2                                        # exit code 2 = block, text goes to Claude
    return 0


if __name__ == "__main__":
    sys.exit(main())
