"""The builder never ends without a SPEC it can generate from.

    binding = bind(tools)                         # what the Binder agent does, by rule, from the tool API alone
    spec, notes, left = coerce(raw, tools)        # any Reader output -> a SPEC that validates; `left`: errors that stay

A hidden brief is read once, with no manual step. If the Reader's SPEC still has problems after its repair rounds,
stopping would mean no phone agent at all. `coerce` instead keeps everything of the Reader's SPEC that is usable,
puts each value into the shape the schema asks for, repairs the cross-references (outcomes against the closing
table and the tool API, field names against the tool API, ladders, bands, ids) and fills what is missing from a
neutral skeleton. Whatever it had to drop or replace is kept as a free rule, so the phone agent still reads it.
Nothing here knows a brief: the skeleton is built from the tool API and holds only generic sentences.
"""
import copy, difflib, json, re

from builder import spec_schema as S

NUM = ("number", "integer")


def _req(tools, name):
    return (tools.get(name) or {}).get("request") or {}


def _resp(tools, name):
    return (tools.get(name) or {}).get("response") or {}


def _pick(fields, words=(), types=(), enum=None, fmt=(), exclude=(), last=False):
    """The field that fits a role best, scored by its name (earlier words weigh more), type, enum and format.
    '' when nothing fits; with `last`, the only field left counts as a fit."""
    best, top = "", 0
    cands = [(k, v) for k, v in fields.items() if k not in exclude and k]
    for name, f in cands:
        low = name.lower()
        score = sum(len(words) - i for i, w in enumerate(words) if w in low)
        score += 2 * (f.get("type") in types) + 2 * (bool(f.get("format")) and f.get("format") in fmt)
        if enum is not None:
            score += 2 if bool(f.get("enum")) == enum else -1
        if score > top:
            best, top = name, score
    if not best and last and len(cands) == 1:
        return cands[0][0]
    return best


def _words(text):
    return [w for w in re.findall(r"[a-z]+", str(text or "").lower()) if len(w) >= 3]


def _alike(a, b):
    """How many words two word lists share, a plural counting as its singular."""
    one = lambda w: w[:-1] if w.endswith("s") and len(w) > 3 else w
    return len({one(x) for x in a} & {one(y) for y in b})


