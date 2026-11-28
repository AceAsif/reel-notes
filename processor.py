"""Turns a downloaded reel video into a markdown note with action items.

Pipeline (all free, all local):
  video -> faster-whisper (speech to text)
        -> ffmpeg frames + Tesseract OCR (on-screen text, e.g. repo names)
        -> Ollama local LLM (summary + action items as JSON)
        -> markdown file in NOTES_DIR
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytesseract
import requests
import threads_link
from faster_whisper import WhisperModel

NOTES_DIR = Path(os.getenv("NOTES_DIR", "notes"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
# Optional: a GitHub token raises the API limit (10 -> 30 searches/minute).
# Not needed for normal use.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
FRAME_EVERY_SECONDS = int(os.getenv("FRAME_EVERY_SECONDS", "2"))

# On Windows, point this at tesseract.exe if it is not on PATH
if os.getenv("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.getenv("TESSERACT_CMD")

_whisper = None


def get_whisper() -> WhisperModel:
    """Load the Whisper model once and reuse it."""
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def transcribe(video: Path) -> tuple[str, str]:
    """Speech to English text. Returns (transcript, detected language code).

    English reels are transcribed as-is. Other languages (Hindi, Spanish, ...)
    are translated to English by Whisper while transcribing.
    """
    if not has_audio(video):
        return "", "en"   # silent clip (or a photo slide): nothing to transcribe
    model = get_whisper()
    # Language is detected up front; the segments are only computed if we read them
    segments, info = model.transcribe(str(video), vad_filter=True)
    language = info.language or "en"
    if language != "en":
        segments, _ = model.transcribe(str(video), vad_filter=True, task="translate")
    return collapse_repeats(" ".join(seg.text.strip() for seg in segments)), language


def has_audio(video: Path) -> bool:
    """True if the video file has a sound track. Silent clips would otherwise
    crash Whisper with 'tuple index out of range'."""
    import av
    try:
        with av.open(str(video)) as container:
            return len(container.streams.audio) > 0
    except Exception:
        return False


def screen_text(video: Path, workdir: Path) -> str:
    """Grab a frame every few seconds and OCR it to catch on-screen text."""
    frames = workdir / "frames"
    frames.mkdir(exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-vf", f"fps=1/{FRAME_EVERY_SECONDS}", str(frames / "f_%03d.png")],
        check=True,
    )
    return ocr_lines(sorted(frames.glob("*.png")))


PROMPT = """You turn short social media videos (motivation, tech, programming) into useful notes.
Below is the spoken transcript, the text that appeared on screen (from OCR, so it may have
typos), and the post's caption written by the creator (often has links and extra details).
A post can have several videos, marked [Video 1], [Video 2], ...: make ONE note that
covers ALL of them, with at least one key point per video.

Always write every field in English, even if the transcript or on-screen text
is in another language (e.g. Hindi or Hinglish); translate as needed.
Write simple English: short sentences and easy words. Keep tool names, commands and
links exactly as they are.

Return ONLY a JSON object with these keys:
- "title": short title (max 8 words)
- "category": one of "motivation", "tech", "programming", "other"
- "tags": list of 3-6 short topic tags, lowercase, words joined with "-", no "#".
  Prefer common, reusable tags so notes group well, e.g. "python", "ai-tools",
  "github", "claude", "productivity", "communication", "career", "security".
  <<EXISTING_TAGS>>
- "summary": 2-3 sentences
- "key_points": list of 3-7 specific, self-contained points. Someone who never watched
  the video must be able to USE them. Keep the actual details: exact questions,
  steps, commands, numbers, research findings, names, and WHY it works.
  If the video is a list, a roadmap or a step-by-step guide, keep EVERY step, in the
  same order, one point per step (up to 15). Do not merge steps and do not drop any.
  Bad: "Ask about favorite memories". Good: "Ask: 'What is your favourite memory?'"
- "resources": list of objects {"name": "...", "link": "..."}. List only named software, apps,
  AI models and repos. Do not list techniques, companies, courses, generic topics or programming
  languages. Use the product's own name (e.g. "Claude Code", not "Claude's coding tool").
  Fix obvious OCR typos. Only use a URL that was actually shown or said; never invent one.
  Use "" for link otherwise (never "N/A").
- "action_items": list of 1-2 objects {"text": "...", "priority": "high" | "normal" | "low",
  "type": "ai" | "habit" | "lookup"}.
  Fewer is better: I have little time, so give only the one or two actions that are really
  worth doing (the best first). Give at least one: a real step, like trying the main tool.
  "Comment X to get the link", "DM me", "follow" or "link in bio" are NOT actions.
  "text" is a short, concrete thing I should do, starting with a verb,
  e.g. "Find the Strix GitHub repo and read its README". Only actions supported by the video.
  When the video names several tools, pick the one or two most useful ones.
  Priority: "high" = specific, quick (under ~30 min) and clearly useful;
  "low" = optional, vague, or just following/contacting the creator; otherwise "normal".
  Type: "ai" = an AI tool (Claude, ChatGPT...) can do it or help with it, e.g. "Ask Claude to
  rewrite my CV"; "habit" = something I practise myself, e.g. "Every morning, write 3 goals";
  "lookup" = open a site, read a page, install or set up a tool.
- "claims": list of objects {"claim": "...", "why": "..."} for things I should NOT take
  at face value: big numbers or results ("7 billion free tokens", "10x faster"),
  "free"/"official"/"secret"/guaranteed claims, research or statistics with no source,
  and posts that mainly promote a paid product, course or "DM me" offer.
  ALWAYS include: anything called "official" (e.g. "an official Anthropic plugin"),
  and "comment X and I'll DM you" / "link in bio" / "check my channel" offers
  (why: engagement bait; get the tool from its real source instead).
  "claim" = what was said (short), "why" = why to check it (one short sentence).
  Use [] if nothing needs checking. Never more than 4.
- "quote", "lesson", "habit": ONLY when category is "motivation" (use "" otherwise):
  - "quote": the single most powerful sentence from the video, copied WORD FOR WORD
    from the transcript or caption (do not reword it). "" if nothing stands out.
  - "lesson": the main lesson in ONE plain sentence.
  - "habit": ONE small, specific habit to try, saying when or how often,
    e.g. "Every Monday, pick one task slightly harder than last week's and finish it."

TRANSCRIPT:
<<TRANSCRIPT>>

ON-SCREEN TEXT:
<<SCREEN>>

POST CAPTION:
<<CAPTION>>
"""


def ollama_extra() -> dict:
    """Thinking models (qwen3, deepseek-r1) 'think' for minutes before answering.
    Notes don't need that, so turn it off. Other models don't get the option."""
    m = OLLAMA_MODEL.lower()
    return {"think": False} if m.startswith(("qwen3", "deepseek-r1")) else {}


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def ask_ollama_json(prompt: str, schema: dict | None = None, tries: int = 2) -> dict:
    """Send a prompt to the local Ollama model and get a JSON object back.
    `schema` (a JSON schema) makes Ollama force the right shape. An empty or broken
    answer is tried again; if it is still empty, {} is returned."""
    # ~3.5 characters per token. Long multi-video posts need a bigger context window
    # (uses more graphics-card memory, so only when needed).
    num_ctx = 8192 if len(prompt) < 20000 else 16384
    for _ in range(tries):
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": schema or "json",
                **ollama_extra(),
                "options": {
                    "temperature": 0.2,  # low = consistent notes for the same reel
                    "num_ctx": num_ctx,  # room for long transcripts + on-screen text
                },
            },
            timeout=600,
        )
        resp.raise_for_status()
        try:
            data = json.loads(strip_thinking(resp.json()["response"]))
        except (json.JSONDecodeError, KeyError):
            data = {}
        if isinstance(data, dict) and data:
            return data
    return {}


# ---- Priorities and claim check -------------------------------------------

PRIORITY_ICON = {"high": "🔥 ", "normal": "", "low": "🔽 "}
PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}

# What kind of action it is. 🤖 = an AI can do (or help with) it, 🧠 = a habit or
# mindset thing for me, 🔗 = look something up, open a site, install or set up.
KIND_ICON = {"ai": "🤖", "habit": "🧠", "lookup": "🔗"}
KIND_LABEL = {"ai": "AI can do it", "habit": "Habit", "lookup": "Look up / set up"}
AI_RE = re.compile(
    r"\b(?:claude|chatgpt|gpt|gemini|copilot|cursor|llm|prompt|ai agents?|ai tools?|"
    r"ai assistants?|ask (?:an? )?ai|ask it|generate|automate|build (?:an? )?(?:app|bot|agent|tool|"
    r"workflow)|write (?:a )?(?:script|code|prompt))\b", re.I)
HABIT_RE = re.compile(
    r"\b(?:practi[sc]e|every (?:day|morning|night|week|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday)|daily|weekly|journal|meditate|exercise|workout|write down|"
    r"ask yourself|tell yourself|spend \d+|\d+ minutes?|stop |start (?:your|the) day)\b", re.I)


def guess_kind(text: str, category: str = "") -> str:
    """Best guess for an action with no saved type (older notes): no AI needed."""
    if AI_RE.search(text):
        return "ai"
    if HABIT_RE.search(text) or category == "motivation":
        return "habit"
    return "lookup"


def split_kind(text: str) -> tuple[str, str]:
    """'🤖 Do the thing' -> ('ai', 'Do the thing'); no icon -> ('', text)."""
    for kind, icon in KIND_ICON.items():
        if text.startswith(icon + " "):
            return kind, text[len(icon) + 1:].lstrip()
    return "", text


def kind_icon(kind: str) -> str:
    """'🤖 ' for a kind (with the space), '' for none."""
    return KIND_ICON[kind] + " " if kind in KIND_ICON else ""


def clean_actions(items) -> list[dict]:
    """Accept what the AI returns (objects or plain strings) → [{text, priority}]."""
    result = []
    for item in items or []:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("action") or "").strip()
            priority = str(item.get("priority", "normal")).lower().strip()
            kind = str(item.get("type") or item.get("kind") or "").lower().strip()
        else:
            text, priority, kind = str(item).strip(), "normal", ""
        if not text:
            continue
        if priority not in PRIORITY_ICON:
            priority = "normal"
        # Small models often skip priorities: actions that only send you to the
        # creator (bio, DM, comment, follow, channel) are always low.
        if LOW_PRIORITY_RE.search(text):
            priority = "low"
        if kind not in KIND_ICON:                 # the model skipped or misspelled it
            kind = guess_kind(text)
        result.append({"text": text, "priority": priority, "kind": kind})
    return result


MAX_ACTIONS = 1          # one main action per reel: a short list gets done, a long one doesn't
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


def split_actions(actions: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """(the action(s) to keep, other ideas, creator offers).

    Creator offers ("comment X", "link in bio") are not actions: they go to the
    "From the creator" section. Of the real actions the best one is kept (highest
    priority, then first); the rest become plain "other ideas" in the note."""
    offers = [a["text"] for a in actions if LOW_PRIORITY_RE.search(a["text"])]
    real = [a for a in actions if not LOW_PRIORITY_RE.search(a["text"])]
    ranked = sorted(real, key=lambda a: PRIORITY_RANK[a["priority"]])      # stable
    return ranked[:MAX_ACTIONS], ranked[MAX_ACTIONS:], offers


def limit_actions(actions: list[dict]) -> list[dict]:
    """Just the kept actions of split_actions()."""
    return split_actions(actions)[0]


# Actions/points that only send you to the creator: "comment 'MEMORY' to get the link",
# "DM me", "link in bio", "follow the creator", "check my broadcast channel"...
LOW_PRIORITY_RE = re.compile(
    # "comment 'MEMORY'" / "comment CLAUDE" / "comment below" (not "add a comment to your code")
    r"\bcomment\s+(?:[\"'“”‘’][\w-]+[\"'“”‘’]|(?-i:[A-Z][A-Z0-9]+)\b|below\b)"
    # "link in bio", "DM me", "follow the creator"... but NOT "update your LinkedIn bio",
    # "DM your manager" or "put the link in your notes app" (those are real actions)
    r"|\b(?:link in (?:the |my |his |her )?(?:bio|caption|description|comments?|profile)|"
    r"link (?:below|above)|(?:in|from|check|see) (?:the |my |his |her )bio|"
    r"dms? (?:me|us)\b|dm (?:for|to get)|send (?:me|us) a dm|dm you|"
    r"follow (?:the |this )?(?:creator|author|account|page)|follow (?:me|for more)|"
    r"broadcast channel|telegram channel|(?:creator|author)'?s? (?:channel|page|profile)|"
    r"in the caption|in my (?:profile|page))\b",
    re.I)


def clean_claims(items) -> list[dict]:
    result = []
    for item in items or []:
        if isinstance(item, dict) and str(item.get("claim", "")).strip():
            result.append({"claim": str(item["claim"]).strip().strip("\"'“”"),
                           "why": str(item.get("why", "")).strip()})
        elif isinstance(item, str) and item.strip():
            result.append({"claim": item.strip(), "why": ""})
    return result[:4]


def action_line(action: dict) -> str:
    """'- [ ] 🔥 Do the thing' — the icon after the checkbox stores the priority."""
    return (f"- [ ] {PRIORITY_ICON[action['priority']]}"
            f"{kind_icon(action.get('kind', ''))}{action['text']}")


def split_priority(text: str) -> tuple[str, str]:
    """'🔥 Do the thing' -> ('high', 'Do the thing')."""
    for level, icon in PRIORITY_ICON.items():
        if icon and text.startswith(icon):
            return level, text[len(icon):]
    return "normal", text


def creator_offers(texts: list[str]) -> list[str]:
    """The 'comment X / DM me / link in bio' parts: how the creator gives out links."""
    return [t for t in texts if LOW_PRIORITY_RE.search(t)]


def creator_offer_lines(data: dict) -> list[str]:
    """'## From the creator': who made it and how they offer the links, as a backup
    if a link in this note is wrong or missing."""
    offers = creator_offers(list(data.get("creator_offers", []))
                            + [a["text"] for a in data.get("action_items", [])]
                            + list(data.get("key_points", [])))
    if not offers:
        return []
    lines = ["## From the creator"]
    if data.get("creator"):
        lines.append(f"- Creator: {data['creator']}")
    lines += [f"- Offer: {o}" for o in dict.fromkeys(offers)]
    lines.append("- Use this if a link in this note is wrong or missing.")
    return lines + [""]


def other_ideas_lines(data: dict) -> list[str]:
    """'## Other ideas': the extra actions. Plain bullets, not on the to-do list."""
    ideas = [i for i in data.get("other_ideas", []) if i]
    if not ideas:
        return []
    return ["## Other ideas", *[f"- {i}" for i in ideas], ""]


def claims_lines(data: dict) -> list[str]:
    if not data.get("claims"):
        return []
    lines = ["## Claims to check"]
    for c in data["claims"]:
        lines.append(f"- ⚠️ \"{c['claim']}\"" + (f" — {c['why']}" if c["why"] else ""))
    return lines + [""]


def clean_motivation_fields(data: dict, source_text: str) -> None:
    """Keep quote/lesson/habit only for motivation reels, and check the quote
    really appears in the video (AI models like to 'improve' quotes)."""
    for key in ("quote", "lesson", "habit"):
        value = data.get(key, "")
        data[key] = value.strip() if isinstance(value, str) else ""
    if data.get("category") != "motivation":
        data["quote"] = data["lesson"] = data["habit"] = ""
        return
    data["quote"] = data["quote"].strip("\"'“”‘’ ")
    # Exact quote = its letters appear in the transcript/caption, ignoring punctuation
    data["quote_exact"] = bool(data["quote"]) and squash(data["quote"]) in squash(source_text)


def clean_tags(tags) -> list[str]:
    """'#AI Tools', 'Python ' -> ['ai-tools', 'python']; max 6, no duplicates."""
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+(?=#)|,", tags)
    result = []
    for t in tags or []:
        t = re.sub(r"[^a-z0-9-]", "", str(t).strip().lstrip("#").lower().replace(" ", "-"))
        t = re.sub(r"-+", "-", t).strip("-")
        if t and t not in result:
            result.append(t)
    return result[:6]


NOTE_CATEGORIES = ("motivation", "tech", "programming", "other")


def text_of(value) -> str:
    """Any AI value → clean one-line-ish text ('' for None, first text inside a dict)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return next((v.strip() for v in value.values() if isinstance(v, str) and v.strip()), "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def text_list(value) -> list[str]:
    """Any AI value → list of non-empty strings. A plain string is split by line
    (never one bullet per letter); None or a number gives []."""
    if isinstance(value, str):
        value = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln) for ln in value.splitlines()]
    if not isinstance(value, (list, tuple)):
        return []
    return [s for s in (text_of(v) for v in value) if s]


