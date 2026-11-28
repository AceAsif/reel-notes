"""Chat simulator: test plain-English chat without Telegram.

A message goes through the same handler Telegram would pick for it (bot.build_app routing), with
fake message objects. The reply text and button labels are printed. Nothing is sent to Telegram.

Safety:
- Everything runs on a temporary notes folder and temporary state files. By default it holds a
  few SAMPLE notes, so no private note text is printed. --copy-real-notes copies your real notes
  into the temporary folder first (run that yourself; the real folder is only read, never written).
- The only network call allowed is the local Ollama URL. GitHub, yt-dlp links and Telegram are blocked.

Use (from the repo root):
  python tools/chat_sim.py "I finished the Hallmark task" --press "✅ Yes, tick it"
  python tools/chat_sim.py --file tests/chat_scenarios.txt        (runs scenarios, prints a table)
"""
import argparse
import asyncio
import contextlib
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TELEGRAM_BOT_TOKEN"] = "123:ABC"      # a fake token: this script never talks to Telegram

import bot  # noqa: E402  (loads .env the same way the real bot does)
import processor  # noqa: E402

STATE_FILES = ("STATE_FILE", "CLEANUP_UNDO_FILE", "SENT_JOBS_FILE", "REMINDERS_FILE", "LINK_INDEX_FILE")
SAMPLE_NOTES = [  # neutral examples only: the repo is public
    ("Hallmark card ideas", ["Send a Hallmark card to a friend"], []),
    ("BLA command line tool", ["Try the BLA command line"], [{"name": "BLA", "link": "https://example.com/bla"}]),
    ("Strix security scanner", ["Run Strix on my repo"],
     [{"name": "Strix", "link": "https://github.com/usestrix/strix"}]),
]


# ---- sandbox ------------------------------------------------------------------------------

def write_sample_notes(folder: Path) -> None:
    start = datetime(2026, 1, 1, 9, 0)
    for n, (title, actions, resources) in enumerate(SAMPLE_NOTES):
        data = {"title": title, "category": "tech", "summary": f"About {title}.", "key_points": [title],
                "resources": resources, "tags": ["sample"], "claims": [], "quote": "", "lesson": "",
                "habit": "", "action_items": processor.clean_actions(actions)}
        processor.save_note(data, "sample transcript", "sample screen", f"https://example.com/v/{n}",
                            saved_at=start + timedelta(minutes=n))


def fill_notes(folder: Path, real_notes: Path | None) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    if real_notes:
        shutil.copytree(real_notes, folder, ignore=shutil.ignore_patterns("pending", "old"))
    else:
        folder.mkdir(parents=True)
        write_sample_notes(folder)


def guard_network() -> dict:
    """Allow only the local Ollama URL. Returns the originals so they can be put back."""
    requests = processor.requests
    ollama = urlsplit(processor.OLLAMA_URL)
    originals = {name: getattr(requests, name) for name in ("post", "get", "request")}

    def checked(name):
        def call(*args, **kwargs):
            url = kwargs.get("url") or (args[1] if name == "request" else args[0])
            parts = urlsplit(url)
            if (parts.hostname, parts.port) != (ollama.hostname, ollama.port) or \
                    parts.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise requests.exceptions.ConnectionError(f"chat_sim blocks network calls to {parts.hostname}")
            return originals[name](*args, **kwargs)
        return call

    for name in originals:
        setattr(requests, name, checked(name))
    return originals


@contextlib.contextmanager
def sandbox(real_notes: Path | None = None):
    """Point every notes folder and state file at a temporary folder, then put them back."""
    saved = {name: getattr(processor, name) for name in ("NOTES_DIR", "PENDING_DIR", *STATE_FILES)}
    saved_bot = {"ALLOWED_USER_ID": bot.ALLOWED_USER_ID, "TOKEN": getattr(bot, "TOKEN", None)}
    real = [Path(p).resolve() for p in saved.values()]
    net = guard_network()
    with tempfile.TemporaryDirectory(prefix="chat_sim_") as tmp:
        tmp = Path(tmp).resolve()
        try:
            processor.NOTES_DIR = tmp / "notes"
            processor.PENDING_DIR = tmp / "pending"
            for name in STATE_FILES:
                setattr(processor, name, tmp / f"{name.lower()}.json")
            bot.ALLOWED_USER_ID, bot.TOKEN = "", "123:ABC"
            in_use = [Path(getattr(processor, n)).resolve() for n in saved]
            if any(tmp not in p.parents for p in in_use) or set(in_use) & set(real):
                raise SystemExit("chat_sim: a notes folder or state file is not in the temp folder. Stopped.")
            fill_notes(processor.NOTES_DIR, real_notes)
            yield tmp
        finally:
            for name, value in saved.items():
                setattr(processor, name, value)
            bot.ALLOWED_USER_ID, bot.TOKEN = saved_bot["ALLOWED_USER_ID"], saved_bot["TOKEN"]
            for name, value in net.items():
                setattr(processor.requests, name, value)


