"""The mock briefs with the model and with the platform (the checks that need neither are dev/test_mock_briefs.py).

    python dev/run_mock_briefs.py --extract [d e f] [--out out/mock]      # the builder reads each pack's documents
    python dev/run_mock_briefs.py --check out/mock [d e f]                # judge the SPECs of an earlier --extract again, no model
    python dev/run_mock_briefs.py --list                                  # pack F's customers for the platform, no network
    python dev/run_mock_briefs.py --simulate <agent_id> [--only F-01,F-09] [--style in_words] [--reps 3] [--out results/mock-f.json]

--extract runs the real builder, one pack after the other (`builder/build.py <documents> <tool API> --no-save`: about
three model calls and two minutes each, on the Claude login's quota). Each SPEC it brings back is then
  1. compared with the pack's oracle SPEC, rule by rule (wording is not compared; a special situation is matched by
     what it does, not by its name), and
  2. made into an agent that meets the pack's customers and the universal customers, in the walker.
A rule the Reader missed shows in 1; whether it matters shows in 2. Fix what it finds in the extractor's field guide
or in the SPEC format, never by writing a value of a mock brief into builder/.

--simulate needs FREYA_API_KEY and FREYA_BANK_TEAM_KEY (source env.sh). Pack F keeps the kit's tool API, so its
customers borrow the practice customers' accounts, like dev/scenarios.py. The agent must have been BUILT FROM PACK F:
    python builder/build.py dev/mock_briefs/f-freya-sibling/1-specification.md dev/mock_briefs/f-freya-sibling/2-addendum.md tools/openapi.json --slot mock-f
One simulation runs at a time per workspace: agree with the team before a run.
"""
import argparse, collections, copy, json, pathlib, subprocess, sys, time, traceback
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev")); sys.path.insert(0, str(KIT / "dev" / "mock_briefs")); sys.path.insert(0, str(KIT / "tools"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import lib, universal
from compare_specs import WORDING, diff
from builder.spec_schema import validate

QUIET = (".rule_map", ".free_rules", ".meta", ".spec_version", ".situations", ".faq", ".agent")
SOFT = (".source", ".evidence_words", ".guidance", ".priority", ".trigger", ".not_this", ".name", ".meaning")


# ---------------------------------------------------------------- comparing a SPEC with the oracle

def what_it_does(x):
    """A special situation by its effect, whatever the Reader called it."""
    def eff(e):
        return (e["outcome"], e["reason"], tuple(sorted((a["type"], a.get("queue") or a.get("note_reason") or "") for a in e["actions"])))
    return eff(x["offer"]["on_accept"]) if x.get("offer") else eff(x["effect"])


def situation_map(oracle, got):
    """oracle situation id -> the extracted situation that does the same (most stages in common), or None."""
    out, used = {}, set()
    for o in oracle["situations"]:
        same = [g for g in got["situations"] if what_it_does(g) == what_it_does(o) and g["id"] not in used]
        best = max(same, key=lambda g: len(set(g["stages"]) & set(o["stages"])), default=None)
        out[o["id"]] = best["id"] if best else None
        if best:
            used.add(best["id"])
    return out


def normal(spec):
    """Names a reader is free to choose are made alike: bands are numbered by their days, an open band ends at 9999."""
    s = copy.deepcopy(spec)
    for i, b in enumerate(sorted(s["bands"], key=lambda b: b["days_late_min"])):
        b["name"] = f"band {i + 1}"
        b["days_late_max"] = 9999 if b["days_late_max"] >= 365 else b["days_late_max"]
    if not s["dates"]["business_day_only"]:
        s["dates"]["non_business_day"] = "-"                 # says nothing when any day is allowed
    return s


