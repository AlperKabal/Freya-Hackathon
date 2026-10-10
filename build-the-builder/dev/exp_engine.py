"""Experiment (simulation): can the orchestrator speak and record without the model?

    source env.sh && python dev/exp_engine.py > results/exp-engine.txt

On a practice customer (PUB-01's session; dev/ may hold Brief A values), the workflow:
  setup (code: say_text, amt, date) -> verify x2 (api_request, answers baked) -> rec (api_request create_promise,
  amount baked from a code variable, plus a pre-hook that makes it a number) -> talk (TTS {{say_text}} on EVERY
  entry) <-> judge (code: new say_text with a marker) -> ... -> bye.
Checks:
  X2  every re-entry of `talk` speaks the NEW say_text by TTS (markers TTS-1, TTS-2), and nothing else is said;
  X4  the ledger has the promise with the baked amount as a number and the baked date;
  X5  a pre-hook on a pre_actions api_call runs (it writes `hook_ran`).
"""
import json, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev")); sys.path.insert(0, str(KIT / "tools"))
import freya
from exp_loop import code_node
from score import http

URL = "https://freya-bank-mock.freyavoice.workers.dev/v1/"
HDR = {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}}


def api(name, tool, body, target, pre=""):
    fn = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
          "function": {"name": tool, "handler": "__function__:api_call", "parameters": {"type": "object", "properties": {
              "url": {"type": "string", "default": URL + tool}, "method": {"type": "string", "default": "POST"}, "headers": HDR,
              "body": {"type": "object", "required": [], "properties": dict({"customer_id": {"type": "string", "default": "{{customer_id}}"}}, **body)}}}}}
    if pre: fn["pre_process_code"] = pre
    return {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": target, "on_enter": {"type": "silent"},
            "pre_actions": [fn], "response_mapping": [], "transitions": [{"target_node": target, "description": "always", "condition": {"operator": "always"}}]}


SETUP = "vars['say_text'] = 'TTS-0. Please say a colour.'\nvars['amt'] = '420.00'\nvars['pdate'] = '2026-10-16'\nvars['hops'] = '0'\n"
JUDGE = """try:
    n = int(str(vars.get('hops') or '0')) + 1
    vars['hops'] = str(n)
    vars['say_text'] = 'TTS-' + str(n) + '. Say another colour.'
    vars['done'] = 'yes' if n >= 2 else 'no'
except Exception:
    vars['done'] = 'yes'
"""
PRE = ("try:\n    b = config.get('body')\n    if isinstance(b, dict):\n        b['amount'] = float(str(vars.get('amt')))\n        vars['hook_ran'] = 'yes'\nexcept Exception:\n    pass\n")

WF = {
    "initial_node": "setup", "system_prompt": "You are a test assistant. Speak English. One short sentence per turn.", "global_nodes": {},
    "test_variables": {"say_text": "fallback"},
    "nodes": {
        "setup": code_node("setup", SETUP, "v1"),
        "v1": api("v1", "verify_identity", {"field": {"type": "string", "default": "date_of_birth"}, "answer": {"type": "string", "default": "1988-03-14"}}, "v2"),
        "v2": api("v2", "verify_identity", {"field": {"type": "string", "default": "phone_last4"}, "answer": {"type": "string", "default": "4471"}}, "rec"),
        "rec": api("rec", "create_promise", {"product_id": {"type": "string", "default": "p1"}, "amount": {"type": "number", "default": "{{amt}}"},
                                              "date": {"type": "string", "default": "{{pdate}}"}}, "talk", pre=PRE),
        "talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{say_text}}"},
                 "task_message": "Do not say anything of your own. Do not call a tool.",
                 "extraction_schema": [{"name": "colour", "type": "string", "enum_values": ["red", "blue", "green", "other"], "description": "Colour in the latest message", "min_confidence": 0.5}],
                 "transitions": [{"target_node": "judge", "description": "always", "condition": {"operator": "always"}}]},
        "judge": dict(code_node("judge", JUDGE, "talk"), transitions=[
            {"target_node": "bye", "description": "done", "condition": {"logic": "or", "conditions": [{"variable": "done", "operator": "equals", "operand": "yes"}]}},
            {"target_node": "talk", "description": "always", "condition": {"operator": "always"}}]),
        "bye": {"name": "bye", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                "terminal": {"type": "function", "function": {"name": "exp_done", "handler": "__function__:end_call",
                             "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"}, "spoken_message": {"type": "string", "default": "TTS-END goodbye."}}}}}},
    },
}
PERSONA = ("OUTPUT RULE: write only the words you say. You are testing a voice assistant. Each time it speaks, answer with one colour: "
           "first 'Red.', then 'Blue.', then 'Green.', then 'Goodbye.'")


def main():
    session = http("/v1/practice/sessions", {"case": "PUB-01"})["variables"]
    ids = freya.save_workflow("yasar-exp-date", WF, state_file=str(KIT / ".freya-agents.json"))
    print("workflow", ids, "| customer", session["customer_id"])
    store = KIT / ".personas.json"; known = json.loads(store.read_text()) if store.exists() else {}
    if "exp:engine" not in known:
        known["exp:engine"] = freya.create_personas([{"name": "exp engine", "prompt": PERSONA, "successCriteria": "The call happened.", "tags": ["experiment"]}])["personas"][0]["id"]
        store.write_text(json.dumps(known, indent=1))
    t0 = time.time()
    sim, it, status = freya.run_simulation(ids["agent_id"], f"exp engine {time.strftime('%H:%M:%S')}", {known["exp:engine"]: session}, max_seconds=180, concurrency=1)
    print(f"simulation {status} in {time.time() - t0:.0f} s")
    call = freya.get_call(freya.get_iteration(sim, it)["runs"][0]["callId"])
    said, hook = [], None
    for m in call.get("messages", []):
        if m.get("role") in ("assistant", "user"):
            print(f"{'AGENT' if m['role'] == 'assistant' else 'USER '} {m.get('message')}")
            if m["role"] == "assistant": said.append(str(m.get("message")))
        snap = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
        if "hook_ran" in snap: hook = snap["hook_ran"]
        if m.get("role") == "system":
            try: ev = json.loads(m.get("message") or "{}")
            except ValueError: continue
            if ev.get("event") == "function_call_start" and "create_promise" in str(ev.get("function")): print("      [call]", json.dumps((ev.get("args") or {}).get("body")))
            if ev.get("event") == "function_call_complete" and "create_promise" in str(ev.get("function")): print("      [done]", json.dumps(ev.get("result"))[:200])
            if (ev.get("variable_table") or {}).get("hook_ran"): hook = ev["variable_table"]["hook_ran"]
    led = http("/v1/practice/ledger/" + session["customer_id"])
    print("\nledger promises:", led.get("promises"))
    print("X2 TTS-1 and TTS-2 spoken exactly:", all(any(s.strip().startswith(f"TTS-{i}.") for s in said) for i in (1, 2)), "| agent lines:", len(said))
    p = (led.get("promises") or [{}])[0]
    print("X4 amount is a number 420.0 and date 2026-10-16:", isinstance(p.get("amount"), (int, float)) and float(p.get("amount", 0)) == 420.0 and p.get("date") == "2026-10-16", repr(p.get("amount")))
    print("X5 pre-hook on pre_actions ran:", hook)


if __name__ == "__main__":
    main()
