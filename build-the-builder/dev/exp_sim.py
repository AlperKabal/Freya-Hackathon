"""Run an experiment workflow as a real (text) simulation, because the chat route skips the initial code node and
fails with 503/504 when a call enters a code node mid-call (seen 2026-10-10).

    source env.sh && python dev/exp_sim.py hop > results/exp-hop.txt

Saves the experiment's workflow to the shared slot `yasar-exp-date`, creates (once) a persona that follows a fixed
script, runs one simulated call and prints the transcript with the checks. One simulation at a time per workspace.
"""
import json, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev"))
import freya

EXPERIMENTS = {
    "hop": {
        "module": "exp_hop",
        "persona": ("OUTPUT RULE: write only the words you say. You are testing a voice assistant. It will ask you for colours. "
                    "Answer its questions one at a time, in this order, one answer per turn: first say 'Red.', then 'Blue.', "
                    "then 'Hmm, I am not sure.', then 'Green.', then 'Thank you, goodbye.' and stop."),
        "check": lambda replies: [(f"APPLE-{i}", any(f"APPLE-{i}" in r.upper() for r in replies)) for i in (1, 2, 3)],
    },
}


def main(name):
    exp = EXPERIMENTS[name]
    mod = __import__(exp["module"])
    wf = json.loads(json.dumps(mod.WF))
    if not any(n.get("node_type") == "end_call" for n in wf["nodes"].values()):
        wf["nodes"]["bye"] = {"name": "bye", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                              "terminal": {"type": "function", "function": {"name": "exp_done", "handler": "__function__:end_call",
                                           "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}
    ids = freya.save_workflow("yasar-exp-date", wf, state_file=str(KIT / ".freya-agents.json"))
    print("workflow", ids)
    store = KIT / ".personas.json"
    known = json.loads(store.read_text()) if store.exists() else {}
    key = f"exp:{name}:{abs(hash(exp['persona'])) % 10**8}"
    if key not in known:
        p = freya.create_personas([{"name": f"exp {name}", "prompt": exp["persona"], "successCriteria": "The call happened.", "tags": ["experiment"]}])["personas"][0]
        known[key] = p["id"]; store.write_text(json.dumps(known, indent=1))
    pid = known[key]
    t0 = time.time()
    sim_id, it_id, status = freya.run_simulation(ids["agent_id"], f"exp {name} {time.strftime('%H:%M:%S')}", {pid: {}}, max_seconds=180, concurrency=1)
    print(f"simulation {sim_id} {status} in {time.time() - t0:.0f} s")
    run = freya.get_iteration(sim_id, it_id)["runs"][0]
    call = freya.get_call(run["callId"])
    replies = []
    for m in call.get("messages", []):
        if m.get("role") in ("assistant", "user"):
            print(f"{'AGENT' if m['role'] == 'assistant' else 'USER '} {m.get('message')}")
            if m["role"] == "assistant": replies.append(str(m.get("message")))
        elif m.get("role") == "system":
            try: ev = json.loads(m.get("message") or "{}")
            except ValueError: continue
            if ev.get("event") == "node_enter": print(f"      [node] {ev.get('from_node')} -> {ev.get('node')}")
            if ev.get("event") == "error": print(f"      [ERROR] {ev.get('message')}")
    print("\nchecks:")
    for label, ok in exp["check"](replies):
        print(f"  {'PASS' if ok else 'FAIL'} {label} spoken after its hop")
    print("endedReason:", call.get("endedReason"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "hop")
