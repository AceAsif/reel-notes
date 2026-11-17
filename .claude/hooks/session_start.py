"""SessionStart hook: install what the tests need in a Claude Code cloud session.

- Runs only in the cloud (CLAUDE_CODE_REMOTE=true). On your own PC it does nothing,
  so it never touches your .venv.
- Installs the packages from requirements.txt and requirements-dev.txt, except the ones
  the tests replace with stubs or that only the Windows tray needs.
- Skips the install when nothing changed since the last good install.
- Plain Python, so it works on Windows and Linux. Free and local: only pip.
"""
import hashlib
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENT_FILES = ["requirements.txt", "requirements-dev.txt"]
# The tests stub pytesseract and faster_whisper. av is only for Whisper. pystray is the tray.
SKIP = {"faster-whisper", "pytesseract", "av", "pystray"}


def package_name(requirement: str) -> str:
    """'python-telegram-bot[job-queue]>=21.0' -> 'python-telegram-bot'."""
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    return m.group(0).lower().replace("_", "-") if m else ""


def packages_to_install(root: Path = ROOT) -> list[str]:
    """Requirement lines (as written) without the skipped packages."""
    wanted = []
    for name in REQUIREMENT_FILES:
        path = root / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-") and package_name(line) not in SKIP:
                wanted.append(line)
    return wanted


def input_hash(root: Path = ROOT) -> str:
    """One hash of this script and every file that decides what gets installed."""
    digest = hashlib.sha256()
    for path in [Path(__file__).resolve(), *(root / n for n in REQUIREMENT_FILES)]:
        digest.update(path.name.encode())
        digest.update(path.read_bytes() if path.is_file() else b"-")
    return digest.hexdigest()


def hash_file() -> Path:
    """Stored in the folder the packages go to: if the packages are gone, so is the hash."""
    return Path(sysconfig.get_path("purelib")) / ".reel-notes-session-start.sha256"


def main() -> int:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0                                   # your own PC: do nothing
    stored, current = hash_file(), input_hash()
    if stored.is_file() and stored.read_text().strip() == current:
        print("Test packages already installed.")
        return 0
    stored.unlink(missing_ok=True)                 # a failed install must run again next time
    packages = packages_to_install()
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         *packages], capture_output=True, text=True, timeout=280)
    if result.returncode != 0:
        print("Could not install the test packages:\n" + result.stderr[-800:], file=sys.stderr)
        return 1
    stored.write_text(current)
    print(f"Installed {len(packages)} test packages. Run: python -m pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
