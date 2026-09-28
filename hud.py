"""Ultron's HUD — a local page (the animated core, a skill panel, a status bar and a text box).

It never imports ultron.py. The two processes share a few small files:
  hud_state.json   ultron.py -> HUD   mode, active brain, last response time
  hud_display.json ultron.py -> HUD   the panel to show (reply, calendar, reminders)  — see hud_display.py
  hud_input_queue/ HUD -> ultron.py   one file per typed message, written atomically
  hud_shutdown.json ultron.py -> HUD  "powering down" — the page closes itself

  python hud.py        (ultron.py starts it for you)
"""
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer

import hud_display
from paths import APP_DIR

HERE = APP_DIR
HUD_STATE_PATH = HERE / "hud_state.json"
HUD_SHUTDOWN_PATH = HERE / "hud_shutdown.json"
HUD_INPUT_QUEUE_DIR = HERE / "hud_input_queue"
PORT = 8766

_browser_proc: "subprocess.Popen | None" = None
_shutdown_kill_scheduled = False
_app_mode_launch = False
_native = {"window": None}   # the pywebview window, when there is one
_RECENT_SUBMIT_IDS: "deque[str]" = deque(maxlen=200)


def _hud_profile_dir() -> Path:
    return APP_DIR / ".hud_browser_profile"


def _kill_hud_browser_by_profile() -> int:
    try:
        import psutil
    except ImportError:
        return 0
    marker = str(_hud_profile_dir()).lower().replace("/", "\\")
    n = 0
    _browsers = ("chrome.exe", "msedge.exe", "chromium.exe", "brave.exe", "chrome", "msedge", "chromium", "brave")
    for proc in psutil.process_iter(["cmdline", "name"]):
        try:


            if (proc.info.get("name") or "").lower() not in _browsers:
                continue
            cmd = " ".join(proc.info.get("cmdline") or []).lower().replace("/", "\\")
            if marker in cmd:
                proc.terminate(); n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return n


def _find_app_mode_browser() -> str | None:
    for exe_name in (
        "google-chrome", "google-chrome-stable", "chromium",
        "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "msedge",
    ):
        found = shutil.which(exe_name)
        if found:
            return found

    candidates_by_os = {
        "Windows": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "Darwin": [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ],
        "Linux": [],
    }
    for path in candidates_by_os.get(platform.system(), []):
        if Path(path).exists():
            return path
    return None


class _QuietThreadingHTTPServer(ThreadingHTTPServer):

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _open_hud_window(url: str) -> None:
    global _browser_proc, _app_mode_launch
    browser_path = _find_app_mode_browser()
    if browser_path:
        try:


            profile_dir = _hud_profile_dir()


            _orphans = _kill_hud_browser_by_profile()
            if _orphans:
                print(f"Ultron HUD: closed {_orphans} orphaned HUD window process(es) from an earlier session")
                time.sleep(0.8)
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)
            profile_dir.mkdir(exist_ok=True)


            browser_args = [
                browser_path,
                f"--app={url}",
                "--window-size=1400,800",
                f"--user-data-dir={profile_dir}",
                "--disk-cache-size=52428800",
            ]
            _browser_proc = subprocess.Popen(browser_args)
            _app_mode_launch = True
            return
        except OSError:
            pass
    print(
        "Ultron HUD: no Chrome/Edge/Chromium found for an app-mode window — "
        "opening a normal browser tab instead. Auto-close on shutdown is "
        "best-effort in this mode, since browsers block scripts from "
        "closing tabs they didn't open themselves."
    )
    webbrowser.open(url)


