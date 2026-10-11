"""State-machine tests for builder/snippets/negotiation.py: the practice cases' negotiations, step by step, with the
extraction values a customer turn would produce. No model, no platform.

    python dev/test_negotiation.py
"""
import datetime as dt, json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen
from builder.snippets import dates as D

ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f"   (want {want})"))


def cfg_for(spec_path):
    spec = json.loads((KIT / spec_path).read_text(encoding="utf-8"))
    c = codegen.date_config(spec)
    sit = {x["id"]: {"note": next(a["note_reason"] for a in x["effect"]["actions"] if a["type"] == "note"), "say": x["say"]}
           for x in spec["situations"] if spec["notes"]["enabled"] and x["scope"] == "product" and any(a["type"] == "note" for a in x["effect"]["actions"])}
    c.update({"too_much_say": spec["amounts"]["too_much"]["say"], "below_min_say": spec["amounts"]["below_min"]["say"],
              "exhausted_note": spec["negotiation"]["attempts_exhausted"].get("note_reason") or spec["negotiation"]["attempts_exhausted"]["reason"],
              "confirm_question": spec["confirmation"]["question"], "floor_refused_is_flat": spec["amounts"]["too_much"]["refused_is_flat_refusal"],
              "vague_asks": spec["dates"]["vague"]["ask_exact_times"], "vague_then": spec["dates"]["vague"]["then"], "product_situations": sit})
    return c


def plan_for(products, today, cfg):
    out = []
    for name, full, floor, days in products:
        band = D.band_for(days, cfg)
        dl = D.deadline_for(band, today, cfg)
        ladder = []
        for st in band["ladder"]:
            d = D.apply_date_rule(st["date"], today, cfg, dl)
            d = min(d, dl)
            k = st["amount"]["kind"]
            ladder.append({"kind": k, "amount": floor if k == "floor" else full, "date": d.isoformat()})
        spoken = {(today + dt.timedelta(days=j)).isoformat(): D.spoken(today + dt.timedelta(days=j)) for j in range(60)}
        out.append({"name": name, "full": full, "floor": floor, "today": today.isoformat(), "deadline": dl.isoformat(), "ladder": ladder, "spoken": spoken})
    return out


def run(label, cfg, products, turns, now="2026-10-14"):
    today = dt.date.fromisoformat(now)
    plan = plan_for(products, today, cfg)
    st = ns["new_state"](plan)
    says = []
    nxt = "talk"
    for ev in turns:
        st, say, nxt = ns["step"](st, ev, plan, today, cfg)
        says.append(say)
    res = [(x["status"], x["amt"], x["date"], x["note"], x["attempt"]) for x in st["p"]]
    return st, says, nxt, res


A = cfg_for("dev/specs/brief-a.json")
AB = cfg_for("dev/specs/brief-ab.json")
E = lambda kind, day="", amount="", about="": {"kind": kind, "day": day, "amount": amount, "about": about}

# PUB-01: pays the full amount today, confirms
st, says, nxt, res = run("PUB-01", A, [("credit card ending 4821", 420.0, 126.0, 6)], [E("accept"), E("accept")])
check("PUB-01 outcome", (nxt, res[0][:3]), ("record", ("agreed", 420.0, "2026-10-14")))
check("PUB-01 read-back names amount, product, date", all(w in says[0] for w in ("420.00", "credit card ending 4821", "Wednesday 14 October 2026", "Do you confirm?")), True)

# PUB-04: names 6 November (after the late deadline), accepts the deadline
st, says, nxt, res = run("PUB-04", A, [("car loan", 1250.0, 400.0, 14)], [E("propose", day="the 6th of November"), E("accept"), E("accept")])
check("PUB-04 deadline offered", "latest date" in says[0] and "Friday 23 October 2026" in says[0], True)
check("PUB-04 outcome", (nxt, res[0][:3]), ("record", ("agreed", 1250.0, "2026-10-23")))

# PUB-06: full amount too much -> floor once (with the sentence), "you tell me" -> refusal -> attempt 1 names only the date -> accepts Friday
st, says, nxt, res = run("PUB-06", A, [("credit card ending 1903", 2125.1, 637.5, 12)], [E("too_much"), E("refuse"), E("accept"), E("accept")])
check("PUB-06 floor offered with the sentence", "637.50" in says[0] and A["too_much_say"] in says[0], True)
check("PUB-06 attempt 1 does not repeat the amount", "637.50" not in says[1] and "Friday 16 October 2026" in says[1], True)
check("PUB-06 outcome", (nxt, res[0][:3]), ("record", ("agreed", 637.5, "2026-10-16")))

