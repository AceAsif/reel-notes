"""Tests for Threads links. The network is always mocked: no real request is made."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor  # noqa: E402
import threads_link as t  # noqa: E402

POST = "https://www.threads.net/@ann/post/AbC123?xmt=tracking"
CDN_VIDEO = r"https:\/\/scontent.cdninstagram.com\/v\/t50\/clip.mp4?x=1\u0026y=2"
CDN_VIDEO_CLEAN = "https://scontent.cdninstagram.com/v/t50/clip.mp4?x=1&y=2"


def page(video_json=True, og_video="", text="Nice clip, I'm happy", title="Ann Lee (@ann) on Threads",
         images=False, extra=""):
    parts = ["<html><head>",
             f'<meta property="og:title" content="{title}">',
             f'<meta content="{text}" property="og:description">']
    if og_video:
        parts.append(f'<meta property="og:video" content="{og_video}">')
    parts.append("</head><body><script type=\"application/json\">{")
    if video_json:
        parts.append(f'"video_versions":[{{"type":101,"url":"{CDN_VIDEO}"}},{{"type":102,"url":"x"}}],')
    else:
        parts.append('"video_versions":null,')
    if images:
        parts.append('"image_versions2":{"candidates":[{"url":"https:\\/\\/scontent.cdninstagram.com\\/p.jpg"}]},')
    parts.append(f'"caption":{{"text":"{text}"}}}}</script>{extra}</body></html>')
    return "".join(parts)


class Resp:
    def __init__(self, status=200, text="", url="", chunks=(b"video-bytes",), headers=None):
        self.status_code, self.text, self.url = status, text, url
        self.chunks, self.headers = chunks, headers or {"Content-Type": "video/mp4"}
        self.closed = False

    def iter_content(self, size):
        yield from self.chunks

    def close(self):
        self.closed = True


class Net:
    """Records every request. The page address returns `page_resp`, anything else the video."""
    def __init__(self, monkeypatch, page_resp=None, video_resp=None, error=None):
        self.calls = []
        self.page_resp = page_resp or Resp(text=page(), url="https://www.threads.com/@ann/post/AbC123")
        self.video_resp = video_resp or Resp()
        self.error = error
        monkeypatch.setattr(t.requests, "get", self.get)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error and "threads" in url:
            raise self.error
        return self.page_resp if "threads" in url else self.video_resp

    @property
    def page_calls(self):
        return [c for c in self.calls if "threads.com" in c[0] or "threads.net" in c[0]]


# ---- links ---------------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://www.threads.com/@ann/post/AbC123", True),
    ("https://threads.com/@ann/post/AbC123", True),
    ("http://www.threads.net/@ann/post/AbC123?x=1", True),
    ("https://threads.net", True),
    ("https://notthreads.com/@ann/post/AbC123", False),
    ("https://www.instagram.com/reel/ABC/", False),
    ("https://example.com/threads.com/post/x", False),
    ("", False),
])
def test_is_threads_url(url, ok):
    assert t.is_threads_url(url) is ok


def test_post_code_and_page_url():
    assert t.post_code(POST) == "AbC123"
    assert t.post_code("https://www.threads.com/@ann") == ""             # a profile
    assert t.page_url(POST) == "https://www.threads.com/@ann/post/AbC123"  # new host, no tracking


def test_same_post_on_com_and_net_is_a_duplicate(tmp_path, monkeypatch):
    a, b = "https://www.threads.com/@ann/post/AbC123/", "https://threads.net/@ann/post/AbC123?xmt=1"
    assert processor.normalise_url(a) == processor.normalise_url(b)
    assert processor.normalise_url(a) != processor.normalise_url("https://threads.com/@ann/post/abc123")
    notes = tmp_path / "notes"
    notes.mkdir()
    monkeypatch.setattr(processor, "NOTES_DIR", notes)
    (notes / "2026-11-17_1200_clip.md").write_text(f"# Clip\n\n- Source: {a}\n", encoding="utf-8")
    assert processor.find_note_by_source(b).name == "2026-11-17_1200_clip.md"


# ---- reading the page ------------------------------------------------------------

def test_parse_video_from_page_data_unescapes_the_address():
    info = t.parse_page(page())
    assert info["kind"] == "video" and info["video_url"] == CDN_VIDEO_CLEAN
    assert info["text"] == "Nice clip, I'm happy"
    assert (info["name"], info["handle"]) == ("Ann Lee", "ann")


def test_parse_video_from_og_tag_when_there_is_no_page_data():
    info = t.parse_page(page(video_json=False, og_video="https://video.fbcdn.net/a.mp4?x=1&amp;y=2"))
    assert info["kind"] == "video" and info["video_url"] == "https://video.fbcdn.net/a.mp4?x=1&y=2"


def test_parse_video_from_video_tag():
    info = t.parse_page(page(video_json=False, extra='<video src="https://v.cdninstagram.com/a.mp4"></video>'))
    assert info["video_url"] == "https://v.cdninstagram.com/a.mp4"


def test_parse_text_only_images_only_and_unknown():
    assert t.parse_page(page(video_json=False))["kind"] == "text"       # "video_versions": null
    assert t.parse_page(page(video_json=False, images=True))["kind"] == "images"
    assert t.parse_page("<html><body>Log in to continue</body></html>")["kind"] == "unknown"
    # a video we cannot read must NOT be called "text only"
    assert t.parse_page(page(video_json=False, extra='<a href="x.mp4">v</a>'))["kind"] == "unknown"


def test_text_falls_back_to_page_data_and_handles_escapes():
    html = '<html><script>{"caption":{"text":"Line one \\"quoted\\" \\u00e9"}}</script></html>'
    assert t.parse_page(html)["text"] == 'Line one "quoted" é'


# ---- download ---------------------------------------------------------------------

def test_download_works_with_one_page_request(tmp_path, monkeypatch):
    net = Net(monkeypatch)
    videos, caption, creator = t.download(POST, tmp_path)
    assert [v.name for v in videos] == ["item_NA.mp4"] and videos[0].read_bytes() == b"video-bytes"
    assert caption == "Nice clip, I'm happy"
    assert creator == {"name": "Ann Lee", "handle": "ann", "url": "https://www.threads.com/@ann"}
    assert len(net.page_calls) == 1                                   # ONE request to Threads
    assert net.page_calls[0][0] == "https://www.threads.com/@ann/post/AbC123"
    assert net.calls[1][0] == CDN_VIDEO_CLEAN and len(net.calls) == 2  # then the video file
    assert net.video_resp.closed


def test_no_cookies_no_login_are_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "cookies.txt"))
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    net = Net(monkeypatch)
    t.download(POST, tmp_path)
    for _, kwargs in net.calls:
        assert "cookies" not in kwargs and "auth" not in kwargs
        assert not {"Cookie", "Authorization"} & set(kwargs["headers"])


@pytest.mark.parametrize("make", [
    lambda mp: dict(page_resp=Resp(status=404, text="gone")),
    lambda mp: dict(page_resp=Resp(status=200, text=page(), url="https://www.threads.com/login/?next=x")),
    lambda mp: dict(page_resp=Resp(text="<html>Log in to continue</html>", url="https://www.threads.com/@ann/post/AbC123")),
    lambda mp: dict(error=t.requests.ConnectionError("no internet")),
    lambda mp: dict(video_resp=Resp(status=403)),
    lambda mp: dict(video_resp=Resp(headers={"Content-Type": "text/html"})),
    lambda mp: dict(video_resp=Resp(chunks=())),
    lambda mp: dict(page_resp=Resp(text=page().replace("cdninstagram.com", "evil.example"),
                                   url="https://www.threads.com/@ann/post/AbC123")),
], ids=["http-404", "login-redirect", "no-video-address", "network-error", "video-403",
        "video-not-a-video", "empty-video", "video-host-not-allowed"])
def test_failures_give_the_exact_message_and_log_the_real_reason(tmp_path, monkeypatch, capsys, make):
    Net(monkeypatch, **make(monkeypatch))
    with pytest.raises(t.ThreadsError) as err:
        t.download(POST, tmp_path)
    assert str(err.value) == ("I could not get this Threads video. "
                              "Please save the video and send me the file.")
    log = capsys.readouterr().out
    assert "threads:" in log and POST in log and len(log.strip().splitlines()) >= 1


def test_text_only_and_pictures_only_posts_are_explained(tmp_path, monkeypatch, capsys):
    Net(monkeypatch, page_resp=Resp(text=page(video_json=False), url="https://www.threads.com/@ann/post/AbC123"))
    with pytest.raises(t.ThreadsError) as err:
        t.download(POST, tmp_path)
    assert str(err.value) == t.MSG_TEXT_ONLY and "screenshot" in t.MSG_TEXT_ONLY
    assert "text only" in capsys.readouterr().out
    Net(monkeypatch, page_resp=Resp(text=page(video_json=False, images=True), url="https://www.threads.com/@ann/post/AbC123"))
    with pytest.raises(t.ThreadsError) as err:
        t.download(POST, tmp_path)
    assert str(err.value) == t.MSG_IMAGES_ONLY and "pictures" in t.MSG_IMAGES_ONLY


def test_profile_link_makes_no_request(tmp_path, monkeypatch):
    net = Net(monkeypatch)
    with pytest.raises(t.ThreadsError) as err:
        t.download("https://www.threads.com/@ann", tmp_path)
    assert str(err.value) == t.MSG_PROFILE and net.calls == []


def test_too_big_video_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "MAX_VIDEO_BYTES", 10)
    Net(monkeypatch, video_resp=Resp(chunks=(b"x" * 8, b"x" * 8)))
    with pytest.raises(t.ThreadsError):
        t.download(POST, tmp_path)


def test_messages_are_short_and_simple():
    for msg in (t.MSG_NO_VIDEO, t.MSG_TEXT_ONLY, t.MSG_IMAGES_ONLY, t.MSG_PROFILE):
        assert all(len(sentence.split()) <= 22 for sentence in msg.split(". "))


# ---- the pipeline and the bot ----------------------------------------------------------

def test_download_media_sends_threads_links_to_threads_code(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "download", lambda url, workdir: ([Path("v.mp4")], "cap", {"name": "A"}))
    monkeypatch.setitem(sys.modules, "yt_dlp", None)    # importing it would fail
    assert processor.download_media(POST, tmp_path) == ([Path("v.mp4")], "cap", {"name": "A"})


class Status:
    def __init__(self):
        self.texts = []

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)


def test_bot_shows_the_threads_message_as_it_is(monkeypatch):
    def fail(url, workdir):
        raise t.ThreadsError(t.MSG_NO_VIDEO)
    monkeypatch.setattr(bot.processor, "download_media", fail)
    monkeypatch.setattr(bot.processor, "process_videos",
                        lambda *a, **k: pytest.fail("no video, so no note"))
    status = Status()
    assert asyncio.run(bot.note_from_link(status, POST)) is None
    assert status.texts == [t.MSG_NO_VIDEO]               # no "Something went wrong", no cookies hint


def test_bot_still_shows_other_errors_the_old_way(monkeypatch):
    def fail(url, workdir):
        raise RuntimeError("boom")
    monkeypatch.setattr(bot.processor, "download_media", fail)
    status = Status()
    asyncio.run(bot.note_from_link(status, "https://www.instagram.com/reel/ABC/"))
    assert status.texts[0].startswith("❌ Something went wrong: boom")


def test_threads_video_makes_a_note_through_the_normal_pipeline(tmp_path, monkeypatch):
    Net(monkeypatch)
    seen = {}
    def fake_process(videos, source, caption, creator):
        # the real download_media ran, so the video file must exist right now
        assert videos[0].read_bytes() == b"video-bytes"
        seen.update(source=source, caption=caption, creator=creator)
        return Path("n.md"), {"timings": {"whisper": 1.0}}
    monkeypatch.setattr(bot.processor, "process_videos", fake_process)
    monkeypatch.setattr(bot.processor, "log_timing", lambda *a, **k: None)
    monkeypatch.setattr(bot, "send_note_reply", lambda status, data, path: asyncio.sleep(0))
    assert asyncio.run(bot.note_from_link(Status(), POST)) == Path("n.md")
    assert seen["source"] == POST and seen["caption"] == "Nice clip, I'm happy"
    assert seen["creator"]["handle"] == "ann"


# ---- links the Threads app really gives (found in a real bot.log) ---------------------

SHARE = "https://www.threads.com/share/_aB3xYz12"
MEDIA = "https://www.threads.com/@ann/post/AbC123/media?xmt=tracking"


@pytest.mark.parametrize("url,ok", [
    (SHARE, True),
    ("https://www.threads.net/share/_aB3xYz12?x=1", True),
    ("https://www.threads.com/t/AbC123", True),
    ("https://www.threads.com/@ann", False),
    ("https://www.threads.com/share", False),
    ("https://www.threads.com/", False),
    (POST, False),
])
def test_is_share_link(url, ok):
    assert t.is_share_link(url) is ok


def test_share_link_is_not_called_a_profile(tmp_path, monkeypatch):
    net = Net(monkeypatch)                    # the page answer ends at the real post address
    videos, caption, creator = t.download(SHARE, tmp_path)
    assert videos[0].read_bytes() == b"video-bytes"
    assert [c[0] for c in net.page_calls] == [SHARE]              # still ONE request to Threads
    assert creator["handle"] == "ann"


def test_share_link_whose_page_has_no_name_takes_it_from_where_it_ended(tmp_path, monkeypatch):
    Net(monkeypatch, page_resp=Resp(text=page(title="Threads"), url="https://www.threads.com/@bob/post/Zz9"))
    assert t.download(SHARE, tmp_path)[2]["handle"] == "bob"


def test_media_link_asks_for_the_post_page_and_is_the_same_post(tmp_path, monkeypatch):
    assert t.page_url(MEDIA) == "https://www.threads.com/@ann/post/AbC123"
    assert t.page_url(MEDIA + "#x") == "https://www.threads.com/@ann/post/AbC123"
    assert t.dedupe_key(MEDIA) == t.dedupe_key(POST) == "threads:AbC123"
    net = Net(monkeypatch)
    t.download(MEDIA, tmp_path)
    assert [c[0] for c in net.page_calls] == ["https://www.threads.com/@ann/post/AbC123"]


def test_an_empty_page_is_described_in_the_log(tmp_path, monkeypatch, capsys):
    shell = ('<html><head><title>Threads</title><meta property="og:site_name" content="Threads">'
             "</head><body>Log in to see more</body></html>")
    Net(monkeypatch, page_resp=Resp(text=shell, url="https://www.threads.com/@ann/post/AbC123",
                                    headers={"Content-Type": "text/html; charset=utf-8"}))
    with pytest.raises(t.ThreadsError) as err:
        t.download(POST, tmp_path)
    assert str(err.value) == t.MSG_NO_VIDEO                       # the user still sees one sentence
    log = capsys.readouterr().out
    for part in ("no video address", "HTTP 200", "title='Threads'", "og:site_name",
                 "video_versions=0", "login words=1", "text/html"):
        assert part in log, part
    assert "Log in to see more" not in log                         # the page text is not copied
