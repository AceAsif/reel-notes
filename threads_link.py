"""Threads links (threads.com and threads.net): find the video in the public page.

yt-dlp has no Threads support, so this module does it in a small, careful way:
  * ONE request to the public Threads page. No login, no cookies, no extra requests to Threads.
  * The video address is read from that page (JSON data, og:video tag, or a <video> tag).
  * Then the video file itself is downloaded from the address in the page.
Then the normal pipeline (Whisper, OCR, Ollama) makes the note.

Threads can change its page at any time. When that happens the bot says it could not get the
video, and the real reason is written to bot.log (a line that starts with "threads:").
Only the standard library and `requests` are used. Free and local.
"""
import html as html_lib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

THREADS_RE = re.compile(r"^https?://(?:www\.)?threads\.(?:com|net)(?=[/?#]|$)", re.I)
POST_RE = re.compile(r"/post/([A-Za-z0-9_-]+)")
PAGE_HOST = "www.threads.com"          # threads.net is the old name: go straight to the new one
PAGE_TIMEOUT = 15                      # seconds
VIDEO_TIMEOUT = (10, 60)               # connect, read (seconds)
MAX_VIDEO_BYTES = 200 * 1024 * 1024    # a short video is far smaller than this
# A plain browser-style header. Nothing else is sent: no cookies, no login, no token.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en",
}
# The video must come from Meta's own servers (not any web address that is in the page).
VIDEO_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net", "instagram.com", "facebook.com",
                       "fbsbx.com", "threads.com", "threads.net")

# What the bot tells you (short, simple English)
MSG_NO_VIDEO = "I could not get this Threads video. Please save the video and send me the file."
MSG_TEXT_ONLY = ("This Threads post has text but no video. I only save videos from Threads links. "
                 "To keep the text, send me a screenshot of the post.")
MSG_IMAGES_ONLY = ("This Threads post has pictures but no video. I cannot download pictures from "
                   "a Threads link. Send me a screenshot and I will read the text in it.")
MSG_PROFILE = "That is a Threads profile, not a post. Send me the link to one post."


class ThreadsError(RuntimeError):
    """The message is ready to show in Telegram. The real reason is in bot.log."""


def log(url: str, detail: str) -> None:
    """One line in bot.log (the bot's output goes there)."""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] threads: {detail} | {url}", flush=True)


def is_threads_url(url: str) -> bool:
    return bool(THREADS_RE.match((url or "").strip()))


def post_code(url: str) -> str:
    """'https://www.threads.net/@ann/post/AbC123?xmt=x' -> 'AbC123' ('' for a profile link)."""
    m = POST_RE.search(urlsplit((url or "").strip()).path)
    return m.group(1) if m else ""


def dedupe_key(url: str) -> str:
    """The same post has the same key on threads.com and threads.net ('' if not a post link).
    Post codes are case-sensitive, so the case is kept."""
    return "threads:" + post_code(url) if is_threads_url(url) and post_code(url) else ""


def page_url(url: str) -> str:
    """The public page address: new host, no tracking bits (?xmt=...)."""
    path = urlsplit(url.strip()).path.rstrip("/")
    return f"https://{PAGE_HOST}{path}"


# ---- reading the page -----------------------------------------------------------

_STR = r'"((?:[^"\\]|\\.)*)"'          # a JSON string, with its escapes


def _json_text(raw: str) -> str:
    """'https:\\/\\/a.com\\/x?y=1\\u0026z=2' -> 'https://a.com/x?y=1&z=2'."""
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return raw.replace("\\/", "/").replace("\\u0026", "&")


def _meta(page: str, prop: str) -> str:
    """Content of <meta property="..." content="..."> (either attribute order)."""
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):        # one tag at a time
        attrs = {k.lower(): a or b for k, a, b in
                 re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag)}
        if prop in (attrs.get("property"), attrs.get("name")) and attrs.get("content"):
            return html_lib.unescape(attrs["content"]).strip()
    return ""


