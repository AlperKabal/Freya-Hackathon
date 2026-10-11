"""Calendar and date logic. Runs in two places, unchanged:
- inside the platform's code sandbox, embedded by builder/codegen.py with a config made from the SPEC;
- locally, imported by the builder's tests.
So: only json, re and datetime; no double braces anywhere; no exception may escape a public function.

Config (from the SPEC, see codegen.date_config): business_weekdays, holidays, bands, earliest, business_day_only,
non_business_day, after_deadline, relative_weekday, vague_examples (dev/test_dates.py checks every key read here is written).
"""
import datetime as _dt
import re as _re

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
             "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
             "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30}


# ---------- calendar ----------

def parse_now(value):
    """'2026-10-14T11:00' (or a date, or with seconds/zone) -> datetime. None if unreadable."""
    s = str(value or "").strip()
    m = _re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?", s)
    if not m:
        return None
    y, mo, d, h, mi = m.groups()
    try:
        return _dt.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0))
    except ValueError:
        return None


def is_business_day(day, cfg):
    return day.weekday() in cfg["business_weekdays"] and day.isoformat() not in cfg["holidays"]


def next_business_day(day, cfg, include_self=False):
    d = day if include_self else day + _dt.timedelta(days=1)
    for _ in range(400):
        if is_business_day(d, cfg):
            return d
        d += _dt.timedelta(days=1)
    return d


def previous_business_day(day, cfg, include_self=False):
    d = day if include_self else day - _dt.timedelta(days=1)
    for _ in range(400):
        if is_business_day(d, cfg):
            return d
        d -= _dt.timedelta(days=1)
    return d


def nth_business_day_after(day, n, cfg):
    d = day
    for _ in range(max(0, int(n))):
        d = next_business_day(d, cfg)
    return d


def _monday(day):
    return day - _dt.timedelta(days=day.weekday())


def _last_business_day_of_week(today, week_offset, cfg):
    sunday = _monday(today) + _dt.timedelta(days=7 * int(week_offset) + 6)
    return previous_business_day(sunday, cfg, include_self=True)


def _last_business_day_of_month(today, month_offset, cfg):
    y, m = today.year, today.month + int(month_offset)
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    first_next = _dt.date(y + (m == 12), m % 12 + 1, 1)
    return previous_business_day(first_next - _dt.timedelta(days=1), cfg, include_self=True)


def apply_date_rule(rule, today, cfg, deadline=None):
    """A SPEC date rule -> date. `deadline` is the band's deadline (for kind 'deadline')."""
    k = rule.get("kind")
    if k == "today":
        return today
    if k == "deadline":
        return deadline
    if k == "nth_business_day_after_today":
        return nth_business_day_after(today, rule["n"], cfg)
    if k == "nth_calendar_day_after_today":
        d = today + _dt.timedelta(days=int(rule["n"]))
        roll = rule.get("roll", "none")
        if roll == "next_business_day":
            return next_business_day(d, cfg, include_self=True)
        if roll == "previous_business_day":
            return previous_business_day(d, cfg, include_self=True)
        return d
    if k == "last_business_day_of_week":
        d = _last_business_day_of_week(today, rule.get("week_offset", 0), cfg)
        if d <= today and rule.get("if_today_week_offset") is not None:
            d = _last_business_day_of_week(today, rule["if_today_week_offset"], cfg)
        return d
    if k == "last_business_day_of_month":
        d = _last_business_day_of_month(today, rule.get("month_offset", 0), cfg)
        if d < today:
            d = _last_business_day_of_month(today, int(rule.get("month_offset", 0)) + 1, cfg)
        return d
    return None


def band_for(days_late, cfg):
    try:
        n = int(float(days_late))
    except (TypeError, ValueError):
        return None
    for b in cfg["bands"]:
        if b["days_late_min"] <= n <= b["days_late_max"]:
            return b
    return None


def deadline_for(band, today, cfg):
    return apply_date_rule(band["deadline"], today, cfg) if band else None


def spoken(day):
    """'Friday 16 October 2026'. The weekday always comes from the calendar, never from a model."""
    return f"{WEEKDAYS[day.weekday()].capitalize()} {day.day} {MONTHS[day.month - 1].capitalize()} {day.year}" if day else ""


# ---------- understanding what the customer said ----------

