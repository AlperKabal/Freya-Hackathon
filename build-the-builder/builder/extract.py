"""Stage 2: brief files + tool API -> SPEC, with three builder agents (dev/ARCHITECTURE.md, light set).

    spec, report = run(extract(docs, tools, trace))

Reader (brief -> SPEC) and Binder (tool API -> field mapping) run in parallel; code merges and validates; invalid
SPECs go back to the Reader with the errors (at most twice); then the Auditor, who never saw the drafts, checks the
SPEC against the brief rule by rule; its findings get one repair round, which is kept only if it still validates.
The prompts describe mechanisms and the SPEC format. They contain no content from any brief.
"""
import asyncio, copy, json, re

from builder import spec_schema as S
from builder.llm import ask_json

# ---------------------------------------------------------------- the SPEC format, written out for the model

HELP = {
    "spec_version": "Always " + str(S.SPEC_VERSION) + ".",
    "call_variables": "Every variable the call starts with, from the brief's table of call variables. role: customer_id (passed to every tool), now (the current date and time of the call), address (used to address or ask for the person), name, other.",
    "addressing": "How to address the customer, built from call variables in single braces.",
    "tool_fields": "Filled by the Binder from the tool API file: for each tool, which request field carries each role. Use \"\" when the API has no such field.",
    "agent.self_description": "How the agent describes itself, as the brief says (for example a digital assistant of the bank).",
    "agent.style_rules": "Only style rules the brief states. Leave empty if none.",
    "opening.first_sentence": "The exact first sentence the agent says, covering every element the brief requires in it, in plain words. Use single-brace call variables if needed.",
    "opening.confirm_question": "The exact question that asks whether the right person is on the line.",
    "opening.forbidden_before_identity": "Words or topics the agent must never say before identity is verified, including the names of products if the brief forbids naming the product.",
    "opening.confirmations": "What counts as confirming identity. non_confirmations: what does not.",
    "opening.max_asks": "How many times in total the agent may ask the confirmation question before closing as unclear.",
    "opening.unclear": "Outcome and reason when it stays unclear.",
    "third_party": "Someone else answered. instructions: what to say and not say. callback: when a callback may be booked (include_today, business_days_ahead, window_start/window_end HH:MM, inclusive, after_now), how many asks, and the outcome for booked / not booked.",
    "identity.questions": "The security questions in the order the brief gives. field: the value from the identity tool's field enum. ask: how to ask. value_type: date, digits, year, text or number. answer_format and conversion: how the answer must be sent, as the brief and the tool API say.",
    "identity.max_wrong_total": "Wrong answers in total that end the check.",
    "identity.hints": "Values the identity tool can return as a hint, each with what the agent must do and whether it counts as a wrong answer.",
    "identity.on_failed": "What to say and the outcome when the check fails.",
    "identity.decline": "Declining to answer: the explanation to give, how many refusals close the call, whether asking what the call is about counts as declining, and the outcome.",
    "identity.result_fields": "Filled by the Binder: response field names of the identity tool for ok, verified, all_verified, wrong_left, hint.",
    "account": "products_field and product_fields: filled by the Binder from the account tool's response. product_types: one per product type value in the API, with spoken_name (how to name it in speech; single-brace product fields allowed) and floor_field (the product field that holds the minimum acceptable amount). statement_intro and statement_per_product: how the debt is stated; statement_per_product may use {spoken_name}, {past_due}, {days_late} and product fields. max_products: the most products one customer can have.",
    "calendar": "business_weekdays: 0 = Monday ... 6 = Sunday. holidays: every bank holiday as YYYY-MM-DD.",
    "bands": "One row per band of the brief, by days late. deadline and ladder dates are date rules; ladder amounts are amount rules. attempts: persuasion attempts allowed; the ladder lists attempts 1..attempts in order.",
    "dates": "earliest (date rule), business_day_only, what to do with a non-business day and with a date after the deadline, whether refusing the deadline is a flat refusal, vague periods (examples, how often to ask for the exact day, then what), and what a weekday means when the customer says it with the word next or this.",
    "amounts": "first_offer, accept_min, accept_max (amount rules), too_much (what to offer, how often, the sentence to add, whether refusing it is a flat refusal), below_min (what to say and offer).",
    "negotiation": "first_ask: the exact first question about paying. flat_refusal_definition as the brief defines it. attempts_exhausted: outcome, reason (and note_reason if products are noted). forbidden_offers and forbidden_questions. call_attempt_limit: only when the brief counts persuasion attempts for the whole call, not per product, and gives that number; otherwise leave it out.",
    "confirmation": "read_back items, the exact confirmation question, and what to say when a recorded promise should be changed.",
    "recording": "max_attempts of the promise tool (first try plus retries), success_field in its response, the exact sentence after a recorded promise (after_success_say, \"\" if none), retry_say (said before a retry; must not claim anything was saved), failure_say, and on_final_failure.",
    "situations": "Every special situation the brief describes (things the customer says or that happen). id: short snake_case. trigger: when it applies, stated as narrowly as the documents state it. not_this: what looks similar but is something else (copy the brief's own distinctions); when the situation transfers the call or ends it, also name the everyday replies that are NOT it: a plain refusal, saying they cannot pay, and an open question about what else is possible or what the customer's options are, unless the documents say such a reply is this situation. evidence_words (optional): only for a situation that is the customer's explicit request for something the documents name and that transfers or ends the call the first time it is said; lower-case word stems from the documents' own wording of that request, plus close synonyms and spelling variants, so that every natural way of making this exact request contains at least one of them. Never list a word that also fits a plain refusal, a general question or the agent's own offers. Leave it out when a situation can be said in countless ways (an event in the customer's life, a claim about the account, not wanting to talk). stages: where it can happen (opening, third_party, identity, negotiation, confirmation). say: the sentence the agent speaks when the situation's effect happens (for a call-scope situation: right before the call ends, after any transfer), written as the words themselves, or "" (say_exact: true when the brief prescribes these exact words). What the agent says BEFORE acting (for example a question asked the first time) belongs in first_response, never in say. guidance: how the agent must behave here, as an instruction (never spoken). first_response and threshold: when the brief says to do something first and act only on the n-th time. suppresses_persuasion, priority (higher wins when two apply), proposal_still_handled. scope: call (ends the call) or product (only that product, the call continues). effect: actions (transfer with queue, note with note_reason, callback), outcome, reason, optional outcome_by_stage (before_identity / after_identity) when the brief gives different outcomes. offer: when the agent must offer something the customer may accept or decline, with on_accept and on_decline effects. source: the brief's rule id or a short quote.",
    "faq": "Questions the agent answers and then continues (trigger, answer, source).",
    "multi_product": "Rules for customers with several products. enabled false if the brief has one product per customer. state_all_first: all products are stated at the start (false: each when it is reached). ask_all_today_once: one question about paying everything today (false: asked per product). attempts_per_product: persuasion attempts are counted per product (false: for the whole call, see negotiation.call_attempt_limit). one_date_clamped_per_product: one date for everything puts a product past its deadline on its own deadline. single_read_back: one read-back of all promises (false: each promise is read back when it is agreed). unrecorded_on_transfer: what happens on a transfer to promises agreed but not yet recorded.",
    "notes": "Whether products without a promise get a note, the allowed reasons, and whether notes are written on a transfer. for_each_product_without_promise: true when every product without a promise gets a note, also when its attempts were used up; false when only the situations that name a note write one.",
    "outcomes": "table: every outcome with its allowed reasons (empty list when the brief lists none). reason_omitted_for: outcomes sent without a reason. promise: the outcome when at least one promise was recorded. transfer_after_promise. multi (only with several products): when all notes match a reason, and otherwise which reason to use.",
    "closing.farewell": "The goodbye the agent says at the end.",
    "free_rules": "EVERY rule of the brief that does not fit a field above, word for word or close to it, with applies_to (stages or all) and source. Also record here every place where a later document overrides an earlier one, quoting both.",
    "rule_map": "One row per rule of the brief (numbered rules, table rows, memo items): which SPEC fields carry it. Nothing may be left out.",
}


