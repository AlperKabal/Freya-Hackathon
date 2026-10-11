"""The thirteen practice customers without the platform: each one's script, played through the agent the builder
generates, and the bank records scored with the kit's own tools/score.py.

    python dev/walk_practice.py                      # Brief A customers on dev/specs/brief-a.json, Brief B on brief-ab.json
    python dev/walk_practice.py --spec-a out/x.spec.json --spec-ab out/y.spec.json    # on SPECs the builder extracted
    python dev/walk_practice.py --only PUB-08 -v     # one customer: every spoken fixed line, and the ledger

Two seconds instead of a simulation, so it can run after every change. It checks what code decides: the records
(the scorer's part of a pass), the fixed sentences the judge's checks name, and what must hold in every call. It
cannot check what the phone model says or how it classifies a reply: a customer's turn is given here as what the
extraction would write. A pass here is needed for a pass on the platform; it is not one.
"""
import argparse, json, pathlib, sys, traceback
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev")); sys.path.insert(0, str(KIT / "dev" / "mock_briefs")); sys.path.insert(0, str(KIT / "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import lib
from lib import Customer, day
from builder.ingest import parse_openapi
from run_mock_briefs import situation_map, translate
from score import score_ledger

PUBLIC = {c["id"]: c for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}
YES = [("neg", Customer("accept"))]


def scripts(spec):
    """PUB id -> (steps, sentences that must be said, sentences said exactly once, tool -> number of calls)."""
    ok = lambda cid, said=None: lib.verified(lib.Box("x", spec, {}), PUBLIC[cid]["identity"], said)
    by = {x["id"]: x for x in spec["situations"]}
    paid = by.get("already_paid", {}).get("say", "")
    return {
        "PUB-01": (ok("PUB-01", {"date_of_birth": "14 March 1988"}) + YES, [spec["recording"]["after_success_say"]], [], {"create_promise": 1, "get_account": 1}),
        "PUB-02": ([("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow morning around eleven"})], [], [], {"verify_identity": 0, "get_account": 0, "schedule_callback": 1}),
        "PUB-03": ([("who", "confirmed"), ("id", "date_of_birth", "12 July 1991", "1991-07-12"), ("id", "date_of_birth", "21 August 1992", "1992-08-21"),
                    ("id", "date_of_birth", "21 July 1990", "1990-07-21")], [spec["identity"]["on_failed"]["say"]], [], {"get_account": 0, "verify_identity": 3}),
        "PUB-04": (ok("PUB-04") + [("neg", Customer({"kind": "propose", "day": "the 6th of November", "said": "My salary arrives on 6 November, I can pay then."},
                                                     then=[{"kind": "question", "said": "Am I talking to a robot?", "question": "yes"}, "accept"]))],
                   ["Friday 23 October 2026"], [], {"create_promise": 1}),
        "PUB-05": (ok("PUB-05") + [("neg", Customer({"kind": "hardship", "said": "I lost my job last month and cannot pay anything."}, offer="decline"))], [], [],
                   {"transfer_to_agent": 0, "create_promise": 0}),
        "PUB-06": (ok("PUB-06") + [("neg", Customer({"kind": "too_much", "said": "That is too much for me right now."},
                                                     then=[{"kind": "propose", "day": "this Friday", "amount": "the minimum", "said": "I can pay the minimum this Friday."}]))],
                   [], [spec["amounts"]["too_much"]["say"]], {"create_promise": 1}),
        "PUB-07": (ok("PUB-07") + [("neg", Customer({"kind": "vague", "day": "the week after next", "said": "I can't today. The week after next."},
                                                     then=[{"kind": "propose", "day": "Monday the 26th", "said": "Monday the 26th."}, "accept"]))],
                   ["Tuesday 27 October 2026"], [], {"create_promise": 1}),
        "PUB-08": (ok("PUB-08") + [("neg", Customer({"kind": "already_paid", "said": "I paid it in the app this morning."}))], [paid] if paid else [], [], {"create_promise": 0}),
        "PUB-09": (ok("PUB-09") + [("neg", Customer({"kind": "restructuring", "said": "I cannot pay this amount, I want lower instalments."}))], [], [],
                   {"transfer_to_agent": 1, "create_promise": 0}),
        "PUB-10": (ok("PUB-10") + [("neg", Customer({"kind": "propose", "day": "this Friday", "said": "I can't today, but I can pay the full amount this Friday."}))],
                   [spec["recording"]["after_success_say"]], [], {"create_promise": 2}),
        "PUB-11": (ok("PUB-11") + [("neg", Customer({"kind": "propose", "day": "this Friday", "about": "all three", "said": "I can't today. All three this Friday."}))],
                   [], [spec["confirmation"]["question"]], {"create_promise": 3}),
        "PUB-12": ([("who", "confirmed"), ("id", "date_of_birth", "19 October 1983", "1983-10-19"), ("id", "phone_last4", "4401", "4401"), ("id", "phone_last4", "4410", "4410"),
                    ("neg", Customer({"kind": "propose", "day": "tomorrow", "about": "the credit card", "said": "I will pay the credit card tomorrow."}, then=["refuse"]))],
                   [], [], {"create_promise": 1, "add_note": 2, "verify_identity": 3}),
        "PUB-13": (ok("PUB-13") + [("neg", Customer({"kind": "propose", "day": "30 October", "about": "both", "said": "I can't today. Both on 30 October."}))],
                   ["Friday 30 October 2026", "Friday 23 October 2026"], [], {"create_promise": 2}),
    }


