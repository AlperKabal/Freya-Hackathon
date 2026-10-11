"""Customers the practice set does not have: our own scripts on the practice customers' accounts, on other calendar
days, with the bank records each must leave behind worked out from the brief (dev/expect.py).

    from scenarios import scenarios
    for s in scenarios(): ...          # each is shaped like a case of public-test-set.json, plus "base"

The mock bank opens a session only for a known practice case id, so every scenario borrows one (`base`): its
identity answers and its products. The script, the call's `now`, the expected records and the judge's checks are
ours. dev/run_scenarios.py runs them against an agent. Brief A/B values are fixtures here (dev/), never in builder/.
"""
import copy, datetime as dt, json, pathlib
KIT = pathlib.Path(__file__).resolve().parent.parent
from expect import attempt_1, biz, deadline, next_business_day, spoken

PUBLIC = {c["id"]: c for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}
WEDNESDAY = dt.date(2026, 10, 14)                 # the practice set's own day
DAYS = [("fri", dt.date(2026, 10, 16), "a Friday: the week's last business day is today"),
        ("prehol", dt.date(2026, 10, 23), "a Friday before a Monday holiday"),
        ("holeve", dt.date(2026, 11, 10), "the day before a holiday in the middle of the week"),
        ("monthend", dt.date(2026, 10, 30), "the last business day of the month"),
        ("xmas", dt.date(2026, 12, 24), "the day before a holiday, a week before the year ends")]


def _floor(p):
    return p.get("minimum_payment", p.get("instalment_amount"))


def _promise(i, amount, day):
    return {"product_id": f"p{i}", "amount": float(amount), "date": day.isoformat()}


def _case(sid, base, day, title, script, outcome, reason=None, promises=(), notes=(), callbacks=(), transfers=(), checks=(), family="Custom", hour="11:00", third_party=None):
    b = copy.deepcopy(PUBLIC[base])
    b.pop("faults", None)                                  # the mock applies a base case's faults by itself
    b.update(id=sid, base=base, family=family, level="custom", title=title, script=script, checks=list(checks) or ["the agent follows the brief"],
             expected={"outcome": outcome, "reason": reason, "promises": list(promises), "notes": [{"product_id": p, "reason": r} for p, r in notes],
                       "callbacks": [{"date": d.isoformat(), "time": t} for d, t in callbacks], "transfers": [{"queue": q} for q in transfers]})
    b["variables"] = dict(b["variables"], now=f"{day.isoformat()}T{hour}")
    if third_party is not None:
        b["third_party"] = third_party
    return b


