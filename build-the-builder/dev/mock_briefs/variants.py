"""One rule changed at a time: every switch and number of the SPEC that packs D, E and F leave at one value, set
to another one. Each variant is a SPEC a careful reader could bring back from a brief with that rule, built from a
pack's oracle SPEC (and, where the rule needs it, a changed tool API). The generated agent then meets the customers
of universal.py on several calendar days.

    for v in variants(): box = v["box"]; ...        # v: name, tier, rule (the brief's sentence), box, days, now

The `rule` is the sentence a brief would carry; it is there so a failure can be read without opening the code, and
so the sentence can be put into a brief when the extractor is tested on it.
Tier 1: a kind of change the final briefs announce. Tier 2: a plausible rule. Tier 3: exotic.
"""
import copy, json
import lib
from builder import ingest

DAYS = ["2026-11-03", "2026-11-06", "2026-11-07", "2026-11-12", "2026-11-30", "2026-12-23", "2026-12-31"]


def _packs():
    return {p.name.split("-")[0]: p for p in lib.packs()}


def _api(pack):
    return json.loads(pack.api_path.read_text(encoding="utf-8"))


def _props(api, tool):
    """The request properties of a tool in an API description, whatever its style."""
    for route, ops in api["paths"].items():
        if ingest.tool_name(ops["post"].get("operationId"), route) == tool:
            schema = ops["post"]["requestBody"]["content"]["application/json"]["schema"]
            while "$ref" in schema or "allOf" in schema:
                if "$ref" in schema:
                    schema = api["components"]["schemas"][schema["$ref"].split("/")[-1]]
                else:
                    schema = next(x for x in schema["allOf"] if "properties" in x and "$ref" not in x)
            return schema
    raise KeyError(tool)


def strip_reasons(spec):
    """A brief whose outcome table has no reasons at all (and a tool API without a reason field)."""
    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("outcome"), str) and "reason" in v:
                v["reason"] = ""
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(spec)
    for row in spec["outcomes"]["table"]:
        row["reasons"] = []
    spec["outcomes"]["reason_omitted_for"] = [r["outcome"] for r in spec["outcomes"]["table"]]
    spec["outcomes"].pop("multi", None)                    # its "otherwise" close takes a note's reason, and there are none
    spec["tool_fields"]["close_call"]["reason"] = ""


