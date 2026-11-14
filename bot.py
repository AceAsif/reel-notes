"""Telegram bot: send it a reel video, get back a note with action items."""
import asyncio
import datetime
import os
import re
import tempfile
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # must run before importing processor so it sees .env values

import requests  # noqa: E402
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.constants import ChatAction  # noqa: E402
from telegram.error import NetworkError, TimedOut  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import processor  # noqa: E402

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Australia/Hobart"))
YTDLP_UPDATE_TIME = os.getenv("YTDLP_UPDATE_TIME", "03:30").strip().lower()
MAX_BYTES = 20 * 1024 * 1024  # Telegram bots can only download files up to 20 MB


def is_allowed(update: Update) -> bool:
    """Only you can use the bot once ALLOWED_USER_ID is set."""
    return not ALLOWED_USER_ID or str(update.effective_user.id) == ALLOWED_USER_ID


def format_reply(data: dict, note_path: Path) -> str:
    lang = data.get("language", "en")
    lang_tag = f"  🌐 {lang}→en" if lang != "en" else ""
    if processor.slide_total(data) > 1:
        lang_tag += f"  🎞 {processor.slide_summary(data)}"
    parts = [f"📝 {data['title']}  [{data['category']}]{lang_tag}"]
    if data.get("tags"):
        parts.append("🏷 " + " ".join(f"#{t}" for t in data["tags"]))
    parts += ["", data["summary"]]
    if data.get("quote"):
        tail = "" if data.get("quote_exact") else "  (paraphrased)"
        parts += ["", f"💬 “{data['quote']}”{tail}"]
    if data.get("lesson"):
        parts += ["", f"💡 Lesson: {data['lesson']}"]
    if data.get("habit"):
        parts += ["", f"🔁 Habit to try: {data['habit']}"]
    if data["key_points"]:
        parts += ["", "Key points:", *[f"• {p}" for p in data["key_points"]]]
    if data["resources"]:
        parts += ["", "Resources:"]
        parts += [f"• {processor.resource_line(r, data['category'])}" for r in data["resources"]]
    if data.get("claims"):
        parts += ["", "⚠️ Claims to check:"]
        parts += [f"• “{c['claim']}”" + (f" — {c['why']}" if c["why"] else "")
                  for c in data["claims"]]
    if data["action_items"]:
        parts += ["", "✅ Action items:"]
        parts += [f"☐ {processor.PRIORITY_ICON[a['priority']]}{a['text']}"
                  for a in data["action_items"]]
    parts += ["", f"Saved: {note_path.name}"]
    return "\n".join(parts)[:4000]  # Telegram message limit is 4096


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hi! Your Telegram user ID is {update.effective_user.id}\n"
        "Put it in .env as ALLOWED_USER_ID, then restart me.\n\n"
        "Send me a reel, carousel, YouTube Short or TikTok link (or a video) and I'll turn it into a note.\n\n"
        "Actions: /todo  /done 2  /skip 3  /high 3  /low 3  /remind 3 friday  /nudge  /stats\n"
        "Notes: /ask question  /notes  /note 1  /file 1  /plan 1  /search strix\n"
        "Tags: /tags  /tag python  /renametag old new  /retag\n"
        "Fix: /redo (make the newest note again)  /health  /update\n\n"
        "Or just talk to me! Ask anything about your notes, e.g. \"what did I save about Claude?\" (/newchat starts over)\n\n"
        "Every morning I'll send one action to do, and every Sunday a weekly review."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    msg = update.message
    media = msg.video or msg.document
    if media.file_size and media.file_size > MAX_BYTES:
        await msg.reply_text("That file is over 20 MB, which is Telegram's limit for bots.")
        return

    # If the caption has the reel link and we've seen it before, don't redo it
    link = re.search(LINK_PATTERN, msg.caption or "")
    if link and await already_saved(msg, link.group(0)):
        return

    status = await msg.reply_text("Got it ⏳ Processing... this can take a minute or two.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "reel.mp4"
            tg_file = await media.get_file()
            await tg_file.download_to_drive(video_path)
            # Heavy work runs in a thread so the bot stays responsive
            note_path, data = await asyncio.to_thread(
                processor.process_video, video_path, msg.caption or ""
            )
    except Exception as exc:  # show the error so you can fix it
        await status.edit_text(f"❌ Something went wrong: {exc}")
        return

    await status.edit_text(format_reply(data, note_path))


# ---- Screenshots → notes -------------------------------------------------
# Telegram sends an album as separate messages with the same media_group_id.
# We collect them for a moment, then make ONE note from all of them.
ALBUM_WAIT = 2.5          # seconds to wait for the rest of an album
MAX_SCREENSHOTS = 10
_albums: dict[str, list] = {}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    msg = update.message
    if msg.media_group_id:
        album = _albums.setdefault(msg.media_group_id, [])
        album.append(msg)
        if len(album) == 1:                      # first photo: wait for the others
            context.job_queue.run_once(process_album, ALBUM_WAIT,
                                       data=msg.media_group_id,
                                       name=f"album-{msg.media_group_id}")
        return
    await process_screenshots([msg])


async def process_album(context: ContextTypes.DEFAULT_TYPE) -> None:
    msgs = _albums.pop(context.job.data, [])
    if msgs:
        await process_screenshots(msgs)


async def process_screenshots(msgs: list) -> None:
    first = msgs[0]
    msgs = msgs[:MAX_SCREENSHOTS]
    caption = next((m.caption for m in msgs if m.caption), "") or ""
    link = re.search(LINK_PATTERN, caption)
    source = link.group(0) if link else "screenshot"
    if link and await already_saved(first, source):
        return
    count = f"{len(msgs)} screenshots" if len(msgs) > 1 else "screenshot"
    status = await first.reply_text(f"Got the {count} 📸 Reading the text... this takes about a minute.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, m in enumerate(msgs, start=1):
                media = m.photo[-1] if m.photo else m.document   # biggest photo size
                ext = Path(getattr(media, "file_name", "") or "x.jpg").suffix or ".jpg"
                path = Path(tmp) / f"shot{i}{ext.lower()}"
                await (await media.get_file()).download_to_drive(path)
                paths.append(path)
            note_path, data = await asyncio.to_thread(
                processor.process_videos, paths, source, caption)
    except Exception as exc:
        await status.edit_text(f"❌ Something went wrong: {exc}")
        return
    await status.edit_text(format_reply(data, note_path))


LINK_PATTERN = (r"https?://\S*(instagram\.com|facebook\.com|fb\.watch|"
                r"youtube\.com/(shorts|watch)|youtu\.be|tiktok\.com)\S*")


async def already_saved(msg, url: str) -> bool:
    """Reply and return True if this reel already has a note."""
    existing = processor.find_note_by_source(url)
    if existing:
        await msg.reply_text(
            f"📌 Already saved: {existing.name}\n"
            "To make a fresh note, delete that file from the notes folder and send it again."
        )
        return True
    return False


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """You paste a reel link; the bot downloads it and makes the note."""
    if not is_allowed(update):
        return
    msg = update.message
    url = re.search(LINK_PATTERN, msg.text).group(0)
    if await already_saved(msg, url):
        return

    status = await msg.reply_text("Got the link ⏳ Downloading...")
    await note_from_link(status, url)


async def note_from_link(status, url: str) -> Path | None:
    """Download + process a link, editing the status message as it goes."""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            videos, caption, creator = await asyncio.to_thread(
                processor.download_media, url, Path(tmp))
            if len(videos) > 1:
                photos = sum(v.suffix.lower() in processor.IMAGE_EXTS for v in videos)
                kinds = processor.slide_summary(
                    {"video_count": len(videos) - photos, "photo_count": photos})
                await status.edit_text(
                    f"Found {kinds} in this post ⏳ Processing all of them "
                    f"(about {len(videos) - photos + 1} min)...")
            else:
                await status.edit_text("Downloaded ⏳ Processing...")
            note_path, data = await asyncio.to_thread(
                processor.process_videos, videos, url, caption, creator)
    except Exception as exc:
        await status.edit_text(
            f"❌ Something went wrong: {exc}\n\n"
            "If it's a login/cookies error, see COOKIES_FILE in .env, "
            "or send me the video file instead."
        )
        return None

    await status.edit_text(format_reply(data, note_path))
    return note_path


# ---- /redo ------------------------------------------------------------------

async def redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/redo = make your newest note again. /redo 2 (after /notes) or /redo llm wiki."""
    if not is_allowed(update):
        return
    args = " ".join(context.args or []).strip()
    path = None
    if args.isdigit():
        paths = context.user_data.get("last_results", [])
        n = int(args)
        if 1 <= n <= len(paths):
            path = Path(paths[n - 1])
    else:
        path = processor.find_note_for_redo(args)
    if not path or not path.exists():
        await update.message.reply_text(
            "I couldn't find that note. Try /redo (newest note), /redo llm wiki, "
            "or /notes then /redo 2")
        return
    source = processor.note_source(path)
    if not re.search(LINK_PATTERN, source):
        await update.message.reply_text(
            f"“{path.name}” wasn't made from a link, so I can't download it again. "
            "Send the video or screenshots again instead.")
        return
    context.user_data["redo_path"] = str(path)
    title = path.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ")
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Yes, redo it", callback_data="redo:yes"),
                                     InlineKeyboardButton("Cancel", callback_data="redo:no")]])
    await update.message.reply_text(
        f"Make this note again with {processor.OLLAMA_MODEL}?\n\n📝 {title}\n{source}\n\n"
        "The old note moves to the “old” folder (not deleted). "
        "Ticked actions in it won't carry over.", reply_markup=buttons)


async def redo_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    path = Path(context.user_data.pop("redo_path", "") or ".")
    if query.data != "redo:yes":
        await query.edit_message_text("OK, kept the note as it is.")
        return
    if not path.is_file():
        await query.edit_message_text("That note is gone. Run /redo again.")
        return
    url = processor.note_source(path)
    await query.edit_message_text("🔁 Making the note again ⏳ Downloading...")
    old = path.with_suffix(".redo")          # hide it so the duplicate check doesn't stop us
    path.replace(old)
    new_note = await note_from_link(query.message, url)
    if new_note:
        processor.archive_note(old)
    else:
        old.replace(path)                   # failed: put the old note back


# ---- /health and yt-dlp updates ----------------------------------------------

def health_text() -> str:
    checks = processor.health_checks()
    lines = [f"{'✅' if ok else '❌'} {name}: {detail}" for ok, name, detail in checks]
    bad = sum(not ok for ok, _, _ in checks)
    head = "🩺 All good, Boss!" if not bad else f"🩺 {bad} problem{'s' if bad > 1 else ''} found:"
    return head + "\n\n" + "\n".join(lines)


async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    await update.message.reply_text(await asyncio.to_thread(health_text))


def update_text(old: str, new: str, err: str) -> str:
    if err:
        return f"⚠️ yt-dlp update failed ({old}):\n{err}"
    if old == new:
        return f"✅ yt-dlp is up to date ({new})."
    return (f"⬆️ yt-dlp updated: {old} → {new}\n"
            "Restart me from the tray icon (Quit, then open again) to use it.")


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/update = update yt-dlp now (new Instagram/Facebook changes break old versions)."""
    if not is_allowed(update):
        return
    status = await update.message.reply_text("Checking for a new yt-dlp ⏳")
    await status.edit_text(update_text(*await asyncio.to_thread(processor.update_ytdlp)))


async def daily_ytdlp_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every night. Only messages you if something changed or failed."""
    old, new, err = await asyncio.to_thread(processor.update_ytdlp)
    if err or old != new:
        await context.bot.send_message(context.job.chat_id, update_text(old, new, err))


TODO_PAGE_SIZE = 10
LEVELS = ("high", "normal", "low")


def todo_page(page: int = 1, level: str | None = None) -> tuple[str, InlineKeyboardMarkup | None]:
    """One page of /todo (10 actions). Numbers are the real /todo numbers, so
    /done 23 works from any page. level='high' shows only 🔥 actions."""
    all_actions = list(enumerate(processor.open_actions(), start=1))
    if not all_actions:
        return "🎉 No open action items.", None
    items = [(n, a) for n, a in all_actions if level is None or a["priority"] == level]
    if not items:
        return f"No {level} priority actions. See everything with /todo", None
    pages = (len(items) + TODO_PAGE_SIZE - 1) // TODO_PAGE_SIZE
    page = max(1, min(page, pages))
    shown = items[(page - 1) * TODO_PAGE_SIZE: page * TODO_PAGE_SIZE]

    headings = {"high": "🔥 HIGH PRIORITY", "normal": "▫️ NORMAL", "low": "🔽 LOW"}
    reminded = {r["action_id"] for r in processor.load_reminders()}
    counts = {lv: sum(a["priority"] == lv for _, a in all_actions) for lv in LEVELS}
    what = f"{level} priority " if level else ""
    lines = [f"📋 {len(items)} open {what}actions"
             + (f" (page {page}/{pages})" if pages > 1 else "") + ":",
             f"🔥 {counts['high']} high · ▫️ {counts['normal']} normal · 🔽 {counts['low']} low"]
    current_priority, current_title = None, None
    for n, a in shown:
        if a["priority"] != current_priority:   # priority section
            current_priority, current_title = a["priority"], None
            lines += ["", f"━━ {headings[a['priority']]} ━━"]
        if a["title"] != current_title:         # reel title inside the section
            current_title = a["title"]
            lines += [f"📌 {current_title}"]
        bell = " 🔔" if processor.action_id(a) in reminded else ""
        lines.append(f"{n}. ☐ {a['action']}{bell}")
    lines += ["", "/done 2 · /skip 3 · /high 3 · /low 3 · /remind 3 friday",
              "Only 🔥 ones: /todo high"]

    keyboard = None
    if pages > 1:
        tag = level or "all"
        row = []
        if page > 1:
            row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"todo:{tag}:{page - 1}"))
        row.append(InlineKeyboardButton(f"{page}/{pages}", callback_data=f"todo:{tag}:{page}"))
        if page < pages:
            row.append(InlineKeyboardButton("Next ➡️", callback_data=f"todo:{tag}:{page + 1}"))
        keyboard = InlineKeyboardMarkup([row])
    return "\n".join(lines)[:4000], keyboard


def actions_text() -> str:
    """First page of /todo as plain text (used by the weekly review)."""
    text, keyboard = todo_page(1)
    return text + ("\n\nMore pages: send /todo" if keyboard else "")


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/todo, /todo 2 (page 2), /todo high (only 🔥), /todo low 2."""
    if not is_allowed(update):
        return
    args = [a.lower() for a in (context.args or [])]
    level = next((a for a in args if a in LEVELS), None)
    page = next((int(a) for a in args if a.isdigit()), 1)
    text, keyboard = todo_page(page, level)
    await update.message.reply_text(text, reply_markup=keyboard)


async def todo_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⬅️ / ➡️ page buttons under /todo."""
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    _, tag, page = query.data.split(":")
    text, keyboard = todo_page(int(page), None if tag == "all" else tag)
    try:
        await query.edit_message_text(text, reply_markup=keyboard)
    except Exception:
        pass                                    # same page pressed again: nothing changed


async def mark_actions(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       mark: str, command: str, heading: str) -> None:
    """Shared code for /done (mark 'x') and /skip (mark '-')."""
    if not is_allowed(update):
        return
    numbers = [int(x) for x in re.findall(r"\d+", " ".join(context.args or []))]
    if not numbers:
        await update.message.reply_text(
            f"Usage: /{command} 2  or  /{command} 1 3 4  (numbers come from /todo)")
        return
    changed = processor.complete_actions(numbers, mark)
    if not changed:
        await update.message.reply_text("No matching numbers. Send /todo to see the list.")
        return
    remaining = len(processor.open_actions())
    reply = [heading, *[f"• {t}" for t in changed], "",
             f"{remaining} open items left. Numbers have changed, so send /todo again "
             "before your next /done or /skip."]
    await update.message.reply_text("\n".join(reply))


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done 2  or  /done 1 3 4  ticks off actions by their /todo number."""
    await mark_actions(update, context, "x", "done", "✅ Done:")


async def skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/skip 3 drops an action you've decided not to do (kept in the note as [-])."""
    await mark_actions(update, context, "-", "skip", "⏭ Skipped:")


async def change_priority(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          level: str) -> None:
    """Shared code for /high, /normal and /low."""
    if not is_allowed(update):
        return
    numbers = [int(x) for x in re.findall(r"\d+", " ".join(context.args or []))]
    if not numbers:
        await update.message.reply_text(
            f"Usage: /{level} 3  or  /{level} 1 4  (numbers come from /todo)")
        return
    changed = processor.set_priority(numbers, level)
    if not changed:
        await update.message.reply_text("No matching numbers. Send /todo to see the list.")
        return
    icon = {"high": "🔥", "normal": "▫️", "low": "🔽"}[level]
    reply = [f"{icon} Now {level} priority:", *[f"• {t}" for t in changed], "",
             "The list order has changed, so send /todo before your next command."]
    await update.message.reply_text("\n".join(reply))


async def high(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await change_priority(update, context, "high")


async def normal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await change_priority(update, context, "normal")


async def low(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await change_priority(update, context, "low")


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/search strix   or   /search claude memory  (all words must match)."""
    if not is_allowed(update):
        return
    query = " ".join(context.args or []).strip()
    if not query:
        await update.message.reply_text("Usage: /search strix  (or several words: /search claude memory)")
        return
    results = processor.search_notes(query)
    if not results:
        await update.message.reply_text(f"🔍 No notes found for \"{query}\".")
        return
    # Remember results so /note 2 opens the 2nd one
    context.user_data["last_results"] = [str(r["path"]) for r in results]
    lines = [f"🔍 {len(results)} note(s) for \"{query}\":", ""]
    for n, r in enumerate(results, start=1):
        lines.append(f"{n}. {r['title']}  ({r['date']})")
        if r["snippet"]:
            lines.append(f"    “{r['snippet']}”")
    lines += ["", "Open one with /note 1"]
    await update.message.reply_text("\n".join(lines)[:4000])


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/note 2 shows the 2nd note from your last /search (or /notes)."""
    if not is_allowed(update):
        return
    paths = context.user_data.get("last_results", [])
    numbers = re.findall(r"\d+", " ".join(context.args or []))
    if not numbers or not paths:
        await update.message.reply_text("Use /search or /notes first, then /note 1")
        return
    n = int(numbers[0])
    if not 1 <= n <= len(paths) or not Path(paths[n - 1]).exists():
        await update.message.reply_text("No note with that number. Run /search or /notes again.")
        return
    await update.message.reply_text(processor.note_summary_text(Path(paths[n - 1]))[:4000])


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask which tools help Claude remember things?  → answer from your notes."""
    if not is_allowed(update):
        return
    question = " ".join(context.args or []).strip()
    if not question:
        await update.message.reply_text(
            "Usage: /ask your question\n"
            "e.g. /ask which tools help Claude remember things?")
        return
    status = await update.message.reply_text("🤔 Looking through your notes...")
    try:
        answer, sources = await asyncio.to_thread(processor.answer_question, question)
    except Exception as exc:
        await status.edit_text(f"❌ Something went wrong: {exc}")
        return
    if not sources:
        await status.edit_text(f"🔍 {answer}\nTry /search with a single word, e.g. /search strix")
        return
    context.user_data["last_results"] = [str(p) for p in sources]
    lines = [f"💡 {answer}", "", "📚 Based on these notes (check them, AI can be wrong):"]
    for n, path in enumerate(sources, start=1):
        title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        lines.append(f"{n}. {title}  ({path.name[:10]})")
    lines += ["", "Open one with /note 1"]
    await status.edit_text("\n".join(lines)[:4000])


# ---- chat mode ----------------------------------------------------------------

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Any normal message (not a /command, not a link): talk about your notes."""
    if not is_allowed(update):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    history = context.chat_data.setdefault("chat_history", [])
    try:
        reply, sources = await asyncio.to_thread(processor.chat_reply, text, list(history))
    except requests.exceptions.ConnectionError:
        await update.message.reply_text(
            "😴 I can't reach the AI on your PC. Is Ollama running? "
            "(Look for the llama icon near the clock.)")
        return
    except Exception as exc:
        await update.message.reply_text(f"❌ Something went wrong: {exc}")
        return
    history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
    del history[:-processor.CHAT_HISTORY_TURNS * 2]          # keep only recent turns
    if sources:
        context.user_data["last_results"] = [str(p) for p in sources]
        titles = []
        for n, path in enumerate(sources, start=1):
            title = path.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
            titles.append(f"{n}. {title}")
        reply += "\n\n📚 From your notes (open with /note 1):\n" + "\n".join(titles)
    await update.message.reply_text(reply[:4000])


async def newchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newchat makes the bot forget the current conversation."""
    if is_allowed(update):
        context.chat_data["chat_history"] = []
        await update.message.reply_text("🧹 Fresh start! What would you like to talk about?")


def note_from_list(context, args) -> tuple[Path | None, str]:
    """Note N from the last /notes, /search, /tag or chat reply (newest notes if none).
    Returns (path, rest of the words after the number)."""
    paths = context.user_data.get("last_results")
    if not paths:
        files = sorted(processor.NOTES_DIR.glob("*.md"), reverse=True)[:10] \
            if processor.NOTES_DIR.exists() else []
        paths = [str(f) for f in files]
    words = list(args or [])
    n = int(words.pop(0)) if words and words[0].isdigit() else 1
    if not paths or not 1 <= n <= len(paths) or not Path(paths[n - 1]).exists():
        return None, ""
    return Path(paths[n - 1]), " ".join(words)


async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/plan 2  (or /plan 2 my own goal) → a prompt to paste into Claude."""
    if not is_allowed(update):
        return
    path, goal = note_from_list(context, context.args)
    if path is None:
        await update.message.reply_text(
            "Usage: /plan 2  (number from /notes, /search, /tag or a chat reply)\n"
            "Add your own goal: /plan 2 I want to use it in my bot")
        return
    prompt = processor.make_plan(path, goal)
    await update.message.reply_text(
        "📋 Here's your action plan. Long-press it → Copy, then paste it into Claude 👇")
    if len(prompt) <= 4000:
        await update.message.reply_text(prompt)
    else:                                         # very long: send as a file instead
        await update.message.reply_document(document=prompt.encode("utf-8"),
                                            filename=f"plan_{path.stem[16:] or path.stem}.txt")


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/file 2 sends note 2 (from your last /search, /notes or /tag) as a .md file,
    so you can open, save or share it on your phone."""
    if not is_allowed(update):
        return
    paths = context.user_data.get("last_results")
    if not paths:  # nothing searched yet: use the newest notes
        files = sorted(processor.NOTES_DIR.glob("*.md"), reverse=True)[:10] \
            if processor.NOTES_DIR.exists() else []
        paths = [str(f) for f in files]
    numbers = re.findall(r"\d+", " ".join(context.args or []))
    n = int(numbers[0]) if numbers else 1
    if not paths or not 1 <= n <= len(paths) or not Path(paths[n - 1]).exists():
        await update.message.reply_text("No note with that number. Run /notes or /search first.")
        return
    path = Path(paths[n - 1])
    with path.open("rb") as f:
        await update.message.reply_document(document=f, filename=path.name,
                                            caption=f"📄 {path.stem[16:] or path.stem}")


async def notes_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/notes shows your 10 newest notes."""
    if not is_allowed(update):
        return
    files = sorted(processor.NOTES_DIR.glob("*.md"), reverse=True)[:10] \
        if processor.NOTES_DIR.exists() else []
    if not files:
        await update.message.reply_text("No notes yet. Send me a reel!")
        return
    context.user_data["last_results"] = [str(f) for f in files]
    lines = ["🗂 Your latest notes:", ""]
    for n, f in enumerate(files, start=1):
        title = f.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        lines.append(f"{n}. {title}  ({f.name[:10]})")
    lines += ["", "Open one with /note 1"]
    await update.message.reply_text("\n".join(lines))


def tag_results_text(name: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Text listing the notes with this tag (and remember them for /note N)."""
    name = name.lstrip("#").lower()
    paths = processor.notes_with_tag(name)
    if not paths:
        return f"🏷 No notes tagged #{name}. See all tags with /tags"
    context.user_data["last_results"] = [str(p) for p in paths]
    lines = [f"🏷 {len(paths)} note(s) tagged #{name}:", ""]
    for n, p in enumerate(paths, start=1):
        title = p.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        lines.append(f"{n}. {title}  ({p.name[:10]})")
    lines += ["", "Open one with /note 1"]
    return "\n".join(lines)[:4000]


def tag_buttons(limit: int = 12, per_row: int = 3) -> InlineKeyboardMarkup | None:
    """Buttons for your most-used tags, e.g. [#github (7)] [#claude (2)] ..."""
    top = processor.all_tags()[:limit]
    if not top:
        return None
    buttons = [InlineKeyboardButton(f"#{t} ({n})", callback_data=f"tag:{t}"[:64])
               for t, n in top]
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(rows)


async def tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tag python shows notes tagged #python; /tag on its own shows tag buttons."""
    if not is_allowed(update):
        return
    name = " ".join(context.args or []).strip()
    if name:
        await update.message.reply_text(tag_results_text(name, context))
        return
    keyboard = tag_buttons()
    if keyboard is None:
        await update.message.reply_text(
            "No tags yet. New reels get tags automatically; use /retag for older notes.")
        return
    await update.message.reply_text(
        "🏷 Pick a tag (or type /tag python for any tag):", reply_markup=keyboard)


async def tag_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs when you tap one of the tag buttons."""
    query = update.callback_query
    await query.answer()  # stops the loading spinner on the button
    if not is_allowed(update):
        return
    name = query.data.split(":", 1)[1]
    await query.message.reply_text(tag_results_text(name, context))


async def renametag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/renametag claudie claude  renames (or merges) a tag in every note."""
    if not is_allowed(update):
        return
    args = context.args or []
    if len(args) != 2:
        await update.message.reply_text(
            "Usage: /renametag old new   e.g. /renametag claudie claude\n"
            "If notes already use the new tag, the two are merged.")
        return
    count = processor.rename_tag(args[0], args[1])
    old, new = args[0].lstrip("#").lower(), args[1].lstrip("#").lower()
    if count == 0:
        await update.message.reply_text(f"🏷 No notes tagged #{old}. See all tags with /tags")
    else:
        await update.message.reply_text(f"🏷 Renamed #{old} → #{new} in {count} note(s).")


async def tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tags lists all tags with how many notes use each."""
    if not is_allowed(update):
        return
    counts = processor.all_tags()
    if not counts:
        await update.message.reply_text(
            "No tags yet. New reels get tags automatically; use /retag for older notes.")
        return
    lines = ["🏷 Your tags:", ""] + [f"#{t}  ({n})" for t, n in counts]
    lines += ["", "Filter with /tag python"]
    await update.message.reply_text("\n".join(lines)[:4000])


async def retag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/retag adds tags to older notes that were saved before tags existed."""
    if not is_allowed(update):
        return
    status = await update.message.reply_text("🏷 Adding tags to older notes... ⏳")
    done = await asyncio.to_thread(processor.tag_untagged_notes)
    if not done:
        await status.edit_text("🏷 All notes already have tags.")
        return
    lines = [f"🏷 Tagged {len(done)} note(s):", ""]
    lines += [f"• {title}: " + " ".join(f"#{t}" for t in t_list) for title, t_list in done]
    await status.edit_text("\n".join(lines)[:4000])


NUDGE_TIME = os.getenv("NUDGE_TIME", "08:00").strip().lower()   # "off" to disable


def nudge_message(action: dict, intro: str) -> tuple[str, InlineKeyboardMarkup]:
    icon = processor.PRIORITY_ICON[action["priority"]]
    text = f"{intro}\n\n{icon}{action['action']}\n\n📌 From: {action['title']}"
    aid = processor.action_id(action)
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"nudge:done:{aid}"),
        InlineKeyboardButton("⏭ Skip", callback_data=f"nudge:skip:{aid}"),
        InlineKeyboardButton("🔁 Another one", callback_data=f"nudge:next:{aid}"),
    ]])
    return text, buttons


async def send_nudge(bot, chat_id: int, intro: str) -> None:
    action = processor.pick_nudge()
    if action is None:
        await bot.send_message(chat_id, "🎉 No open actions. Send me a reel to get new ideas!")
        return
    text, buttons = nudge_message(action, intro)
    await bot.send_message(chat_id, text, reply_markup=buttons)


async def daily_nudge(context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_nudge(context.bot, context.job.chat_id, "☀️ Good morning! Today's one action:")


async def nudge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/nudge gives you one action to do right now."""
    if is_allowed(update):
        await send_nudge(context.bot, update.effective_chat.id, "🎯 One action to do now:")


async def nudge_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Done / Skip / Another one buttons under a nudge."""
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    _, what, aid = query.data.split(":", 2)
    if what == "next":
        action = processor.pick_nudge(after=aid)
        if action is None:
            await query.edit_message_text("🎉 No open actions left!")
            return
        text, buttons = nudge_message(action, "🔁 How about this one?")
        await query.edit_message_text(text, reply_markup=buttons)
        return
    found = processor.find_action(aid)
    if found is None:
        await query.edit_message_text("This action is already done or skipped. Try /nudge")
        return
    number, action = found
    processor.complete_actions([number], "x" if what == "done" else "-")
    processor.remove_reminder(aid)          # no reminder needed for a finished action
    left = len(processor.open_actions())
    verb = "✅ Done" if what == "done" else "⏭ Skipped"
    await query.edit_message_text(f"{verb}: {action['action']}\n\n{left} open items left. "
                                  "Want another? /nudge")


# ---- reminders --------------------------------------------------------------

REMIND_EXAMPLES = ("Examples:\n/remind 3 friday\n/remind 3 tomorrow 5pm\n"
                   "/remind 3 in 2 hours\n/remind 3 20/11 9am\n(no time = 9:00 am)")


def when_text(when: datetime.datetime) -> str:
    """'Fri 20 Nov, 9:00 am'"""
    ampm = "am" if when.hour < 12 else "pm"
    return f"{when:%a} {when.day} {when:%b}, {when.hour % 12 or 12}:{when:%M} {ampm}"


def schedule_reminder(job_queue, reminder: dict, chat_id: int) -> None:
    when = datetime.datetime.fromisoformat(reminder["when"])
    now = datetime.datetime.now(TIMEZONE)
    # Missed while the PC was off? Send it shortly after start-up instead.
    run_at = when if when > now else now + datetime.timedelta(seconds=15)
    job_queue.run_once(send_reminder, when=run_at, chat_id=chat_id,
                       data=reminder["action_id"], name=f"remind:{reminder['action_id']}")


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    aid = context.job.data
    reminder = next((r for r in processor.load_reminders() if r["action_id"] == aid), None)
    if reminder is None:
        return                                  # cancelled with /unremind
    processor.remove_reminder(aid)
    found = processor.find_action(aid)
    if found is None:
        return                                  # already done or skipped
    _, action = found
    icon = processor.PRIORITY_ICON[action["priority"]]
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Done", callback_data=f"nudge:done:{aid}"),
        InlineKeyboardButton("⏭ Skip", callback_data=f"nudge:skip:{aid}"),
        InlineKeyboardButton("⏰ Tomorrow", callback_data=f"rem:tomorrow:{aid}"),
    ]])
    await context.bot.send_message(
        context.job.chat_id,
        f"⏰ Reminder!\n\n{icon}{action['action']}\n\n📌 From: {action['title']}",
        reply_markup=buttons)


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/remind 3 friday  → reminds you about /todo item 3 on Friday at 9:00 am."""
    if not is_allowed(update):
        return
    args = context.args or []
    if len(args) < 2 or not args[0].isdigit():
        await update.message.reply_text("Usage: /remind <number from /todo> <when>\n\n"
                                        + REMIND_EXAMPLES)
        return
    actions = processor.open_actions()
    n = int(args[0])
    if not 1 <= n <= len(actions):
        await update.message.reply_text("No action with that number. Send /todo to see the list.")
        return
    now = datetime.datetime.now(TIMEZONE)
    when = processor.parse_when(" ".join(args[1:]), now)
    if when is None:
        await update.message.reply_text("I didn't understand the time 🤔\n\n" + REMIND_EXAMPLES)
        return
    if when <= now:
        await update.message.reply_text("That time has already passed. Pick a future time.")
        return
    reminder = processor.add_reminder(actions[n - 1], when)
    for job in context.job_queue.get_jobs_by_name(f"remind:{reminder['action_id']}"):
        job.schedule_removal()                  # replace an older reminder for this action
    schedule_reminder(context.job_queue, reminder, update.effective_chat.id)
    await update.message.reply_text(
        f"🔔 I'll remind you on {when_text(when)}:\n{actions[n - 1]['action']}")


def reminders_list() -> list[dict]:
    """Saved reminders whose action is still open, soonest first."""
    return [r for r in processor.load_reminders() if processor.find_action(r["action_id"])]


async def reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/reminders lists upcoming reminders."""
    if not is_allowed(update):
        return
    items = reminders_list()
    if not items:
        await update.message.reply_text("🔔 No reminders set. Add one: /remind 3 friday")
        return
    lines = ["🔔 Upcoming reminders:", ""]
    for n, r in enumerate(items, start=1):
        when = datetime.datetime.fromisoformat(r["when"])
        lines.append(f"{n}. {when_text(when)} — {r['text']}")
    lines += ["", "Cancel one with /unremind 1"]
    await update.message.reply_text("\n".join(lines)[:4000])