def bind(tools):
    """The tool API's field names for the SPEC's roles, by rule. Never raises; a role nothing fits is ''."""
    present = [set(_req(tools, n)) for n in S.TOOL_NAMES if n in tools]
    common = set.intersection(*present) if present else set()
    cid = _pick({k: {} for k in common}, words=("customer", "client", "debtor", "account", "id")) or (sorted(common)[0] if common else "")
    rest = lambda n: {k: v for k, v in _req(tools, n).items() if k != cid}

    vi = rest("verify_identity")
    field = _pick(vi, words=("field", "question", "kind", "check", "type"), enum=True)
    answer = _pick(vi, words=("answer", "value", "response", "reply"), exclude=(field,), last=True)
    cp = rest("create_promise")
    pid = _pick(cp, words=("product", "item", "contract", "loan"))
    amount = _pick(cp, words=("amount", "sum", "value", "payment"), types=NUM, exclude=(pid,))
    date = _pick(cp, words=("date", "day", "when", "due"), fmt=("date", "date-time"), exclude=(pid, amount), last=True)
    an = rest("add_note")
    npid = _pick(an, words=("product", "item", "contract", "loan"))
    nreason = _pick(an, words=("reason", "code", "category", "type"), enum=True, exclude=(npid,))
    ntext = _pick(an, words=("text", "note", "comment", "detail", "message"), exclude=(npid, nreason))
    sc = rest("schedule_callback")
    cdate = _pick(sc, words=("date", "day"), fmt=("date",))
    ctime = _pick(sc, words=("time", "hour"), exclude=(cdate,), last=True)
    queue = _pick(rest("transfer_to_agent"), words=("queue", "team", "department", "desk", "group", "target"), enum=True, last=True)
    cc = rest("close_call")
    outcome = _pick(cc, words=("outcome", "result", "status", "disposition"), enum=True)
    creason = _pick(cc, words=("reason", "code", "detail"), exclude=(outcome,), last=True)

    vr = _resp(tools, "verify_identity")
    ok = _pick(vr, words=("ok", "success"), types=("boolean",))
    allv = _pick({k: v for k, v in vr.items() if "all" in k.lower() or "complete" in k.lower() or "passed" in k.lower()}, types=("boolean",), last=True)
    verified = _pick(vr, words=("verified", "match", "correct", "valid"), types=("boolean",), exclude=(ok, allv))
    left = _pick({k: v for k, v in vr.items() if v.get("type") in NUM}, words=("left", "remaining", "attempt", "tries", "wrong"), exclude=(ok, allv, verified), last=True)
    hint = _pick(vr, words=("hint", "tip", "suggest"), enum=True, exclude=(ok, allv, verified, left))

    ar = _resp(tools, "get_account")
    products = next((k for k, v in ar.items() if v.get("items")), "")
    items = (ar.get(products) or {}).get("items") or {}
    p_id = _pick(items, words=("product_id", "id"))
    p_type = _pick(items, words=("type", "kind", "category"), enum=True, exclude=(p_id,))
    p_due = _pick(items, words=("past_due", "overdue", "due", "arrears", "outstanding", "amount", "balance"), types=NUM, exclude=(p_id, p_type))
    p_days = _pick(items, words=("days_late", "days", "late", "dpd", "delay", "overdue"), types=NUM, exclude=(p_id, p_type, p_due))
    numeric = [k for k, v in items.items() if v.get("type") in NUM and k not in (p_due, p_days)]
    types = []
    for t in (items.get(p_type) or {}).get("enum") or []:
        tw = _words(str(t).replace("_", " "))
        # the floor: a number the API ties to this type (in its description or its name), else one named like a
        # minimum, else the full amount
        near = lambda k: _alike(tw, _words(items[k].get("description"))) + _alike(tw, _words(k.replace("_", " ")))
        floor = max(numeric, key=near, default="")
        if not floor or not near(floor):
            floor = _pick({k: items[k] for k in numeric}, words=("minimum", "min", "instal", "floor", "least")) or p_due
        types.append({"type": str(t), "spoken_name": str(t).replace("_", " "), "floor_field": floor})
    success = _pick(_resp(tools, "create_promise"), words=("ok", "success", "saved"), types=("boolean",)) or ok

    return {"tool_fields": {"customer_id": cid,
                            "verify_identity": {"field": field, "answer": answer},
                            "create_promise": {"product_id": pid, "amount": amount, "date": date},
                            "add_note": {"product_id": npid, "reason": nreason, "text": ntext},
                            "schedule_callback": {"date": cdate, "time": ctime},
                            "transfer_to_agent": {"queue": queue},
                            "close_call": {"outcome": outcome, "reason": creason}},
            "result_fields": {"ok": ok, "verified": verified, "all_verified": allv, "wrong_left": left, "hint": hint},
            "products_field": products, "product_fields": {"id": p_id, "type": p_type, "past_due": p_due, "days_late": p_days},
            "product_types": types, "success_field": success}


def _enum(tools, tool, field):
    return list((_req(tools, tool).get(field) or {}).get("enum") or []) if field else []


def _value_type(name, description=""):
    """How an identity answer is written, guessed from the question's name and the API's words about it."""
    low = (str(name) + " " + str(description)).lower()
    if "year" in low: return "year"
    if "date" in low or "birth" in low or "dob" in low: return "date"
    if any(w in low for w in ("last4", "last_4", "digits", "phone", "pin", "number", "last four")): return "digits"
    return "text"


