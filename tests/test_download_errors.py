"""A failed yt-dlp download shows yt-dlp's real error in the chat, cleaned. No network is used."""
import asyncio
import os
from pathlib import Path

import pytest
import yt_dlp

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor  # noqa: E402

REEL = "https://www.instagram.com/reel/ABC123/?igsh=private-looking-token"

INSTAGRAM_LOGIN = (
    "\x1b[0;31mERROR:\x1b[0m [Instagram] ABC123: Requested content is not available, rate-limit reached "
    "or login required. Use --cookies, --cookies-from-browser, --username and --password, --netrc-cmd, "
    "or --netrc (instagram) to provide account credentials. See  "
    "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  "
    "for how to manually pass cookies")


def fake_ytdlp(monkeypatch, behave):
    """Replace yt_dlp.YoutubeDL; `behave(opts)` returns info or raises. Records the options."""
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            calls.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            return behave(self.opts)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    return calls


def logs_then_returns_nothing(message):
    def behave(opts):                       # what yt-dlp does with ignoreerrors=True
        opts["logger"].error(message)
        return None
    return behave


# ---- cleaning ---------------------------------------------------------------------------

def test_clean_removes_colours_error_prefix_and_the_cookie_advice():
    text = processor.clean_ytdlp_error(INSTAGRAM_LOGIN)
    assert text == ("[Instagram] ABC123: Requested content is not available, "
                    "rate-limit reached or login required.")


@pytest.mark.parametrize("raw,clean", [
    ("ERROR: [youtube] abc: Private video", "[youtube] abc: Private video"),
    ("error:  ERROR: twice", "twice"),
    ("WARNING: ERROR: [tiktok] 1: Video not available", "[tiktok] 1: Video not available"),
    ("\x1b[1;31mERROR:\x1b[0m red", "red"),
    ("  lots \n of\t space  ", "lots of space"),
    ("", "unknown error"),
    (None, "unknown error"),
    ("ERROR: ", "unknown error"),
])
def test_clean_small_cases(raw, clean):
    assert processor.clean_ytdlp_error(raw) == clean


def test_clean_hides_links_and_file_paths():
    raw = ("ERROR: unable to download https://cdn.example.com/v.mp4?token=private-looking-token "
           r"to C:\path\to\reel-notes\tmp\item_1.mp4 or /tmp/tmpabc/item_NA.mp4 "
           "(~/reel-notes/cookies.txt) www.example.com/a?sig=x. HTTP Error 403: Forbidden")
    text = processor.clean_ytdlp_error(raw)
    for secret in ("private-looking-token", "cdn.example.com", "path", "tmpabc", "reel-notes",
                   "cookies", "sig=", "www."):
        assert secret not in text
    assert "[link]" in text and "[file]" in text and text.endswith("HTTP Error 403: Forbidden")


def test_clean_drops_any_sentence_about_cookies_passwords_or_tokens():
    raw = "ERROR: Login failed. Your cookies.txt is old. Bad password given. Token expired! Try later."
    assert processor.clean_ytdlp_error(raw) == "Login failed. Try later."


def test_clean_keeps_normal_slashes_and_numbers():
    assert processor.clean_ytdlp_error("ERROR: rate-limit/x after 1/2 tries") == "rate-limit/x after 1/2 tries"


def test_clean_is_about_300_characters():
    text = processor.clean_ytdlp_error("ERROR: " + "word " * 200)
    assert len(text) == 300 and text.endswith("…")
    assert len(processor.clean_ytdlp_error("a" * 300)) == 300     # exactly at the limit: not cut
    assert processor.clean_ytdlp_error("a" * 300).endswith("a")


# ---- the reply ----------------------------------------------------------------------------

def test_reply_for_a_normal_link():
    text = processor.download_failed_text("ERROR: [youtube] abc: Private video")
    assert text == ("❌ I could not download this video.\n"
                    "Reason: [youtube] abc: Private video\n\n"
                    "Try /update (a new yt-dlp often fixes it), or send me the video file.")


def test_reply_for_an_x_link_keeps_the_x_sentence():
    text = processor.download_failed_text("ERROR: [twitter] 1: No video", x_link=True)
    assert text == processor.MSG_X_NO_VIDEO + "\nReason: [twitter] 1: No video"


def test_download_shows_the_last_yt_dlp_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "cookies-file"))
    calls = fake_ytdlp(monkeypatch, logs_then_returns_nothing(INSTAGRAM_LOGIN))
    with pytest.raises(processor.VideoNotSaved) as err:
        processor.download_media(REEL, tmp_path)
    text = str(err.value)
    assert "Reason: [Instagram] ABC123: Requested content is not available" in text
    assert "Nothing could be downloaded" not in text                 # the old, often wrong reason
    for secret in ("private-looking-token", "cookies", "http", str(tmp_path), "ERROR", "\x1b"):
        assert secret not in text
    assert isinstance(calls[0]["logger"], processor.YtdlpErrors)       # every site gets the logger
    assert calls[0]["cookiefile"] == str(tmp_path / "cookies-file")   # cookies use is unchanged
    log = capsys.readouterr().out
    assert " download: yt-dlp failed: " in log and "private-looking-token" not in log


def test_a_crash_without_a_yt_dlp_error_shows_the_crash(tmp_path, monkeypatch):
    def crash(opts):
        raise ConnectionResetError("connection reset by peer")
    fake_ytdlp(monkeypatch, crash)
    with pytest.raises(processor.VideoNotSaved, match="Reason: connection reset by peer"):
        processor.download_media(REEL, tmp_path)


def test_a_good_download_is_not_changed(tmp_path, monkeypatch):
    def good(opts):
        (Path(opts["outtmpl"]).parent / "item_NA.mp4").write_bytes(b"video")
        return {"description": "cap", "uploader": "Ann"}
    fake_ytdlp(monkeypatch, good)
    slides, caption, _ = processor.download_media(REEL, tmp_path)
    assert [s.name for s in slides] == ["item_NA.mp4"] and caption == "cap"


# ---- the bot ------------------------------------------------------------------------------

class Status:
    def __init__(self):
        self.texts = []

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)


def test_bot_shows_the_real_error_instead_of_something_went_wrong(tmp_path, monkeypatch):
    fake_ytdlp(monkeypatch, logs_then_returns_nothing("ERROR: [youtube] abc: Private video"))
    monkeypatch.setattr(bot.processor, "process_videos", lambda *a, **k: pytest.fail("no video, no note"))
    status = Status()
    assert asyncio.run(bot.note_from_link(status, "https://youtube.com/shorts/abc")) is None
    assert status.texts == [processor.download_failed_text("ERROR: [youtube] abc: Private video")]
    assert "Something went wrong" not in status.texts[0]


def test_threads_reply_is_not_changed(monkeypatch):
    def fail(url, workdir):
        raise bot.threads_link.ThreadsError(bot.threads_link.MSG_NO_VIDEO)
    monkeypatch.setattr(bot.processor.threads_link, "download", fail)
    status = Status()
    assert asyncio.run(bot.note_from_link(status, "https://www.threads.net/@ann/post/ABC")) is None
    assert status.texts == ["I could not get this Threads video. Please save the video and send me the file."]