def words_to_number(text):
    """'twenty-six' -> 26, 'twenty sixth' -> 26, '26th' -> 26, 'nineteen ninety' -> None (not a small number)."""
    t = str(text or "").lower().replace("-", " ").strip()
    m = _re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", t)
    if m:
        return int(m.group(1))
    parts = t.split()
    if len(parts) == 1:
        p = parts[0]
        return _UNITS.get(p, _TENS.get(p, _ORDINALS.get(p)))
    if len(parts) == 2 and parts[0] in _TENS:
        tail = _UNITS.get(parts[1], _ORDINALS.get(parts[1]))
        if tail is not None and tail < 10:
            return _TENS[parts[0]] + tail
    return None


_ORD_WORDS = "|".join(sorted(_ORDINALS, key=len, reverse=True))
_TENS_ORD = r"(?:twenty|thirty)[ -](?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|one|two|three|four|five|six|seven|eight|nine)"
# an ordinal day: "26th", "twenty-sixth", "first"; used after "the", where a plain "one" would be a pronoun
_ORDNUM = r"(\d{1,2}(?:st|nd|rd|th)|" + _TENS_ORD + "|" + _ORD_WORDS + r")"
# any day number, also cardinal: "26", "twenty six"; used next to a month name
_DAYNUM = r"(\d{1,2}(?:st|nd|rd|th)?|" + _TENS_ORD + "|" + _ORD_WORDS + "|" + "|".join(sorted(list(_UNITS) + ["twenty", "thirty"], key=len, reverse=True)) + r")"
_YEAR = r"(?: (\d{4}))?"
_MONTH = r"(" + "|".join(MONTHS + [m[:3] for m in MONTHS]) + r")\.?"


def _month_index(name):
    name = name.lower().rstrip(".")
    for i, m in enumerate(MONTHS):
        if name == m or name == m[:3]:
            return i + 1
    return None


def _future_day_of_month(today, day):
    """The next date (today or later) with this day of the month."""
    y, m = today.year, today.month
    for _ in range(13):
        try:
            d = _dt.date(y, m, day)
            if d >= today:
                return d
        except ValueError:
            pass
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def resolve_spoken_date(text, today, cfg):
    """What date did the customer name? -> {"status": exact|vague|none, "date": "YYYY-MM-DD" or ""}.
    `today` is the call's own date (from `now`), never the real clock.
    A self-correction ("tomorrow, no sorry, Friday") keeps the last day named; a negated today
    ("not today", "I can't pay right now") is not a day."""
    t = " " + _re.sub(r"[^a-z0-9/\- ]", " ", str(text or "").lower()) + " "
    t = _re.sub(r"\s+", " ", t)
    none = {"status": "none", "date": ""}
    if not t.strip():
        return none
    parts = _re.split(_CORRECTION, t)
    if len(parts) > 1:
        for seg in reversed(parts):
            r = _resolve(" " + seg.strip() + " ", today, cfg)
            if r["status"] != "none":
                return r
    return _resolve(t, today, cfg)


# words that start a self-correction: the day named after the last one wins
_CORRECTION = r"\b(?:no wait|wait|sorry|actually|i mean|make that|rather|scratch that|correction)\b"
_NOW = r"(?:today|tonight|right now|now|this (?:morning|afternoon|evening))"
# "not today", "I can't pay right now", "cannot do it today": a no to today, not a day (apostrophes became spaces)
_NEG_NOW = [r"\b(?:not|never|can t|cannot|cant|couldn t|won t|wont|don t|unable to)\b(?: [a-z]+){0,4}? " + _NOW + r"\b",
            r"\b(?:today|now)\b (?:is not|isn t|doesn t|does not|won t|will not|is no|is impossible|is bad)\b"]