def skeleton(tools):
    """A complete SPEC that validates against this tool API and says nothing a brief would have to say: generic
    sentences, no bands, no situations, every outcome sent without a reason. The base that `coerce` fills in."""
    b = bind(tools)
    tf = b["tool_fields"]
    outcomes = _enum(tools, "close_call", tf["close_call"]["outcome"]) or ["closed"]

    def named(*parts):
        return next((o for p in parts for o in outcomes if p in str(o).lower()), None)
    promise = named("promise", "agree", "commit", "arrang") or outcomes[0]
    nothing = named("refus", "declin", "unresolved", "no_p", "no_agree", "no_arr") or outcomes[-1]
    unreached = named("unreach", "reach", "contact", "answer") or nothing
    unverified = named("verif", "ident", "authent") or nothing
    pair = lambda o: {"outcome": o, "reason": ""}
    fields = _enum(tools, "verify_identity", tf["verify_identity"]["field"])
    answer_doc = (_req(tools, "verify_identity").get(tf["verify_identity"]["answer"]) or {}).get("description", "")
    return {
        "spec_version": S.SPEC_VERSION,
        "meta": {"bank_name": "the bank", "language": "English", "sources": []},
        "call_variables": [{"name": tf["customer_id"] or "customer_id", "role": "customer_id", "meaning": "passed to every tool call"},
                           {"name": "now", "role": "now", "meaning": "the current date and time of the call"}],
        "addressing": "the customer",
        "tool_fields": tf,
        "agent": {"self_description": "a digital assistant of the bank", "style_rules": []},
        "opening": {"first_sentence": "Hello, this is a digital assistant calling from your bank.", "confirm_question": "Am I speaking with the account holder?",
                    "forbidden_before_identity": [], "confirmations": ["yes", "speaking", "that is me"], "non_confirmations": [],
                    "max_asks": 2, "answer_question_first": True, "unclear": pair(unreached)},
        "third_party": {"enabled": False, "instructions": [],
                        "callback": {"enabled": False, "include_today": True, "business_days_ahead": 1, "window_start": "09:00", "window_end": "18:00",
                                     "inclusive": True, "after_now": True, "max_asks": 2, "scheduled": pair(unreached), "not_scheduled": pair(unreached)}},
        "identity": {"questions": [{"field": f, "ask": "Please tell me your " + str(f).replace("_", " ") + ".", "value_type": _value_type(f),
                                    "answer_format": "", "conversion": answer_doc} for f in fields],
                     "one_at_a_time": True, "max_wrong_total": 3, "wrong_may_retry": True, "hints": [],
                     "on_failed": {"say": "I could not verify your identity.", "outcome": unverified, "reason": ""},
                     "decline": {"explanation": "", "max_declines": 2, "purpose_question_counts": False, "outcome": unverified, "reason": ""},
                     "result_fields": b["result_fields"]},
        "account": {"products_field": b["products_field"], "product_fields": b["product_fields"], "product_types": b["product_types"], "max_products": 1,
                    "statement_intro": "I am calling about a late payment.",
                    "statement_per_product": "Your {spoken_name} is {days_late} days late with {past_due} past due."},
        "calendar": {"business_weekdays": [0, 1, 2, 3, 4], "holidays": []},
        "bands": [],
        "dates": {"earliest": {"kind": "today"}, "business_day_only": True, "non_business_day": "offer_next_business_day", "after_deadline": "offer_deadline",
                  "refused_deadline_is_flat_refusal": True, "vague": {"examples": [], "ask_exact_times": 1, "then": "propose_deadline"},
                  "relative_weekday": {"next": "following_week", "this": "current_week"}},
        "amounts": {"first_offer": {"kind": "full"}, "never_ask_open_amount": True, "accept_min": {"kind": "floor"}, "accept_max": {"kind": "full"},
                    "too_much": {"offer": {"kind": "floor"}, "times": 1, "say": "", "refused_is_flat_refusal": True},
                    "below_min": {"say": "", "offer": {"kind": "floor"}, "times": 1, "refused_is_flat_refusal": True}},
        "negotiation": {"first_ask": "Are you able to pay this amount today?", "proposal_never_refusal": True,
                        "flat_refusal_definition": "A no with no date and no amount.", "attempts_exhausted": pair(nothing),
                        "forbidden_offers": [], "forbidden_questions": []},
        "confirmation": {"read_back": ["product", "amount", "date"], "question": "Is that correct?", "require_clear_yes": True,
                         "on_change": "revalidate_and_read_back", "one_promise_per_product": True, "after_record_change_say": ""},
        "recording": {"max_attempts": 2, "success_field": b["success_field"], "after_success_say": "", "retry_say": "One moment please, let me try that again.",
                      "failure_say": "I am sorry, that did not work because of a technical problem.", "on_final_failure": pair(nothing)},
        "situations": [], "faq": [],
        "multi_product": {"enabled": False, "state_all_first": True, "ask_all_today_once": True, "first_ask_all": "", "order": "as_returned",
                          "attempts_per_product": True, "one_date_clamped_per_product": True, "single_read_back": True, "unrecorded_on_transfer": "drop"},
        "notes": {"enabled": False, "for_each_product_without_promise": True, "reasons": [], "on_transfer": "none"},
        "outcomes": {"table": [{"outcome": o, "reasons": [], "when": ""} for o in outcomes], "reason_omitted_for": list(outcomes),
                     "promise": pair(promise), "transfer_after_promise": "transfer_wins"},
        "closing": {"farewell": "Thank you for your time. Goodbye."},
        "free_rules": [], "rule_map": [],
    }