# PUB-07: not today, vague, then Monday the 26th (holiday) -> next business day
st, says, nxt, res = run("PUB-07", A, [("personal loan", 540.0, 180.0, 5)],
                         [E("refuse", day="the week after next"), E("propose", day="Monday the twenty-sixth"), E("accept"), E("accept")])
check("PUB-07 asks for the exact day", "exact day" in says[0], True)
check("PUB-07 offers the 27th", "Tuesday 27 October 2026" in says[1], True)
check("PUB-07 outcome", (nxt, res[0][:3]), ("record", ("agreed", 540.0, "2026-10-27")))

# PUB-10: cannot pay today, accepts the full amount this Friday
st, says, nxt, res = run("PUB-10", A, [("credit card ending 7740", 365.0, 109.5, 8)], [E("refuse"), E("accept"), E("accept")])
check("PUB-10 attempt 1 is Friday", "Friday 16 October 2026" in says[0] and "365.00" in says[0], True)
check("PUB-10 outcome", (nxt, res[0][:3]), ("record", ("agreed", 365.0, "2026-10-16")))

# Flat refusals, late band: exactly 2 attempts, then the product ends refused; early band: exactly 1
st, says, nxt, res = run("refuse late", A, [("personal loan", 2100.0, 700.0, 28)], [E("refuse"), E("refuse"), E("refuse")])
check("late band: 2 offers then close", (nxt, res[0][0], res[0][3], res[0][4]), ("close", "ended", "refused", 2))
check("late band attempt 2 = floor on the deadline", "700.00" in says[1] and "Friday 23 October 2026" in says[1], True)
st, says, nxt, res = run("refuse early", A, [("credit card ending 4821", 420.0, 126.0, 6)], [E("refuse"), E("refuse")])
check("early band: 1 offer then close", (nxt, res[0][4]), ("close", 1))

# Below the floor -> said once and floor offered; accepted
st, says, nxt, res = run("below floor", A, [("credit card ending 1903", 2125.1, 637.5, 12)], [E("propose", amount="three hundred"), E("accept"), E("accept")])
check("below floor: floor offered", A["below_min_say"] in says[0] and "637.50" in says[0], True)
check("below floor: outcome", res[0][:3], ("agreed", 637.5, "2026-10-14"))

# "next Friday" said on a Friday
st, says, nxt, res = run("next Friday on a Friday", A, [("car loan", 1250.0, 400.0, 14)], [E("propose", day="next Friday"), E("accept")], now="2026-10-16")
check("next Friday on Friday -> 23rd", res[0][:3], ("agreed", 1250.0, "2026-10-23"))

# Changes the date at the read-back
st, says, nxt, res = run("change at read-back", A, [("credit card ending 4821", 420.0, 126.0, 6)], [E("accept"), E("propose", day="Friday"), E("accept")])
check("change at read-back -> new read-back", "Friday 16 October 2026" in says[1] and "Do you confirm?" in says[1], True)
check("change at read-back -> then record", (nxt, res[0][:3]), ("record", ("agreed", 420.0, "2026-10-16")))

# PUB-11: three products, cannot pay today, all three this Friday, one confirmation
P11 = [("credit card ending 2288", 220.0, 66.0, 9), ("personal loan", 640.0, 213.0, 9), ("car loan", 75.0, 25.0, 3)]
st, says, nxt, res = run("PUB-11", AB, P11, [E("refuse"), E("propose", day="this Friday", about="all three"), E("accept")])
check("PUB-11 all three on Friday", [r[:3] for r in res], [("agreed", 220.0, "2026-10-16"), ("agreed", 640.0, "2026-10-16"), ("agreed", 75.0, "2026-10-16")])
check("PUB-11 one read-back with three products", says[1].count(" for your ") == 3 and "Do you confirm?" in says[1], True)
check("PUB-11 record", nxt, "record")

# PUB-12: card tomorrow; refuses the others flatly: 2 attempts on the late loan, 1 on the early car loan
P12 = [("credit card ending 9015", 510.0, 153.0, 16), ("personal loan", 1320.0, 440.0, 16), ("car loan", 140.0, 46.0, 7)]
st, says, nxt, res = run("PUB-12", AB, P12, [E("propose", day="tomorrow", about="credit card"), E("refuse"), E("refuse"), E("refuse"), E("accept")])
check("PUB-12 card agreed tomorrow", res[0][:3], ("agreed", 510.0, "2026-10-15"))
check("PUB-12 loan: 2 attempts, refused", (res[1][0], res[1][3], res[1][4]), ("ended", "refused", 2))
check("PUB-12 car loan: 1 attempt, refused", (res[2][0], res[2][3], res[2][4]), ("ended", "refused", 1))
check("PUB-12 read-back only the card", says[3].count(" for your ") == 1 and "credit card" in says[3], True)
check("PUB-12 record", nxt, "record")