def _resolve(t, today, cfg):
    none = {"status": "none", "date": ""}
    for p in _NEG_NOW:
        t = _re.sub(p, " ", t)
    t = _re.sub(r"\s+", " ", t)
    if not t.strip():
        return none
    try:
        m = _re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
        if m:
            return {"status": "exact", "date": _dt.date(*map(int, m.groups())).isoformat()}
        if _re.search(r"\bday after tomorrow\b", t):
            return {"status": "exact", "date": (today + _dt.timedelta(days=2)).isoformat()}
        if _re.search(r"\btomorrow\b", t):
            return {"status": "exact", "date": (today + _dt.timedelta(days=1)).isoformat()}
        if _re.search(r"\b(today|tonight|this (morning|afternoon|evening)|right now|now)\b", t):
            return {"status": "exact", "date": today.isoformat()}
        m = _re.search(r"\bin (\w+(?: \w+)?) days?\b", t)
        if m and words_to_number(m.group(1)) is not None:
            return {"status": "exact", "date": (today + _dt.timedelta(days=words_to_number(m.group(1)))).isoformat()}
        # a day of the month, with or without a month name: "26 october", "october 26th", "the 26th", "monday the 26th"
        m = _re.search(r"\b" + _DAYNUM + r"(?: of)? " + _MONTH + _YEAR + r"\b", t)
        if m:
            day, mon, year = words_to_number(m.group(1)), _month_index(m.group(2)), m.group(3)
        else:
            m = _re.search(r"\b" + _MONTH + r" (?:the )?" + _DAYNUM + r"\b" + _YEAR, t)
            day, mon, year = (words_to_number(m.group(2)), _month_index(m.group(1)), m.group(3)) if m else (None, None, None)
        if day and mon:
            y = int(year) if year else today.year
            d = _dt.date(y, mon, day)
            if not year and d < today:
                d = _dt.date(y + 1, mon, day)
            return {"status": "exact", "date": d.isoformat()}
        m = _re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)     # numbers only: day, then month
        if m:
            day, mon = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else today.year
            y = y + 2000 if y < 100 else y
            d = _dt.date(y, mon, day)
            if not m.group(3) and d < today:
                d = _dt.date(y + 1, mon, day)
            return {"status": "exact", "date": d.isoformat()}
        m = _re.search(r"\bthe " + _ORDNUM + r"\b", t) or _re.search(r"\bon (\d{1,2}(?:st|nd|rd|th))\b", t)
        if m and words_to_number(m.group(1)):
            d = _future_day_of_month(today, words_to_number(m.group(1)))
            if d:
                return {"status": "exact", "date": d.isoformat()}
        # a weekday, with this / next / plain
        for i, name in enumerate(WEEKDAYS):
            m = _re.search(rf"\b(this |next |coming |on )?{name}\b", t)
            if not m:
                continue
            mod = (m.group(1) or "").strip()
            this_week = _monday(today) + _dt.timedelta(days=i)
            if _re.search(rf"\bnext week (?:on )?{name}\b|\b{name} (?:of )?next week\b", t):
                return {"status": "exact", "date": (this_week + _dt.timedelta(days=7)).isoformat()}   # always the following calendar week
            if _re.search(rf"\bthis week (?:on )?{name}\b|\b{name} (?:of )?this week\b", t):
                return {"status": "exact", "date": this_week.isoformat()}
            if mod == "next":
                d = this_week + _dt.timedelta(days=7) if cfg["relative_weekday"]["next"] == "following_week" else _upcoming(today, i)
            elif mod == "this":
                d = this_week if cfg["relative_weekday"]["this"] == "current_week" else _upcoming(today, i, include_today=True)
            else:
                d = _upcoming(today, i, include_today=True)
            return {"status": "exact", "date": d.isoformat()}
        if _is_vague(t, cfg):
            return {"status": "vague", "date": ""}
    except (ValueError, TypeError, KeyError):
        return none
    return none


def _upcoming(today, weekday, include_today=False):
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return today + _dt.timedelta(days=delta)


_VAGUE = [r"\bnext week\b", r"\bweek after next\b", r"\bend of (the )?(month|week|year)\b", r"\b(beginning|start|middle|mid) of\b",
          r"\bsalary\b", r"\bpay ?day\b", r"\b(get|getting|am|i m) paid\b", r"\bthis week\b", r"\bsoon\b", r"\blater\b", r"\bsometime\b", r"\bin a (few|couple)\b", r"\bin (two|three|a few) weeks\b",
          r"\bnext month\b", r"\bwhen i can\b", r"\bnot sure\b",
          # a part of a named month, no day: "end of October", "early November", "mid October"
          r"\b(?:end|beginning|start|middle|mid) of (?:" + "|".join(MONTHS) + r")\b", r"\b(?:early|late|mid) (?:" + "|".join(MONTHS) + r")\b"]


def _is_vague(t, cfg):
    if any(_re.search(p, t) for p in _VAGUE):
        return True
    return any(str(e).lower() in t for e in cfg.get("vague_examples", []))


# ---------- times of day ----------

_HOURWORDS = dict(list(_UNITS.items())[1:13])          # one .. twelve