def differences(P, got):
    """Behaviour in which an extracted SPEC differs from the pack's oracle: [(tier-like weight, text)]."""
    out, raw = [], []
    diff(normal(P.spec), normal(got), "", raw)
    tolerate = tuple(P.meta.get("tolerate") or ())
    for kind, path, a, b in raw:
        if path.startswith(QUIET) or path.split(".")[-1].split("[")[0] in WORDING or any(w in path for w in SOFT) or path.startswith(tolerate):
            continue
        out.append(f"{kind} {path}: oracle {json.dumps(a, ensure_ascii=False)[:140]} | extracted {json.dumps(b, ensure_ascii=False)[:140]}")
    m = situation_map(P.spec, got)
    by_id = {x["id"]: x for x in got["situations"]}
    for o in P.spec["situations"]:
        g = by_id.get(m[o["id"]])
        if g is None:
            out.append(f"no special situation does what the oracle's {o['id']!r} does: {what_it_does(o)}")
            continue
        for key in ("scope", "threshold", "proposal_still_handled", "say_exact"):
            if g[key] != o[key]:
                out.append(f"situation {o['id']} (extracted as {g['id']}): {key} is {g[key]!r}, the oracle has {o[key]!r}")
        if set(g["stages"]) != set(o["stages"]):
            out.append(f"situation {o['id']} (extracted as {g['id']}): stages {sorted(g['stages'])}, the oracle has {sorted(o['stages'])}")
        if bool(g.get("offer")) != bool(o.get("offer")):
            out.append(f"situation {o['id']} (extracted as {g['id']}): {'an' if g.get('offer') else 'no'} offer, the oracle has {'one' if o.get('offer') else 'none'}")
        elif o.get("offer") and what_it_does(dict(g, offer=None, effect=g["offer"]["on_decline"])) != what_it_does(dict(o, offer=None, effect=o["offer"]["on_decline"])):
            out.append(f"situation {o['id']} (extracted as {g['id']}): a declined offer ends differently")
        if (g["effect"].get("outcome_by_stage") or {}) != (o["effect"].get("outcome_by_stage") or {}):
            out.append(f"situation {o['id']} (extracted as {g['id']}): outcome by stage is {g['effect'].get('outcome_by_stage')}, the oracle has {o['effect'].get('outcome_by_stage')}")
        if o["say_exact"] and o["say"].strip() != g["say"].strip():
            out.append(f"situation {o['id']} (extracted as {g['id']}): the prescribed sentence is {g['say']!r}, the brief says {o['say']!r}")
    extra = [g["id"] for g in got["situations"] if g["id"] not in m.values()]
    if extra:
        out.append(f"special situations the oracle does not have: {extra}")
    exact = [("negotiation.first_ask", "the first ask"), ("confirmation.question", "the read-back question"), ("recording.after_success_say", "the sentence after a recorded promise"),
             ("recording.failure_say", "the sentence when a promise cannot be saved"), ("amounts.too_much.say", "the sentence with the minimum"),
             ("amounts.below_min.say", "the sentence for an amount below the minimum"), ("identity.on_failed.say", "the sentence when the check has ended"),
             ("multi_product.first_ask_all", "the first ask for several products")]
    text = P.text()
    for path, label in exact:
        o, g = P.spec, got
        for part in path.split("."):
            o, g = o[part], g[part]
        if o and o in text and g.strip() != o.strip():      # only sentences the documents give word for word
            out.append(f"{label}: extracted {g!r}, the brief says {o!r}")
    return out


def translate(c, m):
    """The same customer for an agent whose special situations have other names."""
    c = copy.deepcopy(c)

    def ev(a):
        if isinstance(a, dict):
            return dict(a, kind=m[a["kind"]]) if m.get(a.get("kind")) else a
        return m[a] if isinstance(a, str) and m.get(a) else a
    steps = []
    for st in c["steps"]:
        if st[0] == "who" and m.get(st[1]):
            st = ("who", m[st[1]])
        elif st[0] == "go" and m.get(st[1]):
            st = ("go", m[st[1]])
        elif st[0] == "tp" and m.get(st[1].get("tp_event")):
            st = ("tp", dict(st[1], tp_event=m[st[1]["tp_event"]]))
        elif st[0] == "neg":
            cust = st[1]
            cust.first, cust.then, cust.readback, cust.offer = ev(cust.first), [ev(a) for a in cust.then], [ev(a) for a in cust.readback], ev(cust.offer)
        steps.append(st)
    c["steps"] = steps
    return c