def _skeleton(t, path=""):
    if isinstance(t, S.Opt):
        return _skeleton(t.t, path)
    if t is str: return "<string>"
    if t is int: return "<integer>"
    if t is bool: return "<true|false>"
    if isinstance(t, S.Enum): return "<one of: " + " | ".join(map(str, t.values)) + ">"
    if isinstance(t, S.Rule): return "<rule: {\"kind\": " + " | ".join(f"{k}{'(' + ', '.join(v) + ')' if v else ''}" for k, v in t.kinds.items()) + "}>"
    if isinstance(t, list): return [_skeleton(t[0], path + "[]")]
    if isinstance(t, dict):
        return {(k.t + " (optional)" if isinstance(k, S.Opt) else k): _skeleton(v, f"{path}.{k.t if isinstance(k, S.Opt) else k}".strip(".")) for k, v in t.items()}
    return "<value>"


def format_guide():
    return ("THE SPEC FORMAT (JSON). Keys marked (optional) may be left out; every other key is required. Never use null.\n"
            + json.dumps(_skeleton(S.SCHEMA), indent=1)
            + "\n\nDate rule kinds: " + "; ".join(f"{k} {v}" for k, v in S.DATE_RULE_KINDS.items())
            + ". roll: next_business_day | previous_business_day | none."
            + "\nAmount rule kinds: full; floor (the product type's floor field); full_or_floor_if_too_much; percent_of_full(percent)."
            + "\n\nFIELD GUIDE\n" + "\n".join(f"- {k}: {v}" for k, v in HELP.items()))