def variants(only=None):
    packs, out = _packs(), []

    def add(name, tier, base, rule, edit=None, api=None, days=None, now=None, note=""):
        if only and name not in only:
            return
        pack = packs[base]
        spec = copy.deepcopy(pack.spec)
        tools = pack.tools
        if api:
            doc = _api(pack)
            api(doc)
            tools = ingest.parse_api(doc)["tools"]
        if edit:
            edit(spec)
        out.append({"name": name, "tier": tier, "base": pack.name, "rule": rule, "note": note, "days": days or DAYS, "now": now,
                    "box": lib.Box(f"{base}+{name}", spec, tools, f"{pack.name} with: {rule}", tier)})

    S = lambda path, value: (lambda spec: _set(spec, path, value))

    # ---------------- dates
    add("earliest_tomorrow", 2, "d", "A promise date is tomorrow or later: a payment for the same day cannot be promised.",
        S("dates.earliest", {"kind": "nth_calendar_day_after_today", "n": 1, "roll": "none"}))
    add("earliest_next_business_day", 2, "d", "A promise date is the next business day or later.", S("dates.earliest", {"kind": "nth_business_day_after_today", "n": 1}))
    add("weekend_gets_next_business_day", 1, "d", "A weekend day or a closure day: offer the next business day.", S("dates.non_business_day", "offer_next_business_day"))
    add("late_date_refused", 2, "d", "A date after the latest promise date cannot be recorded: say so and ask for an earlier one.", S("dates.after_deadline", "reject"))
    add("any_calendar_day", 2, "d", "A promise can have any calendar day, also a weekend day or a closure day.", S("dates.business_day_only", False))
    add("vague_never_asked", 2, "d", "A vague period: do not ask again, propose the latest promise date at once.", S("dates.vague.ask_exact_times", 0))
    add("vague_is_refusal", 2, "d", "A vague period is a flat refusal.", lambda s: s["dates"]["vague"].update(ask_exact_times=0, then="flat_refusal"))
    add("next_means_following_week", 1, "d", "'Next Friday' is the Friday of the following calendar week, 'this Friday' the one of this week.",
        S("dates.relative_weekday", {"next": "following_week", "this": "current_week"}))
    add("no_holidays", 1, "d", "Business days are Monday to Friday. There are no closure days.", S("calendar.holidays", []))
    add("sunday_to_thursday", 2, "e", "Business days are Sunday to Thursday.", S("calendar.business_weekdays", [6, 0, 1, 2, 3]))
    add("every_day_is_a_business_day", 3, "e", "Every day is a business day.", lambda s: s["calendar"].update(business_weekdays=[0, 1, 2, 3, 4, 5, 6], holidays=[]))
    add("holiday_run", 2, "d", "Closure days: every day from 9 to 20 November 2026.",
        S("calendar.holidays", [f"2026-11-{d:02d}" for d in range(9, 21)]), note="ten closure days in a row: every count of business days jumps over them")

    # ---------------- bands, deadlines, the persuasion ladder
    add("one_band", 1, "d", "Every customer has the same latest promise date (the 7th business day after today) and one persuasion attempt.",
        lambda s: s.__setitem__("bands", [dict(copy.deepcopy(s["bands"][0]), name="all", days_late_min=1, days_late_max=9999, deadline={"kind": "nth_business_day_after_today", "n": 7})]))
    add("four_bands", 2, "d", "A fourth band, 121 to 365 days overdue: latest promise date tomorrow's business day, four persuasion attempts.",
        lambda s: s["bands"].append({"name": "D", "days_late_min": 121, "days_late_max": 365, "deadline": {"kind": "nth_business_day_after_today", "n": 2}, "attempts": 4,
                                     "ladder": [{"attempt": 1, "date": {"kind": "nth_business_day_after_today", "n": 1}, "amount": {"kind": "full"}},
                                                {"attempt": 2, "date": {"kind": "nth_business_day_after_today", "n": 1}, "amount": {"kind": "percent_of_full", "percent": 75}},
                                                {"attempt": 3, "date": {"kind": "deadline"}, "amount": {"kind": "percent_of_full", "percent": 50}},
                                                {"attempt": 4, "date": {"kind": "deadline"}, "amount": {"kind": "floor"}}]}))
    add("deadline_today", 2, "d", "Band A: the latest promise date is today.", S("bands.0.deadline", {"kind": "today"}),
        note="every attempt is clamped to today; nothing after today can be promised")
    add("deadline_is_the_weeks_end", 2, "d", "Band A: the latest promise date is the last business day of this week.",
        S("bands.0.deadline", {"kind": "last_business_day_of_week", "week_offset": 0, "if_today_week_offset": 0}), note="on a Saturday that day has passed: no day is left for a promise")
    add("deadline_next_months_end", 2, "d", "Band A: the latest promise date is the last business day of next month.",
        S("bands.0.deadline", {"kind": "last_business_day_of_month", "month_offset": 1}), note="up to nine weeks ahead: the agent must still say the date in words")
    add("deadline_sixty_business_days", 2, "d", "Band A: the latest promise date is the 60th business day after today.",
        S("bands.0.deadline", {"kind": "nth_business_day_after_today", "n": 60}), note="about twelve weeks ahead")
    add("deadline_calendar_days_not_rolled", 2, "d", "Band A: the latest promise date is the 7th calendar day after today.",
        S("bands.0.deadline", {"kind": "nth_calendar_day_after_today", "n": 7, "roll": "none"}), note="the deadline itself can be a weekend day")
    add("attempt_on_the_weeks_end", 2, "d", "Attempt 1: the full overdue amount on the last business day of this week.",
        lambda s: [b["ladder"][0].__setitem__("date", {"kind": "last_business_day_of_week", "week_offset": 0, "if_today_week_offset": 0}) for b in s["bands"]],
        note="no word about the day when today is that day: on a Friday the offer is today, on a Saturday it would be yesterday")
    add("attempt_in_calendar_days", 2, "d", "Attempt 1: the full overdue amount in three days.",
        lambda s: [b["ladder"][0].__setitem__("date", {"kind": "nth_calendar_day_after_today", "n": 3, "roll": "none"}) for b in s["bands"]],
        note="three calendar days on can be a weekend day or a closure day")
    add("attempt_at_months_end", 2, "e", "Attempt 1: the full overdue amount on the last business day of this month.",
        lambda s: [b["ladder"][0].__setitem__("date", {"kind": "last_business_day_of_month", "month_offset": 0}) for b in s["bands"] if b["ladder"]])
    add("no_attempts_at_all", 2, "d", "No persuasion attempts in any band: a refusal ends the account at once.",
        lambda s: [b.update(attempts=0, ladder=[]) for b in s["bands"]])

    # ---------------- amounts
    add("minimum_first", 2, "d", "Ask for the minimum first, not for the full overdue amount; every persuasion attempt is for the minimum too.",
        lambda s: (s["amounts"].__setitem__("first_offer", {"kind": "floor"}), [st.__setitem__("amount", {"kind": "floor"}) for b in s["bands"] for st in b["ladder"]]))
    add("only_the_full_amount", 2, "d", "Part payments are not accepted: only the full overdue amount can be promised, and nothing lower is ever offered.",
        lambda s: (s["amounts"].update(accept_min={"kind": "full"}), s["amounts"]["too_much"].update(offer={"kind": "full"}, times=0, say=""),
                   s["amounts"]["below_min"].update(offer={"kind": "full"})))
    add("at_least_half", 2, "d", "A part payment of at least half the overdue amount is accepted; below that, offer half.",
        lambda s: (s["amounts"].update(accept_min={"kind": "percent_of_full", "percent": 50}), s["amounts"]["below_min"].update(offer={"kind": "percent_of_full", "percent": 50}),
                   s["amounts"]["too_much"].update(offer={"kind": "percent_of_full", "percent": 50})))
    add("minimum_refused_is_not_flat", 2, "d", "A customer who turns the minimum down has not flatly refused.",
        lambda s: (s["amounts"]["too_much"].__setitem__("refused_is_flat_refusal", False), s["amounts"]["below_min"].__setitem__("refused_is_flat_refusal", False)))
    add("no_too_much_sentence", 1, "d", "If the full amount is too much, offer the minimum once. (No sentence is prescribed.)", S("amounts.too_much.say", ""))

    # ---------------- recording and sentences
    add("one_try", 1, "d", "If create_promise fails, do not try again.", S("recording.max_attempts", 1))
    add("four_tries", 2, "d", "If create_promise fails, try again: four tries in total.", S("recording.max_attempts", 4))
    add("no_sentence_after_recording", 1, "d", "(No sentence is prescribed after a recorded promise.)", S("recording.after_success_say", ""))
    add("no_retry_sentence", 1, "d", "(No sentence is prescribed before a retry.)", S("recording.retry_say", ""))
    add("farewell_without_name", 1, "d", "Thank the customer and say goodbye.", S("closing.farewell", "Thank you. Goodbye."))
    add("no_farewell", 3, "d", "(No farewell is prescribed.)", S("closing.farewell", ""))

    # ---------------- opening, someone else, security
    add("asks_once", 1, "d", "Ask once. If the person does not confirm, close.", S("opening.max_asks", 1))
    add("no_callback", 2, "e", "Do not book a callback: close as no_contact / callback_refused.", S("third_party.callback.enabled", False))
    add("callback_same_day_only", 2, "e", "A callback is for today only.", lambda s: s["third_party"]["callback"].update(include_today=True, business_days_ahead=0))
    add("callback_any_time", 2, "e", "A callback can have any time, also one that has passed today is asked again.", S("third_party.callback.after_now", False))
    add("callback_narrow_window", 2, "e", "A callback is strictly between 12:00 and 12:30, and asked for once only.",
        lambda s: s["third_party"]["callback"].update(window_start="12:00", window_end="12:30", inclusive=False, max_asks=1))
    add("nobody_else", 3, "e", "(The brief has no rule for someone else answering.)", S("third_party.enabled", False))
    add("one_question", 1, "d", "One security question: the postcode of the registered address.",
        lambda s: s["identity"].__setitem__("questions", s["identity"]["questions"][:1]),
        api=lambda a: _props(a, "verify_identity")["properties"]["question"].__setitem__("enum", ["postcode"]))
    add("three_questions", 2, "e", "A third question: the last three digits of the business account number.",
        lambda s: s["identity"]["questions"].append({"field": "account_last3", "ask": "And the last three digits of the business account number?", "value_type": "digits",
                                                     "answer_format": "three digits", "conversion": "Send the three digits only."}),
        api=lambda a: _props(a, "verify_identity")["properties"]["check"]["enum"].append("account_last3"))
    add("one_wrong_answer", 1, "d", "One wrong answer ends the check.", S("identity.max_wrong_total", 1))
    add("five_wrong_answers", 1, "d", "Five wrong answers in total end the check.", S("identity.max_wrong_total", 5))
    add("declines_three_times", 2, "e", "If the contact declines, explain; a third refusal closes the call.", S("identity.decline.max_declines", 3))
    add("purpose_question_declines", 1, "d", "Asking what the call is about instead of answering counts as declining.", S("identity.decline.purpose_question_counts", True))
    add("hint_counts_as_wrong", 2, "d", "The advice partial_postcode counts as a wrong answer.", lambda s: s["identity"]["hints"][0].__setitem__("counts_as_wrong", True))
    add("api_says_nothing", 2, "e", "(The verify tool answers only whether this one answer was correct.)", S("identity.result_fields.all_verified", ""),
        note="the code must know by itself when every question is passed and when the wrong answers are used up")

    # ---------------- several products, notes, the close
    add("read_back_each", 2, "d", "Read each promise back as soon as it is agreed, with its own confirmation.", S("multi_product.single_read_back", False))
    add("one_by_one", 2, "d", "State one account, deal with it, then state the next one and ask whether it can be cleared today.",
        lambda s: s["multi_product"].update(state_all_first=False, ask_all_today_once=False))
    add("today_asked_per_product", 2, "d", "Ask about today for each account in turn.", S("multi_product.ask_all_today_once", False))
    add("attempts_for_the_call", 2, "d", "Persuasion attempts are counted for the whole call: at most two.",
        lambda s: (s["multi_product"].__setitem__("attempts_per_product", False), s["negotiation"].__setitem__("call_attempt_limit", 2)))
    add("attempts_for_the_call_no_number", 2, "d", "Persuasion attempts are counted for the whole call, not per account.", S("multi_product.attempts_per_product", False))
    add("one_date_not_clamped", 2, "d", "One date for everything that is too late for one account: offer that account its own latest date.",
        S("multi_product.one_date_clamped_per_product", False))
    add("record_before_transfer", 2, "d", "On a hand-over, promises that were agreed are recorded first.", S("multi_product.unrecorded_on_transfer", "record"))
    add("transfer_wins", 1, "d", "If a hand-over follows a recorded promise, close as handed_over.", S("outcomes.transfer_after_promise", "transfer_wins"))
    add("no_note_for_a_refusal", 2, "d", "An account that was simply refused gets no note.",
        lambda s: (s["notes"].__setitem__("for_each_product_without_promise", False), s["negotiation"]["attempts_exhausted"].pop("note_reason", None)))
    add("notes_on_a_transfer_too", 2, "d", "On a hand-over, note every account without a promise as well.", S("notes.on_transfer", "add"))
    add("one_product_with_notes", 1, "f", "One product per customer, and add_note is used: a product that ends without a promise is noted.",
        lambda s: (s["account"].__setitem__("max_products", 1), s["multi_product"].__setitem__("enabled", False)),
        note="the kit's Brief A says it never uses add_note; a one-product brief that does is this")
    add("one_product_with_notes_no_closing_rule", 2, "f", "One product per customer with notes, and no closing rule for several products.",
        lambda s: (s["account"].__setitem__("max_products", 1), s["multi_product"].__setitem__("enabled", False), s["outcomes"].pop("multi", None)))
    add("several_products_no_notes", 2, "f", "Up to three products, and add_note is never used.",
        lambda s: (s["notes"].update(enabled=False, reasons=[]), s["outcomes"].pop("multi", None), s["negotiation"]["attempts_exhausted"].pop("note_reason", None),
                   s["recording"]["on_final_failure"].pop("note_reason", None), [x["effect"].__setitem__("actions", [a for a in x["effect"]["actions"] if a["type"] != "note"]) for x in s["situations"]],
                   [x["offer"]["on_decline"].__setitem__("actions", []) for x in s["situations"] if x.get("offer")]))
    add("no_reasons", 3, "e", "(The outcome table has no reasons, and close_call has no reason field.)", strip_reasons,
        api=lambda a: _props(a, "close_call")["properties"].pop("reason"))
    add("no_situations", 2, "d", "(The brief names no special situation at all.)", lambda s: (s.__setitem__("situations", []), s.__setitem__("faq", [])))

    # ---------------- the tool API and the call's clock
    add("note_text_required", 3, "d", "(The tool API requires a free text with every note.)", None, api=lambda a: _props(a, "add_note")["required"].append("comment"))
    for name, value in (("now_with_seconds", "{d}T11:00:00"), ("now_with_zone", "{d}T11:00:00+03:00"), ("now_with_z", "{d}T11:00:00Z"), ("now_with_a_space", "{d} 11:00")):
        add(name, 1 if name != "now_with_zone" else 2, "d", f"(The call's time is given as {value.format(d='2026-11-03')}.)", None, now=value, days=DAYS[:3])
    return out


def _set(spec, path, value):
    node = spec
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if part.isdigit() else node[part]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value