def clean_note_fields(data: dict) -> dict:
    """Make the shape of the AI answer safe, so one wrong type can't crash the note
    after the long wait. Changes `data` and returns it."""
    data["title"] = text_of(data.get("title")) or "Untitled reel"
    category = text_of(data.get("category")).lower()
    data["category"] = category if category in NOTE_CATEGORIES else "other"
    data["summary"] = text_of(data.get("summary"))
    data["key_points"] = text_list(data.get("key_points"))
    resources = data.get("resources")
    data["resources"] = ([r for r in resources if isinstance(r, (dict, str)) and r]
                         if isinstance(resources, list) else [])
    return data


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or list(props)}


_STR = {"type": "string"}
NOTE_SCHEMA = _obj({
    "title": _STR,
    "category": {"type": "string", "enum": list(NOTE_CATEGORIES)},
    "tags": {"type": "array", "items": _STR},
    "summary": _STR,
    "key_points": {"type": "array", "items": _STR},
    "resources": {"type": "array", "items": _obj({"name": _STR, "link": _STR})},
    "action_items": {"type": "array", "items": _obj({
        "text": _STR, "priority": {"type": "string", "enum": ["high", "normal", "low"]},
        "type": {"type": "string", "enum": list(KIND_ICON)}})},
    "claims": {"type": "array", "items": _obj({"claim": _STR, "why": _STR})},
    "quote": _STR, "lesson": _STR, "habit": _STR,
}, required=["title", "category", "tags", "summary", "key_points", "resources",
             "action_items", "claims"])


# ---- one idea, one to-do (a habit and an action that say the same thing) -------------------

# Words that tell WHEN something is done. They do not tell WHAT it is, so they are ignored
# when two lines are compared ("Every morning, write..." and "Write..." are the same idea).
WHEN_WORDS = {"one", "every", "each", "day", "daily", "morning", "evening", "night", "week",
              "weekly", "month", "monthly", "time", "times", "today", "tomorrow", "monday",
              "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def _idea_word(word: str) -> str:
    """'limiting', 'limits' -> 'limit' (very light stemming, good enough to compare)."""
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def idea_words(text: str) -> set[str]:
    skip = STOPWORDS | WHEN_WORDS
    return {_idea_word(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) >= 3 and w not in skip}


def similar_idea(a: str, b: str, min_shared: int = 3, ratio: float = 0.6) -> bool:
    """True when two to-do lines are the same idea: they share at least `min_shared` words
    and at least `ratio` of the words of the shorter one. No AI is used."""
    wa, wb = idea_words(a), idea_words(b)
    if not wa or not wb:
        return False
    shared = len(wa & wb)
    return shared >= min_shared and shared / min(len(wa), len(wb)) >= ratio


def merge_habit_and_actions(data: dict) -> None:
    """A motivation reel gives a "habit" AND an action that are often the same thing. That
    would be two entries in /todo for one idea. Keep ONE: the habit (it has the detail,
    like "Every morning"), with the priority of the action it replaces. Changes `data`."""
    habit = data.get("habit") or ""
    if not habit:
        return
    kept, merged = [], []
    for action in data.get("action_items", []):
        (merged if similar_idea(habit, action["text"]) else kept).append(action)
    if merged:
        data["action_items"] = kept
        data["habit_priority"] = min((a["priority"] for a in merged), key=PRIORITY_RANK.get)
    data["other_ideas"] = [i for i in data.get("other_ideas", []) if not similar_idea(habit, i)]


def habit_prefix(data: dict) -> str:
    """'🔥 🧠 ' when the habit replaced an action (so /todo shows its priority and type), else ''."""
    if "habit_priority" not in data:
        return ""
    return PRIORITY_ICON[data["habit_priority"]] + kind_icon("habit")


def drop_repeats(lines: list[str]) -> list[str]:
    """The same list without a line that repeats an earlier one (same idea)."""
    kept: list[str] = []
    for line in lines:
        if not any(similar_idea(line, other) for other in kept):
            kept.append(line)
    return kept


def summarise(transcript: str, screen: str, caption: str = "") -> dict:
    """Ask the local Ollama model for a structured note."""
    existing = [t for t, _ in all_tags()][:30]
    tag_hint = ("Tags already used in my notes (reuse them when they fit): "
                + ", ".join(existing)) if existing else ""
    prompt = (PROMPT.replace("<<TRANSCRIPT>>", transcript or "(no speech)")
                    .replace("<<SCREEN>>", screen or "(no on-screen text)")
                    .replace("<<CAPTION>>", caption or "(no caption)")
                    .replace("<<EXISTING_TAGS>>", tag_hint))
    said = transcript + "\n" + caption
    screen = screen + "\n" + caption  # links in the caption count as "shown in the post"
    data = ask_ollama_json(prompt, schema=NOTE_SCHEMA)
    if not data:
        raise RuntimeError("The AI gave no usable answer. Send the link again or try /redo.")
    clean_note_fields(data)       # wrong types can't crash the note any more
    data["action_items"], extras, data["creator_offers"] = split_actions(
        clean_actions(data.get("action_items", [])))
    data["other_ideas"] = [a["text"] for a in extras]
    data["claims"] = clean_claims(data.get("claims", []))
    clean_motivation_fields(data, transcript + "\n" + caption)
    merge_habit_and_actions(data)             # one idea = one to-do
    data["tags"] = clean_tags(data.get("tags", []))
    data["resources"] = drop_invented_links(data["resources"], transcript + "\n" + screen)
    data["resources"] = drop_link_borrowers(data["resources"], said)
    data["resources"] = mark_unverified_names(data["resources"], transcript + "\n" + screen)
    data["resources"] = clean_resources(data["resources"])     # same catalog rules as /tools
    data["resources"] = enrich_with_github(data["resources"], data["category"],
                                           transcript + "\n" + screen)
    ensure_action(data)
    return data


ACTION_RETRY_PROMPT = """A note about a short video has no action yet. Give one or two concrete
things I can do, based on the summary and the main resource. Start each with a verb, e.g.
"Install the Hallmark skill and try it on one page". Never "comment X to get the link", "DM me",
"follow" or "link in bio": those are not actions.
Return ONLY JSON: {"action_items": [{"text": "...", "priority": "normal", "type": "ai" | "habit" | "lookup"}]}

TITLE: <<TITLE>>
SUMMARY: <<SUMMARY>>
MAIN RESOURCE: <<RESOURCE>>"""
DEFAULT_ACTION_NOTICE = "⚠️ No action found, added a default"


def ensure_action(data: dict) -> None:
    """Every new note gets a to-do. No action left (the AI gave none, or only "comment X")?
    Ask once more; still none: "Try <main resource>: <link>", or "Review this note"."""
    if data.get("action_items") or data.get("habit"):    # a habit is the note's to-do
        return
    main = next((r for r in data.get("resources", []) if isinstance(r, dict) and r.get("name")
                 and not r.get("unverified")), None)
    prompt = (ACTION_RETRY_PROMPT.replace("<<TITLE>>", data.get("title", ""))
              .replace("<<SUMMARY>>", data.get("summary", ""))
              .replace("<<RESOURCE>>", f"{main['name']} {main.get('link', '')}".strip() if main else "(none)"))
    try:
        retry = ask_ollama_json(prompt)
    except requests.RequestException:
        retry = {}
    data["action_items"] = split_actions(clean_actions(retry.get("action_items", [])))[0]
    if data["action_items"]:
        return
    text = ("Review this note" if not main else
            f"Try {main['name']}: {main['link']}" if main.get("link") else f"Try {main['name']}")
    data["action_items"] = clean_actions([{"text": text, "priority": "normal", "type": "lookup"}])
    data["default_action"] = True
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] warning: no action found for "
          f"\"{data.get('title', '')}\", added a default: {text}", flush=True)


def drop_link_borrowers(resources: list, said_text: str) -> list:
    """Two resources with one link: keep the ones the video says, drop a name that was only on
    screen ("Relay Example" pointing at the Hallmark repo). With none said, keep them all."""
    said = squash(said_text)
    groups: dict[str, list] = {}
    for r in resources:
        if isinstance(r, dict) and str(r.get("link", "")).strip():
            groups.setdefault(str(r["link"]).strip().rstrip("/").lower(), []).append(r)
    drop = set()
    for group in groups.values():
        spoken = [r for r in group if squash(str(r.get("name", ""))) in said]
        if len(group) > 1 and spoken:
            drop |= {id(r) for r in group if r not in spoken}
    return [r for r in resources if id(r) not in drop]


def collapse_repeats(text: str) -> str:
    """Whisper sometimes loops: the same sentence again and again, or the whole text twice.
    Keep one copy."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [s for n, s in enumerate(sentences) if n == 0 or s != sentences[n - 1]]
    words = " ".join(kept).split()
    for size in range(4, len(words) // 2 + 1):       # 4+ words: "no no no" is real speech
        if len(words) % size == 0 and words == words[:size] * (len(words) // size):
            return " ".join(words[:size])
    return " ".join(kept)


# ---- GitHub repo detection ------------------------------------------------

GITHUB_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)", re.I)
INSTALL_CMD_RE = re.compile(
    r"npx\s+(?:-y\s+)?skills\s+add\s+([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)((?:\s+--skill\s+[\w-]+)*)",
    re.I)
# A repo found only by name search must be this popular, so a small personal
# repo with the same name (e.g. a 68-star "claude-code-setup") isn't linked by mistake.
# Repos shown in the video or caption, or in an install command, don't need this.
MIN_SEARCH_STARS = 300
GENERIC_WORDS = r"\b(github|repo|repository|plugin|skill|tool|library|framework|the|app)\b"


def squash(text: str) -> str:
    """'Claude mem' -> 'claudemem', 'claude-mem' -> 'claudemem' (for comparing names)."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def github_request(path: str, params: dict | None = None) -> tuple[int, dict | None]:
    """Call the GitHub API: (HTTP status, JSON). Status 0 = network problem."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "reel-notes-bot"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = requests.get("https://api.github.com" + path, params=params,
                         headers=headers, timeout=10)
        return r.status_code, (r.json() if r.status_code == 200 else None)
    except (requests.RequestException, ValueError):
        return 0, None


def github_get(path: str, params: dict | None = None) -> dict | None:
    """Call the GitHub API. Returns None on any problem, so notes never fail."""
    return github_request(path, params)[1]


def repo_fields(d: dict) -> dict:
    """What we keep about a repo: link, stars, description, last update, archived, licence."""
    licence = (d.get("license") or {}).get("spdx_id") or ""
    return {"link": d["html_url"], "stars": d.get("stargazers_count", 0),
            "description": (d.get("description") or "").strip(),
            "updated": (d.get("pushed_at") or "")[:10],
            "archived": bool(d.get("archived")),
            "license": "" if licence == "NOASSERTION" else licence}


def repo_info(owner: str, name: str) -> dict | None:
    """Repo details for owner/name. {'missing': True} if GitHub says it doesn't exist
    (wrong link), None if GitHub couldn't be asked (offline, rate limit)."""
    name = name.rstrip(".,;:)!?]").removesuffix(".git")   # 'repo.' at the end of a sentence
    status, d = github_request(f"/repos/{owner}/{name}")
    if status == 200 and d and "html_url" in d:
        return repo_fields(d)
    if status == 404:
        return {"missing": True}
    # Fallback: the same repo through the search API (422 = no such repo)
    status, found = github_request("/search/repositories", {"q": f"repo:{owner}/{name}"})
    if status == 422:
        return {"missing": True}
    items = (found or {}).get("items", [])
    return repo_fields(items[0]) if items else None


def find_repo(name: str, source_text: str) -> dict | None:
    """Find the GitHub repo for a tool name. Only accepts a confident match,
    otherwise returns None and the note keeps a GitHub search link."""
    key = squash(re.sub(GENERIC_WORDS, "", name.lower()))
    if len(key) < 3:
        return None
    joined = re.sub(r"\s*([/.])\s*", r"\1", source_text)  # OCR splits URLs; join them
    # 1) An install command in the video/caption, e.g.
    #    "npx skills add benjitaylor/skills --skill stageshow"
    for owner, repo, skills in INSTALL_CMD_RE.findall(joined):
        names = [squash(repo)] + [squash(s) for s in re.findall(r"--skill\s+([\w-]+)", skills)]
        if any(len(n) >= 3 and (key == n or key in n or n in key) for n in names):
            info = repo_info(owner, repo)
            if info and not info.get("missing"):
                return info
    # 2) A github.com/owner/repo link shown in the video or written in the caption
    for owner, repo in GITHUB_REPO_RE.findall(joined):
        r = squash(repo.removesuffix(".git"))
        if len(r) >= 3 and (key in r or r in key):
            info = repo_info(owner, repo)
            if info and not info.get("missing"):
                return info
    # 3) GitHub search: the repo name must match the tool name exactly, AND have at
    #    least MIN_SEARCH_STARS stars, so a tiny unrelated repo with the same name
    #    (e.g. a 5-star "StageShow") isn't picked by mistake
    found = github_get("/search/repositories",
                       {"q": f"{name} in:name", "sort": "stars", "per_page": 10})
    for item in (found or {}).get("items", []):
        if (squash(item.get("name", "")) == key
                and item.get("stargazers_count", 0) >= MIN_SEARCH_STARS):
            return repo_fields(item)
    return None


# Words that show the video is really about code you can download. Plain "GitHub"
# isn't enough: roadmaps say "learn Git/GitHub" without pointing to a repo.
CODE_HINT_RE = re.compile(
    r"github\.com/|open[\s-]?source|\bon github\b|\b(?:the |this |my |our )repo(?:sitory)?\b|"
    r"\bnpx\b|npm (?:i|install)\b|pip install|git clone|brew install|uvx?\s", re.I)

# Learning resources (courses, docs, tutorials) are websites, not repos
COURSE_RE = re.compile(
    r"\b(?:course|courses|tutorials?|guide|documentation|docs|learn|academy|"
    r"specialization|getting started|lessons?|skills|bootcamp|textbook|book|youtube)\b"
    r"|^(?:github|git)$", re.I)


def mentions_code(source_text: str) -> bool:
    return bool(CODE_HINT_RE.search(source_text or ""))


def enrich_with_github(resources: list, category: str, source_text: str) -> list:
    """Add real GitHub links, stars and descriptions to resources.
    A GitHub search only runs when the video/caption talks about code (GitHub,
    open source, install commands...). Otherwise common names like "Settings"
    or "Muse" would match a random popular repo."""
    code = mentions_code(source_text)
    for r in resources:
        if not isinstance(r, dict) or r.get("unverified"):
            continue                            # no GitHub lookup for a name the video never said
        link = str(r.get("link", "")).strip()
        m = GITHUB_REPO_RE.search(link)
        if m:                                   # already a repo link: check it's real
            info = repo_info(m.group(1), m.group(2))
        elif (not link and category in ("tech", "programming") and code
              and not COURSE_RE.search(str(r.get("name", "")))):
            info = find_repo(str(r.get("name", "")), source_text)
        else:
            info = None
        if info and info.get("missing"):
            r["missing"] = True                 # keep the link, but warn it may be wrong
        elif info:
            r.update(info)
    return resources


STALE_DAYS = 365


def repo_warnings(r: dict, today: date | None = None) -> list[str]:
    """Health warnings for a repo resource."""
    if r.get("missing"):
        return ["⚠️ repo not found: this link may be wrong"]
    warnings = []
    if r.get("archived"):
        warnings.append("⚠️ archived: no longer maintained")
    updated = r.get("updated", "")
    if updated:
        try:
            last = date.fromisoformat(updated)
            if ((today or date.today()) - last).days > STALE_DAYS:
                warnings.append(f"⚠️ no updates for over a year (last: {last:%b %Y})")
        except ValueError:
            pass
    return warnings


