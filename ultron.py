"""Ultron — the assistant. Starts the HUD, loads the brains, and answers what you type in the HUD's box or
in this terminal.

  python ultron.py            HUD + terminal
  python ultron.py --no-hud   terminal only

Each message: FRIDAY picks the domain; an assistant request goes to EDITH, whose skill call runs a local skill
and can raise a HUD panel (calendar, reminders); chat is answered by the base model with the adapters off;
code and research are recognised but not handled. Say "power down" (or "exit") to close everything.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import hud_display
from paths import APP_DIR, FROZEN
from skills import Skills

HERE = APP_DIR
HUD_STATE_PATH = HERE / "hud_state.json"
HUD_SHUTDOWN_PATH = HERE / "hud_shutdown.json"
HUD_INPUT_QUEUE_DIR = HERE / "hud_input_queue"
POWER_DOWN = {"power down", "shut down", "shutdown", "exit", "quit", "goodbye"}


def write_state(**state) -> None:
    """What the HUD's status bar shows. Written atomically; never allowed to break a turn."""
    try:
        current = json.loads(HUD_STATE_PATH.read_text(encoding="utf-8")) if HUD_STATE_PATH.exists() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(state)
    try:
        tmp = HUD_STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(current), encoding="utf-8")
        os.replace(tmp, HUD_STATE_PATH)
    except OSError:
        pass


def _terminal_input(inbox: "queue.Queue[tuple[str, str]]", stop: threading.Event, eof_quits: bool) -> None:
    """Terminal input. When the terminal is the only way in (--no-hud), its end means quit. With the HUD it
    doesn't: measured, a launch with no usable console hit end-of-file at once and powered a working HUD down."""
    while not stop.is_set():
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            if eof_quits:
                inbox.put(("terminal", "power down"))
            return
        if line.strip():
            inbox.put(("terminal", line.strip()))


def _hud_input(inbox: "queue.Queue[tuple[str, str]]", stop: threading.Event) -> None:
    """The HUD writes one file per message (atomically, via rename); take them in order and delete them."""
    HUD_INPUT_QUEUE_DIR.mkdir(exist_ok=True)
    while not stop.is_set():
        for f in sorted(HUD_INPUT_QUEUE_DIR.glob("*.json")):
            try:
                text = json.loads(f.read_text(encoding="utf-8")).get("text", "").strip()
            except (OSError, json.JSONDecodeError):
                text = ""
            try:
                f.unlink()
            except OSError:
                pass
            if text:
                inbox.put(("hud", text))
        time.sleep(0.15)


def handle(brains, skills: Skills, text: str) -> str:
    started = time.time()
    write_state(active_brain="FRIDAY", thinking=True)
    domain = brains.friday(text)
    print(f"  [FRIDAY] {domain}")
    panel = None
    if domain == "pa_domain":
        write_state(active_brain="EDITH")
        call, skill, fields = brains.edith(text, skills.recent)
        print(f"  [EDITH]  {call or '(no skill call)'}")
        reply, panel = skills.run(skill, fields) if skill else ("I couldn't turn that into an action.", None)
    elif domain == "conversation":
        write_state(active_brain="FRIDAY")
        reply = brains.chat(text)
    if domain != "pa_domain":
        skills.recent = ""          # the next turn only — see Skills.run
    if domain in ("code_domain", "research_needed"):
        reply = f"That's a {domain.replace('_', ' ')} request — I only handle chat and assistant tasks."
    if panel:
        kind, title, content = panel
        hud_display.push_display(kind, title, {**content, "reply_text": reply})
    else:
        hud_display.push_display("reply", "", {"text": reply})
    write_state(thinking=False, response_latency_ms=round((time.time() - started) * 1000))
    return reply


