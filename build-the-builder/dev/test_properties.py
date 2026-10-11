"""Customers nobody scripted: thousands of random conversations against the negotiation state machine, on many
calendar days and product mixes, for three banks' SPECs. No single answer is expected; these must hold in all of them:

    python dev/test_properties.py

 1. the code never fails and never falls silent (an internal error would make the agent say "could you say that again");
 2. an agreed amount lies between the product's lowest and highest acceptable amount;
 3. an agreed date is a business day of that bank, not before the call's day and not after the product's deadline;
 4. the full amount first: an amount below it is agreed only after the customer said it is too much or named an
    amount, or on a persuasion step that is defined as the lower amount (ties are broken by the promised total);
 5. a product gets at most the persuasion attempts of its band;
 6. a product that ended (refused, disputed, already paid) comes back only when the customer names a day or an
    amount of their own (a proposal is never a refusal), never through the agent's doing;
 7. what is recorded is what the last read-back said;
 8. a customer who only refuses, or only agrees, ends the negotiation within a few turns;
 9. the state survives being written to a variable and read back (JSON) at every turn, as on the platform;
10. a read-back is worded as the customer's promise, never as an offer;
11. an offer of an amount below the full one carries the SPEC's sentence for it ("the rest stays overdue");
12. "Could you make that payment" stands only for the amount the customer already heard with that sentence.
"""
import datetime as dt, json, pathlib, random, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen, generate, verify
from builder.ingest import parse_openapi

ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
step, new_state, UNCONFIRMED = ns["step"], ns["new_state"], ns["UNCONFIRMED"]
fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {str(got)[:700]}" + ("" if ok else f"   (want {want})"))


def load(path):
    return json.loads((KIT / path).read_text(encoding="utf-8"))


def environment(spec, tools, products, day):
    """The orchestrated agent's own config and the plan its account step builds for these products on this day."""
    g = generate.Gen(spec, tools, "orch")
    wf = g.build()
    cfg = g.cfg(**g.neg_cfg(), call_situations={}, turn_nodes=[], evidence={})
    now_var = next(v["name"] for v in spec["call_variables"] if v["role"] == "now")
    v = {now_var: day.isoformat() + "T11:00", "acct_items": products}
    exec(verify.code_of(wf["nodes"]["prepare_deal"]), {"vars": v})
    return cfg, json.loads(v["neg_plan"])


def business_day(spec, d):
    return d.weekday() in spec["calendar"]["business_weekdays"] and d.isoformat() not in spec["calendar"]["holidays"]


def random_event(rng, plan, today, product_kinds):
    kind = rng.choice(["accept", "refuse", "refuse", "too_much", "propose", "propose", "vague", "question", "unclear", UNCONFIRMED] + product_kinds)
    pp = rng.choice(plan)
    day = amount = about = ""
    if kind == "propose" or rng.random() < 0.15:
        day = rng.choice(["", "today", "tomorrow", "Friday", "next Friday", "next Monday", "this Saturday", "the 30th", "in three days", "next week",
                          "not today", "I can't pay today"] + [(today + dt.timedelta(days=rng.randint(0, 25))).isoformat() for _ in range(4)])
    if kind == "propose" and rng.random() < 0.5 or rng.random() < 0.08:
        amount = rng.choice(["%.2f" % pp["full"], "%.2f" % pp["floor"], "%.2f" % max(1.0, pp["floor"] - 5), "%.2f" % ((pp["full"] + pp["floor"]) / 2), "%.2f" % (pp["full"] + 50),
                             "two hundred", "twelve fifty"])
    if rng.random() < 0.3:
        about = rng.choice(["all of them", "both", pp["name"], "the " + pp["name"].split()[-1]])
    return {"kind": kind, "day": day, "amount": amount, "about": about}