def walk(P, got, verbose=False):
    """The pack's customers and the universal customers of the ORACLE, met by the agent of the extracted SPEC.
    The bank stand-in keeps speaking the oracle's field names: it is the bank, not the reading of it."""
    m = situation_map(P.spec, got)
    cases = P.cases()
    for d in ("2026-11-03", "2026-11-06", "2026-12-23"):
        cases += universal.cases(P, d, tag=d[5:] + "-")
    bad, runs = collections.OrderedDict(), 0
    wf = {}
    for c in cases:
        c2 = translate(c, m)
        for mode in c["modes"]:
            runs += 1
            try:
                if mode not in wf:
                    wf[mode] = lib.generate.build(got, P.tools, mode)
                sim = lib.Sim(got, P.tools, lib.Bank(P.spec, P.tools, c["identity"], c["products"], c["faults"]), mode, c["now"], c["variables"], wf[mode])
                problems = lib.judge(P, c2, lib.play(sim, c2))
            except Exception:
                problems = ["the walk raised: " + traceback.format_exc()[-400:]]
            if problems:
                bad[(c["tier"], c["id"], mode, c["title"])] = problems
    return bad, runs


def judge_spec(P, got, verbose=False):
    """Print the verdict on one extracted SPEC. Returns (rule differences, failing runs of tier 1)."""
    errs = validate(got, P.tools)
    if errs:
        print(f"   the SPEC does not fit the schema or the tool API: {errs[:4]}")
        return 1, 1
    diffs = differences(P, got)
    print(f"   {len(diffs)} rule(s) read differently from the oracle" + (":" if diffs else ""))
    for d in diffs:
        print("     - " + d[:330])
    bad, runs = walk(P, got, verbose)
    base, _ = walk(P, P.spec)
    new = {k: v for k, v in bad.items() if k not in base}
    t1 = sum(1 for k in new if k[0] == 1)
    print(f"   walked: {runs - len(bad)} of {runs} runs match the brief; {len(new)} fail that pass with the oracle SPEC (tier 1: {t1})")
    for (tier, cid, mode, title), problems in list(new.items())[:40 if verbose else 15]:
        print(f"     - [tier {tier}] [{mode}] {cid}: {title[:90]}")
        for p in problems[:3 if verbose else 1]:
            print("           " + p[:300])
    if len(new) > 15 and not verbose:
        print(f"     ... and {len(new) - 15} more (-v shows them)")
    return len(diffs), t1


# ---------------------------------------------------------------- sections

def extract(names, out, verbose):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for P in lib.packs(names or None):
        slot = "mock-" + P.name.split("-")[0]
        print(f"\n== {P.title}")
        t0 = time.time()
        cmd = [sys.executable, str(KIT / "builder/build.py")] + [str(d) for d in P.docs] + [str(P.api_path), "--slot", slot, "--no-save", "--out", str(out)]
        r = subprocess.run(cmd, cwd=str(KIT), capture_output=True, text=True)
        print(f"   builder: exit {r.returncode}, {time.time() - t0:.0f} s; {(r.stdout.strip().splitlines() or ['(no output)'])[-1][:200]}")
        spec = out / f"{slot}.spec.json"
        if not spec.exists():
            print("   no SPEC was written: " + (r.stderr.strip().splitlines() or ["(no error text)"])[-1][:300])
            total += 1
            continue
        d, t1 = judge_spec(P, json.loads(spec.read_text(encoding="utf-8")), verbose)
        total += t1
    return total


def check(folder, names, verbose):
    total = 0
    for P in lib.packs(names or None):
        spec = pathlib.Path(folder) / f"mock-{P.name.split('-')[0]}.spec.json"
        print(f"\n== {P.title}")
        if not spec.exists():
            print(f"   {spec} does not exist")
            continue
        total += judge_spec(P, json.loads(spec.read_text(encoding="utf-8")), verbose)[1]
    return total