def _build_tick_ring(cx=300, cy=300, radius=292, count=96, major_every=6, tick_len=9, major_len=18) -> str:
    lines = []
    for i in range(count):
        angle = (360 / count) * i
        rad = math.radians(angle)
        is_major = (i % major_every == 0)
        length = major_len if is_major else tick_len
        x1, y1 = cx + radius * math.cos(rad), cy + radius * math.sin(rad)
        x2, y2 = cx + (radius - length) * math.cos(rad), cy + (radius - length) * math.sin(rad)
        if is_major:
            cls = "tick-major"
        else:
            cls = "tick-blue" if (i // major_every) % 2 == 0 else "tick-red"
        lines.append(f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    return "".join(lines)


def _build_layered_chassis_group(base_radius, class_prefix, segments, bar_density=200) -> str:
    cx, cy = 300, 300
    group_elements = []

    bar_elements = []
    for i in range(bar_density):
        angle_pct = i / bar_density
        is_inside = any(seg["start"] <= angle_pct <= seg["end"] for seg in segments)
        if not is_inside:
            continue

        angle = angle_pct * 360
        rad = math.radians(angle)
        x1, y1 = cx + base_radius * math.cos(rad), cy + base_radius * math.sin(rad)

        bar_elements.append(
            f'<line class="eq-bar {class_prefix}" data-angle="{angle:.2f}" data-r0="{base_radius}" '
            f'x1="{x1:.1f}" y1="{y1:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>'
        )
    group_elements.append("".join(bar_elements))

    base_paths = []
    for seg in segments:
        s_rad = math.radians(seg["start"] * 360)
        e_rad = math.radians(seg["end"] * 360)
        sx, sy = cx + base_radius * math.cos(s_rad), cy + base_radius * math.sin(s_rad)
        ex, ey = cx + base_radius * math.cos(e_rad), cy + base_radius * math.sin(e_rad)
        long_arc = 1 if (seg["end"] - seg["start"]) > 0.5 else 0
        base_paths.append(f"M {sx:.2f} {sy:.2f} A {base_radius} {base_radius} 0 {long_arc} 1 {ex:.2f} {ey:.2f}")

    group_elements.append(f'<path class="solid-base-arc {class_prefix}-base" d="{" ".join(base_paths)}"/>')

    return "".join(group_elements)


def _build_3d_particle_pool(count=140) -> str:
    elements = []
    for i in range(count):
        elements.append(f'<circle id="cp-{i}" class="core-particle" r="5.5" filter="url(#blur-dust)"/>')
    return "".join(elements)


TICK_RING_SVG = _build_tick_ring()

_INNER_SEGS = [{"start": 0.05, "end": 0.45}, {"start": 0.55, "end": 0.95}]
_MID_SEGS   = [{"start": 0.00, "end": 0.25}, {"start": 0.35, "end": 0.65}, {"start": 0.75, "end": 0.92}]
_OUTER_SEGS = [{"start": 0.10, "end": 0.40}, {"start": 0.50, "end": 0.85}]

WAVE_INNER_SVG = _build_layered_chassis_group(130, "wave-blue", _INNER_SEGS, 260)
WAVE_MID_SVG   = _build_layered_chassis_group(190, "wave-red",  _MID_SEGS,   340)
WAVE_OUTER_SVG = _build_layered_chassis_group(250, "wave-blue", _OUTER_SEGS, 420)
CORE_FOG_SVG = _build_3d_particle_pool()

_RING_SPECS = [
    ("1", "none",   "ring-blue",  "spin-a"),
    ("2", "5 10",   "ring-red",   "spin-b"),
    ("3", "2 8",    "ring-blue",  "spin-a"),
]


def _build_rings_svg() -> str:
    parts = []
    for suffix, dash, color_cls, spin_cls in _RING_SPECS:
        dash_attr = f' stroke-dasharray="{dash}"' if dash != "none" else ""
        parts.append(
            f'<g class="{spin_cls}"><circle class="ring ring-{suffix} {color_cls}" '
            f'cx="300" cy="300"{dash_attr}/></g>'
        )
    return "".join(parts)


def _build_ring_css() -> str:
    base_radii = [154, 214, 274]
    expand_to = [164, 226, 286]
    rules = []
    for i, (suffix, _, _, _) in enumerate(_RING_SPECS):
        delay = i * 0.05
        rules.append(
            f'.ring-{suffix} {{ r: {base_radii[i]}px; transition: r 0.6s cubic-bezier(.2,.8,.3,1.4) {delay}s, '
            f'opacity 0.4s ease {delay}s; }}'
        )
        rules.append(f'body.speaking .ring-{suffix} {{ r: {expand_to[i]}px; }}')
    return "\n  ".join(rules)


RINGS_SVG = _build_rings_svg()
RING_CSS = _build_ring_css()

PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Ultron HUD</title>
<style>
  
  :root {
    color-scheme: dark;
    --accent-primary: #ff1a1a;
    --accent-secondary: #ff4400;
    --accent-tertiary: #ff1100;
    --accent-secondary-fade: rgba(255,68,0,0.3);
    --bg-gradient-start: #1c0b0b;
    --bg-gradient-mid: #0d0606;
    --bg-gradient-end: #050202;
    
    --border-color: #331414;
    --bg-status-start: rgba(13,5,5,0.95);
    --bg-status-end: rgba(8,3,3,0.98);
    --bg-input-start: rgba(18,7,7,0.95);
    --bg-input-end: rgba(10,4,4,0.98);
    --send-btn-bg: #c0392b;
    --send-btn-hover: #d84a3a;
    --warn-color: #ff4d4d;
    --footer-accent: #ff6666;
    --divider-color: rgba(51,20,20,0.8);
    --crit-color-dark: #8b0000;
  }
  
  svg.globe *, .status-item .stat-value, .status-bar, .hud-input-row,
  .hud-input-box, .hud-input-send, .status-footer b, .warn, body {
    transition: stroke 1.5s ease, fill 1.5s ease, color 1.5s ease,
      background-color 1.5s ease, background 1.5s ease, box-shadow 1.5s ease,
      border-color 1.5s ease;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: radial-gradient(circle at center, var(--bg-gradient-start) 0%, var(--bg-gradient-mid) 60%, var(--bg-gradient-end) 100%);
    color: #eae6dc;
    font-family: 'Courier New', ui-monospace, monospace;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 16px 16px 60px 16px; 
    perspective: 1200px;
    overflow: hidden;
    position: relative;
  }
  
  body::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: -1;
    background: radial-gradient(circle at center, #0a1c0d 0%, #061006 60%, #020502 100%);
    opacity: 0;
    transition: opacity 1.5s ease;
    pointer-events: none;
  }

  .main-stage {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0px;
    width: 100%;
    max-width: 1200px;
    flex: 1;
    transition: gap 0.6s cubic-bezier(0.25, 0.8, 0.3, 1);
  }
  body.has-display.display-wide .main-stage { max-width: 1380px; }

  .core-zone {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: transform 0.6s cubic-bezier(0.25, 0.8, 0.3, 1),
                opacity 0.5s ease;
  }

  .reactor-wrap {
    position: relative;
    width: 620px;
    height: 620px;
    display: flex;
    align-items: center;
    justify-content: center;
    transform-style: preserve-3d;
    transform: rotateX(12deg);
    animation: tilt-drift 10s ease-in-out infinite;
    transition: width 0.6s cubic-bezier(0.25, 0.8, 0.3, 1),
                height 0.6s cubic-bezier(0.25, 0.8, 0.3, 1),
                transform 0.6s cubic-bezier(0.25, 0.8, 0.3, 1);
  }
  
  body.has-display.display-dense .reactor-wrap {
    width: 340px;
    height: 340px;
  }
  
  body.has-display.display-wide .reactor-wrap {
    width: 170px;
    height: 170px;
  }
  body.has-display.display-wide .glow {
    width: 130px;
    height: 130px;
  }
  body.has-display.display-wide .floor-shadow {
    width: 160px;
  }

  @keyframes tilt-drift {
    0%, 100% { transform: rotateX(10deg) rotateY(-3deg); }
    50%      { transform: rotateX(13deg) rotateY(3deg); }
  }

  .floor-shadow {
    position: absolute;
    width: 420px;
    height: 60px;
    bottom: -15px;
    border-radius: 50%;
    background: radial-gradient(ellipse, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0) 70%);
    transform: translateZ(-80px) scale(1.05);
    filter: blur(4px);
    transition: width 0.6s cubic-bezier(0.25, 0.8, 0.3, 1);
  }
  body.has-display .floor-shadow { width: 300px; }

  .glow {
    position: absolute;
    width: 340px;
    height: 340px;
    border-radius: 50%;
    background: radial-gradient(circle,
      rgba(210,218,226,0.12) 0%,
      rgba(210,218,226,0.28) 35%,
      rgba(255,26,26,0.15) 55%,
      rgba(255,26,26,0.06) 72%,
      rgba(210,218,226,0.02) 84%,
      rgba(0,0,0,0) 100%);
    filter: blur(14px);
    animation: breathe 3.4s ease-in-out infinite;
    transition: filter 0.4s ease, transform 0.5s ease, width 0.6s ease, height 0.6s ease;
  }
  body.has-display .glow { width: 240px; height: 240px; }
  @keyframes breathe {
    0%, 100% { opacity: 0.55; transform: scale(0.96); }
    50% { opacity: 0.95; transform: scale(1.05); }
  }

  svg.globe {
    width: 100%;
    height: 100%;
    position: relative;
    overflow: visible;
    filter: drop-shadow(0 20px 22px rgba(0,0,0,0.65));
  }

  body.speaking .glow { filter: blur(16px) brightness(1.5); transform: scale(1.18); }
  body.speaking .core-outer-ring { filter: brightness(1.6); }
  body.speaking .stat-value.speaking-label { color: var(--warn-color); text-shadow: 0 0 8px var(--accent-primary); }
  body.speaking .spin-a { animation-duration: 12s; }
  body.speaking .spin-b { animation-duration: 14s; }
  body.speaking .spin-c { animation-duration: 9s; }

  .spin-a, .spin-b, .spin-c { transform-origin: 300px 300px; }
  @keyframes spin-anim { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
  @keyframes spin-rev-anim { from { transform: rotate(360deg); } to { transform: rotate(0deg); } }

  .ring { fill: none; stroke-width: 2.2; }
  .ring-blue { stroke: #d2d7df; opacity: 0.45; }
  .ring-red  { stroke: var(--accent-primary); opacity: 0.35; }
  __RING_CSS__

  .solid-base-arc {
    fill: none;
    stroke-width: 4.0;
    stroke-linecap: round;
  }
  .wave-blue-base { stroke: #d2d7df; opacity: 0.85; filter: drop-shadow(0 0 1px rgba(210,215,223,0.3)); }
  .wave-red-base  { stroke: var(--accent-primary); opacity: 0.80; filter: drop-shadow(0 0 2px var(--accent-primary)); }

  .eq-bar {
    stroke-linecap: square;
    stroke-width: 1.4;
  }
  .wave-blue { stroke: #d2d7df; opacity: 0.70; }
  .wave-red  { stroke: var(--accent-primary); opacity: 0.65; }

  .tick-blue  { stroke: #d2d7df; stroke-width: 1.3; opacity: 0.65; }
  .tick-red   { stroke: var(--accent-primary); stroke-width: 1.3; opacity: 0.6; }
  .tick-major { stroke: var(--accent-secondary); stroke-width: 1.8; opacity: 0.95; }

  .leader { stroke: rgba(138,147,158,0.3); stroke-width: 1; stroke-dasharray: 2 4; }

  .core-void { fill: #060101; opacity: 0.95; }
  .core-particle { mix-blend-mode: screen; }
  .core-outer-ring {
    fill: none; stroke: var(--accent-primary); stroke-width: 3.5; opacity: 0.85;
    filter: drop-shadow(0 0 8px var(--accent-primary));
  }
  .part-charcoal { fill: #2a1f1f; }
  .part-crimson  { fill: var(--accent-tertiary); }
  .part-amber    { fill: var(--accent-secondary); }
  .core-sector-scanner {
    fill: none;
    stroke: #ffffff;
    stroke-width: 5.0;
    stroke-linecap: butt;
    transform-origin: 300px 300px;
    filter: drop-shadow(0 0 5px var(--accent-primary));
  }

  .spin-a { transform-origin: 300px 300px; animation: spin-anim 34s linear infinite; }
  .spin-b { transform-origin: 300px 300px; animation: spin-rev-anim 46s linear infinite; }
  .spin-c { transform-origin: 300px 300px; animation: spin-anim 26s linear infinite; }

  .hud-tag {
    position: absolute;
    font-size: 10px;
    letter-spacing: 1.5px;
    color: #8a939e;
    border-bottom: 1px solid rgba(210,215,223,0.4);
    padding: 6px 10px;
    background: #0d0606;
    text-transform: uppercase;
    opacity: 0.9;
    z-index: 50;
    border-radius: 2px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.5);
    transition: opacity 0.5s ease, transform 0.5s ease;
  }
  body.has-display .hud-tag { opacity: 0.5; transform: scale(0.8); }
  .hud-tag.red { color: var(--footer-accent); border-bottom-color: var(--accent-primary); }
  .hud-tag.tl { top: 30px; left: 30px; }
  .hud-tag.br { bottom: 30px; right: 30px; text-align: right; }

  .skill-panel {
    flex: 1;
    max-width: 0;
    opacity: 0;
    overflow: hidden;
    transition: max-width 0.6s cubic-bezier(0.25, 0.8, 0.3, 1),
                opacity 0.5s ease 0.1s,
                transform 0.6s cubic-bezier(0.25, 0.8, 0.3, 1);
    transform: translateX(40px);
  }
  body.has-display .skill-panel {
    max-width: 520px;
    opacity: 1;
    transform: translateX(0);
  }
  body.has-display.display-wide .skill-panel {
    max-width: 900px;
  }

  .skill-panel-inner {
    padding: 12px 8px;
    background: radial-gradient(ellipse at 50% 0%, rgba(255,60,40,0.05), transparent 70%);
    box-shadow: 0 0 60px rgba(255,26,26,0.06);
    max-height: 600px;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--border-color) transparent;
  }
  .skill-panel-inner::-webkit-scrollbar { width: 6px; }
  .skill-panel-inner::-webkit-scrollbar-track { background: transparent; }
  .skill-panel-inner::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 3px; }

  .skill-panel-title {
    font-size: 14px;
    letter-spacing: 2px;
    color: var(--footer-accent);
    text-transform: uppercase;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,26,26,0.2);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .skill-panel-title::before {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--accent-primary);
    box-shadow: 0 0 6px var(--accent-primary);
    animation: pulse-dot 2s ease-in-out infinite;
  }
  @keyframes pulse-dot {
    0%, 100% { opacity: 0.5; }
    50% { opacity: 1; }
  }

  .panel-reply {
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid rgba(51,20,20,0.6);
    font-size: 12px;
    line-height: 1.5;
    color: #c9d2dc;
  }

  .week-cal { font-size: 11px; }
  .week-cal-header {
    display: grid;
    grid-template-columns: 40px repeat(7, 1fr);
    margin-bottom: 6px;
  }
  .week-cal-daylabel {
    text-align: center;
    padding: 2px 2px 6px;
    font-size: 10px;
    letter-spacing: 1px;
    color: #8e7c7c;
    text-transform: uppercase;
    border-bottom: 1px solid rgba(51,20,20,0.6);
  }
  .week-cal-daylabel .daynum {
    display: block;
    font-size: 16px;
    color: #eef2f8;
    font-weight: 600;
    margin-top: 3px;
  }
  .week-cal-daylabel.is-today { color: var(--footer-accent); }
  .week-cal-daylabel.is-today .daynum {
    color: var(--accent-primary);
    text-shadow: 0 0 8px rgba(255,26,26,0.5);
  }
  .week-cal-body {
    position: relative;
    display: grid;
    grid-template-columns: 40px repeat(7, 1fr);
  }
  .week-cal-hourcol { position: relative; }
  .week-cal-hourlabel {
    position: absolute;
    right: 6px;
    transform: translateY(-50%);
    font-size: 9px;
    color: #6e6262;
    white-space: nowrap;
  }
  .week-cal-daycol {
    position: relative;
    border-left: 1px solid rgba(51,20,20,0.45);
  }
  .week-cal-gridline {
    position: absolute;
    left: 0;
    right: 0;
    border-top: 1px solid rgba(51,20,20,0.3);
  }
  .cal-block {
    position: absolute;
    left: 2px;
    right: 2px;
    border-radius: 4px;
    padding: 3px 5px;
    font-size: 10px;
    line-height: 1.3;
    overflow: hidden;
    color: rgba(10,4,4,0.88);
    box-shadow: 0 1px 4px rgba(0,0,0,0.4);
  }
  .cal-block .cb-title { font-weight: 700; font-size: 10.5px; }
  .cal-block .cb-time { font-size: 9px; opacity: 0.8; }

  .cal-entry {
    display: flex;
    gap: 14px;
    padding: 10px 0;
    border-bottom: 1px solid rgba(51,20,20,0.5);
    align-items: flex-start;
  }
  .cal-entry:last-child { border-bottom: none; }
  .cal-time {
    flex-shrink: 0;
    width: 80px;
    font-size: 12px;
    color: #8e7c7c;
    text-align: right;
    padding-top: 2px;
  }
  .cal-time .cal-date { color: #b09a9a; font-weight: bold; }
  .cal-body { flex: 1; }
  .cal-title { font-size: 15px; color: #eef2f8; margin-bottom: 2px; }
  .cal-cat {
    display: inline-block;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 3px;
    background: rgba(255,26,26,0.15);
    color: var(--footer-accent);
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  .wx { font-size: 11px; }
  .wx-now {
    display: flex; align-items: baseline; gap: 10px;
    padding-bottom: 8px; margin-bottom: 8px;
    border-bottom: 1px solid rgba(51,20,20,0.6);
  }
  .wx-now .t { font-size: 30px; font-weight: 600; color: #eef2f8; line-height: 1; }
  .wx-now .c { font-size: 12px; color: #b09a9a; }
  .wx-now .p {
    margin-left: auto; font-size: 10px; letter-spacing: 1px;
    text-transform: uppercase; color: #8e7c7c;
  }
  .wx-verdict { font-size: 12.5px; color: #eef2f8; margin-bottom: 10px; line-height: 1.45; }
  .wx-cols { display: grid; grid-template-columns: repeat(8, 1fr); }
  .wx-col { text-align: center; padding: 2px 2px 4px; }
  .wx-col .hr {
    font-size: 10px; letter-spacing: 1px; color: #8e7c7c; text-transform: uppercase;
  }
  .wx-col .tp { display: block; font-size: 16px; color: #eef2f8; font-weight: 600; margin-top: 3px; }
  .wx-col .ic { font-size: 15px; line-height: 1.5; }
  .wx-col .pp { font-size: 10px; color: #8e7c7c; }
  .wx-col.is-now .hr { color: var(--footer-accent); }
  .wx-col.is-now .tp { color: var(--accent-primary); text-shadow: 0 0 8px rgba(255,26,26,0.5); }
  .wx-col.wet .pp { color: var(--footer-accent); }
  
  .wx-bar-slot { height: 30px; display: flex; align-items: flex-end;
                 padding: 0 26%; margin: 3px 0 1px; }
  .wx-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px;
            background: linear-gradient(180deg, var(--accent-secondary), rgba(255,68,0,0.22)); }
  .wx-col.is-now .wx-bar {
    background: linear-gradient(180deg, var(--accent-primary), rgba(255,26,26,0.25));
    box-shadow: 0 0 8px rgba(255,26,26,0.35);
  }

  .generic-content { font-size: 14px; color: #b09a9a; line-height: 1.6; white-space: pre-wrap; }
  .generic-content strong { color: #eef2f8; }

  .reply-content {
    font-size: 15px;
    color: #eef2f8;
    line-height: 1.7;
    white-space: pre-wrap;
    letter-spacing: 0.2px;
  }

  .skill-empty {
    text-align: center;
    color: #6e6262;
    font-size: 14px;
    padding: 40px 0;
  }

  .status-bar {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 44px;
    background: linear-gradient(180deg, var(--bg-status-start), var(--bg-status-end));
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 32px;
    padding: 0 24px;
    z-index: 100;
    box-shadow: 0 -4px 20px rgba(0,0,0,0.5);
    transition: opacity 0.3s ease;
  }
  
  .status-bar::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    background: linear-gradient(180deg, rgba(5,13,5,0.95), rgba(3,8,3,0.98));
    opacity: 0;
    transition: opacity 1.5s ease;
    pointer-events: none;
  }
  .status-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
  }
  .status-item .stat-label {
    font-size: 10px;
    letter-spacing: 1.5px;
    color: #6e6262;
    text-transform: uppercase;
  }

  .hud-input-row {
    position: fixed;
    bottom: 44px;
    left: 0;
    right: 0;
    height: 52px;
    background: linear-gradient(180deg, var(--bg-input-start), var(--bg-input-end));
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 24px;
    z-index: 100;
  }
  .hud-input-row::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    background: linear-gradient(180deg, rgba(7,18,7,0.95), rgba(4,10,4,0.98));
    opacity: 0;
    transition: opacity 1.5s ease;
    pointer-events: none;
  }
  .hud-input-box {
    flex: 1;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: #e8d8d8;
    font-family: inherit;
    font-size: 14px;
    padding: 10px 14px;
    outline: none;
  }
  .hud-input-box:focus {
    
    background: rgba(255,255,255,0.03);
  }
  .hud-input-box::placeholder {
    
    color: rgba(232, 216, 216, 0.28);
  }
  .hud-input-send {
    background: var(--send-btn-bg);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 10px 20px;
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
    cursor: pointer;
    transition: background 0.15s ease;
  }
  .hud-input-send:hover {
    background: var(--send-btn-hover);
  }
  .status-item .stat-value {
    font-size: 13px;
    font-weight: bold;
    color: #eef2f8;
    transition: color 0.3s ease;
  }
  .status-item .stat-value.online { color: var(--accent-secondary); }
  .status-item .stat-value.offline { color: #5a544a; }
  .status-item .stat-value.speaking-label { color: var(--warn-color); }   
  .status-item .stat-value.brain-friday { color: #4fc3d8; }   
  .status-item .stat-value.brain-edith  { color: #ff5fa8; }
  .status-divider {
    width: 1px;
    height: 20px;
    background: var(--divider-color);
  }
  .status-footer {
    font-size: 11px;
    color: #6e6262;
    font-style: italic;
  }
  .status-footer b { color: var(--footer-accent); font-style: normal; }
  .warn { color: var(--warn-color); font-weight: bold; }

  .shutdown-msg {
    text-align: center;
    padding: 40px;
    font-size: 18px;
    color: #eef2f8;
  }

  @media (max-width: 700px) {
    body { padding: 8px 8px 110px 8px; overflow-y: auto; perspective: none; }
    .main-stage { flex-direction: column; gap: 12px !important; max-width: 100% !important; }
    .core-zone { width: 100%; }
    .skill-panel { max-width: 0; }
    body.has-display .skill-panel,
    body.has-display.display-wide .skill-panel { max-width: 100% !important; width: 100%; transform: none; }
    .skill-panel-inner { max-height: 55vh; }
    .hud-tag { display: none; }
    
    .status-bar { height: auto; min-height: 44px; gap: 6px 14px; padding: 6px 10px; flex-wrap: wrap; justify-content: center; }
    .status-item { font-size: 11px; }
    .status-footer { display: none; }
    .hud-input-row { bottom: 56px; }
    
    .main-stage { justify-content: center; min-height: calc(100vh - 140px); }
    body.has-display .main-stage { justify-content: flex-start; min-height: 0; }
    .hud-input-row { height: 60px; bottom: 44px; padding: 0 8px; gap: 6px; box-sizing: border-box; }
    
    .hud-input-box { font-size: 16px; min-width: 0; padding: 10px 8px; }
    .hud-input-send { padding: 10px 12px; flex: 0 0 auto; }
    .hud-input-row button, .hud-input-row label { flex: 0 0 auto; }
    html, body { max-width: 100vw; overflow-x: hidden; }
  }

</style>
</head>
<body>

<div class="main-stage">
  <div class="core-zone">
    <div class="reactor-wrap" id="reactor">
      <div class="floor-shadow"></div>
      <div class="glow"></div>

      <div class="hud-tag tl">NEURAL<br>LINK: SYNCED</div>
      <div class="hud-tag red br">PWR<br>CORE: NOMINAL</div>

      <svg class="globe" viewBox="0 0 600 600">
        <defs>
          <filter id="blur-dust" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3.5"/>
          </filter>
        </defs>

        <g>__TICK_RING__</g>

        <line class="leader" x1="65" y1="90" x2="160" y2="185"/>
        <line class="leader" x1="535" y1="510" x2="440" y2="415"/>

        __RINGS__

        <g class="spin-a">__WAVE_INNER__</g>
        <g class="spin-b">__WAVE_MID__</g>
        <g class="spin-c">__WAVE_OUTER__</g>

        <circle class="core-void" cx="300" cy="300" r="64"/>

        <g id="scattered-3d-fog-matrix">
          __CORE_FOG__
        </g>

        <circle class="core-outer-ring" cx="300" cy="300" r="64"/>
        <path class="core-sector-scanner" d="M 300 236 A 64 64 0 0 1 364 300"/>
      </svg>
    </div>
  </div>

  <div class="skill-panel" id="skillPanel">
    <div class="skill-panel-inner" id="skillPanelInner">
      
    </div>
  </div>
</div>

<div class="status-bar" id="statusBar">
  
</div>

<div class="hud-input-row" id="hudInputRow">
  <input type="text" id="hudInputBox" class="hud-input-box"
         placeholder="Type a message to Ultron..." autocomplete="off" />
  <button type="button" id="hudInputSend" class="hud-input-send">Send</button>
</div>

<div id="hudInputNote" style="display:none; max-width:640px; margin:6px auto 0;
     font-size:12px; color:#ffb4a2; text-align:center; opacity:0.9;"></div>

<script>
let isSpeaking = false;
let speakingIntensity = 0;
let globalTime = 0;
let currentDisplayType = null;
let shutdownHandled = false;

async function sendHudInput() {
  const box = document.getElementById('hudInputBox');
  const text = box.value.trim();
  if (!text) return;
  const submitId = (self.crypto && crypto.randomUUID)
    ? crypto.randomUUID()
    : (Date.now() + '-' + Math.random().toString(36).slice(2));
  box.value = '';
  try {
    let delivered = false;
    let lastErr = null;
    for (let attempt = 0; attempt < 3 && !delivered; attempt++) {
      const ctrl = new AbortController();
      const timeoutId = setTimeout(() => ctrl.abort(), 8000);
      try {
        const resp = await fetch('/api/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: text, submit_id: submitId }),
          signal: ctrl.signal,
        });
        clearTimeout(timeoutId);
        if (!resp.ok) throw new Error('submit returned ' + resp.status);
        delivered = true;
      } catch (e) {
        clearTimeout(timeoutId);
        lastErr = e;
        await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
      }
    }
    if (!delivered) throw (lastErr || new Error('submit failed'));
  } catch (e) {
    if (!box.value) box.value = text;
    const why = (e && e.name === 'AbortError')
      ? 'Ultron did not respond after three tries'
      : 'that message did not reach Ultron';
    const note = document.getElementById('hudInputNote');
    if (note) {
      note.textContent = '⚠ ' + why + ' — your text is back in the box, press Enter to retry.';
      note.style.display = 'block';
      setTimeout(() => { note.style.display = 'none'; }, 8000);
    }
  } finally {
    box.focus();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const box = document.getElementById('hudInputBox');
  box.value = '';
  document.getElementById('hudInputSend').addEventListener('click', sendHudInput);
  box.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendHudInput();
  });
});

const fogNodes = [];
const totalNodes = 140;

for (let i = 0; i < totalNodes; i++) {
  let radius = Math.random() * 16;
  if (i > 35) radius = 14 + Math.random() * 16;
  if (i > 80) radius = 28 + Math.random() * 16;

  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos((Math.random() * 2) - 1);

  let cls = "part-charcoal";
  const roll = Math.random();
  if (roll > 0.35) cls = "part-crimson";
  if (roll > 0.82) cls = "part-amber";

  fogNodes.push({
    x: radius * Math.sin(phi) * Math.cos(theta),
    y: radius * Math.sin(phi) * Math.sin(theta),
    z: radius * Math.cos(phi),
    colorClass: cls,
    baseRadius: radius
  });
}

function animateFluidBarsAndCore() {
  globalTime += 0.08;
  const cx = 300, cy = 300;

  const targetIntensity = isSpeaking ? 1 : 0;
  const easeRate = targetIntensity > speakingIntensity ? 0.14 : 0.07;
  speakingIntensity += (targetIntensity - speakingIntensity) * easeRate;

  const bars = document.querySelectorAll('.eq-bar');
  bars.forEach(bar => {
    const r0 = parseFloat(bar.dataset.r0);
    const angleDeg = parseFloat(bar.dataset.angle);
    const rad = angleDeg * Math.PI / 180;

    let maxLen = 42;
    let freqModifier = 1.6;
    if (r0 > 140) { maxLen = 64; freqModifier = 1.2; }
    if (r0 > 210) { maxLen = 96; freqModifier = 0.8; }

    let waveMod = Math.sin(angleDeg * 0.12 + globalTime * freqModifier) * Math.cos(angleDeg * 0.06 - globalTime * (freqModifier * 0.5));
    waveMod += Math.sin(angleDeg * 0.35 + globalTime * 2.2) * 0.25;

    const baseAmplitude = maxLen * (0.25 + 0.75 * speakingIntensity);
    const targetLength = Math.max(1.0, (0.5 + 0.5 * waveMod) * baseAmplitude);

    const finalRadius = r0 + targetLength;
    const x2 = cx + finalRadius * Math.cos(rad);
    const y2 = cy + finalRadius * Math.sin(rad);

    bar.setAttribute('x2', x2.toFixed(1));
    bar.setAttribute('y2', y2.toFixed(1));
  });

  const speed = 0.65 + (2.2 - 0.65) * speakingIntensity;
  const angleY = 0.012 * speed;
  const angleX = 0.006 * speed;

  const cosY = Math.cos(angleY), sinY = Math.sin(angleY);
  const cosX = Math.cos(angleX), sinX = Math.sin(angleX);

  fogNodes.forEach((p, idx) => {
    let x1 = p.x * cosY - p.z * sinY;
    let z1 = p.z * cosY + p.x * sinY;
    let y2 = p.y * cosX - z1 * sinX;
    let z2 = z1 * cosX + p.y * sinX;
    p.x = x1;
    p.y = y2;
    p.z = z2;

    const screenX = cx + p.x;
    const screenY = cy + p.y;
    const normalizedZ = (p.z + 44) / 88;
    const opacity = Math.min(0.85, Math.max(0.06, 0.15 + normalizedZ * 0.65));
    const breatheSize = 4.8 + Math.sin(globalTime * 2.0 + idx) * (0.8 + (2.5 - 0.8) * speakingIntensity);

    const blobNode = document.getElementById('cp-' + idx);
    if (blobNode) {
      blobNode.setAttribute('cx', screenX.toFixed(1));
      blobNode.setAttribute('cy', screenY.toFixed(1));
      blobNode.setAttribute('r', breatheSize.toFixed(1));
      blobNode.setAttribute('class', 'core-particle ' + p.colorClass);
      blobNode.style.opacity = opacity.toFixed(2);
    }
  });

  const scannerPath = document.querySelector('.core-sector-scanner');
  if (scannerPath) {
    let scanSpin = -globalTime * 5.2 * (1.0 + (2.0 - 1.0) * speakingIntensity);
    scannerPath.style.transform = 'rotate(' + scanSpin + 'deg)';
    scannerPath.style.transformOrigin = '300px 300px';
  }

  requestAnimationFrame(animateFluidBarsAndCore);
}
requestAnimationFrame(animateFluidBarsAndCore);

function renderSkillPanel(display) {
  const inner = document.getElementById('skillPanelInner');

  if (!display || !display.type) {
    document.body.classList.remove('has-display', 'display-dense', 'display-wide');
    currentDisplayType = null;
    inner.innerHTML = '';
    return;
  }

  const dtype = display.type;
  const title = display.title || dtype.toUpperCase();
  const content = display.content || {};

  const denseTypes = [];
  const wideTypes = ['calendar'];
  document.body.classList.toggle('display-dense', denseTypes.includes(dtype));
  document.body.classList.toggle('display-wide', wideTypes.includes(dtype));
  document.body.classList.add('has-display');
  currentDisplayType = dtype;

  let html = dtype === 'reply' ? '' : '<div class="skill-panel-title">' + escHtml(title) + '</div>';

  switch (dtype) {
    case 'calendar':
      html += renderCalendar(content);
      break;
    case 'reminders':
      html += renderReminders(content);
      break;
    case 'weather':
      html += renderWeather(content);
      break;
    case 'reply':
      html += renderReply(content);
      break;
    default:
      html += renderGeneric(content);
  }

  if (dtype !== 'reply' && content.reply_text) {
    html += '<div class="panel-reply">' + escHtml(content.reply_text).replace(/\n/g, '<br>') + '</div>';
  }

  inner.innerHTML = html;
}

function renderCalendar(content) {
  const events = content.events || content.items || [];
  const weekStartStr = content.week_start || null;

  let weekStart;
  if (weekStartStr) {
    weekStart = new Date(weekStartStr);
  } else {
    const now = new Date();
    const ds = (now.getDay() + 0) % 7;
    weekStart = new Date(now);
    weekStart.setDate(now.getDate() - ds);
    weekStart.setHours(0, 0, 0, 0);
  }

  function hoursFromMidnightOf(when, refDay) {
    const midnight = new Date(refDay);
    midnight.setHours(0, 0, 0, 0);
    return (when.getTime() - midnight.getTime()) / 3600000;
  }
  const HOUR_START = 0, HOUR_END = 24, HOURS = 24;
  const HOUR_PX = 38;
  const bodyHeight = HOURS * HOUR_PX;

  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  let header = '<div class="week-cal-header"><div></div>';
  for (let d = 0; d < 7; d++) {
    const dayDate = new Date(weekStart);
    dayDate.setDate(weekStart.getDate() + d);
    const isToday = dayDate.getTime() === today.getTime();
    header += '<div class="week-cal-daylabel' + (isToday ? ' is-today' : '') + '">'
            + dayNames[d]
            + '<span class="daynum">' + dayDate.getDate() + '</span></div>';
  }
  header += '</div>';

  let body = '<div class="week-cal-body" style="height:' + bodyHeight + 'px">';

  body += '<div class="week-cal-hourcol">';
  for (let h = HOUR_START; h < HOUR_END; h++) {
    const top = (h - HOUR_START) * HOUR_PX;
    const label = ((h + 11) % 12 + 1) + (h >= 12 ? 'p' : 'a');
    body += '<div class="week-cal-hourlabel" style="top:' + top + 'px">' + label + '</div>';
  }
  body += '</div>';

  const dayBuckets = [[], [], [], [], [], [], []];
  events.forEach(ev => {
    const iso = ev.start_iso || '';
    if (!iso) return;
    const isoDate = iso.slice(0, 10);
    let dayIdx = -1;
    for (let d = 0; d < 7; d++) {
      const dayDate = new Date(weekStart);
      dayDate.setDate(weekStart.getDate() + d);
      const yy = dayDate.getFullYear();
      const mm = String(dayDate.getMonth() + 1).padStart(2, '0');
      const dd = String(dayDate.getDate()).padStart(2, '0');
      if (isoDate === yy + '-' + mm + '-' + dd) { dayIdx = d; break; }
    }
    if (dayIdx < 0 || dayIdx > 6) return;
    dayBuckets[dayIdx].push(ev);
  });

  const blockColors = [
    'rgba(255,26,26,0.55)',
    'rgba(210,218,226,0.45)',
    'rgba(255,180,50,0.50)',
    'rgba(80,200,120,0.45)',
    'rgba(150,120,255,0.45)',
  ];

  for (let d = 0; d < 7; d++) {
    body += '<div class="week-cal-daycol" style="height:' + bodyHeight + 'px">';
    for (let h = 0; h <= HOURS; h++) {
      body += '<div class="week-cal-gridline" style="top:' + (h * HOUR_PX) + 'px"></div>';
    }
    dayBuckets[d].forEach((ev, i) => {
      const iso = ev.start_iso || '';
      const endIso = ev.end_iso || iso;
      const evStart = new Date(iso.replace('T', ' ').replace('Z', ''));
      const evEnd = new Date(endIso.replace('T', ' ').replace('Z', ''));
      if (isNaN(evStart.getTime())) return;

      const startHours = evStart.getHours() + evStart.getMinutes() / 60;
      const endHours = isNaN(evEnd.getTime())
        ? startHours + 1
        : Math.min(24, hoursFromMidnightOf(evEnd, evStart));
      const clampedStart = Math.max(startHours, HOUR_START);
      const clampedEnd = Math.min(endHours, HOUR_END);
      if (clampedEnd <= clampedStart) return;

      const top = Math.round((clampedStart - HOUR_START) * HOUR_PX);
      const height = Math.max(18, Math.round((clampedEnd - clampedStart) * HOUR_PX) - 2);
      const isClass = (ev.category === 'class');
      const color = isClass ? 'rgba(43,111,212,0.55)' : blockColors[i % blockColors.length];
      const title = escHtml(ev.title || ev.name || 'Untitled');
      const timeLabel = ev.time_str || '';

      body += '<div class="cal-block" style="top:' + top + 'px;height:' + height + 'px;background:' + color + '">';
      body += '<div class="cb-title">' + title + '</div>';
      if (height > 28 && timeLabel) body += '<div class="cb-time">' + escHtml(timeLabel) + '</div>';
      body += '</div>';
    });
    body += '</div>';
  }
  body += '</div>';

  const emptyNote = events.length ? ''
    : '<div class="skill-empty" style="margin-top:12px">No events this week.</div>';
  return '<div class="week-cal">' + header + body + emptyNote + '</div>';
}

function renderReminders(content) {
  const reminders = content.reminders || content.items || [];
  if (!reminders.length) return '<div class="skill-empty">No reminders set.</div>';
  let html = '';
  reminders.forEach(r => {
    const when = r.fire_at || r.when || '';
    const task = r.task || r.title || 'Untitled';
    html += '<div class="cal-entry">';
    html += '<div class="cal-time"><div class="cal-date">' + escHtml(when) + '</div></div>';
    html += '<div class="cal-title">' + escHtml(task) + '</div>';
    html += '</div>';
  });
  return html;
}

function renderWeather(content) {
  const hours = content.hours || [];
  const unit = content.unit || '';
  const cur = content.current || {};

  let html = '<div class="wx">';
  html += '<div class="wx-now">';
  html += '<span class="t">' + (cur.temp == null ? '--' : Math.round(cur.temp)) + unit + '</span>';
  html += '<span class="c">' + escHtml(cur.condition || '') + '</span>';
  if (content.place) html += '<span class="p">' + escHtml(content.place) + '</span>';
  html += '</div>';
  if (content.verdict) html += '<div class="wx-verdict">' + escHtml(content.verdict) + '</div>';
  if (!hours.length) return html + '</div>';

  const temps = hours.map(h => h.temp).filter(t => t != null);
  const mx = temps.length ? Math.max(...temps) : 0;
  const mn = temps.length ? Math.min(...temps) : 0;
  const rng = (mx - mn) || 1;

  html += '<div class="wx-cols">';
  hours.forEach(h => {
    const pct = h.temp == null ? 22 : 22 + ((h.temp - mn) / rng) * 78;
    const p = h.prob == null ? null : Math.round(h.prob);
    const tip = h.label + ' — ' + (h.temp == null ? '--' : Math.round(h.temp)) + unit
      + ', ' + (h.condition || '') + (p == null ? '' : ', rain ' + p + '%')
      + (h.wind == null ? '' : ', wind ' + Math.round(h.wind) + ' ' + (content.wind_label || ''));

    html += '<div class="wx-col' + (h.mark ? ' is-now' : '') + (p >= 50 ? ' wet' : '') + '"'
         +  ' title="' + escHtml(tip) + '">';
    html += '<span class="hr">' + escHtml(h.label || '') + '</span>';
    html += '<span class="tp">' + (h.temp == null ? '--' : Math.round(h.temp)) + '</span>';
    html += '<div class="wx-bar-slot"><div class="wx-bar" style="height:' + pct.toFixed(0) + '%"></div></div>';
    html += '<div class="ic">' + escHtml(h.icon || '') + '</div>';
    html += '<div class="pp">' + (p == null ? '--' : p + '%') + '</div>';
    html += '</div>';
  });
  html += '</div></div>';
  return html;
}

function renderGeneric(content) {
  if (content.html) return content.html;
  const lines = content.lines || content.text || [];
  if (typeof lines === 'string') return '<div class="generic-content">' + escHtml(lines) + '</div>';
  if (Array.isArray(lines)) {
    return '<div class="generic-content">' + lines.map(l => escHtml(typeof l === 'string' ? l : (l.text || JSON.stringify(l)))).join('<br>') + '</div>';
  }
  return '<div class="generic-content">' + escHtml(JSON.stringify(content, null, 2)) + '</div>';
}

function renderReply(content) {
  const text = content.text || '';
  const escaped = escHtml(text).replace(/\n/g, '<br>');
  return '<div class="reply-content">' + escaped + '</div>';
}

function escHtml(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function brainColorClass(brainName) {
  var name = (brainName || '').toUpperCase();
  if (name === 'FRIDAY') return 'brain-friday';
  if (name === 'EDITH') return 'brain-edith';
  return '';
}

let pollInFlight = false;
let pollFailures = 0;
let pollSkipTicks = 0;

async function refresh() {
  if (pollInFlight) return;
  if (pollSkipTicks > 0) { pollSkipTicks--; return; }
  pollInFlight = true;
  try {
    const ctrl = new AbortController();
    const timeoutId = setTimeout(() => ctrl.abort(), 6000);
    const res = await fetch('/api/status', { signal: ctrl.signal });
    clearTimeout(timeoutId);
    const s = await res.json();
    pollFailures = 0;
    const statusBar = document.getElementById('statusBar');

    if (!s.configured) {
      statusBar.innerHTML = '<div class="warn">' + escHtml(s.message) + '</div>';
      return;
    }

    if (s.shutdown && !shutdownHandled) {
      shutdownHandled = true;
      clearInterval(pollTimer);
      document.body.classList.remove('has-display', 'display-dense', 'display-wide');
      document.getElementById('skillPanelInner').innerHTML = '';
      statusBar.innerHTML = '<div class="shutdown-msg">' + escHtml(s.shutdown_message || 'Powering down.') + ' - closing...</div>';
      if (s.app_mode) {
        try { window.close(); } catch (e) {  }
      }
      setTimeout(() => {
        statusBar.innerHTML = '<div class="shutdown-msg">' + escHtml(s.shutdown_message || 'Powering down.') + ' - you can close this tab now.</div>';
      }, 900);
      return;
    }

    isSpeaking = !!s.speaking;
    document.body.classList.toggle('speaking', isSpeaking);

    if (s.display && s.display.type) {
      renderSkillPanel(s.display);
    } else if (currentDisplayType) {
      renderSkillPanel(null);
    }

    const modeClass = s.mode === 'ONLINE' ? 'online' : 'offline';
    const inputModeClass = s.input_mode === 'VOICE' ? 'online' : 'offline';
    const speakingItem = s.speaking
      ? '<div class="status-item"><span class="stat-label">Status</span><span class="stat-value speaking-label">SPEAKING</span></div>'
      : '<div class="status-item"><span class="stat-label">Status</span><span class="stat-value">IDLE</span></div>';

    statusBar.innerHTML =
      '<div class="status-item"><span class="stat-label">Brain</span><span class="stat-value ' + brainColorClass(s.active_brain) + '">' + escHtml(s.active_brain) + '</span></div>' +
      '<div class="status-divider"></div>' +
      '<div class="status-item"><span class="stat-label">Mode</span><span class="stat-value ' + modeClass + '">' + escHtml(s.mode) + '</span></div>' +
      '<div class="status-divider"></div>' +
      '<div class="status-item"><span class="stat-label">Input</span><span class="stat-value ' + inputModeClass + '">' + escHtml(s.input_mode || 'UNKNOWN') + '</span></div>' +
      '<div class="status-divider"></div>' +
      '<div class="status-item"><span class="stat-label">Response</span><span class="stat-value">' + escHtml(s.response_latency) + '</span></div>' +
      '<div class="status-divider"></div>' +
      '<div class="status-item"><span class="stat-label">Net</span><span class="stat-value">' + escHtml(s.latency) + '</span></div>' +
      '<div class="status-divider"></div>' +
      speakingItem +
      '<div class="status-divider"></div>' +
      '<div class="status-footer">monitoring for <b>"' + escHtml(s.wake_online) + '"</b></div>';
  } catch (e) {
    pollFailures++;
    pollSkipTicks = Math.min(40, pollFailures * 4);
    const waiting = pollFailures < 8;
    document.getElementById('statusBar').innerHTML =
      '<div class="warn">' +
      (waiting ? 'Waiting for Ultron - still working...'
               : 'HUD lost contact with Ultron - retrying...') +
      '</div>';
  } finally {
    pollInFlight = false;
  }
}
refresh();
const pollTimer = setInterval(refresh, 150);
</script>
</body>
</html>
"""

PAGE = (
    PAGE_TEMPLATE
    .replace("__TICK_RING__", TICK_RING_SVG)
    .replace("__RINGS__", RINGS_SVG)
    .replace("__RING_CSS__", RING_CSS)
    .replace("__WAVE_INNER__", WAVE_INNER_SVG)
    .replace("__WAVE_MID__", WAVE_MID_SVG)
    .replace("__WAVE_OUTER__", WAVE_OUTER_SVG)
    .replace("__CORE_FOG__", CORE_FOG_SVG)
)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _force_close_browser_if_needed() -> None:
    """If the page couldn't close its own window, end the HUD's browser process (only ever the HUD's own)."""
    _kill_hud_browser_by_profile()
    if _browser_proc is not None and _browser_proc.poll() is None:
        try:
            _browser_proc.terminate()
        except OSError:
            pass


def _schedule_shutdown_kill() -> None:
    """Close the window once Ultron says it's powering down: the native window is closed directly; the browser
    fallback's window is ended by process."""
    global _shutdown_kill_scheduled
    if _shutdown_kill_scheduled:
        return
    _shutdown_kill_scheduled = True
    if _native["window"] is not None:
        Timer(1.2, _native["window"].destroy).start()
    else:
        Timer(1.8, _force_close_browser_if_needed).start()


_last_poll = {"t": 0.0}


def _watch_for_closed_window() -> None:
    """The page polls /api/status several times a second. If it has polled and then goes quiet for 15 s, the
    window was closed — so Ultron is told to power down through the normal input queue, instead of carrying on
    invisibly with the model still holding the GPU."""
    while True:
        time.sleep(2)
        if _last_poll["t"] and time.time() - _last_poll["t"] > 15:
            _append_hud_input("power down")
            return


def get_status() -> dict:
    _last_poll["t"] = time.time()
    state = _read_json(HUD_STATE_PATH) or {}
    shutdown = _read_json(HUD_SHUTDOWN_PATH) or {}
    if shutdown.get("shutdown"):
        _schedule_shutdown_kill()
    latency = state.get("response_latency_ms")
    return {
        "configured": True,
        "active_brain": str(state.get("active_brain") or "STANDBY").upper(),
        "mode": str(state.get("mode") or "STARTING").upper(),
        "input_mode": str(state.get("input_mode") or "TYPED").upper(),
        "latency": "local",
        "response_latency": f"{latency}ms" if latency is not None else "--",
        "wake_online": "type below",
        "speaking": bool(state.get("thinking")),
        "shutdown": bool(shutdown.get("shutdown")),
        "shutdown_message": shutdown.get("message", ""),
        "app_mode": _app_mode_launch,
        "display": hud_display.get_display(),
    }


def _append_hud_input(text: str) -> None:
    """One uniquely named file per message, written to a temp name and renamed into place: the rename is
    atomic, so ultron.py never reads a half-written file."""
    try:
        HUD_INPUT_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{time.time_ns()}_{uuid.uuid4().hex}.json"
        tmp = HUD_INPUT_QUEUE_DIR / f"{name}.tmp"
        tmp.write_text(json.dumps({"text": text, "ts": time.time()}), encoding="utf-8")
        os.replace(tmp, HUD_INPUT_QUEUE_DIR / name)
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(200, json.dumps(get_status()).encode("utf-8"), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self.path.startswith("/api/submit"):
            self._send(404, b"{}", "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) if length else b"{}")
            text = (payload.get("text") or "").strip()
            submit_id = (payload.get("submit_id") or "").strip()
            duplicate = bool(submit_id) and submit_id in _RECENT_SUBMIT_IDS
            if submit_id and not duplicate:
                _RECENT_SUBMIT_IDS.append(submit_id)
            if text and not duplicate:
                _append_hud_input(text)
            self._send(200, b'{"ok": true}', "application/json")
        except Exception:
            self._send(200, b'{"ok": false}', "application/json")

    def log_message(self, *args):
        pass


def _dont_focus_on_show() -> None:
    """A --minimized start must leave the user's focus where it was. Measured: pywebview (6.2.1, WinForms) activates
    its first window as it shows it, even minimized with focus=False, and then focuses the page as well. It offers no
    way to show a window without activating it, so the window hands the foreground straight back to whatever was
    active before the HUD started, and skips focusing the page. Best effort: if pywebview changes shape, the window
    still opens; it just may keep the focus."""
    try:
        import ctypes
        from webview.platforms import winforms
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        previous = user32.GetForegroundWindow()
        form = winforms.BrowserView.BrowserForm

        def on_shown(self, *_):
            self.shown.set()
            if self.pywebview_window.focus:
                self.browser.webview.Focus()
            elif previous and user32.GetForegroundWindow() == self.Handle.ToInt64():
                user32.SetForegroundWindow(ctypes.c_void_p(previous))
        form.on_shown = on_shown
    except Exception as e:  # noqa: BLE001
        print(f"HUD: couldn't keep the window from taking focus ({type(e).__name__})")


def run(minimized: bool = False) -> None:
    """Serve the page locally, then show it in a NATIVE window (pywebview, drawn by Windows' WebView2) owned by
    this process — its own title, the app's icon, and closing it is a direct event. Without pywebview, the page
    opens in a Chrome/Edge app window instead and a watchdog notices when it's closed."""
    import threading
    for stale in (HUD_SHUTDOWN_PATH, hud_display.DISPLAY_PATH):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass
    Handler.protocol_version = "HTTP/1.1"
    _QuietThreadingHTTPServer.allow_reuse_address = True
    _QuietThreadingHTTPServer.daemon_threads = True
    try:
        server = _QuietThreadingHTTPServer(("localhost", PORT), Handler)
    except OSError as e:
        print(f"HUD: couldn't bind to port {PORT} ({e}) — is another HUD already running?")
        sys.exit(0)
    url = f"http://localhost:{PORT}"
    print(f"HUD at {url}")
    try:
        import webview
    except ImportError:
        webview = None
    if webview is None:
        print("HUD: pywebview isn't installed — using a browser window instead")
        Timer(0.6, _open_hud_window, args=[url]).start()
        threading.Thread(target=_watch_for_closed_window, daemon=True).start()
        server.serve_forever()
        return
    global _app_mode_launch
    _app_mode_launch = True
    if minimized:
        _dont_focus_on_show()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _native["window"] = webview.create_window("Ultron", url, width=1400, height=820, min_size=(900, 600),
                                              background_color="#050000", minimized=minimized, focus=not minimized)
    webview.start()                     # blocks until the window closes, however it closes
    if not (_read_json(HUD_SHUTDOWN_PATH) or {}).get("shutdown"):
        _append_hud_input("power down")  # the user closed the window: Ultron follows, nothing keeps the GPU


if __name__ == "__main__":
    run(minimized="--minimized" in sys.argv)