def format_stars(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def drop_invented_links(resources: list, source_text: str) -> list:
    """Remove URLs whose website never appeared in the video (the AI made them up).

    The resource stays; resource_line() then adds a search link instead.
    """
    squashed = re.sub(r"\s+", "", source_text.lower())  # OCR often splits URLs
    for r in resources:
        if not isinstance(r, dict):
            continue
        link = str(r.get("link", "")).strip()
        domain = re.sub(r"^https?://(www\.)?", "", link.lower()).split("/")[0]
        if domain and domain not in squashed:
            r["link"] = ""
    return resources


def mark_unverified_names(resources: list, source_text: str) -> list:
    """Flag tool/plugin names that are not in the transcript, OCR or caption.

    The AI can invent names. resource_line() then shows them as '(unverified)'.
    """
    squashed = squash(source_text)              # 'claude-mem' matches 'Claude mem'
    for r in resources:
        if isinstance(r, dict) and squash(str(r.get("name", ""))) not in squashed:
            r["unverified"] = True
    return resources


# 'strix.ai/docs', 'github.com/a/b', 'www.nas.com': no spaces, a dot, a real ending
BARE_DOMAIN_RE = re.compile(r"^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:[/?#]\S*)?$", re.I)


def resource_line(r, category: str = "") -> str:
    """Name + link. If there's no real URL, add a search link:
    GitHub when the video talks about code, Google for everything else."""
    if not isinstance(r, dict):
        return str(r)
    name = str(r.get("name", "")).strip()
    link = str(r.get("link", "")).strip()
    if link and not link.lower().startswith("http") and BARE_DOMAIN_RE.match(link):
        link = "https://" + link                  # 'strix.ai/docs' is a real link
    if not link.lower().startswith("http"):
        link = "— No link found"                 # no search link: it often led to the wrong thing
    if r.get("unverified"):
        name += " (unverified)"
    line = f"{name} {link}".strip()
    if "stars" in r:
        line += f"  ⭐ {format_stars(int(r['stars']))}"
        extra = []
        if r.get("updated"):
            extra.append(f"updated {date.fromisoformat(r['updated']):%b %Y}")
        if "license" in r:
            extra.append(r["license"] or "no licence")
        if extra:
            line += " · " + " · ".join(extra)
    warnings = repo_warnings(r)
    if warnings:
        line += "  " + "  ".join(warnings)
    if r.get("description"):
        desc = r["description"]
        line += " — " + (desc if len(desc) <= 100 else desc[:97] + "...")
    return line


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "reel"


def save_note(data: dict, transcript: str, screen: str, source: str,
              language: str = "en", caption: str = "", saved_at: datetime | None = None,
              keep_existing: bool = True) -> Path:
    """Write the note. `saved_at` keeps an older date (used by /redo fast).
    A note with the same file name is never overwritten (the new one gets _2, _3...)."""
    now = saved_at or datetime.now()
    name = f"{now:%Y-%m-%d_%H%M}_{slugify(data['title'])}.md"

    lines = [
        f"# {data['title']}",
        "",
        f"- Date: {now:%Y-%m-%d %H:%M}",
        f"- Category: {data['category']}",
        f"- Source: {source or '-'}",
        *([f"- Creator: {data['creator']}"] if data.get("creator") else []),
        f"- Language: {language}" + (" (translated to English)" if language != "en" else ""),
        *([f"- Slides: {slide_summary(data)}"] if slide_total(data) > 1 else []),
        tags_line(data.get("tags", [])),
        "",
        "## Summary",
        data["summary"],
        "",
        *motivation_lines(data),
        *claims_lines(data),
        *creator_offer_lines(data),
        "## Key points",
        *[f"- {p}" for p in data["key_points"]],
        "",
        "## Resources",
    ]
    lines += [f"- {resource_line(r, data['category'])}" for r in data["resources"]]
    lines += [
        "",
        "## Action items",
        *[action_line(a) for a in data["action_items"]],
        "",
        *other_ideas_lines(data),
        "## Transcript",
        transcript or "(no speech)",
        "",
        "## On-screen text",
        *fenced(screen or "(none)"),
        "",
    ]
    if caption:
        lines += ["## Post caption", caption, ""]
    return write_note_file(name, "\n".join(lines), keep_existing)


MAX_VIDEOS = 10                       # most slides taken from one carousel post
MAX_MINUTES = int(os.getenv("MAX_MINUTES", "10"))  # longest video accepted (YouTube etc.)
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def slide_position(p: Path) -> int:
    """item_3.mp4 -> 3 (a single reel is 'item_NA' -> 0)."""
    n = p.stem.split("_")[-1]
    return int(n) if n.isdigit() else 0


# ---- X (x.com and twitter.com) ------------------------------------------------------------
# yt-dlp reads X videos. No login and no cookies are used for X, so a post that needs a login
# (age-limited, private) cannot be saved. Then the bot asks for the video file instead.

X_URL_RE = re.compile(r"^https?://(?:www\.|mobile\.|m\.)?(?:x|twitter)\.com/", re.I)
X_STATUS_RE = re.compile(
    r"^https?://(?:www\.|mobile\.|m\.)?(?:x|twitter)\.com/[^/?#]+/status(?:es)?/(\d+)", re.I)
MSG_X_NO_VIDEO = "I could not get this X video. Please save the video and send me the file."


class VideoNotSaved(RuntimeError):
    """The message is ready to show in Telegram. The real reason is in bot.log."""


def is_x_url(url: str) -> bool:
    return bool(X_URL_RE.match((url or "").strip()))


MSG_DOWNLOAD_FAILED = "❌ I could not download this video."
MSG_DOWNLOAD_TRY = "Try /update (a new yt-dlp often fixes it), or send me the video file."
YTDLP_ERROR_LIMIT = 300

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|~/|(?<![\w.:-])/(?=[^\s/]+/))[^\s'\"]*")
_SECRET_RE = re.compile(r"cookie|password|passwd|netrc|credential|token", re.I)


def clean_ytdlp_error(text: str, limit: int = YTDLP_ERROR_LIMIT) -> str:
    """yt-dlp's error, safe and short for a chat message: no colour codes, no "ERROR:",
    no links, no file paths, no sentence about cookies, logins or tokens. About `limit` chars."""
    text = _ANSI_RE.sub("", str(text or ""))
    text = re.sub(r"^\s*(?:(?:ERROR|WARNING)\s*:\s*)+", "", text, flags=re.I)
    text = _URL_RE.sub("[link]", text)
    text = _PATH_RE.sub("[file]", text)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    text = " ".join(x for x in sentences if not _SECRET_RE.search(x)).strip()
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text or "unknown error"


def download_failed_text(reason: str, x_link: bool = False) -> str:
    """The chat message when yt-dlp could not get a video, with yt-dlp's own reason."""
    head = MSG_X_NO_VIDEO if x_link else MSG_DOWNLOAD_FAILED
    tail = "" if x_link else "\n\n" + MSG_DOWNLOAD_TRY
    return f"{head}\nReason: {clean_ytdlp_error(reason)}{tail}"


class YtdlpErrors:
    """A yt-dlp logger that only remembers the error lines, so they can go to bot.log."""
    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg) -> None: pass
    def info(self, msg) -> None: pass
    def warning(self, msg) -> None: pass

    def error(self, msg) -> None:
        self.errors.append(str(msg))


def download_media(url: str, workdir: Path) -> tuple[list[Path], str, dict]:
    """Download a reel, or every slide of a carousel post (videos AND photos).

    Returns (slide files in post order, the post caption, the creator). For a video
    slide you get the video; for a photo slide you get the image.
    """
    if threads_link.is_threads_url(url):        # yt-dlp has no Threads support
        return threads_link.download(url, workdir)

    import yt_dlp

    opts = {
        # playlist_index = position in a carousel ("NA" for a single reel)
        "outtmpl": str(workdir / "item_%(playlist_index)s.%(ext)s"),
        "format": "bv*+ba/b",           # best video + audio, merged by ffmpeg
        "merge_output_format": "mp4",
        "noplaylist": False,            # carousels are "playlists": take every slide
        "playlistend": MAX_VIDEOS,
        "ignoreerrors": True,           # one broken slide shouldn't stop the rest
        # Photo slides have no video. These two options keep them and save the
        # slide's picture (its "thumbnail" is the full photo):
        "ignore_no_formats_error": True,
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,             # no [download] lines filling bot.log
        # Long YouTube videos would take ages: only take videos up to MAX_MINUTES
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <=? {MAX_MINUTES * 60}"),
    }
    x_link = is_x_url(url)
    seen = YtdlpErrors()
    opts["logger"] = seen               # keep yt-dlp's real error for the chat and bot.log
    # Instagram often needs you logged in: export cookies to a cookies.txt file.
    # X links never get cookies (no login for X).
    if os.getenv("COOKIES_FILE") and not x_link:
        opts["cookiefile"] = os.getenv("COOKIES_FILE")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}

        caption = info.get("description") or ""
        if not caption:  # carousels keep the caption on each item
            for entry in info.get("entries") or []:
                if entry and entry.get("description"):
                    caption = entry["description"]
                    break
        return pick_slides(workdir), caption.strip(), creator_from_info(info)
    except Exception as exc:
        logged = " | ".join(seen.errors[-2:]) or repr(exc)       # yt-dlp's own words first
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {'x' if x_link else 'download'}: "
              f"yt-dlp failed: {logged[:400]} | {url.split('?')[0]}", flush=True)
        reason = seen.errors[-1] if seen.errors else (str(exc) or repr(exc))
        raise VideoNotSaved(download_failed_text(reason, x_link)) from exc


def creator_from_info(info: dict) -> dict:
    """Who posted it: {'name', 'handle', 'url'} from yt-dlp's details (any may be '')."""
    entries = [e for e in (info.get("entries") or []) if e]
    src = info if (info.get("uploader") or info.get("channel")) else (entries[0] if entries else info)
    name = str(src.get("uploader") or src.get("channel") or "").strip()
    handle = str(src.get("uploader_id") or src.get("channel_id") or "").strip().lstrip("@")
    url = str(src.get("uploader_url") or src.get("channel_url") or "").strip()
    if handle.isdigit():                     # Instagram sometimes gives a number, not a name
        handle = ""
    return {"name": name, "handle": handle, "url": url}


def creator_line(creator: dict | None) -> str:
    """'Akita (@akitaonrails) https://...' or '' if unknown."""
    if not creator:
        return ""
    name, handle, url = creator.get("name", ""), creator.get("handle", ""), creator.get("url", "")
    parts = [name] if name else []
    if handle and handle.lower() != name.lower():
        parts.append(f"(@{handle})" if name else f"@{handle}")
    if url:
        parts.append(url)
    return " ".join(parts)


def pick_slides(workdir: Path) -> list[Path]:
    """One file per slide: the video if there is one, otherwise the photo.
    (Video slides also get a cover image saved; that one is ignored.)"""
    by_slide: dict[int, Path] = {}
    for p in workdir.glob("item_*"):
        ext = p.suffix.lower()
        pos = slide_position(p)
        if ext in VIDEO_EXTS:
            by_slide[pos] = p
        elif ext in IMAGE_EXTS and pos not in by_slide:
            by_slide[pos] = p
    # a photo may have been seen before its video: prefer videos
    for p in workdir.glob("item_*"):
        if p.suffix.lower() in VIDEO_EXTS:
            by_slide[slide_position(p)] = p
    slides = [by_slide[k] for k in sorted(by_slide)]
    if not slides:
        raise RuntimeError("Nothing could be downloaded from this post. "
                           f"(Videos longer than {MAX_MINUTES} minutes are skipped: see MAX_MINUTES in .env)")
    return slides


def ocr_lines(images: list[Path]) -> str:
    """OCR several images; keep each distinct line once."""
    seen, lines = set(), []
    for img in images:
        for line in pytesseract.image_to_string(str(img)).splitlines():
            line = line.strip()
            if len(line) < 4:
                continue
            key = line.lower()
            if key not in seen:
                seen.add(key)
                lines.append(line)
    return "\n".join(lines)[:6000]


def image_text(image: Path, workdir: Path) -> str:
    """OCR a photo slide. Formats the OCR library can't open (e.g. HEIC)
    are converted to PNG with ffmpeg first."""
    try:
        return ocr_lines([image])
    except Exception:
        png = workdir / (image.stem + ".png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(image), str(png)],
                       check=True)
        return ocr_lines([png])


TIMING_LABELS = {"download": "download", "whisper": "listen", "ocr": "read screen", "ai": "AI"}


def timing_text(timings: dict) -> str:
    """'87s (download 4 · listen 21 · read screen 48 · AI 14)' — where the time went."""
    parts = [f"{label} {timings[key]:.0f}" for key, label in TIMING_LABELS.items()
             if key in timings]
    return f"{sum(timings.values()):.0f}s" + (f" ({' · '.join(parts)})" if parts else "")


def log_timing(what: str, timings: dict) -> None:
    """One line in bot.log per note, so slow steps are easy to see."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] timing: {timing_text(timings)} | {what}")


def process_videos(videos: list[Path], source: str = "", caption: str = "",
                   creator: dict | None = None) -> tuple[Path, dict]:
    """Full pipeline for one reel or a multi-slide post (videos and/or photos) → ONE note."""
    labels, transcripts, screens, languages = [], [], [], []
    photo_count = 0
    timings = {"whisper": 0.0, "ocr": 0.0, "ai": 0.0}     # seconds per step
    with tempfile.TemporaryDirectory() as tmp:
        for i, slide in enumerate(videos[:MAX_VIDEOS], start=1):
            workdir = Path(tmp) / f"s{i}"
            workdir.mkdir()
            is_photo = slide.suffix.lower() in IMAGE_EXTS
            try:
                started = time.perf_counter()
                if is_photo:
                    text, lang = "", "en"
                    screen = image_text(slide, workdir)
                else:
                    text, lang = transcribe(slide)
                    timings["whisper"] += time.perf_counter() - started
                    started = time.perf_counter()
                    screen = screen_text(slide, workdir)
                timings["ocr"] += time.perf_counter() - started
            except Exception as exc:   # one broken slide shouldn't stop the whole post
                print(f"Skipping slide {i} ({slide.name}): {exc!r}")
                continue
            photo_count += is_photo
            labels.append(f"Slide {len(labels) + 1}" + (" · photo" if is_photo else ""))
            transcripts.append(text)
            screens.append(screen)
            languages.append(lang)
    if not transcripts:
        raise RuntimeError("None of the slides in this post could be processed.")

    if len(transcripts) == 1:
        transcript, screen = transcripts[0], screens[0]
    else:  # label each part so the AI (and you) can tell the slides apart
        per_slide = max(1500, 9000 // len(screens))   # keep the prompt a sensible size
        transcript = "\n\n".join(f"[{lab}] {t or '(no speech)'}"
                                 for lab, t in zip(labels, transcripts))
        screen = "\n\n".join(f"[{lab}]\n{s[:per_slide]}" for lab, s in zip(labels, screens))
    language = next((lang for lang in languages if lang != "en"), "en")

    started = time.perf_counter()
    data = summarise(transcript, screen, caption)
    timings["ai"] = time.perf_counter() - started
    data["timings"] = timings
    log_timing(f"{len(transcripts)} slide(s), {len(transcript)} chars spoken, "
               f"{len(screen)} chars on screen", timings)
    data["language"] = language
    data["video_count"] = len(transcripts) - photo_count
    data["photo_count"] = photo_count
    data["creator"] = creator_line(creator)
    return save_note(data, transcript, screen, source, language, caption), data


YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:shorts/|watch\?(?:.*&)?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")


# /reel/, /reels/, /p/ and /tv/ (also after a user name) all point to one Instagram post
INSTAGRAM_ID_RE = re.compile(r"instagram\.com/(?:[^/?#]+/)?(?:reels?|p|tv)/([A-Za-z0-9_-]+)", re.I)
TIKTOK_ID_RE = re.compile(r"tiktok\.com/(?:@[^/?#]+/video|v|embed(?:/v2)?)/(\d+)", re.I)
FACEBOOK_ID_RE = re.compile(
    r"(?:facebook\.com/(?:reel/|watch/?\?(?:[^#]*&)?v=|(?:[^/?#]+/)?videos/(?:[^/?#]+/)?)|fb\.watch/)"
    r"([A-Za-z0-9_-]+)", re.I)


def normalise_url(url: str) -> str:
    """The video ID of a link, so one video = one key whatever the link looks like:
    'instagram:ID', 'tiktok:ID', 'youtube:ID', 'facebook:ID', 'x:ID', or the Threads key.
    Other links: the URL without ?tracking bits, #, trailing slash or capitals.
    Short links (vm.tiktok.com, share links) can't be opened without the internet, so they
    stay as URLs."""
    url = url.strip()
    threads_key = threads_link.dedupe_key(url)
    if threads_key:
        return threads_key
    x = X_STATUS_RE.match(url)
    if x:
        return "x:" + x.group(1)                 # x.com, twitter.com and mobile links: same post
    for platform, pattern in (("youtube", YOUTUBE_ID_RE), ("instagram", INSTAGRAM_ID_RE),
                              ("tiktok", TIKTOK_ID_RE), ("facebook", FACEBOOK_ID_RE)):
        m = pattern.search(url)
        if m:
            return f"{platform}:{m.group(1)}"   # IDs are case-sensitive: don't lower()
    return url.split("?")[0].split("#")[0].rstrip("/").lower()


# ---- link index: video ID -> notes, so a video is never downloaded twice -------------------
# link_index.json is private (it lists note files). It keeps the list of note files it was
# built from; when the files on disk differ (a note added, moved, deleted, or the notes folder
# is away), it is rebuilt from the Source lines of the notes.

LINK_INDEX_FILE = Path(os.getenv("LINK_INDEX_FILE", "link_index.json"))
LINK_INDEX_VERSION = 1           # raise it when normalise_url() changes, so old keys are rebuilt


def _note_files() -> list[tuple[str, Path]]:
    return [(label, p) for label, folder in (("notes", NOTES_DIR), ("pending", PENDING_DIR))
            if folder.is_dir() for p in sorted(folder.glob("*.md"))]


def _index_entry(label: str, path: Path) -> tuple[str, dict] | None:
    """(video key, {'file', 'saved', 'folder'}) from a note's Source line, or None."""
    lines = path.read_text(encoding="utf-8").splitlines()[:12]
    source = next((l[10:].strip() for l in lines[:8] if l.startswith("- Source: ")), "")
    if not re.match(r"https?://", source):
        return None                              # 'screenshot' or no source: nothing to match
    saved = _note_date(path, lines) or datetime.fromtimestamp(path.stat().st_mtime)
    return normalise_url(source), {"file": path.name, "saved": f"{saved:%Y-%m-%d %H:%M}", "folder": label}


