"""Regression checks for the fixes of the 11 October tuning round (practice runs of both modes, read call by call):

1. A sandbox result marker in a variable: after one cut sandbox output, the platform stored its error (which quotes
   the marker) in a variable, and every later hook of the call failed (v1 PUB-07, 30 identity checks in a row).
   Every code node and hook now takes the marker out of the variables first.
2. "I cannot pay this amount. I want lower instalments." is the request, not a refusal (v1 PUB-09): the look-alike
   guard says that a message that also asks for the situation in so many words is that situation.
3. A question about the open offer ("How much is the minimum payment?") is answered and the offer is not said again
   (orch PUB-06: the judge counted the repeated offer as a second floor offer).
4. Self-corrections in amounts and a no to today said after the day ("right now I can't, maybe Friday").

    python dev/test_tuning.py
"""
import datetime as dt, json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "dev"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen, generate, verify
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


TOOLS = parse_openapi(KIT / "tools/openapi.json")["tools"]
SPECS = [("brief-a", load("dev/specs/brief-a.json"), TOOLS), ("brief-ab", load("dev/specs/brief-ab.json"), TOOLS),
         ("imaginary-c", load("dev/specs/imaginary-c.json"), parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"]),
         ("imaginary-d", load("dev/specs/imaginary-d.json"), parse_openapi(KIT / "dev/specs/imaginary-d.openapi.json")["tools"])]
MARK = "__CODE_EXEC" + "_RESULT__"

# ---------------------------------------------------------------- 1. the marker scrub
for tag, spec, tools in SPECS:
    for mode in ("v1", "orch"):
        wf = generate.build(spec, tools, mode)
        srcs = [(n, verify.code_of(x)) for n, x in wf["nodes"].items() if verify.code_of(x)] + [(l, s) for l, k, s in verify.hooks(wf)]
        check(f"{tag} {mode}: every code node and hook scrubs the marker", [n for n, s in srcs if not s.startswith(("import json\n" + codegen.SCRUB, codegen.SCRUB))], [])
        check(f"{tag} {mode}: the marker never appears as one word in a source", [n for n, s in srcs if MARK in s], [])
        pre = next((t.get("pre_process_code") for t in wf["nodes"]["identity"]["tools"] if t.get("pre_process_code")), "")
        v = {"verify_identity_response.message": "Sandbox did not return a parseable result. Stdout: \n" + MARK + '{"config": {}}', "keep": "x"}
        exec(pre, {"vars": v, "config": {"body": {}}})
        check(f"{tag} {mode}: the identity pre-hook removes the marker from a poisoned variable", MARK in v["verify_identity_response.message"], False)
        check(f"{tag} {mode}: other variables are untouched", v["keep"], "x")
        setup = verify.code_of(wf["nodes"]["setup"])
        v = {next(x["name"] for x in spec["call_variables"] if x["role"] == "now"): "2026-10-14T11:00", "old": MARK + "{"}
        exec(setup, {"vars": v})
        check(f"{tag} {mode}: a code node removes the marker too", MARK in v["old"], False)
check("scrubbed() does not add the scrub twice", codegen.scrubbed(codegen.scrubbed("x = 1\n")).count(codegen.SCRUB), 1)
check("scrubbed() leaves an empty hook empty", codegen.scrubbed(""), "")

# ---------------------------------------------------------------- 2. the look-alike guard keeps an explicit request
SPEC_A = SPECS[0][1]
g = generate.Gen(SPEC_A, TOOLS, "v1")
by_id = {x["id"]: x for x in SPEC_A["situations"]}
text = g.guard(by_id["restructuring"])
check("the guard says a message that also asks for it IS it", "it IS this, even if it also says they cannot pay" in text, True)
check("the guard names the SPEC's evidence words as examples", "'instal'" in text or "'lower'" in text, True)
check("the guard still names the look-alikes", "is, by itself, NOT this" in text, True)
no_words = json.loads(json.dumps(SPEC_A))
for x in no_words["situations"]:
    x.pop("evidence_words", None)
text = generate.Gen(no_words, TOOLS, "v1").guard({x["id"]: x for x in no_words["situations"]}["restructuring"])
check("without evidence words the rule stands, with no example list", ("it IS this" in text, "words like" in text), (True, False))
check("an offer situation carries no guard", g.guard(by_id["hardship"]), "")
wf = generate.build(SPEC_A, TOOLS, "v1")
task = wf["nodes"]["negotiate_1"]["task_message"]
check("v1: the situation list says the customer does not have to repeat an explicit request", "the customer does not have to repeat it" in task, True)
tool = next(t for t in wf["nodes"]["negotiate_1"]["transitions"] if "restructuring" in t["target_node"])
check("v1: the restructuring exit's own description keeps the explicit request", "it IS this" in tool["condition"]["description"], True)
wf = generate.build(SPEC_A, TOOLS, "orch")
kind = {e["name"]: e for e in wf["nodes"]["negotiate"]["extraction_schema"]}["reply_kind"]["description"]
check("orch: the classifier says cannot-pay plus an explicit request is the situation", "AND asks in so many words" in kind, True)

# ---------------------------------------------------------------- 3. a question about the open offer
PUB06 = [{"product_id": "p1", "type": "credit_card", "card_last4": "1903", "past_due": 2125.10, "days_late": 12, "minimum_payment": 637.50}]
c = Call(SPEC_A, TOOLS, PUB06, mode="orch")
c.say("too_much", "That is too much money for me to pay right now.")
offer = c.v["say_text"]
check("too much: the floor is offered with the SPEC's sentence", ("637.50" in offer, SPEC_A["amounts"]["too_much"]["say"] in offer), (True, True))
node = c.say("question", "How much is the minimum payment?")
check("a question about it goes to the answering node", node, "negotiate_q")
check("after the answer the offer is not said again", c.v["say_text"], "Does that work for you?")
check("the answer is told not to offer the amount again", "do not offer it again" in c.v["say_instr"], True)
c.say("propose", "I can pay the minimum this Friday.", day="this Friday", amount="the minimum")
c.say("accept", "Yes, I confirm.")
promises = [b for t, b in c.calls if t == "create_promise"]
check("the promise is still the floor on Friday", [(b.get("amount"), b.get("date")) for b in promises], [(637.5, "2026-10-16")])

# the floor offered for today, the customer names Friday: the read-back is her promise, not a second offer
# (orch PUB-06, rep 2: "So that is 637.50 ... on Friday" was counted as a second floor offer without the note)
c = Call(SPEC_A, TOOLS, PUB06, mode="orch")
c.say("too_much", "That is too much.")
c.say("propose", "This Friday.", day="this Friday")
check("the read-back after a new day is worded as her promise", c.v["say_text"],
      "Let me read your promise back: you will pay 637.50 for your credit card ending 1903 on Friday 16 October 2026. Do you confirm?")
check("v1: the read-back is worded as the customer's promise, never as a new offer",
      "never as a new offer" in generate.build(SPEC_A, TOOLS, "v1")["nodes"]["negotiate_1"]["task_message"], True)

# a question when the last sentence was not the open offer: the offer is said after the answer
c = Call(SPEC_A, TOOLS, PUB06, mode="orch")
c.say("propose", "I can pay 700.", amount="700")
asked = c.v["say_text"]
c.say("question", "Why do you need a day?")
check("a question after 'on which day' repeats the open question, not the short re-ask", (asked.startswith("On which day"), c.v["say_text"] != "Does that work for you?"), (True, True))

# ---------------------------------------------------------------- 4. corrections and a no to today
ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
for said, want in (("two hundred, sorry, two fifty", 250.0), ("I can do 150, no actually 200", 200.0), ("150", 150.0),
                   ("I'd rather pay 100", 100.0), ("637.50", 637.5), ("make that 300", 300.0), ("no amount here", None)):
    check(f"amount {said!r}", ns["parse_amount"](said), want)
cfg = codegen.date_config(SPEC_A)
WED = dt.date(2026, 10, 14)
for said, want in (("right now I can't, maybe Friday", "2026-10-16"), ("today I cannot but tomorrow is fine", "2026-10-15"),
                   ("I can pay right now", "2026-10-14"), ("yes, today works", "2026-10-14"), ("today", "2026-10-14"), ("not today", "")):
    check(f"day {said!r}", ns["resolve_spoken_date"](said, WED, cfg)["date"], want)

# ---------------------------------------------------------------- 5. the Reworder never leaves "recorded" silently
import asyncio, copy
from builder import extract


class T:
    def __init__(self): self.lines = []
    def event(self, kind, text): self.lines.append((kind, text))


def run_reword(replies, sentence):
    """reword_pre_success with a fake model that gives `replies` in turn; -> (the sentence after, the trace lines)."""
    it = iter(replies)
    async def fake(system, prompt, purpose, trace=None, **kw):
        r = next(it)
        if isinstance(r, Exception): raise r
        return {"sentence": r}
    old, extract.ask_json = extract.ask_json, fake
    try:
        spec = copy.deepcopy(SPEC_A)
        spec["opening"]["first_sentence"] = sentence
        t = T()
        asyncio.run(extract.reword_pre_success(spec, t))
        return spec["opening"]["first_sentence"], t.lines
    finally:
        extract.ask_json = old


NOTICE = "Hello, this is the bank's digital assistant, and this call is recorded."
s, lines = run_reword(["Hello, this is the bank's digital assistant, and this call is being recorded.", "Hello, I am the bank's assistant, and we record this call."], NOTICE)
check("a rewording that keeps the word is sent back once, the second one is used", s, "Hello, I am the bank's assistant, and we record this call.")
s, lines = run_reword(["... this call is being recorded.", "... this call is recorded."], NOTICE)
check("two failed rewordings: the notice is put in the active voice by rule", s, "Hello, this is the bank's digital assistant, and we record this call.")
check("the rule's rewording is in the trace", any(k == "spec" and "reworded" in x for k, x in lines), True)
s, lines = run_reword([extract.LLMError("no reply"), extract.LLMError("no reply")], NOTICE)
check("no model answer at all: the rule still rewords the notice", s, "Hello, this is the bank's digital assistant, and we record this call.")
s, lines = run_reword(["Your payment is saved.", "Your payment is saved."], "Your payment is saved.")
check("a sentence the rule cannot fix stays, with a warning in the trace", (s, any(k == "warning" for k, x in lines)), ("Your payment is saved.", True))
for said, want in (("Calls are recorded for quality.", "We record calls for quality."), ("Hello. This conversation is monitored and recorded.", "Hello. We monitor and record this conversation."),
                   ("Your promise is recorded.", "Your promise is recorded.")):
    check(f"by rule: {said!r}", extract.reword_by_rule(said), want)

print(f"\n{'all good' if not fails else f'{fails} failure(s)'}")
sys.exit(1 if fails else 0)