# ---------------------------------------------------------------- shape: any value into the schema's form

def _blank(t):
    if isinstance(t, S.Opt): t = t.t
    if t is str: return ""
    if t is int: return 0
    if t is bool: return False
    if isinstance(t, S.Enum): return t.values[0]
    if isinstance(t, S.Rule): return {"kind": next(k for k, params in t.kinds.items() if not params)}
    if isinstance(t, list): return []
    if isinstance(t, dict): return {k: _blank(v) for k, v in t.items() if not isinstance(k, S.Opt)}
    return ""


_PARAM = {"roll": "none", "week_offset": 0, "month_offset": 0}       # a rule parameter the Reader left out


def _rule(value, t, default, lost):
    if isinstance(value, str) and value in t.kinds:
        value = {"kind": value}
    if not isinstance(value, dict) or value.get("kind") not in t.kinds:
        lost.append(value)
        return copy.deepcopy(default)
    out = dict(value)
    for p in t.kinds[value["kind"]]:
        if p == "if_today_week_offset" and p not in out:
            out[p] = out.get("week_offset", 0)
        elif p not in out and p in _PARAM:
            out[p] = _PARAM[p]
        elif p in ("n", "percent", "week_offset", "month_offset", "if_today_week_offset"):
            try:
                out[p] = float(out[p]) if p == "percent" else int(float(out[p]))
            except (KeyError, TypeError, ValueError):
                lost.append(value)
                return copy.deepcopy(default)
    if out.get("roll") is not None and out["roll"] not in S.ROLL_VALUES:
        out["roll"] = "none"
    return out


def _fit(value, t, default, path, lost):
    """`value` in the form of schema part `t`. Where it cannot be, `default` fills in and the value goes to `lost`
    (path, value), so the caller can keep it as a free rule."""
    if isinstance(t, S.Opt):
        t = t.t
    if t is str:
        if isinstance(value, str): return value
        if isinstance(value, (int, float)) and not isinstance(value, bool): return str(value)
        if isinstance(value, list) and value and all(isinstance(x, str) for x in value): return " ".join(value)
        lost.append((path, value)); return default
    if t is bool:
        if isinstance(value, bool): return value
        if isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"): return True
        if isinstance(value, str) and value.strip().lower() in ("false", "no", "0"): return False
        if isinstance(value, (int, float)): return bool(value)
        lost.append((path, value)); return default
    if t is int:
        if isinstance(value, int) and not isinstance(value, bool): return value
        if isinstance(value, float) and value == int(value): return int(value)
        if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value): return int(value)
        lost.append((path, value)); return default
    if isinstance(t, S.Enum):
        if value in t.values: return value
        if isinstance(value, str):
            plain = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())
            for v in t.values:
                if plain(v) == plain(value): return v
        lost.append((path, value)); return default
    if isinstance(t, S.Rule):
        mine = []
        out = _rule(value, t, default, mine)
        lost.extend((path, v) for v in mine)
        return out
    if isinstance(t, list):
        if isinstance(value, (str, dict)):
            value = [value]
        if not isinstance(value, list):
            lost.append((path, value)); return copy.deepcopy(default)
        out = []
        for i, v in enumerate(value):
            sub = []
            item = _fit(v, t[0], _blank(t[0]), f"{path}[{i}]", sub)
            if isinstance(t[0], dict) and not isinstance(v, dict):
                lost.append((f"{path}[{i}]", v)); continue             # an item of the wrong kind says nothing
            if sub and not isinstance(t[0], dict):
                lost.extend(sub); continue                             # a wrong scalar in a list is dropped
            lost.extend(sub); out.append(item)
        return out
    if isinstance(t, dict):
        if not isinstance(value, dict):
            lost.append((path, value)); return copy.deepcopy(default)
        out = {}
        for k, sub in t.items():
            name, optional = (k.t, True) if isinstance(k, S.Opt) else (k, False)
            d = default.get(name) if isinstance(default, dict) and default.get(name) is not None else None
            if value.get(name) is not None:
                mine = []
                fitted = _fit(value[name], sub, d if d is not None else _blank(sub), f"{path}.{name}", mine)
                if optional and mine and any(p == f"{path}.{name}" for p, _ in mine):
                    lost.extend(mine); continue                        # an optional key in the wrong form is left out
                lost.extend(mine); out[name] = fitted
            elif not optional:
                out[name] = copy.deepcopy(d) if d is not None else _blank(sub)
                lost.append((f"{path}.{name}", None))
        known = {(k.t if isinstance(k, S.Opt) else k) for k in t}
        lost.extend((f"{path}.{k}", v) for k, v in value.items() if k not in known)
        return out
    return value


