"""Generator tests that need no platform: build the workflow from the reference SPECs and check mechanisms.

    python dev/test_generate.py

- identity: declines are counted in code (node id_count) with a turn guard, and the call closes on the SPEC's count;
- call-ending / transferring situations carry the look-alike guard, offers and product situations do not;
- orch: a refusal with a question is decided as usual and the question is answered too (asks_question).
"""
import json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import generate, verify
from builder.ingest import parse_openapi

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got}" + ("" if ok else f"   (want {want})"))


def code(node):
    return node["pre_actions"][0]["function"]["parameters"]["properties"]["code"]["default"]


def run_node(node, vars_):
    env = {"vars": dict(vars_)}
    exec(code(node), env)
    return env["vars"]


def route(node, vars_):
    """The first transition whose equals-condition holds (the generator's code-node transitions are equals or always)."""
    for t in node["transitions"]:
        c = t["condition"]
        if c.get("operator") == "always":
            return t["target_node"]
        if any(str(vars_.get(x["variable"])) == x["operand"] for x in c["conditions"]):
            return t["target_node"]


tools = parse_openapi(str(KIT / "tools/openapi.json"))["tools"]
for spec_name in ("brief-a", "brief-ab"):
    spec = json.loads((KIT / f"dev/specs/{spec_name}.json").read_text(encoding="utf-8"))
    for mode in ("v1", "orch"):
        wf = generate.build(spec, tools, mode)
        tag = f"{spec_name} {mode}"
        check(f"{tag} lint", verify.lint(wf, spec, tools), [])
        check(f"{tag} snippets", verify.run_snippets(wf, spec), [])

        # identity: decline counting
        idn, idc = wf["nodes"]["identity"], wf["nodes"]["id_count"]
        mx = spec["identity"]["decline"]["max_declines"]
        check(f"{tag} identity routes a decline to id_count", any(t["target_node"] == "id_count" for t in idn["transitions"]), True)
        check(f"{tag} identity has no model-driven decline exit",
              any(t.get("is_tool_call") and "declined" in t["target_node"] for t in idn["transitions"]), False)
        v = {"id_declines": "0", "id_decline_turn": "", "identity.total_turns": 4, "id_reply": "decline"}
        v = run_node(idc, v)
        check(f"{tag} first decline: counted, back to identity", (v["id_declines"], route(idc, v)), ("1", "identity"))
        check(f"{tag} id_reply consumed", v["id_reply"], "unclear")
        v = run_node(idc, dict(v, id_reply="decline"))           # same turn again (extractor re-read): not counted twice
        check(f"{tag} same turn counted once", v["id_declines"], "1")
        v = run_node(idc, dict(v, **{"identity.total_turns": 6, "id_reply": "decline"}))
        check(f"{tag} decline {mx} closes the call", (v["id_declines"], route(idc, v).startswith("set_identity_declined")), (str(mx), True))
        check(f"{tag} explanation from the SPEC in the prompt", spec["identity"]["decline"]["explanation"] in idn["task_message"], True)

        # look-alike guard on situations that end or transfer the call
        g = generate.Gen(spec, tools, mode).guard
        by_id = {x["id"]: x for x in spec["situations"]}
        for sid, want in (("restructuring_request", True), ("human_request", True), ("hardship", False), ("already_paid", False)):
            if sid in by_id:
                check(f"{tag} guard on {sid}", bool(g(by_id[sid])), want)
        if mode == "orch":
            ex = {e["name"]: e for e in wf["nodes"]["negotiate"]["extraction_schema"]}
            check(f"{tag} asks_question extracted", ex.get("asks_question", {}).get("enum_values"), ["yes", "no"])
            check(f"{tag} reply_kind no longer says situations always win", "choose it over the others" in ex["reply_kind"]["description"], False)
            ne = code(wf["nodes"]["neg_eval"])
            check(f"{tag} neg_eval answers a question next to a refusal", "asks_question" in ne and "neg_error" in ne, True)
        # the transfer farewell says "connecting" once
        for name, n in wf["nodes"].items():
            if name.startswith("set_") and "transfer" in json.dumps(spec["situations"]):
                f = run_node(n, {})["farewell"].lower() if n.get("node_type") == "code" else ""
                if f.count("connect") > 1:
                    check(f"{tag} {name} farewell says connect once", f, "one 'connect'")


