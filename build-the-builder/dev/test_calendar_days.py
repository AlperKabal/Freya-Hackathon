"""The practice customers all call on one Wednesday. The final runs "on several calendar days", so here the generated
agent is walked on every day of three months: Fridays, weekends, the days around each bank holiday, month and year
ends, and with the clock close to the end of the callback window.

    python dev/test_calendar_days.py

What is expected is worked out HERE, from the brief's own text and a plain day-by-day calendar, not with the
builder's date code: two independent ways to the same date. Brief A/B values are fixtures (dev/), never in builder/.
"""
import datetime as dt, json, pathlib, re, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen, generate, verify
from builder.ingest import parse_openapi
from builder.snippets import dates as D
from walk import Call
from expect import HOLIDAYS, WD, attempt_1, biz, next_business_day, nth_business_day_after, spoken

fails = 0
TOOLS = parse_openapi(KIT / "tools/openapi.json")["tools"]
SPEC_A = json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8"))
SPEC_AB = json.loads((KIT / "dev/specs/brief-ab.json").read_text(encoding="utf-8"))
WF_A, WF_AB = generate.build(SPEC_A, TOOLS, "orch"), generate.build(SPEC_AB, TOOLS, "orch")


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {str(got)[:400]}" + ("" if ok else f"   (want {want})"))


def check_all(label, bad, total):
    """One line for a whole sweep: how many days, and the first days that went wrong."""
    global fails
    fails += bool(bad)
    print(f"{'PASS' if not bad else 'FAIL'} {label}: {total - len(bad)} of {total} days" + ("" if not bad else "; wrong on " + " | ".join(str(b)[:260] for b in bad[:4])))


# ---------------------------------------------------------------- the calendar, read from the brief's own text

check("the brief's holiday line is found and the reference SPEC has the same days", sorted(HOLIDAYS), sorted(SPEC_A["calendar"]["holidays"]))


DEADLINE = {"early": lambda t: nth_business_day_after(t, 12), "late": lambda t: nth_business_day_after(t, 7)}       # rule 18
ATTEMPTS = {"early": 1, "late": 2}
PRODUCT = {"early": {"product_id": "p1", "type": "credit_card", "card_last4": "4821", "past_due": 420.0, "days_late": 6, "minimum_payment": 126.0},
           "late": {"product_id": "p1", "type": "personal_loan", "past_due": 2100.0, "days_late": 28, "instalment_amount": 700.0}}
NAME = {"early": "credit card ending 4821", "late": "personal loan"}
FLOOR = {"early": 126.0, "late": 700.0}
DAYS = [dt.date(2026, 10, 12) + dt.timedelta(days=i) for i in range(92)]              # 12 October 2026 .. 11 January 2027
WORK = [d for d in DAYS if biz(d)]
check("the sweep covers every holiday, weekends, a month end and the year end", (all(dt.date.fromisoformat(h) in DAYS for h in HOLIDAYS), len(DAYS), len(WORK)), (True, 92, 61))


def call(band, day, wf=WF_A, spec=SPEC_A, products=None):
    return Call(spec, TOOLS, products or [PRODUCT[band]], now=day.isoformat() + "T11:00", wf=wf)


def money(x): return "%.2f" % x


# ---------------------------------------------------------------- one product, every business day of three months

