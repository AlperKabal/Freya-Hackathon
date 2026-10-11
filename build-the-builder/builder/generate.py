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


def _plain(t):
    return re.sub(r"([a-z])\1+", r"\1", re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip())


def stem_in(stem, text):
    """Does the text hold this word stem (or phrase) at the start of a word? The same comparison as has_evidence in
    snippets/negotiation.py, which runs on the platform and cannot be imported here."""
    return bool(_plain(stem)) and (" " + _plain(stem)) in (" " + _plain(text))


def word_in(word, text):
    """Does the text hold this word (or phrase) as whole words?"""
    return bool(_plain(word)) and (" " + _plain(word) + " ") in (" " + _plain(text) + " ")


# the words of the sentences the state machine itself says (snippets/negotiation.py): a customer may repeat any of them
OWN_FIXED = ("can you pay for your on today tomorrow instead could you make that payment which exact day could you pay on which day can you pay "
             "that day is not possible the latest date i can record is it let me read your promise back you will pay and does that work for you "
             "sorry could you say that again")


# A sentence that code writes into a spoken variable is said as it stands: the platform fills {{name}} only in a
# node's own text. So a call variable the SPEC wrote into such a sentence (a farewell that addresses the customer)
# is filled in by the code node itself; any other brace stays.
SAY_DEF = ("def _say(t):\n"
           "    import re\n"
           "    names = CFG.get('call_vars') or []\n"
           "    return re.sub(r'(?<![{])[{]([a-zA-Z_][a-zA-Z0-9_]*)[}](?![}])',\n"
           "                  lambda m: str(vars.get(m.group(1))) if m.group(1) in names and vars.get(m.group(1)) is not None else m.group(0), str(t or ''))\n")


def extr(name, desc, enum=None, pattern=None, conf=0.7):
    e = {"name": name, "type": "string", "description": desc, "min_confidence": conf}
    if enum: e["enum_values"] = list(enum)
    if pattern: e["validation_pattern"] = pattern
    return e


# ---------------------------------------------------------------- generator

class Gen:
    def __init__(self, spec, tools, mode="v1"):
        self.mode = mode                     # v1: one LLM negotiation node; orch: code decides every offer
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
        said = " ".join(p.strip() for p in parts if p and p.strip())
        fw = self.s["closing"]["farewell"].strip()
        if fw and (fw.lower() in said.lower() or re.search(r"\b(good ?bye|bye)\b", said, re.I)):
            return said                                    # the situation's own sentence already closes the call
        return " ".join(x for x in (said, fw) if x)

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
        if pre: fn["pre_process_code"] = codegen.scrubbed(pre)
        if post: fn["post_process_code"] = codegen.scrubbed(post)
        return fn

    def enum(self, tool, role):
        field = self.tf[tool][role]
        return list((self.t[tool]["request"].get(field) or {}).get("enum") or [])

    def ftype(self, tool, role):
        return (self.t[tool]["request"].get(self.tf[tool][role]) or {}).get("type", "string")

    def amount_std(self):
        """True when the SPEC's amount rules are the common ladder (first the full amount, accept floor..full, offer the
        floor when it is too much or too low): the prompt then names them in words. Otherwise each product's FACTS list
        its own amounts and the prompt points there."""
        a = self.s["amounts"]
        return ([a["first_offer"]["kind"], a["accept_min"]["kind"], a["accept_max"]["kind"], a["too_much"]["offer"]["kind"], a["below_min"]["offer"]["kind"]]
                == ["full", "floor", "full", "floor", "floor"])

    def flags(self):
        """The SPEC switches the code nodes read. Absent keys mean the common case (see snippets/negotiation.py);
        a one-product brief keeps it."""
        m, f = self.s["multi_product"], {}
        if self.multi:
            f.update(single_read_back=bool(m["single_read_back"]), ask_all_once=bool(m["ask_all_today_once"]),
                     state_all_first=bool(m["state_all_first"]), attempts_per_product=bool(m["attempts_per_product"]),
                     call_attempt_limit=int(self.s["negotiation"].get("call_attempt_limit") or 0))
        if self.notes:
            f["note_exhausted"] = bool(self.s["notes"]["for_each_product_without_promise"])
        return f

    def flag(self, key):
        return self.flags().get(key, True)

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
            "call_vars": self.call_vars,
            "am": {k: s["amounts"][k] for k in ("first_offer", "accept_min", "accept_max")} | {"too_much": s["amounts"]["too_much"]["offer"], "below_min": s["amounts"]["below_min"]["offer"]},
            "amount_std": self.amount_std(),
        })
        c.update(self.flags())
        c.update(extra)
        return c

    def code(self, name, body, transitions, **extra):
        return code_node(name, codegen.embed(self.cfg(**extra), body), transitions)

    # --- exits: one code node per (outcome, reason, farewell), then the end node
    def exit(self, key, outcome, reason, farewell, promise_wins=False):
        node = "set_" + key
        if node not in self.nodes:
            body = (f"vars['outcome'] = CFG['o']\nvars['reason'] = CFG['r']\nvars['farewell'] = CFG['f']\n")
            c = {"o": outcome, "r": reason, "f": farewell}
            if promise_wins:              # outcomes.transfer_after_promise: a promise recorded before the transfer decides
                po = self.s["outcomes"]["promise"]
                c.update(po=po["outcome"], pr=po["reason"])
                body += ("try:\n    n = max(1, int(str(vars.get('n_products') or '0')))\n"
                         "    if any(str(vars.get('res_' + str(j))) == 'promise' for j in range(1, n + 1)):\n"
                         "        vars['outcome'] = CFG['po']\n        vars['reason'] = CFG['pr']\nexcept Exception:\n    pass\n")
            self.nodes[node] = code_node(node, codegen.embed(c, body, snippets=()), [tr("final_end", "always")])
        return node

    def situation_exit(self, sit, stage_key="after_identity", effect=None, branch=""):
        """Exit chain for a call-scope situation: its actions (engine-run), then the outcome node."""
        eff = effect or sit["effect"]
        ob = (eff.get("outcome_by_stage") or {}).get(stage_key)
        outcome, reason = (ob["outcome"], ob["reason"]) if ob else (eff["outcome"], eff["reason"])
        say = sit["say"]                                          # a speakable sentence by SPEC contract
        if any(a["type"] == "transfer" for a in eff["actions"]) and not re.search(r"\b(connect|transfer|put you through|hand you over)", say, re.I):
            say = (say + " I am connecting you now.").strip()        # spoken after the transfer call ran; not twice when the SPEC's sentence already says it
        key = f"{sit['id']}_{stage_key}" if eff.get("outcome_by_stage") else sit["id"]
        if branch:
            key += "_" + branch
        pw = any(a["type"] == "transfer" for a in eff["actions"]) and self.s["outcomes"]["transfer_after_promise"] == "promise_wins"
        target = self.exit(key, outcome, reason, self.farewell(say), promise_wins=pw)
        for i, a in reversed(list(enumerate(eff["actions"]))):
            if a["type"] == "transfer":
                name = f"do_{key}_transfer{i}"
                q = self.tf["transfer_to_agent"]["queue"]
                self.nodes[name] = api_node(name, self.api_fn("transfer_to_agent", {q: {"type": "string", "default": a["queue"]}}, [q]),
                                            [tr(target, "always")])
                target = name
            elif a["type"] == "callback":
                target = self.callback_flow(f"{key}{i}", target)
            elif a["type"] == "note" and self.notes and stage_key != "before_identity" and a.get("note_reason"):
                # before identity no account is loaded, so there is no product to note; after it, every product
                # without a promise gets the note (engine-run), then the situation's own exit
                target = self.notes_chain(a["note_reason"], after=target, prefix=f"do_{key}_note{i}")
        return target

    def cb_window(self):
        cb = self.s["third_party"]["callback"]
        return (f"A callback is only possible on these days: {{{{cb_days_text}}}}, between {cb['window_start']} and {cb['window_end']}"
                + (" (both included)" if cb["inclusive"] else "") + (", and later than now ({{now_hhmm}} today)" if cb["after_now"] else "") + ".")

    CB_CHECK = """
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
    rel = relative_time(said, now)                           # "in an hour": a day and a time, counted from now
    if rel:
        day, hhmm = rel.date().isoformat(), rel.strftime('%H:%M')
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

    def callback_nodes(self, check, book, ask, scheduled, not_sched):
        """Code checks the day and time against the SPEC's callback window, then the engine books it."""
        self.nodes[check] = self.code(check, self.CB_CHECK, [
            tr(book, "valid", eq("cb_state", "valid")), tr(not_sched, "out of window again", eq("cb_state", "fail")), tr(ask, "ask again")])
        f, ok = self.tf["schedule_callback"], self.s["identity"]["result_fields"]["ok"]
        self.nodes[book] = api_node(book, self.api_fn("schedule_callback", {
            f["date"]: {"type": "string", "default": "{{cb_date_iso}}"}, f["time"]: {"type": "string", "default": "{{cb_time_norm}}"}}, [f["date"], f["time"]]),
            [tr(scheduled, "booked", truthy("cb_booked", book + "_response.data." + ok, "schedule_callback_response.data." + ok)), tr(not_sched, "the booking did not work")],
            mapping=[{"path": "data." + ok, "variable": "cb_booked"}])

    def callback_flow(self, key, booked):
        """A situation whose effect includes a callback: ask the customer for a day and a time, check them in code,
        book them, then continue with `booked` (the situation's other actions and its outcome)."""
        ask = f"cb_{key}"
        if ask in self.nodes:
            return ask
        cb = self.s["third_party"]["callback"]
        not_sched = self.exit(f"{key}_no_callback", cb["not_scheduled"]["outcome"], cb["not_scheduled"]["reason"], self.farewell())
        task = ("Ask the customer for a day and a time when the bank can call back. " + self.cb_window() + " You need a day and a time. {{cb_feedback}} "
                "There is no booking tool: the system books the callback by itself as soon as the customer has given a day and a time that fit. "
                "Never say that you booked it and never say that you cannot book it. "
                f"The ONLY tool you may call is transition_to_{not_sched}, and only when the customer cannot or will not give any time.")
        self.nodes[ask] = {"name": ask, "node_type": "conversation", "on_enter": {"type": "llm"}, "task_message": task,
                           "extraction_schema": [extr("cb_when_text", "When the customer can be called back: the day and the time of day, copied exactly as said (also 'in an hour'). "
                                                      "Include a day or a time given in an earlier reply if the latest reply gives only the other. Empty if none.")],
                           "max_node_turns": 6, "max_turn_transition": not_sched,
                           "transitions": [tr(f"{ask}_check", "A day or a time was given", {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                               {"variable": "cb_when_text", "operator": "is_set"}, {"variable": "cb_when_text", "operator": "not_equals", "operand": "none"}]}]}),
                                           tool_t(not_sched, "The customer cannot or will not give any callback time")]}
        self.callback_nodes(f"{ask}_check", f"{ask}_book", ask, booked, not_sched)
        return ask

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
    vars['p' + str(i) + '_deadline'] = ''