def to_public(c):
    """A case in the shape of the kit's public test set (plus `base`), for tools/run_cases.persona_for and tools/score.py."""
    e = c["expected"]
    return {"id": c["id"], "base": c["base"], "brief": "B", "family": c["family"], "level": "mock", "title": c["title"], "variables": dict(c["variables"], now=c["now"]),
            "identity": c["identity"], "products": c["products"], "script": c["script"], "checks": c["checks"] or ["the agent follows the brief"],
            "expected": {"outcome": e["outcome"], "reason": e["reason"], "promises": [{"product_id": p, "amount": a, "date": d} for p, a, d in e["promises"]],
                         "notes": [{"product_id": p, "reason": r} for p, r in e["notes"]], "callbacks": [{"date": d, "time": t} for d, t in e["callbacks"]],
                         "transfers": [{"queue": q} for q in e["transfers"]]}}


def platform_cases(only=None):
    P = next(p for p in lib.packs() if p.meta.get("platform"))
    return [to_public(c) for c in P.cases() if c["base"] and c["script"] and (not only or c["id"] in only)]


def simulate(agent_id, only, style, reps, out):
    import freya
    from run_cases import STYLES, persona_for
    from run_scenarios import chunks, personas, run_once
    from score import http, score_ledger
    if style and style not in STYLES:
        sys.exit(f"--style must be one of {sorted(STYLES)}")
    cases = platform_cases(only)
    ids = personas(cases, style, freya, persona_for, KIT / ".personas.json")
    all_rows, t0 = [], time.time()
    for rep in range(reps):
        rows = []
        for part in chunks(cases, 12):
            got, sim_id, it_id, status = run_once(agent_id, part, ids, freya, http, score_ledger)
            rows += got
            print(f"-- simulation {sim_id} ({status}): {sum(r['pass'] for r in got)} / {len(got)} passed\n", flush=True)
        all_rows.append(rows)
    final = [{"id": c["id"], "passes": sum(r[k]["pass"] for r in all_rows), "runs": reps, "pass": all(r[k]["pass"] for r in all_rows)} for k, c in enumerate(cases)]
    for f in final:
        if reps > 1 or not f["pass"]:
            print(("PASS" if f["pass"] else "FAIL"), f["id"], f"{f['passes']}/{f['runs']}")
    n = sum(f["pass"] for f in final)
    print(f"\n{n} / {len(final)} customers of pack F passed" + (f" in all {reps} runs" if reps > 1 else "") + f", {time.time() - t0:.0f} s. A customer is OUR reading of the changed brief: read a failure before trusting it.")
    if out:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        json.dump({"agent_id": agent_id, "style": style, "passed": n, "total": len(final), "runs": reps, "final": final, "rows": all_rows[-1], "all_rows": all_rows}, open(out, "w"), indent=1)
    return 0 if n == len(final) else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="*"); ap.add_argument("--extract", action="store_true"); ap.add_argument("--check"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--simulate"); ap.add_argument("--only"); ap.add_argument("--style"); ap.add_argument("--reps", type=int, default=1); ap.add_argument("--out"); ap.add_argument("-v", action="store_true")
    a = ap.parse_args(argv)
    only = a.only.split(",") if a.only else None
    if a.list:
        for c in platform_cases(only):
            e = c["expected"]
            print(f"{c['id']:<6} {c['variables']['now']}  base {c['base']}  {c['title']}")
            print(f"{'':6} -> {e['outcome']}" + (f" / {e['reason']}" if e["reason"] else "") + "".join(f" | promise {p['product_id']} {p['amount']:.2f} on {p['date']}" for p in e["promises"])
                  + "".join(f" | note {n['product_id']} {n['reason']}" for n in e["notes"]) + "".join(f" | callback {x['date']} {x['time']}" for x in e["callbacks"])
                  + "".join(f" | transfer {t['queue']}" for t in e["transfers"]))
        return 0
    if a.extract:
        return 1 if extract(a.packs, a.out or str(KIT / "out" / "mock"), a.v) else 0
    if a.check:
        return 1 if check(a.check, a.packs, a.v) else 0
    if a.simulate:
        return simulate(a.simulate, only, a.style, a.reps, a.out)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