# ---- a fake Telegram chat -------------------------------------------------------------------

class SimChat:
    def __init__(self):
        from telegram import User
        self.app = bot.build_app()
        self.app.bot._bot_user = User(999, "Reel Notes", True, username="sim_reel_bot")  # no Telegram call
        self.user_data, self.chat_data = {}, {}
        self.out: list[str] = []          # what the bot "sent", in order
        self.markup = None                # buttons of the latest message
        self.intents: list[dict] = []
        real_detect = processor.detect_intent

        def detect(message):              # remember what the model decided
            found = real_detect(message)
            self.intents.append(found)
            return found
        processor.detect_intent = detect
        self._real_detect = real_detect

    def close(self):
        processor.detect_intent = self._real_detect

    async def _reply(self, text, reply_markup=None, **kw):
        self._show(text, reply_markup)
        return types.SimpleNamespace(message_id=1000 + len(self.out), edit_text=self._edit,
                                     reply_text=self._reply)

    async def _edit(self, text, reply_markup=None, **kw):
        self._show(text, reply_markup, edited=True)

    async def _nothing(self, *a, **k):
        pass

    def _show(self, text, markup, edited=False):
        self.out.append(("(edited) " if edited else "") + str(text))
        if markup is not None and hasattr(markup, "inline_keyboard"):
            self.markup = markup
        elif not edited:
            self.markup = None

    def labels(self) -> list[str]:
        return [b.text for row in (self.markup.inline_keyboard if self.markup else []) for b in row]

    def context(self, args=None):
        return types.SimpleNamespace(user_data=self.user_data, chat_data=self.chat_data, args=args,
                                     bot=types.SimpleNamespace(send_chat_action=self._nothing),
                                     job_queue=None)

    def handler_for(self, text):
        from telegram import Chat, Message, MessageEntity, Update, User
        entities = [MessageEntity("bot_command", 0, len(text.split()[0]))] if text.startswith("/") else None
        msg = Message(1, datetime.now(), Chat(1, "private"), from_user=User(1, "me", False),
                      text=text, entities=entities)
        upd = Update(1, message=msg)
        upd.set_bot(self.app.bot)
        msg.set_bot(self.app.bot)
        return next((h for h in self.app.handlers[0] if h.check_update(upd)), None)

    def send(self, text):
        handler = self.handler_for(text)
        if handler is None:
            self._show("(no handler for this message)", None)
            return
        if handler.callback.__name__ == "handle_link":
            self._show("(skipped: a link would download a video; chat_sim is for chat only)", None)
            return
        msg = types.SimpleNamespace(text=text, reply_text=self._reply, reply_to_message=None)
        upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1),
                                    effective_chat=types.SimpleNamespace(id=1), callback_query=None)
        args = text.split()[1:] if text.startswith("/") else None
        asyncio.run(handler.callback(upd, self.context(args)))

    def press(self, label):
        button = next((b for row in (self.markup.inline_keyboard if self.markup else []) for b in row
                       if b.text == label), None)
        if button is None:
            self._show(f"(no button \"{label}\". Buttons: {self.labels() or 'none'})", None)
            return False
        from telegram.ext import CallbackQueryHandler
        handler = next((h for h in self.app.handlers[0] if isinstance(h, CallbackQueryHandler)
                        and h.pattern and h.pattern.match(button.callback_data)), None)
        if handler is None:
            self._show(f"(no handler for button data {button.callback_data})", None)
            return False
        query = types.SimpleNamespace(data=button.callback_data, answer=self._nothing,
                                      edit_message_text=self._edit,
                                      message=types.SimpleNamespace(reply_text=self._reply, message_id=1))
        upd = types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1),
                                    effective_chat=types.SimpleNamespace(id=1), message=None)
        asyncio.run(handler.callback(upd, self.context()))
        return True


