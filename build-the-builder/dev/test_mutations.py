"""The brief mutation tool (dev/mutate_brief.py) checked without a model: its fifteen-odd changes apply to the
brief as it reads today, each check accepts a SPEC with the change and rejects one without it, and a run with a
stand-in Reader reports "read", "missed" and "also changed" correctly.

    python dev/test_mutations.py
"""
import asyncio, copy, json, pathlib, shutil, sys, tempfile
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import io
import mutate_brief as MB
from builder import extract

fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {str(got)[:400]}" + ("" if ok else f"   (want {want})"))


M = MB.mutations()
REF = json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8"))
check("the tool's own self-check: every change applies and every check tells a changed SPEC from an unchanged one", MB.selftest(), [])
check("there are at least fifteen changes, each to another kind of rule", len(M) >= 15, True)
blind = [n for n, m in M.items() if not MB.collateral(REF, m["oracle"](REF), [])]
check("a change outside the allowed parts is noticed for every mutation", blind, [])
check("two readings that differ only in wording are not called a change",
      MB.collateral(REF, json.loads(json.dumps(REF).replace("Do you confirm?", "Do you confirm this?")), []), [])

# a run with a stand-in Reader: perfect for most changes, blind for one, and careless for another
TMP = pathlib.Path(tempfile.mkdtemp(prefix="mutations-"))
real = extract.extract


async def reader(docs, tools, trace=None, max_repairs=2):
    text = "\n".join(d["text"] for d in docs)
    name = next((n for n, m in M.items() if [t for _, t in m["docs"]] == [d["text"] for d in docs]), None)
    spec = copy.deepcopy(REF) if name in (None, "six_day_week") else M[name]["oracle"](REF)       # misses the six-day week
    if name == "holiday_added":
        spec["identity"]["max_wrong_total"] = 5                                                  # reads it, and changes something else too
    return spec, {"repairs": 0, "audit_issues": [], "audit_applied": False, "errors": []}


extract.extract = reader
out, stdout = io.StringIO(), sys.stdout
sys.stdout = out
try:
    missed = asyncio.run(MB.run(TMP, None, 4, None))
finally:
    sys.stdout = stdout
    extract.extract = real
lines = out.getvalue().splitlines()
verdict = {l.split()[1]: l.split()[0] for l in lines if l.split() and l.split()[0] in ("READ", "MISSED", "NOISY", "ERROR")}
check("the missed change is reported as missed, the careless one as changing something else, the rest as read",
      (missed, verdict["six_day_week"], verdict["holiday_added"], sorted(set(verdict.values()))), (1, "MISSED", "NOISY", ["MISSED", "NOISY", "READ"]))
check("the report says what else changed", any("also changed" in l and "max_wrong_total" in l for l in lines), True)
check("the changed briefs, their tool API files and the SPECs (one per change, one for the unchanged brief) are written",
      ((TMP / "memo_overrides_two_rules" / "2-memo.md").exists(), (TMP / "outcome_renamed" / "tool-api.json").exists(), len(list(TMP.glob("*.spec.json")))), (True, True, len(M) + 1))
out = io.StringIO()
sys.stdout = out
try:
    again = MB.main(["--check", str(TMP), "--baseline", str(KIT / "dev/specs/brief-a.json")])
finally:
    sys.stdout = stdout
check("--check reads the same verdicts from the files", (again, "MISSED six_day_week" in out.getvalue()), (1, True))
shutil.rmtree(TMP, ignore_errors=True)
for p in (KIT / "traces").glob("dev-mutation-*.log"):
    p.unlink()

# ---------------------------------------------------------------- the GENERATOR follows each change (no model)
# The Reader's part needs the model (--run). The generator's part does not: give it the SPEC with the change made by
# hand and walk the agent it builds. A change the agent ignores here is knowledge of Brief A left in the generator.
import datetime as dt
from builder import generate, verify
from builder.ingest import parse_api
from walk import Call

LOAN = [{"product_id": "p1", "type": "personal_loan", "past_due": 2100.0, "days_late": 28, "instalment_amount": 700.0}]
CARD = [{"product_id": "p1", "type": "credit_card", "card_last4": "4821", "past_due": 420.0, "days_late": 6, "minimum_payment": 126.0}]
built = {}
for name, m in M.items():
    spec, tools = m["oracle"](REF), parse_api(m["api"])["tools"]
    built[name] = (spec, tools)
    bad = []
    for mode in ("v1", "orch"):
        wf = generate.build(spec, tools, mode)
        bad += verify.lint(wf, spec, tools) + verify.run_snippets(wf, spec, days=["2026-10-14", "2026-10-16", "2026-12-24"])
    if bad:
        check(f"{name}: the changed SPEC builds clean in both modes", bad[:3], [])
check("every changed SPEC builds clean in both modes", len(built), len(M))


def call(name, products, day="2026-10-14", **kw):
    spec, tools = built[name]
    return Call(spec, tools, products, now=day + "T11:00", **kw)