# ---------------------------------------------------------------- meaning: cross-references made right

def _closest(value, allowed):
    if value in allowed:
        return value
    m = difflib.get_close_matches(str(value), [str(a) for a in allowed], n=1, cutoff=0.6)
    return next((a for a in allowed if str(a) == m[0]), None) if m else None


def _pairs(node):
    """Every dict in the SPEC that holds an outcome with its reason."""
    if isinstance(node, dict):
        if isinstance(node.get("outcome"), str) and isinstance(node.get("reason"), str):
            yield node
        for v in node.values():
            yield from _pairs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _pairs(v)


def _hhmm(value, default):
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.h](\d{2}))?\s*(am|pm)?\s*", str(value or "").lower().replace(" ", ""))
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if m.group(3) == "pm" and h < 12: h += 12
    if m.group(3) == "am" and h == 12: h = 0
    return "%02d:%02d" % (h, mi) if 0 <= h <= 23 and 0 <= mi <= 59 else default


def _iso(value):
    s = str(value or "").strip()
    if S.ISO_DATE.match(s):
        return s
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)             # day first, as European documents write it
    return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))) if m and int(m.group(2)) <= 12 and int(m.group(1)) <= 31 else None


def _actions(sit):
    yield sit["effect"]
    if sit.get("offer"):
        yield sit["offer"]["on_accept"]
        yield sit["offer"]["on_decline"]


