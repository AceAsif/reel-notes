# Reel Notes: New Feature Ideas

Written on 2026-11-16, after batch 3 (`main` at "Just removed whitespace").
Read: `docs/HANDOVER.md`, `docs/REVIEW_BY_FABLE.md`, `PROGRESS.md`, `README.md`,
`processor.py`, `bot.py`. Tests: 205 pass. No code was changed. Only this file was added.

Not read: `.env`, `notes/`, `bot.log`, `cookies.txt`, `reminders.json`.
So I do not know what your notes say or which commands you really use. Where I guess, I say so.

---

## 1. The real problem

You have about 57 open actions and 0 done.

Batches 2 and 3 made the list **shorter and cleaner**. That was needed. But a clean list
does not make you start. Today the bot helps you *manage* actions. It does little to help
you *start* one. I see three gaps in the code:

1. **The nudge is too thin.** `nudge_message` in `bot.py` shows only the action text and
   the reel title. To do the action you must still open the note, find the link, and think
   about the first step. That is too much work for a busy morning.
2. **Saving is free, doing is not.** You can send 10 reels and the bot never asks about the
   old ones. The only moment you are sure to be in Telegram with the PC on is when you
   **send a reel**. The bot does not use that moment.
3. **The action types do nothing yet.** 🤖 means "AI can do it", but no button gives you
   the prompt. The icon is only a label.

Every idea below is free and local. None needs a login, cookies, or an always-on machine.
All bot messages stay in short, simple English.

---

## 2. Top 3 (build these first)

### 1. Save one, do one 🟢 new

- **What it does:** When you send a reel and you have done 0 actions in the last 7 days,
  the bot adds one line and two buttons under the new note: your oldest 🔥 action, with
  **✅ Done** and **❌ Drop it**. It still saves the new reel. It never blocks you.
- **Why it helps:** It uses the one moment you are surely in Telegram and the PC is on.
  It links saving to doing. A "Drop it" tap is also a good result: the list gets honest.
- **Why top 3:** Smallest change with the biggest effect on "0 done". It reuses the nudge
  buttons that already work (`nudge:done`, `nudge:skip`).
- **Files:** `bot.py` (`send_note_reply`), `processor.py` (small helper using
  `weekly_stats` and `pick_nudge`), tests.

### 2. A nudge you can act on 🟡 new

- **What it does:** The daily nudge shows the action **plus** what you need to do it: the
  main link from the note, two key points, and one "first step" that takes under 5
  minutes. It adds an **📖 Open note** button.
- **Why it helps:** Today you must send `/notes`, find the note, then `/note 3`. With this
  you can start from one message. A small first step is much easier to begin.
- **Why top 3:** The nudge is the main "do it" message, and it arrives every day you turn
  the PC on. Making it complete is worth more than any new command.
- **Honest note:** The link and key points come straight from the note, so they are safe.
  The "first step" needs one call to qwen3:8b. I am not sure it will always be good. Build
  the safe part first. Add the first step after you see it work on 10 real actions.
- **Files:** `bot.py` (`nudge_message`, a new button handler), `processor.py`
  (`note_sections` already reads the parts; one new prompt), tests.

### 3. Make 🤖 do something: "Get the prompt" 🟢 new

- **What it does:** Every 🤖 action gets a **🤖 Get prompt** button in the nudge, and
  `/prompt 3` works from `/todo`. The bot sends a ready prompt for that ONE action, built
  from the note, to paste into Claude.
- **Why it helps:** It turns a to-do into a 2-minute job: tap, copy, paste. `/plan`
  already builds prompts for a whole note, but you need the note number and it covers
  everything. This is one tap for one action.
- **Why top 3:** Batch 3 added the types. This is the feature that makes the 🤖 type
  useful. It needs no AI call, so nothing is invented.
- **Files:** `processor.py` (`make_plan` and `plan_parts`: add a "one action" mode),
  `bot.py` (button and `/prompt`), tests.

---

## 3. All ideas, ranked

Effort: 🟢 small, 🟡 medium, 🔴 big.
"In list" = already in the to-do list in `docs/HANDOVER.md` section 10.

