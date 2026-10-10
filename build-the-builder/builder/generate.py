"""Stage 5: SPEC + tool specs -> workflow JSON. Deterministic: the same SPEC always gives the same workflow.

v1 design (dev/ARCHITECTURE.md, migration plan): opening, third party, identity, account and closing are built from
mechanisms that passed the practice cases; the negotiation is one LLM node per product count with per-product
tools whose product id is baked. Every sentence, number, name and table comes from the SPEC or the tool API file.

    wf = build(spec, tools)          # tools = ingest.parse_openapi(path)["tools"]
"""
import json, re

from builder import codegen

HDR = {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}}
PH = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


# ---------------------------------------------------------------- small JSON builders

def eq(var, *vals):
    return {"logic": "or", "conditions": [{"variable": var, "operator": "equals", "operand": v} for v in vals]}


def truthy(*variables):
    return {"logic": "or", "conditions": [{"variable": v, "operator": "equals", "operand": o} for v in variables for o in ("true", "True")]}


def tr(target, desc, cond=None):
    return {"target_node": target, "description": desc, "condition": cond or {"operator": "always"}}


def tool_t(target, desc):
    return {"target_node": target, "description": desc, "is_tool_call": True, "condition": {"operator": "matches_intent", "description": desc}}


def code_node(name, src, transitions):
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": transitions[-1]["target_node"],
            "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                             "parameters": {"type": "object", "properties": {"code": {"type": "string", "default": src},
                                                                            "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": transitions}


def api_node(name, fn, transitions, mapping=None, say=""):
    return {"name": name, "node_type": "api_request", "passthrough": True, "passthrough_default_transition": transitions[-1]["target_node"],
            "on_enter": {"type": "tts", "text": say} if say else {"type": "silent"}, "disable_inactivity_monitor": True,
            "pre_actions": [fn], "response_mapping": mapping or [], "transitions": transitions}


def times(n):
    n = int(n)
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def extr(name, desc, enum=None, pattern=None, conf=0.7):
    e = {"name": name, "type": "string", "description": desc, "min_confidence": conf}
    if enum: e["enum_values"] = list(enum)
    if pattern: e["validation_pattern"] = pattern
    return e


# ---------------------------------------------------------------- generator