def _mend(spec, tools, base, say):
    """Make every cross-reference the validator checks hold. Each step is safe to repeat."""
    b = bind(tools)
    spec["spec_version"] = S.SPEC_VERSION
    tf = spec["tool_fields"]
    # --- field names against the tool API
    present = [n for n in S.TOOL_NAMES if n in tools]
    if not tf.get("customer_id") or any(tf["customer_id"] not in _req(tools, n) for n in present):
        if b["tool_fields"]["customer_id"]:
            say("tool_fields.customer_id", tf.get("customer_id")); tf["customer_id"] = b["tool_fields"]["customer_id"]
    for tool, roles in b["tool_fields"].items():
        if tool == "customer_id" or tool not in tools:
            continue
        for role, guess in roles.items():
            if tf[tool].get(role) and tf[tool][role] not in _req(tools, tool):
                say(f"tool_fields.{tool}.{role}", tf[tool][role]); tf[tool][role] = guess
            elif not tf[tool].get(role) and guess and role not in ("text", "reason"):
                tf[tool][role] = guess
    idn, acc = spec["identity"], spec["account"]
    vr = _resp(tools, "verify_identity")
    for role, guess in b["result_fields"].items():
        if idn["result_fields"].get(role) and idn["result_fields"][role] not in vr:
            say(f"identity.result_fields.{role}", idn["result_fields"][role]); idn["result_fields"][role] = guess
    if not idn["result_fields"].get("ok"):
        idn["result_fields"]["ok"] = b["result_fields"]["ok"]
    allowed = _enum(tools, "verify_identity", tf["verify_identity"]["field"])
    seen, qs, odd = set(), [], []
    for q in idn["questions"]:
        f = _closest(q["field"], allowed) if allowed else q["field"]
        if not f or f in seen:
            odd.append((len(qs), q)); continue
        seen.add(f)
        qs.append(dict(q, field=f, ask=q["ask"] or "Please tell me your " + str(f).replace("_", " ") + "."))
    free = [a for a in allowed if a not in seen]
    if odd and len(odd) == len(free):                     # as many unreadable questions as fields left: they pair up in order
        for (pos, q), f in reversed(list(zip(odd, free))):
            say("identity.questions.field", q["field"])
            qs.insert(pos, dict(q, field=f, ask=q["ask"] or "Please tell me your " + str(f).replace("_", " ") + "."))
    else:
        for _, q in odd:
            say("identity.questions", q)
    idn["questions"] = qs or copy.deepcopy(base["identity"]["questions"])
    hints = {e for f in vr.values() for e in f.get("enum") or []}
    idn["hints"] = [h for h in idn["hints"] if h["value"] in hints]
    idn["max_wrong_total"] = max(1, idn["max_wrong_total"])
    idn["decline"]["max_declines"] = max(1, idn["decline"]["max_declines"])
    ar = _resp(tools, "get_account")
    if not (ar.get(acc["products_field"]) or {}).get("items"):
        say("account.products_field", acc["products_field"]); acc["products_field"] = b["products_field"]
    items = (ar.get(acc["products_field"]) or {}).get("items") or {}
    for role, guess in b["product_fields"].items():
        if acc["product_fields"].get(role) not in items:
            say(f"account.product_fields.{role}", acc["product_fields"].get(role)); acc["product_fields"][role] = guess
    type_enum = (items.get(acc["product_fields"]["type"]) or {}).get("enum") or []
    guess_floor = {p["type"]: p["floor_field"] for p in b["product_types"]}
    seen, types = set(), []
    for p in acc["product_types"]:
        t = _closest(p["type"], type_enum) if type_enum else p["type"]
        if not t or t in seen:
            say("account.product_types", p); continue
        seen.add(t)
        floor = p["floor_field"] if p["floor_field"] in items else (guess_floor.get(t) or acc["product_fields"]["past_due"])
        name = S.PLACEHOLDER.sub(lambda m: m.group(0) if m.group(1) in items else "", p["spoken_name"] or str(t).replace("_", " "))
        types.append(dict(p, type=t, floor_field=floor, spoken_name=re.sub(r"\s+", " ", name).strip() or str(t).replace("_", " ")))
    acc["product_types"] = types or copy.deepcopy(b["product_types"])
    acc["max_products"] = max(1, acc["max_products"])
    spec["recording"]["max_attempts"] = max(1, spec["recording"]["max_attempts"])
    if not spec["recording"]["success_field"]:
        spec["recording"]["success_field"] = b["success_field"]
    # --- call variables and the sentences that use them
    cv = [v for v in spec["call_variables"] if v["name"]]
    for role, guess in (("customer_id", tf["customer_id"] or "customer_id"), ("now", "now")):
        having = [v for v in cv if v["role"] == role]
        for extra in having[1:]:
            extra["role"] = "other"
        if not having:
            same = next((v for v in cv if v["name"] == guess or (role == "now" and v["name"].lower() in ("now", "current_time", "call_time", "timestamp"))), None)
            if same: same["role"] = role
            else: cv.append({"name": guess, "role": role, "meaning": ""})
    spec["call_variables"] = cv
    names = {v["name"] for v in cv}
    strip = lambda text: re.sub(r"\s+", " ", S.PLACEHOLDER.sub(lambda m: m.group(0) if m.group(1) in names else "", text)).strip()
    spec["addressing"] = strip(spec["addressing"]) or base["addressing"]
    spec["opening"]["first_sentence"] = strip(spec["opening"]["first_sentence"]) or base["opening"]["first_sentence"]
    spec["opening"]["confirm_question"] = strip(spec["opening"]["confirm_question"]) or base["opening"]["confirm_question"]
    spec["opening"]["max_asks"] = max(1, spec["opening"]["max_asks"])
    for key in ("first_ask",):
        spec["negotiation"][key] = spec["negotiation"][key] or base["negotiation"][key]
    spec["confirmation"]["question"] = spec["confirmation"]["question"] or base["confirmation"]["question"]
    spec["closing"]["farewell"] = spec["closing"]["farewell"] or base["closing"]["farewell"]
    # --- calendar, callback window, bands
    cal = spec["calendar"]
    cal["holidays"] = list(dict.fromkeys(d for d in (_iso(h) for h in cal["holidays"]) if d))
    cal["business_weekdays"] = sorted({d for d in cal["business_weekdays"] if isinstance(d, int) and 0 <= d <= 6}) or [0, 1, 2, 3, 4]
    cb = spec["third_party"]["callback"]
    cb["window_start"], cb["window_end"] = _hhmm(cb["window_start"], "09:00"), _hhmm(cb["window_end"], "18:00")
    cb["max_asks"] = max(1, cb["max_asks"])
    bands, last = [], None
    for band in sorted(spec["bands"], key=lambda x: x["days_late_min"]):
        if band["days_late_min"] > band["days_late_max"]:
            band["days_late_min"], band["days_late_max"] = band["days_late_max"], band["days_late_min"]
        if last is not None and band["days_late_min"] <= last:
            band["days_late_min"] = last + 1
        if band["days_late_min"] > band["days_late_max"]:
            say("bands", band); continue
        band["ladder"] = [dict(st, attempt=i + 1) for i, st in enumerate(band["ladder"])]
        band["attempts"] = len(band["ladder"])
        band["name"] = band["name"] or f"band {len(bands) + 1}"
        last = band["days_late_max"]
        bands.append(band)
    spec["bands"] = bands
    # --- situations: ids, actions, queues, notes
    queues = _enum(tools, "transfer_to_agent", tf["transfer_to_agent"]["queue"])
    note_enum = _enum(tools, "add_note", tf["add_note"]["reason"])
    notes = spec["notes"]
    if "add_note" not in tools: notes["enabled"] = False
    if "schedule_callback" not in tools: cb["enabled"] = False
    notes["reasons"] = [r for r in notes["reasons"] if not note_enum or r in note_enum]
    seen, sits = set(), []
    for x in spec["situations"]:
        if not x["id"] or not x["trigger"]:
            say("situations", x); continue
        while x["id"] in seen:
            x["id"] += "_2"
        seen.add(x["id"])
        x["threshold"] = max(1, x["threshold"])
        for eff in _actions(x):
            kept = []
            for a in eff["actions"]:
                if a["type"] == "transfer":
                    q = _closest(a.get("queue"), queues) if queues else a.get("queue")
                    if not q or "transfer_to_agent" not in tools:
                        say(f"situations.{x['id']}", a); continue
                    a["queue"] = q
                elif a["type"] == "note":
                    r = a.get("note_reason")
                    if not r or (note_enum and r not in note_enum) or "add_note" not in tools:
                        say(f"situations.{x['id']}", a); continue
                    if notes["enabled"] and r not in notes["reasons"]:
                        notes["reasons"].append(r)
                elif a["type"] == "callback" and "schedule_callback" not in tools:
                    continue
                kept.append(a)
            eff["actions"] = kept
        sits.append(x)
    spec["situations"] = sits
    for holder in (spec["negotiation"]["attempts_exhausted"], spec["recording"]["on_final_failure"]):
        r = holder.get("note_reason")
        if r and notes["enabled"] and r not in notes["reasons"]:
            if note_enum and r not in note_enum: holder.pop("note_reason")
            else: notes["reasons"].append(r)
    spec["faq"] = [q for q in spec["faq"] if q["trigger"] and q["answer"]]
    spec["free_rules"] = [r for r in spec["free_rules"] if r["text"]]
    for r in spec["free_rules"]:
        r["applies_to"] = r["applies_to"] or ["all"]
    spec["rule_map"] = [r for r in spec["rule_map"] if r["rule"]]
    # --- outcomes: the closing table against the tool API, then every use against the table
    out = spec["outcomes"]
    api = _enum(tools, "close_call", tf["close_call"]["outcome"])
    rows = {}
    for row in out["table"]:
        o = _closest(row["outcome"], api) if api else row["outcome"]
        if not o:
            say("outcomes.table", row); continue
        rows.setdefault(o, {"outcome": o, "reasons": [], "when": row["when"]})
        rows[o]["reasons"] += [r for r in row["reasons"] if r and r not in rows[o]["reasons"]]
    fallback = base["negotiation"]["attempts_exhausted"]["outcome"]
    for pair in _pairs({k: spec[k] for k in ("opening", "third_party", "identity", "negotiation", "recording", "situations")} | {"o": {k: v for k, v in out.items() if k != "table"}}):
        o = pair["outcome"]
        if o not in rows:
            fixed = _closest(o, api) if api else o
            if not fixed:
                say("outcome", dict(pair)); fixed, pair["reason"] = (fallback if (not api or fallback in api) else api[0]), ""
            pair["outcome"] = o = fixed
            rows.setdefault(o, {"outcome": o, "reasons": [], "when": ""})
        if pair["reason"] and pair["reason"] not in rows[o]["reasons"]:
            rows[o]["reasons"].append(pair["reason"])
    if out.get("multi"):                                 # its second outcome has no reason of its own, so no pair finds it
        other = out["multi"]["otherwise"]
        if other["outcome"] not in rows:
            other["outcome"] = (_closest(other["outcome"], api) if api else other["outcome"]) or fallback
            rows.setdefault(other["outcome"], {"outcome": other["outcome"], "reasons": [], "when": ""})
    out["table"] = list(rows.values())
    out["reason_omitted_for"] = [o for o in dict.fromkeys(out["reason_omitted_for"]) if o in rows]
    for pair in _pairs({k: spec[k] for k in ("opening", "third_party", "identity", "negotiation", "recording", "situations")} | {"o": {k: v for k, v in out.items() if k != "table"}}):
        if not pair["reason"] and rows[pair["outcome"]]["reasons"] and pair["outcome"] not in out["reason_omitted_for"]:
            pair["reason"] = rows[pair["outcome"]]["reasons"][0]         # the bank wants a reason here: the first listed one
    return spec


