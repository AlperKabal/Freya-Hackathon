"""Rules no event brief uses, on imaginary bank D (dev/specs/imaginary-d.md): what the 11 October generalisation round
found when the state machine first met them, by rule family. Each check is about a mechanism, so it also runs on the
other banks where the mechanism applies.

Dates: the first ask is about the SPEC's earliest day ("Could you pay this tomorrow?"), not always today; a day the
       rules refuse is refused, not corrected; no day fits between the earliest day and the deadline; a far date is
       still said with its weekday.
Amounts: a later step of the ladder with another amount names that amount (never "that payment"); the customer's own
       amount survives a refused day; "too much" twice without a SPEC sentence is a refusal of the floor.
Attempts: counted for the whole call when the SPEC says so.
Read-back: one per promise when the SPEC says so.

    python dev/test_generalize.py
"""
import json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "dev"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import generate
from builder.ingest import parse_openapi
from walk import Call

fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f"   (want {want})"))


def load(path):
    return json.loads((KIT / path).read_text(encoding="utf-8"))


D = load("dev/specs/imaginary-d.json")
D_TOOLS = parse_openapi(KIT / "dev/specs/imaginary-d.openapi.json")["tools"]
A = load("dev/specs/brief-a.json")
A_TOOLS = parse_openapi(KIT / "tools/openapi.json")["tools"]
C = load("dev/specs/imaginary-c.json")
C_TOOLS = parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"]
MORT = {"facility": "f1", "kind": "mortgage", "arrears": 2400.0, "late_days": 20, "monthly": 800.0}
LINE = {"facility": "f2", "kind": "credit_line", "arrears": 500.0, "late_days": 5, "min_pay": 50.0, "line_ref": "7731"}
STUD = {"facility": "f3", "kind": "student_loan", "arrears": 900.0, "late_days": 90, "monthly": 150.0}
CARD = {"product_id": "p1", "type": "credit_card", "card_last4": "1903", "past_due": 2125.10, "days_late": 12, "minimum_payment": 637.50}


def d_call(products, now="2026-10-14T11:00"):
    return Call(D, D_TOOLS, products, mode="orch", now=now)


# ---------------------------------------------------------------- dates
c = d_call([MORT])
check("D: the first ask is the SPEC's own question", c.v["say_text"].endswith(D["negotiation"]["first_ask"]), True)
c.say("accept", "Yes.")
check("D: a yes to 'tomorrow' is read back as tomorrow, not refused as today", c.v["say_text"],
      "Let me read your promise back: you will pay 2400.00 for your mortgage on Thursday 15 October 2026. Shall I put that through?")
c.say("accept", "Yes.")
check("D: ...and recorded so", c.promises(), [("f1", 2400.0, "2026-10-15")])

c = d_call([MORT], now="2026-10-15T11:00")                 # tomorrow is a holiday, then a weekend, then another holiday
c.say("accept", "Yes.")
check("D: a yes when tomorrow is a holiday goes to the first day a promise can have", "Tuesday 20 October 2026" in c.v["say_text"], True)

c = d_call([MORT])
c.say("propose", "I can pay today.", day="today")
check("D: today is before the earliest day: refused, the open offer stays", c.v["say_text"],
      "That day is not possible. Can you pay 2400.00 for your mortgage on Thursday 15 October 2026?")
c = d_call([MORT])
c.say("propose", "Friday.", day="Friday")
check("D: a holiday is refused, not moved to the next business day (non_business_day = reject)", c.v["say_text"].startswith("That day is not possible. Can you pay 2400.00"), True)

c = d_call([LINE], now="2026-10-30T11:00")                  # the deadline (last business day of the month) is today, the earliest day is 3 November
check("D: no day between the earliest day and the deadline: the deadline becomes the earliest day", Call.__name__ and json.loads(c.v["neg_plan"])[0]["deadline"], "2026-11-03")
c.say("accept", "Yes.")
c.say("accept", "Yes.")
check("D: ...and the yes is recorded on that day, never on a refused one", c.promises(), [("f2", 500.0, "2026-11-03")])

c = Call(A, A_TOOLS, [CARD], mode="orch", now="2026-10-17T11:00")    # Saturday: brief A still offers the next business day
c.say("accept", "Yes.")
check("A: a yes to 'today' on a Saturday still offers Monday first", c.v["say_text"].startswith("That day is not possible. Can you pay 2125.10"), True)

ns = {}
from builder import codegen
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
check("_day: a date past the short list is spoken with its weekday", ns["_day"]({"spoken": {}}, "2027-03-05"), "Friday 5 March 2027")
check("_day: an unreadable value is given back as it is", ns["_day"]({"spoken": {}}, "soon"), "soon")

