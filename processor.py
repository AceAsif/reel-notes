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
    model = get_whisper()
    # Language is detected up front; the segments are only computed if we read them
    segments, info = model.transcribe(str(video), vad_filter=True)
    language = info.language or "en"
    if language != "en":
        segments, _ = model.transcribe(str(video), vad_filter=True, task="translate")
    return " ".join(seg.text.strip() for seg in segments).strip(), language


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
Below is the spoken transcript and the text that appeared on screen (from OCR, so it may have typos).

Always write every field in English, even if the transcript or on-screen text
is in another language (e.g. Hindi or Hinglish); translate as needed.

Return ONLY a JSON object with these keys:
- "title": short title (max 8 words)
- "category": one of "motivation", "tech", "programming", "other"
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
"""


def summarise(transcript: str, screen: str) -> dict:
    """Ask the local Ollama model for a structured note."""
    prompt = (PROMPT.replace("<<TRANSCRIPT>>", transcript or "(no speech)")
                    .replace("<<SCREEN>>", screen or "(no on-screen text)"))
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.2,  # low = consistent notes for the same reel
                "num_ctx": 8192,     # room for long transcripts + on-screen text
            },
        },
        timeout=600,
    )
    resp.raise_for_status()
    try:
        data = json.loads(resp.json()["response"])
    except (json.JSONDecodeError, KeyError):
        data = {}
    # Fill in anything the model left out so the note always renders
    data.setdefault("title", "Untitled reel")
    data.setdefault("category", "other")
    data.setdefault("summary", "")
    data.setdefault("key_points", [])
    data.setdefault("resources", [])
    data.setdefault("action_items", [])
    data["resources"] = drop_invented_links(data["resources"], transcript + "\n" + screen)
    return data


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
    return f"{name} {link}".strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "reel"


def save_note(data: dict, transcript: str, screen: str, source: str,
              language: str = "en") -> Path:
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
        screen or "(none)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def download_reel(url: str, workdir: Path) -> Path:
    """Download a reel from a link with yt-dlp. Returns the video file path."""
    import yt_dlp

    opts = {
        "outtmpl": str(workdir / "reel.%(ext)s"),
        "format": "bv*+ba/b",           # best video + audio, merged by ffmpeg
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    # Instagram often needs you logged in: export cookies to a cookies.txt file
    if os.getenv("COOKIES_FILE"):
        opts["cookiefile"] = os.getenv("COOKIES_FILE")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    files = sorted(workdir.glob("reel.*"))
    if not files:
        raise RuntimeError("Download finished but no video file was found.")
    return files[0]


def process_video(video: Path, source: str = "") -> tuple[Path, dict]:
    """Full pipeline. Returns the note path and the structured data."""
    with tempfile.TemporaryDirectory() as tmp:
        transcript, language = transcribe(video)
        screen = screen_text(video, Path(tmp))
    data = summarise(transcript, screen)
    data["language"] = language
    return save_note(data, transcript, screen, source, language), data


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
        for i, line in enumerate(lines):
            if line.startswith("- [ ] "):
                results.append({"path": note, "line": i, "title": title,
                                "action": line[6:].strip()})
    return results


def complete_actions(numbers: list[int]) -> list[str]:
    """Tick off actions by their /todo number. Returns the texts that were ticked."""
    actions = open_actions()
    chosen = [actions[n - 1] for n in sorted(set(numbers)) if 1 <= n <= len(actions)]
    by_file: dict[Path, list[int]] = {}
    for a in chosen:
        by_file.setdefault(a["path"], []).append(a["line"])
    for path, line_nos in by_file.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        for i in line_nos:
            lines[i] = lines[i].replace("- [ ] ", "- [x] ", 1)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [a["action"] for a in chosen]
