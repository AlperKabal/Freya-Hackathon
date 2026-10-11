"""A phone agent for a call the SPEC cannot hold: any service API, any kind of call, any language.

    design = await read_case(docs, tools, trace)        # one model call: the documents -> the call's script
    wf, shim = assemble(design, tools, variables)       # the script and every service of the tool API -> a workflow

The SPEC (spec_schema.py) describes one kind of call: the bank rings, checks identity and takes payment promises
through seven fixed tools. A pack of documents can describe another call altogether (the customer rings, other
services, another language). The builder still has to end with an agent that follows those documents, so:

- the Reader reads every document and writes the script of the call: what the agent says first, the rules in the
  order of the call, what each service is for and what each of its answers means, and how the call can end. Where
  documents disagree it decides which one holds (the later one, the one that corrects another) and says so;
- this module puts that script on the platform: one conversation step, every operation of the tool API as a tool
  the model may call, a code step that gives the call's date, and one closing step per way the call can end.

Nothing here knows a case. The services, their fields and paths come from the tool API; the words and the rules come
from the Reader's script of the documents.
"""
import json, re

from builder import codegen
from builder.generate import HDR, code_node, tool_t, tr
from builder.llm import ask_json

MAX_DOC_CHARS = 420000          # what one Reader call is given at most; longer packs lose the end of their largest documents

READER_SYSTEM = """You design a phone agent from a bank's own documents. The agent runs on a voice platform as ONE conversation step: a language model that talks with the customer and may call the bank's services (HTTP tools). You write that agent's complete instructions.

You are given every document of the pack and the list of services (name, method, path, request fields, response fields). Read all of it. The documents were written at different times and may disagree: a later document, a correction, a mail or meeting note that changes an earlier rule wins over the older text; a test environment's rules describe test data, not new behaviour. Decide every such conflict and list it.

Reply with ONE JSON object and nothing else:
{
 "language": "the language the calls are held in, in English (for example Turkish)",
 "role": "one sentence: who the agent is and what the call is for",
 "variables": ["the names of the variables every call starts with, exactly as the documents write them"],
 "first_words": "what the agent says first, in the call's language. Empty string when the agent must first call a service and speak only after its answer",
 "script": "the complete rules of the call, as numbered steps in English, in the order of the call. Every sentence the agent says is given in the call's language, word for word where a document prescribes the words (announcements, required notices). Cover every branch the documents describe: each decision, each service call with the exact fields to send and where each value comes from, what to say for each possible answer of a service (also errors and empty lists), how numbers, amounts, currencies and dates are spoken, what the agent must never do or say, and what to do when the customer asks for something the documents do not allow.",
 "services": [{"name": "exactly as in the list", "when": "when to call it", "send": "which value goes into each field", "answers": "what each kind of answer means and what the agent says or does next, including each HTTP error status the documents mention"}],
 "endings": [{"id": "short_snake_case", "when": "when the call ends this way", "last_words": "the agent's final sentence, in the call's language"}],
 "never": ["things the agent must never say or do"],
 "decided": [{"conflict": "what two documents say", "holds": "which one holds and why"}]
}

Rules for the script:
- The agent knows only what its instructions and the services tell it. Put every fact it needs into the script: do not refer to the documents ("as in section 4"), restate the rule.
- A value from a service is said exactly as the service gave it. The agent never invents an amount, a date, a card or an address.
- The call's variables are known from the first moment. The agent never asks the customer for them.
- Spoken style: one or two short sentences per turn, no lists, no markdown, digits and codes said the way the documents ask.
- "endings" lists every way the call ends (the customer is done, handed to a person, a service problem, ...). Each needs its own id and last words."""


def pack_text(docs, limit=MAX_DOC_CHARS):
    """All documents as one text, each under its own name. When the pack is longer than the limit, the longest
    documents are cut at the end, never the short ones."""
    docs = [d for d in docs if str(d.get("text") or "").strip()]
    budget = limit
    out = {}
    for i, d in enumerate(sorted(docs, key=lambda d: len(d["text"]))):
        share = budget // (len(docs) - i)
        text = d["text"] if len(d["text"]) <= share else d["text"][:share] + "\n[... cut: the document is longer]"
        out[id(d)] = text
        budget -= len(text)
    return "\n\n".join(f"===== DOCUMENT: {d.get('path') or d.get('name')} =====\n{out[id(d)]}" for d in docs)


