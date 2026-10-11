"""Tests for the evidence check on special situations that cannot be undone (a transfer, the end of the call).

    python dev/test_situation_guard.py

The failure it guards against (orchestrated mode, a practice run): the customer answered the first ask with "I can't,
what are the other options", the extraction named the situation that transfers the call, and code transferred at
once. Three layers are tested here: the enum text no longer pulls such replies into a situation, code accepts the
situation only when the customer's own words carry the SPEC's evidence words, and a reply that fails the check is
handled as a non-answer (answer first, then the next persuasion offer).

Part 3 walks the GENERATED workflow: code nodes are executed, engine-run API calls are recorded, and each customer
turn is given as the values the extraction would write. No model, no platform. Brief A/B values are fixtures here
(dev/), never in builder/.
"""
import copy, datetime as dt, json, pathlib, re, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen, extract, generate, verify
from builder.ingest import parse_openapi
from builder.snippets import dates as D
from builder.spec_schema import validate

ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
UNCONFIRMED = ns["UNCONFIRMED"]
fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f"   (want {want})"))


def load(path):
    return json.loads((KIT / path).read_text(encoding="utf-8"))


TOOLS = parse_openapi(KIT / "tools/openapi.json")["tools"]
SPEC_A, SPEC_AB = load("dev/specs/brief-a.json"), load("dev/specs/brief-ab.json")
PLAN_SIT = next(x for x in SPEC_A["situations"] if x["id"] == "restructuring")
WORDS = PLAN_SIT["evidence_words"]

# ---------------------------------------------------------------- 1. the customer's words against the evidence words

AMBIGUOUS = ["I can't, what are the other options", "What can you do for me?", "Is there any other way?", "I can't pay today. What are my options?",
             "No.", "I can't.", "That is too much for me.", "Can you help me?", "I want an explanation.", "What else is possible?"]
EXPLICIT = ["I cannot pay this amount, I want lower instalments.", "Can I get a new payment plan?", "I'd like to restructure the loan.",
            "Could you reduce my monthly payments?", "I need smaller installments.", "Can we spread it out?", "LOWER INSTALMENTS, please!"]
for said in AMBIGUOUS:
    check(f"no evidence in {said!r}", ns["has_evidence"](said, WORDS), False)
for said in EXPLICIT:
    check(f"evidence in {said!r}", ns["has_evidence"](said, WORDS), True)
check("a stem matches only at the start of a word", ns["has_evidence"]("an explanation", ["plan"]), False)
check("a phrase is evidence", ns["has_evidence"]("I want to pay less each month", ["pay less"]), True)
check("empty words are never evidence", ns["has_evidence"]("a plan", ["", "  "]), False)

st = {}
check("no evidence words: the extraction stands", ns["situation_confirmed"]("x", "what are my options", st, []), True)
check("no customer words: the extraction stands", ns["situation_confirmed"]("x", "", st, WORDS), True)
check("words with evidence: confirmed", ns["situation_confirmed"]("x", "I want a payment plan", st, WORDS), True)
check("nothing was counted so far", st.get("weak"), None)
check("words without evidence: not confirmed the first time", ns["situation_confirmed"]("x", "what are my options", st, WORDS), False)
check("another situation is counted on its own", ns["situation_confirmed"]("y", "what are my options", st, WORDS), False)
check("the customer insists: confirmed the second time", ns["situation_confirmed"]("x", "is there no other way", st, WORDS), True)
check("garbage never raises", ns["situation_confirmed"]("x", None, {}, None), True)

# ---------------------------------------------------------------- 2. the state machine handles an unconfirmed situation


def cfg_for(spec):
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
        for s in band["ladder"]:
            d = min(D.apply_date_rule(s["date"], today, cfg, dl), dl)
            k = s["amount"]["kind"]
            ladder.append({"kind": k, "amount": floor if k == "floor" else full, "date": d.isoformat()})
        spoken = {(today + dt.timedelta(days=j)).isoformat(): D.spoken(today + dt.timedelta(days=j)) for j in range(60)}
        out.append({"name": name, "full": full, "floor": floor, "today": today.isoformat(), "deadline": dl.isoformat(), "ladder": ladder, "spoken": spoken})
    return out