def _note(path, value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"The bank's documents also say, about {path.replace('spec.', '', 1)} (follow it where it applies): {text[:500]}"


def coerce(raw, tools):
    """Any Reader output -> (SPEC that validates, notes on what was changed, validator errors that stay).
    The errors that can stay are about the tool API itself (a tool it does not have)."""
    notes, lost = [], []
    try:
        base = skeleton(tools)
    except Exception as e:                               # an API nothing can be read from: the caller builds without a SPEC
        return (raw if isinstance(raw, dict) else {}), [f"no skeleton: {type(e).__name__}"], ["tool API: could not be read"]
    try:
        spec = _fit(raw if isinstance(raw, dict) else {}, S.SCHEMA, base, "spec", lost)
        say = lambda path, value: lost.append((path, value))
        spec = _mend(spec, tools, base, say)
        stay = lambda errs: [e for e in errs if not e.startswith("tool API: tool")]
        errs = S.validate(spec, tools)
        reset = set()
        for _ in range(len(S.SCHEMA)):                   # a part that still fails goes back to the skeleton's
            bad = stay(errs)
            if not bad:
                break
            part = re.split(r"[.\[: ]", bad[0].replace("spec.", "", 1))[0]
            if part not in S.SCHEMA:
                part = "situations" if "situation" in bad[0] else ""
            if not part or part in reset:
                break
            reset.add(part)
            lost.append((part, spec.get(part)))
            spec[part] = copy.deepcopy(base[part])
            spec = _mend(spec, tools, base, say)
            errs = S.validate(spec, tools)
        if stay(errs):
            lost.append(("spec", raw)); spec, errs = base, S.validate(base, tools)
    except Exception as e:
        notes.append(f"coercion failed ({type(e).__name__}): the skeleton is used")
        spec, errs = base, S.validate(base, tools)
        lost.append(("spec", raw))
    # what was dropped or replaced still reaches the phone agent, as free rules
    n = 0
    for path, value in lost:
        if value in (None, "", [], {}):
            notes.append(f"{path}: missing, filled with a neutral value")
            continue
        notes.append(f"{path}: {json.dumps(value, ensure_ascii=False)[:120]} could not be used")
        if n < 12 and path != "spec":
            n += 1
            spec["free_rules"].append({"id": f"builder-{n}", "text": _note(path, value), "applies_to": ["all"], "source": "kept by the builder: not usable as a setting"})
    return spec, notes, [e for e in errs]
