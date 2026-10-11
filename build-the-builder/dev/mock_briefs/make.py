"""Write the generated files of the mock briefs: each pack's tool API file, its oracle SPEC and pack.json, and the
documents of pack F (the kit's own Brief A and B with twelve rules changed at once).

    python dev/mock_briefs/make.py            # rewrite them
    python dev/mock_briefs/make.py --check    # exit 1 when a committed file differs from what this script writes

The brief documents of packs D and E are written by hand (they are the test); what is here is their reading: the
SPEC a careful reader takes from them. Change a rule in a document and its value here together.
"""
import copy, json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
KIT = HERE.parent.parent
OUT = {}                                               # relative path -> text


def put(path, value):
    OUT[path] = value if isinstance(value, str) else json.dumps(value, indent=1, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- tool API files

def api(title, server, customer, tools, ok="ok", style="plain", prefix="", extra_paths=None):
    """An OpenAPI description of the seven tools. `tools`: name -> (summary, request fields, required, response
    fields). style "plain": like the kit's file. style "refs": OpenAPI 3.1 with $ref components, allOf for the
    customer field, nullable types and camelCase operation ids on hyphenated paths."""
    refs = style == "refs"
    doc = {"openapi": "3.1.0" if refs else "3.0.3", "info": {"title": title, "version": "mock"},
           "servers": [{"url": server, "variables": {"env": {"default": "sandbox"}}}] if "{env}" in server else [{"url": server}],
           "components": {"schemas": {}} if refs else {}, "paths": {}}
    if refs:
        doc["components"]["schemas"]["Caller"] = {"type": "object", "properties": {customer: {"type": "string", "description": "Identifies the call. Goes into every request."}}, "required": [customer]}
        doc["components"]["schemas"]["Result"] = {"type": "object", "properties": {ok: {"type": "boolean"}, "error": {"type": ["string", "null"]}}}
    for name, (summary, req, required, resp) in tools.items():
        camel = name.split("_")[0] + "".join(w.capitalize() for w in name.split("_")[1:])
        route = prefix + "/" + (name.replace("_", "-") if refs else name)
        if refs:
            doc["components"]["schemas"][camel + "Request"] = {"allOf": [{"$ref": "#/components/schemas/Caller"}, {"type": "object", "properties": req, "required": required}]}
            doc["components"]["schemas"][camel + "Response"] = {"allOf": [{"$ref": "#/components/schemas/Result"}, {"type": "object", "properties": resp}]}
            body, answer = {"$ref": f"#/components/schemas/{camel}Request"}, {"$ref": f"#/components/schemas/{camel}Response"}
        else:
            body = {"type": "object", "properties": dict({customer: {"type": "string"}}, **req), "required": [customer] + required}
            answer = {"type": "object", "properties": dict({ok: {"type": "boolean"}, "error": {"type": "string"}}, **resp)}
        doc["paths"][route] = {"post": dict({"summary": summary, "requestBody": {"required": True, "content": {"application/json": {"schema": body}}},
                                             "responses": {"200": {"description": f"`{ok}` is false when the action was not carried out.", "content": {"application/json": {"schema": answer}}},
                                                           "500": {"description": "The service failed. Nothing was recorded. The call may be repeated."}}},
                                            **({"operationId": camel} if refs else {}))}
    doc["paths"].update(extra_paths or {})
    return doc


S = lambda **kw: dict({"type": "string"}, **kw)
N = lambda **kw: dict({"type": "number"}, **kw)
B = {"type": "boolean"}
I = {"type": "integer"}


# ---------------------------------------------------------------- SPEC building blocks

def sit(id_, trigger, stages, outcome, reason="", actions=(), not_this="", say="", say_exact=False, guidance="", first_response="", threshold=1,
        priority=50, scope="call", proposal=False, offer=None, by_stage=None, words=None, source=""):
    effect = {"actions": list(actions), "outcome": outcome, "reason": reason}
    if by_stage:
        effect["outcome_by_stage"] = by_stage
    s = {"id": id_, "trigger": trigger, "not_this": not_this, "stages": list(stages), "say": say, "say_exact": say_exact, "first_response": first_response,
         "threshold": threshold, "suppresses_persuasion": True, "priority": priority, "proposal_still_handled": proposal, "scope": scope, "effect": effect,
         "source": source, "guidance": guidance}
    if words:
        s["evidence_words"] = list(words)
    if offer:
        s["offer"] = offer
    return s


def transfer(queue):
    return {"type": "transfer", "queue": queue}


def note(reason):
    return {"type": "note", "note_reason": reason}


def pair(outcome, reason=""):
    return {"outcome": outcome, "reason": reason}


def step(n, date, amount):
    return {"attempt": n, "date": date, "amount": amount}


BIZ = lambda n: {"kind": "nth_business_day_after_today", "n": n}
WEEK_END = {"kind": "last_business_day_of_week", "week_offset": 0, "if_today_week_offset": 1}
DEADLINE = {"kind": "deadline"}
FULL, FLOOR, FULL_OR_FLOOR = {"kind": "full"}, {"kind": "floor"}, {"kind": "full_or_floor_if_too_much"}


# ---------------------------------------------------------------- pack D: Harbor Retail Bank, raw bank material

def pack_d():
    tools = {
        "verify_identity": ("Check one security answer. Two wrong answers in total end the check.",
                            {"question": S(enum=["postcode", "birth_year"]),
                             "value": S(description="For postcode: capital letters, no space (LS62AB). For birth_year: four digits.")},
                            ["question", "value"],
                            {"matched": B, "tries_left": I, "passed": B, "advice": S(enum=["partial_postcode"])}),
        "get_account": ("The overdue accounts. Refused until both questions are passed.", {}, [],
                        {"accounts": {"type": "array", "items": {"type": "object", "properties": {
                            "account_id": S(), "kind": S(enum=["credit_card", "personal_loan", "arranged_overdraft"]), "last_digits": S(),
                            "arrears": N(), "days_overdue": I, "min_payment": N(), "monthly_instalment": N()}}}}),
        "create_promise": ("Record a payment promise. One per account.",
                           {"account_id": S(), "promise_amount": N(), "pay_on": S(format="date")}, ["account_id", "promise_amount", "pay_on"], {"reference": S()}),
        "add_note": ("Record why an account ended without a promise.",
                     {"account_id": S(), "code": S(enum=["declined", "hardship", "disputed", "already_paid", "system_fault"]), "comment": S()}, ["account_id", "code"], {}),
        "schedule_callback": ("Book a callback.", {"on_date": S(format="date"), "at_time": S(description="HH:MM, 24-hour clock")}, ["on_date", "at_time"], {}),
        "transfer_to_agent": ("Hand the call to a team.", {"team": S(enum=["care", "complaints", "agents"])}, ["team"], {}),
        "close_call": ("End the call. Always the last tool call. Nothing is accepted after it.",
                       {"result": S(enum=["arrangement", "settled", "handed_over", "no_arrangement", "unverified", "unreached", "legal_review"]),
                        "detail": S(description="Required for handed_over, no_arrangement, unverified and unreached. Leave it out for arrangement and settled.")},
                       ["result"], {}),
    }
    doc = api("Harbor Retail Bank - arrears assistant tools (mock, not an organiser file)", "https://{env}.harbor-retail.invalid/collections/v3", "customer_ref", tools,
              style="refs", prefix="/tools")
    hardship_decline = {"actions": [note("hardship")], "outcome": "no_arrangement", "reason": "hardship"}
    spec = {
        "spec_version": 1,
        "meta": {"bank_name": "Harbor Retail Bank", "language": "English",
                 "sources": ["1-email.md", "2-policy-extract.md", "3-memo.md", "4-code-list.csv", "tool-api.json"]},
        "call_variables": [
            {"name": "customer_ref", "role": "customer_id", "meaning": "Goes into every tool call."},
            {"name": "salutation", "role": "address", "meaning": "Mr, Ms or Mx."},
            {"name": "given_name", "role": "name", "meaning": "The customer's given name. Never used to address them."},
            {"name": "family_name", "role": "address", "meaning": "Address the customer as salutation plus family name."},
            {"name": "call_time", "role": "now", "meaning": "Date and time of the call. All date rules work from it."}],
        "addressing": "{salutation} {family_name}",
        "tool_fields": {"customer_id": "customer_ref", "verify_identity": {"field": "question", "answer": "value"},
                        "create_promise": {"product_id": "account_id", "amount": "promise_amount", "date": "pay_on"},
                        "add_note": {"product_id": "account_id", "reason": "code", "text": "comment"},
                        "schedule_callback": {"date": "on_date", "time": "at_time"},
                        "transfer_to_agent": {"queue": "team"}, "close_call": {"outcome": "result", "reason": "detail"}},
        "agent": {"self_description": "Harbor Retail Bank's automated assistant", "style_rules": []},
        "opening": {
            "first_sentence": "Hello, this is the automated assistant of Harbor Retail Bank. Please note that we record this call.",
            "confirm_question": "Am I speaking with {salutation} {family_name}?",
            "forbidden_before_identity": ["arrears", "overdue", "debt", "payment", "collections", "credit card", "personal loan", "arranged overdraft"],
            "confirmations": ["yes", "speaking", "that is me", "the customer's own name"],
            "non_confirmations": ["hello", "who is calling", "what is this about"],
            "max_asks": 3, "answer_question_first": True, "unclear": pair("unreached", "not_confirmed")},
        "third_party": {
            "enabled": True,
            "instructions": ["Say nothing about the reason for the call.", "Ask when the customer can be reached.",
                             "The person may not answer the security questions for the customer and is told nothing about the accounts, even when they offer to pay."],
            "callback": {"enabled": True, "include_today": False, "business_days_ahead": 2, "window_start": "09:30", "window_end": "16:30", "inclusive": True,
                         "after_now": True, "max_asks": 3, "scheduled": pair("unreached", "callback_booked"), "not_scheduled": pair("unreached", "no_callback")}},
        "identity": {
            "questions": [
                {"field": "postcode", "ask": "Could you tell me the postcode of your registered address?", "value_type": "text",
                 "answer_format": "capital letters without a space", "conversion": "Send the postcode in capital letters without a space: 'LS6 2AB' is sent as LS62AB."},
                {"field": "birth_year", "ask": "And in which year were you born?", "value_type": "year", "answer_format": "four digits (YYYY)",
                 "conversion": "Send the year as four digits."}],
            "one_at_a_time": True, "max_wrong_total": 2, "wrong_may_retry": True,
            "hints": [{"value": "partial_postcode", "instruction": "The customer gave only a part of the postcode. Ask for the full postcode.", "counts_as_wrong": False}],
            "on_failed": {"say": "For your security I cannot continue this call. Please ring the number on the back of your card.", "outcome": "unverified", "reason": "failed_security"},
            "decline": {"explanation": "", "max_declines": 1, "purpose_question_counts": False, "outcome": "unverified", "reason": "refused_security"},
            "result_fields": {"ok": "ok", "verified": "matched", "all_verified": "passed", "wrong_left": "tries_left", "hint": "advice"}},
        "account": {
            "products_field": "accounts",
            "product_fields": {"id": "account_id", "type": "kind", "past_due": "arrears", "days_late": "days_overdue"},
            "product_types": [{"type": "credit_card", "spoken_name": "credit card ending {last_digits}", "floor_field": "min_payment"},
                              {"type": "personal_loan", "spoken_name": "personal loan", "floor_field": "monthly_instalment"},
                              {"type": "arranged_overdraft", "spoken_name": "arranged overdraft", "floor_field": "arrears"}],
            "max_products": 3,
            "statement_intro": "I am calling from the account services team of Harbor Retail Bank about an overdue balance.",
            "statement_per_product": "Your {spoken_name} is {days_late} days overdue, with {past_due} outstanding."},
        "calendar": {"business_weekdays": [0, 1, 2, 3, 4],
                     "holidays": ["2026-11-02", "2026-11-13", "2026-12-24", "2026-12-25", "2026-12-28", "2026-12-31", "2027-01-01"]},
        "bands": [
            {"name": "A", "days_late_min": 1, "days_late_max": 10, "deadline": BIZ(10), "attempts": 1, "ladder": [step(1, BIZ(1), FULL_OR_FLOOR)]},
            {"name": "B", "days_late_min": 11, "days_late_max": 40, "deadline": BIZ(5), "attempts": 3,
             "ladder": [step(1, BIZ(1), FULL_OR_FLOOR), step(2, BIZ(3), FLOOR), step(3, DEADLINE, FLOOR)]},
            {"name": "C", "days_late_min": 41, "days_late_max": 120, "deadline": {"kind": "nth_calendar_day_after_today", "n": 4, "roll": "previous_business_day"},
             "attempts": 2, "ladder": [step(1, BIZ(1), FULL_OR_FLOOR), step(2, DEADLINE, FLOOR)]}],
        "dates": {"earliest": {"kind": "today"}, "business_day_only": True, "non_business_day": "reject", "after_deadline": "offer_deadline",
                  "refused_deadline_is_flat_refusal": True,
                  "vague": {"examples": ["next week", "after payday", "sometime in November"], "ask_exact_times": 2, "then": "propose_deadline"},
                  "relative_weekday": {"next": "upcoming", "this": "upcoming"}},
        "amounts": {"first_offer": FULL, "never_ask_open_amount": True, "accept_min": FLOOR, "accept_max": FULL,
                    "too_much": {"offer": FLOOR, "times": 1, "say": "The remaining balance stays overdue.", "refused_is_flat_refusal": True},
                    "below_min": {"say": "I am afraid I cannot accept less than the minimum.", "offer": FLOOR, "times": 1, "refused_is_flat_refusal": True}},
        "negotiation": {"first_ask": "Are you able to clear this amount today?", "proposal_never_refusal": True,
                        "flat_refusal_definition": "A plain no, or no real answer.",
                        "attempts_exhausted": {"outcome": "no_arrangement", "reason": "declined", "note_reason": "declined"},
                        "forbidden_offers": ["a discount", "a waiver", "a payment holiday", "anything that is not in the handbook"],
                        "forbidden_questions": ["How much can you pay?"]},
        "confirmation": {"read_back": ["product", "amount", "date"], "question": "Shall I record that?", "require_clear_yes": True,
                         "on_change": "revalidate_and_read_back", "one_promise_per_product": True,
                         "after_record_change_say": "A recorded promise cannot be changed on this call. You can change it in online banking."},
        "recording": {"max_attempts": 3, "success_field": "ok", "after_success_say": "A confirmation letter will be sent to your registered address.",
                      "retry_say": "One moment please, I will try that again.", "failure_say": "I am sorry, I was unable to save the arrangement.",
                      "on_final_failure": {"outcome": "no_arrangement", "reason": "system_fault", "note_reason": "system_fault"}},
        "situations": [
            sit("wrong_number", "The person says the number is not the customer's.", ["opening", "third_party"], "unreached", "wrong_number", priority=90,
                not_this="Someone who knows the customer but is not the customer is a third party.", source="3.2"),
            sit("deceased", "The person says the customer has died.", ["opening", "third_party"], "unreached", "deceased", priority=95,
                say="Please accept our condolences.", say_exact=True, guidance="Ask nothing more.", source="3.2"),
            sit("hardship", "The customer speaks of illness, a bereavement or the loss of a job.", ["negotiation", "confirmation"], "no_arrangement", "hardship",
                actions=[note("hardship")], priority=80, proposal=True, not_this="Saying the amount is too much, with no such event, is not hardship.",
                guidance="Say one short sentence of sympathy. Make no persuasion attempt.", source="3.7",
                offer={"question": "Offer to put the customer through to the welfare team.",
                       "on_accept": {"actions": [transfer("care")], "outcome": "handed_over", "reason": "welfare"}, "on_decline": hardship_decline}),
            sit("complaint", "The customer wants to complain about the bank or about this call.", ["negotiation", "confirmation"], "handed_over", "complaints",
                actions=[transfer("complaints")], priority=70, words=["complain", "complaint"], guidance="Do not discuss the complaint.",
                not_this="Being unhappy about the amount or refusing to pay is not a complaint.", source="3.9 c"),
            sit("person", "The customer asks for a person.", ["identity", "negotiation", "confirmation"], "handed_over", "agent_request", actions=[transfer("agents")],
                priority=60, words=["person", "human", "someone", "somebody", "agent", "adviser", "advisor", "representative", "colleague"],
                not_this="Asking whether the assistant is a machine is a question, not a request for a person.", guidance="Transfer at once.", source="3.9 e"),
            sit("not_wanted", "The customer says they do not want this call, or tells the assistant to stop calling.", ["identity", "negotiation", "confirmation"],
                "no_arrangement", "declined", actions=[note("declined")], priority=40, words=["stop calling", "do not call", "don't call", "want this call", "leave me alone"],
                not_this="Refusing to pay is a refusal, not this.", guidance="Do not insist.", source="3.9 f",
                by_stage={"before_identity": pair("unverified", "refused_security"), "after_identity": pair("no_arrangement", "declined")}),
            sit("already_paid", "The customer says the amount that is overdue now is already paid.", ["negotiation", "confirmation"], "settled", "",
                actions=[note("already_paid")], scope="product", say="Payments can take up to two working days to show.", say_exact=True,
                not_this="A claim that the account was paid off in the past is a dispute.", source="3.9 a"),
            sit("dispute", "The customer says the account is not theirs, that they never had it, or that it was closed or paid off long ago.",
                ["negotiation", "confirmation"], "no_arrangement", "disputed", actions=[note("disputed")], scope="product",
                not_this="A payment of the amount that is overdue now is already_paid.", guidance="Do not argue and take no promise.", source="3.9 b")],
        "faq": [
            {"trigger": "The customer asks whether they are talking to a machine.", "answer": "Say that you are Harbor Retail Bank's automated assistant, then carry on.", "source": "email 5"},
            {"trigger": "The customer asks whether this call is a scam.", "answer": "Say: 'You can check this call by ringing the number on the back of your card.' Then carry on.", "source": "email 6"},
            {"trigger": "The customer asks something the tools cannot answer.", "answer": "Say that you do not have that information. Never guess figures, dates or reasons.", "source": "email 7"},
            {"trigger": "The customer asks for a payment plan or for smaller instalments.",
             "answer": "Say: 'Payment plans can be arranged in any branch.' Then carry on with the call. The request by itself is not a refusal and nothing is transferred.", "source": "memo 5"},
            {"trigger": "The customer asks why the security questions are needed.", "answer": "Say that the questions protect the account, then ask the question again. This is not a refusal.", "source": "3.3"}],
        "multi_product": {"enabled": True, "state_all_first": True, "ask_all_today_once": True, "first_ask_all": "Are you able to clear all of these today?",
                          "order": "as_returned", "attempts_per_product": True, "one_date_clamped_per_product": True, "single_read_back": True,
                          "unrecorded_on_transfer": "drop"},
        "notes": {"enabled": True, "for_each_product_without_promise": True, "reasons": ["declined", "hardship", "disputed", "already_paid", "system_fault"],
                  "on_transfer": "none"},
        "outcomes": {
            "table": [{"outcome": "arrangement", "reasons": [], "when": "at least one promise was recorded"},
                      {"outcome": "settled", "reasons": [], "when": "the customer says the overdue amount is already paid"},
                      {"outcome": "handed_over", "reasons": ["welfare", "complaints", "agent_request"], "when": "hardship accepted, complaint, asks for a person"},
                      {"outcome": "no_arrangement", "reasons": ["declined", "hardship", "disputed", "system_fault"], "when": "attempts used up or call not wanted, hardship declined, dispute, promise not saved"},
                      {"outcome": "unverified", "reasons": ["failed_security", "refused_security"], "when": "two wrong answers, refuses security"},
                      {"outcome": "unreached", "reasons": ["callback_booked", "no_callback", "wrong_number", "deceased", "not_confirmed"], "when": "the customer was not on the line"}],
            "reason_omitted_for": ["arrangement", "settled"], "promise": pair("arrangement"), "transfer_after_promise": "promise_wins",
            "multi": {"all_notes_match": {"note_reason": "already_paid", "outcome": "settled", "reason": ""},
                      "otherwise": {"outcome": "no_arrangement", "reason_from": "first_note_not_matching"}}},
        "closing": {"farewell": "Thank you, {salutation} {family_name}. Goodbye."},
        "free_rules": [
            {"id": "3.7b", "text": "An attempt never names a date after the latest promise date: if its date would be later, it names the latest promise date instead.", "applies_to": ["negotiation"], "source": "3.7"},
            {"id": "3.7c", "text": "Do not repeat an offer the customer has refused.", "applies_to": ["negotiation"], "source": "3.7"},
            {"id": "3.6b", "text": "An arranged overdraft has no minimum of its own: only its full overdue amount can be promised.", "applies_to": ["negotiation"], "source": "3.6"},
            {"id": "3.6c", "text": "If the customer names more than the full overdue amount, the full overdue amount is recorded.", "applies_to": ["negotiation", "confirmation"], "source": "3.6"},
            {"id": "3.10.6", "text": "On a hand-over, promises that were agreed but not yet recorded are not recorded, and no notes are added.", "applies_to": ["negotiation", "confirmation"], "source": "3.10"}],
        "rule_map": []}
    put("d-harbor-raw/tool-api.json", doc)
    put("d-harbor-raw/spec.json", spec)
    put("d-harbor-raw/pack.json", {"title": "D: Harbor Retail Bank (consumer). Raw bank material: an e-mail, a handbook extract, a memo that changes it, a code list",
                                   "tier": 1, "docs": ["1-email.md", "2-policy-extract.md", "3-memo.md", "4-code-list.csv"],
                                   "stresses": ["raw form with a memo that changes five rules", "identity: postcode (letters and digits) and year of birth", "outcome table with unreached",
                                                "every tool field renamed, OpenAPI 3.1 with $ref and allOf", "three bands, a calendar-day deadline rolled back, year-end closure days",
                                                "a weekend day is refused, not replaced", "a product type without a minimum", "notes for a single account", "up to three accounts"]})
    return spec


# ---------------------------------------------------------------- pack E: Meridian Business Bank, clean specification

def pack_e():
    tools = {
        "verify_identity": ("Check one verification answer.",
                            {"check": S(enum=["company_number", "founded_year"]),
                             "value": S(description="For company_number: the eight digits, leading zeros included. For founded_year: four digits.")},
                            ["check", "value"], {"correct": B, "complete": B}),
        "get_account": ("The overdue facilities. Refused until both questions are passed.", {}, [],
                        {"facilities": {"type": "array", "items": {"type": "object", "properties": {
                            "facility_id": S(), "facility_type": S(enum=["business_loan", "overdraft", "equipment_lease", "company_card"]),
                            "overdue_amount": N(), "days_overdue": I, "minimum_due": N(), "lease_rental": N(), "agreement_no": S(), "card_suffix": S()}}}}),
        "create_promise": ("Record a payment promise. One per facility.",
                           {"facility_id": S(), "amount": N(), "payment_date": S(format="date")}, ["facility_id", "amount", "payment_date"], {"promise_ref": S()}),
        "add_note": ("Record why a facility ended without a promise.",
                     {"facility_id": S(), "reason": S(enum=["settled", "contested", "difficulty", "system_error"]), "text": S()}, ["facility_id", "reason"], {}),
        "schedule_callback": ("Book a callback.", {"callback_date": S(format="date"), "callback_time": S(description="HH:MM")}, ["callback_date", "callback_time"], {}),
        "transfer_to_agent": ("Hand the call to a desk.", {"desk": S(enum=["specialist", "relationship_manager", "support_desk"])}, ["desk"], {}),
        "close_call": ("End the call. Always the last tool call. Nothing is accepted after it.",
                       {"outcome": S(enum=["agreed", "settled", "escalated", "no_agreement", "unverified", "no_contact"]),
                        "reason": S(enum=["insolvency", "manager_request", "support", "declined", "difficulty", "contested", "system_error", "callback_requested",
                                          "wrong_answers", "declined_checks", "unconfirmed", "callback_booked", "callback_refused", "contact_left", "ceased_trading"],
                                    description="Required for every outcome except agreed and settled.")},
                       ["outcome"], {}),
    }
    doc = api("Meridian Business Bank - assistant tools (mock, not an organiser file)", "https://example.invalid/meridian/api/v2", "account_ref", tools, ok="success", prefix="/assistant")
    ladder = [step(1, WEEK_END, FULL_OR_FLOOR), step(2, DEADLINE, {"kind": "percent_of_full", "percent": 50})]
    difficulty_decline = {"actions": [note("difficulty")], "outcome": "no_agreement", "reason": "difficulty"}
    spec = {
        "spec_version": 1,
        "meta": {"bank_name": "Meridian Business Bank", "language": "English", "sources": ["brief.md", "tool-api.json"]},
        "call_variables": [
            {"name": "account_ref", "role": "customer_id", "meaning": "Pass it to every tool call."},
            {"name": "company_name", "role": "address", "meaning": "The company that owes the money."},
            {"name": "contact_first_name", "role": "address", "meaning": "The person to ask for."},
            {"name": "contact_last_name", "role": "address", "meaning": "Address the contact by first and last name."},
            {"name": "local_time", "role": "now", "meaning": "The current date and time. All date rules use this, never the real clock."}],
        "addressing": "{contact_first_name} {contact_last_name}",
        "tool_fields": {"customer_id": "account_ref", "verify_identity": {"field": "check", "answer": "value"},
                        "create_promise": {"product_id": "facility_id", "amount": "amount", "date": "payment_date"},
                        "add_note": {"product_id": "facility_id", "reason": "reason", "text": "text"},
                        "schedule_callback": {"date": "callback_date", "time": "callback_time"},
                        "transfer_to_agent": {"queue": "desk"}, "close_call": {"outcome": "outcome", "reason": "reason"}},
        "agent": {"self_description": "the virtual assistant of Meridian Business Bank", "style_rules": []},
        "opening": {
            "first_sentence": "Hello, this is the virtual assistant of Meridian Business Bank. Calls are recorded.",
            "confirm_question": "May I speak with {contact_first_name} {contact_last_name} of {company_name}?",
            "forbidden_before_identity": ["overdue", "arrears", "debt", "payment", "facility", "loan", "lease", "overdraft", "card"],
            "confirmations": ["yes", "speaking", "the contact's own name"], "non_confirmations": [],
            "max_asks": 2, "answer_question_first": False, "unclear": pair("no_contact", "unconfirmed")},
        "third_party": {
            "enabled": True,
            "instructions": ["Do not say why you are calling.", "Ask when the contact can be reached.",
                             "Nobody but the contact may answer the verification questions, and nobody else is told anything about the facilities."],
            "callback": {"enabled": True, "include_today": True, "business_days_ahead": 3, "window_start": "08:00", "window_end": "18:00", "inclusive": False,
                         "after_now": True, "max_asks": 2, "scheduled": pair("no_contact", "callback_booked"), "not_scheduled": pair("no_contact", "callback_refused")}},
        "identity": {
            "questions": [
                {"field": "company_number", "ask": "Could you tell me the company registration number?", "value_type": "digits",
                 "answer_format": "eight digits", "conversion": "Send the eight digits, with any leading zeros and nothing else."},
                {"field": "founded_year", "ask": "In which year was the company founded?", "value_type": "year", "answer_format": "four digits (YYYY)",
                 "conversion": "Send the year as four digits."}],
            "one_at_a_time": True, "max_wrong_total": 3, "wrong_may_retry": True, "hints": [],
            "on_failed": {"say": "I cannot verify the company, so I have to end this call.", "outcome": "unverified", "reason": "wrong_answers"},
            "decline": {"explanation": "These checks protect the company's accounts.", "max_declines": 2, "purpose_question_counts": False,
                        "outcome": "unverified", "reason": "declined_checks"},
            "result_fields": {"ok": "success", "verified": "correct", "all_verified": "complete", "wrong_left": "", "hint": ""}},
        "account": {
            "products_field": "facilities",
            "product_fields": {"id": "facility_id", "type": "facility_type", "past_due": "overdue_amount", "days_late": "days_overdue"},
            "product_types": [{"type": "business_loan", "spoken_name": "business loan", "floor_field": "minimum_due"},
                              {"type": "overdraft", "spoken_name": "overdraft facility", "floor_field": "minimum_due"},
                              {"type": "equipment_lease", "spoken_name": "equipment lease {agreement_no}", "floor_field": "lease_rental"},
                              {"type": "company_card", "spoken_name": "company card ending {card_suffix}", "floor_field": "minimum_due"}],
            "max_products": 3,
            "statement_intro": "I am calling about overdue amounts on your company's facilities.",
            "statement_per_product": "Your {spoken_name} is {days_late} days overdue, with {past_due} outstanding."},
        "calendar": {"business_weekdays": [0, 1, 2, 3, 4, 5], "holidays": ["2026-10-29", "2026-11-14", "2026-12-25", "2026-12-26", "2027-01-01", "2027-01-02"]},
        "bands": [
            {"name": "standard", "days_late_min": 1, "days_late_max": 14, "deadline": {"kind": "nth_calendar_day_after_today", "n": 10, "roll": "next_business_day"},
             "attempts": 2, "ladder": copy.deepcopy(ladder)},
            {"name": "priority", "days_late_min": 15, "days_late_max": 60, "deadline": {"kind": "last_business_day_of_month", "month_offset": 0},
             "attempts": 2, "ladder": copy.deepcopy(ladder)},
            {"name": "escalated", "days_late_min": 61, "days_late_max": 9999, "deadline": BIZ(2), "attempts": 0, "ladder": []}],
        "dates": {"earliest": {"kind": "today"}, "business_day_only": False, "non_business_day": "offer_next_business_day", "after_deadline": "reject",
                  "refused_deadline_is_flat_refusal": False,
                  "vague": {"examples": ["next week", "at the end of the quarter", "when our client pays us"], "ask_exact_times": 1, "then": "flat_refusal"},
                  "relative_weekday": {"next": "following_week", "this": "current_week"}},
        "amounts": {"first_offer": FULL, "never_ask_open_amount": True, "accept_min": FLOOR, "accept_max": FULL,
                    "too_much": {"offer": FLOOR, "times": 1, "say": "The balance that remains is still overdue.", "refused_is_flat_refusal": True},
                    "below_min": {"say": "That is below the minimum we can accept.", "offer": FLOOR, "times": 1, "refused_is_flat_refusal": True}},
        "negotiation": {"first_ask": "Can the company settle this today?", "proposal_never_refusal": True,
                        "flat_refusal_definition": "A flat refusal or a non-answer.",
                        "attempts_exhausted": {"outcome": "no_agreement", "reason": "declined"},
                        "forbidden_offers": ["a discount", "a waiver", "a payment holiday", "a new repayment schedule"],
                        "forbidden_questions": ["How much can the company pay?"], "call_attempt_limit": 3},
        "confirmation": {"read_back": ["product", "amount", "date"], "question": "Is that correct?", "require_clear_yes": True,
                         "on_change": "revalidate_and_read_back", "one_promise_per_product": True,
                         "after_record_change_say": "A recorded promise cannot be changed in this call. Your relationship manager can change it."},
        "recording": {"max_attempts": 1, "success_field": "success", "after_success_say": "You will receive an e-mail confirming this arrangement.",
                      "retry_say": "", "failure_say": "I am sorry, the system could not take this arrangement.",
                      "on_final_failure": {"outcome": "no_agreement", "reason": "system_error", "note_reason": "system_error"}},
        "situations": [
            sit("contact_left", "The person says the contact no longer works for the company.", ["opening", "third_party"], "no_contact", "contact_left", priority=90, source="9"),
            sit("ceased_trading", "The person says the company has stopped trading.", ["opening", "third_party"], "no_contact", "ceased_trading", priority=95, source="10"),
            sit("insolvency", "The contact says the company is insolvent, in administration or in liquidation.", ["negotiation", "confirmation"], "escalated", "insolvency",
                actions=[transfer("specialist")], priority=85, words=["insolven", "administrat", "liquidat", "bankrupt"],
                not_this="Saying the company cannot pay now, with no insolvency, is a refusal.", guidance="Do not negotiate and take no promise.", source="39"),
            sit("difficulty", "The contact says the company is in temporary difficulty: a fire, a flood, the loss of a major client.", ["negotiation", "confirmation"],
                "no_agreement", "difficulty", actions=[note("difficulty")], priority=80, proposal=True, not_this="Saying the amount is too much, with no such event, is not this.",
                guidance="Say one short sentence of understanding. Make no persuasion attempt.", source="43",
                offer={"question": "Offer to put the contact through to the business support desk.",
                       "on_accept": {"actions": [transfer("support_desk")], "outcome": "escalated", "reason": "support"}, "on_decline": difficulty_decline}),
            sit("manager", "The contact asks for the relationship manager or for a person.", ["opening", "identity", "negotiation", "confirmation"], "escalated", "manager_request",
                actions=[transfer("relationship_manager")], priority=60, threshold=2, first_response="Ask once whether you can help first.",
                words=["manager", "person", "human", "someone", "somebody"], not_this="Asking whether the assistant is a machine is a question, not this.", source="40"),
            sit("call_back_later", "The contact says it is a bad moment and asks to be called back.", ["identity", "negotiation", "confirmation"], "no_agreement", "callback_requested",
                actions=[{"type": "callback"}], priority=55, words=["call back", "call me back", "call again", "call later", "ring back", "ring me back", "bad moment", "bad time", "in a meeting"],
                not_this="Proposing a later payment date is a proposal, not a request to be called back.", source="44"),
            sit("not_talking", "The contact says they do not want to talk.", ["identity", "negotiation", "confirmation"], "no_agreement", "declined", priority=40, threshold=2,
                first_response="Acknowledge it in one sentence and continue.", not_this="Refusing to pay is a refusal, not this.", source="47",
                by_stage={"before_identity": pair("unverified", "declined_checks"), "after_identity": pair("no_agreement", "declined")}),
            sit("already_paid", "The contact says the company has already paid this overdue amount.", ["negotiation", "confirmation"], "settled", "", actions=[note("settled")],
                scope="product", say="Payments can take up to three business days to appear.", say_exact=True, source="41"),
            sit("contested", "The contact says the company does not owe this, or never had this facility.", ["negotiation", "confirmation"], "no_agreement", "contested",
                actions=[note("contested")], scope="product", guidance="Do not argue and take no promise for that facility.", source="42")],
        "faq": [
            {"trigger": "The contact asks whether they are talking to a machine.", "answer": "Say that you are the virtual assistant of Meridian Business Bank, then continue.", "source": "5"},
            {"trigger": "The contact asks whether this call is a scam.", "answer": "Say that they can check the call by ringing their relationship manager on the usual number, then continue.", "source": "45"},
            {"trigger": "The contact asks something the tools cannot answer.", "answer": "Say that you do not have that information. Do not invent figures, dates or reasons.", "source": "46"}],
        "multi_product": {"enabled": True, "state_all_first": True, "ask_all_today_once": True, "first_ask_all": "Can the company settle all of them today?",
                          "order": "as_returned", "attempts_per_product": False, "one_date_clamped_per_product": False, "single_read_back": True,
                          "unrecorded_on_transfer": "drop"},
        "notes": {"enabled": True, "for_each_product_without_promise": False, "reasons": ["settled", "contested", "difficulty", "system_error"], "on_transfer": "none"},
        "outcomes": {
            "table": [{"outcome": "agreed", "reasons": [], "when": "at least one promise was recorded"},
                      {"outcome": "settled", "reasons": [], "when": "no promise, and every facility was already paid"},
                      {"outcome": "escalated", "reasons": ["insolvency", "manager_request", "support"], "when": "rules 39, 40, 43"},
                      {"outcome": "no_agreement", "reasons": ["declined", "difficulty", "contested", "system_error", "callback_requested"], "when": "rules 32 and 47, 43, 42, 37, 44"},
                      {"outcome": "unverified", "reasons": ["wrong_answers", "declined_checks"], "when": "rules 14, 15 and 47"},
                      {"outcome": "no_contact", "reasons": ["unconfirmed", "callback_booked", "callback_refused", "contact_left", "ceased_trading"], "when": "rules 3, 7, 8, 9, 10"}],
            "reason_omitted_for": ["agreed", "settled"], "promise": pair("agreed"), "transfer_after_promise": "transfer_wins",
            "multi": {"all_notes_match": {"note_reason": "settled", "outcome": "settled", "reason": ""},
                      "otherwise": {"outcome": "no_agreement", "reason_from": "first_note_not_matching"}}},
        "closing": {"farewell": "Thank you for your time. Goodbye."},
        "free_rules": [
            {"id": "29c", "text": "No attempt names a date after the deadline: if its date would be later, it names the deadline.", "applies_to": ["negotiation"], "source": "29"},
            {"id": "30", "text": "Persuasion attempts are counted for the whole call, at most three, and a facility never gets more than its band allows.", "applies_to": ["negotiation"], "source": "30"},
            {"id": "31", "text": "A facility in the escalated band gets no persuasion attempt: a refusal ends it at once.", "applies_to": ["negotiation"], "source": "31"},
            {"id": "50", "text": "A facility that was simply refused gets no note.", "applies_to": ["negotiation", "confirmation"], "source": "50"},
            {"id": "4", "text": "A question asked before the contact is confirmed is not answered: say you can explain once you know who you are speaking with.", "applies_to": ["opening"], "source": "4"}],
        "rule_map": []}
    put("e-meridian-clean/tool-api.json", doc)
    put("e-meridian-clean/spec.json", spec)
    put("e-meridian-clean/pack.json", {"title": "E: Meridian Business Bank (companies). A clean specification of 56 rules", "tier": 1, "docs": ["brief.md"],
                                       "stresses": ["identity: company registration number with leading zeros and year founded", "outcome table with no_contact",
                                                    "a tool API that does not say how many tries are left, and answers `success` instead of `ok`",
                                                    "Saturday is a business day; holidays on Saturdays", "a calendar-day deadline, a month-end deadline, a band with no persuasion attempt",
                                                    "an offer of half the amount", "attempts counted for the whole call", "a refused facility gets no note", "no retry when a promise fails",
                                                    "a callback the contact asks for", "a date after the deadline is refused, not replaced", "`local_time` with a space, not a T"]})
    return spec


# ---------------------------------------------------------------- pack F: the kit's Brief A and B, twelve rules changed

F_CHANGES_A = [
    ("| 1 to 7 | early | the 12th business day after today | 1 |\n| 8 to 45 | late | the 7th business day after today | 2 |",
     "| 1 to 5 | early | the 8th business day after today | 1 |\n| 6 to 20 | middle | the 6th business day after today | 2 |\n| 21 to 45 | late | the 4th business day after today | 3 |"),
    ("Freya Bank holidays: 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01.", "Freya Bank holidays: 2026-10-15, 2026-10-19, 2026-11-11, 2026-12-25, 2027-01-01."),
    ("6. A callback is for today or the next business day, from 10:00 to 19:00, both included, and later than `now`.",
     "6. A callback is for the next business day only, never for today, from 09:00 to 17:00, both included."),
    ("ask once for the exact day. If they still give none, propose the deadline.", "ask for the exact day, twice if needed. If they still give none, treat it as a flat refusal (rule 30)."),
    ("22. \"Next <weekday>\" means that weekday in the following calendar week. \"This <weekday>\" means the one in the current week. So \"next Friday\" said on a Friday is the Friday of the following week.",
     "22. \"Next <weekday>\" and \"this <weekday>\" both mean the first such weekday that comes. Said on that weekday, \"this <weekday>\" means today and \"next <weekday>\" means the one seven days later."),
    ("Attempt 2 may name the floor again, on the deadline.", "Attempts 2 and 3 may name the floor again."),
    ("28. First ask: \"Can you make this payment today?\".", "28. First ask: \"Could you pay this amount today?\"."),
    ("    - Attempt 1: propose the last business day of this week. If today is that day, propose the last business day of next week.\n    - Attempt 2, late band only: propose the floor amount on the deadline.",
     "    - Attempt 1: propose the next business day.\n    - Attempt 2, middle and late bands: propose the floor amount on the 3rd business day after today.\n    - Attempt 3, late band only: propose the floor amount on the deadline."),
    ("and ask \"Do you confirm?\".", "and ask \"Is that right?\"."),
    ("If it fails, try once more. If it fails again, say you could not record it", "If it fails, try twice more. If it fails a third time, say you could not record it"),
    ("38. After a recorded promise, say this sentence: \"You will receive a text message confirming this promise.\"", "38. After a recorded promise, say this sentence: \"We will send you an e-mail to confirm this promise.\""),
    ("say that payments can take one business day to appear", "say that payments can take two business days to show"),
    ("42. A request for a human: ask once whether you can help first. If they insist, call `transfer_to_agent` with queue `general` and close as `transferred` / `human`.",
     "42. A request for a human: do not ask whether you can help first. Call `transfer_to_agent` with queue `general` at once and close as `transferred` / `human`."),
    ("close as `not_reached` / `unclear`", "close as `not_reached` / `no_confirmation`"),
    ("| `not_reached` | `callback`, `no_callback`, `wrong_number`, `deceased`, `unclear` |", "| `not_reached` | `callback`, `no_callback`, `wrong_number`, `deceased`, `no_confirmation` |"),
    ("# Brief A: Freya Bank, early-stage collections, one product", "# Mock brief F, part 1: Freya Bank, autumn campaign, one product\n\nA changed copy of the kit's Brief A, written by us to test the builder. Not an organiser brief."),
]
F_CHANGES_B = [
    ("# Brief B: Freya Bank, up to three products", "# Mock brief F, part 2: Freya Bank, autumn campaign, up to three products\n\nA changed copy of the kit's Brief B, written by us to test the builder. Not an organiser brief."),
    ("Brief B is Brief A with a customer who can be late on up to three products. Every rule of Brief A applies unless a rule below replaces it.",
     "Part 2 is part 1 with a customer who can be late on up to three products. Every rule of part 1 applies unless a rule below replaces it."),
    ("Start each product at attempt 1 of Brief A rule 30.", "Start each product at attempt 1 of part 1 rule 30."),
    ("11. If one `create_promise` fails twice,", "11. If one `create_promise` fails three times,"),
]


def pack_f():
    def changed(path, changes):
        text = (KIT / path).read_text(encoding="utf-8")
        for old, new in changes:
            assert text.count(old) == 1, f"{path}: expected exactly one {old[:60]!r}, found {text.count(old)}"
            text = text.replace(old, new)
        return text
    a, b = changed("briefs/brief-a.md", F_CHANGES_A), changed("briefs/brief-b.md", F_CHANGES_B)
    b = b.replace("Brief A rule 41", "part 1 rule 41").replace("The outcome table of Brief A applies.", "The outcome table of part 1 applies.")
    assert "Brief A" not in b, "part 2 still names Brief A"
    spec = json.loads((KIT / "dev/specs/brief-ab.json").read_text(encoding="utf-8"))
    spec["meta"]["sources"] = ["1-specification.md", "2-addendum.md", "tools/openapi.json"]
    first = step(1, BIZ(1), FULL_OR_FLOOR)
    spec["bands"] = [{"name": "early", "days_late_min": 1, "days_late_max": 5, "deadline": BIZ(8), "attempts": 1, "ladder": [copy.deepcopy(first)]},
                     {"name": "middle", "days_late_min": 6, "days_late_max": 20, "deadline": BIZ(6), "attempts": 2, "ladder": [copy.deepcopy(first), step(2, BIZ(3), FLOOR)]},
                     {"name": "late", "days_late_min": 21, "days_late_max": 45, "deadline": BIZ(4), "attempts": 3,
                      "ladder": [copy.deepcopy(first), step(2, BIZ(3), FLOOR), step(3, DEADLINE, FLOOR)]}]
    spec["calendar"]["holidays"] = ["2026-10-15", "2026-10-19", "2026-11-11", "2026-12-25", "2027-01-01"]
    spec["third_party"]["callback"].update(include_today=False, business_days_ahead=1, window_start="09:00", window_end="17:00")
    spec["dates"]["vague"].update(ask_exact_times=2, then="flat_refusal")
    spec["dates"]["relative_weekday"] = {"next": "upcoming", "this": "upcoming"}
    spec["negotiation"]["first_ask"] = "Could you pay this amount today?"
    spec["confirmation"]["question"] = "Is that right?"
    spec["recording"]["max_attempts"] = 3
    spec["recording"]["after_success_say"] = "We will send you an e-mail to confirm this promise."
    by_id = {x["id"]: x for x in spec["situations"]}
    by_id["already_paid"]["say"] = "Payments can take two business days to show."
    by_id["human"].update(threshold=1, first_response="", guidance="Do not ask whether you can help first. Transfer at once.")
    spec["opening"]["unclear"]["reason"] = "no_confirmation"
    row = next(r for r in spec["outcomes"]["table"] if r["outcome"] == "not_reached")
    row["reasons"] = ["no_confirmation" if r == "unclear" else r for r in row["reasons"]]
    spec["rule_map"] = []
    put("f-freya-sibling/1-specification.md", a)
    put("f-freya-sibling/2-addendum.md", b)
    put("f-freya-sibling/spec.json", spec)
    put("f-freya-sibling/pack.json", {"title": "F: the kit's Brief A and B with twelve rules changed at once, on the kit's own tool API", "tier": 1,
                                      "docs": ["1-specification.md", "2-addendum.md"], "api": "tools/openapi.json", "platform": True,
                                      "stresses": ["the only pack that can be simulated on the platform: it keeps the kit's tool API and the practice customers' accounts",
                                                   "three bands, other deadlines, three persuasion attempts", "holidays on the day after the practice day and the Monday after it",
                                                   "callbacks for the next business day only", "the exact day asked twice, then a flat refusal", "a human is transferred at once",
                                                   "three tries to record a promise", "other fixed sentences", "another closing reason"]})
    return spec


def main(argv=None):
    pack_d(); pack_e(); pack_f()
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    stale = []
    for rel, text in OUT.items():
        p = HERE / rel
        if check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(rel)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
    if check:
        print("\n".join(f"STALE {s}" for s in stale) or f"{len(OUT)} generated files are up to date")
        return 1 if stale else 0
    print(f"wrote {len(OUT)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