async def unremind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unremind 1 cancels reminder 1 from /reminders."""
    if not is_allowed(update):
        return
    items = reminders_list()
    nums = re.findall(r"\d+", " ".join(context.args or []))
    if not nums or not 1 <= int(nums[0]) <= len(items):
        await update.message.reply_text("Usage: /unremind 1  (numbers come from /reminders)")
        return
    r = items[int(nums[0]) - 1]
    processor.remove_reminder(r["action_id"])
    for job in context.job_queue.get_jobs_by_name(f"remind:{r['action_id']}"):
        job.schedule_removal()
    await update.message.reply_text(f"🔕 Reminder cancelled: {r['text']}")


async def reminder_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """⏰ Tomorrow button: remind again tomorrow at 9:00 am."""
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    aid = query.data.split(":", 2)[2]
    found = processor.find_action(aid)
    if found is None:
        await query.edit_message_text("This action is already done or skipped.")
        return
    _, action = found
    when = processor.parse_when("tomorrow", datetime.datetime.now(TIMEZONE))
    reminder = processor.add_reminder(action, when)
    schedule_reminder(context.job_queue, reminder, query.message.chat_id)
    await query.edit_message_text(f"⏰ OK, I'll remind you again on {when_text(when)}:\n"
                                  f"{action['action']}")


# ---- resurface old notes --------------------------------------------------------

RESURFACE = os.getenv("RESURFACE", "on").strip().lower()   # "off" to disable


def resurface_message(shift: int = 0) -> tuple[str, InlineKeyboardMarkup | None, Path | None]:
    item = processor.pick_resurface(shift=shift)
    if item is None:
        return ("🧠 No notes older than a week yet. I'll start resurfacing them soon!",
                None, None)
    icon = {"quote": "💬", "point": "💡", "lesson": "💡", "summary": "📝"}[item["kind"]]
    weeks = item["age_days"] // 7
    ago = f"{weeks} week{'s' * (weeks != 1)} ago" if weeks else f"{item['age_days']} days ago"
    text = (f"🧠 Remember this?\n\n{icon} {item['text']}\n\n"
            f"📌 From: {item['title']} (saved {ago})\nOpen the full note: /note 1")
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
        "🔁 Another one", callback_data=f"resurf:{shift + 1}")]])
    return text, keyboard, item["path"]


def remember_for_note_command(application, chat_id: int, path: Path | None) -> None:
    """So that '/note 1' opens the resurfaced note."""
    if path is not None:
        application.user_data[chat_id]["last_results"] = [str(path)]


async def weekly_resurface(context: ContextTypes.DEFAULT_TYPE) -> None:
    text, keyboard, path = resurface_message()
    if path is None:
        return                                  # nothing old enough yet: stay quiet
    remember_for_note_command(context.application, context.job.chat_id, path)
    await context.bot.send_message(context.job.chat_id, text, reply_markup=keyboard)


async def remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/remember shows one older note to refresh your memory."""
    if not is_allowed(update):
        return
    text, keyboard, path = resurface_message()
    if path is not None:
        context.user_data["last_results"] = [str(path)]
    await update.message.reply_text(text, reply_markup=keyboard)