# ---- group C: SPEC variants another bank could have (copies of the reference SPECs, changed in one place each)
import copy
base = json.loads((KIT / "dev/specs/brief-ab.json").read_text(encoding="utf-8"))
ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + __import__("builder.codegen", fromlist=["x"]).snippet("dates") + "\n"
     + __import__("builder.codegen", fromlist=["x"]).snippet("negotiation"), ns)


def hook(wf, which):
    t = wf["nodes"]["identity"]["tools"][0]
    return t["pre_process_code"] if which == "pre" else t["post_process_code"]


def verify_call(wf, vars_, field, verified, data_extra=None):
    """Run the verify tool's pre-hook and post-hook like the engine does, with a result from the bank."""
    fv = wf["_tf"]
    body = {fv["field"]: field, fv["answer"]: "x"}
    exec(hook(wf, "pre"), {"config": {"body": body}, "vars": vars_})
    data = {"ok": True, "verified": verified}
    data.update(data_extra or {})
    res = {"data": data}
    exec(hook(wf, "post"), {"result": res, "vars": vars_, "json": json})
    return res["data"]["what_to_do_next"]


# C11: the verify API has no "all verified" and no "wrong answers left" field: code counts both from the SPEC
s11 = copy.deepcopy(base)
s11["identity"]["result_fields"]["all_verified"] = ""
s11["identity"]["result_fields"]["wrong_left"] = ""
wf = generate.build(s11, tools, "v1"); wf["_tf"] = s11["tool_fields"]["verify_identity"]
check("C11 lint without all_verified/wrong_left", verify.lint(wf, s11, tools), [])
qf = [q["field"] for q in s11["identity"]["questions"]]
v = {}
m1 = verify_call(wf, v, qf[0], True)
check("C11 first answer right: not all verified yet", (v.get("id_all_ok"), "next security question" in m1), (None, True))
m2 = verify_call(wf, v, qf[1], True)
check("C11 second answer right: all verified by code", (v.get("id_all_ok"), "All answers are verified" in m2), ("true", True))
check("C11 identity routes on id_all_ok", any(c["variable"] == "id_all_ok" for t in wf["nodes"]["identity"]["transitions"]
                                               if t["target_node"] == "load_account" for c in t["condition"]["conditions"]), True)
v = {}
for _ in range(int(s11["identity"]["max_wrong_total"])):
    m = verify_call(wf, v, qf[0], False)
check("C11 wrong answers counted to the SPEC's limit", (v.get("id_left"), "check has ended" in m), ("0", True))
check("C11 no response mapping to a missing field", wf["nodes"]["identity"]["tools"][0]["response_mapping"], [])
# and with the fields present, the API's own values are used (reference behaviour unchanged)
wfa = generate.build(base, tools, "v1"); wfa["_tf"] = base["tool_fields"]["verify_identity"]
v = {}
m = verify_call(wfa, v, qf[0], True, {"all_verified": True, "wrong_answers_left": 3})
check("C11 API all_verified=true is trusted", (v.get("id_all_ok"), "All answers are verified" in m), ("true", True))

# C12: amount rules other than the common ladder reach the agent (percent first offer, accept from 50 %)
s12 = copy.deepcopy(base)
s12["amounts"]["first_offer"] = {"kind": "percent_of_full", "percent": 80}
s12["amounts"]["accept_min"] = {"kind": "percent_of_full", "percent": 50}
for mode in ("v1", "orch"):
    wf = generate.build(s12, tools, mode)
    check(f"C12 {mode} lint", verify.lint(wf, s12, tools), [])
    pd = wf["nodes"]["prepare_deal"]
    vv = {"acct_items": [{"product_id": "p1", "type": "personal_loan", "past_due": 1000, "days_late": 20, "instalment_amount": 300}], "now": "2026-10-14T11:00"}
    out = run_node(pd, vv)
    plan = json.loads(out["neg_plan"])[0]
    check(f"C12 {mode} plan amounts from the SPEC", (plan["first"], plan["lo"], plan["hi"], plan["tm"]), (800.0, 500.0, 1000.0, 300.0))
    check(f"C12 {mode} FACTS name the product's amount rules", "AMOUNT RULES" in out["deal_facts"] and "800.00" in out["deal_facts"], True)
    if mode == "v1":
        check("C12 v1 prompt points to the FACTS amounts", "AMOUNT RULES in the FACTS" in wf["nodes"]["negotiate_1"]["task_message"], True)
