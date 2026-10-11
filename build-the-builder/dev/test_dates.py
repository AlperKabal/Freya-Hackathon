"""Tests for builder/snippets/dates.py with hand-checked expectations, on several calendar days and two banks.

    python dev/test_dates.py

Expected dates were worked out by hand from the brief text (and the Brief A ones also with an independent loop in
Phase 1). They are fixtures, so Brief A values are allowed here (dev/), never in builder/.
"""
import datetime as dt, json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # Windows consoles default to cp1254
from builder import codegen
from builder.snippets import dates as D

D_ = dt.date.fromisoformat
A = codegen.date_config(json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8")))
C = codegen.date_config(json.loads((KIT / "dev/specs/imaginary-c.json").read_text(encoding="utf-8")))
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f"   (want {want})"))


def band(cfg, name): return next(b for b in cfg["bands"] if b["name"] == name)


# 1. Deadlines and attempt-1 dates, Brief A, on six calendar days (Wednesday, Fridays, before holidays, year end)
for now, early, late, att1 in [("2026-10-14", "2026-11-02", "2026-10-23", "2026-10-16"),
                               ("2026-10-16", "2026-11-04", "2026-10-28", "2026-10-23"),
                               ("2026-11-10", "2026-11-30", "2026-11-20", "2026-11-13"),
                               ("2026-12-24", "2027-01-13", "2027-01-06", "2026-12-31"),
                               ("2026-10-23", "2026-11-12", "2026-11-04", "2026-10-30"),
                               ("2026-10-30", "2026-11-18", "2026-11-10", "2026-11-06")]:
    t = D_(now)
    check(f"A {now} early deadline", D.deadline_for(band(A, "early"), t, A).isoformat(), early)
    check(f"A {now} late deadline", D.deadline_for(band(A, "late"), t, A).isoformat(), late)
    check(f"A {now} attempt-1 date", D.apply_date_rule(band(A, "late")["ladder"][0]["date"], t, A).isoformat(), att1)

# 2. Bands from days late
for days, want in [(1, "early"), (7, "early"), (8, "late"), (45, "late"), ("12", "late"), (46, None), (0, None), ("x", None)]:
    b = D.band_for(days, A); check(f"A band for {days!r}", b["name"] if b else None, want)

# 3. What the customer said -> date, against now = 2026-10-14 (a Wednesday)
W = D_("2026-10-14")
for said, status, date in [
        ("tomorrow", "exact", "2026-10-15"), ("I can pay tomorrow", "exact", "2026-10-15"), ("the day after tomorrow", "exact", "2026-10-16"),
        ("today", "exact", "2026-10-14"), ("right now", "exact", "2026-10-14"),
        ("this Friday", "exact", "2026-10-16"), ("Friday", "exact", "2026-10-16"), ("on Friday", "exact", "2026-10-16"),
        ("next Friday", "exact", "2026-10-23"), ("next Monday", "exact", "2026-10-19"), ("the one on Friday", "exact", "2026-10-16"),
        ("Monday the 26th", "exact", "2026-10-26"), ("the 30th", "exact", "2026-10-30"), ("on the 2nd", "exact", "2026-11-02"),
        ("30 October", "exact", "2026-10-30"), ("October 30th", "exact", "2026-10-30"), ("the thirtieth of October", "exact", "2026-10-30"),
        ("twenty-sixth of October", "exact", "2026-10-26"), ("6 November", "exact", "2026-11-06"), ("November the sixth", "exact", "2026-11-06"),
        ("the sixth of November", "exact", "2026-11-06"), ("in three days", "exact", "2026-10-17"), ("14/11", "exact", "2026-11-14"),
        ("2026-10-20", "exact", "2026-10-20"), ("5 October", "exact", "2027-10-05"),
        ("next week", "vague", ""), ("sometime next week", "vague", ""), ("the week after next", "vague", ""),
        ("end of the month", "vague", ""), ("when my salary comes", "vague", ""), ("when I get paid", "vague", ""), ("this week", "vague", ""),
        ("", "none", ""), ("I don't know", "none", ""), ("I already paid", "none", "")]:
    r = D.resolve_spoken_date(said, W, A)
    check(f"A said {said!r}", (r["status"], r["date"]), (status, date))

# 3b. Human phrasing (styles corrects / pieces / in_words): negated "today", self-corrections, "next week <day>",
# vague periods named by month. now = 2026-10-14 (a Wednesday)
for said, status, date in [
        ("not today, Friday", "exact", "2026-10-16"), ("I can't pay right now, maybe on Friday", "exact", "2026-10-16"),
        ("not now", "none", ""), ("not today", "none", ""), ("I cannot do it today but tomorrow is fine", "exact", "2026-10-15"),
        ("today doesn't work, how about Monday", "exact", "2026-10-19"), ("no, I can pay today", "exact", "2026-10-14"),
        ("tomorrow, no sorry, Friday", "exact", "2026-10-16"), ("Friday, sorry, I mean the 30th", "exact", "2026-10-30"),
        ("Friday sorry", "exact", "2026-10-16"), ("actually make that the twenty-third", "exact", "2026-10-23"),
        ("next week Tuesday", "exact", "2026-10-20"), ("Tuesday next week", "exact", "2026-10-20"), ("next week on Monday", "exact", "2026-10-19"),
        ("end of October", "vague", ""), ("the end of November", "vague", ""), ("early November", "vague", ""), ("mid October", "vague", ""),
        ("beginning of December", "vague", "")]:
    r = D.resolve_spoken_date(said, W, A)
    check(f"A human said {said!r}", (r["status"], r["date"]), (status, date))