def _save_link_index(data: dict) -> None:
    try:
        LINK_INDEX_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        _log_notes(f"could not save {LINK_INDEX_FILE.name}: {exc!r}")


def rebuild_link_index() -> dict:
    files = _note_files()
    links: dict[str, list] = {}
    for label, path in files:
        found = _index_entry(label, path)
        if found:
            links.setdefault(found[0], []).append(found[1])
    data = {"version": LINK_INDEX_VERSION, "files": [f"{label}/{p.name}" for label, p in files],
            "links": links}
    _save_link_index(data)
    return data


def load_link_index() -> dict:
    """The index, rebuilt first if it is missing, broken or out of date."""
    try:
        data = json.loads(LINK_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if (not isinstance(data, dict) or data.get("version") != LINK_INDEX_VERSION
            or data.get("files") != [f"{l}/{p.name}" for l, p in _note_files()]):
        data = rebuild_link_index()
    return data


def add_to_link_index(path: Path) -> None:
    """A note was just written: add it without reading every note again."""
    try:
        data = json.loads(LINK_INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return                                    # no index yet: the next check builds it
    label = "pending" if is_pending(path) else "notes"
    found = _index_entry(label, path)
    data.setdefault("files", []).append(f"{label}/{path.name}")
    data["files"] = sorted(set(data["files"]), key=lambda f: (f.split("/")[0] != "notes", f))
    links = data.setdefault("links", {})
    for key in links:                             # a replaced note (same name) is listed once
        links[key] = [e for e in links[key] if (e["file"], e.get("folder")) != (path.name, label)]
    if found:
        links.setdefault(found[0], []).append(found[1])
    data["links"] = {k: v for k, v in links.items() if v}
    _save_link_index(data)                       # if it was stale, the next load rebuilds it


def _entry_path(entry: dict) -> Path:
    return (PENDING_DIR if entry.get("folder") == "pending" else NOTES_DIR) / entry["file"]


def find_note_by_source(url: str) -> Path | None:
    """The newest existing note for this video, if we already made one."""
    if not url:
        return None
    entries = load_link_index()["links"].get(normalise_url(url), [])
    paths = [_entry_path(e) for e in sorted(entries, key=lambda e: e["saved"], reverse=True)]
    return next((p for p in paths if p.is_file()), None)


SHORT_NOTE_SECTIONS = ("Summary", "Key points", "Resources", "Action items")


def short_note(text: str) -> str:
    """The title plus Summary, Key points, Resources and Action items (no transcript or screen text)."""
    lines = text.splitlines()
    keep, out = False, lines[:1]
    for line in lines[1:]:
        if line.startswith("## "):
            keep = line[3:].strip() in SHORT_NOTE_SECTIONS
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def duplicate_notes() -> list[tuple[str, list[dict]]]:
    """Videos with more than one note: [(video key, [{'file', 'saved', 'folder'}...])]."""
    links = load_link_index()["links"]
    dupes = [(k, sorted(v, key=lambda e: e["saved"])) for k, v in links.items() if len(v) > 1]
    return sorted(dupes, key=lambda d: d[1][-1]["saved"], reverse=True)


def slide_total(data: dict) -> int:
    return data.get("video_count", 1) + data.get("photo_count", 0)


def slide_summary(data: dict) -> str:
    """'5 (3 videos, 2 photos)' or '4 videos'."""
    v, ph = data.get("video_count", 1), data.get("photo_count", 0)
    if ph and v:
        return f"{v + ph} ({v} video{'s' * (v != 1)}, {ph} photo{'s' * (ph != 1)})"
    return f"{ph} photos" if ph else f"{v} videos"


def motivation_lines(data: dict) -> list[str]:
    """Extra sections for motivation reels: quote, lesson, habit."""
    lines = []
    if data.get("quote"):
        note = "" if data.get("quote_exact") else "  *(paraphrased)*"
        lines += ["## Key quote", f"> {data['quote']}{note}", ""]
    if data.get("lesson"):
        lines += ["## Main lesson", data["lesson"], ""]
    if data.get("habit"):
        lines += ["## Habit to try", f"- [ ] {habit_prefix(data)}{data['habit']}", ""]
    return lines


def fenced(text: str) -> list[str]:
    """Wrap raw OCR text in a code block so stray symbols ('* ', '| ', '---')
    aren't read as Markdown lists/tables/headings. The fence is longer than any
    run of backticks in the text, so the text can never close it early."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence + "text", text, fence]


def open_actions() -> list[dict]:
    """Every unticked '- [ ]' action across all notes, numbered in this order:
    🔥 high first, then normal, then 🔽 low; oldest note first within each.
    /todo, /done, /skip and /high all use this same order, so numbers match.
    """
    results = []
    if not NOTES_DIR.exists():
        return results
    for note in sorted(NOTES_DIR.glob("*.md")):
        lines = note.read_text(encoding="utf-8").splitlines()
        title = lines[0].lstrip("# ").strip() if lines else note.stem
        category = next((ln[len("- Category: "):].strip() for ln in lines[:8]
                         if ln.startswith("- Category: ")), "")
        section = ""
        for i, line in enumerate(lines):
            if line.startswith("## "):
                section = line[3:].strip()
            # Only real action items count, not "- [ ]" text inside a transcript/caption
            elif section in ("Action items", "Habit to try") and line.startswith("- [ ] "):
                priority, text = split_priority(line[6:].strip())
                stored_kind, text = split_kind(text)
                text, due = split_due(text)
                repeat = sum(r["path"] == note and r["action"] == text for r in results) + 1
                results.append({"path": note, "line": i, "title": title, "section": section,
                                "action": text, "priority": priority, "due": due,
                                "kind": stored_kind or guess_kind(text, category),
                                "kind_saved": bool(stored_kind),
                                "id": action_key(note, text, repeat)})
    today = date.today()
    # Due soon (overdue, today, next 2 days) first, soonest first; then by priority.
    # sort() is stable, so notes keep their order inside each group.
    results.sort(key=lambda a: (0, a["due"]) if is_due_soon(a, today)
                 else (1, date.max, PRIORITY_ORDER[a["priority"]]))
    return results


# ---- Due dates (Obsidian Tasks style: "📅 2026-11-20" at the end) -------------

DUE_RE = re.compile(r"\s*📅\s*(\d{4}-\d{2}-\d{2})\s*$")
DUE_SOON_DAYS = 2


def split_due(text: str) -> tuple[str, date | None]:
    m = DUE_RE.search(text)
    if not m:
        return text, None
    try:
        return text[:m.start()].rstrip(), date.fromisoformat(m.group(1))
    except ValueError:
        return text, None


def is_due_soon(action: dict, today: date | None = None) -> bool:
    due = action.get("due")
    return bool(due) and due <= (today or date.today()) + timedelta(days=DUE_SOON_DAYS)


def todo_line(action: dict, priority: str | None = None, due: date | None | str = "keep") -> str:
    """Rebuild a '- [ ]' line, keeping (or changing) the priority and due date."""
    due = action.get("due") if due == "keep" else due
    saved = action["kind"] if action.get("kind_saved") else ""      # older lines stay as they are
    line = ("- [ ] " + PRIORITY_ICON[priority or action["priority"]]
            + kind_icon(saved) + action["action"])
    return line + (f" 📅 {due:%Y-%m-%d}" if due else "")


def due_label(due: date | None, today: date | None = None) -> str:
    """'⚠️ overdue (Mon 17 Nov)', '📅 today', '📅 tomorrow', '📅 Fri 20 Nov'."""
    if not due:
        return ""
    today = today or date.today()
    if due < today:
        return f"⚠️ overdue ({due:%a %d %b})"
    if due == today:
        return "📅 today"
    if due == today + timedelta(days=1):
        return "📅 tomorrow"
    return f"📅 {due:%a %d %b}"


def set_due(numbers: list[int], due: date | None) -> list[str]:
    """Set (or clear, with due=None) the due date of actions by their /todo number."""
    actions = open_actions()
    chosen = [actions[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(actions)]
    for a in chosen:
        lines = a["path"].read_text(encoding="utf-8").splitlines()
        lines[a["line"]] = todo_line(a, due=due)
        a["path"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [a["action"] for a in chosen]


def parse_due(text: str, today: date | None = None) -> date | None:
    """'friday', 'tomorrow', 'in 3 days', '20/11', 'next week' → a date (not in the past)."""
    today = today or date.today()
    now = datetime.combine(today, datetime.min.time())     # midnight: 'friday' = this Friday
    when = parse_when(text, now)
    if when is None or when.date() < today:
        return None
    return when.date()


def dated_actions(today: date | None = None) -> tuple[list, list]:
    """(overdue, due in the next 7 days) as (/todo number, action) pairs."""
    today = today or date.today()
    overdue, coming = [], []
    for n, a in enumerate(open_actions(), start=1):
        if a["due"] and a["due"] < today:
            overdue.append((n, a))
        elif a["due"] and a["due"] <= today + timedelta(days=7):
            coming.append((n, a))
    return overdue, coming


def set_priority(numbers: list[int], level: str) -> list[str]:
    """Change the priority of actions by their /todo number."""
    actions = open_actions()
    chosen = [actions[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(actions)]
    for a in chosen:
        lines = a["path"].read_text(encoding="utf-8").splitlines()
        lines[a["line"]] = todo_line(a, priority=level)
        a["path"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [a["action"] for a in chosen]


def tags_line(tags: list[str]) -> str:
    return "- Tags: " + " ".join(f"#{t}" for t in tags)


def rename_tag(old: str, new: str) -> int:
    """Rename a tag in every note (e.g. 'claudie' -> 'claude').
    If a note already has the new tag, the two are merged. Returns notes changed."""
    old_c, new_c = clean_tags([old]), clean_tags([new])
    if not old_c or not new_c or not NOTES_DIR.exists():
        return 0
    old, new = old_c[0], new_c[0]
    changed = 0
    for path in NOTES_DIR.glob("*.md"):
        tags = read_tags(path)
        if old not in tags:
            continue
        merged = clean_tags([new if t == old else t for t in tags])  # also removes duplicates
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines[:12]):
            if line.startswith("- Tags:"):
                lines[i] = tags_line(merged)
                break
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        changed += 1
    return changed


def read_tags(path: Path) -> list[str]:
    """Tags from a note's '- Tags: #a #b' line (empty list for old notes)."""
    for line in path.read_text(encoding="utf-8").splitlines()[:12]:
        if line.startswith("- Tags:"):
            return clean_tags(re.findall(r"#([\w-]+)", line))
    return []


def notes_ready() -> bool:
    """False when the notes folder can't be seen (e.g. Google Drive not started yet)."""
    return NOTES_DIR.is_dir()


NOTES_MISSING = "📁 I can't see your notes folder. Is Google Drive running?"

# ---- when the notes folder is not there (for example Google Drive is not running) --------
# A note is never lost. It is saved on this PC in a "pending" folder, and it is moved to the
# real notes folder by itself as soon as that folder is back. (`notes/` is already private:
# it is in .gitignore, in the deny rules and in the commit check.)

PENDING_DIR = Path(os.getenv("NOTES_PENDING_DIR")
                   or Path(__file__).resolve().parent / "notes" / "pending")


def _log_notes(detail: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] notes: {detail}", flush=True)


def _free_name(folder: Path, name: str) -> Path:
    """`folder / name`, or `name_2.md`, `name_3.md`... if that file is already there."""
    path, n = folder / name, 2
    while path.exists():
        path = folder / f"{Path(name).stem}_{n}.md"
        n += 1
    return path


def write_note_file(name: str, text: str, keep_existing: bool = True) -> Path:
    """Write a note into the notes folder. If that folder can't be used, write it into
    the pending folder on this PC instead (and say so in bot.log). Returns the file.
    An older note with the same name is never overwritten (the new one gets _2, _3...).
    Only keep_existing=False replaces it."""
    try:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        path = _free_name(NOTES_DIR, name) if keep_existing else NOTES_DIR / name
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        path = _free_name(PENDING_DIR, name) if keep_existing else PENDING_DIR / name
        path.write_text(text, encoding="utf-8")
        _log_notes(f"notes folder not available ({exc!r}). Saved {path.name} in {PENDING_DIR} for now")
    add_to_link_index(path)
    return path


def pending_notes() -> list[Path]:
    """Notes saved on this PC while the notes folder was missing."""
    return sorted(PENDING_DIR.glob("*.md")) if PENDING_DIR.is_dir() else []


def is_pending(path: Path) -> bool:
    return Path(path).parent.resolve() == PENDING_DIR.resolve()


def sync_pending() -> int:
    """Move the pending notes into the notes folder, once that folder is back.
    Returns how many were moved. A note is copied, checked, and only then deleted from the
    PC. A note with the same name is never overwritten (the new one gets _2, _3...)."""
    waiting = pending_notes()
    if not waiting or not notes_ready() or PENDING_DIR.resolve() == NOTES_DIR.resolve():
        return 0
    moved = 0
    for source in waiting:
        target = _free_name(NOTES_DIR, source.name)
        try:
            shutil.copy2(source, target)
            if target.stat().st_size != source.stat().st_size:
                target.unlink(missing_ok=True)
                raise OSError("the copy has a different size")
            source.unlink()
        except OSError as exc:
            _log_notes(f"could not move {source.name} to the notes folder: {exc!r}. Will try again")
            break
        moved += 1
    if moved:
        _log_notes(f"moved {moved} note(s) from {PENDING_DIR} to {NOTES_DIR}")
        rebuild_link_index()                      # their folder changed (and maybe their name)
    return moved


def notes_missing_text() -> str:
    """What the bot says when the notes folder can't be seen."""
    waiting = len(pending_notes())
    text = NOTES_MISSING + "\nNew reels are still saved on this PC and move over when it is back."
    if waiting:
        text += f"\n💾 {waiting} note{'s' * (waiting != 1)} waiting on this PC."
    return text


def notes_with_tag(tag: str) -> list[Path]:
    """Notes tagged exactly `tag`, or with tags starting with it
    (so /tag ai finds #ai and #ai-tools). Newest first."""
    tag = clean_tags([tag])[0] if clean_tags([tag]) else ""
    if not tag or not NOTES_DIR.exists():
        return []
    hits = [p for p in NOTES_DIR.glob("*.md")
            if any(t == tag or t.startswith(tag + "-") for t in read_tags(p))]
    return sorted(hits, reverse=True)


TOOL_LINE_RE = re.compile(r"- (.+?)(?: (https?://\S+)| — No (?:repo|link) found|$)")


TOOL_CATALOG_FILE = Path(__file__).with_name("tool_catalog.json")
TOOL_TYPES_SHOWN = ("tool", "model", "repo")          # /tools; /tools all shows every type
# 'Artemis GitHub', 'OpenJarvis Documentation', 'Apinex Integrations': part of the parent tool
TOOL_SUFFIX_RE = re.compile(
    r"\s+(?:github(?:\s+repo(?:sitory)?)?|website|docs|documentation|integrations|example)$", re.I)
GENERIC_REPO_NAMES = {"githubrepository", "githubrepo"}
LINK_SHORTENERS = {"t.co", "tinyurl.com", "bit.ly", "goo.gl", "ow.ly", "buff.ly", "is.gd",
                   "rebrand.ly", "cutt.ly", "shorturl.at", "tiny.cc"}
CHANNEL_RE = re.compile(r"youtube channel|\bchannel$|\bon (?:instagram|tiktok|youtube|x)$", re.I)
COURSE_NAME_RE = re.compile(
    r"\b(?:course|courses|specialization|academy|bootcamp|intensive|tutorial|fundamentals|"
    r"elements of ai|essence of|kaggle|learn:|career essentials|skillsbuild|cs50\w*)\b", re.I)
TOOL_TYPES = ("tool", "model", "repo", "language", "course", "company", "channel", "other")
FILE_NAME_RE = re.compile(r"\.(?:xlsx?|csv|pdf|docx?|pptx?|txt|json|zip)$", re.I)   # 'jobs.xlsx' is a file
SHARED_LINK_LIMIT = 3         # a link used by this many different tools is a guess, not theirs


def load_tool_catalog() -> dict:
    try:
        data = json.loads(TOOL_CATALOG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"aliases": data.get("aliases", {}), "entries": data.get("entries", {}),
            "stoplist": data.get("stoplist", [])}


def tool_link_ok(link: str) -> bool:
    """A real web page: not an API endpoint, a file name, a shortener or text with spaces."""
    if re.search(r"\s|%20|\|", link) or not re.match(r"https?://[^/\s]+\.[a-z]{2,}(?:[/?#]|$)", link, re.I):
        return False
    parts = urlsplit(link)
    host, path = (parts.hostname or "").lower(), parts.path.lower()
    if host.removeprefix("www.") in LINK_SHORTENERS or host.endswith(".pdf") or path.endswith(".pdf"):
        return False
    return not (host.startswith(("api.", "mcp.")) or host.endswith("googleapis.com")
                or path.startswith("/api/") or re.search(r"/v\d+(?:alpha|beta)?\d*(?:/|$)", path))


def tool_type(name: str, link: str) -> str:
    if CHANNEL_RE.search(name):
        return "channel"
    if COURSE_NAME_RE.search(name):
        return "course"
    return "repo" if GITHUB_REPO_RE.search(link) else "tool"


def catalog_maps(catalog: dict | None = None) -> tuple[dict, dict, set]:
    """(aliases, entries, stoplist), keyed by squash(name). One place, so /tools and new notes
    always clean names the same way."""
    cat = catalog if catalog is not None else load_tool_catalog()
    return ({squash(k): v for k, v in cat.get("aliases", {}).items()},
            {squash(k): (k, v) for k, v in cat.get("entries", {}).items()},
            {squash(s) for s in cat.get("stoplist", [])})


def clean_tools(raw: list[tuple[str, str, str]], catalog: dict | None = None) -> list[tuple]:
    """(name, link, note file) rows -> (name, link or 'No repo found', notes count, type).
    Folds aliases and 'X GitHub'-style names into one tool, drops stoplist names and bad links."""
    aliases, entries, stop = catalog_maps(catalog)
    groups: dict[str, dict] = {}
    for name, link, note in raw:
        name, link = name.replace("�", "").strip(), link.strip()
        if "/search?" in link:                        # old notes: a search link is not a repo
            link = ""
        if squash(name) in GENERIC_REPO_NAMES:        # 'GitHub Repository' -> the repo's name
            m = GITHUB_REPO_RE.search(link)
            if not m:
                continue
            name = m.group(2).removesuffix(".git")
        folded = TOOL_SUFFIX_RE.search(name)
        if folded and name[:folded.start()].strip():
            name = name[:folded.start()].strip()
        name = aliases.get(squash(name), name)
        key = squash(name)
        if not key or key in stop or FILE_NAME_RE.search(name):
            continue
        g = groups.setdefault(key, {"names": {}, "notes": set(), "own": [], "folded": []})
        g["names"][name] = g["names"].get(name, 0) + 1
        g["notes"].add(note)
        if link:
            g["folded" if folded else "own"].append(link)
    users: dict[str, set] = {}
    for key, g in groups.items():
        for link in g["own"] + g["folded"]:
            users.setdefault(link.rstrip("/").lower(), set()).add(key)
    shared = {link for link, keys in users.items() if len(keys) >= SHARED_LINK_LIMIT}
    tools = []
    for key, g in groups.items():
        name, info = entries.get(key) or (max(g["names"], key=g["names"].get), {})
        good = [l for l in g["folded"] + g["own"]       # a 'Website'/'GitHub' link is the best guess
                if tool_link_ok(l) and l.rstrip("/").lower() not in shared]
        link = info.get("link") or (good[0] if good else "")
        tools.append((name, link or "No repo found", len(g["notes"]), info.get("type") or tool_type(name, link)))
    return sorted(tools, key=lambda t: (-t[2], t[0].lower()))


def clean_resources(resources: list, catalog: dict | None = None) -> list:
    """A new note's resources, cleaned with the /tools catalog rules: alias -> one name, stoplist,
    file names and non-tool types (company, course, language...) dropped, the catalog link used.
    Any other link must already be one the video showed (drop_invented_links runs first)."""
    aliases, entries, stop = catalog_maps(catalog)
    kept: dict[str, dict] = {}
    for r in resources:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).replace("�", "").strip()
        name = aliases.get(squash(name), name)
        key = squash(name)
        if not key or key in stop or FILE_NAME_RE.search(name):
            continue
        name, info = entries.get(key, (name, {}))
        if info.get("type", "tool") not in TOOL_TYPES_SHOWN:
            continue
        link = str(r.get("link", "")).strip()
        if link and not link.lower().startswith("http") and BARE_DOMAIN_RE.match(link):
            link = "https://" + link                  # 'strix.ai/docs' shown on screen
        link = info.get("link") or (link if tool_link_ok(link) else "")
        if key in kept:                               # 'Claw Code' and 'Claude Code': one line
            kept[key]["link"] = kept[key]["link"] or link
            kept[key]["unverified"] = kept[key].get("unverified") and r.get("unverified")
            continue
        kept[key] = {**r, "name": name, "link": link}
    return [{k: v for k, v in r.items() if k != "unverified" or v} for r in kept.values()]


def raw_tools() -> list[tuple[str, str, str]]:
    """(name, link, note file name) for each line under '## Resources' in every note."""
    rows = []
    folders = [f for f in (NOTES_DIR, PENDING_DIR) if f.is_dir()]
    for path in (p for f in folders for p in f.glob("*.md")):
        for line in note_sections(path).get("Resources", []):
            m = TOOL_LINE_RE.match(line)
            name = m.group(1).strip() if m else ""
            if name and not name.endswith("(unverified)"):
                rows.append((name, m.group(2) or "", path.name))
    return rows


def all_tools() -> list[tuple[str, str, int, str]]:
    """(name, link or 'No repo found', notes count, type), cleaned. Most mentioned first."""
    return clean_tools(raw_tools())


def split_messages(lines: list[str], limit: int = 4000) -> list[str]:
    """Join lines into messages under Telegram's 4096-character limit."""
    messages, current = [], ""
    pieces = (line[i:i + limit] for line in lines for i in range(0, max(len(line), 1), limit))
    for line in pieces:                               # a long line (a transcript) is cut, not lost
        if current and len(current) + 1 + len(line) > limit:
            messages.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    return messages + [current] if current else messages


def all_tags() -> list[tuple[str, int]]:
    """Every tag with how many notes use it, most used first."""
    counts: dict[str, int] = {}
    if NOTES_DIR.exists():
        for p in NOTES_DIR.glob("*.md"):
            for t in read_tags(p):
                counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


RETAG_PROMPT = """Here is a note about a short social media video.
Return ONLY a JSON object: {"tags": [...]} with 3-6 short topic tags,
lowercase, words joined with "-", no "#". Prefer common, reusable tags,
e.g. "python", "ai-tools", "github", "claude", "productivity", "communication".
<<EXISTING>>
NOTE:
<<NOTE>>
"""


def tag_untagged_notes() -> list[tuple[str, list[str]]]:
    """Add tags to older notes that don't have any. Returns (title, tags) per note."""
    done = []
    if not NOTES_DIR.exists():
        return done
    for path in sorted(NOTES_DIR.glob("*.md")):
        if read_tags(path):
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        existing = [t for t, _ in all_tags()][:30]
        hint = ("Reuse these existing tags where they fit: " + ", ".join(existing)) if existing else ""
        prompt = (RETAG_PROMPT.replace("<<EXISTING>>", hint)
                  .replace("<<NOTE>>", note_summary_text(path)[:4000]))
        tags = clean_tags(ask_ollama_json(prompt).get("tags", []))
        if not tags:
            continue
        existing_line = next((i for i, ln in enumerate(lines[:12]) if ln.startswith("- Tags:")), None)
        if existing_line is not None:           # an empty '- Tags:' line: fill it in
            lines[existing_line] = tags_line(tags)
        else:                                   # after the other '- Key: value' header lines
            i = 2
            while i < len(lines) and lines[i].startswith("- "):
                i += 1
            lines.insert(i, tags_line(tags))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        title = lines[0].lstrip("# ").strip()
        done.append((title, tags))
    return done


SECTION_WEIGHT = {"title": 5, "Key points": 3, "Resources": 3, "Summary": 2,
                  "Key quote": 3, "Main lesson": 3, "Habit to try": 2, "Claims to check": 2,
                  "Action items": 2, "Post caption": 1, "Transcript": 1, "On-screen text": 1}


def word_in(word: str, text: str) -> bool:
    """Is `word` in `text` (both lower case)? One or two letters ("ai", "uv") must be a
    whole word, or "ai" would match "said" and "again"."""
    if len(word) <= 2:
        return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None
    return word in text


def search_notes(query: str, limit: int = 15, match_all: bool = True) -> list[dict]:
    """Find notes containing ALL words in the query (case-insensitive),
    or ANY of them with match_all=False (used by /ask).

    Matches in the title/key points rank higher than matches in the transcript.
    Returns newest first among equal scores.
    """
    words = [w for w in query.lower().split() if w]
    if not words or not NOTES_DIR.exists():
        return []
    results = []
    for note in NOTES_DIR.glob("*.md"):
        lines = note.read_text(encoding="utf-8").splitlines()
        check = all if match_all else any
        whole = "\n".join(lines).lower()
        if not words or not check(word_in(w, whole) for w in words):
            continue
        title = lines[0].lstrip("# ").strip() if lines else note.stem
        score, snippet, section = 0, "", "title"
        for line in lines:
            if line.startswith("## "):
                section = line[3:].strip()
                continue
            low = line.lower()
            hits = sum(word_in(w, low) for w in words)
            if hits:
                score += hits * SECTION_WEIGHT.get(section, 1)
                if not snippet and section != "title":
                    snippet = make_snippet(line, words[0])
        results.append({"path": note, "title": title, "date": note.name[:10],
                        "snippet": snippet, "score": score})
    results.sort(key=lambda r: (r["score"], r["path"].name), reverse=True)
    return results[:limit]


def make_snippet(line: str, word: str, width: int = 110) -> str:
    """A short piece of the line around the matched word."""
    line = line.lstrip("- ").replace("[ ] ", "").replace("[x] ", "")
    i = max(line.lower().find(word) - width // 3, 0)
    piece = line[i:i + width].strip()
    return ("…" if i > 0 else "") + piece + ("…" if i + width < len(line) else "")


def note_summary_text(path: Path) -> str:
    """The note without the long Transcript / On-screen text sections."""
    text = path.read_text(encoding="utf-8")
    return text.split("\n## Transcript")[0].strip()


def complete_actions(numbers: list[int], mark: str = "x") -> list[str]:
    """Tick off actions by their /todo number. Returns the texts that were ticked.

    mark="x" -> done:    '- [x] ...'
    mark="-" -> skipped: '- [-] ...' (no longer shown in /todo, but kept in the note)
    """
    actions = open_actions()
    chosen = [actions[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(actions)]
    by_file: dict[Path, list[int]] = {}
    for a in chosen:
        by_file.setdefault(a["path"], []).append(a["line"])
    for path, line_nos in by_file.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in line_nos:
            # Record the date too (Obsidian Tasks style): ✅ = done, ❌ = skipped
            stamp = f" {'✅' if mark == 'x' else '❌'} {datetime.now():%Y-%m-%d}"
            lines[i] = lines[i].replace("- [ ] ", f"- [{mark}] ", 1) + stamp
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [a["action"] for a in chosen]


# ---- "What did you learn?": one line saved under a done action --------------------------------
# After you tick an action, the bot asks for one line. It is saved in the note, right under
# the done action, like this (two spaces in front, so it is NOT a to-do and not an action line):
#   - [x] Read the docs ✅ 2026-11-20
#     - 💡 Learned: the docs have a quick start page
# The to-do code ignores it. /month shows it, and /ask and chat can find it.

LEARNED_PREFIX = "  - 💡 Learned: "
MAX_LEARNING = 300
SKIP_ANSWERS = {"skip", "no", "none", "nothing", "n/a", "na", "later", "pass", "-"}


def clean_learning(text) -> str:
    """One short plain line from what you typed. '' means nothing to save (empty, or "skip")."""
    one = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).split())
    one = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", one)               # a leading bullet or number
    if one.lower().strip(" .!") in SKIP_ANSWERS:
        return ""
    return one if len(one) <= MAX_LEARNING else one[:MAX_LEARNING - 1].rstrip() + "…"


def done_line_text(line: str) -> str | None:
    """'- [x] 🔥 🧠 Do it 📅 2026-11-20 ✅ 2026-11-19' -> 'Do it'. None if it is not a done line."""
    if not line.startswith("- [x] "):
        return None
    rest = re.sub(r"\s*✅ \d{4}-\d{2}-\d{2}\s*$", "", line[6:])
    rest = split_kind(split_priority(rest)[1])[1]
    return split_due(rest)[0].strip()


def find_note_file(name: str) -> Path | None:
    """The note by file name: in the notes folder, or waiting on this PC."""
    for folder in (NOTES_DIR, PENDING_DIR):
        if (folder / name).is_file():
            return folder / name
    return None


def add_learning(note_name: str, action_text: str, learning: str) -> bool:
    """Save one line under the done action. A second answer replaces the first.
    Returns False if there is nothing to save or the done action is not in the note."""
    learning = clean_learning(learning)
    path = find_note_file(note_name)
    if not learning or path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    matches = [i for i, ln in enumerate(lines) if done_line_text(ln) == action_text.strip()]
    if not matches:
        return False
    today = f"✅ {datetime.now():%Y-%m-%d}"
    i = ([m for m in matches if lines[m].rstrip().endswith(today)] or matches)[-1]
    line = LEARNED_PREFIX + learning
    if i + 1 < len(lines) and lines[i + 1].startswith(LEARNED_PREFIX):
        lines[i + 1] = line
    else:
        lines.insert(i + 1, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ---- weekly stats ---------------------------------------------------------

DONE_DATE_RE = re.compile(r"^- \[(x|-)\] .*(✅|❌) (\d{4}-\d{2}-\d{2})\s*$")


def weekly_stats(today: date | None = None, days: int = 7) -> dict:
    """What happened in the last `days` days (see stats_between)."""
    today = today or date.today()
    return stats_between(today - timedelta(days=days - 1), today)


def stats_between(start: date, end: date) -> dict:
    """Reels saved, actions done/skipped (with their texts), categories and tags
    between two dates (inclusive), plus what's still open now."""
    stats = {"start": start, "end": end, "saved": 0, "done": 0, "skipped": 0,
             "categories": {}, "tags": {}, "done_items": [], "learned": []}
    if NOTES_DIR.exists():
        for path in sorted(NOTES_DIR.glob("*.md")):
            try:
                created = date.fromisoformat(path.name[:10])
            except ValueError:
                created = None
            text = path.read_text(encoding="utf-8")
            if created and start <= created <= end:
                stats["saved"] += 1
                m = re.search(r"^- Category: (\w+)", text, re.M)
                cat = m.group(1) if m else "other"
                stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
                for t in read_tags(path):
                    stats["tags"][t] = stats["tags"].get(t, 0) + 1
            note_lines = text.splitlines()
            for n, line in enumerate(note_lines):
                m = DONE_DATE_RE.match(line)
                if m and start <= date.fromisoformat(m.group(3)) <= end:
                    if m.group(1) == "x":
                        stats["done"] += 1
                        item = re.sub(r"^- \[x\] (🔥 |🔽 )?", "", line)
                        stats["done_items"].append(re.sub(r"\s*✅ \S+\s*$", "", item))
                        after = note_lines[n + 1] if n + 1 < len(note_lines) else ""
                        if after.startswith(LEARNED_PREFIX):
                            stats["learned"].append(after[len(LEARNED_PREFIX):].strip())
                    else:
                        stats["skipped"] += 1
    actions = open_actions()
    stats["open"] = len(actions)
    stats["open_high"] = sum(a["priority"] == "high" for a in actions)
    stats["top_tags"] = sorted(stats["tags"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return stats


def month_range(today: date | None = None, previous: bool = False) -> tuple[date, date]:
    """(first day, last day) of this month so far, or of the whole previous month."""
    today = today or date.today()
    first = today.replace(day=1)
    if previous:
        last = first - timedelta(days=1)
        return last.replace(day=1), last
    return first, today


# ---- daily nudge ----------------------------------------------------------

def action_key(path: Path, text: str, repeat: int = 1) -> str:
    """Id made from the note's file name + the action's text (not its line number),
    so it stays the same when lines move, or the priority or due date changes.
    `repeat` tells apart the same text written twice in one note."""
    import hashlib
    key = hashlib.md5(f"{path.name}\n{text}".encode()).hexdigest()[:10]
    return key if repeat <= 1 else f"{key}-{repeat}"


def action_id(action: dict) -> str:
    """Short, stable id for an action (fits in a Telegram button)."""
    return action.get("id") or action_key(action["path"], action["action"])


def legacy_action_id(action: dict) -> str:
    """The old id (file-name hash + line number). Reminders saved before the
    change still use it."""
    import hashlib
    return hashlib.md5(action["path"].name.encode()).hexdigest()[:8] + ":" + str(action["line"])


def find_action(aid: str) -> tuple[int, dict] | None:
    """(position in /todo order starting at 1, action) for an id, or None if
    it's already done/skipped/deleted. Old 'hash:line' ids still work."""
    old_style = ":" in aid
    for n, a in enumerate(open_actions(), start=1):
        if action_id(a) == aid or (old_style and legacy_action_id(a) == aid):
            return n, a
    return None


def note_actions(path: Path) -> list[dict]:
    """A note's open actions under '## Action items', in the order they are written."""
    mine = [a for a in open_actions()
            if a["path"] == path and a["section"] == "Action items"]
    return sorted(mine, key=lambda a: a["line"])


def cleanup_plan() -> dict:
    """What /cleanup would skip. Nothing is changed here.

    * junk: "comment X / DM me / link in bio" actions (they are not real actions);
    * extras: in a note with several actions, all but the best one (highest priority,
      then first). Actions with a due date are always kept;
    * dups: a "Habit to try" and an action in the same note that are the same idea. One of
      the two is skipped: the habit, unless only the habit has a due date.
      Other "Habit to try" lines are always kept.
    `ids` = the action ids to skip; `left` = how many open actions remain after."""
    actions = open_actions()
    junk = [a for a in actions if LOW_PRIORITY_RE.search(a["action"])]
    junk_ids = {action_id(a) for a in junk}
    by_note: dict[Path, list[dict]] = {}
    for a in actions:
        if action_id(a) not in junk_ids and a["section"] == "Action items":
            by_note.setdefault(a["path"], []).append(a)
    extras = []
    for items in by_note.values():
        best = min(items, key=lambda a: (PRIORITY_RANK[a["priority"]], a["line"]))
        extras += [a for a in items if a is not best and not a["due"]]
    gone = junk_ids | {action_id(a) for a in extras}
    kept = [a for a in actions if a["section"] == "Action items" and action_id(a) not in gone]
    dup_ids: set[str] = set()
    for habit in actions:
        if habit["section"] != "Habit to try" or action_id(habit) in gone:
            continue
        twin = next((a for a in kept if a["path"] == habit["path"]
                     and similar_idea(habit["action"], a["action"])), None)
        if twin:
            dup_ids.add(action_id(twin) if habit["due"] and not twin["due"] else action_id(habit))
    ids = [action_id(a) for a in junk + extras] + sorted(dup_ids)
    return {"open": len(actions), "junk": len(junk), "extras": len(extras), "dups": len(dup_ids),
            "ids": ids, "left": len(actions) - len(ids),
            "notes": len({a["path"] for a in actions})}


def skip_actions_by_id(ids: list[str]) -> list[str]:
    """Skip ('- [-]') the open actions with these ids. Already done ones are ignored."""
    wanted = set(ids)
    numbers = [n for n, a in enumerate(open_actions(), start=1) if action_id(a) in wanted]
    return complete_actions(numbers, "-") if numbers else []


# ---- small private state (what was shown when, counters) ---------------------------------

STATE_FILE = Path(os.getenv("BOT_STATE_FILE", "bot_state.json"))


def count_usage(name: str) -> None:
    """Count one use of a command ('todo', '(chat)', '(link)') in the private state file."""
    state = load_state()
    usage = state.setdefault("usage", {})
    usage[name] = usage.get(name, 0) + 1
    state.setdefault("usage_since", date.today().isoformat())
    save_state(state)


def usage_text() -> str:
    """The counts for /usage, most used first."""
    state = load_state()
    usage = state.get("usage", {})
    if not usage:
        return "No counts yet. I start counting from now."
    lines = [f"📊 What you used since {state.get('usage_since', '?')}:"]
    lines += [f"{n}× {name if name.startswith('(') else '/' + name}"
              for name, n in sorted(usage.items(), key=lambda kv: (-kv[1], kv[0]))]
    return "\n".join(lines)


def load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


# ---- what you need to do an action: link and key points ----------------------------------

URL_RE = re.compile(r"https?://[^\s)>\]]+")


def action_details(action: dict) -> dict:
    """The main link and two key points of the action's note, for the nudge.
    {'link': url or '', 'is_reel': True if the link is the saved reel, 'points': [...]}.
    A real link from Resources is preferred over a Google search link."""
    s = note_sections(action["path"])
    urls = [u.rstrip(".,;:!?") for line in s.get("Resources", []) for u in URL_RE.findall(line)]
    real = [u for u in urls if "/search?" not in u]
    link, is_reel = (real[0], False) if real else (s.get("source", "").strip(), True)
    if not link.startswith("http"):
        link = ""
    points = [line.lstrip("- ").strip() for line in s.get("Key points", [])]
    points = [x if len(x) <= 160 else x[:157].rstrip() + "..." for x in points[:2]]
    return {"link": link, "is_reel": is_reel and bool(link), "points": points}


def save_one_candidate(exclude: Path | None = None, today: date | None = None) -> dict | None:
    """'Save one, do one': when a new reel is saved and you ticked nothing in the last
    7 days, return ONE older action to ask about (top of /todo, not from the new note).
    At most once a day. Returns None if it should not ask."""
    today = today or date.today()
    state = load_state()
    if state.get("save_one") == today.isoformat():
        return None
    if weekly_stats(today)["done"] > 0:
        return None
    action = next((a for a in open_actions() if a["path"] != exclude), None)
    if action is None:
        return None
    state["save_one"] = today.isoformat()
    save_state(state)
    return action


# ---- undo for /cleanup ---------------------------------------------------------------

CLEANUP_UNDO_FILE = Path(os.getenv("CLEANUP_UNDO_FILE", "cleanup_undo.json"))
STAMP_RE = re.compile(r" ❌ \d{4}-\d{2}-\d{2}$")


def skip_with_undo(ids: list[str]) -> list[str]:
    """Skip these actions like skip_actions_by_id, and remember their exact lines,
    so undo_cleanup() can put them back. Only the LAST clean-up can be undone."""
    wanted = set(ids)
    saved = []
    for a in open_actions():
        if action_id(a) in wanted:
            line = a["path"].read_text(encoding="utf-8").splitlines()[a["line"]]
            saved.append({"path": a["path"].name, "line": line})
    skipped = skip_actions_by_id(ids)
    if skipped:
        CLEANUP_UNDO_FILE.write_text(json.dumps({"when": datetime.now().isoformat(timespec="seconds"),
                                                 "items": saved}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    return skipped


def can_undo_cleanup() -> int:
    """How many actions the last /cleanup could put back (0 = nothing to undo)."""
    try:
        return len(json.loads(CLEANUP_UNDO_FILE.read_text(encoding="utf-8"))["items"])
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return 0


def undo_cleanup() -> int:
    """Put back the actions skipped by the last /cleanup. Returns how many came back.
    An action you ticked or changed since then is left alone."""
    try:
        items = json.loads(CLEANUP_UNDO_FILE.read_text(encoding="utf-8"))["items"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return 0
    restored = 0
    for item in items:
        path = NOTES_DIR / item["path"]
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        skipped_form = "- [-] " + item["line"][6:]
        for i, line in enumerate(lines):
            if line.startswith(skipped_form) and STAMP_RE.fullmatch(line[len(skipped_form):]):
                lines[i] = item["line"]
                restored += 1
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                break
    CLEANUP_UNDO_FILE.unlink(missing_ok=True)
    return restored


def current_numbers(shown_ids: list[str] | None, numbers: list[int]) -> list[int]:
    """Turn the numbers you SAW in your last /todo into today's /todo positions.

    `shown_ids` = the action ids of that /todo list, in order. An action that is
    already done or skipped is left out. With no saved list, numbers are used as-is."""
    if not shown_ids:
        return numbers
    now = {action_id(a): n for n, a in enumerate(open_actions(), start=1)}
    return [now[shown_ids[n - 1]] for n in numbers
            if 1 <= n <= len(shown_ids) and shown_ids[n - 1] in now]


def pick_nudge(after: str | None = None, today: date | None = None) -> dict | None:
    """Today's one action: from the highest priority level that has any,
    rotating day by day so an ignored action doesn't block the rest.
    With `after`, return the next action in the list instead ('Another one')."""
    actions = open_actions()
    if not actions:
        return None
    if after:
        ids = [action_id(a) for a in actions]
        i = ids.index(after) + 1 if after in ids else 0
        return actions[i % len(actions)]
    today = today or date.today()
    due_now = [a for a in actions if a["due"] and a["due"] <= today]
    if due_now:                     # overdue / due today beats everything
        return due_now[0]
    top = actions[0]["priority"]
    bucket = [a for a in actions if a["priority"] == top and not a["due"]] or \
        [a for a in actions if a["priority"] == top]
    day = today.toordinal()
    return bucket[day % len(bucket)]


# ---- /ask: answer questions from your notes --------------------------------

STOPWORDS = set("""a an and are as at be but by can could do does for from had has have how
i if in into is it its me my of on or should so than that the their them then there these
they this to was we were what when where which who why will with would you your about any
all also just like get got some tell show give find need want use using used best good
which did save saved say said saw talk talked mention mentioned watch watched notes note
reel reels video videos""".split())

# Short words that ARE real topics (a plain length rule would drop "ai" and "uv").
SHORT_TOPIC_WORDS = {"ai", "uv", "ml", "js", "ts", "c#", "ui", "ux", "db", "qa", "vr", "3d"}

ASK_PROMPT = """Answer my question using ONLY the notes below. They are my own notes
from short videos I saved. Rules:
- Use only facts written in these notes. Do not add outside knowledge.
- If the notes don't answer the question, the answer must be exactly:
  "I couldn't find that in your notes."
- Keep it short (under 150 words) and in plain, simple English.
- Copy tool names, commands and links exactly as they are written in the notes.
Return ONLY a JSON object: {"answer": "...", "sources": [numbers of the notes you used]}

QUESTION: <<QUESTION>>

NOTES:
<<NOTES>>
"""
NOT_FOUND = "I couldn't find that in your notes."


def question_words(question: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9+#-]*", question.lower())
    return [w for w in words
            if (len(w) >= 3 or w in SHORT_TOPIC_WORDS) and w not in STOPWORDS]


def relevant_notes(text: str, max_notes: int = 5) -> list[dict]:
    """Notes matching the meaningful words in `text`; weak matches dropped."""
    words = question_words(text)
    hits = search_notes(" ".join(words), limit=max_notes, match_all=False) if words else []
    if hits:  # keep only notes that match reasonably well compared to the best one
        best = hits[0]["score"]
        hits = [h for h in hits if h["score"] >= max(1, best * 0.25)]
    return hits


def answer_question(question: str, max_notes: int = 5) -> tuple[str, list[Path]]:
    """Answer from your notes. Returns (answer, notes it was based on).
    If no note matches, the AI isn't asked at all (so it can't make something up)."""
    hits = relevant_notes(question, max_notes)
    if not hits:
        return NOT_FOUND, []
    blocks = [f"[Note {n}] {note_summary_text(h['path'])[:2500]}"
              for n, h in enumerate(hits, start=1)]
    prompt = (ASK_PROMPT.replace("<<QUESTION>>", question.strip())
                        .replace("<<NOTES>>", "\n\n".join(blocks)))
    reply = ask_ollama_json(prompt)
    answer = str(reply.get("answer", "")).strip() or NOT_FOUND
    if answer == NOT_FOUND:
        return NOT_FOUND, []
    numbers = [n for n in reply.get("sources", []) if isinstance(n, int) and 1 <= n <= len(hits)]
    # If the AI didn't say which notes it used, show all the notes it was given
    used = [hits[n - 1]["path"] for n in dict.fromkeys(numbers)] or [h["path"] for h in hits]
    return answer, used


# ---- reminders ------------------------------------------------------------

REMINDERS_FILE = Path(os.getenv("REMINDERS_FILE", "reminders.json"))
DEFAULT_REMIND_HOUR = 9
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _parse_time(text: str) -> tuple[int, int] | None:
    """'5pm', '5:30 pm', '17:00', 'at 9am' -> (hour, minute)."""
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
    if m:
        hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
        return (hour + 12 if m.group(3) == "pm" else hour), minute
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    if "tonight" in text or "evening" in text:
        return 19, 0
    if "afternoon" in text:
        return 14, 0
    if "morning" in text:
        return 9, 0
    return None


def parse_when(text: str, now: datetime) -> datetime | None:
    """Turn everyday words into a date and time (in now's timezone).

    Understands: today, tonight, tomorrow, weekday names (friday, fri),
    next week, in 3 days / 2 hours / 1 week, 2026-11-20, 20/11, 20/11/2026,
    20 nov, nov 20 — plus an optional time (5pm, 17:30, morning).
    No time given = 9:00 am. Returns None if it can't understand it.
    """
    t = text.lower().strip()
    tm = _parse_time(t)
    hour, minute = tm or (DEFAULT_REMIND_HOUR, 0)

    def at(day) -> datetime:
        return now.replace(year=day.year, month=day.month, day=day.day,
                           hour=hour, minute=minute, second=0, microsecond=0)

    m = re.search(r"\bin\s+(\d+)\s*(minute|min|hour|hr|day|week)s?\b", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit in ("minute", "min"):
            return now + timedelta(minutes=n)
        if unit in ("hour", "hr"):
            return now + timedelta(hours=n)
        days = n * (7 if unit == "week" else 1)
        return at(now.date() + timedelta(days=days))

    day = None
    if re.search(r"\b(today|tonight)\b", t):
        day = now.date()
    elif "tomorrow" in t:
        day = now.date() + timedelta(days=1)
    elif "next week" in t:                       # next Monday
        day = now.date() + timedelta(days=7 - now.weekday())
    else:
        for i, name in enumerate(WEEKDAYS):
            if re.search(rf"\b({name}|{name[:3]})\b", t):
                ahead = (i - now.weekday()) % 7
                if ahead == 0 and at(now.date()) <= now:
                    ahead = 7                     # 'friday' on a Friday afternoon = next week
                day = now.date() + timedelta(days=ahead)
                break
    if day is None:
        m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
        if m:
            day = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)   # 20/11 (day first)
            if m:
                year = int(m.group(3)) if m.group(3) else now.year
                year += 2000 if year < 100 else 0
                day = _safe_date(year, int(m.group(2)), int(m.group(1)), now, m.group(3))
            else:
                mon = "|".join(MONTHS)
                m = (re.search(rf"\b(\d{{1,2}})\s*({mon})[a-z]*\b", t)
                     or re.search(rf"\b({mon})[a-z]*\s*(\d{{1,2}})\b", t))
                if m:
                    a, b = m.groups()
                    d, mname = (a, b) if a.isdigit() else (b, a)
                    day = _safe_date(now.year, MONTHS.index(mname[:3]) + 1, int(d), now, None)
    if day is None:
        if tm is None:
            return None
        day = now.date()                          # just a time: today, or tomorrow if passed
        if at(day) <= now:
            day += timedelta(days=1)
    return at(day)


def _safe_date(year, month, day, now=None, year_given="yes"):
    """A real calendar date or None. Without a year, a date already past
    this year means next year (e.g. '5/1' in November = 5 January next year)."""
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if now is not None and not year_given and d < now.date():
        d = date(year + 1, month, day)
    return d


def load_reminders() -> list[dict]:
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def save_reminders(reminders: list[dict]) -> None:
    REMINDERS_FILE.write_text(json.dumps(reminders, indent=2, ensure_ascii=False),
                              encoding="utf-8")


def add_reminder(action: dict, when: datetime) -> dict:
    """Remember to remind about an action. Stored by action_id, so it still
    points to the right action after /todo numbers change."""
    reminders = [r for r in load_reminders()
                 if r["action_id"] not in (action_id(action), legacy_action_id(action))]
    reminder = {"action_id": action_id(action), "text": action["action"],
                "when": when.isoformat()}
    reminders.append(reminder)
    save_reminders(sorted(reminders, key=lambda r: r["when"]))
    return reminder


def remove_reminder(aid: str) -> bool:
    reminders = load_reminders()
    kept = [r for r in reminders if r["action_id"] != aid]
    save_reminders(kept)
    return len(kept) != len(reminders)


# ---- catch-up: scheduled messages missed while the PC was off or asleep -----------

SENT_JOBS_FILE = Path(os.getenv("SENT_JOBS_FILE", "sent_jobs.json"))


def load_sent_jobs() -> dict:
    """{'nudge': '2026-11-16', 'weekly': '2026-11-15', ...}: the last time slot
    each scheduled message was sent for."""
    try:
        data = json.loads(SENT_JOBS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_sent_jobs(sent: dict) -> None:
    SENT_JOBS_FILE.write_text(json.dumps(sent, indent=2), encoding="utf-8")


def last_slot(rule: dict, now: datetime) -> date | None:
    """The newest day this message should already have gone out, or None.

    rule = {"every": "day", "at": (8, 0)}                 → today, once 8:00 has passed
           {"every": "week", "weekday": 6, "at": (9, 0)}  → the last Sunday 9:00 (Monday = 0)
           {"every": "month", "day": 1, "at": (9, 30)}    → the last 1st of a month, 9:30
    A daily message is never sent for yesterday: today's one is coming anyway."""
    hour, minute = rule["at"]
    passed_today = (now.hour, now.minute) >= (hour, minute)
    today = now.date()
    if rule["every"] == "day":
        return today if passed_today else None
    if rule["every"] == "week":
        back = (today.weekday() - rule["weekday"]) % 7
        if back == 0 and not passed_today:
            back = 7
        return today - timedelta(days=back)
    if rule["every"] == "month":
        if today.day > rule["day"] or (today.day == rule["day"] and passed_today):
            return today.replace(day=rule["day"])
        return (today.replace(day=1) - timedelta(days=1)).replace(day=rule["day"])
    return None


def due_jobs(now: datetime, sent: dict, rules: dict) -> list[tuple[str, str]]:
    """Which scheduled messages should go out now: [(kind, slot date)].

    A kind seen for the first time is only written into `sent` (no message), so the
    first start after this update doesn't send a pile of old messages."""
    due = []
    for kind, rule in rules.items():
        slot = last_slot(rule, now)
        if slot is None:
            continue
        slot = slot.isoformat()
        if kind not in sent:
            sent[kind] = slot
        elif str(sent[kind]) < slot:
            due.append((kind, slot))
    return due


# ---- chat mode: talk to the bot about your notes ----------------------------

CHAT_SYSTEM = """You are Reel Notes, a friendly personal assistant inside Telegram.
You help me use the notes I saved from short videos (tech, programming, motivation).
How to talk:
- Warm, encouraging and simple English: short sentences, easy words.
- Short replies: usually 2-6 sentences, or a short list. No long essays.
- For facts about tools, commands, links, quotes or tips, use ONLY the notes below.
  Copy names, commands and links exactly. If the notes don't cover it, say
  "I don't have that in your notes" and suggest saving a reel about it.
  Never invent tools, links, numbers or quotes.
- NEVER invent steps, install instructions, menus or settings. Only give steps that
  are written in the notes. If the notes have no steps, say so and suggest
  "/plan <number>" to get a ready-made prompt for Claude.
- If a note lists something under "Claims to check", say it's not verified yet.
- Small talk (hello, thanks, how are you) is fine: answer briefly and kindly.
- When it helps, suggest a next step, e.g. "Want a reminder? /remind 2 friday".
- Use plain text only, no Markdown symbols like ** or ##.
- You CANNOT change tasks or notes in this chat. Never say you marked, ticked, skipped,
  completed, deleted, added or changed anything. Instead suggest the right command,
  e.g. "Send /todo, then /done 2" or "Say: I finished the <task name>".

MY NOTES FOR THIS MESSAGE:
<<NOTES>>
"""
CHAT_HISTORY_TURNS = 6          # remembered back-and-forth messages
FOLLOW_UP_RE = re.compile(r"\b(it|its|that|this|these|those|them|they|one|first|second|"
                          r"third|last|more|else|again|next|which|same|above)\b", re.I)


def is_follow_up(message: str) -> bool:
    """Short message that points back at the last answer ('which one first?')."""
    return bool(FOLLOW_UP_RE.search(message)) and len(question_words(message)) <= 4


def chat_reply(message: str, history: list[dict], max_notes: int = 4) -> tuple[str, list[Path]]:
    """Reply to a normal chat message using matching notes and recent history.

    history = [{"role": "user"|"assistant", "content": "..."}] (oldest first).
    Notes are found from this message AND the previous user message, so
    follow-ups like "what about the second one?" still find the right notes.
    Returns (reply text, notes that were given to the AI).
    """
    previous = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
    if previous and is_follow_up(message):
        # "which one should I try first?" is about the notes we were just discussing
        hits = relevant_notes(previous + " " + message, max_notes)
    else:
        hits = relevant_notes(message, max_notes) or relevant_notes(previous + " " + message,
                                                                    max_notes)
    notes = "\n\n".join(f"[Note {n}: {h['title']}]\n{note_summary_text(h['path'])[:2000]}"
                         for n, h in enumerate(hits, start=1)) or "(no matching notes)"
    messages = [{"role": "system", "content": CHAT_SYSTEM.replace("<<NOTES>>", notes)}]
    messages += history[-CHAT_HISTORY_TURNS * 2:]
    messages.append({"role": "user", "content": message})
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={"model": OLLAMA_MODEL, "messages": messages, "stream": False,
              **ollama_extra(), "options": {"temperature": 0.4, "num_ctx": 8192}},
        timeout=600,
    )
    resp.raise_for_status()
    reply = strip_thinking(resp.json().get("message", {}).get("content") or "")
    reply = re.sub(r"\*\*|__|^#+\s*", "", reply, flags=re.M)   # strip Markdown leftovers
    if CLAIMED_ACTION_RE.search(reply):          # the model said it did something: it can't
        reply = NO_CHAT_ACTIONS
    return reply or "Sorry, I couldn't think of an answer. Can you ask another way?", \
        [h["path"] for h in hits]


# ---- chat actions: "I finished the Hallmark task" -> a real /done, after a button ----------

CLAIMED_ACTION_RE = re.compile(
    r"\bI(?:'ve| have|'ll| will)?\s+(?:just\s+|now\s+|already\s+)?(?:marked|ticked|checked off|"
    r"completed|skipped|deleted|removed|added|updated|changed|set|moved|saved)\b"    # "I've marked it"
    r"|\b(?:is|are|was|were|has been|have been)\s+(?:now\s+)?(?:marked|ticked|checked off|completed|"
    r"skipped|deleted|removed)\b"                                                     # "it has been completed"
    r"|\b(?:is|are|has been|have been) now done\b|\b(?:has|have) been done\b"         # "it is now done"
    r"|(?:^|[.!?]\s+)done!|\ball set\b", re.I | re.M)                                 # "Done!" (not "Well done!")
NO_CHAT_ACTIONS = "I can't change tasks in chat. Try: I finished <task>, or /done."
# messages without one of these words never ask the AI for an intent (saves one AI call per chat)
TASK_HINT_RE = re.compile(
    r"\b(?:finish|finished|complete|completed|done|did|tick|ticked|mark|marked|skip|todo|to-do|list|"
    r"stats|find|show|open|tools?|dupes?|twice)\b", re.I)
CHAT_INTENTS = ("done", "skip", "todo", "stats", "find_note", "show_note", "dupes", "tools", "chat")
INTENT_PROMPT = """You sort one message sent to my notes bot. Return ONLY JSON:
{"intent": "...", "words": "..."}
intent is one of:
- "done": I say I finished or did a task ("I finished the Hallmark task", "done with the strix one")
- "skip": I want to drop a task ("skip the BLA one", "I won't do the Notion task")
- "todo": I want my task list ("show my todo list", "what's left to do?")
- "stats": I want my progress numbers ("how did I do this week?")
- "find_note": I want to find notes about something ("find my notes about Claude memory")
- "show_note": I want to open one note ("open the Strix note", "show me the note about Higgsfield")
- "dupes": I want videos I saved twice
- "tools": I want the list of tools in my notes
- "chat": anything else (questions, small talk)
words: the few words that name the task or topic, copied from the message (e.g. "Hallmark").
Use "" when there are none.

MESSAGE: <<MESSAGE>>"""
INTENT_SCHEMA = {"type": "object", "properties": {"intent": {"type": "string", "enum": list(CHAT_INTENTS)},
                                                  "words": {"type": "string"}},
                 "required": ["intent", "words"]}
# words that say what to do, not which task it is
TASK_FILLER = {"task", "tasks", "action", "item", "one", "thing", "todo", "finish", "finished", "done",
               "skip", "complete", "completed", "mark", "tick", "drop", "note", "please"}


def detect_intent(message: str) -> dict:
    """{'intent': one of CHAT_INTENTS, 'words': '...'} from the local model. Unsure -> 'chat'.
    A message with no task or command word is chat, with no AI call."""
    if not TASK_HINT_RE.search(message):
        return {"intent": "chat", "words": ""}
    data = ask_ollama_json(INTENT_PROMPT.replace("<<MESSAGE>>", message), schema=INTENT_SCHEMA)
    intent = str(data.get("intent", "")).strip().lower()
    return {"intent": intent if intent in CHAT_INTENTS else "chat", "words": text_of(data.get("words"))}


def _word_hit(word: str, targets: set[str]) -> bool:
    """'hallmark' hits 'hallmark'; small typos ('halmark') hit too."""
    return word in targets or any(
        len(t) >= 4 and difflib.SequenceMatcher(None, word, t).ratio() >= 0.85 for t in targets)


def match_actions(words: str, limit: int = 3) -> list[dict]:
    """Open actions that best match the words, best first, by action text and note title.
    Up to `limit` actions that share at least half of the words come back, so the user can
    step through them with "Not this one"."""
    query = {w for w in idea_words(words) if w not in TASK_FILLER} or {
        w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", words) if w.lower() not in TASK_FILLER}
    if not query:
        return []
    scored = []
    for a in open_actions():
        targets = idea_words(a["action"]) | idea_words(a["title"]) | {
            w.lower() for w in re.findall(r"[A-Za-z0-9]{2,}", a["action"] + " " + a["title"])}
        score = sum(_word_hit(w, targets) for w in query) / len(query)
        if score >= 0.5:
            scored.append((score, a))
    scored.sort(key=lambda s: -s[0])                 # stable: /todo order inside one score
    return [a for _, a in scored[:limit]]


# ---- /plan: turn a note into a ready-to-paste prompt for Claude ---------------

def note_sections(path: Path) -> dict:
    """{'title':..., 'category':..., 'source':..., 'Summary': [lines], ...}."""
    lines = path.read_text(encoding="utf-8").splitlines()
    sections = {"title": lines[0].lstrip("# ").strip() if lines else path.stem}
    current = None
    for line in lines[1:]:
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is None:
            m = re.match(r"- (Category|Source|Creator): (.*)", line)
            if m:
                sections[m.group(1).lower()] = m.group(2).strip()
        elif line.strip():
            sections[current].append(line.strip())
    return sections


ACT_AS = {
    "programming": "an experienced software engineer and AI-tools expert",
    "tech": "an experienced tech expert who explains AI tools clearly",
    "motivation": "a supportive personal coach who turns ideas into small habits",
}


def plan_parts(path: Path) -> dict:
    """What a plan needs from one note (only the note's own content)."""
    s = note_sections(path)
    actions = drop_repeats([split_due(re.sub(r"^- \[ \] (?:🔥 |🔽 )?(?:[🤖🧠🔗] )?", "", line))[0]
                            for line in s.get("Action items", []) + s.get("Habit to try", [])
                            if line.startswith("- [ ] ")])
    # "Comment X / DM me / link in bio" are ways to reach the creator: Claude can't do
    # them, so they go into a separate "backup" part instead of the actions.
    all_points = [line.lstrip("- ") for line in s.get("Key points", [])]
    offers = list(dict.fromkeys(
        [line[len("- Offer: "):] for line in s.get("From the creator", [])
         if line.startswith("- Offer: ")]
        + creator_offers(actions + all_points)))
    return {
        "title": s["title"], "category": s.get("category", "other"),
        "source": s.get("source", ""), "creator": s.get("creator", ""),
        "summary": " ".join(s.get("Summary", [])),
        "actions": [a for a in actions if not LOW_PRIORITY_RE.search(a)],
        "key_points": [k for k in all_points if not LOW_PRIORITY_RE.search(k)],
        "resources": [plan_resource(line.lstrip("- ")) for line in s.get("Resources", [])],
        "claims": [line.lstrip("- ").replace("⚠️ ", "") for line in s.get("Claims to check", [])],
        "offers": offers,
    }


def plan_resource(line: str) -> str:
    """Shorter resource line for plans: search links and long descriptions removed
    (Claude can find a tool by name). Real links, stars and ⚠️ warnings stay."""
    line = re.sub(r"\s*https://(?:www\.google\.com|github\.com)/search\?\S+", "", line)
    return re.sub(r"\s+—\s.*$", "", line).strip()


PLAN_CONSTRAINTS = [
    "- First check that each tool or link is real, current and safe to use; "
    "tell me if something looks outdated, unsafe or like a scam.",
    "- Prefer official sources (GitHub repos, official docs) over the video's claims."]
PLAN_FOOTER = ["- I use Windows. Give exact commands I can copy.",
               "- Use simple English: short sentences, easy words.",
               "- Ask me before installing anything or changing my files or accounts."]


def make_plan(path: Path | list[Path], my_goal: str = "") -> str:
    """A prompt in ART format (Act as / Request / Terms: Instructions, Constraints,
    Output) built ONLY from the notes' own content — no AI, so nothing is invented.
    Give one note, or a list of notes for ONE combined plan."""
    paths = path if isinstance(path, list) else [path]
    if len(paths) > 1:
        return make_combined_plan(paths, my_goal)
    return plan_text(plan_parts(paths[0]), my_goal)


def make_action_prompt(action: dict, my_goal: str = "") -> str:
    """A prompt for ONE action (the 🤖 Get prompt button, /prompt 3). Same ART format,
    built only from the action's note, with the context that note gives."""
    n = plan_parts(action["path"])
    return plan_text(n, my_goal, focus=action["action"])


def plan_text(n: dict, my_goal: str = "", focus: str = "") -> str:
    """The ART prompt for one note's parts. `focus` = ONE action to do instead of all."""
    if focus:
        out = [f"ACT AS: {ACT_AS.get(n['category'], 'a helpful expert assistant')}.", "",
               f"REQUEST: Help me do ONE thing I saved from a short video: \"{focus}\"",
               f"The video was called \"{n['title']}\"."]
    else:
        out = [f"ACT AS: {ACT_AS.get(n['category'], 'a helpful expert assistant')}.", "",
               f"REQUEST: Help me act on what I learned from a short video: \"{n['title']}\"."]
    if n["summary"]:
        out.append(f"What it was about: {n['summary']}")
    if my_goal:
        out.append(f"My goal: {my_goal}")
    out += ["", "TERMS", "", "Instructions:"]
    if focus:
        out += [f"Help me finish this one action: {focus}",
                "Start with a first step that takes under 5 minutes."]
    elif n["actions"]:
        out.append("Help me complete these actions, in a sensible order:")
        out += [f"{i}. {a}" for i, a in enumerate(n["actions"], 1)]
    else:
        out.append("Suggest 3-5 practical actions I can take from this video, then help me do them.")
    if n["key_points"]:
        out += ["", "What the video said (key points):"] + [f"- {k}" for k in n["key_points"][:7]]
    if n["resources"]:
        out += ["", "Tools and links from the video:"] + [f"- {r}" for r in n["resources"][:8]]
    out += ["", "Constraints:"] + PLAN_CONSTRAINTS
    out += [f"- Verify this claim before relying on it: {c}" for c in n["claims"]]
    out += PLAN_FOOTER
    out += ["", "Output:",
            "- A step-by-step plan: for each step, what to do, why, and how long it takes.",
            "- Exact commands or settings where needed.",
            "- A short checklist at the end that I can tick off."]
    if n["offers"] or n["creator"]:
        out += ["", "Backup if a link above is wrong, missing or dead:"]
        if n["creator"]:
            out.append(f"- The video's creator: {n['creator']}")
        out += [f"- The creator offered: {o}" for o in n["offers"]]
        out.append("- Tell me if I should ask the creator for the correct link.")
    if n["source"]:
        out += ["", f"(Source video: {n['source']})"]
    return "\n".join(out)


MAX_PLAN_NOTES = 5


def make_combined_plan(paths: list[Path], my_goal: str = "") -> str:
    """One plan from several notes: overlapping steps merged, one order across videos."""
    notes = [plan_parts(p) for p in paths[:MAX_PLAN_NOTES]]
    cats = [n["category"] for n in notes]
    category = max(set(cats), key=cats.count)          # the most common category
    out = [f"ACT AS: {ACT_AS.get(category, 'a helpful expert assistant')}.", "",
           f"REQUEST: Help me act on what I learned from {len(notes)} short videos, "
           "as ONE combined plan."]
    if my_goal:
        out.append(f"My goal: {my_goal}")
    out += ["", "TERMS", "", "Instructions:",
            "- Merge actions that overlap (do them once), and put everything in a sensible "
            "order across all the videos.",
            "- Say which video (V1, V2...) each step comes from.",
            "- If two videos disagree, tell me and recommend one."]
    for i, n in enumerate(notes, 1):
        out += ["", f"V{i}: \"{n['title']}\""]
        if n["summary"]:
            out.append(f"About: {n['summary']}")
        if n["actions"]:
            out.append("Actions:")
            out += [f"- {a}" for a in n["actions"]]
        if n["key_points"]:
            out.append("Key points:")
            out += [f"- {k}" for k in n["key_points"][:4]]
        if n["resources"]:
            out.append("Tools and links:")
            out += [f"- {r}" for r in n["resources"][:5]]
    claims = [(i, c) for i, n in enumerate(notes, 1) for c in n["claims"]]
    out += ["", "Constraints:"] + PLAN_CONSTRAINTS
    out += [f"- Verify this claim (V{i}) before relying on it: {c}" for i, c in claims]
    out += PLAN_FOOTER
    out += ["", "Output:",
            "- One step-by-step plan: for each step, what to do, why, which video it's "
            "from, and how long it takes.",
            "- Exact commands or settings where needed.",
            "- A short checklist at the end that I can tick off."]
    backup = [(i, n) for i, n in enumerate(notes, 1) if n["creator"] or n["offers"]]
    if backup:
        out += ["", "Backup if a link above is wrong, missing or dead:"]
        for i, n in backup:
            who = n["creator"] or "the creator"
            offers = "; ".join(n["offers"])
            out.append(f"- V{i} creator: {who}" + (f" (offered: {offers})" if offers else ""))
        out.append("- Tell me if I should ask a creator for the correct link.")
    sources = [f"V{i}: {n['source']}" for i, n in enumerate(notes, 1) if n["source"]]
    if sources:
        out += ["", "(Source videos: " + " · ".join(sources) + ")"]
    return "\n".join(out)


# ---- resurface an old note (spaced repetition) ------------------------------------

def pick_resurface(today: date | None = None, min_age_days: int = 7,
                   shift: int = 0) -> dict | None:
    """One older note to look at again, rotating week by week (shift = 'another one').
    Returns {'path', 'title', 'text', 'kind', 'age_days'} or None."""
    today = today or date.today()
    if not NOTES_DIR.exists():
        return None
    old = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        try:
            saved = date.fromisoformat(path.name[:10])
        except ValueError:
            continue
        if (today - saved).days >= min_age_days:
            old.append((path, saved))
    if not old:
        return None
    week = today.toordinal() // 7 + shift
    path, saved = old[week % len(old)]
    s = note_sections(path)
    quote = [line.lstrip("> ").replace("*(paraphrased)*", "").strip()
             for line in s.get("Key quote", [])]
    points = [line.lstrip("- ") for line in s.get("Key points", [])]
    lesson = s.get("Main lesson", [])
    if quote and quote[0]:
        text, kind = quote[0], "quote"
    elif points:
        text, kind = points[week % len(points)], "point"
    elif lesson:
        text, kind = lesson[0], "lesson"
    else:
        text, kind = " ".join(s.get("Summary", [])), "summary"
    return {"path": path, "title": s["title"], "text": text, "kind": kind,
            "age_days": (today - saved).days}


# ---- /redo: make a note again ---------------------------------------------

OLD_DIR_NAME = "old"


def note_source(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines()[:10]:
        if line.startswith("- Source: "):
            return line[10:].strip()
    return ""


def find_note_for_redo(query: str = "") -> Path | None:
    """Newest note, or the newest whose title/file name contains the words."""
    if not NOTES_DIR.exists():
        return None
    notes = sorted(NOTES_DIR.glob("*.md"), reverse=True)
    words = [w for w in query.lower().split() if w]
    for path in notes:
        title = path.read_text(encoding="utf-8").split("\n", 1)[0].lower()
        if all(w in title or w in path.name.lower() for w in words):
            return path
    return None


def archive_note(path: Path) -> Path:
    """Move an old note into NOTES_DIR/old/ (kept, but hidden from /todo, /search...)."""
    old_dir = NOTES_DIR / OLD_DIR_NAME
    old_dir.mkdir(exist_ok=True)
    name = path.with_suffix(".md")
    target = old_dir / name.name
    if target.exists():
        target = old_dir / f"{name.stem}_{datetime.now():%H%M%S}.md"
    path.replace(target)
    return target


# ---- /redo fast: make a note again from the text saved in it (no download) ---------------
# A note keeps what it was made from: "## Transcript", "## On-screen text" (in a code fence)
# and "## Post caption". /redo fast gives that text to the AI again, so an older note gets
# the new format in seconds: no download, no Whisper, no OCR. It works for screenshot and
# video-file notes too. Your history is kept: done and skipped actions (with their
# "Learned" line) are copied into the new note, and an action you already did or skipped
# is not opened again. The note keeps its date and your tags.

class RedoNotPossible(RuntimeError):
    """The message is ready to show in Telegram."""


MSG_NO_SAVED_TEXT = ("This note has no saved transcript or screen text, so I can't make it "
                     "again from the note. Use /redo to download it again.")
FINISHED_RE = re.compile(r"^- \[(x|-)\] ")


def _header_value(lines: list[str], key: str) -> str:
    """'- Key: value' from the top of a note (before the first '## ' heading)."""
    for line in lines:
        if line.startswith("## "):
            break
        if line.startswith(f"- {key}: "):
            return line[len(key) + 4:].strip()
    return ""


def _slide_counts(text: str) -> tuple[int, int]:
    """'5 (3 videos, 2 photos)' -> (3, 2); '4 videos' -> (4, 0); '2 photos' -> (0, 2); '' -> (1, 0)."""
    videos = re.search(r"(\d+) videos?", text)
    photos = re.search(r"(\d+) photos?", text)
    return (int(videos.group(1)) if videos else (0 if photos else 1),
            int(photos.group(1)) if photos else 0)


def _note_date(path: Path, lines: list[str]) -> datetime | None:
    for value, form in ((_header_value(lines, "Date"), "%Y-%m-%d %H:%M"), (path.name[:15], "%Y-%m-%d_%H%M")):
        try:
            return datetime.strptime(value, form)
        except ValueError:
            continue
    return None


def saved_inputs(path: Path) -> dict | None:
    """What a note was made from, read back from the note itself:
    {'transcript', 'screen', 'caption', 'source', 'language', 'creator', 'video_count',
     'photo_count', 'date', 'tags'}. None when the note has no saved text to work from."""
    lines = path.read_text(encoding="utf-8").split("\n")
    if "## Transcript" not in lines:
        return None
    t = lines.index("## Transcript")
    s = next((i for i in range(t + 1, len(lines)) if lines[i] == "## On-screen text"), len(lines))
    transcript = "\n".join(lines[t + 1:s]).strip()
    screen, after = "", s + 1
    if s < len(lines):
        j = s + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        fence = re.fullmatch(r"(`{3,})text", lines[j]) if j < len(lines) else None
        end = next((k for k in range(j + 1, len(lines)) if lines[k] == fence.group(1)), None) \
            if fence else None
        if end is not None:                          # the normal case: text in a code fence
            screen, after = "\n".join(lines[j + 1:end]), end + 1
        else:                                        # older notes: plain text until the caption
            end = next((k for k in range(s + 1, len(lines)) if lines[k] == "## Post caption"), len(lines))
            screen, after = "\n".join(lines[s + 1:end]), end
    c = next((k for k in range(min(after, len(lines)), len(lines)) if lines[k] == "## Post caption"), None)
    caption = "\n".join(lines[c + 1:]).strip() if c is not None else ""
    transcript = "" if transcript == "(no speech)" else transcript
    screen = "" if screen.strip() == "(none)" else screen.strip()
    if not (transcript or screen or caption):
        return None
    source = _header_value(lines, "Source")
    videos, photos = _slide_counts(_header_value(lines, "Slides"))
    return {"transcript": transcript, "screen": screen, "caption": caption,
            "source": "" if source == "-" else source,
            "language": (_header_value(lines, "Language").split() or ["en"])[0],
            "creator": _header_value(lines, "Creator"), "video_count": videos,
            "photo_count": photos, "date": _note_date(path, lines), "tags": read_tags(path)}


def _todo_text(line: str) -> str:
    """'- [x] 🔥 🧠 Do it 📅 2026-11-20 ✅ 2026-11-19' -> 'Do it' (any checkbox)."""
    rest = re.sub(r"\s*(?:✅|❌) \d{4}-\d{2}-\d{2}\s*$", "", line[6:])
    rest = split_kind(split_priority(rest)[1])[1]
    return split_due(rest)[0].strip()


def finished_items(lines: list[str]) -> list[list[str]]:
    """Done and skipped to-dos of a note, each with its 'Learned' line if it has one."""
    items, section = [], ""
    for i, line in enumerate(lines):
        if line.startswith("## "):
            section = line[3:].strip()
        elif section in ("Action items", "Habit to try") and FINISHED_RE.match(line):
            block = [line]
            if i + 1 < len(lines) and lines[i + 1].startswith(LEARNED_PREFIX):
                block.append(lines[i + 1])
            items.append(block)
    return items


def carry_over(path: Path, finished: list[list[str]]) -> None:
    """Put the old done/skipped to-dos into the new note. A new open to-do that is the same
    idea as one of them is replaced by it (so it is not opened again). The rest goes to the
    end of '## Action items'."""
    if not finished:
        return
    left, out, section = list(finished), [], ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section in ("Action items", "Habit to try") and line.startswith("- [ ] "):
            new = _todo_text(line)
            twin = next((b for b in left if new == _todo_text(b[0])
                         or similar_idea(new, _todo_text(b[0]))), None)
            if twin:
                out += twin
                left.remove(twin)
                continue
        out.append(line)
    if left:
        start = out.index("## Action items") if "## Action items" in out else len(out)
        end = next((k for k in range(start + 1, len(out)) if out[k].startswith("## ")), len(out))
        while end > start + 1 and not out[end - 1].strip():
            end -= 1
        out[end:end] = [line for block in left for line in block]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def redo_from_saved(path: Path) -> tuple[Path, dict]:
    """/redo fast: make the note again from its saved text. Returns (new note, data).
    The old note moves to old/. If anything fails, the old note stays where it was."""
    saved = saved_inputs(path)
    if saved is None:
        raise RedoNotPossible(MSG_NO_SAVED_TEXT)
    old_lines = path.read_text(encoding="utf-8").splitlines()
    started = time.perf_counter()
    data = summarise(saved["transcript"], saved["screen"], saved["caption"])   # the only slow step
    timings = {"ai": time.perf_counter() - started}
    data.update(language=saved["language"], video_count=saved["video_count"],
                photo_count=saved["photo_count"], creator=saved["creator"], timings=timings)
    if saved["tags"]:
        data["tags"] = saved["tags"]                 # keep your tags (you may have renamed them)
    archived = archive_note(path)                    # first, so the new note may take its name
    new_path = None
    try:
        new_path = save_note(data, saved["transcript"], saved["screen"], saved["source"],
                             saved["language"], saved["caption"], saved_at=saved["date"],
                             keep_existing=True)
        carry_over(new_path, finished_items(old_lines))
    except Exception:
        if new_path is not None and new_path.exists():
            new_path.unlink()
        archived.replace(path)                       # put the old note back
        raise
    log_timing(f"fast redo, {path.name}", timings)
    return new_path, data


# ---- yt-dlp auto-update -----------------------------------------------------

def ytdlp_version() -> str:
    from importlib import metadata
    try:
        return metadata.version("yt-dlp")
    except metadata.PackageNotFoundError:
        return "not installed"


def update_ytdlp() -> tuple[str, str, str]:
    """pip install -U yt-dlp. Returns (old version, new version, error or '')."""
    import sys
    old = ytdlp_version()
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "--quiet",
                            "--disable-pip-version-check", "yt-dlp"],
                           capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return old, old, str(exc)
    err = "" if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
    return old, ytdlp_version(), err


# ---- /health ----------------------------------------------------------------

def health_checks() -> list[tuple[bool, str, str]]:
    """(ok, name, detail) for everything the bot needs."""
    import shutil
    checks = []
    # Ollama + model
    try:
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).json()
        names = [m.get("name", "") for m in tags.get("models", [])]
        have = OLLAMA_MODEL in names or f"{OLLAMA_MODEL}:latest" in names
        checks.append((True, "Ollama", "running"))
        checks.append((have, "AI model", OLLAMA_MODEL + ("" if have else
                       f" not downloaded. Run: ollama pull {OLLAMA_MODEL}")))
    except (requests.RequestException, ValueError):
        checks.append((False, "Ollama", "not running. Start the Ollama app"))
    # Tools
    checks.append((bool(shutil.which("ffmpeg")), "ffmpeg",
                   "found" if shutil.which("ffmpeg") else "not found. Install it and add to PATH"))
    try:
        checks.append((True, "Tesseract OCR", f"v{pytesseract.get_tesseract_version()}"))
    except Exception:
        checks.append((False, "Tesseract OCR", "not found. Check TESSERACT_CMD in .env"))
    checks.append((ytdlp_version() != "not installed", "yt-dlp", ytdlp_version()))
    checks.append((True, "Whisper model", WHISPER_MODEL))
    cookies = os.getenv("COOKIES_FILE")
    if cookies:
        checks.append((Path(cookies).exists(), "Cookies file",
                       "found" if Path(cookies).exists() else "missing: " + cookies))
    # Notes folder + disk space
    if NOTES_DIR.exists():
        count = len(list(NOTES_DIR.glob("*.md")))
        try:
            probe = NOTES_DIR / ".health_check"
            probe.write_text("ok")
            probe.unlink()
            checks.append((True, "Notes folder", f"{count} notes"))
        except OSError:
            checks.append((False, "Notes folder", "can't write. Is Google Drive running?"))
        free_gb = shutil.disk_usage(NOTES_DIR).free / 1e9
        checks.append((free_gb > 2, "Free disk space", f"{free_gb:.0f} GB"))
    else:
        checks.append((False, "Notes folder", f"{NOTES_DIR} not found. Is Google Drive running?"))
    waiting = len(pending_notes())
    if waiting:
        checks.append((False, "Notes waiting on this PC",
                       f"{waiting}. They move to the notes folder when it is back"))
    return checks