def kit_ledger(bank):
    """The stand-in bank's records in the shape the kit's scorer reads."""
    led = bank.ledger()
    return {"outcome": led["outcome"], "reason": led["reason"], "promises": [{"product_id": p, "amount": a, "date": d} for p, a, d in led["promises"]],
            "notes": [{"product_id": p, "reason": r} for p, r in led["notes"]], "callbacks": [{"date": d, "time": t} for d, t in led["callbacks"]],
            "transfers": [{"queue": q} for q in led["transfers"]], "calls": [{"tool": t, "result": data} for t, body, data in bank.calls]}


def run(spec, tools, cid, mode="orch", verbose=False, reference=None):
    """One practice customer. Returns (problems, sim)."""
    pub = PUBLIC[cid]
    steps, said, once, calls = scripts(reference or spec)[cid]
    e = pub["expected"]
    c = lib.case(cid, pub["title"], pub["family"], pub["variables"]["now"], steps, e["outcome"], e["reason"],
                 promises=[(p["product_id"], p["amount"], p["date"]) for p in e["promises"]], notes=[(n["product_id"], n["reason"]) for n in e["notes"]],
                 callbacks=[(x["date"], x["time"]) for x in e["callbacks"]], transfers=[t["queue"] for t in e["transfers"]],
                 variables={k: v for k, v in pub["variables"].items() if k != "now"}, identity=pub["identity"], products=pub["products"],
                 faults={f["tool"]: f["fail_first_n"] for f in pub.get("faults") or []}, said=[s for s in said if s], once=[s for s in once if s], calls=calls)
    if reference is not None:
        c = translate(c, situation_map(reference, spec))
    box = lib.Box("practice", reference or spec, tools)
    bank = lib.Bank(reference or spec, tools, c["identity"], c["products"], c["faults"])
    sim = lib.play(lib.Sim(spec, tools, bank, mode, c["now"], c["variables"]), c)
    problems = lib.judge(box, c, sim)
    kit = score_ledger(pub, kit_ledger(bank))                    # the organisers' own reading of the records
    problems += [f"tools/score.py: {f}" for f in kit["failed"] if not any(f.split(",")[0].split(" ")[0] in p for p in problems)]
    return problems, sim


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec-a", default=str(KIT / "dev/specs/brief-a.json")); ap.add_argument("--spec-ab", default=str(KIT / "dev/specs/brief-ab.json"))
    ap.add_argument("--only"); ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    tools = parse_openapi(KIT / "tools/openapi.json")["tools"]
    load = lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    specs = {"A": load(a.spec_a), "B": load(a.spec_ab)}
    refs = {"A": load(KIT / "dev/specs/brief-a.json"), "B": load(KIT / "dev/specs/brief-ab.json")}
    failed = 0
    for cid, pub in PUBLIC.items():
        if a.only and cid not in a.only.split(","):
            continue
        spec = specs[pub["brief"]]
        try:
            problems, sim = run(spec, tools, cid, verbose=a.v, reference=None if spec == refs[pub["brief"]] else refs[pub["brief"]])
        except Exception:
            problems, sim = ["the walk raised: " + traceback.format_exc()[-600:]], None
        failed += bool(problems)
        tools_called = " > ".join(t.replace("verify_identity", "verify").replace("create_promise", "promise") for t in (sim.bank.ledger()["calls"] if sim else []))
        print(("PASS" if not problems else "FAIL") + f" {cid} [{pub['brief']}] {pub['title']:<48} {tools_called}")
        for p in problems:
            print("       - " + p[:400])
        if a.v and sim:
            for node, text in sim.said:
                print(f"         {node}: {text[:400]}")
    n = len([c for c in PUBLIC if not a.only or c in a.only.split(",")])
    print(f"\n{n - failed} / {n} practice customers leave the records the brief requires (the conversation itself is the platform's to judge)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
