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


def transcribe(video: Path) -> str:
    """Speech to text. faster-whisper reads the audio straight from the video."""
    segments, _info = get_whisper().transcribe(str(video), vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()


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

Return ONLY a JSON object with these keys:
- "title": short title (max 8 words)
- "category": one of "motivation", "tech", "programming", "other"
- "summary": 2-3 sentences
- "key_points": list of 3-5 short strings
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
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
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
    return data


def resource_line(r) -> str:
    """Name + link. If the model gave no real URL, add a GitHub search link."""
    if not isinstance(r, dict):
        return str(r)
    name = str(r.get("name", "")).strip()
    link = str(r.get("link", "")).strip()
    if not link.lower().startswith("http"):
        link = "https://github.com/search?type=repositories&q=" + quote_plus(name)
    return f"{name} {link}".strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "reel"


def save_note(data: dict, transcript: str, screen: str, source: str) -> Path:
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = NOTES_DIR / f"{now:%Y-%m-%d_%H%M}_{slugify(data['title'])}.md"

    lines = [
        f"# {data['title']}",
        "",
        f"- Date: {now:%Y-%m-%d %H:%M}",
        f"- Category: {data['category']}",
        f"- Source: {source or '-'}",
        "",
        "## Summary",
        data["summary"],
        "",
        "## Key points",
        *[f"- {p}" for p in data["key_points"]],
        "",
        "## Resources",
    ]
    lines += [f"- {resource_line(r)}" for r in data["resources"]]
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
        transcript = transcribe(video)
        screen = screen_text(video, Path(tmp))
    data = summarise(transcript, screen)
    return save_note(data, transcript, screen, source), data


def open_actions() -> list[tuple[str, str]]:
    """Find every unticked '- [ ]' action across all notes."""
    results = []
    if not NOTES_DIR.exists():
        return results
    for note in sorted(NOTES_DIR.glob("*.md")):
        text = note.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text else note.stem
        for line in text.splitlines():
            if line.startswith("- [ ] "):
                results.append((title, line[6:].strip()))
    return results
