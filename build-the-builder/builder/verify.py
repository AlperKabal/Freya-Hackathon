"""Stage 6: checks that need no practice cases, so they work on any brief.

    problems = lint(wf, spec, tools)          # structure and platform rules
    problems = run_snippets(wf, spec)         # every code node and hook executed locally on sample data

Each returns a list of strings; empty means passed.
"""
import copy, datetime, json, re

TOOL_CALL = re.compile(r"transition_to_([a-zA-Z0-9_]+)")
VAR = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)(?::json)?\}\}")


def _walk(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items(): yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x): yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, x


def code_of(node):
    """(label, source) of the code_exec snippet of a code node."""
    for a in node.get("pre_actions") or []:
        if a.get("function", {}).get("handler") == "__function__:code_exec":
            return a["function"]["parameters"]["properties"]["code"]["default"]
    return None


def hooks(wf):
    """(label, kind, source) of every pre/post hook."""
    out = []
    for name, n in wf["nodes"].items():
        for t in (n.get("tools") or []) + (n.get("pre_actions") or []):
            for k in ("pre_process_code", "post_process_code"):
                if t.get(k): out.append((f"{name}.{t['function']['name']}.{k}", k, t[k]))
    for t in wf.get("tools") or []:
        for k in ("pre_process_code", "post_process_code"):
            if t.get(k): out.append((f"workflow.{t['function']['name']}.{k}", k, t[k]))
    return out


def lint(wf, spec, tools):
    p = []
    nodes = wf["nodes"]
    for path, v in _walk(wf):
        if v is None: p.append(f"null at {path}")
    if wf["initial_node"] not in nodes: p.append("initial_node does not exist")
    call_vars = {v["name"] for v in spec["call_variables"]}
    written = set(call_vars)
    for n in nodes.values():
        src = code_of(n) or ""
        written |= set(re.findall(r"vars\['([a-zA-Z_][a-zA-Z0-9_]*)'\]\s*=", src))
        written |= {"p%d_id" % i for i in range(1, 10)} | {"p%d_words" % i for i in range(1, 10)} if "'p' + n + '_id'" in src else set()
    for name, n in nodes.items():
        t = n.get("node_type")
        if n.get("name") != name: p.append(f"{name}: name differs from key")
        if t != "conversation" and n.get("tools"): p.append(f"{name}: tools on a {t} node are dropped by the platform")
        if t == "conversation" and n.get("pre_actions"): p.append(f"{name}: pre_actions on a conversation node are dropped by the platform")
        targets = [x["target_node"] for x in n.get("transitions") or []]
        for k in ("passthrough_default_transition", "max_turn_transition"):
            if n.get(k): targets.append(n[k])
        for x in targets:
            if x not in nodes and x != "__previous__": p.append(f"{name}: transition to missing node {x}")
        if n.get("passthrough"):
            tr = n.get("transitions") or []
            if not tr or tr[-1].get("condition", {}).get("operator") != "always": p.append(f"{name}: passthrough node must end with an always transition")
        if t == "end_call" and n.get("transitions"): p.append(f"{name}: end_call node has transitions")
        # every transition_to_X the prompt mentions must be a tool-call transition of this node
        offered = {x["target_node"] for x in n.get("transitions") or [] if x.get("is_tool_call")}
        for m in set(TOOL_CALL.findall(n.get("task_message") or "")):
            if m not in offered: p.append(f"{name}: prompt mentions transition_to_{m} but the node has no such tool-call transition")
        # fixed spoken lines may only use variables that exist
        spoken = [((n.get("on_enter") or {}).get("text") or "")]
        term = (n.get("terminal") or {}).get("function", {}).get("parameters", {}).get("properties", {})
        spoken.append((term.get("spoken_message") or {}).get("default", ""))
        for line in spoken:
            for v in VAR.findall(line):
                if v not in written: p.append(f"{name}: spoken line uses {{{{{v}}}}}, which nothing writes")
        src = code_of(n)
        if src is not None:
            if "{{" in src or "}}" in src: p.append(f"{name}: code contains a double brace")
            try: compile(src, name, "exec")
            except SyntaxError as e: p.append(f"{name}: code does not compile: {e}")
    for label, kind, src in hooks(wf):
        if "{{" in src or "}}" in src: p.append(f"{label}: hook contains a double brace")
        try: compile(src, label, "exec")
        except SyntaxError as e: p.append(f"{label}: hook does not compile: {e}")
    # reachability and every path ends
    seen, todo = set(), [wf["initial_node"]]
    edges = {k: {x["target_node"] for x in n.get("transitions") or []} | {n[k2] for k2 in ("passthrough_default_transition", "max_turn_transition") if n.get(k2)} for k, n in nodes.items()}
    while todo:
        k = todo.pop()
        if k in seen or k not in nodes: continue
        seen.add(k); todo += list(edges[k])
    for k in nodes:
        if k not in seen: p.append(f"{k}: not reachable from the initial node")
    ends = {k for k, n in nodes.items() if n.get("node_type") == "end_call"}
    reach_end = set(ends)
    changed = True
    while changed:
        changed = False
        for k, e in edges.items():
            if k not in reach_end and e & reach_end: reach_end.add(k); changed = True
    for k in nodes:
        if k not in reach_end: p.append(f"{k}: no path to an end node")
    # tools: url, fields and enum values come from the tool API file
    by_url = {t["url"]: t for t in tools.values()}
    for name, n in list(nodes.items()) + [("workflow", {"tools": wf.get("tools") or []})]:
        for fn in (n.get("tools") or []) + (n.get("pre_actions") or []):
            f = fn.get("function", {})
            if f.get("handler") != "__function__:api_call": continue
            props = f["parameters"]["properties"]
            api = by_url.get(props["url"]["default"])
            if not api: p.append(f"{name}.{f['name']}: url is not in the tool API"); continue
            for field, spec_ in props["body"]["properties"].items():
                if field not in api["request"]: p.append(f"{name}.{f['name']}: body field {field} is not in the tool API"); continue
                allowed = api["request"][field]["enum"]
                for e in spec_.get("enum") or []:
                    if allowed and e not in allowed: p.append(f"{name}.{f['name']}.{field}: enum value {e} is not in the tool API")
                d = spec_.get("default")
                if allowed and isinstance(d, str) and "{{" not in d and d not in allowed: p.append(f"{name}.{f['name']}.{field}: baked value {d} is not in the tool API")
            for r in api["required"]:
                if r not in props["body"]["properties"]: p.append(f"{name}.{f['name']}: required field {r} is missing")
    if not any((t.get("config") or {}).get("alwaysRunsAt") == ["end_of_call"] for t in wf.get("tools") or []):
        p.append("no end_of_call lifecycle tool")
    if "agent_config" in wf: p.append("agent_config must be left out")
    return p


