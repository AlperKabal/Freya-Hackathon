"""The last resort: a phone agent built without a SPEC, from the documents' own text and the tool API alone.

    wf, shim = build(docs, tools)        # shim: the little a SPEC-shaped dict verify.lint needs

When no SPEC can be had (the model is not reachable, the time is used up) or nothing generated from a SPEC passes,
the build still must not end with nothing. This agent is one conversation step: the bank's documents are its
instructions, every bank tool is offered to the model with the fields and allowed values of the tool API, a code
step gives it the call's date and a calendar with weekday names, and the call is closed through one transition per
(outcome, reason) row the documents list. It is far weaker than the generated agent: code decides nothing here.
Nothing in this file knows a brief; the field roles come from builder/robust.py.
"""
import json, re

from builder import codegen, robust
from builder.generate import HDR, code_node, tool_t, tr
from builder.spec_schema import TOOL_NAMES

MAX_DOC_CHARS = 60000        # the documents are the prompt: far more than a brief is, and little enough to stay fast


def closings(docs, outcomes):
    """The (outcome, reason) rows the documents list for closing a call: every table or list row whose first cell is
    one of the tool API's outcome values; the code-like cells right after it are its reasons. No row for an outcome
    means it is closed without a reason."""
    rows = {o: [] for o in outcomes}
    code = lambda c: re.fullmatch(r"[a-z][a-z0-9_]*", c) is not None and c not in ("none", "na", "empty", "null")
    for d in docs:
        for line in str(d.get("text") or "").splitlines():
            cells = [c.strip().strip("`'\"*").strip() for c in re.split(r"[|,;\t]", line.strip().strip("|"))]
            if len(cells) < 2 or cells[0] not in rows:
                continue
            for c in cells[1:]:
                if not code(c):
                    break
                if c not in rows[cells[0]]:
                    rows[cells[0]].append(c)
    return [(o, r) for o in outcomes for r in (rows[o] or [""])]


SETUP = """
try:
    now = None
    for k in list(vars.keys()):
        if str(k).startswith(('system.', 'call.')):
            continue
        v = str(vars.get(k) or '')
        if _re.match(r'\\d{4}-\\d{2}-\\d{2}[T ]\\d{1,2}:\\d{2}', v):       # the call's own clock, whatever the variable is called
            now = parse_now(v)
            break
    if not now:
        now = _dt.datetime.now()
    today = now.date()
    vars['today_iso'] = today.isoformat()
    vars['today_spoken'] = spoken(today) + now.strftime(', %H:%M')
    vars['calendar_text'] = '\\n'.join(spoken(today + _dt.timedelta(days=j)) + ' (' + (today + _dt.timedelta(days=j)).isoformat() + ')' for j in range(0, 46))
except Exception:
    vars['today_iso'] = ''
    vars['today_spoken'] = 'today'
    vars['calendar_text'] = ''
"""

POST = """
try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if isinstance(d, dict):
            d['what_to_do_next'] = ('Tell the customer what this result means and go on with the specification. If it did not work '
                                    '(an error, or a value that says no), say so truthfully and never claim that it worked.')
except Exception:
    pass
"""


def _tool(name, spec, cid, cid_var):
    props = {}
    for field, f in spec["request"].items():
        if field == cid:
            props[field] = {"type": "string", "default": "{{" + cid_var + "}}"}
            continue
        p = {"type": f.get("type") if f.get("type") in ("string", "number", "integer", "boolean") else "string",
             "default": "{{m_" + name + "_" + field + "}}",             # a name nothing sets: the model fills the field
             "description": (f.get("description") or field.replace("_", " ")) + (" One of: " + ", ".join(map(str, f["enum"])) + "." if f.get("enum") else "")}
        if f.get("enum"):
            p["enum"] = list(f["enum"])
        props[field] = p
    return {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0},
            "function": {"name": name, "handler": "__function__:api_call", "description": (spec.get("summary") or name.replace("_", " ")) + " CALL it when the specification says so.",
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": spec["url"]}, "method": {"type": "string", "default": spec["method"]}, "headers": HDR,
                             "body": {"type": "object", "required": [r for r in spec["required"] if r != cid], "properties": props}}}},
            "post_process_code": POST}


