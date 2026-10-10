"""Experiment: the date-check hop the negotiation needs.

    source env.sh && python dev/exp_hop.py > results/exp-hop.txt

talk (conversation, TTS opening on FIRST entry only, extracts `colour`) -[colour set]-> check (code: writes a marker
word into `note`, clears `colour`) -always-> talk.
Question: after the hop, does the dialogue model answer the user IN THE SAME TURN, using the new {{note}}? Pass if
every agent reply after a colour contains that turn's marker word (APPLE-1, APPLE-2, ...).
A turn without a colour must not hop (tests that the cleared variable is not re-read from the history).
Uses the shared experiment slot `yasar-exp-date`.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya
from exp_loop import code_node

CHECK = """try:
    n = int(str(vars.get('hops') or '0')) + 1
    vars['hops'] = str(n)
    vars['note'] = 'The user just said the colour ' + str(vars.get('colour') or '?') + '. In your reply you MUST say the word APPLE-' + str(n) + '.'
    vars['colour'] = ''
except Exception:
    vars['note'] = 'error'
"""
WF = {
    "initial_node": "talk", "system_prompt": "You are a test assistant. Speak English. One short sentence per turn.",
    "test_variables": {"note": "No colour yet.", "hops": "0"}, "global_nodes": {},
    "nodes": {
        "talk": {"name": "talk", "node_type": "conversation", "on_enter": {"type": "tts", "text": "Please say a colour."}, "on_enter_first_entry_only": True,
                 "task_message": "LATEST NOTE: {{note}}\nReply in one short sentence and ask for another colour. Do not call a tool.",
                 "extraction_schema": [{"name": "colour", "type": "string", "enum_values": ["red", "blue", "green"],
                                        "description": "The colour named in the user's LATEST message only. Empty if the latest message names no colour.", "min_confidence": 0.5}],
                 "transitions": [{"target_node": "check", "description": "a colour was named", "condition": {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                     {"variable": "colour", "operator": "is_set"}, {"variable": "colour", "operator": "not_equals", "operand": ""}]}]}}]},
        "check": code_node("check", CHECK, "talk"),
    },
}
TURNS = ["Hello.", "Red.", "Blue.", "Hmm, I am not sure.", "Green."]


def main():
    ids = freya.save_workflow("yasar-exp-date", WF)
    print("workflow", ids)
    cid, n = None, 0
    for msg in TURNS:
        body = {"workflowId": ids["workflow_id"], "message": msg, "customerVariables": {}}
        if cid: body["callId"] = cid
        r = freya.api("POST", "/api/v2/chat/message", body)
        cid = r.get("callId") or cid
        reply = str(r.get("response"))
        if msg.rstrip(".").lower() in ("red", "blue", "green"):
            n += 1
            verdict = "PASS" if f"APPLE-{n}" in reply.upper() else "FAIL"
        else:
            verdict = "no hop expected: " + ("PASS" if "APPLE" not in reply.upper() or f"APPLE-{n}" in reply.upper() else "FAIL (hopped again?)")
        print(f"USER  {msg}\nAGENT {reply!r}\n      -> {verdict}")
    try: freya.api("POST", "/api/v2/chat/end", {"callId": cid})
    except RuntimeError as e: print("chat end:", e)


if __name__ == "__main__":
    main()