# "next week Tuesday" said on a Monday is the FOLLOWING week's Tuesday, not tomorrow
MON = D_("2026-10-12")
for said, date in [("next week Tuesday", "2026-10-20"), ("Tuesday next week", "2026-10-20"), ("Tuesday", "2026-10-13")]:
    check(f"A on Mon said {said!r}", D.resolve_spoken_date(said, MON, A)["date"], date)

# 3c. Every config key the date snippet reads is written by codegen.date_config (a missing key would raise inside
# the sandbox and be swallowed by a try/except, silently)
import re as _re
used = set(_re.findall(r"cfg\[\"([a-z_]+)\"\]", (KIT / "builder/snippets/dates.py").read_text(encoding="utf-8")))
check("date snippet config keys all written by date_config", sorted(used - set(A)), [])

# 4. The same words on a Friday (2026-10-16): "next" is the following calendar week, "this" the current one
F = D_("2026-10-16")
for said, date in [("next Friday", "2026-10-23"), ("this Friday", "2026-10-16"), ("Friday", "2026-10-16"), ("tomorrow", "2026-10-17"), ("next Monday", "2026-10-19")]:
    check(f"A on Fri said {said!r}", D.resolve_spoken_date(said, F, A)["date"], date)

# 5. Checking a promise date (Brief A rules 19, 20, 23), now = 2026-10-14
late_dl, early_dl = D_("2026-10-23"), D_("2026-11-02")
for label, day, dl, verdict, date in [
        ("PUB-04 after the late deadline", "2026-11-06", late_dl, "offer", "2026-10-23"),
        ("PUB-07 holiday inside the early deadline", "2026-10-26", early_dl, "offer", "2026-10-27"),
        ("Saturday inside the deadline", "2026-10-17", late_dl, "offer", "2026-10-19"),
        ("Saturday after the deadline", "2026-10-24", late_dl, "offer", "2026-10-23"),
        ("yesterday", "2026-10-13", late_dl, "too_early", ""),
        ("on the deadline", "2026-10-23", late_dl, "ok", "2026-10-23"),
        ("PUB-13 card inside the early deadline", "2026-10-30", early_dl, "ok", "2026-10-30"),
        ("PUB-13 loan after the late deadline", "2026-10-30", late_dl, "offer", "2026-10-23"),
        ("today", "2026-10-14", late_dl, "ok", "2026-10-14")]:
    r = D.check_promise_date(D_(day), W, dl, A)
    check(f"A check {label}", (r["verdict"], r["date"]), (verdict, date))

# 6. Imaginary bank C: Monday-Saturday, other holidays, calendar-day deadline, "next" = upcoming, month-end ladder
M = D_("2027-01-04")                       # a Monday; 2027-01-06 is a holiday
check("C band_1 deadline (15 calendar days, rolled)", D.deadline_for(band(C, "band_1"), M, C).isoformat(), "2027-01-19")
check("C band_2 deadline (10th business day, Saturdays count)", D.deadline_for(band(C, "band_2"), M, C).isoformat(), "2027-01-16")
check("C band_3 deadline (5th business day)", D.deadline_for(band(C, "band_3"), M, C).isoformat(), "2027-01-11")
check("C attempt-1 date (last business day of month, a Saturday)", D.apply_date_rule(band(C, "band_1")["ladder"][0]["date"], M, C).isoformat(), "2027-01-30")
check("C said 'next Friday' (upcoming)", D.resolve_spoken_date("next Friday", M, C)["date"], "2027-01-08")
check("C Saturday is a business day", D.check_promise_date(D_("2027-01-09"), M, D_("2027-01-16"), C)["verdict"], "ok")
check("C holiday -> next business day", D.check_promise_date(D_("2027-01-06"), M, D_("2027-01-16"), C)["date"], "2027-01-07")

# 7. Robustness: bad input never raises
for bad in [None, 123, "2026-13-45", "the 31st of February", "next blursday", "🙂"]:
    try:
        r = D.resolve_spoken_date(bad, W, A); check(f"no crash on {bad!r}", r["status"] in ("exact", "vague", "none"), True)
    except Exception as e:
        check(f"no crash on {bad!r}", repr(e), "no exception")
check("parse_now with seconds and zone", D.parse_now("2026-10-14T11:00:00Z"), dt.datetime(2026, 10, 14, 11, 0))
check("parse_now garbage", D.parse_now("soon"), None)

# 7b. Times of day, with a 10:00-19:00 window (minutes 600-1140) for hours said without am/pm
for said, want in [("tomorrow morning around eleven", "11:00"), ("around eleven", "11:00"), ("at 3", "15:00"), ("at three", "15:00"),
                   ("3 pm", "15:00"), ("10am", "10:00"), ("half past ten", "10:30"), ("quarter past two", "14:15"), ("quarter to six", "17:45"),
                   ("15:30", "15:30"), ("at eleven thirty", "11:30"), ("six o'clock", "18:00"), ("noon", "12:00"), ("in the evening at seven", "19:00"),
                   ("eleven", "11:00"), ("on the 15th at eleven", "11:00"), ("sometime in the afternoon", ""), ("tomorrow", ""), ("", ""), (None, "")]:
    check(f"time {said!r}", D.parse_spoken_time(said, 600, 1140), want)

# 8. The embedded code node: no double braces, runs with a `vars` dict like the sandbox gives it
body = "try:\n    t = parse_now(vars.get('now')).date()\n    vars['answer'] = resolve_spoken_date(vars.get('said'), t, CFG)['date']\nexcept Exception:\n    vars['answer'] = ''\n"
src = codegen.embed(A, body)
check("embedded source has no double braces", "{{" in src or "}}" in src, False)
env = {"vars": {"now": "2026-10-14T11:00", "said": "tomorrow"}}
exec(src, env)
check("embedded code resolves 'tomorrow' from now, not the real clock", env["vars"]["answer"], "2026-10-15")

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
