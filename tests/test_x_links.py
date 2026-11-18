"""Tests for X (x.com / twitter.com) links. yt-dlp is replaced by a fake: no network is used."""
import asyncio
import os
from pathlib import Path

import pytest
import yt_dlp

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor  # noqa: E402

TWEET = "https://x.com/ann/status/1234567890"
EXACT = "I could not get this X video. Please save the video and send me the file."


def fake_ytdlp(monkeypatch, behave):
    """Replace yt_dlp.YoutubeDL. `behave(opts, url)` returns info, or raises. Records the options."""
    class FakeYDL:
        calls = []

        def __init__(self, opts):
            self.opts = opts
            FakeYDL.calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            return behave(self.opts, url)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


def write_video(opts, name="item_NA.mp4"):
    path = Path(opts["outtmpl"]).parent / name
    path.write_bytes(b"video")
    return path


def good(opts, url):
    write_video(opts)
    return {"description": "Great tip about Python", "uploader": "Ann Lee", "uploader_id": "ann",
            "uploader_url": "https://twitter.com/ann"}


# ---- links ----------------------------------------------------------------------------

@pytest.mark.parametrize("url,ok", [
    ("https://x.com/ann/status/1", True),
    ("https://www.x.com/ann/status/1", True),
    ("https://twitter.com/ann/status/1?s=20", True),
    ("http://mobile.twitter.com/ann/status/1", True),
    ("https://m.twitter.com/ann/status/1", True),
    ("https://x.com/i/status/1", True),
    ("https://x.com/ann", True),                  # a profile is still an X link (yt-dlp will refuse it)
    ("https://fixupx.com/ann/status/1", False),
    ("https://linux.com/ann/status/1", False),
    ("https://example.com/x.com/status/1", False),
    ("https://www.instagram.com/reel/ABC/", False),
    ("", False),
])
def test_is_x_url(url, ok):
    assert processor.is_x_url(url) is ok


def test_same_post_on_every_x_address_is_a_duplicate(tmp_path, monkeypatch):
    same = ["https://x.com/ann/status/1234567890", "https://twitter.com/ann/status/1234567890?s=20&t=abc",
            "https://mobile.twitter.com/Ann/status/1234567890/", "https://x.com/i/status/1234567890",
            "https://x.com/ann/statuses/1234567890"]
    assert len({processor.normalise_url(u) for u in same}) == 1
    assert processor.normalise_url(same[0]) != processor.normalise_url("https://x.com/ann/status/999")
    notes = tmp_path / "notes"
    notes.mkdir()
    monkeypatch.setattr(processor, "NOTES_DIR", notes)
    (notes / "2026-11-18_1200_tip.md").write_text(f"# Tip\n\n- Source: {same[1]}\n", encoding="utf-8")
    assert processor.find_note_by_source(same[3]).name == "2026-11-18_1200_tip.md"


# ---- download ---------------------------------------------------------------------------

def test_x_video_goes_through_yt_dlp(tmp_path, monkeypatch):
    fake = fake_ytdlp(monkeypatch, good)
    monkeypatch.setattr(processor.threads_link, "download", lambda *a: pytest.fail("not a Threads link"))
    slides, caption, creator = processor.download_media(TWEET, tmp_path)
    assert [s.name for s in slides] == ["item_NA.mp4"]
    assert caption == "Great tip about Python"
    assert creator == {"name": "Ann Lee", "handle": "ann", "url": "https://twitter.com/ann"}
    assert len(fake.calls) == 1                                 # one yt-dlp run, no other request


def test_x_never_gets_cookies_but_other_sites_still_do(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "cookies-file"))
    fake = fake_ytdlp(monkeypatch, good)
    processor.download_media(TWEET, tmp_path)
    processor.download_media("https://twitter.com/ann/status/1?s=20", tmp_path)
    processor.download_media("https://www.instagram.com/reel/ABC/", tmp_path)
    x1, x2, insta = fake.calls
    for opts in (x1, x2):
        assert "cookiefile" not in opts and "cookiesfrombrowser" not in opts
        assert "username" not in opts and "password" not in opts
    assert insta["cookiefile"] == str(tmp_path / "cookies-file")   # unchanged for Instagram