def tools_summary(tools):
    def fields(fs):
        return {k: {x: v[x] for x in ("type", "enum", "description") if v.get(x)} | ({"items": fields(v["items"])} if v.get("items") else {}) for k, v in fs.items()}
    return json.dumps({n: {"summary": t["summary"], "request": fields(t["request"]), "required": t["required"], "response": fields(t["response"])} for n, t in tools.items()}, indent=1)


def briefs_text(docs):
    return "\n\n".join(f"===== FILE {i + 1}: {d['name']} =====\n{d['text']}" for i, d in enumerate(docs))


COMMON = ("You are part of a program that builds a phone agent for a bank's collection calls from the bank's own documents. "
          "Everything you write must come from the documents and the tool API file given to you. Never invent a rule, a value, a name or a sentence. "
          "Reply with one JSON object only.")

READER = COMMON + """
You are the READER. Turn the bank's documents into one SPEC.
- The documents may be a clean specification or raw material (emails, a policy extract, memos that change it, code lists). Build one consistent rule set. When a later or more specific document changes a rule, the change wins; record each such override in free_rules, quoting both texts.
- Copy every sentence the documents prescribe word for word. When they only describe what to say, write a short plain sentence that says exactly that and nothing more.
- Honesty: in a sentence spoken before anything has been saved, avoid words that a listener could take as a claim that something was recorded, saved or booked (for example, word a recording notice with a present-tense verb rather than a past participle) unless the documents prescribe that exact sentence word for word.
- Every outcome and reason you use must appear in outcomes.table, and every value must exist in the tool API where the API lists allowed values.
- A transfer or the end of the call cannot be undone. For each situation with such an effect, state the trigger as the explicit thing the customer must say or ask for, and fill not_this and evidence_words as the field guide describes.
- Use single braces for call variables in sentences, for example {variable_name}.
- If the documents do not say something a field needs, choose the most cautious value and add a free_rules entry that says what was missing.
- Put every rule that fits no field into free_rules, and list every rule in rule_map."""

