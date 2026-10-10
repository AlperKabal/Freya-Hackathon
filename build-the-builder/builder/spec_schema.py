"""The SPEC: everything a bank's brief says, in a form the generator can read.

The generator (generate.py) knows MECHANISMS: a call has an opening, maybe a third party, an identity check, an
account step, a negotiation, a confirmation and a close. The SPEC holds the CONTENT: every sentence, number,
calendar, table and name. Nothing brief-specific may live in the generator.

Two ideas keep the SPEC general:
- Rules are built from generic kinds with parameters (DATE_RULE_KINDS, AMOUNT_RULE_KINDS), so another number of
  bands, other day counts or other offers are data, not code.
- Special situations are a catalogue (`situations`): each one says when it applies, what to say, what to do
  (ACTION_TYPES) and how the call closes. A new situation in a new brief is a new row, not new code.

Placeholders in SPEC text use single braces: {<call variable name>} for a call variable, {<role or field>} for
a product role or product field. The generator turns them into platform variables. Never write double braces in a
SPEC.

    errors = validate(spec)                 # structure only
    errors = validate(spec, tools)          # plus cross-checks against ingest.parse_openapi(...)["tools"]
"""
import re

SPEC_VERSION = 1

# The event guarantees these seven tool names; their fields and values come from the tool API file.
TOOL_NAMES = ["verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"]
STAGES = ["opening", "third_party", "identity", "negotiation", "confirmation"]
CALL_VARIABLE_ROLES = ["customer_id", "now", "address", "name", "other"]
VALUE_TYPES = ["date", "digits", "year", "text", "number"]
ACTION_TYPES = ["transfer", "note", "callback"]
# How a date is chosen. Every kind is implemented once in generator code, with its parameters from the SPEC.
DATE_RULE_KINDS = {
    "today": [],
    "deadline": [],                                   # the band's own deadline
    "nth_business_day_after_today": ["n"],
    "nth_calendar_day_after_today": ["n", "roll"],    # roll: next_business_day | previous_business_day | none
    "last_business_day_of_week": ["week_offset", "if_today_week_offset"],
    "last_business_day_of_month": ["month_offset"],
}
ROLL_VALUES = ["next_business_day", "previous_business_day", "none"]
# How an amount is chosen. "floor" is the product type's floor field.
AMOUNT_RULE_KINDS = {"full": [], "floor": [], "full_or_floor_if_too_much": [], "percent_of_full": ["percent"]}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


class Opt:
    """An optional key: validated when present."""
    def __init__(self, t): self.t = t


class Enum:
    def __init__(self, values): self.values = list(values)


class Rule:
    """A DATE or AMOUNT rule object: {"kind": ..., <params>}."""
    def __init__(self, kinds): self.kinds = kinds


DATE_RULE, AMOUNT_RULE = Rule(DATE_RULE_KINDS), Rule(AMOUNT_RULE_KINDS)
OUTCOME = {"outcome": str, "reason": str}            # reason "" when the outcome table lists none
ACTION = {"type": Enum(ACTION_TYPES), Opt("queue"): str, Opt("note_reason"): str}
EFFECT = {"actions": [ACTION], "outcome": str, "reason": str, Opt("ends_call"): bool,
          Opt("outcome_by_stage"): {Opt("before_identity"): OUTCOME, Opt("after_identity"): OUTCOME}}

