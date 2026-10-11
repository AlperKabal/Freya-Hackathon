"""Run our own customers (dev/scenarios.py) against an agent: other calendar days, rules no practice customer
tests, replies that only look like a special situation. Scored like tools/run_cases.py: the bank's records must
equal what the brief requires, and the judge reads the conversation against the scenario's checks.

    python dev/run_scenarios.py --list [--brief A|B] [--grep fri]                  # no network: what would run
    python dev/run_scenarios.py <agent_id> [--brief A|B] [--grep text] [--only ID,ID] [--style pieces] [--reps 3] [--out results/sc.json]

Needs FREYA_API_KEY and FREYA_BANK_TEAM_KEY (source env.sh). One simulation runs at a time per workspace: agree
with the team before a long run. More than 15 scenarios need --all; they run as simulations of at most --chunk
customers (default 12, about the size of a practice run), one after the other.
Each scenario borrows a practice customer (`base`): the mock opens a session for that case id, and the simulation
gets that session's variables with OUR `now`. The mock records any date, so another day needs nothing from it.
Read a failed call with: python dev/show_call.py <the --out file> <scenario id>
These are Brief A/B customers: never run them against an agent built from another brief.
"""
import argparse, hashlib, json, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "tools")); sys.path.insert(0, str(KIT / "dev"))
from scenarios import scenarios


def select(a):
    out = [s for s in scenarios() if (not a.brief or s["brief"] == a.brief) and (not a.only or s["id"] in a.only.split(","))
           and (not a.grep or a.grep.lower() in (s["id"] + " " + s["title"] + " " + s["family"]).lower())]
    return out


def show(cases):
    for c in cases:
        e = c["expected"]
        print(f"{c['id']:<34} {c['variables']['now']}  base {c['base']}  {c['title']}")
        print(f"{'':34} -> {e['outcome']}" + (f" / {e['reason']}" if e["reason"] else "")
              + "".join(f" | promise {p['product_id']} {p['amount']:.2f} on {p['date']}" for p in e["promises"])
              + "".join(f" | note {n['product_id']} {n['reason']}" for n in e["notes"])
              + "".join(f" | callback {x['date']} {x['time']}" for x in e["callbacks"])
              + "".join(f" | transfer {t['queue']}" for t in e["transfers"]))
    print(f"\n{len(cases)} scenario(s)")


def chunks(items, size):
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def personas(cases, style, freya, persona_for, store):
    """One persona per scenario text, cached like tools/run_cases.py does (a changed script makes a new persona)."""
    ids = json.loads(store.read_text()) if store.exists() else {}
    spec = {c["id"]: persona_for(c, {"identity": c["identity"]}, style) for c in cases}
    key = {i: i + ":" + hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:10] for i, p in spec.items()}
    new = [c for c in cases if key[c["id"]] not in ids]
    if new:
        made = freya.create_personas([spec[c["id"]] for c in new])["personas"]
        ids.update({key[c["id"]]: p["id"] for c, p in zip(new, made)})
        store.write_text(json.dumps(ids, indent=1))
    return {c["id"]: ids[key[c["id"]]] for c in cases}


