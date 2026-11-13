"""Turns a downloaded reel video into a markdown note with action items.

Pipeline (all free, all local):
  video -> faster-whisper (speech to text)
        -> ffmpeg frames + Tesseract OCR (on-screen text, e.g. repo names)
        -> Ollama local LLM (summary + action items as JSON)
        -> markdown file in NOTES_DIR
"""
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import pytesseract
import requests
from faster_whisper import WhisperModel

NOTES_DIR = Path(os.getenv("NOTES_DIR", "notes"))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
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

    English reels are transcribed as-is. Other languages (Hindi, Bengali, ...)
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
    return " ".join(seg.text.strip() for seg in segments).strip(), language


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

Return ONLY a JSON object with these keys:
- "title": short title (max 8 words)
- "category": one of "motivation", "tech", "programming", "other"
- "tags": list of 3-6 short topic tags, lowercase, words joined with "-", no "#".
  Prefer common, reusable tags so notes group well, e.g. "python", "ai-tools",
  "github", "claude", "productivity", "communication", "career", "security".
  <<EXISTING_TAGS>>
- "summary": 2-3 sentences
- "key_points": list of 4-7 specific, self-contained points. Someone who never watched
  the video must be able to USE them. Keep the actual details: exact questions,
  steps, commands, numbers, research findings, names, and WHY it works.
  Bad: "Ask about favorite memories". Good: "Ask: 'What is your favourite memory?'"
- "resources": list of objects {"name": "...", "link": "..."} for every GitHub repo, tool, website,
  library or command mentioned. Fix obvious OCR typos. Only use a URL that was actually
  shown or said; never invent one. Use "" for link otherwise (never "N/A").
- "action_items": list of 3-6 objects {"text": "...", "priority": "high" | "normal" | "low"}.
  "text" is a short, concrete thing I should do, starting with a verb,
  e.g. "Find the Strix GitHub repo and read its README". Only actions supported by the video.
  When the video names several tools, give each useful tool its own action.
  Priority: "high" = specific, quick (under ~30 min) and clearly useful;
  "low" = optional, vague, or just following/contacting the creator; otherwise "normal".
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


def ask_ollama_json(prompt: str) -> dict:
    """Send a prompt to the local Ollama model and get a JSON object back."""
    # ~3.5 characters per token. Long multi-video posts need a bigger context window
    # (uses more graphics-card memory, so only when needed).
    num_ctx = 8192 if len(prompt) < 20000 else 16384
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,  # low = consistent notes for the same reel
                "num_ctx": num_ctx,  # room for long transcripts + on-screen text
            },
        },
        timeout=600,
    )
    resp.raise_for_status()
    try:
        data = json.loads(resp.json()["response"])
    except (json.JSONDecodeError, KeyError):
        data = {}
    return data if isinstance(data, dict) else {}


# ---- Priorities and claim check -------------------------------------------

PRIORITY_ICON = {"high": "🔥 ", "normal": "", "low": "🔽 "}
PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def clean_actions(items) -> list[dict]:
    """Accept what the AI returns (objects or plain strings) → [{text, priority}]."""
    result = []
    for item in items or []:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("action") or "").strip()
            priority = str(item.get("priority", "normal")).lower().strip()
        else:
            text, priority = str(item).strip(), "normal"
        if not text:
            continue
        if priority not in PRIORITY_ICON:
            priority = "normal"
        # Small models often skip priorities: actions that only send you to the
        # creator (bio, DM, comment, follow, channel) are always low.
        if LOW_PRIORITY_RE.search(text):
            priority = "low"
        result.append({"text": text, "priority": priority})
    return result