SCHEMA = {
    "spec_version": int,
    "meta": {"bank_name": str, "language": str, "sources": [str]},
    # call variables the call starts with, and what each one is for
    "call_variables": [{"name": str, "role": Enum(CALL_VARIABLE_ROLES), "meaning": str}],
    "addressing": str,                                # how to address the customer, call variables in braces
    # semantic role -> request field name, per tool. "" means the API has no such field.
    "tool_fields": {
        "customer_id": str,
        "verify_identity": {"field": str, "answer": str},
        "create_promise": {"product_id": str, "amount": str, "date": str},
        "add_note": {"product_id": str, "reason": str, "text": str},
        "schedule_callback": {"date": str, "time": str},
        "transfer_to_agent": {"queue": str},
        "close_call": {"outcome": str, "reason": str},
    },
    "agent": {"self_description": str, "style_rules": [str]},
    "opening": {
        "first_sentence": str,                        # exact spoken text
        "confirm_question": str,                      # exact spoken text
        "forbidden_before_identity": [str],           # words never said before identity is verified
        "confirmations": [str], "non_confirmations": [str],
        "max_asks": int,
        "answer_question_first": bool,
        "unclear": OUTCOME,                           # still unclear after max_asks
    },
    "third_party": {
        "enabled": bool,
        "instructions": [str],                        # what to say and not say to someone else
        "callback": {
            "enabled": bool, "include_today": bool, "business_days_ahead": int,
            "window_start": str, "window_end": str, "inclusive": bool, "after_now": bool,
            "max_asks": int, "scheduled": OUTCOME, "not_scheduled": OUTCOME,
        },
    },
    "identity": {
        "questions": [{"field": str, "ask": str, "value_type": Enum(VALUE_TYPES), "answer_format": str, "conversion": str}],
        "one_at_a_time": bool,
        "max_wrong_total": int,
        "wrong_may_retry": bool,
        "hints": [{"value": str, "instruction": str, "counts_as_wrong": bool}],
        "on_failed": {"say": str, "outcome": str, "reason": str},
        "decline": {"explanation": str, "max_declines": int, "purpose_question_counts": bool, "outcome": str, "reason": str},
        # semantic role -> field name in the verify tool's response (names can change between briefs)
        "result_fields": {"ok": str, "verified": str, "all_verified": str, "wrong_left": str, "hint": str},
    },
    "account": {
        "products_field": str,                        # the list in the account tool's response
        "product_fields": {"id": str, "type": str, "past_due": str, "days_late": str},
        "product_types": [{"type": str, "spoken_name": str, "floor_field": str}],
        "max_products": int,
        "statement_intro": str,                       # said once, before the products
        "statement_per_product": str,                 # one sentence per product, placeholders = roles/fields
    },
    "calendar": {"business_weekdays": [int], "holidays": [str]},
    "bands": [{
        "name": str, "days_late_min": int, "days_late_max": int, "deadline": DATE_RULE, "attempts": int,
        "ladder": [{"attempt": int, "date": DATE_RULE, "amount": AMOUNT_RULE}],
    }],
    "dates": {
        "earliest": DATE_RULE,
        "business_day_only": bool,
        "non_business_day": Enum(["offer_next_business_day", "reject"]),
        "after_deadline": Enum(["offer_deadline", "reject"]),
        "refused_deadline_is_flat_refusal": bool,
        "vague": {"examples": [str], "ask_exact_times": int, "then": Enum(["propose_deadline", "flat_refusal"])},
        "relative_weekday": {"next": Enum(["following_week", "upcoming"]), "this": Enum(["current_week", "upcoming"])},
    },
    "amounts": {
        "first_offer": AMOUNT_RULE,
        "never_ask_open_amount": bool,
        "accept_min": AMOUNT_RULE, "accept_max": AMOUNT_RULE,
        "too_much": {"offer": AMOUNT_RULE, "times": int, "say": str, "refused_is_flat_refusal": bool},
        "below_min": {"say": str, "offer": AMOUNT_RULE, "times": int, "refused_is_flat_refusal": bool},
    },
    "negotiation": {
        "first_ask": str,                             # exact spoken question
        "proposal_never_refusal": bool,
        "flat_refusal_definition": str,
        "attempts_exhausted": {"outcome": str, "reason": str, Opt("note_reason"): str},
        "forbidden_offers": [str],
        "forbidden_questions": [str],
    },
    "confirmation": {
        "read_back": [str], "question": str, "require_clear_yes": bool,
        "on_change": Enum(["revalidate_and_read_back"]),
        "one_promise_per_product": bool, "after_record_change_say": str,
    },
    "recording": {
        "max_attempts": int,
        "success_field": str,                         # field in the promise tool's response that means success
        "after_success_say": str,                     # exact sentence after a recorded promise
        "retry_say": str,                             # said before the retry; never claims success
        "failure_say": str,                           # said when the last attempt failed
        "on_final_failure": {"outcome": str, "reason": str, Opt("note_reason"): str},
    },
    "situations": [{
        "id": str, "trigger": str, "not_this": str,   # not_this: what looks similar but is another situation
        "stages": [Enum(STAGES)],
        "say": str, "say_exact": bool,                # say: a sentence the agent speaks ("" if none); say_exact: the brief prescribes these words
        "guidance": str,                              # how the agent must behave here (an instruction, never spoken)
        "first_response": str, "threshold": int,     # say first_response until said `threshold` times, then act
        "suppresses_persuasion": bool, "priority": int,
        "proposal_still_handled": bool,               # a date or amount the customer names is still recorded
        "scope": Enum(["call", "product"]),           # product: note it and continue with the other products
        "effect": EFFECT,
        Opt("offer"): {"question": str, "on_accept": EFFECT, "on_decline": EFFECT},
        "source": str,
    }],
    "faq": [{"trigger": str, "answer": str, "source": str}],
    "multi_product": {
        "enabled": bool, "state_all_first": bool, "ask_all_today_once": bool, "first_ask_all": str,
        "order": Enum(["as_returned"]), "attempts_per_product": bool,
        "one_date_clamped_per_product": bool, "single_read_back": bool,
        Opt("one_date_rule"): str,
        "unrecorded_on_transfer": Enum(["drop", "record"]),
    },
    "notes": {"enabled": bool, "for_each_product_without_promise": bool, "reasons": [str], "on_transfer": Enum(["none", "add"])},
    "outcomes": {
        "table": [{"outcome": str, "reasons": [str], "when": str}],
        "reason_omitted_for": [str],
        "promise": OUTCOME,                           # at least one promise recorded
        "transfer_after_promise": Enum(["transfer_wins", "promise_wins"]),
        Opt("multi"): {
            "all_notes_match": {"note_reason": str, "outcome": str, "reason": str},
            "otherwise": {"outcome": str, "reason_from": Enum(["first_note_not_matching"])},
        },
    },
    "closing": {"farewell": str},
    "free_rules": [{"id": str, "text": str, "applies_to": [str], "source": str}],
    "rule_map": [{"rule": str, "fields": [str]}],
}


