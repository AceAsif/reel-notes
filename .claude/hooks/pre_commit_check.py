"""PreToolUse hook for Bash: blocks dangerous commands, and checks before `git commit`.

Any command is blocked (exit code 2, reason on stderr) when it:
  a. deletes by force and recursively: `rm -rf`, `rm -r -f`, `Remove-Item -Recurse -Force`, `rd /s`,
  b. names a private file: .env, .env.local, cookies.txt, bot.log, the *.json state files, notes/.
     (A second guard next to the deny rules in settings.json: those only match some commands.)
An allowed command gets exit code 0 and no output, so the normal permission rules still apply.

It blocks the commit (exit code 2) when:
  1. the commit command has a `Co-Authored-By` or `Claude-Session` line (project rule),
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
                 "sent_jobs.json", "bot_state.json", "cleanup_undo.json", "link_index.json",
                 "search_index.json"}
SECRET_RES = {
    "a Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "a GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
}
MAX_FILE_BYTES = 1_000_000

# a private file named anywhere in a command (".env.example" is fine: it has no secrets)
PRIVATE_IN_COMMAND_RE = re.compile(
    r"(?<![\w.-])(?:\.env(?:\.local)?|cookies\.txt|bot\.log|reminders\.json|sent_jobs\.json"
    r"|bot_state\.json|cleanup_undo\.json|link_index\.json|search_index\.json)(?![\w.-])|(?<![\w.-])notes[/\\]", re.I)
SEGMENT_SPLIT_RE = re.compile(r"[;&|\n]+|\$\(|`")
PREFIX_WORDS = {"sudo", "command", "builtin", "exec", "nohup", "time", "xargs", "env"}


def is_force_delete(command: str) -> bool:
    """True for rm -rf (any flag order), PowerShell Remove-Item -Recurse -Force, cmd rd /s."""
    for segment in SEGMENT_SPLIT_RE.split(command):
        words = [w.strip("'\"(){}") for w in segment.split()]
        while words and (words[0] in PREFIX_WORDS or "=" in words[0]):
            words = words[1:]
        if not words:
            continue
        name = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        rest = [w.lower() for w in words[1:]]
        short = "".join(w[1:] for w in words[1:] if w.startswith("-") and not w.startswith("--"))
        if name == "rm":
            recursive = "r" in short.lower() or "--recursive" in rest
            force = "f" in short or "--force" in rest
            if recursive and force:
                return True
        if name in ("remove-item", "ri", "rm", "del", "rmdir", "rd", "erase"):
            if any(w.startswith("-r") and "recurse".startswith(w[1:]) for w in rest) and \
                    any(w.startswith("-fo") and "force".startswith(w[1:]) for w in rest):
                return True                             # PowerShell, any short form
        if name in ("rd", "rmdir") and "/s" in rest:
            return True                                 # cmd.exe
    return False


def danger_in(command: str) -> list[str]:
    """Reasons to block any Bash command, commit or not. [] = let it run."""
    problems = []
    if is_force_delete(command):
        problems.append("force delete (rm -rf or the same) is not allowed. Delete one file you have "
                        "looked at, or ask the owner.")
    found = PRIVATE_IN_COMMAND_RE.search(command)
    if found:
        problems.append(f"the command names a private file ({found.group(0)}). Project rule: never "
                        "read, print or commit private files.")
    return problems


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
                        "Project rule: plain commit messages only.")
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
    danger = danger_in(command)
    if danger:
        print("Command blocked:\n- " + "\n- ".join(danger), file=sys.stderr)
        return 2                                        # exit code 2 = block, text goes to Claude
    problems = problems_for(command)
    if problems:
        print("Commit blocked:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    return 0                                            # allowed: no output, normal rules apply


if __name__ == "__main__":
    sys.exit(main())
