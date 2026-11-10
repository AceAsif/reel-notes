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
from datetime import datetime
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
    seen, lines = set(), []
    for img in sorted(frames.glob("*.png")):
        for line in pytesseract.image_to_string(str(img)).splitlines():
            line = line.strip()
            if len(line) < 4:
                continue
            key = line.lower()
            if key not in seen:
                seen.add(key)
                lines.append(line)
    return "\n".join(lines)[:6000]


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
- "action_items": list of short, concrete things I should do (start each with a verb,
  e.g. "Find the Strix GitHub repo and read its README", "Test X on one of my own projects").
  Only include actions supported by the video. If the video makes big claims
  (free tokens, "official", etc.), add one action to verify the claim first.

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
    data.setdefault("action_items", [])
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
MIN_SEARCH_STARS = 50
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
        *([f"- Videos: {data['video_count']}"] if data.get("video_count", 1) > 1 else []),
        tags_line(data.get("tags", [])),
        "",
        "## Summary",
        data["summary"],
        "",
        "## Key points",
        *[f"- {p}" for p in data["key_points"]],
        "",
        "## Resources",
    ]
    lines += [f"- {resource_line(r, data['category'])}" for r in data["resources"]]
    lines += [
        "",
        "## Action items",
        *[f"- [ ] {a}" for a in data["action_items"]],
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


MAX_VIDEOS = 10                       # most videos taken from one carousel post
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def download_media(url: str, workdir: Path) -> tuple[list[Path], str]:
    """Download a reel OR every video in a carousel post.

    Returns (video files in post order, the post caption).
    Photo slides are skipped (yt-dlp only downloads videos).
    """
    import yt_dlp

    opts = {
        # playlist_index = position in a carousel ("NA" for a single reel)
        "outtmpl": str(workdir / "item_%(playlist_index)s.%(ext)s"),
        "format": "bv*+ba/b",           # best video + audio, merged by ffmpeg
        "merge_output_format": "mp4",
        "noplaylist": False,            # carousels are "playlists": take every video
        "playlistend": MAX_VIDEOS,
        "ignoreerrors": True,           # one broken slide shouldn't stop the rest
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,             # no [download] lines filling bot.log
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

    def position(p: Path) -> int:
        n = p.stem.split("_")[-1]
        return int(n) if n.isdigit() else 0

    videos = sorted((p for p in workdir.glob("item_*") if p.suffix.lower() in VIDEO_EXTS),
                    key=position)
    if not videos:
        raise RuntimeError("No videos found in this post. Photo-only posts aren't supported yet.")
    return videos, caption.strip()


def process_videos(videos: list[Path], source: str = "", caption: str = "") -> tuple[Path, dict]:
    """Full pipeline for one reel or a multi-video post → ONE note."""
    transcripts, screens, languages = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for i, video in enumerate(videos[:MAX_VIDEOS], start=1):
            workdir = Path(tmp) / f"v{i}"
            workdir.mkdir()
            try:
                text, lang = transcribe(video)
                screen = screen_text(video, workdir)
            except Exception as exc:   # one broken video shouldn't stop the whole post
                print(f"Skipping video {i} ({video.name}): {exc!r}")
                continue
            transcripts.append(text)
            screens.append(screen)
            languages.append(lang)
    if not transcripts:
        raise RuntimeError("None of the videos in this post could be processed.")

    if len(transcripts) == 1:
        transcript, screen = transcripts[0], screens[0]
    else:  # label each part so the AI (and you) can tell the videos apart
        per_video = max(1500, 9000 // len(screens))   # keep the prompt a sensible size
        transcript = "\n\n".join(f"[Video {i}] {t or '(no speech)'}"
                                 for i, t in enumerate(transcripts, 1))
        screen = "\n\n".join(f"[Video {i}]\n{s[:per_video]}"
                             for i, s in enumerate(screens, 1))
    language = next((lang for lang in languages if lang != "en"), "en")

    data = summarise(transcript, screen, caption)
    data["language"] = language
    data["video_count"] = len(transcripts)
    return save_note(data, transcript, screen, source, language, caption), data


def process_video(video: Path, source: str = "") -> tuple[Path, dict]:
    """One video file (kept for older code paths)."""
    return process_videos([video], source)


def normalise_url(url: str) -> str:
    """Same reel = same URL, ignoring ?igsh=... tracking bits and trailing slash."""
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


def fenced(text: str) -> list[str]:
    """Wrap raw OCR text in a code block so stray symbols ('* ', '| ', '---')
    aren't read as Markdown lists/tables/headings. The fence is longer than any
    run of backticks in the text, so the text can never close it early."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence + "text", text, fence]


def open_actions() -> list[dict]:
    """Every unticked '- [ ]' action across all notes, in a stable numbered order.

    New notes sort after old ones (file names start with the date),
    so existing numbers don't shift when you add a reel.
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
            elif section == "Action items" and line.startswith("- [ ] "):
                results.append({"path": note, "line": i, "title": title,
                                "action": line[6:].strip()})
    return results


def tags_line(tags: list[str]) -> str:
    return "- Tags: " + " ".join(f"#{t}" for t in tags)


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
                  "Action items": 2, "Post caption": 1, "Transcript": 1, "On-screen text": 1}


def search_notes(query: str, limit: int = 15) -> list[dict]:
    """Find notes containing ALL words in the query (case-insensitive).

    Matches in the title/key points rank higher than matches in the transcript.
    Returns newest first among equal scores.
    """
    words = [w for w in query.lower().split() if w]
    if not words or not NOTES_DIR.exists():
        return []
    results = []
    for note in NOTES_DIR.glob("*.md"):
        lines = note.read_text(encoding="utf-8").splitlines()
        if not words or not all(w in "\n".join(lines).lower() for w in words):
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
            lines[i] = lines[i].replace("- [ ] ", f"- [{mark}] ", 1)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [a["action"] for a in chosen]