c = call("six_day_week", LOAN, "2026-10-16"); c.say("refuse", "No.")
check("six-day week: on a Friday the week's last business day is the Saturday", "Saturday 17 October 2026" in c.v["say_text"], True)
c = call("holiday_added", LOAN); c.say("propose", "then", day="2026-11-20")
check("an added holiday moves the late deadline by a day", "Tuesday 27 October 2026" in c.v["say_text"], True)
c = call("holiday_removed", CARD, "2026-11-10"); c.say("propose", "then", day="2026-11-11"); c.say("accept", "yes")
check("a removed holiday is a day a promise can have", c.promises(), [("p1", 420.0, "2026-11-11")])
c = call("band_limit_moved", [dict(CARD[0], days_late=9)]); c.say("refuse", "No."); c.say("refuse", "No.")
check("a moved band limit: nine days late is now the early band, one attempt", (c.node, c.closed()), ("final_end", ("no_promise", "refused")))
c = call("third_band", [dict(LOAN[0], days_late=60)]); c.say("propose", "then", day="2026-11-20")
check("a third band has its own deadline", "Monday 19 October 2026" in c.v["say_text"], True)
c = call("third_band", [dict(LOAN[0], days_late=60)])
for _ in range(3): c.say("refuse", "No.")
check("...and its own number of attempts", (c.node, c.closed()), ("final_end", ("no_promise", "refused")))
c = call("outcome_renamed", CARD); c.say("refuse", "No."); c.say("refuse", "No.")
check("a renamed outcome is the one the call closes with", c.closed(), ("no_agreement", "refused"))
c = call("deadline_in_calendar_days", CARD); c.say("propose", "then", day="2026-11-20")
check("a deadline in calendar days", "Wednesday 28 October 2026" in c.v["say_text"], True)
c = call("deadline_in_calendar_days", CARD, "2026-10-17"); c.say("propose", "then", day="2026-11-20")
check("...rolled to the next business day when it falls on a weekend", "Monday 2 November 2026" in c.v["say_text"], True)
c = call("new_situation", CARD)
check("a new situation with its own queue: transferred there and closed with its reason",
      (c.say("staff_member", "I work for the bank myself, I am staff."), c.of("transfer_to_agent"), c.closed()), ("final_end", [{"customer_id": "c_test", "queue": "staff"}], ("transferred", "staff")))
c = call("early_band_two_attempts", CARD); c.say("refuse", "No."); c.say("refuse", "No.")
check("a second attempt for the early band: the floor on its deadline", ("126.00" in c.v["say_text"], "Monday 2 November 2026" in c.v["say_text"], c.node), (True, True, "negotiate"))
c = call("first_ask_reworded", CARD)
check("a reworded first ask is the one that is said", c.v["deal_intro"].endswith("Are you able to settle this amount today?"), True)
c = call("vague_asked_twice", CARD); c.say("vague", "next week", day="next week"); first = c.v["say_text"]; c.say("vague", "sometime", day="next week"); second = c.v["say_text"]; c.say("vague", "not sure", day="next week")
check("the exact day asked twice, then a flat refusal: attempt 1", ("exact day" in first, "exact day" in second, "Friday 16 October 2026" in c.v["say_text"]), (True, True, True))
c = call("two_retries", CARD, answers={"create_promise": [{"ok": False}, {"ok": False}, {"ok": True}]}); c.say("accept", "yes"); c.say("accept", "Yes, I confirm.")
check("two retries: the third call records the promise", (len(c.of("create_promise")), c.closed()), (3, ("promise", None)))
c = call("two_retries", CARD, answers={"create_promise": [{"ok": False}] * 3}); c.say("accept", "yes"); c.say("accept", "Yes, I confirm.")
check("...and three failures close as the brief says", (len(c.of("create_promise")), c.closed()), (3, ("no_promise", "service_error")))
spec, tools = built["callback_window_moved"]
node = generate.build(spec, tools, "orch")["nodes"]["check_callback"]


def cb(words):
    v = {"now": "2026-10-14T09:00", "cb_when_text": words, "cb_attempts": "0"}
    exec(verify.code_of(node), {"vars": v})
    return v["cb_state"]


check("a moved callback window: 09:45 is inside, 18:00 is not", (cb("today at 9:45"), cb("today at 6 pm")), ("valid", "retry"))
for name in ("memo_overrides_two_rules", "callback_window_moved"):
    spec, tools = built[name]
    check(f"{name}: the window reaches the prompt of the callback step", f"between {spec['third_party']['callback']['window_start']} and {spec['third_party']['callback']['window_end']}" in generate.build(spec, tools, "v1")["nodes"]["third_party"]["task_message"], True)
spec, tools = built["identity_question_changed"]
idn = generate.build(spec, tools, "v1")["nodes"]["identity"]
body = {"field": "postcode", "answer": "sw1a 1aa"}
exec(idn["tools"][0]["pre_process_code"], {"config": {"body": body}, "vars": {}})
check("another identity question: offered to the model, and its answer sent in the form the description asks for",
      ("postcode" in idn["tools"][0]["function"]["parameters"]["properties"]["body"]["properties"]["field"]["enum"], "postcode" in idn["task_message"], body["answer"]), (True, True, "SW1A1AA"))
spec, tools = built["two_wrong_answers"]
check("the number of wrong answers that end the check is the SPEC's", ("max(0, 2 - int" in generate.build(spec, tools, "v1")["nodes"]["identity"]["tools"][0]["post_process_code"]), True)

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