def run(cfg, products, turns, now="2026-10-14"):
    today = dt.date.fromisoformat(now)
    plan = plan_for(products, today, cfg)
    state, says, nxt = ns["new_state"](plan), [], "talk"
    for ev in turns:
        state, say, nxt = ns["step"](state, ev, plan, today, cfg)
        says.append(say)
    return state, says, nxt


A, AB = cfg_for(SPEC_A), cfg_for(SPEC_AB)
E = lambda kind, day="", amount="", about="": {"kind": kind, "day": day, "amount": amount, "about": about}
U = E(UNCONFIRMED)
CARD, LOAN = ("credit card ending 7740", 365.0, 109.5, 8), ("personal loan", 2100.0, 700.0, 28)
EARLY = ("credit card ending 4821", 420.0, 126.0, 6)

state, says, nxt = run(A, [CARD], [U])
check("first ask, unconfirmed: answer first, then attempt 1 (full amount, last business day of the week)",
      says[0], "ASK_FIRST: Can you pay 365.00 for your credit card ending 7740 on Friday 16 October 2026?")
check("first ask, unconfirmed: one attempt used, the product stays open", (nxt, state["p"][0]["status"], state["p"][0]["attempt"]), ("talk", "open", 1))
state, says, nxt = run(A, [CARD], [U, E("accept"), E("accept")])
check("then the customer accepts and confirms: recorded as offered", (nxt, state["p"][0]["amt"], state["p"][0]["date"]), ("record", 365.0, "2026-10-16"))
state, says, nxt = run(A, [LOAN], [E("refuse"), U])
check("mid-ladder, unconfirmed: answer first, then attempt 2 (the floor on the deadline)",
      says[1].startswith("ASK_FIRST: ") and "700.00" in says[1] and "Friday 23 October 2026" in says[1], True)
state, says, nxt = run(A, [LOAN], [E("refuse"), E("refuse"), U])
check("no attempt left, unconfirmed: the open offer is repeated, the product does not end", (nxt, state["p"][0]["status"], says[2].startswith("ASK_FIRST: ")), ("talk", "open", True))
check("no attempt left, unconfirmed: the floor amount is not named again", "700.00" in says[2], False)
state, says, nxt = run(A, [LOAN], [E("refuse"), E("refuse"), U, E("refuse")])
check("the refusal that follows ends the product as before", (nxt, state["p"][0]["note"]), ("close", "refused"))
state, says, nxt = run(A, [EARLY], [E("refuse"), U])
check("early band (one attempt) after its attempt: repeated, not closed", (nxt, state["p"][0]["attempt"]), ("talk", 1))
state, says, nxt = run(A, [CARD], [E("accept"), U])
check("at the read-back, unconfirmed: answer first, read back again, nothing dropped",
      (nxt, state["p"][0]["status"], says[1].startswith("ASK_FIRST: Let me read your promise back: you will pay 365.00"), says[1].endswith("Do you confirm?")), ("talk", "agreed", True, True))
state, says, nxt = run(A, [CARD], [E(UNCONFIRMED, day="Friday")])
check("unconfirmed with a day named: a proposal, never a refusal", (state["p"][0]["status"], state["p"][0]["date"]), ("agreed", "2026-10-16"))
state, says, nxt = run(A, [CARD], [E(UNCONFIRMED, day="next week")])
check("unconfirmed with a vague period: ask for the exact day", "exact day" in says[0], True)
P12 = [("credit card ending 9015", 510.0, 153.0, 16), ("personal loan", 1320.0, 440.0, 16), ("car loan", 140.0, 46.0, 7)]
state, says, nxt = run(AB, P12, [U])
check("several products, first ask, unconfirmed: answer first, then attempt 1 of the first product",
      says[0], "ASK_FIRST: Can you pay 510.00 for your credit card ending 9015 on Friday 16 October 2026?")
