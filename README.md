# Reel Notes 📝

A personal Telegram bot that turns Instagram, Facebook, YouTube Shorts, TikTok, Threads and X videos (motivation, tech, programming) into notes with action items, so the useful stuff from reels doesn't get lost.

Send the bot a **reel link** or a **reel video**, and about a minute later you get back:

- a title, category and short summary
- key points
- resources (GitHub repos, tools, links), with a GitHub search link for anything without a URL
- action items you can tick off

Everything runs **free and locally** on your own computer. No paid APIs.

## How it works

```
Reel link ──► yt-dlp downloads the video ─┐
Reel video ───────────────────────────────┤
                                          ▼
              faster-whisper  ──► transcript of what is said
              ffmpeg + Tesseract ──► text shown on screen (repo names, URLs)
                                          ▼
              Ollama (local AI) ──► summary, key points, resources, action items
                                          ▼
              Markdown note saved in notes/  +  reply in Telegram
```

| Part | What it does |
|---|---|
| `bot.py` | Telegram bot: receives links/videos, commands, weekly reminder |
| `processor.py` | Download, transcribe, OCR, summarise, save notes, track actions |
| `notes/` | One `.md` file per reel (not committed to Git) |

## Bot commands

| Command | What it does |
|---|---|
| *(send a reel link)* | Downloads the reel and makes a note. Works with Instagram, Facebook, YouTube Shorts, YouTube (videos up to 10 minutes), TikTok, Threads and X (video posts only, see below) |
| *(send a reel video)* | Makes a note from the video (add the link as caption to enable the duplicate check) |
| *(send a carousel post link)* | Instagram posts with several slides (`instagram.com/p/...`): every slide (up to 10) is processed into **one** combined note: videos are transcribed and read, photos are read with OCR. Photo-only posts work too |
| `/start` | Shows your Telegram user ID |
| `/todo` | Open actions in pages of 10 (⬅️ ➡️ buttons), grouped by priority and reel. `/todo high` shows only 🔥 ones, `/todo 2` opens page 2 |
| `/done 2` | Ticks off item 2 (or several: `/done 1 3 4`) |
| `/high 3`, `/low 3`, `/normal 3` | Change an action's priority. `/todo` lists 🔥 high first, then normal, then 🔽 low |
| `/remind 3 friday` | Reminds you about `/todo` item 3. Understands `tomorrow 5pm`, `monday`, `in 2 hours`, `in 3 days`, `next week`, `20/11 9am`, `25 dec`. No time means 9:00 am. The reminder has ✅ Done / ⏭ Skip / ⏰ Tomorrow buttons, and a reminder missed while the PC was off is sent when the bot starts again |
| `/reminders`, `/unremind 1` | List upcoming reminders, or cancel one. Actions with a reminder show 🔔 in `/todo` |
| `/skip 3` | Drops an action you've decided not to do. It's kept in the note as `- [-]` but hidden from `/todo` |
| *(type a normal message)* | **Chat mode**: talk to the bot about your notes, e.g. *"what did I save about Claude?"*, then follow-ups like *"how do I install it?"*. It uses only facts from your notes (with the notes listed under the reply) and remembers the last 6 back-and-forth messages. Runs on your local Ollama model, free and private |
| `/plan 2` | Turns note 2 (from `/notes`, `/search`, `/tag` or a chat reply) into a **ready-to-paste prompt for Claude** in ART format (Act as / Request / Terms: Instructions, Constraints, Output). Built only from the note: open actions, key points, links and claims to verify. Add your own goal: `/plan 2 I want to use it in my bot` |
| `/remember` | One older note's key quote or key point, to refresh your memory (🔁 for another) |
| `/month`, `/month last` | Your learning this month so far, or last month: topics, reels saved, actions finished |
| `/newchat` | Forget the current conversation and start fresh |
| `/ask your question` | Answers from **your saved notes only**, e.g. `/ask which tools help Claude remember things?`. Shows which notes it used, so you can check. If nothing matches, it says so instead of guessing |
| `/search strix` | Finds every note that mentions it. Several words must all match: `/search claude memory` |
| `/notes` | Lists your 10 newest notes |
| `/note 1` | Opens note 1 from your last `/search`, `/notes` or `/tag` (without the transcript) |
| `/tags` | Lists all your tags with how many notes use each |
| `/tag python` | Shows notes tagged `#python`. `/tag ai` also matches `#ai-tools` |
| `/tag` | On its own: shows buttons for your 12 most-used tags; tap one to see its notes |
| `/retag` | Adds tags to older notes saved before tags existed |
| `/renametag claudie claude` | Renames a tag in every note (merges it if the new tag is already used) |
| `/nudge` | One action to do right now, with the link, two key points and buttons: ✅ Done, ⏭ Skip, 🔁 Another one, 📖 Open note, 🤖 Get prompt (🤖 actions only) |
| `/prompt 3` | A ready prompt for action 3 of your last `/todo`, to paste into Claude |
| `/cleanup` | Skip junk and extra old actions (asks first). `/undocleanup` puts the last clean-up back |
| `/usage` | How often you used each command (only the names are counted) |
| `/stats` | The last 7 days: reels saved, actions done and skipped, top topics |
| `/file 1` | Sends note 1 (from your last `/notes`, `/search` or `/tag`) as a `.md` file |

