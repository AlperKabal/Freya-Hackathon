"""Checks on our own customers (dev/scenarios.py) and on the runner (dev/run_scenarios.py), without the platform.

    python dev/test_scenarios.py

A scenario with a wrong expectation would "fail" a right agent and send us fixing the wrong thing. So every
expected record is checked against the brief's rules here, and the runner is run once with a pretend bank and a
pretend platform to see that it sends OUR day, scores the bank's records and reports a wrong one.
"""
import copy, datetime as dt, json, pathlib, sys, tempfile
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "tools")); sys.path.insert(0, str(KIT / "dev"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import run_scenarios
from expect import attempts, biz, callback_days, deadline
from run_cases import STYLES, persona_for
from scenarios import PUBLIC, scenarios
from score import score_ledger

fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {str(got)[:400]}" + ("" if ok else f"   (want {want})"))


ALL = scenarios()
ids = [s["id"] for s in ALL]
check("scenario ids are unique and none reuses a practice id", (len(ids), len(set(ids)), [i for i in ids if i in PUBLIC]), (len(ids), len(ids), []))
check("there are scenarios for both briefs, on six calendar days", (sorted({s["brief"] for s in ALL}), len({s["variables"]["now"][:10] for s in ALL})), (["A", "B"], 6))
OUTCOMES = {row.split("|")[1].strip().strip("`"): [r.strip().strip("`") for r in row.split("|")[2].split(",")] for row in
            (KIT / "briefs/brief-a.md").read_text(encoding="utf-8").split("| Outcome | Reason | When |")[1].splitlines()[2:8]}
bad = []
for s in ALL:
    today = dt.date.fromisoformat(s["variables"]["now"][:10])
    e, products = s["expected"], s["products"]
    if e["outcome"] not in OUTCOMES or (e["reason"] or "none") not in OUTCOMES[e["outcome"]]:
        bad.append((s["id"], "outcome and reason are not a row of the brief's closing table", e["outcome"], e["reason"]))
    for p in e["promises"]:
        prod = products[int(p["product_id"][1:]) - 1]
        d, floor = dt.date.fromisoformat(p["date"]), prod.get("minimum_payment", prod.get("instalment_amount"))
        if not (biz(d) and today <= d <= deadline(prod["days_late"], today)):
            bad.append((s["id"], "promise date is not a business day from today to the deadline", p))
        if not (floor <= p["amount"] <= prod["past_due"]):
            bad.append((s["id"], "promise amount is not between the floor and the full amount", p))
    if len({p["product_id"] for p in e["promises"]}) != len(e["promises"]) or {p["product_id"] for p in e["promises"]} & {n["product_id"] for n in e["notes"]}:
        bad.append((s["id"], "a product has more than one promise, or a promise and a note"))
    if e["promises"] and e["outcome"] != "promise" and not e["transfers"]:
        bad.append((s["id"], "a promise is recorded but the outcome is not promise"))
    if e["notes"] and (s["brief"] != "B" or e["transfers"]):
        bad.append((s["id"], "notes exist only in Brief B and never with a transfer"))
    if s["brief"] == "B" and not e["transfers"] and e["outcome"] not in ("not_reached", "not_verified") and len(e["promises"]) + len(e["notes"]) != len(products):
        bad.append((s["id"], "Brief B: every product needs a promise or a note"))
    for c in e["callbacks"]:
        hh = int(c["time"][:2]) * 60 + int(c["time"][3:])
        now = dt.datetime.fromisoformat(s["variables"]["now"])
        if dt.date.fromisoformat(c["date"]) not in callback_days(today) or not 600 <= hh <= 1140 or dt.datetime.fromisoformat(c["date"] + "T" + c["time"]) <= now:
            bad.append((s["id"], "callback outside today / next business day, 10:00-19:00, later than now", c))
    if (e["outcome"] == "transferred") != bool(e["transfers"]) or (e["outcome"] == "not_reached" and e["reason"] == "callback") != bool(e["callbacks"]):
        bad.append((s["id"], "outcome does not fit the transfers or callbacks"))
check(f"every expected record of the {len(ALL)} scenarios follows the brief's rules", bad, [])
texts = [persona_for(s, {"identity": s["identity"]}, style) for s in ALL for style in (None, "pieces")]
check("the kit's own persona builder takes every scenario, with and without a style", (len(texts), all(s["script"] in t["prompt"] for s, t in zip([x for x in ALL for _ in (0, 1)], texts))), (2 * len(ALL), True))
third = [s["id"] for s in ALL if "You are NOT" in persona_for(s, {"identity": s["identity"]})["prompt"]]
check("only the scenarios where someone else answers get the 'you are not the customer' persona",
      sorted(third) == sorted(s["id"] for s in ALL if s["family"] == "Third party" or s.get("third_party")), True)
check("the scenario where the customer herself has a relative's practice account is not a third party", "RULE-month-as-word" in third, False)

# ---------------------------------------------------------------- the runner, with a pretend bank and platform


class Bank:
    """Opens a session per base case and returns, as the ledger, exactly what each scenario expects (or a changed copy)."""
    def __init__(self, cases, spoil=None):
        self.cases, self.spoil, self.opened, self.owner = {c["id"]: c for c in cases}, spoil or {}, [], {}
    def http(self, path, body=None):
        if path == "/v1/practice/sessions":
            cid = f"c{len(self.opened)}"
            self.opened.append(body["case"])
            return {"ok": True, "variables": dict(PUBLIC[body["case"]]["variables"], customer_id=cid)}
        cid = path.rsplit("/", 1)[1]
        e = copy.deepcopy(self.cases[self.owner[cid]]["expected"])
        e = self.spoil.get(self.owner[cid], lambda x: x)(e)
        calls = [{"tool": "create_promise", "result": {"ok": True}} for _ in e["promises"]] + [{"tool": "close_call", "result": {"ok": True}}]
        return dict(e, calls=calls)


class Platform:
    def __init__(self, bank, verdict=lambda sid: "pass"):
        self.bank, self.verdict, self.sent, self.made = bank, verdict, {}, []
    def create_personas(self, personas):
        self.made += personas
        return {"personas": [{"id": "persona:" + p["name"]} for p in personas]}
    def run_simulation(self, agent_id, name, variables):
        self.sent = variables
        for pid, v in variables.items():
            sid = next(c for c in self.bank.cases if pid.startswith("persona:" + c + " "))
            self.bank.owner[v["customer_id"]] = sid
        return "sim1", "it1", "completed"
    def get_iteration(self, sim, it):
        return {"runs": [{"personaId": pid, "callId": "call-" + v["customer_id"], "outcome": self.verdict(self.bank.owner[v["customer_id"]]), "reason": "the judge's words"} for pid, v in self.sent.items()]}


cases = [s for s in ALL if s["id"].startswith(("CAL-fri-", "RULE-B-"))]
store = pathlib.Path(tempfile.mkdtemp()) / "personas.json"
bank = Bank(cases); plat = Platform(bank)
lines = []
pid = run_scenarios.personas(cases, None, plat, persona_for, store)
rows, sim, it, status = run_scenarios.run_once("agent", cases, pid, plat, bank.http, score_ledger, out=lines.append)
check("the runner opens a session for each scenario's base customer", bank.opened, [c["base"] for c in cases])
check("the simulation gets OUR day, not the practice set's", sorted({v["now"] for v in plat.sent.values()}), sorted({c["variables"]["now"] for c in cases}))
check("...and every other variable of the base customer", all(v["last_name"] == PUBLIC[bank.cases[bank.owner[v["customer_id"]]]["base"]]["variables"]["last_name"] for v in plat.sent.values()), True)
check("records that equal the expectation pass", ([r["pass"] for r in rows], len(lines)), ([True] * len(cases), len(cases)))
check("the rows have what dev/show_call.py reads", sorted(rows[0]), sorted(["id", "base", "family", "level", "now", "pass", "failed", "call_id", "tools", "customer_id"]))
check("personas are made once and found again", (len(plat.made), run_scenarios.personas(cases, None, plat, persona_for, store) == pid, len(plat.made)), (len(cases), True, len(cases)))
check("a style makes other personas", len(set(run_scenarios.personas(cases, "pieces", plat, persona_for, store).values()) & set(pid.values())), 0)


def later(e):
    e["promises"][0]["date"] = "2026-10-26"
    return e


bank = Bank(cases, spoil={"CAL-fri-first": later, "RULE-B-both-paid": lambda e: dict(e, outcome="no_promise", reason="refused")})
plat = Platform(bank, verdict=lambda sid: "fail" if sid == "CAL-fri-floor" else "pass")
rows, *_ = run_scenarios.run_once("agent", cases, run_scenarios.personas(cases, None, plat, persona_for, store), plat, bank.http, score_ledger, out=lambda x: None)
got = {r["id"]: r["failed"] for r in rows if not r["pass"]}
check("a promise on a wrong day, a wrong outcome and a judge's no are each reported, nothing else is",
      (sorted(got), ["promises" in got["CAL-fri-first"][0], "outcome" in got["RULE-B-both-paid"][0], got["CAL-fri-floor"][0].startswith("conversation: the judge's words")]),
      (["CAL-fri-first", "CAL-fri-floor", "RULE-B-both-paid"], [True, True, True]))


class A:
    brief, only, grep = "B", None, "cal-fri"


check("selection by brief and by text", [s["id"] for s in run_scenarios.select(A)], ["CAL-fri-three-one-day", "CAL-fri-two-deadlines", "CAL-fri-one-of-three"])
check("every style of the kit can be asked for", sorted(STYLES), ["asks_back", "corrects", "in_words", "pieces", "talkative"])
check("a long list runs as simulations of a practice run's size, in order, nothing lost",
      ([len(x) for x in run_scenarios.chunks(ALL, 12)][:3], sum(run_scenarios.chunks(ALL, 12), []) == ALL, run_scenarios.chunks(ALL[:3], 0)), ([12, 12, 12], True, [[x] for x in ALL[:3]]))


def refused(argv):
    try:
        run_scenarios.main(argv)
    except SystemExit as e:
        return str(e.code)
    return "ran"


check("more than fifteen scenarios need --all", refused(["agent-id"]).startswith(f"{len(ALL)} scenarios match: about"), True)
check("a selection that matches nothing says so", refused(["agent-id", "--grep", "no-such-scenario"]), "no scenario matches: see --list")

# ---------------------------------------------------------------- the scenarios against the agent the builder generates
# Each scenario's conversation is played through the generated orchestrated agent without the platform (dev/walk.py:
# a customer turn is given as the values the extraction would write) and the bank calls it makes are scored with the
# kit's own scorer against the scenario's expected records. The expectations come from the brief's text
# (dev/expect.py), the agent's dates from the builder's date code: when the two disagree, one of them is wrong, and
# that is found here instead of in a simulation.
from builder import generate, verify
from builder.ingest import parse_openapi
from expect import attempt_1, next_business_day
from walk import Call

TOOLS = parse_openapi(KIT / "tools/openapi.json")["tools"]
SPEC = {b: json.loads((KIT / f"dev/specs/{n}.json").read_text(encoding="utf-8")) for b, n in (("A", "brief-a"), ("B", "brief-ab"))}
WF = {b: generate.build(SPEC[b], TOOLS, "orch") for b in SPEC}


def finish(c, reply):
    """Confirm every read-back; answer every other sentence of the agent with `reply`."""
    for _ in range(12):
        if c.node not in ("negotiate", "negotiate_q"):
            break
        if "confirm" in c.v.get("say_text", "").lower():
            c.say("accept", "Yes, I confirm.")
        else:
            c.say(reply, "Yes." if reply == "accept" else "No.")
    return c


def play(s):
    """The scenario's conversation from the account step on; None when it ends before that step."""
    day = dt.date.fromisoformat(s["variables"]["now"][:10])
    p = [dict(x, product_id=f"p{i}") for i, x in enumerate(s["products"], 1)]            # get_account numbers them
    kind = s["id"].split("-", 2)[2] if s["id"].startswith("CAL-") else s["id"]
    if kind.startswith("callback") or kind in OUTSIDE:
        return None
    c = Call(SPEC[s["brief"]], TOOLS, p, now=s["variables"]["now"], wf=WF[s["brief"]])
    late = deadline(p[-1]["days_late"], day)
    if kind == "first": c.say("refuse", "I cannot pay today."); finish(c, "accept")
    elif kind == "late-date": c.say("propose", "My salary arrives then, I can pay then.", day=(late + dt.timedelta(days=14)).isoformat()); finish(c, "accept")
    elif kind == "floor": c.say("too_much", "The full amount is too much right now."); c.say("refuse", "I cannot pay anything today."); finish(c, "accept")
    elif kind == "not-a-business-day":
        off = next(day + dt.timedelta(days=i) for i in range(1, 30) if not biz(day + dt.timedelta(days=i)) and next_business_day(day + dt.timedelta(days=i)) <= late)
        c.say("propose", "Not today. I can pay on that day.", day=off.isoformat()); finish(c, "accept")
    elif kind == "refuses": c.say("refuse", "I cannot pay."); finish(c, "refuse")
    elif kind == "three-one-day": c.say("refuse", "Not today."); c.say("propose", "All three on that day.", day=attempt_1(day).isoformat(), about="all of them"); finish(c, "accept")
    elif kind == "two-deadlines": c.say("refuse", "Not today."); c.say("propose", "Both on that day.", day=next_business_day(late).isoformat(), about="both"); finish(c, "accept")
    elif kind == "one-of-three": c.say("propose", "The credit card on that day.", day=next_business_day(day).isoformat(), about="credit card"); finish(c, "refuse")
    elif kind == "RULE-below-floor": c.say("propose", "I can pay 300 today.", day="today", amount="300"); finish(c, "accept")
    elif kind == "RULE-change-at-read-back": c.say("accept", "Yes, today."); c.say("propose", "I will pay on that day instead.", day=attempt_1(day).isoformat()); finish(c, "accept")
    elif kind in ("RULE-change-after-record", "RULE-scam", "RULE-month-as-word"): c.say("accept", "Yes, I can pay today."); finish(c, "accept")
    elif kind == "RULE-vague-twice": c.say("vague", "Not today. Next week.", day="next week"); c.say("vague", "Sometime next week, I am not sure yet.", day="next week"); finish(c, "accept")
    elif kind == "RULE-not-talking": c.say("not_talking", "I do not want to talk about this."); c.say("not_talking", "I said I do not want to talk about this.")
    elif kind == "RULE-dispute": c.say("dispute", "That card was closed years ago, this debt is not mine.")
    elif kind == "RULE-human-after": c.say("human", "I want to speak to a human."); c.say("human", "No, a human please.")
    elif kind.startswith("LOOK-options"): c.say("refuse", s["script"].split('"')[1], question="yes"); finish(c, "accept")
    elif kind == "LOOK-real-plan-request": c.say("restructuring", "I cannot pay this amount. Can I get lower instalments?", question="yes")
    elif kind == "RULE-B-dispute-one":
        c.say("dispute", "The credit card debt is not mine, I never had that card.", about="credit card")
        c.say("propose", "The personal loan and the car loan on that day.", day=attempt_1(day).isoformat(), about="all of them"); finish(c, "accept")
    elif kind == "RULE-B-paid-and-refused": c.say("already_paid", "I already paid the credit card this morning.", about="credit card"); finish(c, "refuse")
    elif kind == "RULE-B-both-paid": c.say("already_paid", "I paid both this morning in the app.", about="both")
    elif kind == "RULE-B-plan-after-agreeing":
        c.say("propose", "The credit card tomorrow.", day=next_business_day(day).isoformat(), about="credit card"); c.say("restructuring", "I cannot pay them, I want lower instalments.")
    else:
        raise AssertionError(f"no conversation is written for scenario {s['id']}")
    return c


def records(c):
    """What the walked call left at the bank, in the shape of the mock's ledger."""
    f = c.spec["tool_fields"]
    outcome, reason = c.closed()
    return {"outcome": outcome, "reason": reason, "promises": [{"product_id": a, "amount": b, "date": d} for a, b, d in c.promises()],
            "notes": [{"product_id": a, "reason": b} for a, b in c.notes()], "callbacks": [],
            "transfers": [{"queue": b.get(f["transfer_to_agent"]["queue"])} for b in c.of("transfer_to_agent")],
            "calls": [{"tool": t, "result": {"ok": True}} for t, _ in c.calls] + ([{"tool": "close_call", "result": {"ok": True}}] if c.node == "final_end" else [])}


# these end before the account step, or in a step where the model decides: the walker cannot play them
OUTSIDE = {"RULE-unclear": "opening", "RULE-wrong-number": "opening", "RULE-deceased": "third party", "RULE-declines-twice": "identity", "RULE-asks-purpose-twice": "identity",
           "RULE-human-before": "identity", "RULE-hardship-accepts": "the support offer is answered in a model-driven step",
           "RULE-no-callback": "callback", "RULE-callback-past-then-tomorrow": "callback"}
played, differ = 0, []
for s in ALL:
    c = play(s)
    if c is None:
        continue
    played += 1
    r = score_ledger(s, records(c))
    if r["failed"]:
        differ.append((s["id"], c.node, r["failed"], c.v.get("say_text", "")[:160]))
check(f"the generated agent leaves exactly the expected records for the {played} scenarios that reach the negotiation", differ, [])
check("the scenarios the walker cannot play are the ones that end before the account step (and one model-driven offer)",
      sorted(s["id"] for s in ALL if play(s) is None and "callback" not in s["id"]), sorted(k for k in OUTSIDE if "callback" not in k))
c = play(next(s for s in ALL if s["id"] == "RULE-dispute"))
check("...a dispute ends the single-product call at once", (c.node, c.closed(), c.promises()), ("final_end", ("no_promise", "dispute"), []))
hard = next(s for s in ALL if s["id"] == "RULE-hardship-accepts")
c = Call(SPEC["A"], TOOLS, [dict(hard["products"][0], product_id="p1")], now=hard["variables"]["now"], wf=WF["A"])
check("...hardship goes to the support offer without a persuasion attempt", (c.say("hardship", "I lost my job last month, I cannot pay anything."), c.state()["p"][0]["attempt"]), ("offer_hardship", 0))

# the callback scenarios: the same window check the agent runs, on the scenario's clock
node = WF["A"]["nodes"]["check_callback"]


def callback(now, turns):
    v = {"now": now}
    for words in turns:
        v["cb_when_text"] = words
        exec(verify.code_of(node), {"vars": v})
        if v["cb_state"] != "retry":
            break
    return [{"date": v["cb_date_iso"], "time": v["cb_time_norm"]}] if v["cb_state"] == "valid" else [], v["cb_state"]


TURNS = {"callback-1830": ["today at seven in the evening"], "callback-past": ["today at six in the evening", "tomorrow morning at ten"],
         "RULE-no-callback": ["tonight at nine", "Saturday at noon"], "RULE-callback-past-then-tomorrow": ["today at six in the evening", "tomorrow morning at ten"]}
bad = []
for s in ALL:
    key = next((k for k in TURNS if s["id"].endswith(k)), None)
    if key:
        got, state = callback(s["variables"]["now"], TURNS[key])
        if got != s["expected"]["callbacks"] or (state == "valid") != (s["expected"]["reason"] == "callback"):
            bad.append((s["id"], got, state, s["expected"]["callbacks"]))
check(f"the callback check books exactly the expected callback for the {sum(any(s['id'].endswith(k) for k in TURNS) for s in ALL)} callback scenarios", bad, [])

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