# ---------------------------------------------------------------- local execution

def sample_products(spec, n=3):
    """Products shaped like the tool API's product list, one per type, cycling through the bands."""
    pf, out = spec["account"]["product_fields"], []
    types, bands = spec["account"]["product_types"], spec["bands"]
    for i in range(n):
        t, b = types[i % len(types)], bands[i % len(bands)]
        p = {pf["id"]: f"x{i + 1}", pf["type"]: t["type"], pf["past_due"]: 400.0 + i, pf["days_late"]: b["days_late_max"], t["floor_field"]: 100.0}
        for ph in re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", t["spoken_name"]):
            p.setdefault(ph, "9" * 4)
        out.append(p)
    return out


def _run(src, vars_, extra=None):
    env = {"vars": vars_}
    env.update(extra or {})
    exec(src, env)
    return env


def run_snippets(wf, spec, days=None):
    """Execute every code node and hook on sample data and on several calendar days. Exceptions are failures:
    platform code must never raise."""
    p = []
    now_var = next(v["name"] for v in spec["call_variables"] if v["role"] == "now")
    days = days or _sample_days(spec)
    nodes = wf["nodes"]
    for day in days:
        base = {now_var: day + "T12:00"}
        for name, n in nodes.items():
            src = code_of(n)
            if src is None: continue
            for variant in ("list", "json", "empty"):
                v = copy.deepcopy(base)
                prods = sample_products(spec, min(3, int(spec["account"]["max_products"])))
                v["acct_items"] = prods if variant == "list" else json.dumps(prods) if variant == "json" else []
                v.update({"cb_day_text": "tomorrow", "cb_time": "11:00", "n_products": "1", "res_1": "promise"})
                try:
                    _run(src, v)
                except Exception as e:
                    p.append(f"{name} on {day} ({variant}): raised {e!r}")
                    continue
                if name == "prepare_deal" and variant != "empty":
                    if v.get("deal_state") != "ready": p.append(f"prepare_deal on {day}: deal_state={v.get('deal_state')!r}")
                    for k in ("deal_intro", "deal_facts", "calendar_text"):
                        if not v.get(k): p.append(f"prepare_deal on {day}: {k} empty")
                    if "None" in v.get("deal_facts", ""): p.append(f"prepare_deal on {day}: facts contain None")
                if name == "setup":
                    for k in ("outcome", "reason", "farewell", "today_iso"):
                        if k not in v: p.append(f"setup on {day}: {k} not written")
    for label, kind, src in hooks(wf):
        for result in ({"status": "success", "data": {"ok": True, "verified": True}, "header": {}}, {"status": "error", "data": {"ok": False}}, {"weird": 1}, None):
            try:
                if kind == "post_process_code":
                    _run(src, {"n_products": "1"}, {"result": copy.deepcopy(result)})
                else:
                    _run(src, {}, {"config": {"body": {"x": "1", "outcome": "a"}}})
            except Exception as e:
                p.append(f"{label}: raised {e!r} on {result!r}")
    return p


def _sample_days(spec):
    """Calendar days that stress the rules: today, Fridays, weekends, the day before each holiday, month ends."""
    start = datetime.date.today()
    out = {start}
    for i in range(1, 60):
        d = start + datetime.timedelta(days=i)
        if d.weekday() in (4, 5, 6) or (d + datetime.timedelta(days=1)).day == 1: out.add(d)
    for h in spec["calendar"]["holidays"]:
        try:
            d = datetime.date.fromisoformat(h); out |= {d - datetime.timedelta(days=1), d}
        except ValueError:
            pass
    return sorted(x.isoformat() for x in out)[:40]