**Automatic messages:** every morning at 8:00 a **daily nudge** sends one action, 🔥 high priority first (change the time with `NUDGE_TIME` in `.env`, or set it to `off`). Every Sunday at 9:00 a **weekly review** sends your stats and the open actions. Every Wednesday at 7:00 pm one **older note resurfaces** (`RESURFACE=off` to stop it). On the 1st of each month at 9:30 am you get a **monthly learning summary**. Ticked actions get a date (`✅ 2026-11-13`, or `❌` for skipped), the same format as the Obsidian Tasks plugin.

**Action priorities.** The AI marks each action 🔥 high (specific, quick, clearly useful), normal, or 🔽 low (optional, vague, or "follow the creator"). The icon is saved in the note (`- [ ] 🔥 ...`), and you can change it with `/high`, `/normal` and `/low`.

**Claim check.** A `⚠️ Claims to check` section flags things not to take at face value: big numbers ("7 billion free tokens"), "free/official/secret" claims, statistics with no source, and posts that mainly sell a product, course or "DM me" offer. The bot can't check facts by itself; it tells you what to verify.

**Motivation reels get their own style.** On top of the summary and key points, the note has:

- 💬 **Key quote**: the strongest sentence, word for word. If the AI reworded it, it's marked *(paraphrased)*, because the bot checks the quote against the transcript.
- 💡 **Main lesson**: one plain sentence.
- 🔁 **Habit to try**: one small, specific habit. It appears in `/todo`, so you can tick it off with `/done`. If the AI also gave an action that says the same thing, you get **one** to-do, not two: the habit, with the priority of that action (shown as `🔥 🧠`).

**The post caption is read too**, because creators often put links and details there. It's given to the AI, saved in the note under `## Post caption`, and links in it count as real (not invented).

**GitHub repos are looked up automatically** for tech and programming reels. A tool named in the reel (e.g. "Claude mem") is matched to its real repo, using a repo shown on screen first and then GitHub search. Only an exact name match is accepted, so the bot doesn't link the wrong repo. The note gets the real link, ⭐ stars and the repo's description:

```
- Claude mem https://github.com/thedotmack/claude-mem  ⭐ 115.6k — Persistent Context Across Sessions...
```

If there's no confident match, the note keeps a GitHub search link. This uses the free GitHub API without a login. Optionally set `GITHUB_TOKEN` in `.env` for higher rate limits.

Every new note gets 3–6 topic tags (e.g. `#python #ai-tools #github`). The AI is shown your existing tags so it reuses them, which keeps topics grouped together.