cfg12 = dict(ns["json"].loads("{}"))
# the state machine uses them: 400 is below the 50 % minimum -> below-minimum path; 600 is accepted
from builder import codegen as CG
c = CG.date_config(s12)
c.update({"too_much_say": "", "below_min_say": "Too low.", "exhausted_note": "refused", "confirm_question": "Do you confirm?",
          "floor_refused_is_flat": True, "vague_asks": 1, "vague_then": "propose_deadline", "product_situations": {}})
plan = [{"name": "personal loan", "full": 1000.0, "floor": 300.0, "first": 800.0, "lo": 500.0, "hi": 1000.0, "tm": 300.0, "bm": 500.0,
         "today": "2026-10-14", "deadline": "2026-10-23", "ladder": [], "spoken": {"2026-10-16": "Friday 16 October 2026", "2026-10-14": "Wednesday 14 October 2026"}}]
st = ns["new_state"](plan)
check("C12 first offer is 80 %", st["p"][0]["offer_amt"], 800.0)
st, say, nxt = ns["step"](st, {"kind": "propose", "day": "Friday", "amount": "400"}, plan, __import__("datetime").date(2026, 10, 14), c)
check("C12 400 is below the minimum -> offer 500", ("Too low." in say, "500.00" in say), (True, True))
st = ns["new_state"](plan)
st, say, nxt = ns["step"](st, {"kind": "propose", "day": "Friday", "amount": "600"}, plan, __import__("datetime").date(2026, 10, 14), c)
check("C12 600 accepted", (st["p"][0]["status"], st["p"][0]["amt"]), ("agreed", 600.0))
# the reference SPEC keeps the old prompt wording (no regression for A/B)
check("C12 reference SPEC prompt unchanged", "Start with the full past-due amount." in generate.build(base, tools, "v1")["nodes"]["negotiate_1"]["task_message"], True)

# C13: a situation whose effect is a callback asks for a time, checks it in code and books it
s13 = copy.deepcopy(base)
s13["situations"].append({"id": "busy_now", "trigger": "The customer says they are busy and asks to be called later.", "not_this": "",
                          "stages": ["negotiation"], "say": "", "say_exact": False, "guidance": "", "first_response": "", "threshold": 1,
                          "suppresses_persuasion": True, "priority": 1, "proposal_still_handled": False, "scope": "call",
                          "effect": {"actions": [{"type": "callback"}], "outcome": s13["third_party"]["callback"]["scheduled"]["outcome"],
                                     "reason": s13["third_party"]["callback"]["scheduled"]["reason"]}, "source": "test"})
for mode in ("v1", "orch"):
    wf = generate.build(s13, tools, mode)
    check(f"C13 {mode} lint", verify.lint(wf, s13, tools), [])
    check(f"C13 {mode} snippets", verify.run_snippets(wf, s13), [])
    names = set(wf["nodes"])
    check(f"C13 {mode} callback chain built", {"cb_busy_now0", "cb_busy_now0_check", "cb_busy_now0_book"} <= names, True)
    book = wf["nodes"]["cb_busy_now0_book"]
    check(f"C13 {mode} booked -> the situation's outcome", any(t["target_node"] == "set_busy_now" for t in book["transitions"]), True)

# C14: one date past a product's deadline: the SPEC decides between "own deadline" and "offer it first"
s14 = copy.deepcopy(base)
s14["multi_product"]["one_date_clamped_per_product"] = False
check("C14 v1 prompt follows the SPEC flag", "goes on its OWN deadline" in generate.build(s14, tools, "v1")["nodes"]["negotiate_2"]["task_message"], False)
check("C14 v1 reference keeps the rule", "goes on its OWN deadline" in generate.build(base, tools, "v1")["nodes"]["negotiate_2"]["task_message"], True)
c14 = dict(c, one_date_clamped=False)
p2 = [{"name": "credit card", "full": 300.0, "floor": 90.0, "today": "2026-10-14", "deadline": "2026-11-02", "ladder": [], "spoken": {}},
      {"name": "personal loan", "full": 900.0, "floor": 300.0, "today": "2026-10-14", "deadline": "2026-10-23", "ladder": [], "spoken": {}}]
st = ns["new_state"](p2)
st, say, nxt = ns["step"](st, {"kind": "propose", "day": "the 30th of October", "about": "both"}, p2, __import__("datetime").date(2026, 10, 14), c14)
check("C14 not clamped: the loan's late date is offered first", (st["p"][1]["status"], st["p"][1]["clamped"], "personal loan" in say), ("open", False, True))
st = ns["new_state"](p2)
st, say, nxt = ns["step"](st, {"kind": "propose", "day": "the 30th of October", "about": "both"}, p2, __import__("datetime").date(2026, 10, 14), dict(c, one_date_clamped=True))
check("C14 clamped (reference): loan on its own deadline", (st["p"][1]["status"], st["p"][1]["date"]), ("agreed", "2026-10-23"))