BINDER = COMMON + """
You are the BINDER. You map the tool API file onto the SPEC's roles. Reply with this JSON object:
{"call_variables": CALL_VARIABLES_SHAPE,
 "tool_fields": TOOL_FIELDS_SHAPE,
 "identity_result_fields": {"ok": "", "verified": "", "all_verified": "", "wrong_left": "", "hint": ""},
 "identity_fields": ["field enum values of the identity tool, in the order the documents ask them"],
 "hint_values": ["values the identity tool can return as a hint"],
 "products_field": "", "product_fields": {"id": "", "type": "", "past_due": "", "days_late": ""},
 "product_types": [{"type": "", "floor_field": "", "name_fields": ["product fields useful to name it in speech"]}]}
Take every name from the tool API file exactly. The seven tool names are fixed; their fields and values may differ from what you expect.
tool_fields maps each ROLE (the keys shown) to the request field NAME of that tool; it is an object, never a list. call_variables is a list of objects."""
BINDER = BINDER.replace("CALL_VARIABLES_SHAPE", json.dumps(_skeleton(S.SCHEMA["call_variables"]))).replace("TOOL_FIELDS_SHAPE", json.dumps(_skeleton(S.SCHEMA["tool_fields"])))

AUDITOR = COMMON + """
You are the AUDITOR. You did not write the SPEC. Check it against the documents, rule by rule: every rule must be carried by a SPEC field or a free_rules entry, with the right values; overrides from later documents must win.
Reply: {"issues": [{"rule": "short quote from the documents", "problem": "what is wrong or missing in the SPEC", "fix": "what the SPEC must say"}]}
Check at least: every numbered rule and table row; every outcome and reason against the closing table; every date, number and holiday; each situation's say (spoken when its effect happens, never a question asked first), first_response, threshold, stages and outcome; for each situation that transfers or ends the call, that not_this rules out the everyday replies the field guide names and that evidence_words, where the field guide asks for them, hold only words specific to that request; the identity questions and their order; the opening sentence against what the documents require.
Report only real problems: a missing rule, a wrong value, a wrong outcome or reason, a lost override, a sentence that is not what the documents prescribe, a field used for the wrong purpose. An empty list is a valid answer only after these checks."""


def _shape_ok(value, schema_part):
    errs = []
    S._check(value, schema_part, "x", errs)
    return not errs


# Sentences spoken before anything is saved, and words a literal judge can read as "it was saved".
PRE_SUCCESS = [("opening", "first_sentence"), ("opening", "confirm_question"), ("recording", "retry_say"), ("negotiation", "first_ask"), ("confirmation", "question")]
CLAIM_WORDS = re.compile(r"\b(recorded|saved|booked|registered|logged)\b", re.I)

REWORDER = COMMON + """
You reword ONE sentence that a phone agent says before anything has been saved. Keep every element and its meaning;
only replace words that a listener could take as a claim that something was recorded, saved or booked (use a present-tense verb instead of a past participle, for example).
Reply: {"sentence": "..."}"""


async def reword_pre_success(spec, trace=None):
    """Code finds the risky sentences; the model only rewrites those, one small call each, in parallel."""
    todo = [(a, b) for a, b in PRE_SUCCESS if isinstance(spec.get(a, {}).get(b), str) and CLAIM_WORDS.search(spec[a][b])]
    async def one(a, b):
        r = await ask_json(REWORDER, f"Sentence: {spec[a][b]}", f"Reworder: {a}.{b} before any save", trace)
        new = r.get("sentence") if isinstance(r, dict) else None
        if isinstance(new, str) and new.strip() and not CLAIM_WORDS.search(new):
            if trace: trace.event("spec", f"reworded {a}.{b}: {spec[a][b]!r} -> {new!r}")
            spec[a][b] = new.strip()
    await asyncio.gather(*(one(a, b) for a, b in todo))
    return spec


def merge_binding(spec, b):
    """The Binder is authoritative for names that come from the tool API, but only for parts that have the right
    shape: a malformed Binder answer must never overwrite a good Reader answer."""
    s = copy.deepcopy(spec)
    if not isinstance(b, dict) or not isinstance(s, dict):
        return s
    parts = [("tool_fields", None, S.SCHEMA["tool_fields"]), ("call_variables", None, S.SCHEMA["call_variables"]),
             ("identity_result_fields", ("identity", "result_fields"), S.SCHEMA["identity"]["result_fields"]),
             ("products_field", ("account", "products_field"), str), ("product_fields", ("account", "product_fields"), S.SCHEMA["account"]["product_fields"])]
    for key, path, shape in parts:
        v = b.get(key)
        if v and _shape_ok(v, shape):
            try:
                if path is None: s[key] = v
                else: s[path[0]][path[1]] = v
            except (KeyError, TypeError):
                pass
    try:
        floors = {p.get("type"): p.get("floor_field") for p in b.get("product_types") or [] if isinstance(p, dict)}
        for p in s["account"]["product_types"]:
            if isinstance(floors.get(p["type"]), str) and floors[p["type"]]: p["floor_field"] = floors[p["type"]]
    except (KeyError, TypeError, AttributeError):
        pass
    return s