The bot also sends a **weekly review** of open action items every Sunday at 9:00 am, and it skips reels that already have a note.

## X (Twitter) links

Send a link to a post on `x.com` or `twitter.com` (also `mobile.twitter.com`).

- The bot uses **yt-dlp**, like for the other sites. A post with a video makes a note. A post with several videos makes one combined note.
- **No login and no cookies.** The bot never sends your cookies file to X. So posts that need a login (age-limited or private posts) cannot be saved.
- **Video posts only.** A post with only text or pictures cannot be saved from a link.
- If the video cannot be saved, the bot replies: *I could not get this X video. Please save the video and send me the file.* and a short *Reason:* line with yt-dlp's own error. Then send the video file to the bot as normal. The full error is written to `bot.log`: search for `x: yt-dlp failed`.

**When any link fails to download**, the bot shows yt-dlp's real error, for example *Reason: [youtube] abc: Private video*. The error is cleaned first: no colour codes, no `ERROR:`, no links, no file paths, no sentence about cookies, passwords or tokens, and at most about 300 characters. The full error is in `bot.log` (search for `yt-dlp failed`). A new yt-dlp often fixes it: send `/update`.
- The same post on `x.com` and `twitter.com` counts as one note (the duplicate check).
- Links that other sites make for X (for example `fixupx.com` or `vxtwitter.com`) are not accepted. Use the normal `x.com` link.
- X changes often. If it stops working, update yt-dlp with `/update` and restart the bot.

## Threads links

Send a link to a Threads post (`threads.com` or `threads.net`). These work: a normal post link, a link from the app's **Share** button (`threads.com/share/...`), and a link that ends in `/media`.

- yt-dlp does not support Threads, so the bot reads the **public page** once, finds the video address in it, downloads the video and makes the note as usual.
- No login and no cookies. The bot sends **one request** to the Threads page, then downloads the video file.
- **Video posts only.** A post with only text or only pictures cannot be saved from a link. The bot says so and suggests a screenshot. Screenshots work: it reads the text with OCR.
- A link to a profile (not one post) is not accepted.
- If the video cannot be found, the bot replies: *I could not get this Threads video. Please save the video and send me the file.* Then send the video file to the bot as normal. The real reason is written to `bot.log` (search for `threads:`). For a page with no video, the log line says what the page looked like (a login page, an empty page, or a new format), without copying the post.
- Threads can change its page at any time, so this may stop working one day. Private posts and posts that need a login will not work.
- The same post on `threads.com` and `threads.net` counts as one note (the duplicate check). A Share-button link is not matched to the post, so the same post can be saved twice if you send it by two different links.

## Screenshots → notes

Send a screenshot (or several as one album) to the bot. It reads the text (OCR) and saves a normal note: summary, key points, resources and actions.
- An album of up to 10 screenshots becomes **one** note.
- Add a caption to give context. If the caption has the reel link, it becomes the note's Source (and duplicates are caught).
- For the sharpest text, send the image **as a file** (📎 → File). Telegram makes normal photos smaller.

## Creator info and link checks

- Every note has a **Creator** line (name, @handle and profile link) when the site gives it.
- A **From the creator** section keeps the creator's own offers ("comment X", "link in bio", "DM me"). Use it if a link in the note is wrong or missing. These offers also stay as low-priority actions, and `/plan` lists them as a backup.
- For every GitHub link the bot shows stars, last update and licence, e.g. `⭐ 1.2k · updated Mar 2025 · MIT`. It warns you when:
  - ⚠️ the repo is **archived** (no longer maintained)
  - ⚠️ there were **no updates for over a year**
  - ⚠️ the repo was **not found** (the link may be wrong)

## Action plans for Claude