| # | Idea | Effort | New or in list | Files |
|---|---|---|---|---|
| 1 | Save one, do one | 🟢 | new | `bot.py`, `processor.py` |
| 2 | A nudge you can act on | 🟡 | new | `bot.py`, `processor.py` |
| 3 | 🤖 Get the prompt | 🟢 | new | `processor.py`, `bot.py` |
| 4 | Review my old notes (`/review`) | 🟡 | new | `bot.py`, `processor.py` |
| 5 | Bring back an "Other idea" | 🟢 | new | `bot.py`, `processor.py` |
| 6 | Pick 3 for this week | 🟡 | new | `bot.py`, `processor.py` |
| 7 | Keep or drop after 3 nudges | 🟢 | new | `bot.py`, `processor.py` |
| 8 | Done, with one line of what I learned | 🟢 | in list | `bot.py`, `processor.py` |
| 9 | 7-day habit check for 🧠 | 🟡 | new | `bot.py`, `processor.py` |
| 10 | Fast redo from the saved text | 🟡 | new | `processor.py`, `bot.py` |
| 11 | My tools list (`/tools`) | 🟢 | new | `processor.py`, `bot.py` |
| 12 | "You already saved this topic" | 🟢 | in list (part of "merge duplicates") | `processor.py`, `bot.py` |
| 13 | Topic cheat sheet (`/topic claude`) | 🟡 | in list ("topic summary") | `processor.py`, `bot.py` |
| 14 | Search that finds "AI" and "uv" | 🟢 | new (bug B14 from my review) | `processor.py` |
| 15 | Add my own action (`/add`) | 🟢 | in list (`/addnote`) | `bot.py`, `processor.py` |
| 16 | Count which commands I use | 🟢 | new | `bot.py`, `.gitignore` |
| 17 | Quiz from my notes | 🟡 | in list | `processor.py`, `bot.py` |
| 18 | Voice note to action | 🟡 | in list | `bot.py`, `processor.py` |

Ideas **4, 10, 11 and 13** use the notes you already have (about 50), not only new reels.

### 4. Review my old notes (`/review`) 🟡 new — uses old notes

- **What it does:** The bot shows one old note at a time: title, summary and its main
  action. You tap **👍 Keep action**, **💡 Useful, no action**, **🗑 Not useful** (the note
  moves to the `old` folder), or **Stop**. It gives you 5 notes per round.
- **Why it helps:** Your 50 notes were made with older prompts, with 3 to 6 actions each.
  `/cleanup` picked one per note by a rule. Here **you** decide in about 5 seconds per
  note. After 10 rounds your whole list is one you chose.
- **Files:** `bot.py` (command and buttons), `processor.py` (`archive_note` exists; a
  small "reviewed" list in a private JSON file, added to `.gitignore`), tests.

### 5. Bring back an "Other idea" 🟢 new

- **What it does:** `/note 3` shows a **➕ To-do** button for each line under "Other
  ideas". One tap moves it into "Action items".
- **Why it helps:** Since batch 3, extra actions are plain bullets. You only use Telegram,
  so today you cannot bring one back without editing the file. See the risk in section 5.
- **Files:** `bot.py` (`note`, one button handler), `processor.py` (move one line), tests.

### 6. Pick 3 for this week 🟡 new

- **What it does:** The Sunday review shows your top 6 actions as buttons. You tap up to 3.
  Those are "this week". The daily nudge only uses them, and `/todo` shows them first.
- **Why it helps:** 57 actions is a pile. 3 is a plan. You choose once a week, not every day.
- **Honest note:** If the PC is off on Sunday, the review comes late (catch-up handles
  this). The picks should stay until you pick again.
- **Files:** `bot.py` (`weekly_digest`, buttons, `todo_page`), `processor.py`
  (`pick_nudge`), a private JSON file, tests.

### 7. Keep or drop after 3 nudges 🟢 new

- **What it does:** The bot counts how many times each action was sent as a nudge. After 3
  times with no Done, the nudge asks: **Keep / Drop / Too big**. "Too big" asks the AI for
  a smaller version of the action.
- **Why it helps:** An action you ignored 3 times will not get done by a 4th message. This
  makes you decide, so dead actions leave the list.
- **Files:** `bot.py` (`send_nudge`, buttons), `processor.py` (counter in a private JSON
  file), tests.

### 8. Done, with one line of what I learned 🟢 in list

- **What it does:** After ✅ Done the bot asks: "What did you learn? Reply, or tap Skip."
  Your reply is saved under the action in the note.
- **Why it helps:** It makes a done action useful later in chat and in `/month`. It also
  makes "done" feel like progress, which helps you do the next one.