def _start_hud(minimized: bool = False) -> subprocess.Popen:
    """The HUD runs as its own process. Packaged, there's no python to run hud.py with, so the exe relaunches
    itself with --hud. --minimized starts the window minimized and without taking focus."""
    # Windows applies the way THIS process was launched (e.g. hidden, from a shortcut or a scheduler) to the first
    # window a child shows; measured: a hidden launch gave an invisible HUD. So the HUD always asks to be shown.
    kw = {"cwd": str(HERE)}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7 if minimized else 1  # SW_SHOWMINNOACTIVE / SW_SHOWNORMAL
        kw["startupinfo"] = si
    extra = ["--minimized"] if minimized else []
    if FROZEN:
        return subprocess.Popen([sys.executable, "--hud", *extra], **kw)
    return subprocess.Popen([sys.executable, str(Path(__file__).parent / "hud.py"), *extra], **kw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hud", action="store_true", help="terminal only")
    ap.add_argument("--hud", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--minimized", action="store_true", help="start the window minimized, without taking focus")
    args = ap.parse_args()
    if sys.stdout is None or sys.stderr is None:
        # A windowed exe has no console: everything printed (and the libraries' progress bars, which would crash
        # on a missing stream) goes to a log next to the exe instead.
        log = open(HERE / ("hud.log" if args.hud else "ultron.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.hud:
        import hud
        hud.run(minimized=args.minimized)
        return

    # A message left in the queue by an earlier session (a "power down" from closing the window, say) must never
    # act on this one — measured: one did, and this session powered down the moment it was ready.
    for stale in (HUD_SHUTDOWN_PATH, hud_display.DISPLAY_PATH, *HUD_INPUT_QUEUE_DIR.glob("*.json*")):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass
    write_state(mode="LOADING", active_brain="STANDBY", input_mode="TYPED", thinking=False, response_latency_ms=None)
    hud = None if args.no_hud else _start_hud(args.minimized)

    inbox: "queue.Queue[tuple[str, str]]" = queue.Queue()
    stop = threading.Event()
    print("Loading the base model and both adapters...")
    try:
        from brains import Brains
        brains = Brains()
    except RuntimeError as e:
        # Shown where the user is looking (the HUD), then a clean power-down — never a window left saying LOADING.
        print(f"Can't start: {e}")
        write_state(mode="STOPPED", active_brain="STANDBY")
        hud_display.push_display("reply", "", {"text": f"Can't start: {e}"}, ttl=0)
        if hud is not None:
            time.sleep(12)
        _power_down(hud)
        return
    skills = Skills()
    write_state(mode="LOCAL", active_brain="STANDBY")
    hud_display.push_display("reply", "", {"text": "Online. Type a message below."}, ttl=30)
    print("Ready. Type here or in the HUD. \"power down\" to close.")
    if sys.stdin is not None and sys.stdin.isatty():
        threading.Thread(target=_terminal_input, args=(inbox, stop, hud is None), daemon=True).start()
    if hud is not None:
        threading.Thread(target=_hud_input, args=(inbox, stop), daemon=True).start()
    try:
        while True:
            source, text = inbox.get()
            if source == "hud":
                print(f"\nyou (HUD)> {text}")
            if text.lower().strip(" .!") in POWER_DOWN:
                break
            try:
                print("ultron>", handle(brains, skills, text))
            except Exception as e:  # a failed turn is reported, never fatal
                print(f"ultron> Something went wrong on that one ({type(e).__name__}: {e}).")
                write_state(thinking=False, active_brain="STANDBY")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        _power_down(hud)


def _power_down(hud) -> None:
    print("Powering down.")
    try:
        HUD_SHUTDOWN_PATH.write_text(json.dumps({"shutdown": True, "message": "Powering down."}), encoding="utf-8")
    except OSError:
        pass
    if hud is not None:
        time.sleep(3.0)                     # the page sees the signal and closes its own window first
        hud.terminate()
        try:
            hud.wait(timeout=5)
        except subprocess.TimeoutExpired:
            hud.kill()
    for leftover in (HUD_STATE_PATH, hud_display.DISPLAY_PATH):
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