state, says, nxt = run(A, [CARD], [E("question")])
check("a question is still answered without using an attempt", (says[0].startswith("ASK_FIRST: "), state["p"][0]["attempt"]), (True, 0))

# A refusal that mentions today refuses today. The extraction copies the day from "I can't pay today" as if it were
# named; taken as a proposal it would agree the full amount for today and read that back.
for words in ("today", "right now", "can't pay today", "no way today"):
    state, says, nxt = run(A, [CARD], [E("refuse", day=words)])
    check(f"a refusal with {words!r} as the day: attempt 1, nothing agreed", (state["p"][0]["status"], state["p"][0]["attempt"], "Friday 16 October 2026" in says[0]), ("open", 1, True))
state, says, nxt = run(A, [CARD], [E(UNCONFIRMED, day="today")])
check("unconfirmed with today as the day: answer first, attempt 1", says[0], "ASK_FIRST: Can you pay 365.00 for your credit card ending 7740 on Friday 16 October 2026?")
state, says, nxt = run(A, [CARD], [E("too_much", day="today")])
check("too much with today as the day: the floor offer, nothing agreed", (state["p"][0]["status"], "109.50" in says[0], A["too_much_say"] in says[0]), ("open", True, True))
state, says, nxt = run(A, [CARD], [E("refuse", day="Friday")])
check("another day in a refusal is still a proposal", (state["p"][0]["status"], state["p"][0]["date"]), ("agreed", "2026-10-16"))
state, says, nxt = run(A, [CARD], [E("refuse", day="not today, Friday")])
check("'not today, Friday' is a proposal for Friday", (state["p"][0]["status"], state["p"][0]["date"]), ("agreed", "2026-10-16"))
state, says, nxt = run(A, [CARD], [E("accept", day="today")])
check("a yes for today is still agreed for today", (state["p"][0]["status"], state["p"][0]["date"]), ("agreed", "2026-10-14"))
state, says, nxt = run(A, [CARD], [E("refuse"), E("question", day="today")])
check("asking to pay today after all is still a proposal for today", (state["p"][0]["status"], state["p"][0]["date"]), ("agreed", "2026-10-14"))
state, says, nxt = run(A, [CARD], [E("accept"), E("refuse", day="today")])
check("a no at the read-back that mentions today is a no", (nxt, state["p"][0]["status"]), ("close", "ended"))

# ---------------------------------------------------------------- 3. the generated workflow, walked turn by turn

VAR = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)(?::json)?\}\}")


def holds(c, v):
    """A transition condition, evaluated like the platform's deterministic operators."""
    if c.get("operator") == "always":
        return True
    if "logic" in c:
        r = [holds(x, v) for x in c["conditions"]]
        return all(r) if c["logic"] == "and" else any(r)
    val, op = v.get(c["variable"]), c["operator"]
    if op == "equals": return val is not None and str(val) == str(c["operand"])
    if op == "not_equals": return not (val is not None and str(val) == str(c["operand"]))
    if op == "is_set": return val is not None
    if op == "greater_than":
        try: return float(val) > float(c["operand"])
        except (TypeError, ValueError): return False
    return False                                              # matches_intent is a model's judgment: never taken here