for band in ("early", "late"):
    full, floor, name = PRODUCT[band]["past_due"], FLOOR[band], NAME[band]
    bad = {k: [] for k in ("a1", "refuse", "late_date", "too_much", "holiday", "today")}
    for day in WORK:
        dl, a1 = DEADLINE[band](day), min(attempt_1(day), DEADLINE[band](day))
        # cannot pay today, accepts the first offer (the practice case of this kind, on every day)
        c = call(band, day)
        c.say("refuse", "No, I can't pay today.")
        want = f"Can you pay {money(full)} for your {name} on {spoken(a1)}?"
        got = c.v["say_text"]
        c.say("accept", "Yes, I can do that."); c.say("accept", "Yes, I confirm.")
        if (got, c.node, c.promises(), c.closed()) != (want, "final_end", [("p1", full, a1.isoformat())], ("promise", None)):
            bad["a1"].append((day.isoformat(), got, c.promises()))
        # refuses everything: exactly the band's number of offers, the second one the floor on the deadline, then closed
        c, offers = call(band, day), []
        for _ in range(ATTEMPTS[band] + 1):
            c.say("refuse", "No.")
            offers.append(c.v["say_text"])
        want2 = f"Can you pay {money(floor)} for your {name} on {spoken(dl)}? The rest stays overdue."
        if (c.node, c.promises(), c.closed()) != ("final_end", [], ("no_promise", "refused")) or (band == "late" and offers[1] != want2):
            bad["refuse"].append((day.isoformat(), c.node, offers[-2:], c.closed()))
        # a date after the deadline: the deadline is offered, then recorded (rule 23)
        c = call(band, day)
        c.say("propose", "I can pay then.", day=(dl + dt.timedelta(days=9)).isoformat())
        got = c.v["say_text"]
        c.say("accept", "Fine."); c.say("accept", "Yes, I confirm.")
        if (got.startswith(f"The latest date I can record for your {name} is {spoken(dl)}."), c.promises()) != (True, [("p1", full, dl.isoformat())]):
            bad["late_date"].append((day.isoformat(), got, c.promises()))
        # the full amount is too much: the floor once with its sentence, then attempt 1 names only the date (rule 26)
        c = call(band, day)
        c.say("too_much", "That is too much for me right now.")
        first = c.v["say_text"]
        c.say("refuse", "You tell me.")
        second = c.v["say_text"]
        c.say("accept", "OK."); c.say("accept", "Yes, I confirm.")
        if (first, second, c.promises()) != (f"Can you pay {money(floor)} for your {name} on {spoken(day)}? The rest stays overdue.",
                                               f"Could you make that payment for your {name} on {spoken(a1)}?", [("p1", floor, a1.isoformat())]):
            bad["too_much"].append((day.isoformat(), first, second, c.promises()))
        # a weekend day or a holiday inside the deadline: the next business day is offered (rule 20)
        off = next((day + dt.timedelta(days=i) for i in range(1, 40) if not biz(day + dt.timedelta(days=i)) and day + dt.timedelta(days=i) <= dl), None)
        if off:
            nb = next_business_day(off)
            exp = nb if nb <= dl else dl
            c = call(band, day)
            c.say("propose", "I can pay on that day.", day=off.isoformat())
            got = c.v["say_text"]
            c.say("accept", "All right."); c.say("accept", "Yes, I confirm.")
            if (spoken(exp) in got, off.isoformat() in json.dumps(c.promises()), c.promises()) != (True, False, [("p1", full, exp.isoformat())]):
                bad["holiday"].append((day.isoformat(), off.isoformat(), got, c.promises()))
        # can pay today
        c = call(band, day)
        c.say("accept", "Yes, I can pay it today."); c.say("accept", "Yes, I confirm.")
        if c.promises() != [("p1", full, day.isoformat())]:
            bad["today"].append((day.isoformat(), c.promises()))
    n = len(WORK)
    check_all(f"{band} band: cannot pay today, accepts attempt 1 (last business day of the week, next week's when today is that day)", bad["a1"], n)
    check_all(f"{band} band: refuses everything: {ATTEMPTS[band]} offer(s), then closed as refused", bad["refuse"], n)
    check_all(f"{band} band: a date after the deadline is recorded on the deadline", bad["late_date"], n)
    check_all(f"{band} band: too much, then the floor on the attempt-1 date, the amount named once", bad["too_much"], n)
    check_all(f"{band} band: a weekend day or holiday is never recorded, the next business day is", bad["holiday"], n)
    check_all(f"{band} band: can pay today", bad["today"], n)

# ---------------------------------------------------------------- the call itself falls on a weekend day or a holiday

OFF = [d for d in DAYS if not biz(d)]
for band in ("early", "late"):
    full, floor, name = PRODUCT[band]["past_due"], FLOOR[band], NAME[band]
    bad = {k: [] for k in ("yes", "too_much", "a1")}
    for day in OFF:
        nb, dl = next_business_day(day), DEADLINE[band](day)
        # "yes, today": today is no business day, so it cannot be the promise date (rule 19); the next business day is offered
        c = call(band, day)
        c.say("accept", "Yes, I can pay it today.")
        got = c.v["say_text"]
        c.say("accept", "OK."); c.say("accept", "Yes, I confirm.")
        if (spoken(nb) in got, c.promises()) != (True, [("p1", full, nb.isoformat())]):
            bad["yes"].append((day.isoformat(), got, c.promises()))
        c = call(band, day)
        c.say("too_much", "That is too much.")
        got = c.v["say_text"]
        c.say("accept", "OK."); c.say("accept", "Yes, I confirm.")
        if (spoken(day) in got, c.promises()) != (False, [("p1", floor, nb.isoformat())]):
            bad["too_much"].append((day.isoformat(), got, c.promises()))
        c = call(band, day)
        c.say("refuse", "No.")
        a1 = min(attempt_1(day), dl)
        if c.v["say_text"] != f"Can you pay {money(full)} for your {name} on {spoken(a1)}?":
            bad["a1"].append((day.isoformat(), c.v["say_text"]))
    check_all(f"{band} band, call on a non-business day: a yes to today is recorded on the next business day, after it was offered", bad["yes"], len(OFF))
    check_all(f"{band} band, call on a non-business day: the floor is never offered for that day", bad["too_much"], len(OFF))
    check_all(f"{band} band, call on a non-business day: attempt 1 is still the week's last business day", bad["a1"], len(OFF))

