"""Customers of mock brief F: the kit's Brief A and B with twelve rules changed (see ../make.py, F_CHANGES_A).

F keeps the kit's tool API, so its customers can be simulated on the platform: each one borrows a practice
customer's account and security answers (`base`), like dev/scenarios.py does, and carries a persona text (`script`)
and the judge's criteria (`checks`). Run them with dev/run_mock_briefs.py --simulate <agent_id>, against an agent
that was BUILT FROM THE TWO DOCUMENTS OF THIS PACK, never against a Brief A/B agent.
Every expected record is worked out from the changed documents with lib.Cal.
"""
import datetime as dt, json
from lib import KIT, MO, ONE, Customer, case, day, spoken, verified

PUBLIC = {c["id"]: c for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}
NOW = "2026-10-14T11:00"                                    # the practice set's Wednesday; Thursday 15 and Monday 19 are holidays here
OK = "Confirms the name and answers both security questions correctly."


def cases(P):
    cal, out = P.cal, []
    T = day(NOW)

    def C(cid, base, title, family, steps, outcome, reason=None, now=NOW, **kw):
        b = PUBLIC[base]
        v = {k: x for k, x in b["variables"].items() if k != "now"}
        out.append(case("F-" + cid, title, family, now, steps, outcome, reason, variables=v, identity=b["identity"], products=b["products"], base=base, **kw))

    V = lambda base: verified(P, PUBLIC[base]["identity"])
    prod = lambda base, i=0: PUBLIC[base]["products"][i]
    floor = lambda p: p.get("minimum_payment", p.get("instalment_amount"))
    dl = lambda p, today=T: cal.deadline(p["days_late"], today)
    lad = lambda p, today=T, tm=False: cal.ladder(p["days_late"], today, p["past_due"], floor(p), tm)
    nb = cal.next_biz(T)                                    # Friday 16 October: Thursday is a holiday

    C("01", "PUB-01", "Pays the full amount today", "Happy path", V("PUB-01") + [("neg", Customer("accept"))], "promise", promises=[("p1", 420.0, T)],
      said=["Could you pay this amount today?", "Is that right?", "We will send you an e-mail to confirm this promise."],
      script=f"{OK} Says he can pay the full amount today. Confirms at the read-back.",
      checks=["both security questions passed before get_account", "the agent asks whether he can pay this amount today", "create_promise called exactly once",
              "after the promise the agent says that an e-mail will confirm it"])
    C("02", "PUB-01", "Never confirms who is speaking", "Opening", [("who", ""), ("who", "")], "not_reached", "no_confirmation", calls={"verify_identity": 0, "get_account": 0},
      modes=("orch", "v1"), script="Says 'Hello?' when asked whether he is Daniel Reyes. When asked again, says 'Who is this?'. Never says yes, never says his name, never confirms.",
      checks=["the agent asks at most twice whether it is speaking with Mr Reyes", "verify_identity and get_account never called", "no product, amount or debt is named"])
    C("03", "PUB-02", "A relative offers tomorrow, a holiday, then Friday", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at eleven"}), ("tp", {"cb_when_text": "Friday at eleven"})], "not_reached", "callback",
      callbacks=[(nb, "11:00")], modes=("orch", "v1"),
      script="The person who answers is her husband. Says Maria can be reached tomorrow at eleven. When asked for another time, says Friday at eleven in the morning.",
      checks=["the agent does not say why it is calling and names no product, amount or debt", "the agent does not accept tomorrow, because it is a bank holiday, and asks once for another time",
              "callback scheduled for Friday 16 October at 11:00"])
    C("04", "PUB-02", "A relative offers today twice: today is never possible", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "today at three in the afternoon"}), ("tp", {"cb_when_text": "today at five"})], "not_reached", "no_callback",
      calls={"schedule_callback": 0}, modes=("orch", "v1"),
      script="The person who answers is her husband. Says Maria can be reached today at three in the afternoon. When asked for another time, says today at five.",
      checks=["the agent asks once for another time", "no callback is scheduled", "the agent does not say why it is calling"])
    C("05", "PUB-02", "A relative offers Friday at six: after the window", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "Friday at six in the evening"}), ("tp", {"cb_when_text": "Friday at five in the afternoon"})], "not_reached", "callback",
      callbacks=[(nb, "17:00")], modes=("orch", "v1"),
      script="The person who answers is her husband. Says Maria can be reached on Friday at six in the evening. When asked for another time, says Friday at five in the afternoon.",
      checks=["the agent asks once for another time because 18:00 is outside the callback hours", "callback scheduled for Friday 16 October at 17:00"])
    p = prod("PUB-04")
    C("06", "PUB-04", "Wants a date after the deadline, accepts the deadline", "Dates",
      V("PUB-04") + [("neg", Customer({"kind": "propose", "day": "the 6th of November", "said": "My salary comes on the 6th of November, I can pay then."}, then=["accept"]))],
      "promise", promises=[("p1", p["past_due"], dl(p))], offered=[(p["past_due"], dl(p))],
      script=f"{OK} Says her salary arrives on 6 November and she can pay then. Accepts the latest possible date when it is offered. Confirms.",
      checks=["her own date is not counted as a refusal", f"the agent says the latest date it can record is {spoken(dl(p))}", f"the promise is recorded on {spoken(dl(p))}"])
    p = prod("PUB-07")
    C("07", "PUB-07", "Wants to pay tomorrow, a holiday: the next business day is offered", "Dates",
      V("PUB-07") + [("neg", Customer({"kind": "propose", "day": "tomorrow", "said": "I can pay tomorrow."}, then=["accept"]))], "promise", promises=[("p1", p["past_due"], nb)],
      script=f"{OK} Cannot pay today. Wants to pay tomorrow. Accepts the next business day when it is offered. Confirms.",
      checks=[f"the agent does not accept tomorrow, because it is a bank holiday, and offers {spoken(nb)}", f"promise recorded for {spoken(nb)}"])
    tue = day("2026-10-20")
    C("08", "PUB-07", "'Next Monday' is the first Monday that comes, a holiday: Tuesday is offered", "Dates",
      V("PUB-07") + [("neg", Customer({"kind": "propose", "day": "next Monday", "said": "I can pay next Monday."}, then=["accept"]))], "promise", promises=[("p1", p["past_due"], tue)],
      script=f"{OK} Cannot pay today. Says he can pay next Monday. Accepts the day the agent offers instead. Confirms.",
      checks=["the agent reads 'next Monday' as Monday 19 October", f"the agent says that day is not possible and offers {spoken(tue)}", f"promise recorded for {spoken(tue)}"])
    a1 = lad(p)[0]
    C("09", "PUB-07", "A vague period three times: asked twice for the exact day, then it counts as a refusal", "Dates",
      V("PUB-07") + [("neg", Customer({"kind": "vague", "day": "next week", "said": "Not today. Next week."},
                                      then=[{"kind": "vague", "day": "sometime next week", "said": "Sometime next week."}, {"kind": "vague", "day": "when my salary comes", "said": "When my salary comes."}, "accept"]))],
      "promise", promises=[("p1", p["past_due"], a1[1])], offered=[a1],
      script=f"{OK} When asked whether he can pay today, answers exactly: 'Not today. Next week.' When asked for the exact day, says 'Sometime next week.' "
             "When asked again, says 'When my salary comes.' Agrees to the date the agent then proposes. Confirms.",
      checks=["the agent asks for the exact day twice", f"the agent then proposes the full amount on {spoken(a1[1])}", "the promise is recorded for that date"])
    p = prod("PUB-06")
    C("10", "PUB-06", "The full amount is too much, not today either: the minimum on the next business day", "Amounts",
      V("PUB-06") + [("neg", Customer("too_much", then=["refuse", "accept"]))], "promise", promises=[("p1", floor(p), nb)],
      script=f"{OK} Says the full amount is too much right now. If asked how much she can pay, says 'you tell me'. Says she cannot pay the minimum payment today either. "
             f"Accepts the minimum payment on {spoken(nb)}. Confirms.",
      checks=["agent never asks how much she can pay", "when the minimum payment is first offered the agent says that the rest stays overdue", f"promise for {floor(p):.2f} on {spoken(nb)}"])
    for cid, base, n in (("11", "PUB-03", 1), ("12", "PUB-01", 2), ("13", "PUB-09", 3)):
        p = prod(base)
        steps = lad(p)
        said = "; then ".join((f"the full amount ({a:.2f})" if i == 0 else f"the {'minimum payment' if p['type'] == 'credit_card' else 'instalment amount'} ({a:.2f})") + f" on {spoken(d)}"
                              for i, (a, d) in enumerate(steps))
        ident = OK
        C(cid, base, f"Refuses everything: {n} persuasion attempt(s) for {p['days_late']} days late", "Refusals", V(base) + [("neg", Customer("refuse", then=["refuse"]))],
          "no_promise", "refused", notes=[("p1", "refused")], offered=steps, calls={"create_promise": 0, "transfer_to_agent": 0},
          script=f"{ident} Says no to paying today. Flatly refuses every date and every amount the agent proposes. Does not ask for a plan, for lower instalments, for a person or for anything else.",
          checks=[f"exactly {n} persuasion attempt(s): {said}", "after the last refusal the agent stops and does not repeat an offer", "transfer_to_agent is never called",
                  "one 'refused' note for the product"])
    C("14", "PUB-01", "Asks for a human: transferred at once", "Situations", V("PUB-01") + [("neg", Customer({"kind": "human", "said": "I want to speak to a human."}))],
      "transferred", "human", transfers=["general"], calls={"create_promise": 0, "add_note": 0},
      script=f"{OK} When the debt is stated, says he wants to speak to a human.",
      checks=["the agent does not ask whether it can help first", "transfer_to_agent called with queue general", "no promise recorded and no note added"])
    C("15", "PUB-10", "create_promise fails once: the second of three tries records it", "Recording", V("PUB-10") + [("neg", Customer("accept"))], "promise",
      promises=[("p1", prod("PUB-10")["past_due"], T)], faults={"create_promise": 1}, calls={"create_promise": 2},
      script=f"{OK} Can pay the full amount today. Confirms at the read-back.",
      checks=["the agent does not say the promise is recorded before a create_promise call succeeded", "the promise is recorded after the retry", "the e-mail sentence is said after the promise"])
    C("16", "PUB-08", "Says it is already paid", "Situations", V("PUB-08") + [("neg", Customer({"kind": "already_paid", "said": "I paid that this morning."}))], "paid",
      notes=[("p1", "paid")], said=["Payments can take two business days to show."], calls={"create_promise": 0},
      script=f"{OK} Says she already paid this amount this morning in the app.",
      checks=["the agent says payments can take two business days to show", "no promise recorded", "one 'paid' note for the product"])
    C("17", "PUB-05", "Lost his job, declines the support team", "Hardship",
      V("PUB-05") + [("neg", Customer({"kind": "hardship", "said": "I lost my job last month, I cannot pay anything."}, offer="decline"))], "no_promise", "hardship",
      notes=[("p1", "hardship")], calls={"transfer_to_agent": 0},
      script=f"{OK} Says he lost his job last month and cannot pay anything. Does not want to be connected to anybody.",
      checks=["one sentence of sympathy", "no persuasion attempt", "transfer_to_agent is never called", "one 'hardship' note for the product"])
    C("18", "PUB-09", "A real request for lower instalments", "Situations",
      V("PUB-09") + [("neg", Customer({"kind": "restructuring", "said": "I cannot pay this amount. Can I get lower instalments?"}))], "transferred", "restructuring",
      transfers=["restructuring"], calls={"create_promise": 0, "add_note": 0},
      script=f"{OK} Says he cannot pay this amount. Asks: \"Can I get lower instalments?\"",
      checks=["transfer_to_agent called with queue restructuring", "agent does not describe a plan of its own", "no promise recorded and no note added"])
    ps = PUBLIC["PUB-11"]["products"]
    C("20", "PUB-11", "Three products, one day for all of them", "Several products",
      V("PUB-11") + [("neg", Customer({"kind": "propose", "day": "this Friday", "about": "all of them", "said": "All three this Friday."}))], "promise",
      promises=[(f"p{i + 1}", x["past_due"], nb) for i, x in enumerate(ps)], calls={"create_promise": 3},
      script=f"{OK} Cannot pay today. Agrees to pay all three this Friday. Confirms once.",
      checks=["all three products stated before any ask", "one read-back and one confirmation for all three", "one create_promise per product"])
    ps = PUBLIC["PUB-13"]["products"]
    both = day("2026-10-27")
    C("21", "PUB-13", "One day for both, after the loan's deadline", "Several products",
      V("PUB-13") + [("neg", Customer({"kind": "propose", "day": "the 27th of October", "about": "both", "said": "Both on the 27th of October."}))], "promise",
      promises=[("p1", ps[0]["past_due"], both), ("p2", ps[1]["past_due"], dl(ps[1]))], said=["latest date"],
      script=f"{OK} Cannot pay today. Wants to pay both on {spoken(both)}. Accepts when told the loan has an earlier latest date. Confirms.",
      checks=[f"credit card recorded on {spoken(both)}", f"loan recorded on its own deadline, {spoken(dl(ps[1]))}", "the read-back names both dates"])
    ps = PUBLIC["PUB-12"]["products"]
    C("22", "PUB-12", "Promises the card, refuses both loans: two attempts each", "Several products",
      V("PUB-12") + [("neg", Customer({"kind": "propose", "day": "Friday", "about": "the credit card", "said": "The credit card on Friday."}, then=["refuse"]))], "promise",
      promises=[("p1", ps[0]["past_due"], nb)], notes=[("p2", "refused"), ("p3", "refused")], offered=lad(ps[1]) + lad(ps[2]),
      script=f"Gives the date of birth correctly and the last four digits 4410. Will pay the credit card on {spoken(nb)}. Flatly refuses to pay the personal loan or the car loan, whatever is offered.",
      checks=["exactly one promise, on the credit card", "one 'refused' note for each of the other two products", "two attempts on the personal loan and two on the car loan"])
    # ---- another calendar day: the Friday after the holiday, with a holiday on the Monday that follows
    fri = day("2026-10-16")
    p = prod("PUB-01")
    a1 = lad(p, fri)[0]
    C("30", "PUB-01", "On Friday 16 October: cannot today, takes the first date offered", "Dates", V("PUB-01") + [("neg", Customer("refuse", then=["accept"]))], "promise",
      promises=[("p1", p["past_due"], a1[1])], offered=[a1], now="2026-10-16T11:00",
      script=f"{OK} Says he cannot pay today. Proposes no date himself. Agrees to pay the full amount on the first date the agent proposes. Confirms at the read-back.",
      checks=[f"the first date the agent proposes is {spoken(a1[1])}", "the agent never asks how much he can pay", "create_promise called exactly once"])
    p = prod("PUB-09")
    steps = lad(p, fri)
    C("31", "PUB-09", "On Friday 16 October: the late band refuses everything", "Refusals", V("PUB-09") + [("neg", Customer("refuse", then=["refuse"]))], "no_promise", "refused",
      notes=[("p1", "refused")], offered=steps, now="2026-10-16T11:00",
      script=f"{OK} Says no to paying today. Flatly refuses every date and every amount the agent proposes. Does not ask for a plan, for lower instalments, for a person or for anything else.",
      checks=["exactly three persuasion attempts: " + "; then ".join(f"{a:.2f} on {spoken(d)}" for a, d in steps), "transfer_to_agent is never called"])
    return out