LOW_PRIORITY_RE = re.compile(
    r"\b(bio|dm|dms|comment \"?\w+\"? (below|to)|follow (the |this )?(creator|author|account|page)|"
    r"broadcast channel|telegram channel|(creator|author)'?s? (channel|page|profile)|link in)\b",
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
    return f"- [ ] {PRIORITY_ICON[action['priority']]}{action['text']}"


def split_priority(text: str) -> tuple[str, str]:
    """'🔥 Do the thing' -> ('high', 'Do the thing')."""
    for level, icon in PRIORITY_ICON.items():
        if icon and text.startswith(icon):
            return level, text[len(icon):]
    return "normal", text


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


def summarise(transcript: str, screen: str, caption: str = "") -> dict:
    """Ask the local Ollama model for a structured note."""
    existing = [t for t, _ in all_tags()][:30]
    tag_hint = ("Tags already used in my notes (reuse them when they fit): "
                + ", ".join(existing)) if existing else ""
    prompt = (PROMPT.replace("<<TRANSCRIPT>>", transcript or "(no speech)")
                    .replace("<<SCREEN>>", screen or "(no on-screen text)")
                    .replace("<<CAPTION>>", caption or "(no caption)")
                    .replace("<<EXISTING_TAGS>>", tag_hint))
    screen = screen + "\n" + caption  # links in the caption count as "shown in the post"
    data = ask_ollama_json(prompt)
    # Fill in anything the model left out so the note always renders
    data.setdefault("title", "Untitled reel")
    data.setdefault("category", "other")
    data.setdefault("summary", "")
    data.setdefault("key_points", [])
    data.setdefault("resources", [])
    data["action_items"] = clean_actions(data.get("action_items", []))
    data["claims"] = clean_claims(data.get("claims", []))
    clean_motivation_fields(data, transcript + "\n" + caption)
    data["tags"] = clean_tags(data.get("tags", []))
    data["resources"] = drop_invented_links(data["resources"], transcript + "\n" + screen)
    data["resources"] = enrich_with_github(data["resources"], data["category"],
                                           transcript + "\n" + screen)
    return data


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


def github_get(path: str, params: dict | None = None) -> dict | None:
    """Call the GitHub API. Returns None on any problem, so notes never fail."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "reel-notes-bot"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    try:
        r = requests.get("https://api.github.com" + path, params=params,
                         headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def repo_info(owner: str, name: str) -> dict | None:
    """Real link, stars and description for owner/name."""
    name = name.removesuffix(".git")
    d = github_get(f"/repos/{owner}/{name}")
    if not d or "html_url" not in d:
        # Fallback: the same repo through the search API
        found = github_get("/search/repositories", {"q": f"repo:{owner}/{name}"})
        items = (found or {}).get("items", [])
        if not items:
            return None
        d = items[0]
    return {"link": d["html_url"], "stars": d.get("stargazers_count", 0),
            "description": (d.get("description") or "").strip()}


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
            if info:
                return info
    # 2) A github.com/owner/repo link shown in the video or written in the caption
    for owner, repo in GITHUB_REPO_RE.findall(joined):
        r = squash(repo.removesuffix(".git"))
        if len(r) >= 3 and (key in r or r in key):
            info = repo_info(owner, repo)
            if info:
                return info
    # 3) GitHub search: the repo name must match the tool name exactly, AND have at
    #    least MIN_SEARCH_STARS stars, so a tiny unrelated repo with the same name
    #    (e.g. a 5-star "StageShow") isn't picked by mistake
    found = github_get("/search/repositories",
                       {"q": f"{name} in:name", "sort": "stars", "per_page": 10})
    for item in (found or {}).get("items", []):
        if (squash(item.get("name", "")) == key
                and item.get("stargazers_count", 0) >= MIN_SEARCH_STARS):
            return {"link": item["html_url"], "stars": item.get("stargazers_count", 0),
                    "description": (item.get("description") or "").strip()}
    return None


def enrich_with_github(resources: list, category: str, source_text: str) -> list:
    """Add real GitHub links, stars and descriptions to resources."""
    for r in resources:
        if not isinstance(r, dict):
            continue
        link = str(r.get("link", "")).strip()
        m = GITHUB_REPO_RE.search(link)
        if m:                                   # already a repo link: check it's real
            info = repo_info(m.group(1), m.group(2))
        elif not link and category in ("tech", "programming"):
            info = find_repo(str(r.get("name", "")), source_text)
        else:
            info = None
        if info:
            r.update(info)
    return resources


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


def resource_line(r, category: str = "") -> str:
    """Name + link. If there's no real URL, add a search link:
    GitHub for tech/programming reels, Google for everything else."""
    if not isinstance(r, dict):
        return str(r)
    name = str(r.get("name", "")).strip()
    link = str(r.get("link", "")).strip()
    if not link.lower().startswith("http"):
        if category in ("tech", "programming"):
            link = "https://github.com/search?type=repositories&q=" + quote_plus(name)
        else:
            link = "https://www.google.com/search?q=" + quote_plus(name)
    line = f"{name} {link}".strip()
    if "stars" in r:
        line += f"  ⭐ {format_stars(int(r['stars']))}"
    if r.get("description"):
        desc = r["description"]
        line += " — " + (desc if len(desc) <= 100 else desc[:97] + "...")
    return line


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "reel"


def save_note(data: dict, transcript: str, screen: str, source: str,
              language: str = "en", caption: str = "") -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = NOTES_DIR / f"{now:%Y-%m-%d_%H%M}_{slugify(data['title'])}.md"

    lines = [
        f"# {data['title']}",
        "",
        f"- Date: {now:%Y-%m-%d %H:%M}",
        f"- Category: {data['category']}",
        f"- Source: {source or '-'}",
        f"- Language: {language}" + (" (translated to English)" if language != "en" else ""),
        *([f"- Slides: {slide_summary(data)}"] if slide_total(data) > 1 else []),
        tags_line(data.get("tags", [])),
        "",
        "## Summary",
        data["summary"],
        "",
        *motivation_lines(data),
        *claims_lines(data),
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
        "## Transcript",
        transcript or "(no speech)",
        "",
        "## On-screen text",
        *fenced(screen or "(none)"),
        "",
    ]
    if caption:
        lines += ["## Post caption", caption, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


MAX_VIDEOS = 10                       # most slides taken from one carousel post
MAX_MINUTES = int(os.getenv("MAX_MINUTES", "10"))  # longest video accepted (YouTube etc.)
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def slide_position(p: Path) -> int:
    """item_3.mp4 -> 3 (a single reel is 'item_NA' -> 0)."""
    n = p.stem.split("_")[-1]
    return int(n) if n.isdigit() else 0


def download_media(url: str, workdir: Path) -> tuple[list[Path], str]:
    """Download a reel, or every slide of a carousel post (videos AND photos).

    Returns (slide files in post order, the post caption). For a video slide you
    get the video; for a photo slide you get the image.
    """
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
    # Instagram often needs you logged in: export cookies to a cookies.txt file
    if os.getenv("COOKIES_FILE"):
        opts["cookiefile"] = os.getenv("COOKIES_FILE")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True) or {}

    caption = info.get("description") or ""
    if not caption:  # carousels keep the caption on each item
        for entry in info.get("entries") or []:
            if entry and entry.get("description"):
                caption = entry["description"]
                break
    return pick_slides(workdir), caption.strip()


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


def process_videos(videos: list[Path], source: str = "", caption: str = "") -> tuple[Path, dict]:
    """Full pipeline for one reel or a multi-slide post (videos and/or photos) → ONE note."""
    labels, transcripts, screens, languages = [], [], [], []
    photo_count = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, slide in enumerate(videos[:MAX_VIDEOS], start=1):
            workdir = Path(tmp) / f"s{i}"
            workdir.mkdir()
            is_photo = slide.suffix.lower() in IMAGE_EXTS
            try:
                if is_photo:
                    text, lang = "", "en"
                    screen = image_text(slide, workdir)
                else:
                    text, lang = transcribe(slide)
                    screen = screen_text(slide, workdir)
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

    data = summarise(transcript, screen, caption)
    data["language"] = language
    data["video_count"] = len(transcripts) - photo_count
    data["photo_count"] = photo_count
    return save_note(data, transcript, screen, source, language, caption), data


def process_video(video: Path, source: str = "") -> tuple[Path, dict]:
    """One video file (kept for older code paths)."""
    return process_videos([video], source)


YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/(?:shorts/|watch\?(?:.*&)?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})")


def normalise_url(url: str) -> str:
    """Same reel = same URL, ignoring ?igsh=... tracking bits and trailing slash.
    YouTube keeps its video ID (watch?v=ID, shorts/ID and youtu.be/ID all match)."""
    m = YOUTUBE_ID_RE.search(url)
    if m:
        return "youtube:" + m.group(1)           # IDs are case-sensitive: don't lower()
    return url.split("?")[0].split("#")[0].rstrip("/").lower()


def find_note_by_source(url: str) -> Path | None:
    """Return the existing note for this reel link, if we already made one."""
    if not url or not NOTES_DIR.exists():
        return None
    target = normalise_url(url)
    for note in sorted(NOTES_DIR.glob("*.md")):
        for line in note.read_text(encoding="utf-8").splitlines()[:8]:
            if line.startswith("- Source: ") and normalise_url(line[10:].strip()) == target:
                return note
    return None


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
        lines += ["## Habit to try", f"- [ ] {data['habit']}", ""]
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
        section = ""
        for i, line in enumerate(lines):
            if line.startswith("## "):
                section = line[3:].strip()
            # Only real action items count, not "- [ ]" text inside a transcript/caption
            elif section in ("Action items", "Habit to try") and line.startswith("- [ ] "):
                priority, text = split_priority(line[6:].strip())
                results.append({"path": note, "line": i, "title": title,
                                "action": text, "priority": priority})
    results.sort(key=lambda a: PRIORITY_ORDER[a["priority"]])  # stable: keeps note order
    return results


def set_priority(numbers: list[int], level: str) -> list[str]:
    """Change the priority of actions by their /todo number."""
    actions = open_actions()
    chosen = [actions[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(actions)]
    for a in chosen:
        lines = a["path"].read_text(encoding="utf-8").splitlines()
        lines[a["line"]] = "- [ ] " + PRIORITY_ICON[level] + a["action"]
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


def notes_with_tag(tag: str) -> list[Path]:
    """Notes tagged exactly `tag`, or with tags starting with it
    (so /tag ai finds #ai and #ai-tools). Newest first."""
    tag = clean_tags([tag])[0] if clean_tags([tag]) else ""
    if not tag or not NOTES_DIR.exists():
        return []
    hits = [p for p in NOTES_DIR.glob("*.md")
            if any(t == tag or t.startswith(tag + "-") for t in read_tags(p))]
    return sorted(hits, reverse=True)


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
        # Put the Tags line after the other '- Key: value' header lines
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
        if not words or not check(w in "\n".join(lines).lower() for w in words):
            continue
        title = lines[0].lstrip("# ").strip() if lines else note.stem
        score, snippet, section = 0, "", "title"
        for line in lines:
            if line.startswith("## "):
                section = line[3:].strip()
                continue
            low = line.lower()
            hits = sum(w in low for w in words)
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


# ---- weekly stats ---------------------------------------------------------

DONE_DATE_RE = re.compile(r"^- \[(x|-)\] .*(✅|❌) (\d{4}-\d{2}-\d{2})\s*$")


def weekly_stats(today: date | None = None, days: int = 7) -> dict:
    """What happened in the last `days` days: reels saved, actions done/skipped,
    categories, most-used tags, plus what's still open."""
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    stats = {"start": start, "end": today, "saved": 0, "done": 0, "skipped": 0,
             "categories": {}, "tags": {}}
    if NOTES_DIR.exists():
        for path in NOTES_DIR.glob("*.md"):
            try:
                created = date.fromisoformat(path.name[:10])
            except ValueError:
                created = None
            text = path.read_text(encoding="utf-8")
            if created and start <= created <= today:
                stats["saved"] += 1
                m = re.search(r"^- Category: (\w+)", text, re.M)
                cat = m.group(1) if m else "other"
                stats["categories"][cat] = stats["categories"].get(cat, 0) + 1
                for t in read_tags(path):
                    stats["tags"][t] = stats["tags"].get(t, 0) + 1
            for line in text.splitlines():
                m = DONE_DATE_RE.match(line)
                if m and start <= date.fromisoformat(m.group(3)) <= today:
                    stats["done" if m.group(1) == "x" else "skipped"] += 1
    actions = open_actions()
    stats["open"] = len(actions)
    stats["open_high"] = sum(a["priority"] == "high" for a in actions)
    stats["top_tags"] = sorted(stats["tags"].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return stats


# ---- daily nudge ----------------------------------------------------------

def action_id(action: dict) -> str:
    """Short, stable id for an action (fits in a Telegram button):
    first 8 characters of the note's file-name hash + the line number."""
    import hashlib
    return hashlib.md5(action["path"].name.encode()).hexdigest()[:8] + ":" + str(action["line"])


def find_action(aid: str) -> tuple[int, dict] | None:
    """(position in /todo order starting at 1, action) for an id, or None if
    it's already done/skipped/deleted."""
    for n, a in enumerate(open_actions(), start=1):
        if action_id(a) == aid:
            return n, a
    return None


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
    top = actions[0]["priority"]
    bucket = [a for a in actions if a["priority"] == top]
    day = (today or date.today()).toordinal()
    return bucket[day % len(bucket)]


# ---- /ask: answer questions from your notes --------------------------------

STOPWORDS = set("""a an and are as at be but by can could do does for from had has have how
i if in into is it its me my of on or should so than that the their them then there these
they this to was we were what when where which who why will with would you your about any
all also just like get got some tell show give find need want use using used best good
which""".split())

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
    return [w for w in words if len(w) >= 3 and w not in STOPWORDS]


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
    reminders = [r for r in load_reminders() if r["action_id"] != action_id(action)]
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


# ---- chat mode: talk to the bot about your notes ----------------------------

CHAT_SYSTEM = """You are Reel Notes, a friendly personal assistant inside Telegram.
You help me use the notes I saved from short videos (tech, programming, motivation).
How to talk:
- Warm, encouraging and simple English (English is not my first language).
- Short replies: usually 2-6 sentences, or a short list. No long essays.
- For facts about tools, commands, links, quotes or tips, use ONLY the notes below.
  Copy names, commands and links exactly. If the notes don't cover it, say
  "I don't have that in your notes" and suggest saving a reel about it.
  Never invent tools, links, numbers or quotes.
- Small talk (hello, thanks, how are you) is fine: answer briefly and kindly.
- When it helps, suggest a next step, e.g. "Want a reminder? /remind 2 friday".
- Use plain text only, no Markdown symbols like ** or ##.

MY NOTES FOR THIS MESSAGE:
<<NOTES>>
"""
CHAT_HISTORY_TURNS = 6          # remembered back-and-forth messages


def chat_reply(message: str, history: list[dict], max_notes: int = 4) -> tuple[str, list[Path]]:
    """Reply to a normal chat message using matching notes and recent history.

    history = [{"role": "user"|"assistant", "content": "..."}] (oldest first).
    Notes are found from this message AND the previous user message, so
    follow-ups like "what about the second one?" still find the right notes.
    Returns (reply text, notes that were given to the AI).
    """
    previous = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
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
              "options": {"temperature": 0.4, "num_ctx": 8192}},
        timeout=600,
    )
    resp.raise_for_status()
    reply = (resp.json().get("message", {}).get("content") or "").strip()
    reply = re.sub(r"\*\*|__|^#+\s*", "", reply, flags=re.M)   # strip Markdown leftovers
    return reply or "Sorry, I couldn't think of an answer. Can you ask another way?", \
        [h["path"] for h in hits]