def _hour_of(token):
    t = str(token).lower()
    if t.isdigit():
        return int(t)
    return _HOURWORDS.get(t)


def parse_spoken_time(text, lo=None, hi=None):
    """'around eleven' -> '11:00', 'half past ten' -> '10:30', '3 pm' -> '15:00', '15:30' -> '15:30'.
    Without am/pm, an hour that fits the window [lo, hi] (minutes since midnight) is preferred. '' if no time."""
    t = " " + _re.sub(r"[^a-z0-9: ]", " ", str(text or "").lower().replace("a.m.", "am").replace("p.m.", "pm")) + " "
    t = _re.sub(r"\s+", " ", t)
    hw = r"(\d{1,2}|" + "|".join(sorted(_HOURWORDS, key=len, reverse=True)) + r")"
    h, m, half = None, 0, ""
    mt = _re.search(r"\b(\d{1,2}):(\d{2})\b", t)
    if mt:
        h, m = int(mt.group(1)), int(mt.group(2))
        half = "24h" if h > 12 or h == 0 else ""
    if h is None and _re.search(r"\b(noon|midday)\b", t):
        h, half = 12, "24h"
    if h is None:
        mt = _re.search(r"\bhalf past " + hw + r"\b", t) or None
        if mt: h, m = _hour_of(mt.group(1)), 30
    if h is None:
        mt = _re.search(r"\bquarter (past|to) " + hw + r"\b", t)
        if mt:
            h = _hour_of(mt.group(2))
            h, m = (h, 15) if mt.group(1) == "past" else ((h - 1) or 12, 45)
    if h is None:
        mt = _re.search(r"\b" + hw + r" ?(am|pm)\b", t) or _re.search(r"\b" + hw + r" o ?clock\b", t) \
             or _re.search(r"\b(?:at|around|about|by|after|before|from) " + hw + r"(?: (thirty|fifteen|forty five))?\b", t) \
             or _re.search(r"^ " + hw + r"(?: (thirty|fifteen|forty five))? $", t)
        if mt:
            h = _hour_of(mt.group(1))
            extra = mt.group(2) if mt.lastindex and mt.lastindex >= 2 else None
            if extra in ("am", "pm"):
                half = extra
            elif extra:
                m = {"thirty": 30, "fifteen": 15, "forty five": 45}[extra]
    if h is None or not 0 <= h <= 23 or not 0 <= m <= 59:
        return ""
    if not half:
        if _re.search(r"\b(am|morning)\b", t): half = "am"
        elif _re.search(r"\b(pm|afternoon|evening|tonight)\b", t): half = "pm"
    if half == "am":
        h = 0 if h == 12 else h
    elif half == "pm":
        h = h if h == 12 else h + 12
    elif half != "24h" and h <= 12:
        options = [h % 12, h % 12 + 12]
        inside = [x for x in options if lo is not None and hi is not None and lo <= x * 60 + m <= hi]
        h = inside[0] if len(inside) == 1 else (h if 7 <= h <= 12 else h + 12)
    if not 0 <= h <= 23:
        return ""
    return "%02d:%02d" % (h, m)


# ---------- checking a proposed promise date ----------

def check_promise_date(day, today, deadline, cfg):
    """Apply the SPEC's date rules to a date the customer named.
    -> {"verdict": ok|offer|too_early|invalid, "date": the date to record or offer, "why": short reason}"""
    if day is None:
        return {"verdict": "invalid", "date": "", "why": "no date"}
    earliest = apply_date_rule(cfg["earliest"], today, cfg) or today
    if day < earliest:
        return {"verdict": "too_early", "date": "", "why": "before the earliest allowed date"}
    if deadline and day > deadline:
        if cfg["after_deadline"] == "offer_deadline":
            return {"verdict": "offer", "date": deadline.isoformat(), "why": "after the deadline"}
        return {"verdict": "invalid", "date": "", "why": "after the deadline"}
    if cfg["business_day_only"] and not is_business_day(day, cfg):
        if cfg["non_business_day"] == "offer_next_business_day":
            nxt = next_business_day(day, cfg)
            if deadline and nxt > deadline:
                return {"verdict": "offer", "date": deadline.isoformat(), "why": "not a business day; the next one is after the deadline"}
            return {"verdict": "offer", "date": nxt.isoformat(), "why": "not a business day"}
        return {"verdict": "invalid", "date": "", "why": "not a business day"}
    return {"verdict": "ok", "date": day.isoformat(), "why": ""}