# ---- scenarios ------------------------------------------------------------------------------

def parse_scenarios(path: Path) -> list[dict]:
    """One scenario per line:  message || expected intent || text the reply must contain || button to press
    The last two are optional. Lines starting with # are comments."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("||")] + ["", "", ""]
        rows.append({"message": parts[0], "intent": parts[1], "expect": parts[2], "press": parts[3]})
    return rows


def run_scenario(s: dict, real_notes: Path | None = None) -> dict:
    """Fresh notes for every scenario, so one scenario can't change the next."""
    with sandbox(real_notes):
        chat = SimChat()
        try:
            chat.send(s["message"])
            buttons = chat.labels()
            pressed = chat.press(s["press"]) if s.get("press") else None
        finally:
            chat.close()
    intent = chat.intents[0]["intent"] if chat.intents else "(none)"
    reply = "\n".join(chat.out)
    problems = []
    if s.get("intent") and intent != s["intent"]:
        problems.append(f"intent {intent}, expected {s['intent']}")
    if s.get("expect") and s["expect"].lower() not in reply.lower():
        problems.append(f"reply has no \"{s['expect']}\"")
    if intent == "chat" and processor.CLAIMED_ACTION_RE.search(reply):
        problems.append("chat reply claims it changed something")
    if s.get("press") and not pressed:
        problems.append(f"could not press \"{s['press']}\"")
    return {**s, "got_intent": intent, "words": chat.intents[0]["words"] if chat.intents else "",
            "reply": reply, "buttons": buttons, "ok": not problems, "problems": problems}


def one_line(text: str, width: int = 90) -> str:
    text = " / ".join(line.strip() for line in text.splitlines() if line.strip())
    return text if len(text) <= width else text[:width - 1] + "…"


def print_result(r: dict) -> None:
    print(f"> {r['message']}")
    print(f"  intent: {r['got_intent']}" + (f" (words: {r['words']})" if r["words"] else ""))
    for line in r["reply"].splitlines():
        print(f"  {line}")
    if r["buttons"]:
        print(f"  [buttons: {' | '.join(r['buttons'])}]")
    if r.get("press"):
        print(f"  (pressed: {r['press']})")
    print(f"  {'PASS' if r['ok'] else 'FAIL: ' + '; '.join(r['problems'])}\n")


def print_table(results: list[dict]) -> None:
    print("| Message | Intent | Reply | Result |")
    print("|---|---|---|---|")
    for r in results:
        print(f"| {r['message']} | {r['got_intent']} | {one_line(r['reply'], 70)} | "
              f"{'PASS' if r['ok'] else 'FAIL: ' + '; '.join(r['problems'])} |")


def real_notes_folder() -> Path:
    folder = Path(os.getenv("NOTES_DIR", "notes"))
    if not folder.is_dir():
        raise SystemExit("chat_sim: the notes folder from .env was not found.")
    return folder


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Test plain-English chat without Telegram.")
    ap.add_argument("message", nargs="?", help="one message to send")
    ap.add_argument("--file", type=Path, help="scenarios file (see tests/chat_scenarios.txt)")
    ap.add_argument("--press", default="", help="label of a button to press after the message")
    ap.add_argument("--copy-real-notes", action="store_true",
                    help="use a temporary COPY of your real notes instead of sample notes (prints note text)")
    args = ap.parse_args(argv)
    if not args.message and not args.file:
        ap.error("give a message or --file")
    real = real_notes_folder() if args.copy_real_notes else None
    scenarios = parse_scenarios(args.file) if args.file else \
        [{"message": args.message, "intent": "", "expect": "", "press": args.press}]
    results = []
    for s in scenarios:
        r = run_scenario(s, real)
        print_result(r)
        results.append(r)
    if len(results) > 1:
        print_table(results)
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # emoji on a Windows console
    raise SystemExit(main())