def parse_page(page: str) -> dict:
    """What the public page tells us.

    Returns {'video_url', 'text', 'name', 'handle', 'kind'}.
    kind: 'video' (a video address was found), 'images' (pictures only), 'text' (text only),
    or 'unknown' (we cannot tell, for example a login page, or a video we could not read)."""
    video, video_hint = "", False
    m = re.search(r'"video_versions"\s*:\s*\[\s*\{', page)
    if m:
        video_hint = True
        u = re.search(r'"url"\s*:\s*' + _STR, page[m.end():m.end() + 4000])
        if u:
            video = _json_text(u.group(1))
    if not video:
        for prop in ("og:video:secure_url", "og:video:url", "og:video"):
            found = _meta(page, prop)
            if found:
                video, video_hint = found, True
                break
    if not video:
        tag = re.search(r'<(?:video|source)\b[^>]*?\bsrc=(["\'])(.*?)\1', page, re.I | re.S)
        if tag:
            video, video_hint = html_lib.unescape(tag.group(2)).strip(), True
    video_hint = video_hint or ".mp4" in page or "<video" in page.lower()

    images = False
    m = re.search(r'"image_versions2"\s*:\s*\{\s*"candidates"\s*:\s*\[\s*\{', page)
    if m and re.search(r'"url"\s*:\s*' + _STR, page[m.end():m.end() + 3000]):
        images = True

    text = _meta(page, "og:description")
    if not text:
        c = re.search(r'"caption"\s*:\s*\{[^{}]*?"text"\s*:\s*' + _STR, page)
        text = _json_text(c.group(1)).strip() if c else ""

    name, handle = "", ""
    t = re.match(r"\s*(.*?)\s*\(@([A-Za-z0-9._]+)\)", _meta(page, "og:title"))
    if t:
        name, handle = t.group(1).strip(), t.group(2)

    if video:
        kind = "video"
    elif video_hint:
        kind = "unknown"                 # there is a video, but we cannot read its address
    elif images:
        kind = "images"
    elif text:
        kind = "text"
    else:
        kind = "unknown"
    return {"video_url": video, "text": text, "name": name, "handle": handle, "kind": kind}


# ---- the download -----------------------------------------------------------------

def _fail(url: str, detail: str, message: str = MSG_NO_VIDEO) -> None:
    log(url, detail)
    raise ThreadsError(message)


def _video_host_ok(video_url: str) -> bool:
    parts = urlsplit(video_url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == s or host.endswith("." + s)
                                           for s in VIDEO_HOST_SUFFIXES)


def download(url: str, workdir: Path) -> tuple[list[Path], str, dict]:
    """Same result as processor.download_media: (video files, caption, creator).
    Raises ThreadsError (with a message for Telegram) when the video cannot be saved."""
    if not post_code(url):
        _fail(url, "this is a profile link, not a post", MSG_PROFILE)
    address = page_url(url)
    try:
        resp = requests.get(address, headers=HEADERS, timeout=PAGE_TIMEOUT)   # the ONE page request
    except requests.RequestException as exc:
        _fail(url, f"page request failed: {exc!r}")
    final = urlsplit(resp.url or address).path.lower()
    if resp.status_code != 200 or final.startswith(("/login", "/accounts/login")):
        _fail(url, f"page not available: HTTP {resp.status_code}, ended at {final or '/'}")
    info = parse_page(resp.text or "")
    log(url, f"page read: kind={info['kind']}, video address found={bool(info['video_url'])}, "
             f"text chars={len(info['text'])}")
    if info["kind"] == "text":
        _fail(url, "post has text only", MSG_TEXT_ONLY)
    if info["kind"] == "images":
        _fail(url, "post has pictures only", MSG_IMAGES_ONLY)
    if not info["video_url"]:
        _fail(url, "no video address in the page (login page, or Threads changed its page?)")
    if not _video_host_ok(info["video_url"]):
        _fail(url, f"video address not allowed: host {urlsplit(info['video_url']).hostname!r}")

    path = Path(workdir) / "item_NA.mp4"
    try:
        video = requests.get(info["video_url"], headers=HEADERS, stream=True, timeout=VIDEO_TIMEOUT)
        try:
            kind = (video.headers.get("Content-Type") or "").lower()
            if video.status_code != 200:
                _fail(url, f"video download: HTTP {video.status_code}")
            if kind and not (kind.startswith("video/") or "octet-stream" in kind):
                _fail(url, f"video download: unexpected content type {kind!r}")
            size = 0
            with path.open("wb") as f:
                for chunk in video.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_VIDEO_BYTES:
                        _fail(url, f"video download: more than {MAX_VIDEO_BYTES // 2**20} MB")
                    f.write(chunk)
        finally:
            video.close()
    except (requests.RequestException, OSError) as exc:
        _fail(url, f"video download failed: {exc!r}")
    if path.stat().st_size == 0:
        _fail(url, "video download: empty file")

    from_url = re.search(r"/@([A-Za-z0-9._]+)/", urlsplit(url).path + "/")
    handle = info["handle"] or (from_url.group(1) if from_url else "")
    creator = {"name": info["name"], "handle": handle,
               "url": f"https://{PAGE_HOST}/@{handle}" if handle else ""}
    return [path], info["text"], creator