async def extract(docs, tools, trace=None, max_repairs=2):
    guide, api, text = format_guide(), tools_summary(tools), briefs_text(docs)
    reader_prompt = f"{guide}\n\nTOOL API FILE (parsed):\n{api}\n\nTHE BANK'S DOCUMENTS:\n{text}\n\nWrite the SPEC now."
    binder_prompt = f"TOOL API FILE (parsed):\n{api}\n\nTHE BANK'S DOCUMENTS:\n{text}\n\nWrite the mapping now."
    spec, binding = await asyncio.gather(ask_json(READER, reader_prompt, "Reader: documents -> SPEC", trace),
                                         ask_json(BINDER, binder_prompt, "Binder: tool API -> field mapping", trace))
    spec = merge_binding(spec, binding)
    report = {"repairs": 0, "audit_issues": [], "audit_applied": False}

    async def repair(current, problems, why):
        p = (f"{guide}\n\nTOOL API FILE (parsed):\n{api}\n\nTHE BANK'S DOCUMENTS:\n{text}\n\nCURRENT SPEC:\n{json.dumps(current, indent=1)}\n\n"
             f"PROBLEMS ({why}):\n" + "\n".join(f"- {x}" for x in problems) + "\n\nReturn the complete corrected SPEC.")
        return merge_binding(await ask_json(READER, p, f"Reader: repair SPEC ({why})", trace), binding)

    errs = S.validate(spec, tools)
    while errs and report["repairs"] < max_repairs:
        report["repairs"] += 1
        if trace: trace.event("spec", f"{len(errs)} validation problem(s), repair round {report['repairs']}")
        spec = await repair(spec, errs[:60], "validation errors")
        errs = S.validate(spec, tools)
    if errs:
        return spec, dict(report, errors=errs)
    spec = await reword_pre_success(spec, trace)

    audit = await ask_json(AUDITOR, f"{guide}\n\nTOOL API FILE (parsed):\n{api}\n\nTHE BANK'S DOCUMENTS:\n{text}\n\nTHE SPEC TO CHECK:\n{json.dumps(spec, indent=1)}",
                           "Auditor: SPEC vs documents, rule by rule", trace)
    issues = [i for i in (audit.get("issues") or []) if isinstance(i, dict)]
    report["audit_issues"] = issues
    if issues:
        fixed = await repair(spec, [f"{i.get('rule', '')}: {i.get('problem', '')} -> {i.get('fix', '')}" for i in issues], "auditor findings")
        if not S.validate(fixed, tools):
            spec, report["audit_applied"] = fixed, True
        elif trace:
            trace.event("spec", "auditor repair did not validate; kept the validated SPEC")
    return spec, dict(report, errors=[])


if __name__ == "__main__":       # python -m builder.extract <briefs...> <tool_api.json> <out_spec.json>
    import pathlib, sys
    from builder.ingest import parse_openapi, read_briefs
    from builder.llm import run
    from builder.trace import Trace
    *briefs, api_path, out = sys.argv[1:]
    t = Trace(pathlib.Path("traces"), "dev-extract")
    spec, rep = run(extract(read_briefs(briefs), parse_openapi(api_path)["tools"], t))
    pathlib.Path(out).write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "audit_issues"}, indent=1), f"\naudit issues: {len(rep['audit_issues'])}")
    for i in rep["audit_issues"]: print(" -", str(i)[:200])
    t.close("ok" if not rep["errors"] else "invalid")
