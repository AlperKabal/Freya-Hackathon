"""Experiment for the speaker / orchestrator loop (ARCHITECTURE.md section 4, X1 X2 X3 X6 and the chat code-step note).

    source env.sh && python dev/exp_loop.py > results/exp-loop.txt

Workflow: setup (code) -> talk (conversation: TTS {{say_text}}, extracts a colour) -always-> judge (code: counts the
turn, clears the colour, writes the next say_text) -> talk ... After 3 turns judge sends the call to `thanks`, whose
on_enter is an LLM line, then to the end node.

What each turn tells us:
  X1  does the `always` transition of `talk` wait for the user, or fire right after talk's own TTS?  (turn counter)
  X2  is talk's TTS spoken again with the NEW say_text on every re-entry?                           (agent replies)
  X3  after judge writes colour = "", does a turn without a colour leave it empty, or does the
      extractor re-read an old colour from the history?                                           (seen_3)
  X6  does on_enter {"type": "llm", "prompt": ...} speak one line?                                  (last reply)
  X9  does the chat route skip the initial code node?                                              (setup_ran)
Uses the shared experiment slot `yasar-exp-date` (one workflow for all experiments, updated in place).
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya

SLOT = "yasar-exp-date"


def code_node(name, src, target):
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
            "on_enter": {"type": "silent"},
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                             "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": src},
                                                                            "timeout_ms": {"type": "number", "default": 5000}}}}}],
            "transitions": [{"target_node": target, "description": "always", "condition": {"operator": "always"}}]}


SETUP = "vars['setup_ran'] = 'yes'\nvars['turn'] = '0'\nvars['say_text'] = 'Turn zero. Please say a colour.'\n"
JUDGE = """try:
    n = int(str(vars.get('turn') or '0')) + 1
    c = str(vars.get('colour') or '')
    vars['turn'] = str(n)
    vars['seen_' + str(n)] = c if c else 'EMPTY'
    vars['colour'] = ''
    vars['say_text'] = 'Turn ' + str(n) + '. You said ' + (c or 'nothing') + '. Please say another colour.'
    vars['done'] = 'yes' if n >= 3 else 'no'
except Exception:
    vars['done'] = 'yes'
"""

WF = {
    "initial_node": "setup",
    "system_prompt": "You are a test assistant. Speak English. One short sentence per turn.",
    "test_variables": {"say_text": "Fallback line: the setup code did not run. Please say a colour.", "turn": "0"},
    "global_nodes": {},
    "nodes": {
        "setup": code_node("setup", SETUP, "talk"),
        "talk": {"name": "talk", "node_type": "conversation",
                 "on_enter": {"type": "tts", "text": "{{say_text}}"},
                 "task_message": "Repeat the last instruction in one sentence. Do not call a tool in this turn.",
                 "extraction_schema": [{"name": "colour", "type": "string", "enum_values": ["red", "blue", "green", "other"],
                                        "description": "The colour the user names in their LATEST message only. Empty if the latest message names no colour.",
                                        "min_confidence": 0.5}],
                 "transitions": [{"target_node": "judge", "description": "always", "condition": {"operator": "always"}}]},
        "judge": dict(code_node("judge", JUDGE, "talk"), transitions=[
            {"target_node": "thanks", "description": "three turns done", "condition": {"logic": "or", "conditions": [{"variable": "done", "operator": "equals", "operand": "yes"}]}},
            {"target_node": "talk", "description": "always", "condition": {"operator": "always"}}]),
        "thanks": {"name": "thanks", "node_type": "conversation",
                   "on_enter": {"type": "llm", "prompt": "Say exactly one short sentence that thanks the user for the colours and mentions the word banana."},
                   "task_message": "Thank the user. Do not call a tool in this turn.",
                   "transitions": [{"target_node": "bye", "description": "always", "condition": {"operator": "always"}}]},
        "bye": {"name": "bye", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                "terminal": {"type": "function", "function": {"name": "exp_done", "handler": "__function__:end_call",
                             "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"},
                                                                            "spoken_message": {"type": "string", "default": "Goodbye."}}}}}},
    },
}

TURNS = ["Hello?", "Red.", "Blue, I think.", "Hmm, I am not sure.", "Okay."]


def main():
    ids = freya.save_workflow(SLOT, WF)
    print("workflow", ids)
    cid = None
    for msg in TURNS:
        body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": {}}
        if cid: body["callId"] = cid
        try:
            r = freya.api("POST", "/api/v2/chat/message", body)
        except RuntimeError as e:
            print(f"USER  {msg}\n  !! {e}"); break
        cid = r.get("callId") or cid
        print(f"USER  {msg}\nAGENT {r.get('response')!r}")
    try: freya.api("POST", "/api/v2/chat/end", {"callId": cid})
    except RuntimeError as e: print("chat end:", e)
    call = freya.get_call(cid)
    print("\n--- events")
    last_table = {}
    for m in call.get("messages", []):
        if m.get("role") != "system":
            continue
        try: ev = json.loads(m.get("message") or "{}")
        except ValueError: continue
        kind = ev.get("event")
        if kind == "node_enter": print(f"  node {ev.get('from_node')} -> {ev.get('node')}")
        elif kind == "route_evaluated" and ev.get("matched"): print(f"  route {ev.get('from_node')} -> {ev.get('target')}")
        elif kind == "error": print(f"  ERROR {ev.get('message')} {str(ev.get('details'))[:200]}")
        if ev.get("variable_table"): last_table = ev["variable_table"]
    for m in call.get("messages", []):
        snap = (m.get("workflowSnapshot") or {}).get("variableTable")
        if snap: last_table = snap
    keys = ["setup_ran", "turn", "colour", "seen_1", "seen_2", "seen_3", "done", "say_text"]
    print("\n--- variables at the end")
    for k in keys:
        v = last_table.get(k)
        print(f"  {k}: {v.get('value') if isinstance(v, dict) else v!r}")
    print("\nendedReason:", call.get("endedReason"))


if __name__ == "__main__":
    main()