# ---- SPEC switches that were unused (each tested on a copy of brief-ab with one switch changed)
import datetime as _dtm
D14 = _dtm.date(2026, 10, 14)
TWO = [{"product_id": "p1", "type": "personal_loan", "past_due": 900, "days_late": 20, "instalment_amount": 300},
       {"product_id": "p2", "type": "car_loan", "past_due": 400, "days_late": 20, "instalment_amount": 100}]


def orch_env(spec, products=TWO):
    """The orch generator's own state-machine config and the plan its prepare_deal node builds."""
    g = generate.Gen(spec, tools, "orch")
    wf = g.build()
    c = g.cfg(**g.neg_cfg(), call_situations={}, turn_nodes=[])
    v = run_node(wf["nodes"]["prepare_deal"], {"acct_items": products, "now": "2026-10-14T11:00"})
    return wf, c, json.loads(v["neg_plan"]), v


def talk(spec, turns, products=TWO):
    wf, c, plan, v = orch_env(spec, products)
    st, says, nxt = ns["new_state"](plan), [], "talk"
    for ev in turns:
        st, say, nxt = ns["step"](st, dict({"kind": "unclear", "day": "", "amount": "", "about": ""}, **ev), plan, D14, c)
        says.append(say)
    return st, says, nxt, v


def variant(**changes):
    s = copy.deepcopy(base)
    for path, value in changes.items():
        node = s
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return s


def lint_both(tag, s):
    for mode in ("v1", "orch"):
        wf = generate.build(s, tools, mode)
        check(f"{tag} {mode} lint", verify.lint(wf, s, tools), [])
        check(f"{tag} {mode} snippets", verify.run_snippets(wf, s), [])


# the negotiation situation that transfers the call without an offer (its id differs between SPECs)
RX = next(x["id"] for x in base["situations"] if "negotiation" in x["stages"] and not x.get("offer")
          and any(a["type"] == "transfer" for a in x["effect"]["actions"]) and x["threshold"] <= 1)

# F1 outcomes.transfer_after_promise: a promise recorded before the transfer decides the outcome when the SPEC says so
s = variant(outcomes__transfer_after_promise="promise_wins")
lint_both("F1", s)
for mode in ("v1", "orch"):
    ex = generate.build(s, tools, mode)["nodes"][f"set_{RX}"]
    a = run_node(ex, {"n_products": "2", "res_1": "promise", "res_2": "none"})
    b = run_node(ex, {"n_products": "2", "res_1": "none", "res_2": "none"})
    check(f"F1 {mode} promise before transfer -> promise", a["outcome"], s["outcomes"]["promise"]["outcome"])
    check(f"F1 {mode} no promise -> transferred", b["outcome"], next(x for x in s["situations"] if x["id"] == RX)["effect"]["outcome"])
ex = generate.build(base, tools, "v1")["nodes"][f"set_{RX}"]
check("F1 reference (transfer_wins) keeps transferred", run_node(ex, {"n_products": "1", "res_1": "promise"})["outcome"], "transferred")

# F2 multi_product.unrecorded_on_transfer = record: agreed promises are recorded before the transfer
s = variant(multi_product__unrecorded_on_transfer="record")
lint_both("F2", s)
wf = generate.build(s, tools, "orch")
tgt = [t["target_node"] for t in wf["nodes"]["neg_eval"]["transitions"] if "sit_" + RX in json.dumps(t["condition"])]
check("F2 orch restructuring goes through a record chain first", tgt, [f"rx_{RX}_gate_1"])
check("F2 orch record chain ends in the transfer", any(t["target_node"].startswith(f"do_{RX}") for t in wf["nodes"][f"rx_{RX}_gate_3"]["transitions"]), True)
ne = run_node(wf["nodes"]["neg_eval"], {"neg_plan": json.dumps(orch_env(s)[2]), "reply_kind": RX, "negotiate.total_turns": 3,
                                         "nst": json.dumps({"phase": "offer", "cursor": 1, "pending_amount": None, "sit": {},
                                                            "p": [{"status": "agreed", "amt": 900.0, "date": "2026-10-16", "attempt": 1, "too_much": False, "floor_offered": False,
                                                                   "vague_asks": 0, "below_asks": 0, "offer_amt": 900.0, "offer_date": "2026-10-16", "note": "", "clamped": False},
                                                                  {"status": "open", "amt": None, "date": None, "attempt": 0, "too_much": False, "floor_offered": False,
                                                                   "vague_asks": 0, "below_asks": 0, "offer_amt": 400.0, "offer_date": "2026-10-14", "note": "", "clamped": False}]})})