class Gen:
    def __init__(self, spec, tools):
        self.s, self.t = spec, tools
        self.tf = spec["tool_fields"]
        self.var = {v["role"]: v["name"] for v in spec["call_variables"] if v["role"] in ("customer_id", "now")}
        self.call_vars = [v["name"] for v in spec["call_variables"]]
        self.maxp = max(1, int(spec["account"]["max_products"]))
        self.notes = bool(spec["notes"]["enabled"])
        self.multi = bool(spec["multi_product"]["enabled"]) and self.maxp > 1
        self.nodes = {}
        self.exits = {}                      # exit id -> (outcome, reason, farewell)

    # --- text helpers
    def ph(self, text):
        """SPEC single-brace call-variable placeholders -> platform placeholders."""
        return PH.sub(lambda m: "{{" + m.group(1) + "}}" if m.group(1) in self.call_vars else m.group(0), text or "")

    def addr(self):
        return self.ph(self.s["addressing"])

    def farewell(self, *parts):
        return " ".join(p.strip() for p in list(parts) + [self.s["closing"]["farewell"]] if p and p.strip())

    # --- tools
    def api_fn(self, tool, body, required, desc="", retries=0, pre="", post="", name=None):
        props = {self.tf["customer_id"]: {"type": "string", "default": "{{" + self.var["customer_id"] + "}}"}}
        props.update(body)
        fn = {"type": "function", "config": {"timeoutMs": 12000, "maxRetries": retries},
              "function": {"name": name or tool, "handler": "__function__:api_call",
                           "parameters": {"type": "object", "properties": {
                               "url": {"type": "string", "default": self.t[tool]["url"]},
                               "method": {"type": "string", "default": self.t[tool]["method"]},
                               "headers": HDR,
                               "body": {"type": "object", "required": required, "properties": props}}}}}
        if desc: fn["function"]["description"] = desc
        if pre: fn["pre_process_code"] = pre
        if post: fn["post_process_code"] = post
        return fn

    def enum(self, tool, role):
        field = self.tf[tool][role]
        return list((self.t[tool]["request"].get(field) or {}).get("enum") or [])

    def ftype(self, tool, role):
        return (self.t[tool]["request"].get(self.tf[tool][role]) or {}).get("type", "string")

    # --- code config shared by all code nodes
    def cfg(self, **extra):
        s = self.s
        c = codegen.date_config(s)
        c.update({
            "now_var": self.var["now"],
            "cb": s["third_party"]["callback"],
            "products_var": "acct_items",
            "products_field": s["account"]["products_field"],
            "pf": s["account"]["product_fields"],
            "types": {p["type"]: p for p in s["account"]["product_types"]},
            "maxp": self.maxp,
            "intro": s["account"]["statement_intro"],
            "per_product": s["account"]["statement_per_product"],
            "first_ask": s["negotiation"]["first_ask"],
            "first_ask_all": s["multi_product"]["first_ask_all"] if self.multi else "",
            "farewell": s["closing"]["farewell"],
            "after_success": s["recording"]["after_success_say"],
            "promise_outcome": s["outcomes"]["promise"],
            "multi_rule": s["outcomes"].get("multi") or {},
            "note_reasons": s["notes"]["reasons"],
            "default_outcome": s["opening"]["unclear"],
        })
        c.update(extra)
        return c

    def code(self, name, body, transitions, **extra):
        return code_node(name, codegen.embed(self.cfg(**extra), body), transitions)

    # --- exits: one code node per (outcome, reason, farewell), then the end node
    def exit(self, key, outcome, reason, farewell):
        node = "set_" + key
        if node not in self.nodes:
            body = (f"vars['outcome'] = CFG['o']\nvars['reason'] = CFG['r']\nvars['farewell'] = CFG['f']\n")
            self.nodes[node] = code_node(node, codegen.embed({"o": outcome, "r": reason, "f": farewell}, body, snippets=()), [tr("final_end", "always")])
        return node

    def situation_exit(self, sit, stage_key="after_identity", effect=None, branch=""):
        """Exit chain for a call-scope situation: its actions (engine-run), then the outcome node."""
        eff = effect or sit["effect"]
        ob = (eff.get("outcome_by_stage") or {}).get(stage_key)
        outcome, reason = (ob["outcome"], ob["reason"]) if ob else (eff["outcome"], eff["reason"])
        say = sit["say"] if sit["say_exact"] else ""
        if any(a["type"] == "transfer" for a in eff["actions"]):
            say = (say + " I am connecting you now.").strip()        # spoken after the transfer call ran
        key = f"{sit['id']}_{stage_key}" if eff.get("outcome_by_stage") else sit["id"]
        if branch:
            key += "_" + branch
        target = self.exit(key, outcome, reason, self.farewell(say))
        for i, a in reversed(list(enumerate(eff["actions"]))):
            if a["type"] == "transfer":
                name = f"do_{key}_transfer{i}"
                q = self.tf["transfer_to_agent"]["queue"]
                self.nodes[name] = api_node(name, self.api_fn("transfer_to_agent", {q: {"type": "string", "default": a["queue"]}}, [q]),
                                            [tr(target, "always")])
                target = name
        return target

    def stage_situations(self, stage):
        return sorted([x for x in self.s["situations"] if stage in x["stages"]], key=lambda x: -x["priority"])

    # ------------------------------------------------------------ nodes
    def setup(self):
        body = """
try:
    now = parse_now(vars.get(CFG['now_var']))
    vars['clock_ok'] = 'yes' if now else 'no'
    if not now:
        now = _dt.datetime.now()
    today = now.date()
    vars['today_iso'] = today.isoformat()
    vars['today_spoken'] = spoken(today)
    vars['now_hhmm'] = now.strftime('%H:%M')
    cb = CFG['cb']
    days = [today] if cb['include_today'] else []
    d = today
    for _ in range(int(cb['business_days_ahead'])):
        d = next_business_day(d, CFG)
        days.append(d)
    vars['cb_days_text'] = ', '.join(spoken(x) for x in days)
except Exception:
    vars['today_iso'] = ''
    vars['today_spoken'] = 'today'
    vars['now_hhmm'] = ''
    vars['cb_days_text'] = ''
vars['outcome'] = CFG['default_outcome']['outcome']
vars['reason'] = CFG['default_outcome']['reason']
vars['farewell'] = CFG['farewell']
vars['cb_feedback'] = ''
vars['cb_attempts'] = '0'
vars['cb_when_text'] = 'none'
vars['cb_day_found'] = ''
vars['cb_time_found'] = ''
vars['all_done'] = 'no'
vars['n_products'] = '0'
for i in range(1, int(CFG['maxp']) + 1):
    vars['res_' + str(i)] = 'none'
    vars['cp' + str(i) + '_fail'] = '0'
    vars['note' + str(i) + '_saved'] = ''
"""
        self.nodes["setup"] = self.code("setup", body, [tr("opening", "always")])

    def opening(self):
        o = self.s["opening"]
        sits = [x for x in self.stage_situations("opening")]
        enum_sits = [x for x in sits if x["threshold"] <= 1 and not x.get("offer")]
        tool_sits = [x for x in sits if x not in enum_sits]
        enum = ["confirmed", "someone_else"] + [x["id"] for x in enum_sits]
        desc = ("Who is on the line, judged from the person's LATEST reply. confirmed = only if they clearly confirm: "
                + "; ".join(o["confirmations"]) + ". someone_else = another person answered (not the one asked for). "
                + " ".join(f"{x['id']} = {x['trigger']} {x['not_this']}".strip() for x in enum_sits)
                + " Leave empty if unclear" + (": " + "; ".join(o["non_confirmations"]) if o["non_confirmations"] else "") + ", or a question.")
        words = ", ".join(self.s["opening"]["forbidden_before_identity"])
        task = (f"Your opening line was already spoken: it asked whether you are speaking with {self.addr()}. Wait for the answer. "
                f"Only these count as confirmation: {'; '.join(o['confirmations'])}. "
                + (f"These do NOT confirm: {'; '.join(o['non_confirmations'])}. " if o["non_confirmations"] else "")
                + ("If the person asks a question, answer it first in one short sentence, then ask again whether you are speaking with " + self.addr() + ". " if o["answer_question_first"] else
                   "If the confirmation is unclear, ask again whether you are speaking with " + self.addr() + ". ")
                + (f"Until identity is verified NEVER say these words, to anyone: {words}. " if words else "")
                + "If asked why you call, say you can explain after the security check. If someone else is on the line, say nothing about the reason. "
                + " ".join(self.sit_line(x) for x in tool_sits)
                + " Do not call any other tool in this step.")
        trans = [tr("identity", "The person confirmed they are the customer", eq("who", "confirmed"))]
        for x in enum_sits:
            trans.append(tr(self.situation_exit(x, "before_identity"), x["trigger"], eq("who", x["id"])))
        if self.s["third_party"]["enabled"]:
            trans.append(tr("third_party", "Someone else is on the line", eq("who", "someone_else")))
        for x in tool_sits:
            trans.append(tool_t(self.situation_exit(x, "before_identity"), self.sit_trigger(x)))
        unclear = self.exit("opening_unclear", o["unclear"]["outcome"], o["unclear"]["reason"], self.farewell())
        self.nodes["opening"] = {
            "name": "opening", "node_type": "conversation",
            "on_enter": {"type": "tts", "text": self.ph(o["first_sentence"] + " " + o["confirm_question"])},
            "on_enter_first_entry_only": True, "task_message": task,
            "extraction_schema": [extr("who", desc, enum=enum)],
            "max_node_turns": max(1, int(o["max_asks"])), "max_turn_transition": unclear,
            "transitions": trans}

    def sit_trigger(self, x):
        t = x["trigger"]
        if x["threshold"] > 1 and x["first_response"]:
            t += f" This applies only after you already did this once: {x['first_response']} and the customer insists ({x['threshold']} times in total)."
        return t

    def sit_line(self, x):
        line = f"If {x['trigger'][0].lower() + x['trigger'][1:]}"
        if x["threshold"] > 1 and x["first_response"]:
            line += f" The first time: {x['first_response']} If it happens {x['threshold']} times, call transition_to_" + "{node}" + "."
        else:
            line += " Call transition_to_{node}."
        if x["say"] and not x["say_exact"]:
            line += f" ({x['say']})"
        return line.replace("{node}", self.situation_exit(x, "before_identity" if "identity" in x["stages"] or "opening" in x["stages"] else "after_identity"))

    def third_party(self):
        tp, cb = self.s["third_party"], self.s["third_party"]["callback"]
        if not tp["enabled"]:
            return
        sits = [x for x in self.stage_situations("third_party") if x["threshold"] <= 1 and not x.get("offer")]
        scheduled = self.exit("callback_scheduled", cb["scheduled"]["outcome"], cb["scheduled"]["reason"], self.farewell())
        not_sched = self.exit("callback_not_scheduled", cb["not_scheduled"]["outcome"], cb["not_scheduled"]["reason"], self.farewell())
        window = (f"A callback is only possible on these days: {{{{cb_days_text}}}}, between {cb['window_start']} and {cb['window_end']}"
                  + (" (both included)" if cb["inclusive"] else "") + (", and later than now ({{now_hhmm}} today)" if cb["after_now"] else "") + ".")
        task = (f"The person on the line is NOT {self.addr()}. " + " ".join(tp["instructions"]) + " "
                + (window + " You need a day and a time. {{cb_feedback}} "
                   "There is no booking tool: the system books the callback by itself as soon as the person has given a day and a time that fit. "
                   "Never say that you booked it and never say that you cannot book it. " if cb["enabled"] else "")
                + f"The ONLY tool you may call is transition_to_{not_sched}, and only when the person cannot or will not give any time.")
        ex = []
        if cb["enabled"]:
            # one field for day and time together: a second field that fails to extract must not block the path
            ex.append(extr("cb_when_text", "When the customer can be reached: the day and the time of day, copied exactly as the person said them "
                           "(for example 'tomorrow morning around eleven', 'Friday at 3 pm'). Include a day or a time given in an earlier reply "
                           "if the latest reply gives only the other. Empty if no day and no time were named."))
        if sits:
            ex.append(extr("tp_event", " ".join(f"{x['id']} if {x['trigger']}" for x in sits) + " Otherwise empty.", enum=[x["id"] for x in sits]))
        trans = [tr(self.situation_exit(x, "before_identity"), x["trigger"], eq("tp_event", x["id"])) for x in sits]
        if cb["enabled"]:
            trans.append(tr("check_callback", "A day or a time was given", {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                {"variable": "cb_when_text", "operator": "is_set"}, {"variable": "cb_when_text", "operator": "not_equals", "operand": "none"}]}]}))
        trans.append(tool_t(not_sched, "The person cannot or will not give any callback time"))
        self.nodes["third_party"] = {"name": "third_party", "node_type": "conversation", "on_enter": {"type": "llm"}, "task_message": task,
                                     "extraction_schema": ex, "max_node_turns": 8, "max_turn_transition": not_sched, "transitions": trans}
        if not cb["enabled"]:
            return
        body = """
try:
    now = parse_now(vars.get(CFG['now_var'])) or _dt.datetime.now()
    today = now.date()
    cb = CFG['cb']
    lo = int(cb['window_start'][:2]) * 60 + int(cb['window_start'][3:])
    hi = int(cb['window_end'][:2]) * 60 + int(cb['window_end'][3:])
    allowed = [today] if cb['include_today'] else []
    d = today
    for _ in range(int(cb['business_days_ahead'])):
        d = next_business_day(d, CFG)
        allowed.append(d)
    said = str(vars.get('cb_when_text') or '')
    r = resolve_spoken_date(said, today, CFG)
    day = r['date'] if r['status'] == 'exact' else str(vars.get('cb_day_found') or '')
    hhmm = parse_spoken_time(said, lo, hi) or str(vars.get('cb_time_found') or '')
    vars['cb_day_found'] = day
    vars['cb_time_found'] = hhmm
    tries = int(str(vars.get('cb_attempts') or '0'))
    if not day or not hhmm:
        vars['cb_state'] = 'retry'
        vars['cb_feedback'] = ('The person gave the time but not the day. Ask on which day.' if hhmm else
                               'The person gave the day but not the time. Ask at what time.' if day else
                               'The day and the time were not clear. Ask for a day and a time.')
    else:
        dd = _dt.date.fromisoformat(day)
        hh, mm = int(hhmm[:2]), int(hhmm[3:])
        mins = hh * 60 + mm
        inside = (lo <= mins <= hi) if cb['inclusive'] else (lo < mins < hi)
        later = (not cb['after_now']) or _dt.datetime(dd.year, dd.month, dd.day, hh, mm) > now
        if dd in allowed and inside and later:
            vars['cb_state'] = 'valid'
            vars['cb_date_iso'] = day
            vars['cb_time_norm'] = hhmm
        else:
            tries += 1
            vars['cb_attempts'] = str(tries)
            vars['cb_day_found'] = ''
            vars['cb_time_found'] = ''
            if tries >= int(cb['max_asks']):
                vars['cb_state'] = 'fail'
            else:
                vars['cb_state'] = 'retry'
                vars['cb_feedback'] = 'The time the person offered is NOT possible. Say briefly when a callback is possible and ask once for another time.'
except Exception:
    vars['cb_state'] = 'retry'
    vars['cb_feedback'] = 'Ask for a day and a time.'
vars['cb_when_text'] = 'none'
"""
        self.nodes["check_callback"] = self.code("check_callback", body, [
            tr("schedule_cb", "valid", eq("cb_state", "valid")), tr(not_sched, "out of window again", eq("cb_state", "fail")), tr("third_party", "ask again")])
        f, ok = self.tf["schedule_callback"], self.s["identity"]["result_fields"]["ok"]
        self.nodes["schedule_cb"] = api_node("schedule_cb", self.api_fn("schedule_callback", {
            f["date"]: {"type": "string", "default": "{{cb_date_iso}}"}, f["time"]: {"type": "string", "default": "{{cb_time_norm}}"}}, [f["date"], f["time"]]),
            [tr(scheduled, "booked", truthy("cb_booked", "schedule_cb_response.data." + ok, "schedule_callback_response.data." + ok)), tr(not_sched, "the booking did not work")],
            mapping=[{"path": "data." + ok, "variable": "cb_booked"}])

    def identity(self):
        idn, rf = self.s["identity"], self.s["identity"]["result_fields"]
        qs = idn["questions"]
        qlist = " ".join(f"Question {i + 1} ({q['field']}): {q['ask']} Send the answer as {q['answer_format']}. {q['conversion']}" for i, q in enumerate(qs))
        hints = {h["value"]: h for h in idn["hints"]}
        post = f"""
try:
    if isinstance(result, dict):
        result.pop('header', None)
    d = result.get('data') if isinstance(result, dict) else None
    if isinstance(d, dict):
        hints = {json.dumps({k: v['instruction'] + (' This does NOT count as a wrong answer.' if not v['counts_as_wrong'] else '') for k, v in hints.items()})}
        hint = d.get({rf['hint']!r})
        if hint in hints:
            msg = hints[hint] + ' Then call verify_identity again.'
        elif str(d.get({rf['ok']!r})).lower() == 'false':
            msg = 'The value was not accepted and was not counted as a wrong answer. Ask the customer to say it again, then call verify_identity again.'
        elif str(d.get({rf['all_verified']!r})).lower() == 'true':
            msg = 'All answers are verified. Say a brief thank you only. Say nothing about the account yet.'
        elif str(d.get({rf['verified']!r})).lower() == 'true':
            msg = 'This answer is correct. Now ask the next security question that has not been answered correctly yet, in this order: ' + {json.dumps(' | '.join(q['ask'] for q in qs))} + '. Say nothing about the account.'
        else:
            left = d.get({rf['wrong_left']!r})
            if left is not None and str(left).strip() in ('0', '0.0'):
                msg = 'The check has ended. Say nothing about the account.'
            else:
                msg = 'That answer did not match. Say so briefly, do not reveal the right answer, and ask the same question again. Wrong answers left: ' + str(left) + '.'
        d['what_to_do_next'] = msg
except Exception:
    pass
"""
        types = {q["field"]: q["value_type"] for q in qs}
        pre = f"""import re
try:
    b = config.get('body')
    if isinstance(b, dict):
        kinds = {json.dumps(types)}
        k = kinds.get(str(b.get({self.tf['verify_identity']['field']!r}) or ''))
        a = str(b.get({self.tf['verify_identity']['answer']!r}) or '').strip()
        if k in ('digits', 'year', 'number'):
            digits = re.sub(r'\\D', '', a)
            if digits:
                b[{self.tf['verify_identity']['answer']!r}] = digits
except Exception:
    pass
"""
        f = self.tf["verify_identity"]
        tool = self.api_fn("verify_identity", {
            f["field"]: {"type": "string", "enum": self.enum("verify_identity", "field"), "default": "{{field}}", "description": "Which question this answer is for. One of: " + ", ".join(self.enum("verify_identity", "field")) + "."},
            f["answer"]: {"type": "string", "default": "{{answer}}", "description": "The answer in the format of that question: " + "; ".join(f"{q['field']}: {q['answer_format']}" for q in qs) + "."}},
            [f["field"], f["answer"]],
            desc="Check ONE security answer. CALL it every time the customer gives an answer, once per answer. Saying the answer is fine without calling it is not allowed.",
            pre=pre, post=post)
        tool["response_mapping"] = [{"path": "data." + rf["all_verified"], "variable": "all_verified"}, {"path": "data." + rf["wrong_left"], "variable": "wrong_left"}]
        dec = idn["decline"]
        declined = self.exit("identity_declined", dec["outcome"], dec["reason"], self.farewell())
        failed = self.exit("identity_failed", idn["on_failed"]["outcome"], idn["on_failed"]["reason"], self.farewell(idn["on_failed"]["say"]))
        sits = [x for x in self.stage_situations("identity")]
        words = ", ".join(self.s["opening"]["forbidden_before_identity"])
        task = (f"The person confirmed they are {self.addr()}. Do the security check now. You do not know why the bank is calling. "
                + (f"Never say these words before the check passes: {words}. " if words else "")
                + "If asked why you call, say you can explain after the security check. "
                + ("Ask ONE question at a time, in this order. " if idn["one_at_a_time"] else "Ask the questions in this order. ") + qlist + " "
                + "After EACH answer CALL verify_identity. Follow the what_to_do_next line of every tool result exactly. "
                + ("A wrong answer may be asked again. " if idn["wrong_may_retry"] else "")
                + (f"If the customer does not want to answer, explain once: {dec['explanation']} " if dec["explanation"] else "")
                + (f"If they still decline ({dec['max_declines']} refusals in total), call transition_to_{declined}. ")
                + ("Asking what the call is about instead of answering counts as declining. " if dec["purpose_question_counts"] else "")
                + " ".join(self.sit_line(x) for x in sits))
        trans = [tr("load_account", "All answers verified", truthy("all_verified", "verify_identity_response.data." + rf["all_verified"])),
                 tr(failed, "Too many wrong answers", {"logic": "or", "conditions": [{"variable": v, "operator": "equals", "operand": o}
                                                                                    for v in ("wrong_left", "verify_identity_response.data." + rf["wrong_left"]) for o in ("0", "0.0")]}),
                 tool_t(declined, f"The customer still declines the security questions after one explanation ({dec['max_declines']} refusals in total)"
                        + (" or asks what the call is about instead of answering for the second time" if dec["purpose_question_counts"] else ""))]
        trans += [tool_t(self.situation_exit(x, "before_identity"), self.sit_trigger(x)) for x in sits]
        self.nodes["identity"] = {"name": "identity", "node_type": "conversation", "on_enter": {"type": "llm"}, "task_message": task,
                                  "tools": [tool], "max_node_turns": 30, "max_turn_transition": declined, "transitions": trans}

    def account(self):
        fail = self.s["recording"]["on_final_failure"]
        service = self.exit("account_error", fail["outcome"], fail["reason"], self.farewell(self.s["recording"]["failure_say"]))
        self.nodes["load_account"] = api_node("load_account", self.api_fn("get_account", {}, [], retries=2),
                                              [tr(service, "lookup failed", {"logic": "or", "conditions": [{"variable": "load_account_failure_count", "operator": "greater_than", "operand": 0}]}),
                                               tr("prepare_deal", "always")],
                                              mapping=[{"path": "data." + self.s["account"]["products_field"], "variable": "acct_items"}])
        body = """
def _items():
    prods = vars.get(CFG['products_var'])
    if isinstance(prods, str):
        try:
            prods = json.loads(prods)
        except Exception:
            prods = None
    if isinstance(prods, list) and prods and isinstance(prods[0], dict):
        return prods
    out = []
    keys = set(CFG['pf'].values())
    for t in CFG['types'].values():
        keys.add(t['floor_field'])
        keys.update(_re.findall(r'[{]([a-zA-Z_][a-zA-Z0-9_]*)[}]', t['spoken_name']))
    for i in range(int(CFG['maxp'])):
        prefs = [CFG['products_var'] + '.' + str(i) + '.', CFG['products_var'] + '[' + str(i) + '].']
        for src in ('load_account_response', 'get_account_response'):        # the docs do not say which name the engine uses
            prefs += [src + '.data.' + CFG['products_field'] + '.' + str(i) + '.', src + '.data.' + CFG['products_field'] + '[' + str(i) + '].']
        for pref in prefs:
            if vars.get(pref + CFG['pf']['past_due']) is not None:
                out.append(dict((k, vars.get(pref + k)) for k in keys))
                break
    return out
def _fill(template, values):
    return _re.sub(r'[{]([a-zA-Z_][a-zA-Z0-9_]*)[}]', lambda m: str(values.get(m.group(1), '')), template)
def _money(x):
    return '%.2f' % float(x)
def _amount(rule, full, floor):
    k = rule.get('kind')
    if k == 'floor':
        return floor
    if k == 'percent_of_full':
        return round(full * float(rule.get('percent', 100)) / 100.0, 2)
    return full
try:
    now = parse_now(vars.get(CFG['now_var'])) or _dt.datetime.now()
    today = now.date()
    ps = _items()[:int(CFG['maxp'])]
    if not ps:
        vars['deal_state'] = 'none'
    else:
        facts, intro, dls = [], [], []
        pf = CFG['pf']
        for i, p in enumerate(ps):
            n = str(i + 1)
            typ = CFG['types'].get(str(p.get(pf['type'])))
            full = float(p.get(pf['past_due']))
            days = int(float(p.get(pf['days_late'])))
            floor = float(p.get(typ['floor_field'])) if typ and p.get(typ['floor_field']) is not None else full
            floor_name = typ['floor_field'].replace('_', ' ') if typ else 'minimum amount'
            name = _fill(typ['spoken_name'], p) if typ else str(p.get(pf['type'])).replace('_', ' ')
            band = band_for(days, CFG)
            deadline = deadline_for(band, today, CFG) if band else None
            steps = []
            if band:
                for st in band['ladder']:
                    d = apply_date_rule(st['date'], today, CFG, deadline)
                    if d and deadline and d > deadline:
                        d = deadline
                    k = st['amount'].get('kind')
                    if k == 'full_or_floor_if_too_much':
                        what = 'the full past-due amount ' + _money(full) + ' (or the ' + floor_name + ' ' + _money(floor) + ' if the customer already said the full amount is too much)'
                    elif k == 'floor':
                        what = 'the ' + floor_name + ' ' + _money(floor)
                    else:
                        what = _money(_amount(st['amount'], full, floor)) + (' (the full past-due amount)' if k == 'full' else '')
                    steps.append('Attempt ' + str(st['attempt']) + ': ' + what + ' on ' + spoken(d) + ' (' + d.isoformat() + ')')
            vars['p' + n + '_id'] = str(p.get(pf['id']))
            vars['p' + n + '_words'] = name
            dls.append((deadline, n, name))
            facts.append('PRODUCT ' + n + ': ' + name + '. Full past-due amount: ' + _money(full) + '. Days late: ' + str(days)
                         + ('. Band: ' + band['name'] if band else '. No band matches') + '. Minimum acceptable amount (say: the ' + floor_name + '): ' + _money(floor)
                         + ('. Deadline (latest allowed promise date): ' + spoken(deadline) + ' (' + deadline.isoformat() + ')' if deadline else '')
                         + '. Persuasion attempts allowed: ' + (str(band['attempts']) if band else '0') + '. ' + '. '.join(steps) + '.')
            intro.append(_fill(CFG['per_product'], dict(p, spoken_name=name, past_due=_money(full), days_late=str(days))))
        lines = []
        k = 0
        for j in range(0, 35):
            d = today + _dt.timedelta(days=j)
            tag = 'TODAY, ' if j == 0 else ''
            if is_business_day(d, CFG):
                if j > 0:
                    k += 1
                    tag += 'business day number ' + str(k) + ' after today'
                else:
                    tag += 'business day'
            else:
                tag += 'NOT a business day'
            for (dd, n, name) in dls:
                if dd and d == dd:
                    tag += ' <== DEADLINE of product ' + n + ' (' + name + ')'
            after = [n for (dd, n, name) in dls if dd and d > dd]
            if after:
                tag += ' (after the deadline of product ' + ' and '.join(after) + ': not allowed for it)'
            # what to do if the customer names this day, decided here by the SPEC rules, not by the model
            todo = []
            for (dd, n, name) in dls:
                v = check_promise_date(d, today, dd, CFG)
                if v['verdict'] == 'offer':
                    od = _dt.date.fromisoformat(v['date'])
                    todo.append(('product ' + n + ': ' if len(dls) > 1 else '') + 'offer ' + spoken(od) + ' (' + od.isoformat() + ') instead')
                elif v['verdict'] != 'ok':
                    todo.append(('product ' + n + ': ' if len(dls) > 1 else '') + 'not possible')
            if todo:
                tag += ' -> IF THE CUSTOMER NAMES THIS DAY: ' + '; '.join(todo)
            lines.append(str(d.day) + ' ' + MONTHS[d.month - 1].capitalize() + ' is a ' + WEEKDAYS[d.weekday()].upper() + ' (' + d.isoformat() + '): ' + tag)
        monday = today - _dt.timedelta(days=today.weekday())
        w1 = ', '.join(spoken(monday + _dt.timedelta(days=j)) for j in range(7))
        w2 = ', '.join(spoken(monday + _dt.timedelta(days=7 + j)) for j in range(7))
        vars['calendar_text'] = '\\n'.join(lines) + '\\nTHIS calendar week: ' + w1 + '\\nNEXT calendar week: ' + w2
        vars['deal_facts'] = '\\n'.join(facts)
        vars['n_products'] = str(len(ps))
        ask = CFG['first_ask_all'] if (len(ps) > 1 and CFG['first_ask_all']) else CFG['first_ask']
        vars['deal_intro'] = ' '.join([CFG['intro']] + intro + [ask])
        vars['deal_state'] = 'ready'
except Exception:
    vars['deal_state'] = 'none'
"""
        trans = [tr(f"negotiate_{k}", f"{k} item(s) on the account", eq("n_products", str(k))) for k in range(self.maxp, 0, -1)]
        self.nodes["prepare_deal"] = self.code("prepare_deal", body, trans + [tr(service, "no product data")])

    def negotiate(self):
        s = self.s
        rec, am, dt_, neg, conf = s["recording"], s["amounts"], s["dates"], s["negotiation"], s["confirmation"]
        fin_fail = rec["on_final_failure"]
        exhausted = neg["attempts_exhausted"]
        # call-scope situations always exit; product-scope ones exit only when notes are off
        neg_sits = self.stage_situations("negotiation")
        note_sits = [x for x in neg_sits if self.notes and x["scope"] == "product"]
        exit_sits = [x for x in neg_sits if x not in note_sits]
        fail_exit = None if self.notes else self.exit("record_failed", fin_fail["outcome"], fin_fail["reason"], self.farewell(rec["failure_say"]))
        exhausted_exit = None if self.notes else self.exit("attempts_exhausted", exhausted["outcome"], exhausted["reason"], self.farewell())
        relw = dt_["relative_weekday"]
        rules = (
            "A. Amounts. " + ("You propose every amount; never ask an open question about how much they can pay"
                              + (f" (forbidden: {'; '.join(neg['forbidden_questions'])})" if neg["forbidden_questions"] else "") + ". " if am["never_ask_open_amount"] else "")
            + "Start with the full past-due amount. "
            + f"If the customer says the full amount is too much, offer that product's minimum acceptable amount {times(am['too_much']['times'])} only"
            + (f", and in the same sentence say: '{am['too_much']['say']}'" if am["too_much"]["say"] else "") + ". "
            + ("If they refuse it, that is a flat refusal. " if am["too_much"]["refused_is_flat_refusal"] else "")
            + "After you named that amount once, never say it again for that product until the read-back: a later proposal names only the date. "
            + "An amount the customer proposes from the minimum acceptable amount up to the full amount (both included) is accepted. "
            + "Below it, say: '" + (am["below_min"]["say"] or "That amount cannot be accepted.") + "' " + "Offer the minimum acceptable amount once"
            + ("; if they do not accept, that is a flat refusal" if am["below_min"]["refused_is_flat_refusal"] else "") + ". Never use internal words like 'floor' or 'band' with the customer.\n"
            + "B. Dates. A promise date must be today or later, " + ("a business day per the calendar, " if dt_["business_day_only"] else "")
            + "and NOT after that product's deadline. "
            + ("A day that is not a business day and not after the deadline: offer the next business day. " if dt_["non_business_day"] == "offer_next_business_day" else "")
            + ("A date after a product's deadline: say the latest date you can record for it is its deadline and offer it" + ("; refusing the deadline is a flat refusal" if dt_["refused_deadline_is_flat_refusal"] else "") + ". " if dt_["after_deadline"] == "offer_deadline" else "")
            + ("A vague period" + (f" (for example: {'; '.join(dt_['vague']['examples'])})" if dt_["vague"]["examples"] else "") + f": ask for the exact day {times(dt_['vague']['ask_exact_times'])}; "
               + ("if they still give none, propose the deadline. " if dt_["vague"]["then"] == "propose_deadline" else "if they still give none, that is a flat refusal. "))
            + ("A weekday said with the word next means that weekday in the NEXT calendar week. " if relw["next"] == "following_week" else "A weekday said with the word next means the first such weekday after today. ")
            + ("A weekday said with the word this means the one in THIS calendar week. " if relw["this"] == "current_week" else "")
            + "For every date the customer names, find its line in the calendar and copy the day name and the business-day status from that line. Never guess a weekday. "
            + "When a calendar line says IF THE CUSTOMER NAMES THIS DAY, do exactly what it says: it already applies these rules.\n"
            + ("C. A date or an amount the customer proposes is never a refusal; handle it with A and B.\n" if neg["proposal_never_refusal"] else "")
            + f"D. {neg['flat_refusal_definition']} A flat refusal uses ONE persuasion attempt of that product; follow the product's attempts from the FACTS in order. "
            + "When a product's attempts are used up, stop: never repeat a refused offer. "
            + ("That product ends without a promise and you move to the next one.\n" if self.notes else f"Then call transition_to_{exhausted_exit}.\n")
            + f"E. Confirm. Read back {', '.join(conf['read_back'])} of every agreed promise together, with the date's day name, and ask '{conf['question']}'. "
            + ("Only after a clear yes, CALL the create_promise tool of each agreed product, one per message, in product order. " if conf["require_clear_yes"] else "Then CALL the create_promise tool of each agreed product. ")
            + "Saying it is recorded is not enough; you must call the tool. If the customer changes a date or an amount at the read-back, check it against A and B and read back again. "
            + (f"{conf['after_record_change_say']} " if conf["after_record_change_say"] else "")
            + "F. Follow the what_to_do_next line in every tool result exactly. Never tell the customer anything is recorded unless its tool result says so. "
            + f"If a create_promise call fails the first time, say exactly '{rec['retry_say']}' and call the same tool again at once with the same values. "
            + "If it fails the last time, " + (rec["failure_say"] if rec["failure_say"] else "say you could not complete it") + ".\n")
        if self.notes:
            rules += ("G. Notes. After the promises are recorded, CALL the add_note tool of every product WITHOUT a recorded promise, with its reason: "
                      + f"{exhausted.get('note_reason', '')} when its attempts were used up, " + ", ".join(f"{a['note_reason']} when {x['trigger'][0].lower() + x['trigger'][1:]}" for x in note_sits for a in x["effect"]["actions"] if a["type"] == "note")
                      + (f", {fin_fail.get('note_reason')} when its create_promise failed the last time" if fin_fail.get("note_reason") else "")
                      + ". " + ("Never call add_note when the call is being transferred. " if s["notes"]["on_transfer"] == "none" else "") + "\n")
        others = []
        for x in neg_sits:
            line = f"- {x['trigger']} {x['not_this']}".strip() + " "
            if x["say"]:
                line += (f"Say: '{x['say']}' " if x["say_exact"] else x["say"] + " ")
            if x.get("offer"):
                # the offer is made once by its own node; the model here only hands over
                line = f"- {x['trigger']} {x['not_this']}".strip() + f" Call transition_to_{self.offer_node(x)} at once, without saying anything else first. "
            elif x in note_sits:
                line += "Take no promise for that product; it ends with its note and you continue with the other products. "
            else:
                if x["threshold"] > 1 and x["first_response"]:
                    line += f"The first time: {x['first_response']} If it happens {x['threshold']} times, "
                line += f"call transition_to_{self.situation_exit(x)}. "
            if x["suppresses_persuasion"] and x.get("proposal_still_handled") and not x.get("offer"):
                line += "Make no persuasion attempt, but if the customer still names a date or an amount themselves, handle it with A and B. "
            others.append(line)
        free = [r["text"] for r in s["free_rules"] if set(r["applies_to"]) & {"negotiation", "confirmation", "all"}]
        for k in range(1, self.maxp + 1):
            plist = ", ".join(f"product {i} ({{{{p{i}_words}}}}: create_promise_{i}" + (f", add_note_{i}" if self.notes else "") + ")" for i in range(1, k + 1))
            many = k > 1
            task = ("You are on the collections part of the call. The customer is verified. Today is {{today_spoken}} ({{today_iso}}). "
                    "Your opening line already stated every late product and asked whether the customer can pay " + ("all of them" if many else "it") + " today. Never ask about today again. "
                    f"Products, in this order: {plist}. Each product has its OWN tools; use only the tools of the product you mean. One tool call per message.\n"
                    "FACTS:\n{{deal_facts}}\nCALENDAR (the only source for dates; never work out dates yourself):\n{{calendar_text}}\n\n"
                    "HOW THE CALL GOES\n1. If the customer can pay " + ("all of them" if many else "it") + " today, the promise is the full past-due amount today" + (" for every product" if many else "") + "; go to the read-back.\n"
                    + ("2. Otherwise go through the products ONE BY ONE in the order above. For each product start at attempt 1 and count its persuasion attempts separately, with that product's own facts.\n"
                       "3. If the customer names ONE date for everything: use it for every product where it is allowed. If it is after one product's deadline, that product goes on its OWN deadline; say so in the read-back. The others keep the date the customer named.\n" if many else
                       "2. Otherwise follow the rules below.\n")
                    + "\nRULES\n" + rules + "\nOTHER SITUATIONS\n" + "\n".join(others)
                    + ("\n" + "\n".join("- " + t for t in free) if free else "")
                    + "\n- When every product has a recorded promise" + (" or a saved note" if self.notes else "") + ", the system ends the call; do not say goodbye yourself.")
            tools = [self.cp_tool(i, fail_exit) for i in range(1, k + 1)] + ([self.note_tool(i) for i in range(1, k + 1)] if self.notes else [])
            trans = [tr("finalize", "Every product is done", eq("all_done", "yes"))]
            if fail_exit:
                trans.append(tr(fail_exit, "A promise failed the last time", {"logic": "or", "conditions": [
                    {"variable": f"cp{i}_fail", "operator": "greater_than", "operand": rec["max_attempts"] - 1} for i in range(1, k + 1)]}))
            if self.notes:
                trans.append(tool_t("finalize", "Every product now has either a recorded promise or a saved note"))
            for x in exit_sits:
                if x.get("offer"):
                    trans.append(tool_t(self.offer_node(x), x["trigger"]))
                else:
                    trans.append(tool_t(self.situation_exit(x), self.sit_trigger(x)))
            if exhausted_exit:
                trans.append(tool_t(exhausted_exit, "All allowed persuasion attempts are used up and the customer still refuses"))
            self.nodes[f"negotiate_{k}"] = {"name": f"negotiate_{k}", "node_type": "conversation",
                                            "on_enter": {"type": "tts", "text": "{{deal_intro}}"}, "on_enter_first_entry_only": True,
                                            "task_message": task, "tools": tools, "max_node_turns": 60,
                                            "max_turn_transition": "finalize" if self.notes else exhausted_exit, "transitions": trans}
        self.finalize()

    def offer_node(self, x):
        """A situation with an offer (e.g. a transfer the customer may accept): one node makes the offer once,
        an enum reads the answer, routing is deterministic. The model cannot repeat the offer later."""
        name = f"offer_{x['id']}"
        if name in self.nodes:
            return name
        o = x["offer"]
        accept = self.situation_exit(x, effect=o["on_accept"], branch="accept")
        decline_note = next((a["note_reason"] for a in o["on_decline"]["actions"] if a["type"] == "note"), None)
        decline = self.notes_chain(decline_note) if (self.notes and decline_note) else self.situation_exit(x, effect=o["on_decline"], branch="decline")
        values = ["accept", "decline"] + (["proposal"] if x.get("proposal_still_handled") else [])
        desc = ("The customer's answer to this offer: " + o["question"] + " accept = they clearly want it. decline = they say no or do not want it."
                + (" proposal = instead they name a payment date or an amount themselves." if "proposal" in values else "") + " Empty if unclear.")
        task = (f"The customer just said something that means: {x['trigger']} "
                + (f"Say: '{x['say']}' " if x["say_exact"] and x["say"] else (x["say"] + " " if x["say"] else ""))
                + f"Then, in the same turn: {o['question']} Make this offer ONCE only and never repeat it. "
                + ("Make no persuasion attempt and do not ask for any payment. " if x["suppresses_persuasion"] else "")
                + "If the customer asks a question, answer it in one sentence without repeating the offer. Do not call any tool.")
        trans = [tr(accept, "The customer accepted the offer", eq("offer_reply", "accept")),
                 tr(decline, "The customer declined the offer", eq("offer_reply", "decline"))]
        if "proposal" in values:
            trans += [tr(f"negotiate_{k}", "The customer named a date or an amount", {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                {"variable": "offer_reply", "operator": "equals", "operand": "proposal"}, {"variable": "n_products", "operator": "equals", "operand": str(k)}]}]})
                      for k in range(1, self.maxp + 1)]
        self.nodes[name] = {"name": name, "node_type": "conversation", "on_enter": {"type": "llm"}, "on_enter_first_entry_only": True,
                            "task_message": task, "extraction_schema": [extr("offer_reply", desc, enum=values)],
                            "max_node_turns": 2, "max_turn_transition": decline, "transitions": trans}
        return name

    def notes_chain(self, reason):
        """Engine-run notes: one add_note per product that has no recorded promise, reason baked, then finalize.
        No model decides whether or how to note."""
        entry = f"note_all_{reason}_1"
        if entry in self.nodes:
            return entry
        f = self.tf["add_note"]
        for i in range(1, self.maxp + 1):
            gate, note = f"note_all_{reason}_{i}", f"note_all_{reason}_{i}_call"
            nxt = f"note_all_{reason}_{i + 1}" if i < self.maxp else "finalize"
            body = (f"try:\n    n = int(str(vars.get('n_products') or '0'))\n    go = {i} <= n and str(vars.get('res_{i}')) not in ('promise', 'note')\n"
                    f"    vars['note_go'] = 'yes' if go else 'no'\n    if go:\n        vars['res_{i}'] = 'note'\n        vars['note{i}_saved'] = CFG['r']\n"
                    f"except Exception:\n    vars['note_go'] = 'no'\n")
            self.nodes[gate] = code_node(gate, codegen.embed({"r": reason}, body, snippets=()), [tr(note, "this product needs a note", eq("note_go", "yes")), tr(nxt, "always")])
            self.nodes[note] = api_node(note, self.api_fn("add_note", {f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
                                                                       f["reason"]: {"type": "string", "default": reason}}, [f["reason"]]),
                                        [tr(nxt, "always")])
        return entry

    def done_check(self):
        return """
    n = int(str(vars.get('n_products') or '0'))
    done = n > 0
    for j in range(1, n + 1):
        if str(vars.get('res_' + str(j)) or 'none') == 'none':
            done = False
    if done:
        vars['all_done'] = 'yes'
"""

    def cp_tool(self, i, fail_exit):
        rec, f = self.s["recording"], self.tf["create_promise"]
        ok = rec["success_field"]
        nxt = ("If another agreed promise is not recorded yet, call its create_promise tool now. Otherwise "
               + ("call add_note for each product without a promise, or, if none is left, " if self.notes else "") + "say a brief thank you only.")
        last = (f"Tell the customer: {rec['failure_say']} " + (f"Then call add_note_{i} with reason {rec['on_final_failure'].get('note_reason')}, and continue with the other products." if self.notes else ""))
        post = f"""
try:
    if isinstance(result, dict):
        result.pop('header', None)
    d = result.get('data') if isinstance(result, dict) else None
    good = isinstance(d, dict) and str(d.get({ok!r})).lower() == 'true'
    if good:
        vars['res_{i}'] = 'promise'
        msg = {('The promise for product ' + str(i) + ' is recorded. ' + nxt)!r}
    else:
        n = int(str(vars.get('cp{i}_fail') or '0')) + 1
        vars['cp{i}_fail'] = str(n)
        if n >= {int(rec['max_attempts'])}:
            msg = {last!r}
        else:
            msg = {('It failed. Say exactly: ' + rec['retry_say'] + ' Then call create_promise_' + str(i) + ' again at once with exactly the same values, without asking for confirmation again.')!r}
{self.done_check()}
    if isinstance(d, dict):
        d['what_to_do_next'] = msg
    elif isinstance(result, dict):
        result['what_to_do_next'] = msg
except Exception:
    pass
"""
        return self.api_fn("create_promise", {
            f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
            f["amount"]: {"type": self.ftype("create_promise", "amount"), "default": "{{cp%d_amount}}" % i, "description": f"The confirmed amount for product {i}, as a number."},
            f["date"]: {"type": "string", "default": "{{cp%d_date}}" % i, "description": f"The date you read back for product {i} and the customer confirmed, as YYYY-MM-DD copied from its calendar line."}},
            [f["amount"], f["date"]], name=f"create_promise_{i}",
            desc=f"Record the payment promise for PRODUCT {i} only. CALL it only after the customer clearly said yes to the read-back. Never say a promise is recorded without calling it.",
            post=post)

    def note_tool(self, i):
        f = self.tf["add_note"]
        reasons = self.enum("add_note", "reason") or self.s["notes"]["reasons"]
        pre = f"try:\n    b = config.get('body')\n    if isinstance(b, dict):\n        vars['note{i}_saved'] = str(b.get({f['reason']!r}) or '')\nexcept Exception:\n    pass\n"
        post = f"""
try:
    if isinstance(result, dict):
        result.pop('header', None)
    d = result.get('data') if isinstance(result, dict) else None
    good = isinstance(d, dict) and str(d.get({self.s['identity']['result_fields']['ok']!r})).lower() == 'true'
    if good:
        vars['res_{i}'] = 'note'
        msg = 'The note for product {i} is saved. Continue with the next product without a promise or a note, if any; otherwise say a brief thank you.'
    else:
        msg = 'The note could not be saved. Call add_note_{i} once more with the same reason.'
{self.done_check()}
    if isinstance(d, dict):
        d['what_to_do_next'] = msg
    elif isinstance(result, dict):
        result['what_to_do_next'] = msg
except Exception:
    pass
"""
        return self.api_fn("add_note", {
            f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
            f["reason"]: {"type": "string", "enum": reasons, "default": "{{note%d_reason}}" % i, "description": f"Why product {i} ended without a promise. One of: {', '.join(reasons)}."}},
            [f["reason"]], name=f"add_note_{i}",
            desc=f"Record why PRODUCT {i} ended without a promise. CALL it once, after the promises, only for a product without a recorded promise."
                 + (" Never call it when the call is transferred." if self.s["notes"]["on_transfer"] == "none" else ""),
            pre=pre, post=post)

    def finalize(self):
        body = """
try:
    n = int(str(vars.get('n_products') or '0'))
    promised = 0
    reasons = []
    for j in range(1, n + 1):
        s = str(j)
        if str(vars.get('res_' + s)) == 'promise':
            promised += 1
            continue
        r = str(vars.get('note' + s + '_saved') or '')
        reasons.append(r)
    m = CFG['multi_rule']
    if promised > 0:
        vars['outcome'] = CFG['promise_outcome']['outcome']
        vars['reason'] = CFG['promise_outcome']['reason']
        vars['farewell'] = (CFG['after_success'] + ' ' + CFG['farewell']).strip()
    elif m and reasons and all(r == m['all_notes_match']['note_reason'] for r in reasons):
        vars['outcome'] = m['all_notes_match']['outcome']
        vars['reason'] = m['all_notes_match']['reason']
        vars['farewell'] = CFG['farewell']
    elif m:
        first = ''
        for r in reasons:
            if r and r != m['all_notes_match']['note_reason']:
                first = r
                break
        vars['outcome'] = m['otherwise']['outcome']
        vars['reason'] = first or CFG['exhausted_reason']
        vars['farewell'] = CFG['farewell']
    else:
        vars['outcome'] = CFG['exhausted_outcome']
        vars['reason'] = CFG['exhausted_reason']
        vars['farewell'] = CFG['farewell']
except Exception:
    vars['outcome'] = CFG['exhausted_outcome']
    vars['reason'] = CFG['exhausted_reason']
    vars['farewell'] = CFG['farewell']
"""
        ex = self.s["negotiation"]["attempts_exhausted"]
        self.nodes["finalize"] = self.code("finalize", body, [tr("final_end", "always")], exhausted_outcome=ex["outcome"], exhausted_reason=ex["reason"])

    def end(self):
        self.nodes["final_end"] = {"name": "final_end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
                                   "terminal": {"type": "function", "function": {"name": "call_finished", "handler": "__function__:end_call",
                                                "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "custom"},
                                                                                               "spoken_message": {"type": "string", "default": "{{farewell}}"}}}}}}

    def close_tool(self):
        f = self.tf["close_call"]
        table = self.s["outcomes"]["table"]
        omitted = self.s["outcomes"]["reason_omitted_for"]
        body = {f["outcome"]: {"type": "string", "enum": self.enum("close_call", "outcome"), "default": "{{outcome}}",
                               "description": " ".join(f"{r['outcome']}: {r['when']}." for r in table)}}
        if f["reason"]:
            body[f["reason"]] = {"type": "string", "default": "{{reason}}",
                                 "description": " ".join(f"{r['outcome']}: {', '.join(r['reasons'])}." for r in table if r["reasons"]) + f" Leave out for {', '.join(omitted)}."}
        pre = (f"try:\n    b = config.get('body')\n    if isinstance(b, dict):\n"
               f"        if b.get({f['outcome']!r}) in {json.dumps(omitted)} or str(b.get({(f['reason'] or 'reason')!r}) or '').strip() in ('', 'none'):\n"
               f"            b.pop({(f['reason'] or 'reason')!r}, None)\nexcept Exception:\n    pass\n")
        fn = self.api_fn("close_call", body, [f["outcome"]], desc="Record how the call ended.", pre=pre)
        fn["config"]["alwaysRunsAt"] = ["end_of_call"]
        return fn

    def system_prompt(self):
        s = self.s
        lines = [f"You are {s['agent']['self_description']} on an outbound phone call. Speak {s['meta']['language']}. Every turn is one or two short spoken sentences, no lists, no markdown.",
                 f"Address the customer as {self.addr()}. The current date and time is {{{{{self.var['now']}}}}}; never use any other clock.",
                 "Rules that hold in every step:"]
        lines += [f"- {q['trigger']} {q['answer']}" for q in s["faq"]]
        if s["negotiation"]["forbidden_offers"]:
            lines.append(f"- Never offer any of these: {'; '.join(s['negotiation']['forbidden_offers'])}.")
        lines += [f"- {r['text']}" for r in s["free_rules"] if "all" in r["applies_to"]]
        lines += ["- Never say anything is recorded, saved, booked or scheduled unless a tool result says it worked.",
                  "- After every tool result, speak to the customer or continue; never end a turn with nothing.",
                  "- Do not say goodbye yourself. The system says goodbye when the call ends. When your instructions tell you to call a transition tool, call it and do not add a farewell."]
        return "\n".join(lines)

    def build(self):
        self.setup(); self.opening(); self.third_party(); self.identity(); self.account(); self.negotiate(); self.end()
        return {"initial_node": "setup", "system_prompt": self.system_prompt(), "tools": [self.close_tool()],
                "global_nodes": {}, "nodes": self.nodes}


def build(spec, tools):
    return Gen(spec, tools).build()


if __name__ == "__main__":       # python -m builder.generate <spec.json> <tool_api.json> <out.json>
    import sys
    from builder.ingest import parse_openapi
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    wf = build(spec, parse_openapi(sys.argv[2])["tools"])
    json.dump(wf, open(sys.argv[3], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("nodes", len(wf["nodes"]))