vars['date_note'] = 'No payment day has been named yet.'
vars['day_checked'] = ''
vars['id_declines'] = '0'
vars['id_decline_turn'] = ''
vars['id_state'] = 'open'
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
                + " ".join(f"{x['id']} = {self.sit_desc(x)}" for x in enum_sits)
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

    def guard(self, x):
        """A call-scope situation without an offer ends or transfers the call, which cannot be undone in the call:
        its look-alikes (a plain no, a question about options) must not trigger it. But a message that ALSO asks for
        it in so many words is it: "I cannot pay, I want <the thing>" is the request, not a refusal. Mechanism text,
        no brief content (the example words come from the SPEC)."""
        if x["scope"] != "call" or x.get("offer") or not set(x["stages"]) & {"identity", "negotiation", "confirmation"}:
            return ""
        words = self.evidence(x)
        ex = (" (words like: " + ", ".join(f"'{w.lstrip('=')}'" for w in words[:6]) + ")") if words else ""
        return (" Only when the customer says this clearly and explicitly. A plain no, saying they cannot pay, or asking"
                " what options or other ways there are is, by itself, NOT this. But when the same message also asks for exactly this"
                + ex + ", it IS this, even if it also says they cannot pay.")

    def sit_desc(self, x, guard=False):
        """A situation for a classifier or a prompt: the trigger, then what only looks like it, clearly labelled."""
        out = x["trigger"].strip()
        if x["not_this"].strip():
            out = out.rstrip(".") + ". NOT this: " + x["not_this"].strip()
        return (out.rstrip(".") + "." + self.guard(x)) if guard else out

    def evidence(self, x):
        """The situation's usable evidence words (SPEC, optional). A stem needs at least three letters or digits, and
        a word of the agent's own fixed sentences is no evidence: the customer repeats those in any reply."""
        s = self.s
        own = " ".join([s["opening"]["first_sentence"], s["opening"]["confirm_question"], s["account"]["statement_intro"], s["account"]["statement_per_product"],
                        s["negotiation"]["first_ask"], s["multi_product"]["first_ask_all"], s["amounts"]["too_much"]["say"], s["amounts"]["below_min"]["say"],
                        s["confirmation"]["question"]] + [p["spoken_name"] for p in s["account"]["product_types"]])
        own = PH.sub(" ", own)                                   # placeholders are not words anyone says
        words = [w.strip().lower() for w in x.get("evidence_words") or [] if isinstance(w, str)]
        out = []
        for w in words:
            if len(re.sub(r"[^a-z0-9]", "", w)) < 3:
                continue
            if not stem_in(w, own):
                out.append(w)
            elif not word_in(w, own + " " + OWN_FIXED):
                # only a longer word of the agent's sentences begins like it (a product name that starts with the
                # word for a human being): as a stem it would be an echo, as a whole word it is still the customer's
                # own request ("=" marks that)
                out.append("=" + w)
        return out

    def sit_trigger(self, x, with_not=False):
        t = x["trigger"]
        if with_not and x["not_this"]:
            t += " NOT this: " + x["not_this"]
        t += self.guard(x)
        if x["threshold"] > 1 and x["first_response"]:
            t += f" This applies only after you already did this once: {x['first_response']} and the customer insists ({x['threshold']} times in total)."
        return t

    def sit_line(self, x):
        line = f"If {x['trigger'][0].lower() + x['trigger'][1:]}{self.guard(x)}"
        if x["threshold"] > 1 and x["first_response"]:
            line += f" The first time: {x['first_response']} If it happens {x['threshold']} times, call transition_to_" + "{node}" + "."
        else:
            line += " Call transition_to_{node}."
        if x["guidance"]:
            line += f" ({x['guidance']})"
        return line.replace("{node}", self.situation_exit(x, "before_identity" if "identity" in x["stages"] or "opening" in x["stages"] else "after_identity"))

    def third_party(self):
        tp, cb = self.s["third_party"], self.s["third_party"]["callback"]
        if not tp["enabled"]:
            return
        sits = [x for x in self.stage_situations("third_party") if x["threshold"] <= 1 and not x.get("offer")]
        # a brief that books no callback has no "booked" close: a node nothing leads to would be a lint problem
        scheduled = self.exit("callback_scheduled", cb["scheduled"]["outcome"], cb["scheduled"]["reason"], self.farewell()) if cb["enabled"] else None
        not_sched = self.exit("callback_not_scheduled", cb["not_scheduled"]["outcome"], cb["not_scheduled"]["reason"], self.farewell())
        window = self.cb_window()
        task = (f"The person on the line is NOT {self.addr()}. " + " ".join(tp["instructions"]) + " "
                + (window + " You need a day and a time. {{cb_feedback}} "
                   "There is no booking tool: the system books the callback by itself as soon as the person has given a day and a time that fit. "
                   "Never say that you booked it and never say that you cannot book it. " if cb["enabled"] else "")
                + f"The ONLY tool you may call is transition_to_{not_sched}, and only when the person cannot or will not give any time.")
        ex = []
        if cb["enabled"]:
            # one field for day and time together: a second field that fails to extract must not block the path
            ex.append(extr("cb_when_text", "When the customer can be reached: the day and the time of day, copied exactly as the person said them "
                           "(for example 'tomorrow morning around eleven', 'Friday at 3 pm', 'in an hour'). Include a day or a time given in an earlier reply "
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
        self.callback_nodes("check_callback", "schedule_cb", "third_party", scheduled, not_sched)

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
        hint = d.get({rf['hint']!r}) if {rf['hint']!r} else None
        # the API may not say "all verified" or "wrong answers left": then code counts them from the SPEC
        fields = {json.dumps([q['field'] for q in qs])}
        ok_now = str(d.get({rf['verified']!r})).lower() == 'true'
        last = str(vars.get('id_last_field') or '')
        if ok_now and last:
            vars['id_ok_' + last] = 'yes'
        av = d.get({rf['all_verified']!r}) if {rf['all_verified']!r} else None
        all_true = (str(av).lower() == 'true') if av is not None else all(str(vars.get('id_ok_' + q) or '') == 'yes' for q in fields)
        if all_true:
            vars['id_all_ok'] = 'true'
        if not ok_now and hint not in hints and str(d.get({rf['ok']!r})).lower() != 'false':
            vars['id_wrong'] = str(int(str(vars.get('id_wrong') or '0')) + 1)
        lv = d.get({rf['wrong_left']!r}) if {rf['wrong_left']!r} else None
        left = lv if lv is not None else max(0, {int(idn['max_wrong_total'])} - int(str(vars.get('id_wrong') or '0')))
        vars['id_left'] = str(left)
        if hint in hints:
            msg = hints[hint] + ' Then call verify_identity again.'
        elif str(d.get({rf['ok']!r})).lower() == 'false':
            msg = 'The value was not accepted and was not counted as a wrong answer. Ask the customer to say it again, then call verify_identity again.'
        elif all_true:
            msg = 'All answers are verified. Say a brief thank you only. Say nothing about the account yet.'
        elif str(d.get({rf['verified']!r})).lower() == 'true':
            msg = 'This answer is correct. Now ask the next security question that has not been answered correctly yet, in this order: ' + {json.dumps(' | '.join(q['ask'] for q in qs))} + '. Say nothing about the account.'
        else:
            if left is not None and str(left).strip() in ('0', '0.0'):
                msg = 'The check has ended. Say nothing about the account.'
            else:
                msg = 'That answer did not match. Say so briefly, do not reveal the right answer, and ask the same question again. Wrong answers left: ' + str(left) + '.'
        d['what_to_do_next'] = msg
except Exception:
    pass
"""
        # the answer goes out in the form its TYPE asks for (snippets/answers.py), whatever the field is called
        kinds = {q["field"]: [q["value_type"], (q["answer_format"] + " " + q["conversion"]).strip()] for q in qs}
        pre = "import json\n" + codegen.snippet("answers") + f"""
try:
    b = config.get('body')
    if isinstance(b, dict):
        kinds = json.loads(bytes.fromhex('{json.dumps(kinds, ensure_ascii=False).encode("utf-8").hex()}').decode('utf-8'))
        vars['id_last_field'] = str(b.get({self.tf['verify_identity']['field']!r}) or '')
        k = kinds.get(vars['id_last_field'])
        a = str(b.get({self.tf['verify_identity']['answer']!r}) or '').strip()
        if k and a:                                  # an answer given in two turns is sent whole: the kept part is joined
            part = 'id_part_' + vars['id_last_field']
            b[{self.tf['verify_identity']['answer']!r}], vars[part] = whole_answer(k[0], vars.get(part), a, k[1])
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
        tool["response_mapping"] = [{"path": "data." + rf[k], "variable": v} for k, v in (("all_verified", "all_verified"), ("wrong_left", "wrong_left")) if rf[k]]
        dec = idn["decline"]
        declined = self.exit("identity_declined", dec["outcome"], dec["reason"], self.farewell())
        failed = self.exit("identity_failed", idn["on_failed"]["outcome"], idn["on_failed"]["reason"], self.farewell(idn["on_failed"]["say"]))
        sits = [x for x in self.stage_situations("identity")]
        words = ", ".join(self.s["opening"]["forbidden_before_identity"])
        task = (f"The person confirmed they are {self.addr()}. Do the security check now. You do not know why the bank is calling. "
                + (f"Never say these words before the check passes: {words}. " if words else "")
                + "If asked why you call, say you can explain after the security check. "
                + ("Ask ONE question at a time, in this order. " if idn["one_at_a_time"] else "Ask the questions in this order. ") + qlist + " "
                + "After EACH answer CALL verify_identity. If the customer gives only a part of an answer (the first half of a number, "
                  "a date without its year), do not call it yet: ask for the rest, then send the whole answer in one call. "
                + "Follow the what_to_do_next line of every tool result exactly. "
                + ("A wrong answer may be asked again. " if idn["wrong_may_retry"] else "")
                # declines are counted by code (node id_count), not by the model: the call closes on the SPEC's count
                + "The system counts how often the customer declined the security questions: {{id_declines}} time(s) so far. "
                + (f"When it is 1, say once, in this exact wording: '{dec['explanation']}' Then ask the same question again. Never say that explanation twice. "
                   if dec["explanation"] else "After a decline, ask the same question again once. ")
                + "Never end the call yourself because of a decline. "
                + " ".join(self.sit_line(x) for x in sits))
        reply = ("What the customer's LATEST message does with the security question. answer = gives an answer, also a wrong or partial one. "
                 "decline = does not want to answer: refuses, says they do not trust the call, or asks for another way instead of answering"
                 + (", or asks what the call is about instead of answering" if dec["purpose_question_counts"] else "")
                 + ". If the message both declines and asks something, choose decline. question = only asks a question without refusing "
                 "(for example whether the call is genuine). unclear = anything else.")
        api_all = ["verify_identity_response.data." + rf["all_verified"]] if rf["all_verified"] else []
        api_left = ["verify_identity_response.data." + rf["wrong_left"]] if rf["wrong_left"] else []
        trans = [tr("load_account", "All answers verified", truthy("all_verified", "id_all_ok", *api_all)),
                 tr(failed, "Too many wrong answers", {"logic": "or", "conditions": [{"variable": v, "operator": "equals", "operand": o}
                                                                                    for v in ["wrong_left", "id_left"] + api_left for o in ("0", "0.0")]}),
                 tr("id_count", "The customer declined the security questions", eq("id_reply", "decline"))]
        trans += [tool_t(self.situation_exit(x, "before_identity"), self.sit_trigger(x)) for x in sits]
        self.nodes["identity"] = {"name": "identity", "node_type": "conversation", "on_enter": {"type": "llm"}, "task_message": task,
                                  "tools": [tool], "extraction_schema": [extr("id_reply", reply, enum=["answer", "decline", "question", "unclear"])],
                                  "max_node_turns": 30, "max_turn_transition": declined, "transitions": trans}
        # one decline per customer turn (the extractor can re-read an old value: the turn number guards it)
        body = """
try:
    turn = str(vars.get('identity.total_turns') or '')
    if turn != str(vars.get('id_decline_turn') or ''):
        vars['id_decline_turn'] = turn
        vars['id_declines'] = str(int(str(vars.get('id_declines') or '0')) + 1)
    vars['id_state'] = 'closed' if int(str(vars.get('id_declines') or '0')) >= int(CFG['max']) else 'open'
except Exception:
    vars['id_state'] = 'open'
vars['id_reply'] = 'unclear'
"""
        self.nodes["id_count"] = code_node("id_count", codegen.embed({"max": max(1, int(dec["max_declines"]))}, body, snippets=()),
                                           [tr(declined, "declined as often as the brief allows", eq("id_state", "closed")),
                                            tr("identity", "ask the question again")])

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
# a lowest amount is named by its field's own words only when they end as a thing one can pay ("minimum payment",
# "instalment amount", "lease rental"); other field names ("monthly", "floor") are no words for a customer
NOUNS = ('payment', 'repayment', 'amount', 'instalment', 'installment', 'due', 'rate', 'rental', 'fee', 'sum', 'minimum', 'contribution', 'premium')
def _amount(rule, full, floor):
    k = rule.get('kind')
    if k == 'floor':
        return floor
    if k == 'percent_of_full':
        return int(full * float(rule.get('percent', 100)) + 0.5 + 1e-6) / 100.0        # to the cent, half a cent up
    return full
try:
    now = parse_now(vars.get(CFG['now_var'])) or _dt.datetime.now()
    today = now.date()
    ps = _items()[:int(CFG['maxp'])]
    if not ps:
        vars['deal_state'] = 'none'
    else:
        facts, intro, dls, plan = [], [], [], []
        pf = CFG['pf']
        spoken_days = dict(((today + _dt.timedelta(days=j)).isoformat(), spoken(today + _dt.timedelta(days=j))) for j in range(0, 70))
        for i, p in enumerate(ps):
            n = str(i + 1)
            typ = CFG['types'].get(str(p.get(pf['type'])))
            full = float(p.get(pf['past_due']))
            days = int(float(p.get(pf['days_late'])))
            floor = float(p.get(typ['floor_field'])) if typ and p.get(typ['floor_field']) is not None else full
            floor_name = _re.sub('(?<![a-z])min(?![a-z])', 'minimum', typ['floor_field'].replace('_', ' ')) if typ else 'minimum amount'
            name = _fill(typ['spoken_name'], p) if typ else str(p.get(pf['type'])).replace('_', ' ')
            band = band_for(days, CFG)
            deadline = deadline_for(band, today, CFG) if band else None
            first_day = today
            for _ in range(40):                          # today, unless a promise cannot have today (a weekend day, a holiday, a later earliest day)
                v0 = check_promise_date(first_day, today, None, CFG)
                if v0['verdict'] in ('ok', 'offer') and v0['date']:
                    first_day = _dt.date.fromisoformat(v0['date'])
                    break
                first_day = first_day + _dt.timedelta(days=1)
            else:
                first_day = today
            if deadline and deadline < first_day:        # no day fits between the earliest day and the deadline: the earliest day is the deadline
                deadline = first_day
            steps, lad = [], []
            if band:
                for st in band['ladder']:
                    d = apply_date_rule(st['date'], today, CFG, deadline)
                    if d and d < first_day:              # an offer is never for a day before the earliest one
                        d = first_day
                    if d and CFG.get('business_day_only', True) and not is_business_day(d, CFG):
                        d = next_business_day(d, CFG)    # "in three days" on a Sunday: the agent's own offer is for a business day
                    if d and deadline and d > deadline:
                        d = deadline
                    k = st['amount'].get('kind')
                    lad.append(dict(kind=k, amount=round(_amount(st['amount'], full, floor), 2), date=d.isoformat()))
                    if k == 'full_or_floor_if_too_much':
                        what = 'the full past-due amount ' + _money(full) + ' (or the ' + floor_name + ' ' + _money(floor) + ' if the customer already said the full amount is too much)'
                    elif k == 'floor':
                        what = 'the ' + floor_name + ' ' + _money(floor)
                    else:
                        what = _money(_amount(st['amount'], full, floor)) + (' (the full past-due amount)' if k == 'full' else '')
                    steps.append('Attempt ' + str(st['attempt']) + ': ' + what + ' on ' + spoken(d) + ' (' + d.isoformat() + ')')
            vars['p' + n + '_id'] = str(p.get(pf['id']))
            vars['p' + n + '_words'] = name
            vars['p' + n + '_deadline'] = deadline.isoformat() if deadline else ''
            dls.append((deadline, n, name))
            facts.append('PRODUCT ' + n + ': ' + name + '. Full past-due amount: ' + _money(full) + '. Days late: ' + str(days)
                         + ('. Band: ' + band['name'] if band else '. No band matches') + '. Minimum acceptable amount (say: the ' + floor_name + '): ' + _money(floor)
                         + ('. Deadline (latest allowed promise date): ' + spoken(deadline) + ' (' + deadline.isoformat() + ')' if deadline else '')
                         + '. Persuasion attempts allowed: ' + (str(band['attempts']) if band else '0') + '. ' + '. '.join(steps)
                         + '. After attempt ' + (str(band['attempts']) if band else '0') + ' is refused there is NO other offer for this product: it ends without a promise.')
            intro.append(_fill(CFG['per_product'], dict(p, spoken_name=name, past_due=_money(full), days_late=str(days))))
            am = dict((k, round(min(_amount(r, full, floor), full), 2)) for k, r in CFG['am'].items())
            if not CFG['amount_std']:
                facts[-1] += ('. AMOUNT RULES for this product: first offer ' + _money(am['first_offer']) + '; acceptable from ' + _money(am['accept_min'])
                              + ' to ' + _money(am['accept_max']) + ' (both included); if the customer says it is too much, offer ' + _money(am['too_much'])
                              + '; below ' + _money(am['accept_min']) + ', offer ' + _money(am['below_min']) + '.')
            if not CFG.get('state_all_first', True):
                facts[-1] += '. Statement (say it when you start this product): ' + intro[-1]
            ask_day = apply_date_rule(CFG['earliest'], today, CFG, deadline) or today      # the day the first ask is about
            if first_day == ask_day and ask_day != today:  # the prompt-driven mode reads it in the FACTS; the state machine in the plan
                facts[-1] += (' A PROMISE CANNOT BE FOR TODAY: the earliest day is ' + spoken(first_day) + ' (' + first_day.isoformat()
                              + '); a yes to the first question means that day.')
            elif first_day != today:
                facts[-1] += (' TODAY IS NOT A DAY A PROMISE CAN HAVE for this product: if the customer can pay today, offer '
                              + spoken(first_day) + ' (' + first_day.isoformat() + ') instead.')
            plan.append(dict(name=name, full=round(full, 2), floor=round(min(floor, full), 2), today=today.isoformat(), first_day=first_day.isoformat(), ask_day=ask_day.isoformat(), statement=intro[-1],
                             first=am['first_offer'], lo=min(am['accept_min'], am['accept_max']), hi=am['accept_max'], tm=am['too_much'], bm=am['below_min'],
                             deadline=deadline.isoformat() if deadline else '', ladder=lad, spoken=spoken_days,
                             floor_name=floor_name if typ and typ['floor_field'] != pf['past_due'] and floor_name.split()[-1] in NOUNS else ''))
        # A short calendar: weekdays and deadlines only. Named days are checked by the date_check code node,
        # so the model never needs to apply the date rules to this list itself (and a short prompt is a fast turn).
        last = max([dd for (dd, n, name) in dls if dd] or [today])
        span = max(14, min(35, (last - today).days + 3))
        lines = []
        for j in range(0, span):
            d = today + _dt.timedelta(days=j)
            tag = ('today, ' if j == 0 else '') + ('business day' if is_business_day(d, CFG) else 'NOT a business day')
            for (dd, n, name) in dls:
                if dd and d == dd:
                    tag += ', DEADLINE of ' + (('product ' + n + ' (' + name + ')') if len(dls) > 1 else 'the product')
            lines.append(WEEKDAYS[d.weekday()].capitalize() + ' ' + str(d.day) + ' ' + MONTHS[d.month - 1].capitalize() + ' (' + d.isoformat() + '): ' + tag)
        monday = today - _dt.timedelta(days=today.weekday())
        w1 = ', '.join(spoken(monday + _dt.timedelta(days=j)) for j in range(7))
        w2 = ', '.join(spoken(monday + _dt.timedelta(days=7 + j)) for j in range(7))
        vars['calendar_text'] = '\\n'.join(lines) + '\\nTHIS calendar week: ' + w1 + '\\nNEXT calendar week: ' + w2
        vars['deal_facts'] = '\\n'.join(facts)
        vars['n_products'] = str(len(ps))
        ask = CFG['first_ask_all'] if (len(ps) > 1 and CFG['first_ask_all']) else CFG['first_ask']
        if len(ps) > 1 and not CFG.get('state_all_first', True):           # the first product only, then each when reached
            vars['deal_intro'] = ' '.join([CFG['intro'], intro[0], CFG['first_ask']])
        elif len(ps) > 1 and not CFG.get('ask_all_once', True):            # all stated, "today" asked per product
            vars['deal_intro'] = ' '.join([CFG['intro']] + intro + ['Let us start with your ' + plan[0]['name'] + '.', CFG['first_ask']])
        else:
            vars['deal_intro'] = ' '.join([CFG['intro']] + intro + [ask])
        vars['deal_intro'] = _say(vars['deal_intro'])
        vars['neg_plan'] = json.dumps(plan)
        vars['nst'] = ''
        vars['say_text'] = vars['deal_intro']
        vars['say_instr'] = ''
        vars['deal_facts_short'] = ' '.join(pp['name'] + ': ' + _money(pp['full']) + ' past due' + ('; latest promise date ' + spoken_days.get(pp['deadline'], pp['deadline']) if pp['deadline'] else '') + '.' for pp in plan)
        vars['deal_state'] = 'ready'
except Exception:
    vars['deal_state'] = 'none'
"""
        if self.mode == "orch":
            trans = [tr("negotiate", "the account is ready", eq("deal_state", "ready"))]
        else:
            trans = [tr(f"negotiate_{k}", f"{k} item(s) on the account", eq("n_products", str(k))) for k in range(self.maxp, 0, -1)]
        self.nodes["prepare_deal"] = self.code("prepare_deal", SAY_DEF + body, trans + [tr(service, "no product data")])

    def negotiate(self):
        if self.mode == "orch":
            return self.negotiate_orch()
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
        std = self.amount_std()
        rules = (
            "A. Amounts. " + ("You propose every amount; never ask an open question about how much they can pay"
                              + (f" (forbidden: {'; '.join(neg['forbidden_questions'])})" if neg["forbidden_questions"] else "") + ". " if am["never_ask_open_amount"] else "")
            + ("Start with the full past-due amount. " if std else "Each product's AMOUNT RULES in the FACTS give its amounts; they replace the amounts named below. Start with its first offer. ")
            + f"If the customer says the full amount is too much, offer that product's {'minimum acceptable amount' if std else 'too-much offer'} {times(am['too_much']['times'])} only"
            + (f", and in the same sentence say: '{am['too_much']['say']}'" if am["too_much"]["say"] else "") + ". "
            + ("If they refuse it, that is a flat refusal. " if am["too_much"]["refused_is_flat_refusal"] else "")
            + "After you named that amount once, never say it again for that product until the read-back: a later proposal names only the date. "
            + ("An amount the customer proposes from the minimum acceptable amount up to the full amount (both included) is accepted. " if std
               else "An amount the customer proposes inside the product's acceptable range (both ends included) is accepted. ")
            + "Below it, say: '" + (am["below_min"]["say"] or "That amount cannot be accepted.") + "' " + ("Offer the minimum acceptable amount once" if std else "Offer the product's below-range offer once")
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
            + "When the SYSTEM DATE CHECK at the top names a date to offer, offer exactly that date: it already applies these rules.\n"
            + ("C. A date or an amount the customer proposes is never a refusal; handle it with A and B.\n" if neg["proposal_never_refusal"] else "")
            + f"D. {neg['flat_refusal_definition']} A flat refusal is NOT the same as saying the full amount is too much: after a flat refusal never offer the minimum acceptable amount unless the product's next attempt in the FACTS is that amount. "
            + "A flat refusal uses ONE persuasion attempt of that product; make the product's attempts from the FACTS in order, each with exactly its amount and date. "
            + "When a product's attempts are used up, stop: never repeat a refused offer. "
            + ("That product ends without a promise and you move to the next one.\n" if self.notes else f"Then call transition_to_{exhausted_exit}.\n")
            + (f"E. Confirm. Read back {', '.join(conf['read_back'])} of every agreed promise together, with the date's day name, and ask '{conf['question']}'. "
               + ("Only after a clear yes, CALL the create_promise tool of each agreed product, one per message, in product order. " if conf["require_clear_yes"] else "Then CALL the create_promise tool of each agreed product. ")
               if self.flag("single_read_back") else
               f"E. Confirm. As soon as one product's promise is agreed, read back {', '.join(conf['read_back'])} of that promise alone, with the date's day name, and ask '{conf['question']}'. "
               + ("Only after a clear yes, CALL that product's create_promise tool, then continue with the next product. " if conf["require_clear_yes"] else "Then CALL that product's create_promise tool and continue with the next product. "))
            + "Word the read-back as the customer's own promise ('Let me read your promise back: you will pay ...'), never as a new offer. "
            + "Saying it is recorded is not enough; you must call the tool. If the customer changes a date or an amount at the read-back, check it against A and B and read back again. "
            + (f"{conf['after_record_change_say']} " if conf["after_record_change_say"] else "")
            + "F. Follow the what_to_do_next line in every tool result exactly. Never tell the customer anything is recorded unless its tool result says so. "
            + f"If a create_promise call fails the first time, say exactly '{rec['retry_say']}' and call the same tool again at once with the same values. "
            + "If it fails the last time, " + (rec["failure_say"] if rec["failure_say"] else "say you could not complete it") + ".\n")
        if self.notes:
            rules += (("G. Notes. After the promises are recorded, CALL the add_note tool of every product WITHOUT a recorded promise, with its reason: "
                       + f"{exhausted.get('note_reason', '')} when its attempts were used up, " if self.flag("note_exhausted") else
                       "G. Notes. A product whose attempts were used up gets NO note. After the promises are recorded, CALL the add_note tool only of a product that ended for one of these reasons: ")
                      + ", ".join(f"{a['note_reason']} when {x['trigger'][0].lower() + x['trigger'][1:]}" for x in note_sits for a in x["effect"]["actions"] if a["type"] == "note")
                      + (f", {fin_fail.get('note_reason')} when its create_promise failed the last time" if fin_fail.get("note_reason") else "")
                      + ". " + ("Never call add_note when the call is being transferred. " if s["notes"]["on_transfer"] == "none" else "") + "\n")
        others = []
        for x in neg_sits:
            line = f"- {self.sit_desc(x, guard=True)} "
            if x["guidance"]:
                line += x["guidance"] + " "
            if x.get("offer"):
                # the offer is made once by its own node; the model here only hands over
                line = f"- {self.sit_desc(x)}" + f" Call transition_to_{self.offer_node(x)} at once, without saying anything else first. "
            elif x in note_sits:
                if x["say_exact"] and x["say"]:
                    line += f"Say exactly: '{x['say']}' "
                line += "Take no promise for that product; it ends with its note and you continue with the other products. "
            else:
                if x["threshold"] > 1 and x["first_response"]:
                    line += f"The first time: {x['first_response']} If it happens {x['threshold']} times, "
                if self.s["multi_product"]["unrecorded_on_transfer"] == "record" and any(a["type"] == "transfer" for a in x["effect"]["actions"]):
                    line += "Before that, CALL the create_promise tool of every product whose promise the customer already confirmed and that is not recorded yet; then "
                line += f"call transition_to_{self.situation_exit(x)}. "
            if x["suppresses_persuasion"] and x.get("proposal_still_handled") and not x.get("offer"):
                line += "Make no persuasion attempt, but if the customer still names a date or an amount themselves, handle it with A and B. "
            others.append(line)
        if others:
            # a situation exit cannot be undone, so the everyday replies that only look like one are named as not being one
            others.insert(0, "Each of these applies only when the customer clearly says it. By itself, a plain no, or saying they cannot pay, is NOT one of them: the rules above handle it. "
                             "A question about what else is possible or what their options are is NOT one of them either: say in one short sentence that you cannot offer other terms, "
                             "then go on with the rules above. But when the customer's message also asks in so many words for what one of them describes, "
                             "that one applies, even if the same message says they cannot pay; the customer does not have to repeat it.")
        free = [r["text"] for r in s["free_rules"] if set(r["applies_to"]) & {"negotiation", "confirmation", "all"}]
        for k in range(1, self.maxp + 1):
            plist = ", ".join(f"product {i} ({{{{p{i}_words}}}}: create_promise_{i}" + (f", add_note_{i}" if self.notes else "") + ")" for i in range(1, k + 1))
            many = k > 1
            task = ("SYSTEM DATE CHECK (computed from the rules; when it names a date to offer, offer exactly that date now): {{date_note}}\n"
                    "You are on the collections part of the call. The customer is verified. Today is {{today_spoken}} ({{today_iso}}). "
                    + ("Your opening line already stated every late product and asked whether the customer can pay " + ("all of them" if many else "it") + " today. Never ask about today again. "
                       if not many or (self.flag("state_all_first") and self.flag("ask_all_once")) else
                       ("Your opening line stated only product 1 and asked whether the customer can pay it today. When you start another product, first say its Statement from the FACTS and ask whether they can pay it today. "
                        if not self.flag("state_all_first") else
                        "Your opening line stated every late product and asked whether the customer can pay product 1 today. When you start another product, first ask whether they can pay it today. ")
                       + "A no to that question is not a persuasion attempt. ")
                    + 
                    f"Products, in this order: {plist}. Each product has its OWN tools; use only the tools of the product you mean. One tool call per message.\n"
                    "FACTS:\n{{deal_facts}}\nCALENDAR (the only source for dates; never work out dates yourself):\n{{calendar_text}}\n\n"
                    "HOW THE CALL GOES\n1. If the customer can pay " + ("all of them" if many else "it") + " today, the promise is the full past-due amount today" + (" for every product" if many else "") + "; go to the read-back.\n"
                    + ("2. Otherwise go through the products ONE BY ONE in the order above. "
                       + ("For each product start at attempt 1 and count its persuasion attempts separately, with that product's own facts.\n" if self.flag("attempts_per_product") else
                          "Persuasion attempts are counted for the whole call, not per product: "
                          + (f"at most {self.flags()['call_attempt_limit']} in the whole call; when they are used up, every product left ends without a promise. "
                             if self.flags().get("call_attempt_limit") else "attempts already made for earlier products count against each later product's allowed attempts. ")
                          + "Use each product's own facts.\n")
                       + (f"3. {s['multi_product']['one_date_rule']}\n" if s["multi_product"].get("one_date_rule") else
                          "3. If the customer names ONE date for everything: use it for every product where it is allowed. If it is after one product's deadline, that product goes on its OWN deadline; say so in the read-back. The others keep the date the customer named.\n"
                          if s["multi_product"]["one_date_clamped_per_product"] else
                          "3. If the customer names ONE date for everything: check it for each product with rule B; a product that cannot have it is handled on its own with rule B.\n")
                       if many else "2. Otherwise follow the rules below.\n")
                    + "\nRULES\n" + rules + "\nOTHER SITUATIONS\n" + "\n".join(others)
                    + ("\n" + "\n".join("- " + t for t in free) if free else "")
                    + ("\n- When every product has a recorded promise" + (" or a saved note" if self.notes else "") + ", the system ends the call; do not say goodbye yourself."
                       if self.flag("note_exhausted") else
                       "\n- When every product is done (a recorded promise, a saved note, or no promise after its attempts), call transition_to_finalize; do not say goodbye yourself."))
            tools = [self.cp_tool(i, fail_exit) for i in range(1, k + 1)] + ([self.note_tool(i) for i in range(1, k + 1)] if self.notes else [])
            # "every product is done" is checked by routing on the variables, not by the tool hooks: two tools
            # called in one message run their hooks on separate copies, so no single hook sees all results
            all_done = {"logic": "or", "conditions": [{"variable": "all_done", "operator": "equals", "operand": "yes"},
                                                      {"logic": "and", "conditions": [{"variable": f"res_{i}", "operator": "not_equals", "operand": "none"} for i in range(1, k + 1)]}]}
            trans = [tr("finalize", "Every product is done", all_done),
                     tr("date_check", "The customer named a payment day", {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                         {"variable": "named_day_text", "operator": "is_set"}, {"variable": "named_day_text", "operator": "not_equals", "operand": ""}]}]})]
            if fail_exit:
                trans.append(tr(fail_exit, "A promise failed the last time", {"logic": "or", "conditions": [
                    {"variable": f"cp{i}_fail", "operator": "greater_than", "operand": rec["max_attempts"] - 1} for i in range(1, k + 1)]}))
            if self.notes:
                trans.append(tool_t("finalize", "Every product now has either a recorded promise or a saved note" if self.flag("note_exhausted")
                                    else "Every product is done: a recorded promise, a saved note, or no promise after its attempts"))
            for x in exit_sits:
                if x.get("offer"):
                    trans.append(tool_t(self.offer_node(x), x["trigger"] + (" NOT this: " + x["not_this"] if x["not_this"] else "")))
                else:
                    trans.append(tool_t(self.situation_exit(x), self.sit_trigger(x, with_not=True)))
            if exhausted_exit:
                trans.append(tool_t(exhausted_exit, "All allowed persuasion attempts are used up and the customer still refuses"))
            self.nodes[f"negotiate_{k}"] = {"name": f"negotiate_{k}", "node_type": "conversation",
                                            "on_enter": {"type": "tts", "text": "{{deal_intro}}"}, "on_enter_first_entry_only": True,
                                            "task_message": task, "tools": tools, "max_node_turns": 60,
                                            "extraction_schema": [extr("named_day_text", "The payment day the customer names in their LATEST message, copied exactly as said (for example 'Monday the twenty-sixth', 'next Friday', 'the week after next'). Empty if the latest message names no day.")],
                                            "max_turn_transition": "finalize" if self.notes else exhausted_exit, "transitions": trans}
        self.date_check()
        self.finalize()

    def date_check(self):
        """After every customer turn that names a day: code resolves it against `now` and applies the SPEC's date
        rules per product. The extractor may re-read an old day from the history, so code decides what is new."""
        body = """
try:
    said = str(vars.get('named_day_text') or '').strip()
    vars['named_day_text'] = ''
    now = parse_now(vars.get(CFG['now_var'])) or _dt.datetime.now()
    today = now.date()
    r = resolve_spoken_date(said, today, CFG)
    key = r['status'] + ':' + r['date']
    if said and key != str(vars.get('day_checked') or ''):
        vars['day_checked'] = key
        n = int(str(vars.get('n_products') or '1'))
        if r['status'] == 'exact':
            d = _dt.date.fromisoformat(r['date'])
            parts = []
            for i in range(1, n + 1):
                dl = str(vars.get('p' + str(i) + '_deadline') or '')
                v = check_promise_date(d, today, _dt.date.fromisoformat(dl) if dl else None, CFG)
                who = ('for the ' + str(vars.get('p' + str(i) + '_words') or ('product ' + str(i))) + ': ') if n > 1 else ''
                if v['verdict'] == 'ok':
                    parts.append(who + 'this day is allowed')
                elif v['verdict'] == 'offer':
                    od = _dt.date.fromisoformat(v['date'])
                    parts.append(who + 'this day is not allowed (' + v['why'] + '); offer ' + spoken(od) + ' (' + od.isoformat() + ') instead')
                else:
                    parts.append(who + 'this day is not possible (' + v['why'] + ')')
            vars['date_note'] = 'The customer named ' + spoken(d) + ' (' + d.isoformat() + '). ' + '. '.join(p[0].upper() + p[1:] for p in parts) + '.'
        elif r['status'] == 'vague':
            vars['date_note'] = 'The customer named a vague period, not a day. Apply the rule for vague periods.'
except Exception:
    vars['named_day_text'] = ''
"""
        trans = [tr(f"negotiate_{k}", f"back to the {k}-item negotiation", eq("n_products", str(k))) for k in range(self.maxp, 0, -1)]
        self.nodes["date_check"] = self.code("date_check", body, trans + [tr("negotiate_1", "always")])

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
        exact = bool(x["say_exact"] and x["say"])         # the brief prescribes the words: the engine says them
        task = (f"The customer just said something that means: {x['trigger']} "
                + (f"You already said, word for word: '{x['say']} {o['question']}' Wait for the answer. " if exact else
                   (f"Say: '{x['say']}' " if x["say"] else "") + (x["guidance"] + " " if x["guidance"] else "")
                   + f"Then, in the same turn: {o['question']} ")
                + "Make this offer ONCE only and never repeat it. "
                + ("Make no persuasion attempt and do not ask for any payment. " if x["suppresses_persuasion"] else "")
                + "If the customer asks a question, answer it in one sentence without repeating the offer. Do not call any tool.")
        trans = [tr(accept, "The customer accepted the offer", eq("offer_reply", "accept")),
                 tr(decline, "The customer declined the offer", eq("offer_reply", "decline"))]
        if "proposal" in values:
            if self.mode == "orch":
                trans.append(tr("neg_eval", "The customer named a date or an amount", eq("offer_reply", "proposal")))
            else:
                trans += [tr(f"negotiate_{k}", "The customer named a date or an amount", {"logic": "or", "conditions": [{"logic": "and", "conditions": [
                    {"variable": "offer_reply", "operator": "equals", "operand": "proposal"}, {"variable": "n_products", "operator": "equals", "operand": str(k)}]}]})
                          for k in range(1, self.maxp + 1)]
        self.nodes[name] = {"name": name, "node_type": "conversation",
                            "on_enter": {"type": "tts", "text": self.ph(x["say"] + " " + o["question"])} if exact else {"type": "llm"},
                            "on_enter_first_entry_only": True,
                            "task_message": task, "extraction_schema": [extr("offer_reply", desc, enum=values)] + (list(getattr(self, "orch_extraction", [])) if self.mode == "orch" else []),
                            "max_node_turns": 2, "max_turn_transition": decline, "transitions": trans}
        return name

    def notes_chain(self, reason, after="finalize", prefix=None):
        """Engine-run notes: one add_note per product that has no recorded promise, reason baked, then `after`
        (finalize by default). No model decides whether or how to note."""
        pre = prefix or f"note_all_{reason}"
        entry = f"{pre}_1"
        if entry in self.nodes:
            return entry
        f = self.tf["add_note"]
        for i in range(1, self.maxp + 1):
            gate, note = f"{pre}_{i}", f"{pre}_{i}_call"
            nxt = f"{pre}_{i + 1}" if i < self.maxp else after
            body = (f"try:\n    n = int(str(vars.get('n_products') or '0'))\n    go = {i} <= n and str(vars.get('res_{i}')) not in ('promise', 'note')\n"
                    f"    vars['note_go'] = 'yes' if go else 'no'\n    if go:\n        vars['res_{i}'] = 'note'\n        vars['note{i}_saved'] = CFG['r']\n"
                    f"except Exception:\n    vars['note_go'] = 'no'\n")
            self.nodes[gate] = code_node(gate, codegen.embed({"r": reason}, body, snippets=()), [tr(note, "this product needs a note", eq("note_go", "yes")), tr(nxt, "always")])
            self.nodes[note] = api_node(note, self.api_fn("add_note", {f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
                                                                       f["reason"]: {"type": "string", "default": reason}}, [f["reason"]]),
                                        [tr(nxt, "always")])
        return entry

    # ------------------------------------------------------------ orchestrated negotiation (mode "orch")

    def neg_cfg(self):
        s = self.s
        sits = {}
        if self.notes:
            for x in self.stage_situations("negotiation"):
                note = next((a["note_reason"] for a in x["effect"]["actions"] if a["type"] == "note"), None)
                if x["scope"] == "product" and note:
                    sits[x["id"]] = {"note": note, "say": x["say"]}
        ex = s["negotiation"]["attempts_exhausted"]
        return {"too_much_say": s["amounts"]["too_much"]["say"], "below_min_say": s["amounts"]["below_min"]["say"],
                "exhausted_note": ex.get("note_reason") or ex["reason"], "confirm_question": s["confirmation"]["question"],
                "floor_refused_is_flat": s["amounts"]["too_much"]["refused_is_flat_refusal"],
                "vague_asks": s["dates"]["vague"]["ask_exact_times"], "vague_then": s["dates"]["vague"]["then"], "product_situations": sits,
                "fail_note": s["recording"]["on_final_failure"].get("note_reason", ""),
                "one_date_clamped": bool(s["multi_product"]["one_date_clamped_per_product"]),
                "record_on": [], **self.flags()}

    def negotiate_orch(self):
        """Orchestrator v3. Extraction understands the turn (including situations), the state machine decides,
        TTS says the decided sentence word for word, and the engine records. The model speaks only to answer a
        question or to give a situation's first response (node negotiate_q)."""
        s, nc = self.s, self.neg_cfg()
        neg_sits = self.stage_situations("negotiation")
        call_sits = [x for x in neg_sits if x["id"] not in nc["product_situations"]]
        kinds = {"accept": "the customer agrees to what was just asked or proposed (yes, fine, that works, I confirm)",
                 "refuse": "a flat no: " + s["negotiation"]["flat_refusal_definition"],
                 "too_much": "the customer says the amount is too much or more than they can afford, without naming another amount",
                 "propose": "the customer names a payment day or an amount of their own",
                 "vague": "the customer names only a vague period, not a day" + (f" (for example: {'; '.join(s['dates']['vague']['examples'])})" if s["dates"]["vague"]["examples"] else ""),
                 "question": "the customer asks a question instead of answering, also when they ask what else is possible or what their options are"}
        evidence = {}                        # situation id -> the words the customer's own message must contain (SPEC)
        for x in neg_sits:
            words = self.evidence(x)
            kinds[x["id"]] = self.sit_desc(x, guard=True).rstrip(".") + (". Only when the customer asks for exactly this in their own words" if words else "")
            if words:
                evidence[x["id"]] = words
        kinds["unclear"] = "anything else, or the latest message is no answer to the agent's last question"
        # A situation exit cannot be undone, so the enum must not pull everyday replies into one (a customer who says
        # no and asks what else is possible is refusing and asking, not requesting a transfer).
        lead = "What the customer's LATEST message does, judged only from that message. "
        if neg_sits:
            lead += (f"Special situations: {', '.join(x['id'] for x in neg_sits)}. Choose one only when that message itself clearly says what its description says; "
                     "then choose it over the other values. By itself, a plain no, saying they cannot pay, or asking what else is possible or what their options are "
                     "is NOT a special situation unless a description says so: choose one of the other values for it. "
                     "A message that says they cannot pay AND asks in so many words for what a description says is that special situation. ")
        lead += "If the message both refuses and asks a question, choose refuse. "
        self.orch_extraction = [
            extr("reply_kind", lead + " ".join(f"{k} = {v.rstrip('.')}." for k, v in kinds.items()), enum=list(kinds)),
            extr("asks_question", "yes if the LATEST message contains a question to the agent (also next to a refusal or an answer), otherwise no.",
                 enum=["yes", "no"]),
            extr("day_text", "The payment day the customer names in the LATEST message, copied exactly as said ('tomorrow', 'next Friday', 'the 26th'). Empty if none."),
            extr("amount_text", "The amount the customer names in the LATEST message, copied exactly as said ('two hundred', '150'). Empty if none."),
            extr("about_text", "Which product the LATEST message is about, copied as said ('the car loan', 'all of them'). "
                 + ("When the message says one of these things about a product, copy THAT product, also when the message then goes on to other products: "
                    + " | ".join(x["trigger"].strip().rstrip(".") for x in neg_sits if x["id"] in nc["product_situations"]) + ". "
                    if nc["product_situations"] else "")
                 + "Empty if not said.")]
        if evidence:
            # the customer's own words, for the evidence check in code; a copy needs no confidence gate
            self.orch_extraction.append(extr("said_text", "The customer's LATEST message, copied word for word, without shortening or rewording it.", conf=0.05))
        # situation exits, chosen by code from the extracted kind
        sit_cfg, sit_trans = {}, []
        for x in call_sits:
            target = self.offer_node(x) if x.get("offer") else self.situation_exit(x)
            if not x.get("offer") and s["multi_product"]["unrecorded_on_transfer"] == "record" and any(a["type"] == "transfer" for a in x["effect"]["actions"]):
                target = self.record_chain(target, prefix=f"rx_{x['id']}")      # record agreed promises, then transfer
                nc["record_on"].append("sit_" + x["id"])
            sit_cfg[x["id"]] = {"threshold": int(x["threshold"]), "first": x["first_response"]}
            sit_trans.append(tr(target, x["trigger"], eq("neg_next", "sit_" + x["id"])))
        turn_nodes = ["negotiate", "negotiate_q"] + [f"offer_{x['id']}" for x in call_sits if x.get("offer")]
        account = "{{deal_facts_short}}"
        free = [r["text"] for r in s["free_rules"] if set(r["applies_to"]) & {"negotiation", "confirmation", "all"}]
        common = {"extraction_schema": self.orch_extraction, "max_node_turns": 60, "max_turn_transition": "neg_close",
                  "transitions": [tr("neg_eval", "every customer turn goes to the negotiation logic")]}
        self.nodes["negotiate"] = dict({"name": "negotiate", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{say_text}}"},
                                        "task_message": "Say nothing of your own. Do not call a tool."}, **common)
        self.nodes["negotiate_q"] = dict({"name": "negotiate_q", "node_type": "conversation", "on_enter": {"type": "llm"},
                                          "task_message": ("You are on the collections part of the call; the customer is verified. Today is {{today_spoken}}.\n"
                                                           "Do this now, in one or two short sentences: {{say_instr}} Then say this, word for word: {{say_text}}\n"
                                                           "Use only these facts; never make an offer of your own, never ask how much they can pay, never say anything is recorded, do not call a tool.\n"
                                                           "ACCOUNT: " + account + ("\nRULES:\n" + "\n".join("- " + t for t in free) if free else ""))}, **common)
        body = """
try:
    plan = json.loads(vars.get('neg_plan') or '[]')
    raw = vars.get('nst')
    st = json.loads(raw) if raw else new_state(plan)
    st.setdefault('sit', dict())
    turn = str(sum(int(float(str(vars.get(n + '.total_turns') or 0))) for n in CFG['turn_nodes']))
    now = parse_now(vars.get(CFG['now_var'])) or _dt.datetime.now()
    kind = str(vars.get('reply_kind') or 'unclear')
    nxt, say, instr = 'talk', str(vars.get('say_text') or ''), ''
    if turn != str(vars.get('neg_turn_done') or ''):
        unsure = kind in CFG['evidence'] and not situation_confirmed(kind, vars.get('said_text'), st, CFG['evidence'][kind])
        if unsure:
            kind = UNCONFIRMED
        ev = dict(kind=kind, day=vars.get('day_text'), amount=vars.get('amount_text'), about=vars.get('about_text'))
        if kind in CFG['call_situations']:
            c = int(st['sit'].get(kind, 0)) + 1
            st['sit'][kind] = c
            sc = CFG['call_situations'][kind]
            if c < sc['threshold'] and sc['first']:
                nxt, instr = 'ask', sc['first']
            else:
                nxt = 'sit_' + kind
        else:
            st, say2, nxt = step(st, ev, plan, now.date(), CFG)
            say = say2 or say
            if nxt == 'close' and say2:
                # the negotiation ends on this turn and no step speaks any more: a sentence the state machine still
                # owes the customer (a situation's prescribed words on the last open product) is said with the farewell
                vars['close_say'] = _say(say2).strip()
            if say.startswith('ASK_FIRST: '):
                say, nxt = say[len('ASK_FIRST: '):], 'ask'
                instr = ('The customer asked for something you cannot offer on this call. Say so in one short sentence, without naming or describing any alternative.' if unsure
                         else 'Answer the customer question in one short sentence, using only the facts given. If it is about an amount or a day you already offered, '
                              'state it as a fact (for example: that is the amount I mentioned) and do not offer it again.')
            elif nxt == 'talk' and say and str(vars.get('asks_question') or '') == 'yes':
                # a refusal (or an answer) with a question in it: the turn is decided as usual, the question is answered too
                nxt, instr = 'ask', 'Answer the customer question in one short sentence, using only the facts given.'
    if nxt == 'ask':
        try:                                     # what is on the table, as a fact for the answer (never a new offer)
            cx, cp = st['p'][st['cursor']], plan[st['cursor']]
            if cx['status'] == 'open' and st.get('phase') != 'confirm':
                fn = str(cp.get('floor_name') or '')
                low = bool(fn) and cx['offer_amt'] < cp['full'] and abs(cx['offer_amt'] - cp['floor']) < 0.005
                instr += (' The offer that is open is ' + ('%.2f' % float(cx['offer_amt'])) + (' (the ' + fn + ')' if low else '') + ' for the ' + cp['name']
                          + ' on ' + str(cp['spoken'].get(cx['offer_date'], cx['offer_date'])) + ', and the full amount is ' + ('%.2f' % float(cp['full'])) + '.')
        except Exception:
            pass
    vars['asks_question'] = 'no'
    vars['neg_turn_done'] = turn
    vars['neg_error'] = str(st.pop('err', '') or '')
    vars['nst'] = json.dumps(st)
    for k in ('day_text', 'amount_text', 'about_text', 'said_text'):
        vars[k] = ''
    vars['reply_kind'] = 'unclear'          # consumed: a turn whose kind is not extracted must not repeat this one
    vars['say_text'] = _say(say)
    vars['say_instr'] = instr
    vars['neg_next'] = nxt
    for i, x in enumerate(st['p']):
        n = str(i + 1)
        if x['status'] == 'agreed' and (nxt == 'record' or nxt in CFG['record_on']):
            vars['res_' + n] = 'pending'
            vars['p' + n + '_amt'] = '%.2f' % float(x['amt'])
            vars['p' + n + '_date'] = x['date']
        elif x['status'] == 'ended':
            vars['res_' + n] = 'open'
            vars['p' + n + '_note_reason'] = x['note']
            vars['p' + n + '_end_why'] = x.get('why', 'situation')
except Exception as e:
    vars['neg_next'] = 'talk'
    vars['neg_error'] = 'neg_eval: ' + type(e).__name__
"""
        cfg = self.cfg(**nc, call_situations=sit_cfg, turn_nodes=turn_nodes, evidence=evidence)
        self.nodes["neg_eval"] = code_node("neg_eval", codegen.embed(cfg, SAY_DEF + body, snippets=("dates", "negotiation")),
                                           sit_trans + [tr("rec_gate_1", "the customer confirmed the read-back", eq("neg_next", "record")),
                                                        tr("neg_close", "nothing was agreed", eq("neg_next", "close")),
                                                        tr("negotiate_q", "answer a question or give a first response", eq("neg_next", "ask")),
                                                        tr("negotiate", "say the next sentence")])
        after = self.notes_by_product() if self.notes else "finalize"
        self.record_chain(after)
        exhausted = s["negotiation"]["attempts_exhausted"]
        if self.notes:
            self.nodes["neg_close"] = code_node("neg_close", codegen.embed({}, "vars['neg_closed'] = 'yes'\n", snippets=()), [tr(after, "always")])
        else:
            self.nodes["neg_close"] = code_node("neg_close", codegen.embed({}, "vars['neg_closed'] = 'yes'\n", snippets=()),
                                                [tr(self.exit("attempts_exhausted", exhausted["outcome"], exhausted["reason"], self.farewell()), "always")])
        self.finalize()

    def record_chain(self, after, prefix="rec"):
        """Engine-run promises: per agreed product, create_promise with id, amount and date baked from the state
        machine (a pre-hook makes the amount a number), retried with the SPEC's sentence, never claimed by a model.
        Returns the chain's entry; a second chain (another prefix) records before a transfer."""
        rec, f, ok = self.s["recording"], self.tf["create_promise"], self.s["recording"]["success_field"]
        tries = max(1, int(rec["max_attempts"]))
        for i in range(1, self.maxp + 1):
            gate, nxt = f"{prefix}_gate_{i}", (f"{prefix}_gate_{i + 1}" if i < self.maxp else after)
            okn, failn = f"{prefix}_ok_{i}", f"{prefix}_fail_{i}"
            self.nodes[gate] = code_node(gate, codegen.embed({}, f"vars['rec_go'] = 'yes' if str(vars.get('res_{i}')) == 'pending' else 'no'\n", snippets=()),
                                         [tr(f"{prefix}_{i}_1", "this product was agreed", eq("rec_go", "yes")), tr(nxt, "always")])
            pre = (f"try:\n    b = config.get('body')\n    if isinstance(b, dict):\n        b[{f['amount']!r}] = round(float(str(vars.get('p{i}_amt'))), 2)\n"
                   f"        b[{f['date']!r}] = str(vars.get('p{i}_date'))\nexcept Exception:\n    pass\n")
            for t in range(1, tries + 1):
                name, var = f"{prefix}_{i}_{t}", f"{prefix}_{i}_{t}_ok"
                body = {f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
                        f["amount"]: {"type": self.ftype("create_promise", "amount"), "default": "{{p%d_amt}}" % i},
                        f["date"]: {"type": "string", "default": "{{p%d_date}}" % i}}
                fail_to = f"{prefix}_{i}_{t + 1}" if t < tries else failn
                self.nodes[name] = api_node(name, self.api_fn("create_promise", body, [f["amount"], f["date"]], pre=pre),
                                            [tr(okn, "recorded", truthy(var)), tr(fail_to, "not recorded")],
                                            mapping=[{"path": "data." + ok, "variable": var}], say=(self.ph(rec["retry_say"]) if t > 1 else ""))
            # the close is known from here on: if the customer hangs up while the notes and the farewell are still on
            # their way, close_call says "promise", not the opening's default
            po = self.s["outcomes"]["promise"]
            self.nodes[okn] = code_node(okn, codegen.embed({"o": po["outcome"], "r": po["reason"]},
                                                          f"vars['res_{i}'] = 'promise'\nvars['outcome'] = CFG['o']\nvars['reason'] = CFG['r']\n", snippets=()), [tr(nxt, "always")])
            # the note that follows overwrites res_<i>: rec_failed keeps the fact for the close, so the customer is told
            self.nodes[failn] = code_node(failn, codegen.embed({}, f"vars['res_{i}'] = 'failed'\nvars['rec_failed'] = 'yes'\n", snippets=()), [tr(nxt, "always")])
        return f"{prefix}_gate_1"

    def notes_by_product(self):
        """Engine-run notes with each product's own reason (from the state machine), then finalize."""
        f = self.tf["add_note"]
        fail_note = self.s["recording"]["on_final_failure"].get("note_reason", "")
        for i in range(1, self.maxp + 1):
            gate, note = f"pnote_{i}", f"pnote_{i}_call"
            nxt = f"pnote_{i + 1}" if i < self.maxp else "finalize"
            body = (f"try:\n    n = int(str(vars.get('n_products') or '0'))\n    r = str(vars.get('res_{i}') or '')\n"
                    f"    reason = str(vars.get('p{i}_note_reason') or '') if r == 'open' else (CFG['fail'] if r == 'failed' else '')\n"
                    f"    if r == 'open':\n        vars['p{i}_end_reason'] = reason\n"
                    f"    skip = r == 'open' and str(vars.get('p{i}_end_why') or '') == 'exhausted' and not CFG['nx']\n"
                    f"    go = {i} <= n and r in ('open', 'failed') and bool(reason) and not skip\n    vars['note_go'] = 'yes' if go else 'no'\n"
                    f"    if go:\n        vars['p{i}_note_reason'] = reason\n        vars['res_{i}'] = 'note'\n        vars['note{i}_saved'] = reason\n"
                    f"except Exception:\n    vars['note_go'] = 'no'\n")
            self.nodes[gate] = code_node(gate, codegen.embed({"fail": fail_note, "nx": self.flag("note_exhausted")}, body, snippets=()),
                                         [tr(note, "this product needs a note", eq("note_go", "yes")), tr(nxt, "always")])
            self.nodes[note] = api_node(note, self.api_fn("add_note", {f["product_id"]: {"type": "string", "default": "{{p%d_id}}" % i},
                                                                       f["reason"]: {"type": "string", "default": "{{p%d_note_reason}}" % i}}, [f["reason"]]),
                                        [tr(nxt, "always")])
        return "pnote_1"

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
        last = (f"Tell the customer: {rec['failure_say']} " + (f"Then call add_note_{i} with reason {rec['on_final_failure'].get('note_reason')}, and continue with the other products." if self.notes and self.mode != "orch" else ""))
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
            {"vars['res_" + str(i) + "'] = 'failed'" if self.mode == "orch" else "pass"}
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
        if not r and CFG.get('reason_from_state'):
            r = str(vars.get('p' + s + '_end_reason') or '') or CFG['exhausted_reason']
        reasons.append(r)
    m = CFG['multi_rule']
    failed = any(str(vars.get('res_' + str(j))) == 'failed' for j in range(1, n + 1)) or str(vars.get('rec_failed') or '') == 'yes'
    if promised == 0 and failed and not m:
        vars['outcome'] = CFG['fail_outcome']['outcome']
        vars['reason'] = CFG['fail_outcome']['reason']
        vars['farewell'] = (CFG['fail_say'] + ' ' + CFG['farewell']).strip()
    elif promised > 0:
        vars['outcome'] = CFG['promise_outcome']['outcome']
        vars['reason'] = CFG['promise_outcome']['reason']
        vars['farewell'] = ((CFG['fail_say'] + ' ' if failed else '') + CFG['after_success'] + ' ' + CFG['farewell']).strip()
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
        hit = None
        for r in reasons:                        # no closing rule for several products: the first product's own ending decides
            if r:
                hit = CFG['by_note'].get(r)
                break
        vars['outcome'] = hit['outcome'] if hit else CFG['exhausted_outcome']
        vars['reason'] = hit['reason'] if hit else CFG['exhausted_reason']
        vars['farewell'] = CFG['farewell']
    # whatever the close: a promise that could not be saved is said, and so is a sentence the negotiation still owed
    if failed and promised == 0 and CFG['fail_say'] and CFG['fail_say'] not in vars['farewell']:
        vars['farewell'] = (CFG['fail_say'] + ' ' + vars['farewell']).strip()
    owed = str(vars.get('close_say') or '').strip()
    if owed and owed not in vars['farewell']:
        vars['farewell'] = (owed + ' ' + vars['farewell']).strip()
except Exception:
    vars['outcome'] = CFG['exhausted_outcome']
    vars['reason'] = CFG['exhausted_reason']
    vars['farewell'] = CFG['farewell']
"""
        ex = self.s["negotiation"]["attempts_exhausted"]
        # note reason -> how a call closes when a product ended for it (the situation's own close, the failed
        # recording's, the used-up attempts'); read only when the SPEC has no closing rule for several products
        by_note = {}
        if self.notes:
            for x in self.s["situations"]:
                for eff in [x["effect"]] + ([x["offer"]["on_decline"], x["offer"]["on_accept"]] if x.get("offer") else []):
                    for a in eff["actions"]:
                        if a["type"] == "note" and a.get("note_reason"):
                            by_note.setdefault(a["note_reason"], {"outcome": eff["outcome"], "reason": eff["reason"]})
            for rule in (self.s["recording"]["on_final_failure"], ex):
                if rule.get("note_reason"):
                    by_note.setdefault(rule["note_reason"], {"outcome": rule["outcome"], "reason": rule["reason"]})
        self.nodes["finalize"] = self.code("finalize", body, [tr("final_end", "always")], exhausted_outcome=ex["outcome"], exhausted_reason=ex["reason"], by_note=by_note,
                                            reason_from_state=self.notes and not self.flag("note_exhausted"),
                                            fail_outcome={"outcome": self.s["recording"]["on_final_failure"]["outcome"], "reason": self.s["recording"]["on_final_failure"]["reason"]},
                                            fail_say=self.s["recording"]["failure_say"])

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
        # every way to the end node passes one code node that fills the call's variables into the farewell
        for n in list(self.nodes.values()):
            for t in n.get("transitions") or []:
                if t["target_node"] == "final_end":
                    t["target_node"] = "say_farewell"
            for k in ("passthrough_default_transition", "max_turn_transition"):
                if n.get(k) == "final_end":
                    n[k] = "say_farewell"
        body = SAY_DEF + "try:\n    vars['farewell'] = _say(vars.get('farewell'))\nexcept Exception:\n    pass\n"
        self.nodes["say_farewell"] = code_node("say_farewell", codegen.embed({"call_vars": self.call_vars}, body, snippets=()), [tr("final_end", "always")])
        return {"initial_node": "setup", "system_prompt": self.system_prompt(), "tools": [self.close_tool()],
                "global_nodes": {}, "nodes": self.nodes}


def build(spec, tools, mode="v1"):
    return Gen(spec, tools, mode).build()


if __name__ == "__main__":       # python -m builder.generate <spec.json> <tool_api.json> <out.json>
    import sys
    from builder.ingest import parse_openapi
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    wf = build(spec, parse_openapi(sys.argv[2])["tools"])
    json.dump(wf, open(sys.argv[3], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("nodes", len(wf["nodes"]))