def services_text(tools):
    lines = []
    for name, t in tools.items():
        req = ", ".join(f"{k} ({v.get('type', 'string')}{', one of ' + '|'.join(map(str, v['enum'])) if v.get('enum') else ''}{', required' if k in t.get('required', []) else ''})"
                        for k, v in t["request"].items()) or "no fields"
        resp = ", ".join(t["response"]) or "not described"
        lines.append(f"- {name}: {t['method']} {t['url']}\n    {t.get('summary', '')}\n    request: {req}\n    response: {resp}")
    return "\n".join(lines) or "(no services)"


async def read_case(docs, tools, trace=None):
    prompt = (pack_text(docs) + "\n\n===== THE SERVICES THE AGENT CAN CALL =====\n" + services_text(tools) + "\n\nWrite the JSON object now.")
    design = await ask_json(READER_SYSTEM, prompt, "Reader: the pack's documents -> the call's script", trace)
    return clean(design)


def clean(design):
    """The Reader's answer in the shape assemble() reads, whatever was left out or mistyped."""
    d = design if isinstance(design, dict) else {}
    text = lambda v: v.strip() if isinstance(v, str) else ("\n".join(str(x) for x in v) if isinstance(v, list) else "")
    out = {"language": text(d.get("language")) or "the language of the documents", "role": text(d.get("role")), "first_words": text(d.get("first_words")),
           "script": text(d.get("script")), "services": [], "endings": [], "never": [text(x) for x in d.get("never") or [] if text(x)],
           "variables": [v for v in d.get("variables") or [] if isinstance(v, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v)],
           "decided": [x for x in d.get("decided") or [] if isinstance(x, dict)]}
    for s in d.get("services") or []:
        if isinstance(s, dict) and text(s.get("name")):
            out["services"].append({k: text(s.get(k)) for k in ("name", "when", "send", "answers")})
    seen = set()
    for e in d.get("endings") or []:
        if not isinstance(e, dict):
            continue
        eid = re.sub(r"[^a-z0-9_]+", "_", text(e.get("id")).lower()).strip("_") or f"ending_{len(out['endings']) + 1}"
        if eid in seen:
            continue
        seen.add(eid)
        out["endings"].append({"id": eid, "when": text(e.get("when")), "last_words": text(e.get("last_words"))})
    if not out["endings"]:
        out["endings"] = [{"id": "done", "when": "The call is over.", "last_words": ""}]
    return out


SETUP = """
try:
    now = None
    for k in list(vars.keys()):
        if str(k).startswith(('system.', 'call.')):
            continue
        v = str(vars.get(k) or '')
        if _re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{1,2}:[0-9]{2}', v):       # the call's own clock, whatever the variable is called
            now = parse_now(v)
            break
    if not now:
        now = _dt.datetime.now()
    today = now.date()
    vars['today_iso'] = today.isoformat()
    vars['now_hhmm'] = now.strftime('%H:%M')
    vars['today_weekday'] = WEEKDAYS[today.weekday()].capitalize()
    vars['calendar_text'] = '; '.join(WEEKDAYS[(today + _dt.timedelta(days=j)).weekday()].capitalize()[:3] + ' ' + (today + _dt.timedelta(days=j)).isoformat() for j in range(-7, 43))
except Exception:
    vars['today_iso'] = ''
    vars['now_hhmm'] = ''
    vars['today_weekday'] = ''
    vars['calendar_text'] = ''
vars['farewell'] = ''
"""