def _check(value, t, path, errors):
    if isinstance(t, Opt):
        t = t.t
    if t is str or t is bool:
        if not isinstance(value, t): errors.append(f"{path}: expected {t.__name__}, got {type(value).__name__}")
    elif t is int:
        if not isinstance(value, int) or isinstance(value, bool): errors.append(f"{path}: expected int, got {type(value).__name__}")
    elif isinstance(t, Enum):
        if value not in t.values: errors.append(f"{path}: {value!r} is not one of {t.values}")
    elif isinstance(t, Rule):
        if not isinstance(value, dict) or value.get("kind") not in t.kinds:
            errors.append(f"{path}: kind must be one of {sorted(t.kinds)}, got {value!r}")
            return
        for p in t.kinds[value["kind"]]:
            if p not in value: errors.append(f"{path}: kind {value['kind']} needs {p!r}")
        if value.get("roll") is not None and value["roll"] not in ROLL_VALUES: errors.append(f"{path}.roll: not one of {ROLL_VALUES}")
    elif isinstance(t, list):
        if not isinstance(value, list):
            errors.append(f"{path}: expected a list"); return
        for i, v in enumerate(value): _check(v, t[0], f"{path}[{i}]", errors)
    elif isinstance(t, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected an object"); return
        known = set()
        for k, sub in t.items():
            name = k.t if isinstance(k, Opt) else k
            known.add(name)
            if name in value:
                if value[name] is None: errors.append(f"{path}.{name}: null is not allowed")
                else: _check(value[name], sub, f"{path}.{name}", errors)
            elif not isinstance(k, Opt):
                errors.append(f"{path}.{name}: missing")
        for k in value:
            if k not in known: errors.append(f"{path}.{k}: unknown key")


def _outcome_pairs(spec):
    """Every (path, outcome, reason) the SPEC uses."""
    out = []
    def walk(v, path):
        if isinstance(v, dict):
            if isinstance(v.get("outcome"), str) and isinstance(v.get("reason"), str): out.append((path, v["outcome"], v["reason"]))
            for k, x in v.items(): walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v): walk(x, f"{path}[{i}]")
    for key in ("opening", "third_party", "identity", "negotiation", "recording", "situations", "outcomes"):
        if key in spec: walk(spec[key], key)
    return [p for p in out if not p[0].startswith("outcomes.table")]