class Call:
    """One call from the account step on: the generated code nodes run, engine-run API calls are recorded."""

    def __init__(self, spec, products, tools=TOOLS, mode="orch", now="2026-10-14T11:00"):
        self.wf = generate.build(spec, tools, mode)
        self.by_url = {t["url"]: name for name, t in tools.items()}
        now_var = next(x["name"] for x in spec["call_variables"] if x["role"] == "now")
        cust = next(x["name"] for x in spec["call_variables"] if x["role"] == "customer_id")
        self.v = {now_var: now, cust: "c_test"}
        self.calls = []
        exec(verify.code_of(self.wf["nodes"]["setup"]), {"vars": self.v})
        self.v["acct_items"] = products
        self.node = self.walk("prepare_deal")

    def walk(self, name):
        for _ in range(200):
            n = self.wf["nodes"][name]
            if n["node_type"] in ("conversation", "end_call"):
                return name
            if n["node_type"] == "code":
                exec(verify.code_of(n), {"vars": self.v})
            else:
                fn = n["pre_actions"][0]
                props = fn["function"]["parameters"]["properties"]
                body = {}
                for field, p in props["body"]["properties"].items():
                    d = p.get("default")
                    m = VAR.fullmatch(d) if isinstance(d, str) else None
                    if m and self.v.get(m.group(1)) is None:
                        continue                              # an unresolved single placeholder: the field is dropped
                    body[field] = self.v[m.group(1)] if m else d
                if fn.get("pre_process_code"):
                    exec(fn["pre_process_code"], {"vars": self.v, "config": {"body": body}})
                self.calls.append((self.by_url[props["url"]["default"]], body))
                for m in n.get("response_mapping") or []:
                    self.v[m["variable"]] = "true"            # every bank call succeeds here
            name = next(t["target_node"] for t in n["transitions"] if holds(t["condition"], self.v))
        raise AssertionError("the walk did not reach a conversation or end node")

    def say(self, kind, said, day="", amount="", about=""):
        """One customer turn in the current conversation node, as the extraction would write it."""
        key = self.node + ".total_turns"
        self.v[key] = int(self.v.get(key) or 0) + 1
        self.v.update(reply_kind=kind, said_text=said, day_text=day, amount_text=amount, about_text=about)
        self.node = self.walk("neg_eval")
        return self.node

    def transfers(self):
        return [b for tool, b in self.calls if tool == "transfer_to_agent"]


PUB10 = [{"product_id": "p1", "type": "credit_card", "card_last4": "7740", "past_due": 365.0, "days_late": 8, "minimum_payment": 109.5}]
PUB09 = [{"product_id": "p1", "type": "personal_loan", "past_due": 2100.0, "days_late": 28, "instalment_amount": 700.0}]
FRIDAY = "Can you pay 365.00 for your credit card ending 7740 on Friday 16 October 2026?"

# the reported call: the extraction names the transfer situation for "I can't, what are the other options"
c = Call(SPEC_A, PUB10)
check("the account step ends in the negotiation node", c.node, "negotiate")
check("the reported reply: no transfer, the model answers first", (c.say("restructuring", "I can't, what are the other options"), c.transfers()), ("negotiate_q", []))
check("the reported reply: then attempt 1 word for word", c.v["say_text"], FRIDAY)
check("the reported reply: the instruction names no alternative", c.v["say_instr"].startswith("The customer asked for something you cannot offer on this call."), True)
check("the consumed kind and words are reset", (c.v["reply_kind"], c.v["said_text"]), ("unclear", ""))
check("the customer agrees: read-back by the fixed line", (c.say("accept", "Yes, I can do that."), c.v["say_text"]),
      ("negotiate", "Let me read your promise back: you will pay 365.00 for your credit card ending 7740 on Friday 16 October 2026. Do you confirm?"))
check("the customer confirms: the call ends", c.say("accept", "Yes, I confirm."), "final_end")
check("the bank has the promise the practice case expects and no transfer", c.calls,
      [("create_promise", {"customer_id": "c_test", "product_id": "p1", "amount": 365.0, "date": "2026-10-16"})])
check("closed as a promise", (c.v["outcome"], c.v["reason"]), ("promise", ""))

for said in ("What can you do for me?", "Is there any other way?", "I can't pay today. What are my options?"):
    c = Call(SPEC_A, PUB10)
    check(f"{said!r} named as the transfer situation: no transfer, attempt 1", (c.say("restructuring", said), c.transfers(), c.v["say_text"]), ("negotiate_q", [], FRIDAY))
