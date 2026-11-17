"""Tests for the Claude Code hooks in .claude/hooks (no network, no real notes)."""
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / ".claude" / "hooks"


def load(name):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pre = load("pre_commit_check")
start = load("session_start")
COMMIT = 'git commit -m "Add a thing"'
# built at run time, so this file itself never contains something that looks like a token
FAKE_TELEGRAM_TOKEN = "123456789" + ":" + "A" * 35


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.email", "t@example.com")
    run_git(tmp_path, "config", "user.name", "T")
    (tmp_path / ".gitignore").write_text(".env\nnotes/\n")
    (tmp_path / "a.py").write_text("print('hi')\n")
    run_git(tmp_path, "add", ".")
    run_git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def problems(command, repo):
    return pre.problems_for(command, repo, run_tests=False)


def test_other_commands_pass_through(repo):
    assert problems("git status", repo) == []
    assert problems("python -m pytest -q", repo) == []
    assert problems("git log --oneline", repo) == []


def test_clean_commit_is_allowed(repo):
    (repo / "a.py").write_text("print('changed')\n")
    assert problems(COMMIT, repo) == []
    assert problems("git add -A && git -C . commit -m x", repo) == []


@pytest.mark.parametrize("line", ["Co-Authored-By: Someone <a@b.c>", "Claude-Session: https://x/y"])
def test_trailer_lines_are_blocked(repo, line):
    found = problems(f'git commit -m "Add a thing\n\n{line}"', repo)
    assert len(found) == 1 and "plain commit" in found[0]


def test_private_files_staged_are_blocked(repo):
    (repo / ".env").write_text("X=1\n")
    (repo / "notes").mkdir()
    (repo / "notes" / "n.md").write_text("# n\n")
    (repo / "bot.log").write_text("log\n")
    run_git(repo, "add", "-f", ".env", "notes/n.md", "bot.log")
    found = problems(COMMIT, repo)
    assert any(".env" in f for f in found) and any("notes/n.md" in f for f in found)
    assert any("bot.log" in f for f in found)


def test_force_add_in_the_command_is_blocked(repo):
    assert problems("git add -f .env && " + COMMIT, repo)
    assert problems("git add --force notes && " + COMMIT, repo)
    assert problems("git add a.py && " + COMMIT, repo) == []


def test_ignored_files_are_never_read(repo):
    (repo / ".env").write_text("TOKEN=" + FAKE_TELEGRAM_TOKEN + "\n")    # ignored by git
    assert problems(COMMIT, repo) == []


def test_token_in_a_new_or_changed_file_is_blocked(repo):
    (repo / "new.py").write_text(f'T = "{FAKE_TELEGRAM_TOKEN}"\n')
    assert any("Telegram bot token" in f for f in problems(COMMIT, repo))
    (repo / "new.py").unlink()
    (repo / "a.py").write_text("t = 'ghp_" + "a" * 36 + "'\n")
    assert any("GitHub token" in f for f in problems(COMMIT, repo))


def test_short_test_tokens_are_fine(repo):
    (repo / "a.py").write_text('os.environ["TELEGRAM_BOT_TOKEN"] = "123:ABC"\n')
    assert problems(COMMIT, repo) == []


def test_is_private():
    for name in [".env", "notes/a.md", "bot.log", "x/y.log", "n.redo", "cookies.txt",
                 "reminders.json", "sent_jobs.json", "bot_state.json", "cleanup_undo.json"]:
        assert pre.is_private(name), name
    for name in [".env.example", "bot.py", "docs/notes.md", "tests/test_bot.py"]:
        assert not pre.is_private(name), name


def test_is_private_at_any_depth():
    for name in ["backup/.env", "docs/cookies.txt", "old/reminders.json", "a/b/sent_jobs.json",
                 "x/bot_state.json", "x/notes/a.md", "G/My Drive/notes/n.md", "./backup/.env",
                 "backup\\.env", "old\\notes\\a.md", "deep/er/cleanup_undo.json"]:
        assert pre.is_private(name), name
    for name in ["docs/.env.example", "docs/notes.md", "tests/test_notes.py", "notes_helper.py",
                 "src/my_notes/a.md", "docs/reminders.md", "tests/test_hooks.py"]:
        assert not pre.is_private(name), name


def test_nested_private_files_staged_are_blocked(repo):
    (repo / "backup").mkdir()
    (repo / "backup" / ".env").write_text("X=1\n")
    (repo / "old" / "notes").mkdir(parents=True)
    (repo / "old" / "notes" / "n.md").write_text("# n\n")
    run_git(repo, "add", "-f", "backup/.env", "old/notes/n.md")
    found = problems(COMMIT, repo)
    assert any("backup/.env" in f for f in found) and any("old/notes/n.md" in f for f in found)


def run_with_fake_pytest(monkeypatch, repo, code, out=""):
    monkeypatch.setattr(pre.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=code, stdout=out, stderr=""))
    return pre.test_problem(repo)


def test_failing_tests_block_and_passing_tests_allow(monkeypatch, repo):
    assert run_with_fake_pytest(monkeypatch, repo, 0) == ""
    assert run_with_fake_pytest(monkeypatch, repo, 5) == ""                 # no tests found
    assert "tests failed" in run_with_fake_pytest(monkeypatch, repo, 1, "1 failed")
    assert "pip install" in run_with_fake_pytest(monkeypatch, repo, 1, "No module named pytest")


def test_hook_script_exit_codes(repo):
    script = HOOKS / "pre_commit_check.py"
    def call(payload):
        return subprocess.run([sys.executable, str(script)], input=payload, text=True,
                              capture_output=True, env={**__import__("os").environ,
                                                        "REEL_HOOK_SKIP_TESTS": "1"})
    ok = call(json.dumps({"tool_input": {"command": "ls -la"}}))
    assert ok.returncode == 0
    assert call("not json").returncode == 0                  # never block on odd input
    blocked = call(json.dumps({"tool_input": {"command": 'git commit -m "x\n\nCo-Authored-By: A"'}}))
    assert blocked.returncode == 2 and "Commit blocked" in blocked.stderr


# ---- session_start.py -----------------------------------------------------------

def test_package_name():
    assert start.package_name("python-telegram-bot[job-queue]>=21.0") == "python-telegram-bot"
    assert start.package_name("PyYAML==6") == "pyyaml" and start.package_name("# x") == ""


def test_packages_skip_stubbed_and_windows_only(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "python-telegram-bot[job-queue]>=21.0\nfaster-whisper>=1.0\npytesseract>=0.3.10\n"
        "requests>=2.31  # web\nav>=12,<14\nyt-dlp\npystray\n")
    (tmp_path / "requirements-dev.txt").write_text("pytest>=8\n")
    assert start.packages_to_install(tmp_path) == [
        "python-telegram-bot[job-queue]>=21.0", "requests>=2.31", "yt-dlp", "pytest>=8"]


def test_input_hash_changes_with_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests\n")
    first = start.input_hash(tmp_path)
    (tmp_path / "requirements.txt").write_text("requests\nyt-dlp\n")
    assert start.input_hash(tmp_path) != first


def test_does_nothing_outside_the_cloud(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    monkeypatch.setattr(start.subprocess, "run", lambda *a, **k: pytest.fail("must not install"))
    assert start.main() == 0