def _semantic(spec, errors):
    table = {row["outcome"]: row["reasons"] for row in spec["outcomes"]["table"]}
    omitted = set(spec["outcomes"]["reason_omitted_for"])
    for path, outcome, reason in _outcome_pairs(spec):
        if outcome not in table: errors.append(f"{path}: outcome {outcome!r} is not in outcomes.table"); continue
        if reason and reason not in table[outcome]: errors.append(f"{path}: reason {reason!r} is not listed for {outcome!r}")
        if not reason and table[outcome] and outcome not in omitted: errors.append(f"{path}: outcome {outcome!r} needs a reason")
    roles = [v["role"] for v in spec["call_variables"]]
    for r in ("customer_id", "now"):
        if roles.count(r) != 1: errors.append(f"call_variables: exactly one variable needs role {r!r}")
    names = {v["name"] for v in spec["call_variables"]}
    for path in ("addressing", "opening.first_sentence", "opening.confirm_question"):
        node = spec
        for part in path.split("."): node = node[part]
        for ph in PLACEHOLDER.findall(node):
            if ph not in names: errors.append(f"{path}: placeholder {{{ph}}} is not a call variable")
    for d in spec["calendar"]["holidays"]:
        if not ISO_DATE.match(d): errors.append(f"calendar.holidays: {d!r} is not YYYY-MM-DD")
    if not spec["calendar"]["business_weekdays"] or any(not 0 <= d <= 6 for d in spec["calendar"]["business_weekdays"]):
        errors.append("calendar.business_weekdays: need values 0 (Monday) to 6 (Sunday)")
    cb = spec["third_party"]["callback"]
    for k in ("window_start", "window_end"):
        if not HHMM.match(cb[k]): errors.append(f"third_party.callback.{k}: {cb[k]!r} is not HH:MM")
    bands = sorted(spec["bands"], key=lambda b: b["days_late_min"])
    for a, b in zip(bands, bands[1:]):
        if b["days_late_min"] <= a["days_late_max"]: errors.append(f"bands: {a['name']} and {b['name']} overlap")
    for b in spec["bands"]:
        if b["days_late_min"] > b["days_late_max"]: errors.append(f"bands.{b['name']}: min > max")
        if [s["attempt"] for s in b["ladder"]] != list(range(1, b["attempts"] + 1)):
            errors.append(f"bands.{b['name']}: ladder must list attempts 1..{b['attempts']} in order")
    ids = [s["id"] for s in spec["situations"]]
    if len(ids) != len(set(ids)): errors.append("situations: ids must be unique")
    if len({q["field"] for q in spec["identity"]["questions"]}) != len(spec["identity"]["questions"]):
        errors.append("identity.questions: fields must be unique")
    types = [p["type"] for p in spec["account"]["product_types"]]
    if len(types) != len(set(types)): errors.append("account.product_types: types must be unique")
    for s in spec["situations"]:
        for a in _actions(s):
            if a["type"] == "transfer" and not a.get("queue"): errors.append(f"situations.{s['id']}: a transfer needs a queue")
            if a["type"] == "note" and not a.get("note_reason"): errors.append(f"situations.{s['id']}: a note needs a note_reason")
    if spec["notes"]["enabled"]:
        for path, r in _note_reasons(spec):
            if r not in spec["notes"]["reasons"]: errors.append(f"{path}: note reason {r!r} is not in notes.reasons")


def _actions(situation):
    for eff in [situation["effect"]] + ([situation["offer"]["on_accept"], situation["offer"]["on_decline"]] if situation.get("offer") else []):
        yield from eff["actions"]


def _note_reasons(spec):
    out = [("negotiation.attempts_exhausted", spec["negotiation"]["attempts_exhausted"].get("note_reason")),
           ("recording.on_final_failure", spec["recording"]["on_final_failure"].get("note_reason"))]
    for s in spec["situations"]:
        out += [(f"situations.{s['id']}", a.get("note_reason")) for a in _actions(s) if a["type"] == "note"]
    return [(p, r) for p, r in out if r]


