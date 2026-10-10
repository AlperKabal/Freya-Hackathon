"""Print one simulated call as a readable transcript: speech, node changes, tool calls, routing decisions.

    python dev/show_call.py results/base-a.json PUB-02 > results/PUB-02.txt   # by case id from a run_cases --out file
    python dev/show_call.py <call_id>                                          # by call id

Needs FREYA_API_KEY in the environment (source env.sh). Prints no secrets.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya


def call_id_from(args):
    if len(args) == 2:
        run = json.load(open(args[0]))
        for row in run.get("rows", []):
            if row["id"] == args[1]:
                return row["call_id"], row
        sys.exit(f"case {args[1]} not in {args[0]}")
    return args[0], None


def short(x, n=300):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " ..."


def main(args):
    cid, row = call_id_from(args)
    if row:
        print(f"# {row['id']} {'PASS' if row['pass'] else 'FAIL'}  tools: {' > '.join(row['tools'])}")
        for f in row["failed"]:
            print(f"#   - {f}")
    call = freya.get_call(cid)
    print(f"# call {cid}  endedReason={call.get('endedReason')}  duration={call.get('duration')}s\n")
    for m in call.get("messages", []):
        role, t = m.get("role"), m.get("secondsFromStart")
        ts = f"{t:6.1f}s" if isinstance(t, (int, float)) else "       "
        if role in ("assistant", "user"):
            print(f"{ts} {'AGENT' if role == 'assistant' else 'USER '}  {m.get('message')}")
            continue
        try:
            ev = json.loads(m.get("message") or "{}")
        except (TypeError, ValueError):
            print(f"{ts} {role}: {short(m.get('message'))}")
            continue
        kind = ev.get("event")
        if kind == "node_enter":
            print(f"{ts}   [node] {ev.get('from_node')} -> {ev.get('node')} ({ev.get('reason')})")
        elif kind == "function_call_start":
            a = ev.get("args") or {}
            print(f"{ts}   [call] {ev.get('function')} body={short(a.get('body', a))}")
        elif kind == "function_call_complete":
            r = ev.get("result") or {}
            print(f"{ts}   [done] {ev.get('function')} -> {short(r.get('data', r) if isinstance(r, dict) else r)}")
        elif kind == "route_evaluated":
            if ev.get("matched"):
                print(f"{ts}   [route] {ev.get('from_node')} -> {ev.get('target')}: {short(ev.get('reason'), 160)}")
        elif kind == "error":
            print(f"{ts}   [ERROR] {ev.get('message')} {short(ev.get('details'), 200)}")
        elif kind:
            print(f"{ts}   [{kind}]")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    main(sys.argv[1:])
