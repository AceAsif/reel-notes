"""Telegram bot: send it a reel video, get back a note with action items."""
import asyncio
import datetime
import os
import re
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()  # must run before importing processor so it sees .env values

from telegram import Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import processor  # noqa: E402

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()
TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Australia/Hobart"))
MAX_BYTES = 20 * 1024 * 1024  # Telegram bots can only download files up to 20 MB


def is_allowed(update: Update) -> bool:
    """Only you can use the bot once ALLOWED_USER_ID is set."""
    return not ALLOWED_USER_ID or str(update.effective_user.id) == ALLOWED_USER_ID


def format_reply(data: dict, note_path: Path) -> str:
    lang = data.get("language", "en")
    lang_tag = f"  🌐 {lang}→en" if lang != "en" else ""
    parts = [f"📝 {data['title']}  [{data['category']}]{lang_tag}", "", data["summary"]]
    if data["key_points"]:
        parts += ["", "Key points:", *[f"• {p}" for p in data["key_points"]]]
    if data["resources"]:
        parts += ["", "Resources:"]
        parts += [f"• {processor.resource_line(r, data['category'])}" for r in data["resources"]]
    if data["action_items"]:
        parts += ["", "✅ Action items:", *[f"☐ {a}" for a in data["action_items"]]]
    parts += ["", f"Saved: {note_path.name}"]
    return "\n".join(parts)[:4000]  # Telegram message limit is 4096


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hi! Your Telegram user ID is {update.effective_user.id}\n"
        "Put it in .env as ALLOWED_USER_ID, then restart me.\n\n"
        "Send me a reel link or a reel video and I'll turn it into a note.\n"
        "/todo shows your open action items, /done 2 ticks one off."
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


LINK_PATTERN = r"https?://\S*(instagram\.com|facebook\.com|fb\.watch)\S*"


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

    status = await msg.reply_text("Got the link ⏳ Downloading and processing...")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video_path = await asyncio.to_thread(processor.download_reel, url, Path(tmp))
            note_path, data = await asyncio.to_thread(processor.process_video, video_path, url)
    except Exception as exc:
        await status.edit_text(
            f"❌ Something went wrong: {exc}\n\n"
            "If it's a login/cookies error, see COOKIES_FILE in .env, "
            "or send me the video file instead."
        )
        return

    await status.edit_text(format_reply(data, note_path))


def actions_text() -> str:
    actions = processor.open_actions()
    if not actions:
        return "🎉 No open action items."
    lines = [f"You have {len(actions)} open action items:"]
    current_title = None
    for n, a in enumerate(actions, start=1):
        if a["title"] != current_title:  # group under each reel's title
            current_title = a["title"]
            lines += ["", f"📌 {current_title}"]
        lines.append(f"{n}. ☐ {a['action']}")
    lines += ["", "Tick off with /done 2  (or several: /done 1 3 4)"]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n...\n\nList too long, tick some off with /done first."
    return text


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_allowed(update):
        await update.message.reply_text(actions_text())


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done 2  or  /done 1 3 4  ticks off actions by their /todo number."""
    if not is_allowed(update):
        return
    numbers = [int(x) for x in re.findall(r"\d+", " ".join(context.args or []))]
    if not numbers:
        await update.message.reply_text("Usage: /done 2  (numbers come from /todo)")
        return
    ticked = processor.complete_actions(numbers)
    if not ticked:
        await update.message.reply_text("No matching numbers. Send /todo to see the list.")
        return
    remaining = len(processor.open_actions())
    reply = ["✅ Done:", *[f"• {t}" for t in ticked], "",
             f"{remaining} open items left. Numbers have changed, so send /todo again "
             "before your next /done."]
    await update.message.reply_text("\n".join(reply))


async def weekly_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=context.job.chat_id, text="📅 Weekly review\n\n" + actions_text()
    )


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(LINK_PATTERN), handle_link))

    if ALLOWED_USER_ID:
        # Every Sunday at 9:00 am (in python-telegram-bot v20+, 0 = Sunday)
        app.job_queue.run_daily(
            weekly_digest,
            time=datetime.time(9, 0, tzinfo=TIMEZONE),
            days=(0,),
            chat_id=int(ALLOWED_USER_ID),
        )

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