def run_once(agent_id, cases, ids, freya, http, score_ledger, out=print):
    """One simulation: every scenario once. Returns the scored rows (the shape dev/show_call.py reads)."""
    sessions = {c["id"]: http("/v1/practice/sessions", {"case": c["base"]})["variables"] for c in cases}
    variables = {ids[c["id"]]: dict(sessions[c["id"]], now=c["variables"]["now"]) for c in cases}       # the base customer, on our day
    sim_id, it_id, status = freya.run_simulation(agent_id, f"scenarios {time.strftime('%H:%M:%S')}", variables)
    judge = {r["personaId"]: r for r in freya.get_iteration(sim_id, it_id)["runs"]}
    rows = []
    for c in cases:
        led = http("/v1/practice/ledger/" + sessions[c["id"]]["customer_id"])
        r = score_ledger(c, led)
        j = judge.get(ids[c["id"]], {})
        if j.get("outcome") != "pass":
            r["failed"].append("conversation: " + " ".join(str(j.get("reason") or "no verdict").split())[:400])
        tools = [x["tool"] for x in led.get("calls", [])]
        rows.append({"id": c["id"], "base": c["base"], "family": c["family"], "level": c["level"], "now": c["variables"]["now"], "pass": not r["failed"], "failed": r["failed"],
                     "call_id": j.get("callId"), "tools": tools, "customer_id": sessions[c["id"]]["customer_id"]})
        out(("PASS" if not r["failed"] else "FAIL") + f" {c['id']:<34} " + (" > ".join(t.replace("verify_identity", "verify").replace("create_promise", "promise") for t in tools) or "(no tool calls)"))
        for f in r["failed"]:
            out("       - " + f[:300])
    return rows, sim_id, it_id, status


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_id", nargs="?")
    ap.add_argument("--list", action="store_true"); ap.add_argument("--brief", choices=["A", "B"]); ap.add_argument("--only"); ap.add_argument("--grep")
    ap.add_argument("--style"); ap.add_argument("--reps", type=int, default=1); ap.add_argument("--out")
    ap.add_argument("--all", action="store_true", help="allow more than 15 scenarios in one command"); ap.add_argument("--chunk", type=int, default=12)
    a = ap.parse_args(argv)
    cases = select(a)
    if a.list or not a.agent_id:
        show(cases)
        return 0
    if not cases:
        sys.exit("no scenario matches: see --list")
    if len(cases) > 15 and not a.all:
        sys.exit(f"{len(cases)} scenarios match: about {-(-len(cases) // max(1, a.chunk))} simulations, one after the other, in the shared workspace. "
                 "Narrow it with --grep / --only / --brief, or pass --all.")
    import freya
    from run_cases import STYLES, persona_for
    from score import http, score_ledger
    if a.style and a.style not in STYLES:
        sys.exit(f"--style must be one of {sorted(STYLES)}")
    ids = personas(cases, a.style, freya, persona_for, KIT / ".personas.json")
    (KIT / "results").mkdir(exist_ok=True)
    reps, t0, sim_id, it_id = [], time.time(), None, None
    for rep in range(a.reps):
        rows = []
        for part in chunks(cases, a.chunk):
            got, sim_id, it_id, status = run_once(a.agent_id, part, ids, freya, http, score_ledger)
            rows += got
            print(f"-- simulation {sim_id} ({status}): {sum(r['pass'] for r in got)} / {len(got)} passed\n", flush=True)
        reps.append(rows)
        if a.reps > 1:
            print(f"-- run {rep + 1} of {a.reps}: {sum(r['pass'] for r in rows)} / {len(rows)} passed\n", flush=True)
    final = [{"id": c["id"], "passes": sum(r[k]["pass"] for r in reps), "runs": a.reps, "pass": all(r[k]["pass"] for r in reps)} for k, c in enumerate(cases)]
    for f in final:
        if a.reps > 1 or not f["pass"]:
            print(("PASS" if f["pass"] else "FAIL"), f["id"], f"{f['passes']}/{f['runs']}")
    n = sum(f["pass"] for f in final)
    print(f"\n{n} / {len(final)} scenarios passed" + (f" in all {a.reps} runs" if a.reps > 1 else "") + f", {time.time() - t0:.0f} s. A scenario is OUR reading of the brief: read a failure before trusting it.")
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"agent_id": a.agent_id, "simulation_id": sim_id, "iteration_id": it_id, "style": a.style, "passed": n, "total": len(final), "runs": a.reps,
                   "final": final, "rows": reps[-1], "all_rows": reps}, open(a.out, "w"), indent=1)
    return 0 if n == len(final) else 1


if __name__ == "__main__":
    sys.exit(main())