async def resurface_button_pressed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_allowed(update):
        return
    text, keyboard, path = resurface_message(int(query.data.split(":")[1]))
    if path is not None:
        context.user_data["last_results"] = [str(path)]
    await query.edit_message_text(text, reply_markup=keyboard)


def stats_text() -> str:
    s = processor.weekly_stats()
    lines = [f"📊 Last 7 days ({s['start']:%d %b} – {s['end']:%d %b})", "",
             f"🎬 Reels saved: {s['saved']}"]
    if s["categories"]:
        lines.append("    " + ", ".join(f"{n} {c}" for c, n in
                                        sorted(s["categories"].items(), key=lambda kv: -kv[1])))
    lines += [f"✅ Actions done: {s['done']}", f"⏭ Actions skipped: {s['skipped']}",
              f"📋 Still open: {s['open']}" + (f" ({s['open_high']} 🔥 high)" if s["open_high"] else "")]
    if s["top_tags"]:
        lines.append("🏷 Top topics: " + "  ".join(f"#{t} ({n})" for t, n in s["top_tags"]))
    if s["done"] == 0 and s["open"]:
        lines += ["", "💪 Nothing ticked off this week. Pick one 🔥 item and do it today!"]
    elif s["done"] >= 5:
        lines += ["", "🎉 Great week, keep it going!"]
    return "\n".join(lines)