- `/plan 2` turns note 2 (from `/notes`, `/search` or `/tag`) into a ready-made prompt (ART format) to paste into Claude.
- `/plan 1 3 5` makes **one combined plan** from up to 5 notes. Claude merges overlapping steps and says which video (V1, V2...) each step comes from.
- `/plan #python` uses your newest notes with that tag (up to 5).
- Add your own goal at the end: `/plan 1 3 get a data job`.
- Long plans come as a `.txt` file. Attach it in Claude with 📎.

## One action per reel, with a type

- A new note keeps **one main action** (the best one). A short list gets done.
- Extra ideas go into a plain **Other ideas** list in the note. They are not on `/todo`.
- "Comment X to get the link", "DM me" and "link in bio" are **not** actions. They are saved under **From the creator** in case a link is missing.
- Every action has a type:
  - 🤖 an AI (Claude, ChatGPT...) can do it or help with it
  - 🧠 a habit or mindset thing you do yourself
  - 🔗 look something up, open a site, install or set up a tool
- `/todo` shows the icon and the counts. Filter with `/todo ai`, `/todo habit` or `/todo lookup` (you can add `high` too, like `/todo ai high`).
- Older notes have no saved type, so the bot guesses it from the words (no AI needed).

## Clean up old actions

- `/cleanup` shows what it would skip and asks first. Tap **Yes** to do it.
- It skips: (1) old "comment X / DM me" actions, (2) the extra actions in a note that has more than one, and (3) a "Habit to try" that says the same thing as an action in the same note (older notes have both, so the same idea is in `/todo` twice). It keeps the best action per note, anything with a due date, and every other "Habit to try". For (3) it keeps the action and skips the habit, unless only the habit has a due date.
- "The same thing" is decided by shared words, without AI. Words about *when* ("every morning") are ignored.
- `/undocleanup` puts the last clean-up back.
- Skipped actions stay in the note, marked ❌. Nothing is deleted.
- The Sunday review suggests `/cleanup` when you have more than 30 open actions.

## Help to actually do an action

- **The nudge has what you need:** the action, its main link (a real link first, otherwise the saved reel), two key points, and an **📖 Open note** button.
- **🤖 Get prompt:** for an action the AI can help with, one tap gives a ready prompt (ART format, built only from the note, no AI call). `/prompt 3` does the same for action 3 of your last `/todo`.
- **Save one, do one:** when you save a new reel and you have ticked **nothing in the last 7 days**, the bot also shows ONE older action with ✅ Done / ❌ Drop it. It never blocks the new note, and it asks at most once a day.
- **Undo:** `/undocleanup` puts back the actions the last `/cleanup` skipped (only the last one is remembered).
- **Usage:** `/usage` shows how many times you used each command, so unused ones can be removed by fact. Only the command name is counted, never your message text. The counts are in `bot_state.json` (not in git).
- **Search:** "what did I save about AI and uv?" now finds short topic words like AI and uv, and ignores words like "did" and "save".

## Done, with one line of what you learned

- When you tick **one** action (the **✅ Done** button on a nudge or reminder, or `/done 3`), the bot asks: *What did you learn? Reply to this message with one line.*
- Your reply is saved in the note, right under the action, like this: `  - 💡 Learned: the docs have a quick start page`. It is not a to-do. Reply a second time to change it.
- Reply **skip** if there is nothing to say, or just ignore the question. Nothing is lost.
- Only a **reply** to the question counts. If you type a normal message instead, it is a normal chat message. The bot remembers the last 20 questions (until it restarts).
- `/done 1 3 4` and `/skip` do not ask.
- `/month` shows what you learned (the last 5). Chat and `/ask` can find it, and `/search` too, because it is saved in the note.
- To turn the question off, set `ASK_LEARNING=off` in `.env`.

## Numbers in /todo

- `/done 3`, `/skip 3`, `/high 3`, `/due 3 friday` and `/remind 3 friday` use the numbers from the **last `/todo` you saw**.
- The numbers stay the same until you send `/todo` again, even if a new note arrives.

## When the PC was off

