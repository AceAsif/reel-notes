"""Telegram bot: send it a reel video, get back a note with action items."""
import asyncio
import datetime
import os
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
    parts = [f"📝 {data['title']}  [{data['category']}]", "", data["summary"]]
    if data["key_points"]:
        parts += ["", "Key points:", *[f"• {p}" for p in data["key_points"]]]
    if data["resources"]:
        parts += ["", "Resources:"]
        parts += [f"• {processor.resource_line(r)}" for r in data["resources"]]
    if data["action_items"]:
        parts += ["", "✅ Action items:", *[f"☐ {a}" for a in data["action_items"]]]
    parts += ["", f"Saved: {note_path.name}"]
    return "\n".join(parts)[:4000]  # Telegram message limit is 4096


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"Hi! Your Telegram user ID is {update.effective_user.id}\n"
        "Put it in .env as ALLOWED_USER_ID, then restart me.\n\n"
        "Send me a reel video (add the reel link as the caption if you like) "
        "and I'll turn it into a note.\n/todo shows your open action items."
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update):
        return
    msg = update.message
    media = msg.video or msg.document
    if media.file_size and media.file_size > MAX_BYTES:
        await msg.reply_text("That file is over 20 MB, which is Telegram's limit for bots.")
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


def actions_text() -> str:
    actions = processor.open_actions()
    if not actions:
        return "🎉 No open action items."
    lines = [f"You have {len(actions)} open action items:", ""]
    for title, action in actions[:50]:
        lines.append(f"☐ {action}  ({title})")
    lines += ["", "Tick them off by changing '- [ ]' to '- [x]' in the note files."]
    return "\n".join(lines)[:4000]


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_allowed(update):
        await update.message.reply_text(actions_text())


async def weekly_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=context.job.chat_id, text="📅 Weekly review\n\n" + actions_text()
    )


def main() -> None:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

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