# ---------------------------------------------------------------- amounts
c = d_call([STUD])
c.say("too_much", "Too much.")
check("D: too much: the floor, with the SPEC's sentence", c.v["say_text"], "Can you pay 150.00 for your student loan on Thursday 15 October 2026? The remainder stays in arrears.")
c.say("refuse", "No.")
check("D: attempt 1 is the same floor on the deadline: only the day is new", c.v["say_text"], "Could you make that payment for your student loan on Tuesday 20 October 2026?")
c.say("refuse", "No.")
check("D: attempt 2 is ANOTHER amount: it is named, never 'that payment'", c.v["say_text"], "Can you pay 540.00 for your student loan on Tuesday 20 October 2026? The remainder stays in arrears.")
c.say("accept", "Yes.")
check("D: ...and the read-back holds that amount", "540.00" in c.v["say_text"], True)

c = d_call([MORT])
c.say("propose", "1000 on 30 October", day="30 October", amount="1000")
check("D: a refused day keeps the customer's own amount and asks for another day", c.v["say_text"], "That day is not possible. On which day can you pay 1000.00 for your mortgage?")
c.say("propose", "Tuesday then.", day="Tuesday")
check("D: ...the day then takes that amount", "1000.00 for your mortgage on Tuesday 20 October 2026" in c.v["say_text"], True)
c = d_call([MORT])
c.say("propose", "1000 on 30 October", day="30 October", amount="1000")
c.say("too_much", "No, too much.")
check("D: 'too much' after a customer's own amount still offers the floor once", c.v["say_text"].startswith("Can you pay 800.00 for your mortgage"), True)

C_LOAN = {"product_id": "x1", "type": "business_loan", "overdue_amount": 5000.0, "days_overdue": 20, "min_due": 1200.0}
c = Call(C, C_TOOLS, [C_LOAN], mode="orch")
c.say("too_much", "Too much.")
first = c.v["say_text"]
c.say("too_much", "Still too much.")
check("C (no too-much sentence): the floor is offered once; 'too much' again is a refusal, not the same offer again", (first.startswith("Can you pay the minimum due of 1200.00"), c.v["say_text"] != first), (True, True))

# ---------------------------------------------------------------- attempts for the whole call, a read-back per promise
c = d_call([MORT, LINE, STUD])
said = []
for _ in range(7):
    c.say("refuse", "No.")
    said.append(c.v["say_text"])
offers = [x for x in said if x.startswith("Can you pay") or x.startswith("Could you make")]
check("D: the call's three attempts: two for the mortgage (its ladder), the third for the credit line",
      [o.split(" for your ")[1].split(" on ")[0] for o in offers], ["mortgage", "mortgage", "credit line ending 7731"])
check("D: the student loan, asked last, gets no persuasion offer", [x for x in said if "student loan" in x and x.startswith("Can you pay") and "tomorrow" not in x], [])
check("D: the call counted three attempts", json.loads(c.v["nst"]).get("used"), 3)
check("D: every product without a promise is noted as declined", c.notes(), [("f1", "declined"), ("f2", "declined"), ("f3", "declined")])

c = d_call([MORT, LINE])
c.say("accept", "Yes.")
check("D: one read-back per promise, as soon as it is agreed", c.v["say_text"].startswith("Let me read your promise back: you will pay 2400.00 for your mortgage"), True)
c.say("accept", "Yes.")
check("D: after that yes the next facility is stated and asked", c.v["say_text"], "Your credit line ending 7731 has 500.00 in arrears and is 5 days late. Could you pay this tomorrow?")

# ---------------------------------------------------------------- v1 reads the same facts
wf = generate.build(D, D_TOOLS, "v1")
v = {"call_time": "2026-10-14T11:00", "acct_items": [MORT]}
from builder import verify
code = verify.code_of(wf["nodes"]["prepare_deal"]) if "prepare_deal" in wf["nodes"] else ""
if code:
    exec(code, {"vars": v})
    check("v1 D: the facts say a promise cannot be for today and name the earliest day", "A PROMISE CANNOT BE FOR TODAY: the earliest day is Thursday 15 October 2026" in v.get("deal_facts", ""), True)
else:
    name = next(n for n, x in wf["nodes"].items() if "deal_facts" in (verify.code_of(x) or ""))
    exec(verify.code_of(wf["nodes"][name]), {"vars": v})
    check("v1 D: the facts say a promise cannot be for today and name the earliest day", "A PROMISE CANNOT BE FOR TODAY: the earliest day is Thursday 15 October 2026" in v.get("deal_facts", ""), True)

print(f"\n{'all good' if not fails else f'{fails} failure(s)'}")
sys.exit(1 if fails else 0)