def scenarios():
    out = []
    add = lambda *a, **k: out.append(_case(*a, **k))
    V = "Confirms the name and answers both security questions correctly."

    # ---------------- Brief A on other calendar days: the dated rules (18-23, 26, 30)
    for tag, day, why in DAYS:
        p = PUBLIC["PUB-01"]["products"][0]
        a1 = min(attempt_1(day), deadline(p["days_late"], day))
        add(f"CAL-{tag}-first", "PUB-01", day, f"Cannot pay today, takes the first date offered ({why})",
            f"{V} Says he cannot pay today. Proposes no date himself. Agrees to pay the full amount on the first date the agent proposes. Confirms at the read-back.",
            "promise", promises=[_promise(1, p["past_due"], a1)],
            checks=[f"the first date the agent proposes is {spoken(a1)}", "the agent never asks how much he can pay", "create_promise called exactly once"])
        p = PUBLIC["PUB-04"]["products"][0]
        dl = deadline(p["days_late"], day)
        far = dl + dt.timedelta(days=14)
        add(f"CAL-{tag}-late-date", "PUB-04", day, f"Wants a date after the deadline ({why})",
            f"{V} Says her salary arrives on {spoken(far)} and she can pay then. Accepts the latest possible date when it is offered.",
            "promise", promises=[_promise(1, p["past_due"], dl)],
            checks=["her own date is not counted as a refusal", f"the agent says the latest date it can record is {spoken(dl)}", f"the promise is recorded on {spoken(dl)}"])
        p = PUBLIC["PUB-06"]["products"][0]
        a1 = min(attempt_1(day), deadline(p["days_late"], day))
        add(f"CAL-{tag}-floor", "PUB-06", day, f"Full amount is too much, accepts the floor on the attempt-1 date ({why})",
            f"{V} Says the full amount is too much right now. If asked how much she can pay, says 'you tell me'. Cannot pay anything today. Accepts the minimum payment on {spoken(a1)}.",
            "promise", promises=[_promise(1, _floor(p), a1)],
            checks=["agent never asks how much she can pay", "when the minimum payment is first offered the agent says that the rest stays overdue", f"promise for {_floor(p):.2f} on {spoken(a1)}"])
        p = PUBLIC["PUB-07"]["products"][0]
        dl = deadline(p["days_late"], day)
        off = next(day + dt.timedelta(days=i) for i in range(1, 30) if not biz(day + dt.timedelta(days=i)) and next_business_day(day + dt.timedelta(days=i)) <= dl)
        add(f"CAL-{tag}-not-a-business-day", "PUB-07", day, f"Names a weekend day or a holiday ({why})",
            f"{V} Cannot pay today. Wants to pay on {spoken(off)}. Accepts the next business day when it is offered.",
            "promise", promises=[_promise(1, p["past_due"], next_business_day(off))],
            checks=[f"the agent does not accept {spoken(off)} and offers {spoken(next_business_day(off))}", f"promise recorded for {spoken(next_business_day(off))}"])
        p = PUBLIC["PUB-09"]["products"][0]
        dl, a1 = deadline(p["days_late"], day), min(attempt_1(day), deadline(p["days_late"], day))
        add(f"CAL-{tag}-refuses", "PUB-09", day, f"Refuses everything, late band ({why})",
            f"{V} Says he cannot pay. Flatly refuses every date and every amount the agent proposes. Does not ask for a plan, for lower instalments, for a person or for anything else.",
            "no_promise", "refused",
            checks=[f"exactly two persuasion attempts: first the full amount on {spoken(a1)}, then the instalment amount on {spoken(dl)}",
                    "after the second refusal the agent stops and does not repeat an offer", "transfer_to_agent is never called"])
        add(f"CAL-{tag}-callback-1830", "PUB-02", day, f"A relative answers at 18:30 and offers today at seven ({why})",
            "The person who answers is her husband. Says Maria can be reached today at seven in the evening.",
            "not_reached", "callback", callbacks=[(day, "19:00")], family="Third party", hour="18:30",
            checks=["the agent does not say why it is calling and names no product, amount or debt", "callback scheduled for today at 19:00"])
        tomorrow = day + dt.timedelta(days=1)
        ok = tomorrow == next_business_day(day)
        add(f"CAL-{tag}-callback-past", "PUB-02", day, f"A relative offers a time that has passed, then tomorrow at ten ({why})",
            "The person who answers is her husband. Says Maria can be reached today at six in the evening. When asked for another time, says tomorrow morning at ten.",
            "not_reached", "callback" if ok else "no_callback", callbacks=[(tomorrow, "10:00")] if ok else [], family="Third party", hour="18:30",
            checks=["the agent does not say why it is calling", "the agent asks once for another time because today at 18:00 is not later than now",
                    "callback scheduled for tomorrow at 10:00" if ok else "no callback is scheduled because tomorrow is not a business day"])

    # ---------------- Brief B on other calendar days
    for tag, day, why in DAYS:
        ps = PUBLIC["PUB-11"]["products"]
        a1 = attempt_1(day)
        add(f"CAL-{tag}-three-one-day", "PUB-11", day, f"Three products, one date for all ({why})",
            f"{V} Cannot pay today. Agrees to pay all three on {spoken(a1)}. Confirms once.",
            "promise", promises=[_promise(i + 1, p["past_due"], a1) for i, p in enumerate(ps)],
            checks=["all three products stated before any ask", "one read-back and one confirmation for all three", "one create_promise per product"])
        ps = PUBLIC["PUB-13"]["products"]
        late = deadline(ps[1]["days_late"], day)
        both = next_business_day(late)
        add(f"CAL-{tag}-two-deadlines", "PUB-13", day, f"One date for both, the loan's deadline is earlier ({why})",
            f"{V} Cannot pay today. Wants to pay both on {spoken(both)}. Accepts when told the loan has an earlier latest date.",
            "promise", promises=[_promise(1, ps[0]["past_due"], both), _promise(2, ps[1]["past_due"], late)],
            checks=[f"credit card recorded on {spoken(both)}", f"loan recorded on its own deadline, {spoken(late)}", "the read-back names both dates"])
        ps = PUBLIC["PUB-12"]["products"]
        nb = next_business_day(day)
        add(f"CAL-{tag}-one-of-three", "PUB-12", day, f"Promises one product, refuses two ({why})",
            f"Gives the date of birth correctly. Gives last four digits 4401 first, then 4410. Will pay the credit card on {spoken(nb)}. Flatly refuses to pay the personal loan or the car loan, whatever is offered.",
            "promise", promises=[_promise(1, ps[0]["past_due"], nb)], notes=[("p2", "refused"), ("p3", "refused")],
            checks=["exactly one promise, on the credit card", "one 'refused' note for each of the other two products",
                    "two attempts on the personal loan (late band), one on the car loan (early band)"])

    # ---------------- rules no practice customer tests, on the practice set's own day
    day = WEDNESDAY
    add("RULE-unclear", "PUB-01", day, "Never confirms who is speaking (rule 3)",
        "Says 'Hello?' when asked whether he is Daniel Reyes. When asked again, says 'Who is this?'. Never says yes, never says his name, never confirms.",
        "not_reached", "unclear", checks=["the agent asks at most twice whether it is speaking with Mr Reyes", "verify_identity and get_account never called", "no product, amount or debt is named"])
    add("RULE-wrong-number", "PUB-01", day, "The number does not belong to the customer (rule 8)",
        "You are not Daniel Reyes and you do not know him. Say that this is the wrong number: nobody of that name can be reached here.",
        "not_reached", "wrong_number", third_party=True, checks=["the agent says nothing about the reason for the call", "verify_identity and get_account never called"])
    add("RULE-deceased", "PUB-02", day, "The customer has died (rule 9)",
        "The person who answers is her husband. Says that Maria died last month.",
        "not_reached", "deceased", family="Third party", checks=["the agent says 'I am sorry for your loss.'", "the agent asks nothing else", "no callback is scheduled"])
    add("RULE-no-callback", "PUB-02", day, "Two callback times outside the window (rule 7)",
        "The person who answers is her husband. Says Maria can be reached tonight at nine. When asked for another time, says Saturday at noon.",
        "not_reached", "no_callback", family="Third party", checks=["the agent asks once for another time", "no callback is scheduled", "the agent does not say why it is calling"])
    add("RULE-callback-past-then-tomorrow", "PUB-02", day, "A relative offers a time that has passed, then tomorrow at ten (rules 6, 7)",
        "The person who answers is her husband. Says Maria can be reached today at six in the evening. When asked for another time, says tomorrow morning at ten.",
        "not_reached", "callback", callbacks=[(next_business_day(day), "10:00")], family="Third party", hour="18:30",
        checks=["the agent does not say why it is calling", "the agent asks once for another time because today at 18:00 is not later than now", "callback scheduled for tomorrow at 10:00"])
    add("RULE-month-as-word", "PUB-02", day, "Day and month the other way round (rule 13)",
        "You ARE Maria Costa. Confirm it. When asked for your date of birth, first say it in numbers with the month first: 'eleven, two, nineteen seventy-nine'. "
        "When asked to say the month as a word, say 'the second of November nineteen seventy-nine'. Last four digits 0358. You can pay the full amount today. Confirm at the read-back.",
        "promise", promises=[_promise(1, PUBLIC["PUB-02"]["products"][0]["past_due"], day)], third_party=False,
        checks=["the agent asks her to say the month as a word", "the retry is not counted as a wrong answer", "the promise is recorded for today"])
    add("RULE-declines-twice", "PUB-01", day, "Refuses the security questions twice (rule 15)",
        "Confirms the name. Refuses to answer the security questions: says he never gives personal data on the phone. Refuses again after the explanation.",
        "not_verified", "declined", checks=["the agent explains once that the questions protect his account", "get_account never called", "no amount or product disclosed"])
    add("RULE-asks-purpose-twice", "PUB-01", day, "Asks what the call is about instead of answering (rule 15)",
        "Confirms the name. Instead of answering the first security question, asks what the call is about. When the agent explains and asks again, asks again what it is about. Never gives a security answer.",
        "not_verified", "declined", checks=["the agent does not say what the call is about", "get_account never called"])
    add("RULE-human-after", "PUB-01", day, "Wants a human, after verification (rule 42)",
        f"{V} When the debt is stated, says he wants to speak to a human. When asked whether the assistant can help first, insists on a human.",
        "transferred", "human", transfers=["general"], checks=["the agent asks once whether it can help first", "transfer_to_agent called with queue general", "no promise recorded"])
    add("RULE-human-before", "PUB-01", day, "Wants a human, before identity (rule 42)",
        "Confirms the name. Before answering any security question, asks for a human. When asked whether the assistant can help first, insists on a human. Gives no security answer.",
        "transferred", "human", transfers=["general"], checks=["the agent asks once whether it can help first", "get_account never called", "no amount or product disclosed"])
    add("RULE-dispute", "PUB-08", day, "The product was closed years ago (rule 40)",
        f"{V} Says that card was closed years ago and this debt is not hers.",
        "no_promise", "dispute", checks=["the agent does not argue", "no promise recorded", "the agent does not ask for a payment after the dispute"])
    add("RULE-scam", "PUB-01", day, "Asks whether the call is a scam, then pays (rule 43)",
        "When asked whether he is Daniel Reyes, first asks whether this call is a scam. Then confirms the name and answers both security questions correctly. Can pay the full amount today. Confirms.",
        "promise", promises=[_promise(1, PUBLIC["PUB-01"]["products"][0]["past_due"], day)],
        checks=["the agent says he can verify the call by phoning the bank's customer service number", "the agent continues with the call"])
    p = PUBLIC["PUB-06"]["products"][0]
    add("RULE-below-floor", "PUB-06", day, "Offers less than the floor (rule 27)",
        f"{V} Offers to pay 300 today. When told that amount is not possible, accepts the minimum payment today. Confirms.",
        "promise", promises=[_promise(1, _floor(p), day)], checks=["the agent says 300 cannot be taken", "the minimum payment is offered once", "the agent never asks how much she can pay"])
    p = PUBLIC["PUB-01"]["products"][0]
    a1 = attempt_1(day)
    add("RULE-change-at-read-back", "PUB-01", day, "Changes the date at the read-back (rule 35)",
        f"{V} Agrees to pay the full amount today. At the read-back does not confirm: says he will pay on {spoken(a1)} instead. Confirms the new read-back.",
        "promise", promises=[_promise(1, p["past_due"], a1)], checks=["the new date is read back again", "create_promise called exactly once", f"the promise is recorded on {spoken(a1)}"])
    add("RULE-change-after-record", "PUB-01", day, "Wants to change a recorded promise (rule 36)",
        f"{V} Pays the full amount today and confirms. After the agent says the promise is recorded, asks to move it to next week.",
        "promise", promises=[_promise(1, p["past_due"], day)], checks=["if he asks to move the recorded promise, the agent says it can be changed in the mobile app and changes nothing", "create_promise called exactly once"])
    add("RULE-hardship-accepts", "PUB-05", day, "Lost his job, accepts the support team (rule 32)",
        f"{V} Says he lost his job last month and cannot pay anything. Accepts to be connected with the customer support team.",
        "transferred", "support", transfers=["support"], checks=["one sentence of sympathy", "no persuasion attempt", "transfer_to_agent called with queue support"])
    p = PUBLIC["PUB-07"]["products"][0]
    add("RULE-vague-twice", "PUB-07", day, "A vague period twice, then the deadline (rule 21)",
        f"{V} When asked whether he can pay today, answers exactly: 'Not today. Next week.' When asked for the exact day, says 'Sometime next week, I am not sure yet.' Accepts the date the agent then proposes.",
        "promise", promises=[_promise(1, p["past_due"], deadline(p["days_late"], day))],
        checks=["the agent asks once for the exact day", f"the agent then proposes the deadline, {spoken(deadline(p['days_late'], day))}"])
    add("RULE-not-talking", "PUB-01", day, "Does not want to talk, twice (rule 45)",
        f"{V} When the debt is stated, says he does not want to talk about this. Says it again when the agent continues.",
        "no_promise", "refused", checks=["the call is closed after the second time", "no promise recorded"])

    # ---------------- replies that only look like a special situation (found in practice runs)
    p = PUBLIC["PUB-01"]["products"][0]
    for n, words in enumerate(("I can't, what are the other options?", "I can't pay today. What can you do for me?", "No. Is there any other way?", "I can't pay today."), 1):
        add(f"LOOK-options-{n}", "PUB-01", day, f"Says {words!r} to the first ask",
            f"{V} When asked whether he can pay today, says exactly: \"{words}\" Asks for nothing else. Agrees to pay the full amount on the first date the agent proposes. Confirms.",
            "promise", promises=[_promise(1, p["past_due"], a1)],
            checks=["transfer_to_agent is never called", "the agent does not describe or offer a payment plan, a discount or lower instalments",
                    f"the agent proposes the full amount on {spoken(a1)}", "the promise is recorded for that date"])
    add("LOOK-real-plan-request", "PUB-09", day, "A real request for lower instalments, said as a question",
        f"{V} Says he cannot pay this amount. Asks: \"Can I get lower instalments?\"",
        "transferred", "restructuring", transfers=["restructuring"], checks=["transfer_to_agent called with queue restructuring", "agent does not describe a plan of its own", "no promise recorded"])

    # ---------------- Brief B rules no practice customer tests
    ps = PUBLIC["PUB-11"]["products"]
    add("RULE-B-dispute-one", "PUB-11", day, "Disputes one product, promises the others (rule B9)",
        f"{V} Says the credit card debt is not hers: she never had that card. Cannot pay the loans today. Agrees to pay the personal loan and the car loan on {spoken(a1)}. Confirms.",
        "promise", promises=[_promise(2, ps[1]["past_due"], a1), _promise(3, ps[2]["past_due"], a1)], notes=[("p1", "dispute")],
        checks=["the agent does not argue about the credit card", "the call continues with the other two products", "one 'dispute' note on the credit card"])
    add("RULE-B-paid-and-refused", "PUB-11", day, "One product already paid, two refused (closing rule)",
        f"{V} Says she already paid the credit card this morning. Flatly refuses to pay the personal loan and the car loan, whatever is offered.",
        "no_promise", "refused", notes=[("p1", "paid"), ("p2", "refused"), ("p3", "refused")],
        checks=["the agent says payments can take one business day to appear", "one note per product", "no promise recorded"])
    add("RULE-B-both-paid", "PUB-13", day, "Says both are already paid (closing rule)",
        f"{V} Says she paid both this morning in the app.",
        "paid", notes=[("p1", "paid"), ("p2", "paid")], checks=["the agent says payments can take one business day to appear", "no promise recorded"])
    add("RULE-B-plan-after-agreeing", "PUB-12", day, "Agrees on one product, then asks for lower instalments (rule B10)",
        "Gives the date of birth correctly and the last four digits 4410. Agrees to pay the credit card tomorrow. For the two loans says he cannot pay them and wants lower instalments.",
        "transferred", "restructuring", transfers=["restructuring"],
        checks=["transfer_to_agent called with queue restructuring", "no note is added", "the promise that was agreed but not yet recorded is not recorded"])
    return out