# Before the request: a value the model gave for a {name} in the path goes into the path; a GET or DELETE carries
# its other values in the query string. After it: the model is told the HTTP status and that it must go on.
PRE = """
try:
    import urllib.parse as _up
    b = config.get('body')
    if not isinstance(b, dict):
        b = dict()
    url = str(config.get('url') or '')
    for name in _re.findall(r'[{]([A-Za-z_][A-Za-z0-9_]*)[}]', url):
        if b.get(name) is not None:
            url = url.replace(chr(123) + name + chr(125), _up.quote(str(b.pop(name)), safe=''))
    if str(config.get('method') or '').upper() in ('GET', 'DELETE'):
        q = dict((k, v) for k, v in b.items() if v is not None and v != '')
        if q:
            url = url + ('&' if '?' in url else '?') + _up.urlencode(q)
        b = dict()
    config['url'] = url
    config['body'] = b
except Exception:
    pass
"""

POST = """
try:
    if isinstance(result, dict):
        result.pop('header', None)
        code = result.get('status_code')
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict(value=d)
            result['data'] = d
        d['http_status'] = code
        d['what_to_do_next'] = ('This is the service answer (HTTP ' + str(code) + '). Do what your instructions say for this answer: speak to the customer or call the next service now. '
                                'Never stay silent, and never say something worked or exists unless this answer says so.')
except Exception:
    pass
"""


def _tool(name, spec, variables):
    props, required = {}, []
    fields = dict(spec["request"])
    for p in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", spec["url"]):          # a value in the path is a value the caller of the tool gives
        fields.setdefault(p, {"type": "string", "enum": [], "description": f"The {p} for the path of this service."})
        required.append(p)
    for field, f in fields.items():
        if field in variables:                                                   # a call variable: the workflow sends it, the model never sees it
            props[field] = {"type": "string", "default": "{{" + field + "}}"}
            continue
        kind = f.get("type") if f.get("type") in ("string", "number", "integer", "boolean") else "string"
        p = {"type": kind, "default": "{{m_" + re.sub(r"[^A-Za-z0-9_]", "_", name) + "_" + field + "}}",      # a name nothing sets: the model fills the field
             "description": (f.get("description") or field) + (" One of: " + ", ".join(map(str, f["enum"])) + "." if f.get("enum") else "")}
        if f.get("enum"):
            p["enum"] = list(f["enum"])
        props[field] = p
    required += [r for r in spec.get("required", []) if r not in required]
    return {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 1},
            "function": {"name": name, "handler": "__function__:api_call", "description": (spec.get("summary") or name) + " CALL it when your instructions say so.",
                         "parameters": {"type": "object", "properties": {
                             "url": {"type": "string", "default": spec["url"]}, "method": {"type": "string", "default": spec["method"]}, "headers": HDR,
                             "body": {"type": "object", "required": [r for r in required if r not in variables], "properties": props}}}},
            "pre_process_code": codegen.scrubbed("import re as _re\n" + PRE), "post_process_code": codegen.scrubbed(POST)}


def tool_names(tools):
    """A function name the platform accepts for every operation: letters, digits and underscores."""
    out, used = {}, set()
    for name in tools:
        n = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "service"
        n = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", n).lower() if not re.search(r"_", n) else n.lower()
        base, k = n, 2
        while n in used:
            n, k = f"{base}_{k}", k + 1
        used.add(n)
        out[name] = n
    return out