check("F2 orch the agreed promise is marked for recording", (ne["neg_next"], ne.get("res_1"), ne.get("p1_amt")), ("sit_" + RX, "pending", "900.00"))
check("F2 v1 prompt records before the transfer", "Before that, CALL the create_promise tool" in generate.build(s, tools, "v1")["nodes"]["negotiate_2"]["task_message"], True)
check("F2 reference (drop) has no record chain", any(k.startswith("rx_") for k in generate.build(base, tools, "orch")["nodes"]), False)

# F3 notes.for_each_product_without_promise = false: no note for used-up attempts; finalize still knows why
s = variant(notes__for_each_product_without_promise=False)
lint_both("F3", s)
wf = generate.build(s, tools, "orch")
g1 = run_node(wf["nodes"]["pnote_1"], {"n_products": "2", "res_1": "open", "p1_note_reason": "refused", "p1_end_why": "exhausted"})
check("F3 orch used-up product gets no note, keeps its reason", (g1["note_go"], g1["p1_end_reason"]), ("no", "refused"))
g2 = run_node(wf["nodes"]["pnote_1"], {"n_products": "2", "res_1": "open", "p1_note_reason": "dispute", "p1_end_why": "situation"})
check("F3 orch a situation still writes its note", g2["note_go"], "yes")
g3 = run_node(generate.build(base, tools, "orch")["nodes"]["pnote_1"], {"n_products": "2", "res_1": "open", "p1_note_reason": "refused", "p1_end_why": "exhausted"})
check("F3 reference still notes a used-up product", g3["note_go"], "yes")
# three products: refused without a note, dispute, paid -> the first product not matching the paid rule decides (product order)
fin = run_node(wf["nodes"]["finalize"], {"n_products": "3", "res_1": "ended", "p1_end_reason": "refused", "note1_saved": "",
                                         "res_2": "note", "note2_saved": "dispute", "res_3": "note", "note3_saved": "paid"})
check("F3 finalize: refused (no note) + dispute + paid", (fin["outcome"], fin["reason"]), ("no_promise", "refused"))
fin = run_node(wf["nodes"]["finalize"], {"n_products": "2", "res_1": "note", "note1_saved": "paid", "res_2": "ended", "p2_end_reason": "refused"})
check("F3 finalize: paid + refused (no note) is not all paid", (fin["outcome"], fin["reason"]), ("no_promise", "refused"))
v1t = generate.build(s, tools, "v1")["nodes"]["negotiate_2"]["task_message"]
check("F3 v1 prompt: no note for used-up attempts", "attempts were used up gets NO note" in v1t and "or no promise after its attempts" in v1t, True)

# F4 multi_product.single_read_back = false: each promise is read back when it is agreed, recorded at the end
s = variant(multi_product__single_read_back=False)
lint_both("F4", s)
st, says, nxt, _ = talk(s, [{"kind": "refuse"}, {"kind": "accept"}, {"kind": "accept"}, {"kind": "accept"}, {"kind": "accept"}])
check("F4 read-back of product 1 alone", says[1].count(" for your ") == 1 and "personal loan" in says[1] and s["confirmation"]["question"] in says[1], True)
check("F4 then product 2 is offered", "car loan" in says[2] and "?" in says[2], True)
check("F4 read-back of product 2 alone, then record", (says[3].count(" for your "), "car loan" in says[3], nxt), (1, True, "record"))
check("F4 v1 prompt reads back each promise alone", "read back" in generate.build(s, tools, "v1")["nodes"]["negotiate_2"]["task_message"]
      and "of that promise alone" in generate.build(s, tools, "v1")["nodes"]["negotiate_2"]["task_message"], True)

# F5 multi_product.state_all_first = false: the first product only, each next one stated when it is reached
s = variant(multi_product__state_all_first=False)
lint_both("F5", s)
st, says, nxt, v = talk(s, [{"kind": "refuse"}, {"kind": "refuse"}, {"kind": "refuse"}])
check("F5 opening states product 1 only", ("personal loan" in v["deal_intro"], "car loan" in v["deal_intro"]), (True, False))
check("F5 product 2 is stated when it is reached, with the today question",
      says[2].startswith(json.loads(v["neg_plan"])[1]["statement"]) and s["negotiation"]["first_ask"] in says[2], True)
