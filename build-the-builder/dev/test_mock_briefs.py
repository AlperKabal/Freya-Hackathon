"""The mock briefs (dev/mock_briefs/): every customer of every pack, played through the agent the builder generates
from the pack's oracle SPEC, without the platform and without a model.

    python dev/test_mock_briefs.py                 # all packs
    python dev/test_mock_briefs.py d e             # some packs (by letter or folder name)
    python dev/test_mock_briefs.py --only D-65 -v  # one customer, with everything the agent said and the ledger

A FAIL is a difference between what the brief's text requires and what the generated agent does. Tier 1 is a rule
of the kind the final briefs announce (other numbers, names, calendars, identity questions, outcome tables); tier 2
is a plausible rule the kit's briefs do not have; tier 3 is exotic. Exit code 1 when a tier-1 customer fails.
"""
import pathlib, sys, traceback
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev" / "mock_briefs"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import lib
import make
from builder import generate, verify
from builder.spec_schema import validate


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in args
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    names = [a for a in args if not a.startswith("-") and not (only and a in ",".join(only))]
    failed = {1: 0, 2: 0, 3: 0}
    stale = make.main(["--check"])
    if stale:
        print("FAIL the generated pack files differ from dev/mock_briefs/make.py: run it")
        failed[1] += 1
    for P in lib.packs(names or None):
        print(f"\n== {P.title}")
        errs = validate(P.spec, P.tools)
        print(("FAIL" if errs else "PASS") + f" the oracle SPEC fits the schema and the pack's tool API: {errs[:3]}")
        failed[1] += bool(errs)
        for mode in ("v1", "orch"):
            wf = generate.build(P.spec, P.tools, mode)
            bad = verify.lint(wf, P.spec, P.tools) + verify.run_snippets(wf, P.spec)
            print(("FAIL" if bad else "PASS") + f" mode {mode}: builds, lints and its code runs on the sample days: {bad[:3]}")
            failed[1] += bool(bad)
            words = [w for w in P.spec["opening"]["forbidden_before_identity"] if w.lower() in (wf["nodes"]["opening"]["on_enter"].get("text") or "").lower()]
            print(("FAIL" if words else "PASS") + f" mode {mode}: the opening line has none of the words forbidden before identity: {words}")
            failed[1] += bool(words)
        cases, runs, bad_runs = P.cases(), 0, 0
        for c in cases:
            if only and c["id"] not in only:
                continue
            for mode in c["modes"]:
                runs += 1
                try:
                    sim = lib.play(P.sim(c, mode), c)
                    problems = lib.judge(P, c, sim)
                except Exception:
                    sim, problems = None, ["the walk raised: " + traceback.format_exc()[-700:]]
                if problems:
                    bad_runs += 1
                    failed[c["tier"]] += 1
                    print(f"FAIL [tier {c['tier']}] [{mode}] {c['id']}: {c['title']}")
                    for p in problems:
                        print("       - " + p[:500])
                    if c.get("note"):
                        print("       note: " + c["note"])
                if verbose and sim:
                    print(f"     {c['id']} [{mode}] said:")
                    for node, text in sim.said:
                        print(f"        {node}: {text[:400]}")
                    print(f"        ledger: {sim.bank.ledger()}")
        print(f"{runs - bad_runs} of {runs} runs of {len(cases)} customers match the brief")
    print(f"\nfailing runs: tier 1: {failed[1]}, tier 2: {failed[2]}, tier 3: {failed[3]}")
    return 1 if failed[1] else 0


if __name__ == "__main__":
    sys.exit(main())
