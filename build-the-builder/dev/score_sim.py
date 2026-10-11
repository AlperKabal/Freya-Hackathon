"""Score a simulation that run_cases.py did not see to the end (it died while polling, or another tool started it).

    python dev/score_sim.py <simulation_id> [<simulation_id> ...] [--out results/x.json]

Each run's persona name starts with the practice case id; the customer id is read from the call's variables, the
bank's records from the practice ledger, and both are scored with the kit's own score_ledger; the judge's verdict comes
from the simulation's iteration, as in run_cases.py. Several simulations of the same agent give a per-case tally.
"""
import json, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
import freya
from score import http, score_ledger

CASES = {c["id"]: c for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}


def customer_of(call):
    for m in call.get("messages") or []:
        t = m.get("message") or ""
        if t.startswith("{") and '"variable_table"' in t:
            vt = json.loads(t).get("variable_table") or {}
            v = vt.get("customer_id")
            v = v.get("value") if isinstance(v, dict) else v
            if v:
                return v
    return None


def score(sim_id):
    s = freya.api("GET", f"/api/v2/simulations/{sim_id}"); s = s.get("simulation") or s
    if s.get("status") not in ("completed", "failed", "paused"):
        return s.get("status"), []
    its = freya.api("GET", f"/api/v2/simulations/{sim_id}/iterations"); its = its.get("iterations") or its.get("items") or its
    rows = []
    for r in freya.get_iteration(sim_id, its[0]["id"])["runs"]:
        name = str(r.get("personaName") or (r.get("persona") or {}).get("name") or "")
        cid = name.split()[0] if name else ""
        case = CASES.get(cid)
        row = {"id": cid, "judge": r.get("outcome"), "judge_reason": " ".join(str(r.get("reason") or "").split())[:300], "call_id": r.get("callId"), "failed": []}
        try:
            call = freya.get_call(r["callId"]) if r.get("callId") else {}
            cust = customer_of(call)
            if case and cust:
                led = http("/v1/practice/ledger/" + cust)
                row["failed"] = score_ledger(case, led)["failed"]
                row["tools"] = [x["tool"] for x in led["calls"]]
            else:
                row["failed"].append("no customer id or unknown case")
        except Exception as e:
            row["failed"].append(f"could not score: {str(e)[:120]}")
        if row["judge"] != "pass":
            row["failed"].append(f"conversation ({row['judge']}): {row['judge_reason']}")
        row["pass"] = not row["failed"]
        rows.append(row)
    return s.get("status"), sorted(rows, key=lambda x: x["id"])


def main():
    args = sys.argv[1:]
    out = None
    if "--out" in args:
        i = args.index("--out"); out = args[i + 1]; args = args[:i] + args[i + 2:]
    tally, all_rows = {}, {}
    for sim in args:
        status, rows = score(sim)
        print(f"== simulation {sim} ({status}): {sum(r['pass'] for r in rows)} / {len(rows)} passed")
        for r in rows:
            print(("PASS" if r["pass"] else "FAIL"), r["id"], "|", " > ".join(r.get("tools") or []))
            for f in r["failed"]:
                print("       -", f[:260])
            tally.setdefault(r["id"], []).append(r["pass"])
        all_rows[sim] = rows
    if len(args) > 1:
        print("\nper case over the simulations:", ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(tally.items())))
    if out:
        pathlib.Path(out).write_text(json.dumps(all_rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