- The daily nudge, Sunday review, Wednesday "remember this?" and monthly summary are sent **when the PC is back** if their time was missed.
- A missed daily nudge is sent only on the same day. yt-dlp is also checked once a day after start.
- The bot remembers what it sent in `sent_jobs.json` (not committed to Git).

## How long a note takes

- Each new note ends with a line like `⏱ 88s (download 4 · listen 21 · read screen 48 · AI 14)`.
- The same numbers are in `bot.log` (search for `timing:`). "listen" is Whisper, "read screen" is OCR.

## Due dates

- `/due 3 friday` gives action 3 a due date. Also: `tomorrow`, `next week`, `in 5 days`, `20/11`, `2026-11-20`. Several at once: `/due 2 5 friday`.
- `/due 3 off` removes it. `/due` on its own lists every action with a date.
- Actions that are overdue or due in the next 2 days go to the top of `/todo` under **⏰ DUE SOON**.
- The morning nudge picks an overdue or due-today action first. The Sunday review lists overdue actions and what's due this week.
- In the note it looks like `- [ ] 🔥 Learn Pandas 📅 2026-11-20` (the Obsidian Tasks format).

## Fixing and checking the bot

- `/redo` makes your newest note again (e.g. after changing the AI model). `/redo llm wiki` picks a note by its title; `/notes` then `/redo 2` works too. The bot asks first. The old note moves to an `old` folder inside your notes folder, so nothing is lost.
- `/redo fast` (or `/redo fast 2`, `/redo fast llm wiki`) makes the note again from the text **saved in the note**: no download, no listening, no screen reading. Only the AI runs, so it takes seconds. Use it to bring an older note to the new format, or to try another AI model. It also works for notes made from screenshots or a video file.
  - The note keeps its **date** and your **tags**.
  - Your **done and skipped** actions and your 💡 learnings are kept. An action you already did or skipped is not opened again.
  - Open actions are made new by the AI. Their due dates and reminders are not kept.
  - A very old note without saved text cannot be redone fast. Then use `/redo` (download again).
- `/health` checks everything the bot needs: Ollama and the model, ffmpeg, Tesseract, yt-dlp, the notes folder (Google Drive) and free disk space.
- yt-dlp updates itself every night at 03:30 (`YTDLP_UPDATE_TIME` in `.env`, or `off`). You only get a message if it updated or failed. `/update` does it now. After an update, restart the bot from the tray icon.

## If Google Drive is missing

Your notes folder can be on Google Drive (for example `G:\My Drive\Reel Notes`). If Google Drive is not running, that drive does not exist, and Windows shows only C:, D: and so on in **This PC**. Then the bot cannot save into it.

**What the bot does now.** A note is **never lost**:

- The note is saved on the PC, in `notes\pending` inside the project folder (change it with `NOTES_PENDING_DIR` in `.env`).
- The reply says so: *Your notes folder is not ready... This note is saved on this PC and moves there when it is back.*
- When the notes folder is back, the bot moves the notes by itself (it checks about every 5 minutes) and sends you: *Your notes folder is back. Moved N notes from this PC to it.* A note is copied, checked, and only then deleted from the PC. An old note is never overwritten.
- Until then, `/todo`, `/notes` and similar commands say the folder is missing and how many notes are waiting. `/health` shows the waiting notes too.
- The real error is written to `bot.log` (search for `notes:`).

**How to bring Google Drive back** (the menu words can differ a little in your version):

1. Look for the Google Drive icon near the clock. It may be hidden under the **^** arrow. If it is not there, open **Google Drive** from the Start menu.
2. If it asks you to sign in, sign in with the same Google account.
3. Wait a minute, then open **This PC**. You should see a Google Drive drive (for example `G:`). If it has a different letter, put the new path in `NOTES_DIR` in `.env` and restart the bot.
4. To start Google Drive when Windows starts: open the Google Drive icon, then the settings (gear) and **Preferences**, and look for the option to launch Google Drive at startup.
5. Still missing? Restart the PC. If it is still missing, reinstall **Google Drive for desktop**. Your notes are safe: they are also in your Google Drive online.