def roles(say, state, plan, cfg):
    """10-12: each sentence has one role. A read-back is never worded as an offer; an offer below the full amount
    carries the SPEC's sentence for it; 'that payment' is only the amount the customer already heard."""
    out, text = [], str(say or "")
    text = text[len("ASK_FIRST: "):] if text.startswith("ASK_FIRST: ") else text
    if cfg.get("confirm_question") and text.endswith(cfg["confirm_question"]) and "for your" in text and "Let me read your promise back: you will pay " not in text:
        out.append(f"10 a read-back worded as something else: {text!r}")
    if "Let me read your promise back" in text and "Can you pay" in text.split("Let me read your promise back")[1]:
        out.append(f"10 a read-back that is also an offer: {text!r}")
    for i, pp in enumerate(plan):
        for m in __import__("re").finditer(r"Can you pay (\d+\.\d{2}) for your " + __import__("re").escape(pp["name"]) + r" on [^?]+\?", text):
            amt = float(m.group(1))
            if amt < pp["full"] - 0.005 and cfg.get("too_much_say") and cfg["too_much_say"] not in text:
                out.append(f"11 product {i + 1}: {amt} offered below the full {pp['full']} without the SPEC's sentence: {text!r}")
        if ("Could you make that payment for your " + pp["name"] + " ") in text:
            x = state["p"][i]
            if x.get("named_amt") is None or abs(x["offer_amt"] - x["named_amt"]) > 0.005:
                out.append(f"12 product {i + 1}: 'that payment' for {x['offer_amt']}, the customer heard {x.get('named_amt')}: {text!r}")
    return out


def one_run(spec, cfg, plan, today, rng, product_kinds):
    """One random conversation. Returns a list of broken invariants (empty when all hold)."""
    broken = []
    state, events, says, nxt = new_state(plan), [], [], "talk"
    ended, amount_named = set(), False
    for turn in range(16):
        ev = random_event(rng, plan, today, product_kinds)
        amount_named = amount_named or bool(ev["amount"])
        events.append(ev)
        state = json.loads(json.dumps(state))                 # 9: the state is a variable on the platform
        state, say, nxt = step(state, ev, plan, today, cfg)
        says.append(say)
        broken += roles(say, state, plan, cfg)
        if state.get("err"):
            broken.append(f"1 internal error: {state['err']}")
        if nxt not in ("talk", "record", "close") or (nxt == "talk" and not str(say).strip()):
            broken.append(f"1 silent or unknown step: {nxt!r} {say!r}")
        for i, x in enumerate(state["p"]):
            if i in ended and x["status"] != "ended":
                if not (ev["day"] or ev["amount"]):
                    broken.append(f"6 product {i + 1} ended and came back as {x['status']} without a proposal")
                ended.discard(i)
            if x["status"] == "ended":
                ended.add(i)
            if x["attempt"] > len(plan[i]["ladder"]):
                broken.append(f"5 product {i + 1}: attempt {x['attempt']} of {len(plan[i]['ladder'])}")
        if broken or nxt != "talk":
            break
    for i, x in enumerate(state["p"]):
        pp = plan[i]
        if x["status"] != "agreed":
            continue
        lo, hi = min(pp.get("lo", pp["floor"]), pp.get("hi", pp["full"])), pp.get("hi", pp["full"])
        if not (lo - 0.005 <= x["amt"] <= hi + 0.005):
            broken.append(f"2 product {i + 1}: amount {x['amt']} outside {lo}..{hi}")
        try:
            d = dt.date.fromisoformat(x["date"])
        except (TypeError, ValueError):
            broken.append(f"3 product {i + 1}: date {x['date']!r}"); continue
        earliest = ns["apply_date_rule"](spec["dates"]["earliest"], today, codegen.date_config(spec)) or today
        if d < earliest or (pp["deadline"] and d > dt.date.fromisoformat(pp["deadline"])) or (spec["dates"]["business_day_only"] and not business_day(spec, d)):
            broken.append(f"3 product {i + 1}: date {x['date']} (today {today}, earliest {earliest}, deadline {pp['deadline']}, business day {business_day(spec, d)})")
        lower_step = any(st["amount"] < pp.get("first", pp["full"]) - 0.005 for st in pp["ladder"][:x["attempt"]])
        if x["amt"] < pp.get("first", pp["full"]) - 0.005 and not (x["too_much"] or amount_named or lower_step):
            broken.append(f"4 product {i + 1}: {x['amt']} agreed below the first offer {pp.get('first', pp['full'])} although nobody asked for less")
    if nxt == "record":
        # one read-back of everything: the last sentence; one read-back per promise (the SPEC's choice): the last
        # read-back that named this product
        single = spec["multi_product"]["single_read_back"] or len(plan) == 1
        backs = [s[len("ASK_FIRST: "):] if s.startswith("ASK_FIRST: ") else s for s in says if s]
        for i, x in enumerate(state["p"]):
            if x["status"] != "agreed":
                continue
            if single:
                back = backs[-1] if backs else ""
            else:
                back = next((b for b in reversed(backs) if b.startswith("Let me read") and " for your " + plan[i]["name"] + " on " in b), "")
            if not (("%.2f" % x["amt"]) in back and plan[i]["spoken"].get(x["date"], x["date"]) in back):
                broken.append(f"7 product {i + 1}: recorded {x['amt']} on {x['date']}, the read-back said {back!r}")
    if broken:
        broken.append("events: " + json.dumps(events))
    return broken


