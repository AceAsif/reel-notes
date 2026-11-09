"""System tray icon for the Reel Notes bot (Windows).

Runs bot.py in the background, restarts it if it crashes, and shows its status
as a coloured dot next to the clock:
  green = running, yellow = starting, red = stopped / crashed.
Right-click the icon for: open notes, open log, restart, stop/start, quit.

Start it with:  .venv\\Scripts\\pythonw.exe tray.py   (pythonw = no console window)
"""
import datetime
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
LOG = HERE / "bot.log"
NOTES = HERE / "notes"
PYTHON = HERE / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

STARTUP_DELAY = 30    # seconds to wait after login (Wi-Fi, Ollama)
RESTART_DELAY = 60    # seconds to wait before restarting after a crash
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

COLOURS = {"running": "#22c55e", "starting": "#eab308", "stopped": "#ef4444"}


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")


def make_image(state: str) -> Image.Image:
    """A coloured circle with a white 'R' (for Reel Notes)."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=COLOURS[state])
    draw.text((32, 32), "R", fill="white", font_size=34, anchor="mm")
    return img


class BotRunner:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.should_run = True
        self.state = "starting"
        self.started_at: datetime.datetime | None = None
        self.icon: pystray.Icon | None = None

    # ---- bot process -------------------------------------------------
    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start_bot(self) -> None:
        if self.is_running():
            return
        log("Starting bot")
        logfile = LOG.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(PYTHON), "-u", str(HERE / "bot.py")],
            cwd=HERE, stdout=logfile, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        self.started_at = datetime.datetime.now()

    def stop_bot(self) -> None:
        if self.is_running():
            log("Stopping bot")
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.started_at = None

    # ---- tray icon ---------------------------------------------------
    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        if self.icon:
            self.icon.icon = make_image(state)
            self.icon.title = f"Reel Notes bot: {self.status_text()}"
            self.icon.update_menu()

    def status_text(self) -> str:
        if self.state == "running" and self.started_at:
            mins = int((datetime.datetime.now() - self.started_at).total_seconds() // 60)
            return f"running ({mins // 60}h {mins % 60}m)"
        return self.state

    def watch(self) -> None:
        """Background loop: start after delay, restart after crashes, update icon."""
        time.sleep(STARTUP_DELAY)
        while True:
            if self.should_run and not self.is_running():
                if self.proc is not None:  # it was running and died
                    log(f"Bot stopped unexpectedly, restarting in {RESTART_DELAY}s")
                    self.proc = None
                    self.set_state("stopped")
                    time.sleep(RESTART_DELAY)
                    if not self.should_run:
                        continue
                self.set_state("starting")
                self.start_bot()
                time.sleep(5)
            if self.is_running():
                self.set_state("running")
            elif not self.should_run:
                self.set_state("stopped")
            if self.icon:
                self.icon.title = f"Reel Notes bot: {self.status_text()}"
            time.sleep(5)

    # ---- menu actions --------------------------------------------------
    def open_notes(self, *_):
        NOTES.mkdir(exist_ok=True)
        os.startfile(NOTES)

    def open_log(self, *_):
        LOG.touch()
        os.startfile(LOG)

    def restart(self, *_):
        self.stop_bot()
        self.should_run = True
        self.set_state("starting")
        self.start_bot()

    def toggle(self, *_):
        if self.should_run:
            self.should_run = False
            self.stop_bot()
            self.set_state("stopped")
        else:
            self.should_run = True
            self.set_state("starting")
            self.start_bot()

    def quit(self, icon, *_):
        self.should_run = False
        self.stop_bot()
        log("Tray app closed")
        icon.stop()

    def run(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem(lambda _: f"Status: {self.status_text()}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open notes folder", self.open_notes, default=True),
            pystray.MenuItem("Open log", self.open_log),
            pystray.MenuItem("Restart bot", self.restart),
            pystray.MenuItem(lambda _: "Stop bot" if self.should_run else "Start bot", self.toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        )
        self.icon = pystray.Icon("reel-notes", make_image("starting"),
                                 "Reel Notes bot: starting", menu)
        threading.Thread(target=self.watch, daemon=True).start()
        self.icon.run()


def already_running() -> bool:
    """Stop a second copy (two bots at once = Telegram 'Conflict' error)."""
    global _lock
    _lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock.bind(("127.0.0.1", 47321))
        return False
    except OSError:
        return True


if __name__ == "__main__":
    if already_running():
        sys.exit(0)
    log("Tray app started")
    BotRunner().run()