def test_post_with_several_videos_gives_several_slides(tmp_path, monkeypatch):
    def two(opts, url):
        write_video(opts, "item_1.mp4")
        write_video(opts, "item_2.mp4")
        return {"entries": [{"description": "Two clips", "uploader": "Ann"}, {}]}
    fake_ytdlp(monkeypatch, two)
    slides, caption, _ = processor.download_media(TWEET, tmp_path)
    assert [s.name for s in slides] == ["item_1.mp4", "item_2.mp4"] and caption == "Two clips"


def raises_download_error(opts, url):
    raise yt_dlp.utils.DownloadError("ERROR: [twitter] 1234567890: No video could be found in this tweet")


def returns_nothing_and_logs(opts, url):          # what yt-dlp does with ignoreerrors=True
    opts["logger"].error("ERROR: [twitter] 1234567890: Sign in to confirm your age")
    return None


def returns_nothing_quietly(opts, url):
    return None


def crashes(opts, url):
    raise ConnectionResetError("connection reset")


@pytest.mark.parametrize("behave,reason", [
    (raises_download_error, "No video could be found"),
    (returns_nothing_and_logs, "Sign in to confirm your age"),
    (returns_nothing_quietly, "Nothing could be downloaded"),
    (crashes, "ConnectionResetError"),
], ids=["download-error", "error-logged-by-yt-dlp", "nothing-downloaded", "network-crash"])
def test_failure_gives_the_exact_reply_and_logs_the_real_error(tmp_path, monkeypatch, capsys, behave, reason):
    fake_ytdlp(monkeypatch, behave)
    with pytest.raises(processor.VideoNotSaved) as err:
        processor.download_media(TWEET + "?s=20&t=private-looking-token", tmp_path)
    assert str(err.value) == EXACT
    log = capsys.readouterr().out
    assert " x: yt-dlp failed:" in log and reason in log
    assert "private-looking-token" not in log and "https://x.com/ann/status/1234567890" in log


def test_other_sites_keep_their_old_errors(tmp_path, monkeypatch):
    fake_ytdlp(monkeypatch, raises_download_error)
    with pytest.raises(yt_dlp.utils.DownloadError):               # not turned into the X message
        processor.download_media("https://www.instagram.com/reel/ABC/", tmp_path)
    fake_ytdlp(monkeypatch, returns_nothing_quietly)
    with pytest.raises(RuntimeError, match="Nothing could be downloaded") as err:
        processor.download_media("https://www.tiktok.com/@a/video/1", tmp_path)
    assert not isinstance(err.value, processor.VideoNotSaved)


def test_error_logger_is_quiet_and_remembers_errors():
    log = processor.YtdlpErrors()
    log.debug("x"), log.info("x"), log.warning("x")
    log.error("ERROR: one")
    log.error("ERROR: two")
    assert log.errors == ["ERROR: one", "ERROR: two"]


def test_the_message_is_short_and_simple():
    assert all(len(sentence.split()) <= 22 for sentence in EXACT.split(". "))
    assert processor.MSG_X_NO_VIDEO == EXACT


# ---- the bot ---------------------------------------------------------------------------------

class Status:
    def __init__(self):
        self.texts = []

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)


def test_bot_shows_the_x_message_as_it_is(monkeypatch):
    def fail(url, workdir):
        raise processor.VideoNotSaved(processor.MSG_X_NO_VIDEO)
    monkeypatch.setattr(bot.processor, "download_media", fail)
    monkeypatch.setattr(bot.processor, "process_videos", lambda *a, **k: pytest.fail("no video, no note"))
    status = Status()
    assert asyncio.run(bot.note_from_link(status, TWEET)) is None
    assert status.texts == [EXACT]                      # no "Something went wrong", no cookies hint


def test_an_x_video_makes_a_note_through_the_normal_pipeline(tmp_path, monkeypatch):
    fake_ytdlp(monkeypatch, good)
    seen = {}

    def fake_process(videos, source, caption, creator):
        assert videos[0].read_bytes() == b"video"           # the file exists while the note is made
        seen.update(source=source, caption=caption, creator=creator)
        return Path("n.md"), {"timings": {"whisper": 1.0}}
    monkeypatch.setattr(bot.processor, "process_videos", fake_process)
    monkeypatch.setattr(bot.processor, "log_timing", lambda *a, **k: None)
    monkeypatch.setattr(bot, "send_note_reply", lambda status, data, path: asyncio.sleep(0))
    assert asyncio.run(bot.note_from_link(Status(), TWEET)) == Path("n.md")
    assert seen["source"] == TWEET and seen["caption"] == "Great tip about Python"
    assert seen["creator"]["handle"] == "ann"