def steady(cfg, plan, today, kind):
    """A customer who gives the same answer every time: the turns until the negotiation is over (None if it is not)."""
    state = new_state(plan)
    for turn in range(1, 30):
        state, say, nxt = step(json.loads(json.dumps(state)), {"kind": kind, "day": "", "amount": "", "about": ""}, plan, today, cfg)
        if nxt != "talk":
            return turn
    return None


BANKS = [("Brief A", load("dev/specs/brief-a.json"), parse_openapi(KIT / "tools/openapi.json")["tools"], [
              [{"product_id": "p1", "type": "credit_card", "card_last4": "4821", "past_due": 420.0, "days_late": 6, "minimum_payment": 126.0}],
              [{"product_id": "p1", "type": "personal_loan", "past_due": 2100.0, "days_late": 28, "instalment_amount": 700.0}],
              [{"product_id": "p1", "type": "car_loan", "past_due": 1250.0, "days_late": 45, "instalment_amount": 400.0}],
              [{"product_id": "p1", "type": "credit_card", "card_last4": "0001", "past_due": 95.0, "days_late": 1, "minimum_payment": 95.0}]]),
         ("Brief A+B", load("dev/specs/brief-ab.json"), parse_openapi(KIT / "tools/openapi.json")["tools"], [
              [{"product_id": "p1", "type": "credit_card", "card_last4": "2288", "past_due": 220.0, "days_late": 9, "minimum_payment": 66.0},
               {"product_id": "p2", "type": "personal_loan", "past_due": 640.0, "days_late": 9, "instalment_amount": 213.0},
               {"product_id": "p3", "type": "car_loan", "past_due": 75.0, "days_late": 3, "instalment_amount": 25.0}],
              [{"product_id": "p1", "type": "credit_card", "card_last4": "6604", "past_due": 300.0, "days_late": 4, "minimum_payment": 90.0},
               {"product_id": "p2", "type": "personal_loan", "past_due": 900.0, "days_late": 20, "instalment_amount": 300.0}],
              [{"product_id": "p1", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]])]
C_SPEC = load("dev/specs/imaginary-c.json")
C_TOOLS = parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"]
pf, items = C_SPEC["account"]["product_fields"], []
for i, t in enumerate(C_SPEC["account"]["product_types"]):
    band = C_SPEC["bands"][i % len(C_SPEC["bands"])]
    items.append({pf["id"]: f"x{i + 1}", pf["type"]: t["type"], pf["past_due"]: 5000.0 + 100 * i, pf["days_late"]: band["days_late_max"], t["floor_field"]: 1200.0})
BANKS.append(("imaginary bank C (six-day week, other bands and names)", C_SPEC, C_TOOLS, [items, items[:1], items[1:2]]))
D_SPEC = load("dev/specs/imaginary-d.json")
D_TOOLS = parse_openapi(KIT / "dev/specs/imaginary-d.openapi.json")["tools"]
D_MORT = {"facility": "f1", "kind": "mortgage", "arrears": 2400.0, "late_days": 20, "monthly": 800.0}
D_LINE = {"facility": "f2", "kind": "credit_line", "arrears": 500.0, "late_days": 5, "min_pay": 50.0, "line_ref": "7731"}
D_STUD = {"facility": "f3", "kind": "student_loan", "arrears": 900.0, "late_days": 90, "monthly": 150.0}
BANKS.append(("imaginary bank D (earliest tomorrow, refused days, attempts per call, one read-back each)", D_SPEC, D_TOOLS,
              [[D_MORT, D_LINE, D_STUD], [D_STUD], [D_LINE, D_MORT]]))

DAYS = [dt.date(2026, 10, 14), dt.date(2026, 10, 16), dt.date(2026, 10, 17), dt.date(2026, 10, 23), dt.date(2026, 10, 26), dt.date(2026, 10, 30),
        dt.date(2026, 11, 10), dt.date(2026, 11, 25), dt.date(2026, 12, 24), dt.date(2026, 12, 31), dt.date(2027, 1, 1), dt.date(2027, 2, 26)]
RUNS = 60
for name, spec, tools, mixes in BANKS:
    product_kinds = [x["id"] for x in spec["situations"] if spec["notes"]["enabled"] and x["scope"] == "product" and "negotiation" in x["stages"]
                     and any(a["type"] == "note" for a in x["effect"]["actions"])]
    bad, total, endless = [], 0, []
    for products in mixes:
        for day in DAYS:
            cfg, plan = environment(spec, tools, products, day)
            for seed in range(RUNS):
                total += 1
                broken = one_run(spec, cfg, plan, day, random.Random(f"{name}|{len(products)}|{day}|{seed}"), product_kinds)
                if broken:
                    bad.append((day.isoformat(), len(products), seed, broken))
            reads = 1 if spec["multi_product"]["single_read_back"] else len(plan)       # a yes to each read-back is a turn
            for kind, limit in (("refuse", 4 * len(plan) + 2), ("accept", 2 + reads + (len(plan) - 1 if reads > 1 else 0))):
                turns = steady(cfg, plan, day, kind)
                if turns is None or turns > limit:
                    endless.append((day.isoformat(), len(products), kind, turns))
    check(f"{name}: {total} random conversations on {len(DAYS)} days keep all the properties", bad[:3], [])
    check(f"{name}: a customer who only refuses, or only agrees, is done within a few turns", endless[:5], [])

# ---------------------------------------------------------------- what the random conversations found, as fixed cases

name, spec, tools, mixes = BANKS[1]
cfg, plan = environment(spec, tools, mixes[0], dt.date(2026, 10, 14))            # card 220 / loan 640 / car loan 75
E = lambda kind, day="", amount="", about="": {"kind": kind, "day": day, "amount": amount, "about": about}


def play(events, plan=plan, cfg=cfg, day=dt.date(2026, 10, 14)):
    state, says, nxt = new_state(plan), [], "talk"
    for ev in events:
        state, say, nxt = step(json.loads(json.dumps(state)), ev, plan, day, cfg)
        says.append(say)
    return state, says, nxt


# an amount named without a day waits for the day. It must not move on to the next product.
state, says, nxt = play([E("refuse"), E("propose", amount="220", about="credit card"), E("dispute"), E("propose", day="Friday")])
check("an amount that waited for its day is not used for the next product", [(x["status"], x["amt"]) for x in state["p"][:2]], [("ended", None), ("agreed", 640.0)])
state, says, nxt = play([E("refuse"), E("propose", amount="100", about="credit card"), E("refuse"), E("propose", day="2026-10-20")])
check("a new offer replaces the amount that was waiting: the day then takes the offered amount", (state["p"][0]["status"], state["p"][0]["amt"], state["p"][0]["date"]), ("agreed", 66.0, "2026-10-20"))
state, says, nxt = play([E("refuse"), E("propose", amount="100", about="credit card"), E("propose", day="Friday")])
check("without a new offer the waiting amount is still used with its day", (state["p"][0]["status"], state["p"][0]["amt"], state["p"][0]["date"]), ("agreed", 100.0, "2026-10-16"))

# at the read-back, a proposal that names a product changes that product, not the promise being read
to_readback = [E("propose", day="tomorrow", about="credit card"), E("refuse"), E("refuse"), E("refuse")]       # card agreed, both loans refused
state, says, nxt = play(to_readback)
check("the read-back holds the card only", (says[-1].count(" for your "), [x["status"] for x in state["p"]]), (1, ["agreed", "ended", "ended"]))
state, says, nxt = play(to_readback + [E("propose", day="2026-10-20", about="car loan")])
check("'the car loan on the 20th' at the read-back: the card's promise is untouched, the car loan gets its own",
      [(x["status"], x["amt"], x["date"]) for x in state["p"]], [("agreed", 220.0, "2026-10-15"), ("ended", None, None), ("agreed", 75.0, "2026-10-20")])
check("...and both are read back together", (says[-1].count(" for your "), says[-1].endswith(spec["confirmation"]["question"])), (2, True))
state, says, nxt = play(to_readback + [E("propose", day="Friday")])
check("a new day without a product name changes the promise being read back", (state["p"][0]["status"], state["p"][0]["date"], state["p"][2]["status"]), ("agreed", "2026-10-16", "ended"))

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