def month_text(previous: bool = False) -> str:
    start, end = processor.month_range(previous=previous)
    s = processor.stats_between(start, end)
    title = f"{start:%B %Y}" + ("" if previous else " so far")
    lines = [f"🗓 Your learning in {title}", ""]
    if s["saved"] == 0 and s["done"] == 0:
        return "\n".join(lines + ["No reels saved or actions done yet this month.",
                                   "Send me a reel to get started! 🎬"])
    if s["top_tags"]:
        lines += ["📚 You learned about:"]
        lines += [f"   • #{t} ({n} reel{'s' * (n != 1)})" for t, n in s["top_tags"]]
        lines.append("")
    cats = ", ".join(f"{n} {c}" for c, n in sorted(s["categories"].items(), key=lambda kv: -kv[1]))
    lines.append(f"🎬 Reels saved: {s['saved']}" + (f" ({cats})" if cats else ""))
    lines.append(f"✅ Actions done: {s['done']}   ⏭ Skipped: {s['skipped']}")
    if s["done_items"]:
        lines += ["", "🏆 What you finished:"] + [f"   • {d}" for d in s["done_items"][:5]]
        if len(s["done_items"]) > 5:
            lines.append(f"   ...and {len(s['done_items']) - 5} more")
    lines += ["", f"📋 Still open: {s['open']}"
              + (f" ({s['open_high']} 🔥 high)" if s["open_high"] else "")]
    if s["done"] >= 10:
        lines.append("🎉 Amazing month, you're really acting on what you learn!")
    elif s["saved"] > 0 and s["done"] == 0:
        lines.append("💪 Lots saved, nothing done yet. Try /nudge for one easy action.")
    return "\n".join(lines)[:4000]


