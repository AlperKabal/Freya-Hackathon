"""Experiment: does `type: "date"` extraction resolve "tomorrow" against the call variable `now` or the real clock?

    source env.sh && python dev/exp_date_anchor.py > results/exp-date-anchor.txt

Saves a one-node workflow to the slot `yasar-exp-date`, sends one chat turn with now = 2026-10-14T11:00, and prints
what the extractor stored. If `when_date` is the day after the REAL date, the built-in date rules use the real
clock and the builder must resolve dates in code (builder/snippets/dates.py).
"""
import datetime, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya

NOW = "2026-10-14T11:00"
WF = {
    "initial_node": "ask",
    "system_prompt": "You are a test assistant. Speak English. One short sentence per turn.",
    "test_variables": {"now": NOW},
    "global_nodes": {},
    "nodes": {
        "ask": {
            "name": "ask", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": "When can you pay?"},
            "task_message": "Today is {{now}}. Ask on which day the user can pay. Do not call a tool in this turn.",
            "extraction_schema": [
                {"name": "when_date", "type": "date", "description": "The day the user says they can pay", "min_confidence": 0.5},
                {"name": "when_text", "type": "string", "description": "The words the user used for the day, copied exactly", "min_confidence": 0.5},
            ],
            "transitions": [{"target_node": "ask", "description": "stay", "condition": {"operator": "always"}}],
        },
        "bye": {"name": "bye", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                "terminal": {"type": "function", "function": {"name": "bye", "handler": "__function__:end_call",
                             "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}},
    },
}


def find_vars(call):
    """Collect the extracted variables from snapshots and route events, wherever the platform put them."""
    found = {}
    for m in call.get("messages", []):
        snap = (m.get("workflowSnapshot") or {}).get("variableTable") or {}
        for k in ("when_date", "when_text", "now"):
            if k in snap: found[k] = snap[k]
        if m.get("role") == "system":
            try: ev = json.loads(m.get("message") or "{}")
            except ValueError: continue
            table = ev.get("variable_table") or {}
            for k in ("when_date", "when_text", "now"):
                if k in table: found[k] = table[k]
    return found


def main():
    ids = freya.save_workflow("yasar-exp-date", WF)
    print("workflow", ids)
    r = freya.api("POST", "/api/v2/chat/message", {"workflowId": ids["workflow_id"], "message": "I can pay tomorrow.", "customerVariables": {"now": NOW}})
    print("agent said:", r.get("response"))
    cid = r.get("callId")
    try: freya.api("POST", "/api/v2/chat/end", {"callId": cid})
    except RuntimeError as e: print("chat end:", e)
    found = find_vars(freya.get_call(cid))
    real = datetime.date.today()
    print("call variable now   :", NOW, "-> 'tomorrow' should be 2026-10-15")
    print("real clock today    :", real.isoformat(), "-> real tomorrow is", (real + datetime.timedelta(days=1)).isoformat())
    print("extracted variables :", json.dumps(found, indent=1, default=str))


if __name__ == "__main__":
    main()