check("F5 v1 FACTS carry each Statement", "Statement (say it when you start this product)" in v["deal_facts"], True)

# F6 multi_product.ask_all_today_once = false: all stated, "today" asked per product
s = variant(multi_product__ask_all_today_once=False)
lint_both("F6", s)
st, says, nxt, v = talk(s, [{"kind": "accept"}, {"kind": "refuse"}])
check("F6 opening states all, asks about product 1", ("car loan" in v["deal_intro"], "Let us start with your personal loan" in v["deal_intro"]), (True, True))
check("F6 yes to product 1 today agrees product 1 only", (st["p"][0]["status"], st["p"][0]["date"], st["p"][1]["status"]), ("agreed", "2026-10-14", "open"))
check("F6 product 2 asked about today", "car loan today?" in says[0], True)
check("F6 a no to today is not an attempt", (st["p"][1]["attempt"], "Friday 16 October 2026" in says[1]), (1, True))

# F7 multi_product.attempts_per_product = false: attempts for the whole call (call_attempt_limit, else the band limit)
s = variant(multi_product__attempts_per_product=False, negotiation__call_attempt_limit=1)
lint_both("F7", s)
st, says, nxt, _ = talk(s, [{"kind": "refuse"}, {"kind": "refuse"}])
check("F7 limit 1: one attempt in the whole call, then close", (nxt, [x["attempt"] for x in st["p"]], st["used"]), ("close", [1, 0], 1))
s0 = variant(multi_product__attempts_per_product=False)
st, says, nxt, _ = talk(s0, [{"kind": "refuse"}] * 4)
check("F7 no limit given: the band's 2 attempts are the call's total", ([x["attempt"] for x in st["p"]], st["used"], nxt), ([2, 0], 2, "close"))
check("F7 v1 prompt names the call limit", "at most 1 in the whole call" in generate.build(s, tools, "v1")["nodes"]["negotiate_2"]["task_message"], True)
st, says, nxt, _ = talk(base, [{"kind": "refuse"}] * 5)
check("F7 reference: attempts per product", [x["attempt"] for x in st["p"]], [2, 2])

# F8 situations[].say_exact: an offer whose words the brief prescribes is said by the engine
s = copy.deepcopy(base)
h = next(x for x in s["situations"] if x["id"] == "hardship")
h["say_exact"] = True
h["say"] = h["say"] or "I am sorry to hear that."
lint_both("F8", s)
for mode in ("v1", "orch"):
    o = generate.build(s, tools, mode)["nodes"]["offer_hardship"]
    check(f"F8 {mode} exact offer is spoken by TTS", (o["on_enter"]["type"], h["say"] in o["on_enter"]["text"], h["offer"]["question"] in o["on_enter"]["text"]), ("tts", True, True))
check("F8 reference offer stays llm", generate.build(base, tools, "v1")["nodes"]["offer_hardship"]["on_enter"]["type"], "llm")


# A situation's note action (e.g. not wanting to talk, with notes on): no note before identity (no account yet);
# after identity one note per product without a promise, then the situation's own exit
s = copy.deepcopy(base)
nt = next(x for x in s["situations"] if x["scope"] == "call" and "identity" in x["stages"] and "negotiation" in x["stages"]
          and not x.get("offer") and not any(a["type"] == "transfer" for a in x["effect"]["actions"]))
nt["effect"]["actions"] = [{"type": "note", "note_reason": "refused"}]
lint_both("note action", s)
for mode in ("v1", "orch"):
    wf = generate.build(s, tools, mode)
    before = [t["target_node"] for t in wf["nodes"]["identity"]["transitions"] if nt["id"] in t["target_node"]]
    check(f"note action {mode}: before identity straight to the exit, no note", all(t.startswith("set_") for t in before) and bool(before), True)
    chain = sorted(k for k in wf["nodes"] if k.startswith(f"do_{nt['id']}") and "_note" in k and not k.endswith("_call"))
    check(f"note action {mode}: one gate per product after identity", len(chain), int(s["account"]["max_products"]))
    last = wf["nodes"][chain[-1]]
    check(f"note action {mode}: the chain ends in the situation's exit", any(t["target_node"].startswith("set_") for t in last["transitions"]), True)
    g = run_node(wf["nodes"][chain[0]], {"n_products": "2", "res_1": "promise"})
    check(f"note action {mode}: a product with a promise gets no note", g["note_go"], "no")

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