async def month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/month = this month so far, /month last = the whole previous month."""
    if is_allowed(update):
        previous = bool(context.args) and context.args[0].lower() in ("last", "previous")
        await update.message.reply_text(month_text(previous))


async def monthly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(context.job.chat_id, month_text(previous=True))


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats shows the last 7 days."""
    if is_allowed(update):
        await update.message.reply_text(stats_text())


async def weekly_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=context.job.chat_id,
        text=("📅 Weekly review\n\n" + stats_text() + "\n\n" + actions_text())[:4000],
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Short one-line log for Telegram hiccups (Bad Gateway, timeouts);
    full details only for real bugs. The bot keeps running either way."""
    err = context.error
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(err, (NetworkError, TimedOut)):
        print(f"[{stamp}] Telegram network hiccup ({err}), retrying automatically")
    else:
        print(f"[{stamp}] Error: {err!r}")
        traceback.print_exception(err)


def build_app() -> Application:
    """Create the bot with all its commands and scheduled jobs (doesn't start it)."""
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("skip", skip))
    app.add_handler(CommandHandler("high", high))
    app.add_handler(CommandHandler("normal", normal))
    app.add_handler(CommandHandler("low", low))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("notes", notes_list))
    app.add_handler(CommandHandler("tag", tag))
    app.add_handler(CallbackQueryHandler(tag_button_pressed, pattern=r"^tag:"))
    app.add_handler(CallbackQueryHandler(nudge_button_pressed, pattern=r"^nudge:"))
    app.add_handler(CallbackQueryHandler(todo_button_pressed, pattern=r"^todo:"))
    app.add_handler(CommandHandler("nudge", nudge))
    app.add_handler(CommandHandler("tags", tags))
    app.add_handler(CommandHandler("retag", retag))
    app.add_handler(CommandHandler("renametag", renametag))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("redo", redo))
    app.add_handler(CallbackQueryHandler(redo_button_pressed, pattern=r"^redo:"))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("file", send_file))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("reminders", reminders))
    app.add_handler(CommandHandler("unremind", unremind))
    app.add_handler(CallbackQueryHandler(reminder_button_pressed, pattern=r"^rem:"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(LINK_PATTERN), handle_link))
    # Everything else you type (not a /command) is a chat message about your notes.
    # Added after the link handler, so links still become notes.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    app.add_handler(CommandHandler("newchat", newchat))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CommandHandler("remember", remember))
    app.add_handler(CommandHandler("month", month))
    app.add_handler(CallbackQueryHandler(resurface_button_pressed, pattern=r"^resurf:"))

    if ALLOWED_USER_ID:
        # Every Sunday at 9:00 am (in python-telegram-bot v20+, 0 = Sunday)
        app.job_queue.run_daily(
            weekly_digest,
            time=datetime.time(9, 0, tzinfo=TIMEZONE),
            days=(0,),
            chat_id=int(ALLOWED_USER_ID),
        )
        # Every day at NUDGE_TIME (default 08:00): one action to do today
        if NUDGE_TIME != "off":
            try:
                hour, minute = (int(x) for x in NUDGE_TIME.split(":"))
                app.job_queue.run_daily(
                    daily_nudge,
                    time=datetime.time(hour, minute, tzinfo=TIMEZONE),
                    chat_id=int(ALLOWED_USER_ID),
                )
            except ValueError:
                print(f"NUDGE_TIME={NUDGE_TIME!r} isn't HH:MM, daily nudge disabled")

        # Wednesday 7:00 pm: one older note to remember (0 = Sunday, so 3 = Wednesday)
        if RESURFACE != "off":
            app.job_queue.run_daily(weekly_resurface,
                                    time=datetime.time(19, 0, tzinfo=TIMEZONE),
                                    days=(3,), chat_id=int(ALLOWED_USER_ID))
        # 1st of every month, 9:30 am: summary of the previous month
        app.job_queue.run_monthly(monthly_summary, when=datetime.time(9, 30, tzinfo=TIMEZONE),
                                  day=1, chat_id=int(ALLOWED_USER_ID))
        # Every night at YTDLP_UPDATE_TIME (default 03:30): keep yt-dlp fresh
        if YTDLP_UPDATE_TIME != "off":
            try:
                hour, minute = (int(x) for x in YTDLP_UPDATE_TIME.split(":"))
                app.job_queue.run_daily(daily_ytdlp_update,
                                        time=datetime.time(hour, minute, tzinfo=TIMEZONE),
                                        chat_id=int(ALLOWED_USER_ID))
            except ValueError:
                print(f"YTDLP_UPDATE_TIME={YTDLP_UPDATE_TIME!r} isn't HH:MM, auto-update disabled")
        # Reminders saved before a restart (or missed while the PC was off)
        for r in processor.load_reminders():
            schedule_reminder(app.job_queue, r, int(ALLOWED_USER_ID))

    return app


def main() -> None:
    app = build_app()
    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