def _against_tools(spec, tools, errors):
    """Every name and value the SPEC uses must exist in the tool API file. Tools are found by their fixed names,
    fields through `tool_fields`, so a renamed field is a SPEC change, not a code change."""
    tf = spec["tool_fields"]
    for name in TOOL_NAMES:
        if name not in tools: errors.append(f"tool API: tool {name!r} is missing")
    def request(tool): return (tools.get(tool) or {}).get("request") or {}
    def response(tool): return (tools.get(tool) or {}).get("response") or {}
    def enum(tool, role):
        field = tf[tool][role]
        return request(tool).get(field, {}).get("enum") or [] if field else []
    for tool in TOOL_NAMES:
        if tool in tools and tf["customer_id"] not in request(tool): errors.append(f"tool_fields.customer_id: {tf['customer_id']!r} is not a field of {tool}")
        for role, field in (tf.get(tool) or {}).items():
            if field and tool in tools and field not in request(tool): errors.append(f"tool_fields.{tool}.{role}: {field!r} is not a request field of {tool}")
    allowed = enum("verify_identity", "field")
    for q in spec["identity"]["questions"]:
        if allowed and q["field"] not in allowed: errors.append(f"identity.questions: {q['field']!r} is not in the tool API ({allowed})")
    resp = response("verify_identity")
    for role, name in spec["identity"]["result_fields"].items():
        if name and name not in resp: errors.append(f"identity.result_fields.{role}: {name!r} is not in the verify_identity response")
    hint_values = {e for f in resp.values() for e in f["enum"]}
    for h in spec["identity"]["hints"]:
        if h["value"] not in hint_values: errors.append(f"identity.hints: {h['value']!r} is not a value in the tool API")
    products = response("get_account").get(spec["account"]["products_field"], {})
    items = products.get("items")
    if not items: errors.append(f"account.products_field: get_account returns no list {spec['account']['products_field']!r}")
    else:
        for role, name in spec["account"]["product_fields"].items():
            if name not in items: errors.append(f"account.product_fields.{role}: {name!r} is not a product field")
        type_enum = items.get(spec["account"]["product_fields"]["type"], {}).get("enum") or []
        for p in spec["account"]["product_types"]:
            if type_enum and p["type"] not in type_enum: errors.append(f"account.product_types: {p['type']!r} not in {type_enum}")
            if p["floor_field"] not in items: errors.append(f"account.product_types.{p['type']}: floor field {p['floor_field']!r} is not a product field")
            for ph in PLACEHOLDER.findall(p["spoken_name"]):
                if ph not in items: errors.append(f"account.product_types.{p['type']}: placeholder {{{ph}}} is not a product field")
    allowed = enum("close_call", "outcome")
    for row in spec["outcomes"]["table"]:
        if allowed and row["outcome"] not in allowed: errors.append(f"outcomes.table: {row['outcome']!r} is not in the tool API ({allowed})")
    queues = enum("transfer_to_agent", "queue")
    for s in spec["situations"]:
        for a in _actions(s):
            if a["type"] == "transfer" and queues and a.get("queue") and a["queue"] not in queues: errors.append(f"situations.{s['id']}: queue {a['queue']!r} not in {queues}")
    if spec["notes"]["enabled"]:
        allowed = enum("add_note", "reason")
        for r in spec["notes"]["reasons"]:
            if allowed and r not in allowed: errors.append(f"notes.reasons: {r!r} is not in the tool API ({allowed})")


def validate(spec, tools=None):
    """Return a list of error strings. Empty means the SPEC is usable."""
    errors = []
    _check(spec, SCHEMA, "spec", errors)
    if errors:
        return errors                                  # semantic checks assume the structure is right
    if spec["spec_version"] != SPEC_VERSION: errors.append(f"spec_version: expected {SPEC_VERSION}")
    _semantic(spec, errors)
    if tools: _against_tools(spec, tools, errors)
    return errors


if __name__ == "__main__":       # python -m builder.spec_schema <spec.json> [tool_api.json]
    import json, sys
    from builder.ingest import parse_openapi
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    tools = parse_openapi(sys.argv[2])["tools"] if len(sys.argv) > 2 else None
    errs = validate(spec, tools)
    print("\n".join(errs) if errs else f"OK: {sys.argv[1]}")
    sys.exit(1 if errs else 0)
