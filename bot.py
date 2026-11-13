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

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
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
        "Send me a reel link, a carousel post link or a video and I'll turn it into a note.\n\n"
        "Actions: /todo  /done 2  /skip 3  /high 3  /low 3  /nudge  /stats\n"
        "Notes: /notes  /note 1  /file 1  /search strix\n"
        "Tags: /tags  /tag python  /renametag old new  /retag\n\n"
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
    try:
        with tempfile.TemporaryDirectory() as tmp:
            videos, caption = await asyncio.to_thread(processor.download_media, url, Path(tmp))
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
                processor.process_videos, videos, url, caption)
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
    headings = {"high": "🔥 HIGH PRIORITY", "normal": "▫️ NORMAL", "low": "🔽 LOW"}
    lines = [f"You have {len(actions)} open action items:"]
    current_priority, current_title = None, None
    for n, a in enumerate(actions, start=1):
        if a["priority"] != current_priority:   # priority section
            current_priority, current_title = a["priority"], None
            lines += ["", f"━━ {headings[a['priority']]} ━━"]
        if a["title"] != current_title:         # reel title inside the section
            current_title = a["title"]
            lines += [f"📌 {current_title}"]
        lines.append(f"{n}. ☐ {a['action']}")
    lines += ["", "Tick off with /done 2  (or several: /done 1 3 4)",
              "Not doing one? /skip 3   Change priority: /high 3  /low 3  /normal 3"]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3900] + "\n...\n\nList too long, tick some off with /done first."
    return text


async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_allowed(update):
        await update.message.reply_text(actions_text())


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
    left = len(processor.open_actions())
    verb = "✅ Done" if what == "done" else "⏭ Skipped"
    await query.edit_message_text(f"{verb}: {action['action']}\n\n{left} open items left. "
                                  "Want another? /nudge")


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


def main() -> None:
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
    app.add_handler(CommandHandler("nudge", nudge))
    app.add_handler(CommandHandler("tags", tags))
    app.add_handler(CommandHandler("retag", retag))
    app.add_handler(CommandHandler("renametag", renametag))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("file", send_file))
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

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