# ---------------------------------------------------------------- what "next Friday" and "this Friday" mean on each day (rule 22)

CFG = codegen.date_config(SPEC_A)
bad = []
for day in DAYS:
    monday = day - dt.timedelta(days=day.weekday())
    for i, wd in enumerate(WD):
        for words, want in ((f"next {wd}", monday + dt.timedelta(days=7 + i)), (f"this {wd}", monday + dt.timedelta(days=i))):
            got = D.resolve_spoken_date(words, day, CFG)
            if (got["status"], got["date"]) != ("exact", want.isoformat()):
                bad.append((day.isoformat(), words, got))
check_all("'next <weekday>' is the following calendar week, 'this <weekday>' the current one, on every day", bad, len(DAYS))

# ---------------------------------------------------------------- several products on other days (Brief B)

THREE = [{"product_id": "p1", "type": "credit_card", "card_last4": "2288", "past_due": 220.0, "days_late": 9, "minimum_payment": 66.0},
         {"product_id": "p2", "type": "personal_loan", "past_due": 640.0, "days_late": 9, "instalment_amount": 213.0},
         {"product_id": "p3", "type": "car_loan", "past_due": 75.0, "days_late": 3, "instalment_amount": 25.0}]
TWO = [{"product_id": "p1", "type": "credit_card", "card_last4": "6604", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0},
       {"product_id": "p2", "type": "personal_loan", "past_due": 900.0, "days_late": 20, "instalment_amount": 300.0}]
bad = {k: [] for k in ("all", "clamp", "mixed", "holiday_all")}
for day in WORK:
    early, late, a1 = DEADLINE["early"](day), DEADLINE["late"](day), attempt_1(day)
    # three products, all on one allowed day, one confirmation (rule B7)
    c = call("late", day, WF_AB, SPEC_AB, THREE)
    c.say("refuse", "I can't pay them today.")
    c.say("propose", "I can pay all three then.", day=a1.isoformat(), about="all three")
    back = c.v["say_text"]
    c.say("accept", "Yes, I confirm.")
    if (back.count(" for your "), c.promises(), c.notes(), c.closed()) != (3, [("p1", 220.0, a1.isoformat()), ("p2", 640.0, a1.isoformat()), ("p3", 75.0, a1.isoformat())], [], ("promise", None)):
        bad["all"].append((day.isoformat(), back, c.promises()))
    # one date for both, after the loan's deadline: the loan on its own deadline, said in the read-back (rule B6)
    both = next_business_day(late)
    c = call("late", day, WF_AB, SPEC_AB, TWO)
    c.say("refuse", "Not today.")
    c.say("propose", "Both on that day.", day=both.isoformat(), about="both")
    back = c.v["say_text"]
    c.say("accept", "Yes, I confirm.")
    if ("latest date I can record" in back, c.promises()) != (True, [("p1", 300.0, both.isoformat()), ("p2", 900.0, late.isoformat())]):
        bad["clamp"].append((day.isoformat(), both.isoformat(), back, c.promises()))
    # the card tomorrow's business day, the loan refused twice: one promise, one note, the promise wins (rules B8, closing)
    nb = next_business_day(day)
    c = call("late", day, WF_AB, SPEC_AB, TWO)
    c.say("propose", "The card on that day.", day=nb.isoformat(), about="credit card")
    c.say("refuse", "No, not the loan."); c.say("refuse", "No.")
    c.say("accept", "Yes, I confirm.")
    if (c.promises(), c.notes(), c.closed()) != ([("p1", 300.0, nb.isoformat())], [("p2", "refused")], ("promise", None)):
        bad["mixed"].append((day.isoformat(), c.promises(), c.notes(), c.closed()))
    # one day for all three that is a weekend day or a holiday: none is recorded on it, all on the next business day
    off = next((day + dt.timedelta(days=i) for i in range(1, 40) if not biz(day + dt.timedelta(days=i)) and next_business_day(day + dt.timedelta(days=i)) <= late), None)
    if off:
        nb2 = next_business_day(off)
        c = call("late", day, WF_AB, SPEC_AB, THREE)
        c.say("refuse", "Not today.")
        c.say("propose", "All of them on that day.", day=off.isoformat(), about="all of them")
        for _ in range(4):
            if c.node == "final_end": break
            c.say("accept", "Yes." if "confirm" not in c.v["say_text"] else "Yes, I confirm.")
        if c.promises() != [("p1", 220.0, nb2.isoformat()), ("p2", 640.0, nb2.isoformat()), ("p3", 75.0, nb2.isoformat())]:
            bad["holiday_all"].append((day.isoformat(), off.isoformat(), c.promises()))
