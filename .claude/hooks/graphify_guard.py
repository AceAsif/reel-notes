"""Hook wrapper: runs `graphify hook-guard <args>` only when graphify is installed.

Why: settings.json called `graphify hook-guard ...` directly. Where graphify is not on PATH
(a fresh PC, a cloud session, a venv that is not active) the shell exits with 127
"command not found". Claude Code then says "A hook gave no usable answer, so it didn't
check this action" on every Bash, Grep, Read and Glob call.

This wrapper always gives Claude Code a valid answer:
- graphify missing, crashed or too slow: exit 0, no output (graphify's hint is only advice).
- graphify blocks (exit 2): exit 2 with its reason, so a block still works.
- graphify prints JSON: passed on. An "allow" decision is removed, because "allow" would
  skip the permission rules in settings.json; this hook may only add advice or block.
- graphify prints plain text: passed on as `additionalContext` in valid JSON.
Plain Python, so it works on Windows and Linux.
"""
import json
import shutil
import subprocess
import sys

TIMEOUT = 8          # the hook timeout in settings.json is 10 seconds


def event_name(raw: bytes) -> str:
    try:
        return str(json.loads(raw.decode("utf-8", "replace")).get("hook_event_name") or "PreToolUse")
    except (ValueError, AttributeError):
        return "PreToolUse"


def safe_json(text: str, event: str) -> str:
    """The text graphify printed, as valid hook JSON that can never say "allow"."""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})
    specific = data.get("hookSpecificOutput")
    if isinstance(specific, dict) and str(specific.get("permissionDecision", "")).lower() == "allow":
        specific.pop("permissionDecision")
        specific.pop("permissionDecisionReason", None)
    if str(data.get("decision", "")).lower() in ("approve", "allow"):
        data.pop("decision")
    return json.dumps(data)


def main(args: list[str]) -> int:
    raw = sys.stdin.buffer.read()
    exe = shutil.which("graphify")
    if not exe:
        return 0                                    # not installed here: nothing to check
    try:
        result = subprocess.run([exe, "hook-guard", *args], input=raw, capture_output=True,
                                timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode == 2:                      # graphify wants to block: keep the block
        reason = result.stderr.decode("utf-8", "replace").strip() or "Blocked by graphify."
        print(reason, file=sys.stderr)
        return 2
    out = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0 or not out:
        return 0
    print(safe_json(out, event_name(raw)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