- **Files:** `bot.py` (after `nudge_button_pressed` and `/done`), `processor.py`
  (`complete_actions`), tests.

### 9. 7-day habit check for 🧠 🟡 new

- **What it does:** When you start a 🧠 habit, the bot asks once a day for 7 days: "Did
  you do it today?" with ✅ / ❌. After 7 days it shows the count and asks Keep or Stop.
- **Why it helps:** A habit is not a one-time tick box. Today a habit sits in `/todo` like
  "install a tool", and "Done" has no clear meaning for it.
- **Honest note:** Only one habit at a time, or it becomes noise. If the PC is off all
  day, that day is simply skipped.
- **Files:** `bot.py` (job through `run_due_jobs`, buttons), `processor.py`, a private
  JSON file, tests.

### 10. Fast redo from the saved text 🟡 new — uses old notes

- **What it does:** `/redo fast 3` builds note 3 again from the transcript, on-screen text
  and caption that are already saved inside the note. It does not download anything.
- **Why it helps:** Your old notes can get the new format (one action, types, simple
  English) in seconds each. It needs **no Instagram login**, and it works even if the reel
  was deleted. `/redo` today downloads the video again and cannot redo screenshots at all.
- **Files:** `processor.py` (read the three sections, call `summarise`, `save_note`,
  `archive_note`), `bot.py` (`redo`), tests.

### 11. My tools list (`/tools`) 🟢 new — uses old notes

- **What it does:** It reads the "Resources" section of every note and shows one list of
  tools and repos, with stars and the number of notes that mention each. The most
  mentioned ones come first.
- **Why it helps:** It answers "what did I save?" in one message. A tool that appears in 4
  reels is a strong sign of what to try first.
- **Files:** `processor.py` (`note_sections` already reads resources), `bot.py`, tests.

### 12. "You already saved this topic" 🟢 in list (part of "merge duplicates")

- **What it does:** After a new note, the bot adds one line when older notes share 2 or
  more tags: "You have 3 other notes about #claude #memory. See /tag claude."
- **Why it helps:** It shows you when you save the same idea again and again. That is a
  hint to act on it, not save it a 4th time.
- **Files:** `processor.py` (`read_tags`), `bot.py` (`format_reply`), tests.

### 13. Topic cheat sheet (`/topic claude`) 🟡 in list ("topic summary") — uses old notes

- **What it does:** It takes the key points of all notes with one tag and asks the local
  AI to merge them into one short page: main ideas, tools, and one next step.
- **Why it helps:** Ten small notes about one topic become one page you can read once.
- **Honest note:** qwen3:8b can mix up details when it merges many notes. Limit it to 8
  notes and show the source notes under the answer, like `/ask` does.
- **Files:** `processor.py` (new prompt, `notes_with_tag`), `bot.py`, tests.

### 14. Search that finds "AI" and "uv" 🟢 new (bug B14 from my review)

- **What it does:** Chat and `/ask` stop dropping short tech words. They also stop
  searching for filler words.
- **Why it helps:** I checked today: "what did I save about AI and uv?" searches for the
  words "did" and "save". So chat can miss the right notes.
- **Files:** `processor.py` (`question_words`, `STOPWORDS`, `search_notes`), tests.

### 15. Add my own action (`/add`) 🟢 in list (`/addnote`)

- **What it does:** `/add Call the bank about the fee` saves your own action in a
  "My actions" note. It shows in `/todo` like the others.
- **Why it helps:** One list for everything you need to do. I rank it low because your
  problem is doing, not adding.
- **Files:** `bot.py`, `processor.py`, tests.

### 16. Count which commands I use 🟢 new

- **What it does:** The bot counts each command in a private file for 2 weeks. `/usage`
  shows the counts.
- **Why it helps:** Section 4 below is my guess. With counts you can remove commands by
  fact. The file must go in `.gitignore`.
- **Files:** `bot.py`, `.gitignore`, tests.

### 17. Quiz from my notes 🟡 in list

- **What it does:** Once a week the bot asks one question from an old note, with 3 answer
  buttons.
- **Why it helps:** It helps you remember. It does not help you do. That is why it is low.
- **Files:** `processor.py`, `bot.py`, tests.

### 18. Voice note to action 🟡 in list

- **What it does:** You send a Telegram voice message. Whisper turns it into text and the
  bot saves it as an action or a short note.
