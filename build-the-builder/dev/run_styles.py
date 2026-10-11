"""Final customers talk like people: numbers in two parts, self-corrections, small talk, questions back, amounts and
dates in words. This runs the practice customers in every such style, one simulation after the other, and prints
which customer fails in which style.

    python dev/run_styles.py <agent_id> --brief A [--styles pieces,corrects] [--plain] [--reps 1] [--tag orch-a]
    python dev/run_styles.py --summary --brief A --tag orch-a        # only read results/<tag>-<brief>-<style>.json again

Needs FREYA_API_KEY and FREYA_BANK_TEAM_KEY (source env.sh). It calls the kit's own tools/run_cases.py, unchanged.
Five styles of ten customers take about as long as five plain runs: one simulation runs at a time per workspace, so
agree with the team first. Read a failed call with: python dev/show_call.py results/<tag>-<brief>-<style>.json PUB-xx
"""
import argparse, json, pathlib, subprocess, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
STYLES = ["pieces", "corrects", "talkative", "asks_back", "in_words"]


def result_file(tag, brief, style):
    return KIT / "results" / f"{tag}-{brief}-{style or 'plain'}.json"


def summary(tag, brief, styles):
    """The matrix customer x style from the result files that exist. Returns the number of failed cells."""
    runs = {s: json.loads(result_file(tag, brief, s).read_text()) for s in styles if result_file(tag, brief, s).exists()}
    if not runs:
        print(f"no result files for tag {tag!r}, brief {brief}")
        return 0
    cases = sorted({f["id"] for r in runs.values() for f in r["final"]})
    cell = lambda r, cid: next((("ok" if f["pass"] else f"FAIL {f['passes']}/{f['runs']}") for f in r["final"] if f["id"] == cid), "-")
    width = max(12, *(len(str(s or "plain")) + 2 for s in runs))
    print(f"\nBrief {brief}, tag {tag}: customer x style" + "".join(f"{str(s or 'plain'):>{width}}" for s in runs))
    bad = 0
    for cid in cases:
        row = [cell(r, cid) for r in runs.values()]
        bad += sum(x.startswith("FAIL") for x in row)
        print(f"{cid:<36}" + "".join(f"{x:>{width}}" for x in row))
    print(f"{'passed':<36}" + "".join(f"{str(r['passed']) + '/' + str(r['total']):>{width}}" for r in runs.values()))
    for s, r in runs.items():
        for row in r.get("rows", []):
            if not row["pass"]:
                print(f"  {str(s or 'plain')}: {row['id']}: " + " | ".join(str(f)[:200] for f in row["failed"]))
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_id", nargs="?"); ap.add_argument("--brief", required=True, choices=["A", "B"]); ap.add_argument("--styles", default=",".join(STYLES))
    ap.add_argument("--plain", action="store_true", help="also run without a style"); ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--tag", default="styles"); ap.add_argument("--only"); ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    styles = ([None] if a.plain else []) + [s for s in a.styles.split(",") if s]
    unknown = [s for s in styles if s and s not in STYLES]
    if unknown:
        sys.exit(f"unknown style(s) {unknown}; the kit has {STYLES}")
    if not a.summary:
        if not a.agent_id:
            sys.exit("give the agent id, or --summary to read existing results")
        for s in styles:
            cmd = [sys.executable, "-u", str(KIT / "tools" / "run_cases.py"), a.agent_id, "--brief", a.brief, "--reps", str(a.reps), "--out", str(result_file(a.tag, a.brief, s))]
            cmd += (["--style", s] if s else []) + (["--only", a.only] if a.only else [])
            print(f"\n===== {s or 'plain'}: {' '.join(cmd[2:])}", flush=True)
            subprocess.run(cmd, cwd=str(KIT))            # a failed run is seen in the summary: the next style still runs
    return 1 if summary(a.tag, a.brief, styles) else 0


if __name__ == "__main__":
    sys.exit(main())
