"""The panel the HUD shows, written by ultron.py and read by hud.py through hud_display.json.

A display is {"type": "reply" | "calendar" | "reminders" | "weather" | <anything else>, "title", "content",
"timestamp", "ttl"}. The HUD renders each type with its own panel; an unknown type falls back to plain text.
A display older than its ttl (seconds) counts as cleared. Every write is best effort and never raises.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from paths import APP_DIR

DISPLAY_PATH = APP_DIR / "hud_display.json"
DEFAULT_TTL = 300


def push_display(display_type: str, title: str, content: dict[str, Any], ttl: float = DEFAULT_TTL) -> None:
    data = {"type": display_type, "title": title, "content": content, "timestamp": time.time(), "ttl": ttl}
    try:
        tmp = DISPLAY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
        os.replace(tmp, DISPLAY_PATH)
    except OSError:
        pass


def clear_display() -> None:
    push_display(None, "", {}, 0)


def get_display() -> dict | None:
    try:
        data = json.loads(DISPLAY_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if data.get("ttl", 0) > 0 and time.time() - data.get("timestamp", 0) > data["ttl"]:
        return None
    return data


def test_a_display_round_trips_and_expires(tmp_path=None):
    import tempfile
    global DISPLAY_PATH
    saved = DISPLAY_PATH
    DISPLAY_PATH = Path(tempfile.mkdtemp()) / "hud_display.json"
    try:
        push_display("reply", "", {"text": "hi"}, ttl=60)
        assert get_display()["content"]["text"] == "hi"
        push_display("reply", "", {"text": "old"}, ttl=0.001)
        time.sleep(0.01)
        assert get_display() is None
    finally:
        DISPLAY_PATH = saved