def assemble(design, tools, variables=None):
    """The workflow, and the little of a SPEC that verify.lint reads."""
    variables = list(variables if variables is not None else design.get("variables") or [])
    names = tool_names(tools)
    notes = {s["name"]: s for s in design["services"]}
    nodes = {"setup": code_node("setup", codegen.embed({}, SETUP), [tr("talk", "always")])}
    exits = []
    for e in design["endings"]:
        node = "end_" + e["id"]
        nodes[node] = code_node(node, codegen.embed({"say": e["last_words"]}, "vars['farewell'] = CFG['say']\nvars['ending'] = CFG['id'] if 'id' in CFG else ''\n", snippets=()),
                                [tr("final_end", "always")])
        exits.append(tool_t(node, f"The call ends this way: {e['when']} Call it only after you have said everything else your instructions require; the system then says the last words: \"{e['last_words']}\""))
    service_lines = []
    for name, t in tools.items():
        n = notes.get(name) or notes.get(names[name]) or {}
        service_lines.append(f"- {names[name]}: {n.get('when') or t.get('summary') or ''}"
                             + (f"\n  Send: {n['send']}" if n.get("send") else "") + (f"\n  Answers: {n['answers']}" if n.get("answers") else ""))
    task = ("THE CALL\n" + design["script"]
            + ("\n\nSERVICES (tools). Call one whenever the steps above say so, one call per message. Every tool result carries http_status and a what_to_do_next line: follow it.\n"
               + "\n".join(service_lines) if tools else "")
            + ("\n\nNEVER\n" + "\n".join("- " + x for x in design["never"]) if design["never"] else "")
            + "\n\nDATES. The call takes place on {{today_weekday}} {{today_iso}} at {{now_hhmm}}. Never use another clock and never work out a weekday yourself: "
              "read it here (three-letter English weekday, then the date): {{calendar_text}}. Say dates in the call's language, with the month as a word."
            + "\n\nENDING THE CALL. When the call is over, call the one ending tool that fits. Do not say the goodbye yourself: the system says the last words. "
              "Never end the call in any other way, and never end a turn with nothing: after every tool result speak or call the next tool.")
    first = design["first_words"]
    nodes["talk"] = {"name": "talk", "node_type": "conversation",
                     "on_enter": {"type": "tts", "text": first} if first else {"type": "llm"}, "on_enter_first_entry_only": True,
                     "task_message": task, "tools": [_tool(names[n], t, variables) for n, t in tools.items()],
                     "max_node_turns": 80, "max_turn_transition": "final_end", "transitions": exits}
    nodes["final_end"] = {"name": "final_end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                          "terminal": {"type": "function", "function": {"name": "call_finished", "handler": "__function__:end_call",
                                       "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"},
                                                                                      "spoken_message": {"type": "string", "default": "{{farewell}}"}}}}}}
    system = (f"You are a phone agent: {design['role']} Speak {design['language']} with the customer, always. Every turn is one or two short spoken sentences, "
              "no lists, no markdown. Your instructions are complete: follow them step by step and add nothing of your own. A fact you were not given by your "
              "instructions or by a service answer you do not have: say so instead of guessing.")
    wf = {"initial_node": "setup", "system_prompt": system, "tools": [], "global_nodes": {}, "nodes": nodes}
    shim = {"call_variables": [{"name": v, "role": "other", "meaning": ""} for v in variables]}
    return wf, shim


def problems(wf, shim, tools):
    """Local checks of a workflow built here: structure (verify.lint, without the checks that belong to the SPEC's
    kind of call) and every piece of code run on empty and on odd input."""
    from builder import verify
    in_path = {x for t in tools.values() for x in re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", t["url"])}
    out = [p for p in verify.lint(wf, shim, tools) if "lifecycle" not in p and not any(f"body field {x} is not in the tool API" in p for x in in_path)]
    for name, n in wf["nodes"].items():
        src = verify.code_of(n)
        if src is not None:
            for vars_ in ({}, {"now": "2026-10-12T10:30:00+03:00"}, {"x": None, "t": "2027-12-31 23:59"}):
                try:
                    exec(src, {"vars": dict(vars_)})
                except Exception as e:
                    out.append(f"{name}: raised {e!r}")
    for t in wf["nodes"]["talk"]["tools"]:
        url = t["function"]["parameters"]["properties"]["url"]["default"]
        for body in ({}, {"a": 1, "b": "x y"}, None):
            try:
                exec(t["pre_process_code"], {"vars": {}, "config": {"url": url, "method": t["function"]["parameters"]["properties"]["method"]["default"], "body": body}})
            except Exception as e:
                out.append(f"{t['function']['name']} pre-hook: raised {e!r}")
        for result in ({"status": "success", "status_code": 200, "data": {"a": 1}, "header": {}}, {"status": "error", "status_code": 404, "data": None}, {"weird": 1}, None):
            try:
                exec(t["post_process_code"], {"vars": {}, "result": result})
            except Exception as e:
                out.append(f"{t['function']['name']} post-hook: raised {e!r}")
    return out