## Notes on your phone

**Easiest:** use the bot itself. `/notes` then `/note 3` shows a note nicely in Telegram.

**As a file:** send `/file 1` to get a note as a `.md` file in Telegram (after `/notes`, `/search` or `/tag`, the number picks from that list). Open it on your phone, or save or share it.

**All notes, always in sync:** keep the `notes` folder inside a cloud folder that syncs to your phone.

1. Stop the bot (tray icon → **Quit**).
2. Move the `notes` folder into your cloud folder, e.g. `C:\Users\<you>\OneDrive\ReelNotes` (OneDrive) or `G:\My Drive\ReelNotes` (Google Drive for desktop).
3. In `.env`, set the full path:
   ```
   NOTES_DIR=C:\Users\<you>\OneDrive\ReelNotes
   ```
4. Start the bot again. New notes are saved there, and `/todo`, `/search` and the rest keep working.
5. On your phone, open the **OneDrive** or **Google Drive** app. Phones often can't preview `.md` files: use **Open in / Open with** and a Markdown app (Android: **Markor**, free; iPhone: any "Markdown viewer" app) to see the headings and checkboxes.

Edit notes on your phone carefully. Ticking a box (`- [ ]` → `- [x]`) is fine, but keep the `## Action items` heading, because the bot uses it to find your actions.

## Requirements