c = Call(SPEC_A, PUB10)
check("the same reply with 'today' copied as the day: still attempt 1, nothing read back for today",
      (c.say("restructuring", "I can't pay today, what are the other options", day="today"), c.transfers(), c.v["say_text"]), ("negotiate_q", [], FRIDAY))
c = Call(SPEC_A, PUB10)
check("a plain 'I can't pay today' with 'today' copied as the day: attempt 1 by the fixed line", (c.say("refuse", "No, I can't pay today.", day="today"), c.v["say_text"]), ("negotiate", FRIDAY))

# a real request still transfers at once (practice case PUB-09 and its variants)
for said in ("No, I cannot pay this amount. I want lower instalments.", "I can't afford it, can I get a new payment plan?", "I need smaller installments.",
             "Could you reduce my monthly payments?"):
    c = Call(SPEC_A, PUB09)
    check(f"{said!r}: transferred at once", (c.say("restructuring", said), c.calls), ("final_end", [("transfer_to_agent", {"customer_id": "c_test", "queue": "restructuring"})]))
    check(f"{said!r}: closed as the transfer", (c.v["outcome"], c.v["reason"]), ("transferred", "restructuring"))
check("the transfer is announced once", c.v["farewell"], "I will connect you with the team that handles this. Thank you for your time. Goodbye.")

# a request in other words: one extra turn, then the customer insists and it is acted on
c = Call(SPEC_A, PUB09)
check("a request without any evidence word: not acted on the first time", (c.say("restructuring", "Can you make it easier for me somehow?"), c.transfers()), ("negotiate_q", []))
check("the customer insists: transferred", (c.say("restructuring", "I really need you to make it easier."), len(c.transfers())), ("final_end", 1))

# code overrules the extraction only on evidence: without the customer's words the extraction stands
c = Call(SPEC_A, PUB09)
check("the words were not extracted: the extraction stands", (c.say("restructuring", ""), len(c.transfers())), ("final_end", 1))

# a kind that is not extracted again must not repeat the last one
c = Call(SPEC_A, PUB10)
c.say("restructuring", "what are the other options")
key = c.node + ".total_turns"
c.v[key] = int(c.v.get(key) or 0) + 1
c.v.update(said_text="Yes, Friday works.", day_text="", amount_text="", about_text="")          # reply_kind was not extracted this turn
c.node = c.walk("neg_eval")
check("a turn without an extracted kind: no transfer, the offer is said again", (c.node, c.transfers(), c.v["say_text"]), ("negotiate", [], FRIDAY))

# the evidence words never raise a reply INTO a situation, and the other kinds are untouched
c = Call(SPEC_A, PUB10)
check("a question that happens to hold an evidence word stays a question", (c.say("question", "Is that the plan?"), c.transfers(), c.v["say_instr"]),
      ("negotiate_q", [], "Answer the customer question in one short sentence, using only the facts given. If it is about an amount or a day you already offered, "
                          "state it as a fact (for example: that is the amount I mentioned) and do not offer it again."))
c = Call(SPEC_A, PUB10)
check("a situation without evidence words is acted on as before", c.say("hardship", "I lost my job last month."), "offer_hardship")
c = Call(SPEC_A, PUB10)
check("a refusal is a refusal: attempt 1 by the fixed line", (c.say("refuse", "No, I can't."), c.v["say_text"]), ("negotiate", FRIDAY))
c = Call(SPEC_A, PUB10)
c.say("accept", "Yes.")
check("at the read-back: not recorded, read back again", (c.say("restructuring", "Hmm, what are my other options?"), c.calls, c.v["say_text"].endswith("Do you confirm?")), ("negotiate_q", [], True))