- **Why it helps:** Fast capture of your own ideas. But it adds more to the list, so do it
  after the "do" features.
- **Files:** `bot.py` (voice handler), `processor.py`, tests.

### Not now

- **Web articles and X posts** (in list): more ways to save. You do not need more saving.
  X often needs a login, which you do not want.
- **Stats dashboard** (in list): Telegram is your only screen, and `/stats` is enough.
- **Obsidian export** (in list): you almost never open the Drive app.
- **Always-on hosting** (in list): not possible with your rules. Catch-up already covers
  most of it.

---

## 4. What to remove or hide

I cannot see which commands you use, so this is my opinion from the code. Idea 16 gives
you facts. "Hide" means: remove it from the BotFather menu, but keep it working.

| Feature | Do what | Why |
|---|---|---|
| `/ask` | Remove | Chat mode does the same job. You just type the question. Two ways to do one thing is confusing. |
| `/high`, `/normal`, `/low` | Hide | With one action per reel, plus types, plus due dates, three priority levels are too much to manage. Keep 🔥 only as "this week" (idea 6). |
| `/remind`, `/reminders`, `/unremind` | Merge into `/due` | Two date systems for one action is confusing. Let a due date send one message that morning. |
| `/tags` | Hide | `/tag` alone already shows your top tags as buttons. |
| `/retag`, `/renametag` | Hide | Rare repair jobs. They do not need a place in the menu. |
| `/file` | Hide | It is for the Drive and Markdown apps, which you almost never open. `/note` is enough. |
| `/update` | Hide | yt-dlp now updates by itself after the PC starts. |
| `/stats`, `/month` | Hide | Both already arrive by themselves (Sunday review, monthly summary). |
| The count lines at the top of `/todo` | Shorten | There are two lines of counts (🔥 ▫️ 🔽 and 🤖 🧠 🔗) plus two lines of help at the bottom. Keep one line each. |
| Duplicate `plan` line in `botfather-commands.txt` | Fix | `plan` is listed twice. Keep one. |

Keep: `/todo`, `/done`, `/skip`, `/nudge`, `/due`, `/notes`, `/note`, `/search`, `/tag`,
`/plan`, `/redo`, `/cleanup`, `/health`, chat mode. That is 13 things, down from about 30.

---

## 5. Batch 3: one thing that could go wrong

**A real action can be thrown away as a "creator offer".**

Batch 3 uses `LOW_PRIORITY_RE` in two new places:

- `split_actions`: an action that matches is **not saved as an action**. It goes to
  "From the creator".
- `cleanup_plan`: an open action that matches is counted as **junk** and skipped.

But the pattern matches the single words `bio`, `dm` and `link in`. I tested it today
with your real functions:

| Action text | Seen as a creator offer? |
|---|---|
| "Update your LinkedIn bio with these 3 keywords" | Yes (wrong) |
| "DM your manager to ask for feedback" | Yes (wrong) |
| "Put the link in your notes app" | Yes (wrong) |
| "Follow the creator for more" | Yes (right) |

In my test, a 🔥 high action "Update your LinkedIn bio..." was removed, and a weaker
normal action was kept as the main one. For career and job reels this will happen. Before
batch 3 the same match only made the action 🔽 low. Now it removes it, and `/cleanup`
marks it ❌ with no undo command in Telegram.

**Small fix (not done, only suggested):** match "bio" only as "link in bio" or "in my
bio", and "DM" only as "DM me" or "DM us". Add these three sentences as tests.

Two smaller things I also saw:

- The kept action is chosen by the AI's own priority. The 8B model is not reliable at
  this, and the others become "Other ideas" that you cannot bring back from Telegram.
  Idea 5 fixes this.
- `guess_kind` marks "Read the Claude docs page on memory" as 🤖, because of the word
  "Claude". It is really a 🔗 read task. So the 🤖 count in `/todo` will be too high for
  older notes.

---

## 6. Top 3 to build next

1. **Save one, do one** — commit message: `Ask about one old action when a new reel is saved`
2. **A nudge you can act on** — commit message: `Show the link, key points and Open note button in the nudge`
3. **🤖 Get the prompt** — commit message: `Add a Get prompt button for AI actions`

Before these, I would fix the `bio` / `DM` pattern from section 5. Commit message:
`Stop treating LinkedIn bio and DM actions as creator offers`.