- Windows, macOS or Linux
- Python 3.12 (3.14 is too new for some dependencies)
- [ffmpeg](https://ffmpeg.org/)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)
- [Ollama](https://ollama.com/) with a model, e.g. `qwen3:8b`
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

A GPU helps (Ollama uses it automatically) but is not required.

## Setup (Windows)

```powershell
# 1. Tools
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install UB-Mannheim.TesseractOCR
winget install Ollama.Ollama
ollama pull qwen3:8b

# 2. Project
cd "C:\path\to\reel-notes"
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Settings
copy .env.example .env
notepad .env        # add TELEGRAM_BOT_TOKEN and TESSERACT_CMD
```

## Run

```powershell
.venv\Scripts\activate
python bot.py
```

The first time, send `/start` to the bot, put your user ID in `.env` as `ALLOWED_USER_ID`, and restart. After that, only you can use the bot.

### Run in the background with a tray icon (Windows)

`tray.py` runs the bot in the background and shows a coloured **R** icon next to the clock: green = running, yellow = starting, red = stopped. Right-click it to open notes, open the log, restart, stop or quit. It restarts the bot automatically if it crashes, and output goes to `bot.log`.

**Create a shortcut** (works with Windows Smart App Control, unlike `.bat`/`.vbs` launchers):

1. Desktop → right-click → **New → Shortcut**, and use this target:
   ```
   "C:\path\to\reel-notes\.venv\Scripts\pythonw.exe" "C:\path\to\reel-notes\tray.py"
   ```
2. Name it `Reel Notes bot`, then in **Properties → Start in**, enter `"C:\path\to\reel-notes"`.
3. Double-click to test. To start it at login, move the shortcut to the Startup folder (`Win+R` → `shell:startup`).

`pythonw.exe` runs Python without a console window. To stop everything, use the tray icon (**Quit**) or `stop_bot.bat`.

The bot only works while it is running. Messages sent while it's off wait on Telegram for up to 24 hours and are processed when it starts again.

## Settings (`.env`)

| Setting | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | From BotFather. Keep secret |
| `ALLOWED_USER_ID` | — | Your Telegram ID, so only you can use the bot |
| `OLLAMA_MODEL` | `qwen3:8b` | Best free model for 8 GB graphics cards. `qwen2.5:7b` also works |
| `WHISPER_MODEL` | `small` | `medium` is more accurate but slower |
| `TESSERACT_CMD` | — | Windows: `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| `NOTES_DIR` | `notes` | Where notes are saved |
| `NOTES_PENDING_DIR` | `notes\pending` | Where new notes wait if `NOTES_DIR` is missing (see above) |
| `TIMEZONE` | `UTC` | Your time zone, e.g. `Europe/London`. Used for the nudge and review times |
| `FRAME_EVERY_SECONDS` | `2` | How often a frame is read for on-screen text |
| `MAX_MINUTES` | `10` | Longest video accepted (for YouTube links) |
| `ASK_LEARNING` | `on` | Ask "What did you learn?" after a Done; `off` to disable |
| `RESURFACE` | `on` | Weekly "remember this?" message; `off` to disable |
| `NUDGE_TIME` | `08:00` | Time for the daily nudge (24-hour), or `off` |
| `COOKIES_FILE` | — | Only if Instagram/Facebook downloads need a login |
| `GITHUB_TOKEN` | — | Optional. Higher GitHub API limits for repo lookups |

## Known limits

- Telegram bots can only download videos up to 20 MB (links have no limit).
- On-screen text from busy backgrounds or stylised captions can be noisy. The AI usually fixes obvious typos.
- Instagram may sometimes block downloads without a logged-in cookies file.
- Threads: video posts only, and only if the public page shows the video without a login.
- X: video posts only, and no login (so no age-limited or private posts).
- Claims are flagged, not fact-checked: the `⚠️ Claims to check` section tells you what to verify yourself.
- Carousel posts: up to 10 slides. Photo slides are read with OCR only, so text in a photo is captured but the picture itself isn't described.
- For personal use only. Downloading reels may go against Meta's terms of service.

## Troubleshooting

| Problem | Fix |
|---|---|
| `open() got an unexpected keyword argument 'metadata_errors'` | `pip install "av>=12,<14"` |
| Hugging Face symlink warnings | Harmless. Add `HF_HUB_DISABLE_SYMLINKS_WARNING=1` to `.env` |
| `tesseract not found` | Set `TESSERACT_CMD` in `.env` |
| `The system cannot find the path specified: 'G:\'` or "I can't see your notes folder" | Google Drive is not running. See *If Google Drive is missing* above. New notes are kept on the PC until it is back |
| Bot stops right after "Bot is running" | Check `.env` exists and the token is correct |
| `.bat` / `.vbs` file blocked by Windows ("Smart App Control has blocked...") | See below |
| `NetworkError: Bad Gateway` / `TimedOut` in `bot.log` | Telegram's servers had a short outage. Nothing to fix: the bot retries automatically. If a reel got no reply, send the link again |
| Two bots running → Telegram "Conflict" error | Quit the tray icon or run `stop_bot.bat`, then start only one |
| Downloaded `.env.example` / `.gitignore` lost the dot | `Move-Item env.example .env.example -Force` (same for `gitignore`) |

### Windows Smart App Control blocking scripts

When you download a file, Windows attaches a hidden label to it called the **Mark of the Web**, stored in a hidden part of the file named `Zone.Identifier`. Smart App Control blocks downloaded script files such as `.bat`, `.cmd` and `.vbs` that carry this label.

Check whether a file has the label:

```powershell
Get-Content "C:\path\to\reel-notes\stop_bot.bat" -Stream Zone.Identifier
```

`ZoneId=3` means the file came from the internet, and `HostUrl` shows where it was downloaded from.

**Fix for your own, trusted files:** remove the label.

```powershell
Unblock-File "C:\path\to\reel-notes\stop_bot.bat"
```

(This is the same as ticking **Unblock** in the file's Properties.)

- Only unblock files you have read and trust. The label protects you from malware.
- **Don't turn off Smart App Control.** Once it's off, Windows can't turn it back on without a reset.
- Shortcuts you create yourself never get the label, and `pythonw.exe` is a signed program, so the tray shortcut above is never blocked.

## Development

Run the tests (no Whisper, Ollama, Tesseract or internet needed):

```
pip install -r requirements-dev.txt
python -m pytest
```
