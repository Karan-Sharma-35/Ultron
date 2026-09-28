"""The skills EDITH's calls run: a session calendar and reminders (in memory), an arithmetic calculator, and a
weather call shown rather than made. Each returns the reply text and, when there is one, the HUD panel to raise.
"""
from __future__ import annotations

import ast
import datetime as dt
import operator

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def calculate(expression: str) -> str:
    """Arithmetic only, by walking the syntax tree — never eval()."""
    def walk(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](walk(n.left), walk(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](walk(n.operand))
        raise ValueError("not plain arithmetic")
    try:
        value = walk(ast.parse(expression, mode="eval").body)
        return f"{expression} = {round(value, 6):g}"
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return f"I couldn't work out {expression!r} ({type(e).__name__})."


def day_to_date(day: str | None, today: dt.date | None = None) -> dt.date:
    """'today' / 'tomorrow' / a weekday (the next one, today included) -> a date."""
    today = today or dt.date.today()
    day = (day or "today").strip().lower().split()[0]
    if day == "tomorrow":
        return today + dt.timedelta(days=1)
    if day in _WEEKDAYS:
        return today + dt.timedelta(days=(_WEEKDAYS.index(day) - today.weekday()) % 7)
    return today


def _start_iso(f: dict, today: dt.date | None = None) -> str:
    time = f.get("time") or "09:00"
    return f"{day_to_date(f.get('day'), today).isoformat()}T{time}"


def _end_iso(start_iso: str) -> str:
    return (dt.datetime.fromisoformat(start_iso) + dt.timedelta(hours=1)).isoformat(timespec="minutes")


class Skills:
    def __init__(self):
        self.events: list[dict] = []
        self.reminders: list[dict] = []
        self.recent = ""   # the last action, handed back to EDITH as "[recent: ...]"

    def _calendar_panel(self, focus_iso: str | None = None):
        """The week (Sunday first, like the HUD) holding the event just changed — "friday" asked on a
        Saturday is next week's Friday, and a panel on this week would not show it."""
        day = dt.date.fromisoformat(focus_iso[:10]) if focus_iso else dt.date.today()
        sunday = day - dt.timedelta(days=(day.weekday() + 1) % 7)
        return ("calendar", f"WEEK OF {sunday.strftime('%d %b').upper()}",
                {"events": self.events, "week_start": f"{sunday.isoformat()}T00:00:00"})

    def run(self, skill: str | None, f: dict) -> tuple[str, tuple | None]:
        # "[recent: ...]" is context for the NEXT turn only. Measured: left in place, it made a later, unrelated
        # "I've got something going on thursday" move the old event instead of asking what the event is.
        # Only the calendar skills below set it again.
        self.recent = ""
        if skill == "calculator":
            return calculate(f.get("expression", "")), None
        if skill == "calendar_add":
            start = _start_iso(f)
            self.events.append({"title": f.get("title") or "Untitled", "start_iso": start, "end_iso": _end_iso(start),
                                "time_str": f.get("time", ""), "day": f.get("day", "")})
            self.recent = f"[recent: added '{f.get('title')}' event {f.get('day')} at {f.get('time')}]"
            return f"Added '{f.get('title')}' on {f.get('day')} at {f.get('time')}.", self._calendar_panel(start)
        if skill == "calendar_delete":
            before = len(self.events)
            self.events = [e for e in self.events if e["title"] != f.get("title")]
            if len(self.events) == before:
                return f"There's no event called '{f.get('title')}'.", None
            self.recent = ""
            return f"Removed '{f.get('title')}'.", self._calendar_panel()
        if skill == "calendar_update":
            for e in self.events:
                if e["title"] == f.get("title"):
                    e["start_iso"] = e["start_iso"][:11] + (f.get("new_time") or e["start_iso"][11:])
                    e["end_iso"] = _end_iso(e["start_iso"])
                    e["time_str"] = f.get("new_time", e["time_str"])
                    self.recent = f"[recent: added '{e['title']}' event {e['day']} at {e['time_str']}]"
                    return f"Moved '{e['title']}' to {e['time_str']}.", self._calendar_panel(e["start_iso"])
            return f"There's no event called '{f.get('title')}'.", None
        if skill == "reminder":
            self.reminders.append({"task": f.get("task") or "something", "when": f"{f.get('day', '')} {f.get('time', '')}".strip()})
            return (f"I'll remind you to {f.get('task')} {f.get('day')} at {f.get('time')}.",
                    ("reminders", "REMINDERS", {"reminders": self.reminders}))
        if skill == "weather":
            where = f.get("location", "unspecified")
            where = "your area" if where == "unspecified" else where
            return (f"Weather for {where}, {f.get('day', 'today')} — here's the call EDITH made; "
                    f"weather isn't connected to a service."), None
        if skill == "clarify":
            return f.get("question", "Could you say that more specifically?"), None
        return f"EDITH chose '{skill}', which isn't handled.", None


def test_calculator_is_arithmetic_only():
    assert calculate("12*3") == "12*3 = 36"
    assert calculate("7/2") == "7/2 = 3.5"
    assert "couldn't" in calculate("__import__('os')")
    assert "couldn't" in calculate("1/0")


def test_days_become_dates():
    wed = dt.date(2026, 9, 23)                      # a Wednesday
    assert day_to_date("today", wed) == wed
    assert day_to_date("tomorrow", wed) == dt.date(2026, 9, 24)
    assert day_to_date("friday", wed) == dt.date(2026, 9, 25)
    assert day_to_date("wednesday", wed) == wed
    assert day_to_date("monday morning", wed) == dt.date(2026, 9, 28)


def test_a_session_calendar_adds_moves_and_removes():
    s = Skills()
    reply, panel = s.run("calendar_add", {"title": "call the bank", "day": "monday", "time": "10:00"})
    assert panel[0] == "calendar" and s.events[0]["start_iso"].endswith("T10:00")
    week = dt.date.fromisoformat(panel[2]["week_start"][:10])
    assert week.weekday() == 6 and week <= dt.date.fromisoformat(s.events[0]["start_iso"][:10]) < week + dt.timedelta(days=7)
    assert "call the bank" in s.recent
    s.run("calculator", {"expression": "1+1"})
    assert s.recent == "", "context must not outlive the next turn"
    s.recent = "[recent: added 'call the bank' event monday at 10:00]"
    reply, _ = s.run("calendar_update", {"title": "call the bank", "new_time": "11:00"})
    assert reply.startswith("Moved") and s.events[0]["start_iso"].endswith("T11:00")
    assert s.events[0]["end_iso"].endswith("T12:00")
    assert s.run("calendar_delete", {"title": "call the bank"})[0].startswith("Removed")
    assert "no event" in s.run("calendar_delete", {"title": "call the bank"})[0]