def build(docs, tools):
    b = robust.bind(tools)
    tf = b["tool_fields"]
    cid = tf["customer_id"]
    cid_var = cid or "customer_id"
    close = tools.get("close_call") or {}
    out_field, reason_field = tf["close_call"]["outcome"], tf["close_call"]["reason"]
    outcomes = list((close.get("request", {}).get(out_field) or {}).get("enum") or [])
    text = "\n\n".join(f"===== DOCUMENT {i + 1}: {d.get('name', '')} =====\n{d.get('text', '')}" for i, d in enumerate(docs))[:MAX_DOC_CHARS]

    nodes = {"setup": code_node("setup", codegen.embed({}, SETUP), [tr("call", "always")])}
    exits = []
    for o, r in closings(docs, outcomes):
        name = "end_" + re.sub(r"[^a-z0-9_]", "_", (o + ("_" + r if r else "")).lower())
        nodes[name] = code_node(name, codegen.embed({"o": o, "r": r}, "vars['outcome'] = CFG['o']\nvars['reason'] = CFG['r']\n", snippets=()), [tr("final_end", "always")])
        exits.append(tool_t(name, f"The call is over and, by the closing table of the specification, it ends with outcome {o}" + (f" and reason {r}." if r else " (no reason).")))
    offered = [n for n in TOOL_NAMES if n in tools and n != "close_call"]
    task = ("You are making the call that the specification in your instructions describes. It is your only source of rules: follow it from the first "
            "sentence to the closing, in its order.\n"
            "Today is {{today_spoken}} ({{today_iso}}). Never work out a weekday or a date yourself; read it from this calendar:\n{{calendar_text}}\n"
            f"The bank's tools are: {', '.join(offered)}. Call a tool whenever the specification says so, one tool call per message, and send every value "
            "exactly in the form the tool asks for. Product ids, amounts and other facts come only from tool results: never invent one.\n"
            "After every tool result, speak to the customer. Never say that something was done unless its tool result says so.\n"
            "When the call is over, first say everything the specification requires at the end except the goodbye, then call the closing tool that matches "
            "the specification's closing table (the tools whose description starts with 'The call is over'). The system says the goodbye itself. "
            "Never end the call in any other way.")
    nodes["call"] = {"name": "call", "node_type": "conversation", "on_enter": {"type": "llm"}, "on_enter_first_entry_only": True, "task_message": task,
                     "tools": [_tool(n, tools[n], cid, cid_var) for n in offered], "max_node_turns": 80, "max_turn_transition": "final_end",
                     "transitions": exits or [tool_t("final_end", "The call is over")]}
    nodes["final_end"] = {"name": "final_end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                          "terminal": {"type": "function", "function": {"name": "call_finished", "handler": "__function__:end_call",
                                       "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"},
                                                                                      "spoken_message": {"type": "string", "default": "Thank you for your time. Goodbye."}}}}}}
    lifecycle = []
    if close:
        body = {cid: {"type": "string", "default": "{{" + cid_var + "}}"}} if cid else {}
        if out_field:
            body[out_field] = {"type": "string", "default": "{{outcome}}", "description": "How the call ended, by the closing table of the specification."}
            if outcomes:
                body[out_field]["enum"] = outcomes
        if reason_field:
            body[reason_field] = {"type": "string", "default": "{{reason}}", "description": "The reason the closing table lists for that outcome; leave out when it lists none."}
        pre = (f"try:\n    b = config.get('body')\n    if isinstance(b, dict) and str(b.get({(reason_field or 'reason')!r}) or '').strip() in ('', 'none'):\n"
               f"        b.pop({(reason_field or 'reason')!r}, None)\nexcept Exception:\n    pass\n")
        lifecycle.append({"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 0, "alwaysRunsAt": ["end_of_call"]},
                          "function": {"name": "close_call", "handler": "__function__:api_call", "description": "Record how the call ended.",
                                       "parameters": {"type": "object", "properties": {
                                           "url": {"type": "string", "default": close["url"]}, "method": {"type": "string", "default": close["method"]}, "headers": HDR,
                                           "body": {"type": "object", "required": [out_field] if out_field else [], "properties": body}}}},
                          "pre_process_code": pre})
    system = ("You are a bank's phone agent on an outbound call. Speak the language of the specification below. Every turn is one or two short spoken "
              "sentences, no lists, no markdown. The specification is the bank's own documents, in order; where a later document changes a rule of an "
              "earlier one, the later one wins.\n\nSPECIFICATION\n" + text)
    wf = {"initial_node": "setup", "system_prompt": system, "tools": lifecycle, "global_nodes": {}, "nodes": nodes}
    shim = {"call_variables": [{"name": cid_var, "role": "customer_id", "meaning": ""}]}
    return wf, shim


def selftest(wf):
    """The code this agent carries compiles and runs on empty and on odd variables. A list of problems."""
    problems = []
    for name, n in wf["nodes"].items():
        for a in n.get("pre_actions") or []:
            src = (a.get("function", {}).get("parameters", {}).get("properties", {}).get("code") or {}).get("default")
            if src is None:
                continue
            for vars_ in ({}, {"now": "2026-10-16T09:30"}, {"x": None, "system.iso_utc_now": "2026-01-01T00:00:00Z", "t": "2027-12-31 23:59"}):
                try:
                    exec(src, {"vars": dict(vars_)})
                except Exception as e:
                    problems.append(f"{name}: raised {e!r}")
    for t in (wf["nodes"].get("call", {}).get("tools") or []) + (wf.get("tools") or []):
        for k in ("pre_process_code", "post_process_code"):
            if t.get(k):
                for payload in ({"data": {"ok": True}, "header": {}}, {"weird": 1}, None):
                    try:
                        exec(t[k], {"vars": {}, "result": payload, "config": {"body": {"outcome": "x", "reason": ""}}})
                    except Exception as e:
                        problems.append(f"{t['function']['name']}.{k}: raised {e!r}")
    return problems