# PUB-13: one date for both, the loan has an earlier deadline -> clamped and said in the read-back
P13 = [("credit card ending 6604", 300.0, 90.0, 4), ("personal loan", 900.0, 300.0, 20)]
st, says, nxt, res = run("PUB-13", AB, P13, [E("propose", day="the 30th of October", about="both"), E("accept")])
check("PUB-13 dates", [r[:3] for r in res], [("agreed", 300.0, "2026-10-30"), ("agreed", 900.0, "2026-10-23")])
check("PUB-13 read-back says the loan is on its latest date", "latest date I can record" in says[0], True)

# Multi-product: "already paid" on one product is noted and the call continues
st, says, nxt, res = run("paid one", AB, P11, [E("refuse"), E("already_paid", about="credit card"), E("accept"), E("accept"), E("accept")])
check("paid one: card noted paid, others continue", (res[0][0], res[0][3], res[1][0], res[2][0]), ("ended", "paid", "agreed", "agreed"))

# Amounts in words
for words, want in [("four hundred and fifty-five", 455.0), ("one thousand three hundred and twenty", 1320.0), ("153.50", 153.5),
                    ("1,320", 1320.0), ("one twenty five", 125.0), ("six hundred thirty seven point five", 637.5), ("637 pounds 50", 637.5), ("nothing", None)]:
    check(f"amount {words!r}", ns["parse_amount"](words), want)

# Amounts the way people say them: a day number next to the amount, cents in words, "twelve fifty".
# The optional range (smallest floor, largest full amount of the account) picks between readings of a pair.
for words, rng, want in [("on the 16th I can pay 200", None, 200.0), ("200 on the 16th", None, 200.0), ("on 16 October, 300", None, 300.0),
                         ("the twenty-third, two hundred", None, 200.0), ("four hundred fifty five dollars and twenty cents", None, 455.2),
                         ("455 dollars and 20 cents", None, 455.2), ("four hundred fifty five dollars and 20 cents", None, 455.2),
                         ("twelve fifty", None, 1250.0), ("twelve fifty", (5.0, 40.0), 12.5), ("twelve fifty", (400.0, 2000.0), 1250.0),
                         ("twelve fifty five", None, 1255.0), ("twenty five fifty", None, 2550.0), ("fifty five", None, 55.0),
                         ("one twenty five", None, 125.0), ("on the 16th", None, None)]:
    check(f"amount {words!r} range {rng}", ns["parse_amount"](words, rng), want)
# The state machine reads the account's range: "twelve fifty" for a 1250.00 loan is 1250, for a 14.00 balance 12.50
st, says, nxt, res = run("twelve fifty", A, [("car loan", 1250.0, 400.0, 14)], [E("propose", day="Friday", amount="twelve fifty"), E("accept")])
check("twelve fifty on a 1250 loan", res[0][:3], ("agreed", 1250.0, "2026-10-16"))
st, says, nxt, res = run("on the 16th 200", A, [("credit card ending 1903", 2125.1, 200.0, 12)], [E("propose", day="the 16th", amount="on the 16th I can pay 200"), E("accept")])
check("day number in the amount field is not the amount", res[0][:3], ("agreed", 200.0, "2026-10-16"))
# "not today, Friday" in the day field never records today
st, says, nxt, res = run("not today Friday", A, [("car loan", 1250.0, 400.0, 14)], [E("refuse", day="not today, Friday"), E("accept")])
check("not today, Friday -> Friday", res[0][:3], ("agreed", 1250.0, "2026-10-16"))

# An internal error is kept in the state (the code node writes it to vars['neg_error']), never silent
bad_plan = [{"name": "x"}]
st2, say2, nxt2 = ns["step"](ns["new_state"]([{"full": 1.0, "today": "2026-10-14"}]), E("propose", day="Friday"), bad_plan, dt.date(2026, 10, 14), A)
check("error -> asks again", (say2, nxt2), ("Sorry, could you say that again?", "talk"))
check("error -> kept in state['err']", bool(st2.get("err")), True)

# Robustness
st, says, nxt, res = run("garbage", A, [("car loan", 1250.0, 400.0, 14)], [{"kind": None}, {}, E("question"), E("refuse")])
check("garbage never raises and ends in an offer", nxt, "talk")
check("question -> answer first", says[2].startswith("ASK_FIRST: "), True)
src = codegen.snippet("negotiation")
check("snippet has no double braces", "{{" in src or "}}" in src, False)

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