# several products (notes on): the first ask, and a real request after one product was agreed
PUB12 = [{"product_id": "p1", "type": "credit_card", "card_last4": "9015", "past_due": 510.0, "days_late": 16, "minimum_payment": 153.0},
         {"product_id": "p2", "type": "personal_loan", "past_due": 1320.0, "days_late": 16, "instalment_amount": 440.0},
         {"product_id": "p3", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]
c = Call(SPEC_AB, PUB12)
check("three products, the reported reply: no transfer, attempt 1 of the first product", (c.say("restructuring", "I can't, what are the other options"), c.transfers(), c.v["say_text"]),
      ("negotiate_q", [], "Can you pay 510.00 for your credit card ending 9015 on Friday 16 October 2026?"))
c = Call(SPEC_AB, PUB12)
c.say("propose", "I will pay the credit card tomorrow.", day="tomorrow", about="the credit card")
check("three products, a real request after one was agreed: only the transfer reaches the bank",
      (c.say("restructuring", "For the loans I want lower instalments."), c.calls), ("final_end", [("transfer_to_agent", {"customer_id": "c_test", "queue": "restructuring"})]))
check("three products: closed as the transfer", (c.v["outcome"], c.v["reason"]), ("transferred", "restructuring"))

# ---------------------------------------------------------------- 4. what the generator writes

wf = generate.build(SPEC_A, TOOLS, "orch")
fields = {e["name"]: e for e in wf["nodes"]["negotiate"]["extraction_schema"]}
desc = fields["reply_kind"]["description"]
check("the enum text does not tell the model to prefer a situation", "When a special situation applies, choose it over the others" in desc, False)
check("the enum text names the everyday replies that are no situation", "is NOT a special situation unless a description says so: choose one of the other values for it." in desc, True)
check("the enum text does not push a reply about the amount towards a refusal", "use refuse" in desc, False)
check("the guarded situation asks for the customer's own words", "Only when the customer asks for exactly this in their own words." in desc, True)
check("no doubled full stops in the enum text", ".." in desc, False)
check("the customer's words are extracted as a copy, with a low confidence gate", (fields["said_text"]["type"], fields["said_text"]["min_confidence"]), ("string", 0.05))
check("the question node and the offer node extract the same fields", [[e["name"] for e in wf["nodes"][n]["extraction_schema"]][-6:] for n in ("negotiate_q", "offer_hardship")],
      [["reply_kind", "asks_question", "day_text", "amount_text", "about_text", "said_text"]] * 2)

old = copy.deepcopy(SPEC_A)                                    # a SPEC written before the field existed
for x in old["situations"]:
    x.pop("evidence_words", None)
check("a SPEC without evidence words is still valid", validate(old, TOOLS), [])
check("without evidence words nothing extra is extracted", [e["name"] for e in generate.build(old, TOOLS, "orch")["nodes"]["negotiate"]["extraction_schema"]],
      ["reply_kind", "asks_question", "day_text", "amount_text", "about_text"])
c = Call(old, PUB09)
check("without evidence words the extraction stands", (c.say("restructuring", "what are the other options"), len(c.transfers())), ("final_end", 1))
bad = copy.deepcopy(SPEC_A)
next(x for x in bad["situations"] if x["id"] == "restructuring")["evidence_words"] = "plan"
check("evidence words of the wrong type are rejected", bool(validate(bad, TOOLS)), True)
short = copy.deepcopy(SPEC_A)
next(x for x in short["situations"] if x["id"] == "restructuring")["evidence_words"] = ["a", "", "  no "]
check("stems too short to mean anything switch the check off", "said_text" in [e["name"] for e in generate.build(short, TOOLS, "orch")["nodes"]["negotiate"]["extraction_schema"]], False)

# a word list written carelessly: words of the agent's own sentences are everyday words of this call, never evidence
sloppy = copy.deepcopy(SPEC_A)
next(x for x in sloppy["situations"] if x["id"] == "restructuring")["evidence_words"] = ["Payment", "pay", "plan", "loan", "today", "amount", "payment plan", "card"]
gen = generate.Gen(sloppy, TOOLS, "orch")
check("the agent's own words are dropped from the evidence words", gen.evidence(next(x for x in sloppy["situations"] if x["id"] == "restructuring")), ["plan", "payment plan"])
c = Call(sloppy, PUB10)
check("with a careless list the echo of the agent's question is still no evidence",
      (c.say("restructuring", "I can't make this payment today, what are the other options?"), c.transfers()), ("negotiate_q", []))
c = Call(sloppy, PUB09)
check("with a careless list a real request still transfers", (c.say("restructuring", "I can't. I need a payment plan."), len(c.transfers())), ("final_end", 1))
for stem, text in (("plan", "an explanation"), ("plan", "a new plan"), ("instal", "smaller installments"), ("pay less", "I want to pay less"), ("", "anything"), ("smaller", "SMALLER ones")):
    check(f"generator and platform compare {stem!r} with {text!r} alike", generate.stem_in(stem, text), ns["has_evidence"](text, [stem]))


def farewell_of(spec, node="set_restructuring"):
    src = verify.code_of(generate.build(spec, TOOLS, "orch")["nodes"][node])
    return json.loads(bytes.fromhex(re.search(r"fromhex\('([0-9a-f]+)'\)", src).group(1)).decode("utf-8"))["f"]


said = copy.deepcopy(SPEC_A)
next(x for x in said["situations"] if x["id"] == "restructuring")["say"] = "I am connecting you with the team who can help with this."
check("a sentence that already announces the transfer is not followed by a second announcement", farewell_of(said),
      "I am connecting you with the team who can help with this. Thank you for your time. Goodbye.")
said = copy.deepcopy(SPEC_A)
next(x for x in said["situations"] if x["id"] == "restructuring")["say"] = "I understand."
check("a sentence that does not announce it still gets the announcement", farewell_of(said), "I understand. I am connecting you now. Thank you for your time. Goodbye.")

v1 = generate.build(SPEC_A, TOOLS, "v1")
task = v1["nodes"]["negotiate_1"]["task_message"]
check("v1: a plain no stays with the amount, date and refusal rules", "By itself, a plain no, or saying they cannot pay, is NOT one of them: the rules above handle it." in task, True)
check("v1: a question about options is no situation", "A question about what else is possible or what their options are is NOT one of them either" in task, True)
check("v1: the rules come before the situations in the prompt", task.index("\nRULES\n") < task.index("\nOTHER SITUATIONS\n"), True)
tool_calls = {t["target_node"]: t["description"] for t in v1["nodes"]["negotiate_1"]["transitions"] if t.get("is_tool_call")}
check("v1: the transfer tool's description carries what it is NOT", "NOT this: " + PLAN_SIT["not_this"] in tool_calls["do_restructuring_transfer0"], True)
for spec, tools, name in ((SPEC_A, TOOLS, "brief-a"), (SPEC_AB, TOOLS, "brief-ab"), (load("dev/specs/imaginary-c.json"), parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"], "imaginary-c")):
    for mode in ("v1", "orch"):
        w = generate.build(spec, tools, mode)
        check(f"{name} {mode}: lint and local runs pass", (verify.lint(w, spec, tools), verify.run_snippets(w, spec, days=["2026-10-14", "2026-10-16", "2026-12-24"])), ([], []))

# ---------------------------------------------------------------- 5. the builder's agents are told about it

guide = extract.format_guide()
check("the format shown to the Reader has the field as optional", '"evidence_words (optional)"' in guide, True)
check("the field guide says what evidence words are for", "evidence_words (optional): only for a situation that is the customer's explicit request" in guide, True)
check("the field guide asks not_this to rule out everyday replies", "also name the everyday replies that are NOT it" in guide, True)
check("the Reader is told that a transfer cannot be undone", "A transfer or the end of the call cannot be undone." in extract.READER, True)
check("the Auditor checks it", "not_this rules out the everyday replies the field guide names" in extract.AUDITOR, True)

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