check_all("three products, one allowed day for all: three promises, one read-back", bad["all"], len(WORK))
check_all("two products, one day after the loan's deadline: the loan on its own deadline", bad["clamp"], len(WORK))
check_all("one product promised, the other refused: promise, note, promise outcome", bad["mixed"], len(WORK))
check_all("three products, one day for all that is no business day: all on the next business day", bad["holiday_all"], len(WORK))

# ---------------------------------------------------------------- the prompt-driven mode is told when today cannot hold a promise

prepare = generate.build(SPEC_A, TOOLS, "v1")["nodes"]["prepare_deal"]
bad = []
for day in DAYS:
    v = {"now": day.isoformat() + "T11:00", "acct_items": [dict(PRODUCT["late"])]}
    exec(verify.code_of(prepare), {"vars": v})
    told = "TODAY IS NOT A DAY A PROMISE CAN HAVE" in v["deal_facts"]
    if told != (not biz(day)) or (told and f"offer {spoken(next_business_day(day))} ({next_business_day(day).isoformat()}) instead" not in v["deal_facts"]):
        bad.append((day.isoformat(), told, v["deal_facts"][-170:]))
check_all("v1 facts: 'today cannot hold a promise, offer the next business day' on weekends and holidays, and only then", bad, len(DAYS))

# ---------------------------------------------------------------- the callback window, with the clock near its end (rules 6, 7)

node = WF_A["nodes"]["check_callback"]


def callback(now, words, tries="0"):
    v = {"now": now, "cb_when_text": words, "cb_attempts": tries}
    exec(verify.code_of(node), {"vars": v})
    return (v.get("cb_state"), v.get("cb_date_iso"), v.get("cb_time_norm")) if v.get("cb_state") == "valid" else (v.get("cb_state"), None, None)


bad = {k: [] for k in ("tomorrow", "late_today", "past", "outside", "second")}
for day in DAYS:
    iso, tomorrow, nb = day.isoformat(), day + dt.timedelta(days=1), next_business_day(day)
    want = ("valid", tomorrow.isoformat(), "11:00") if tomorrow == nb else ("retry", None, None)
    if callback(iso + "T11:00", "tomorrow morning around eleven") != want:
        bad["tomorrow"].append((iso, callback(iso + "T11:00", "tomorrow morning around eleven")))
    if callback(iso + "T18:30", "today at 7 pm") != ("valid", iso, "19:00"):                 # 19:00 is inside, and later than 18:30
        bad["late_today"].append((iso, callback(iso + "T18:30", "today at 7 pm")))
    if callback(iso + "T18:30", "today at 6 pm")[0] != "retry":                                # inside the window but already past
        bad["past"].append((iso, callback(iso + "T18:30", "today at 6 pm")))
    if callback(iso + "T11:00", "today at 8 pm")[0] != "retry" or callback(iso + "T11:00", "today at half past nine")[0] != "retry":
        bad["outside"].append(iso)
    if callback(iso + "T11:00", "today at 8 pm", tries="1")[0] != "fail":                      # the second time outside: no callback
        bad["second"].append(iso)
check_all("callback 'tomorrow around eleven': booked only when tomorrow is the next business day", bad["tomorrow"], len(DAYS))
check_all("callback today at 19:00 with the clock at 18:30: the window's last minute still counts", bad["late_today"], len(DAYS))
check_all("callback today at 18:00 with the clock at 18:30: not later than now, asked again", bad["past"], len(DAYS))
check_all("callback outside 10:00-19:00: asked again", bad["outside"], len(DAYS))
check_all("callback outside the window a second time: none is booked", bad["second"], len(DAYS))
check("callback 'in an hour' at 11:00: today at 12:00", callback("2026-10-14T11:00", "she will be back in an hour"), ("valid", "2026-10-14", "12:00"))
check("callback 'in half an hour' at 18:30: the window's last minute", callback("2026-10-14T18:30", "in half an hour"), ("valid", "2026-10-14", "19:00"))
check("callback 'in an hour' at 18:30: after the window, asked again", callback("2026-10-14T18:30", "in an hour")[0], "retry")
check("callback 'in two hours' at 23:30: tomorrow at 01:30 is outside the window", callback("2026-10-14T23:30", "in two hours")[0], "retry")

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
