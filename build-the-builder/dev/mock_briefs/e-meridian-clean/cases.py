"""Customers of mock brief E (Meridian Business Bank). Every expected record is worked out from brief.md with
lib.Cal, the day-by-day calendar that does not use the builder's date code. Rule numbers are the brief's.

The call's time is given as the brief's example shows it: with a space, not a T.
"""
import datetime as dt
from lib import MO, ONE, Customer, case, day, spoken, verified

BRANDT = {"variables": {"company_name": "Tidewater Joinery Ltd", "contact_first_name": "Helen", "contact_last_name": "Brandt"},
          "identity": {"company_number": "08123456", "founded_year": "2005"}}
LOAN_S = {"facility_id": "f1", "facility_type": "business_loan", "overdue_amount": 5400.0, "days_overdue": 9, "minimum_due": 1350.0}                 # standard
LEASE_P = {"facility_id": "f1", "facility_type": "equipment_lease", "agreement_no": "EL-2207", "overdue_amount": 1980.0, "days_overdue": 33, "lease_rental": 660.0}   # priority
CARD_X = {"facility_id": "f1", "facility_type": "company_card", "card_suffix": "5512", "overdue_amount": 730.5, "days_overdue": 75, "minimum_due": 219.15}   # escalated
ODD_S = {"facility_id": "f1", "facility_type": "overdraft", "overdue_amount": 425.25, "days_overdue": 12, "minimum_due": 100.0}                      # half is 212.625
THREE = [LOAN_S, dict(LEASE_P, facility_id="f2"), dict(CARD_X, facility_id="f3")]
TWO = [LOAN_S, dict(LEASE_P, facility_id="f2")]
NOW = "2026-10-14 11:00"                                    # a Wednesday
DAYS = [("wed", "2026-10-14", "a Wednesday"), ("sat", "2026-10-17", "a Saturday: a business day here, and the week's last"),
        ("hol", "2026-10-28", "the day before a holiday, three days before the month ends"), ("month", "2026-10-31", "the last business day of the month"),
        ("fri13", "2026-11-13", "a Friday before a Saturday holiday"), ("xmas", "2026-12-24", "the day before two holidays and a Sunday")]


def said_day(d):
    return f"{d.day} {MO[d.month - 1]}"


def cases(P):
    cal, out = P.cal, []
    T = day(NOW)
    V = verified(P, BRANDT["identity"])

    def C(cid, title, family, steps, outcome, reason=None, products=(LOAN_S,), now=NOW, **kw):
        out.append(case("E-" + cid, title, family, now, steps, outcome, reason, variables=BRANDT["variables"], identity=BRANDT["identity"], products=products, **kw))

    full = lambda p: p["overdue_amount"]
    floor = lambda p: p.get("lease_rental", p.get("minimum_due"))
    dl = lambda p, today=T: cal.deadline(p["days_overdue"], today)
    lad = lambda p, today=T, tm=False: cal.ladder(p["days_overdue"], today, full(p), floor(p), tm)

    # ------------------------------------------------------------ the simplest call
    C("01", "Confirms, passes verification and settles in full today", "Happy path", V + [("neg", Customer("accept"))], "agreed", promises=[("f1", 5400.0, T)],
      said=["Hello, this is the virtual assistant of Meridian Business Bank.", "May I speak with Helen Brandt of Tidewater Joinery Ltd?", "Can the company settle this today?",
            "Is that correct?", "You will receive an e-mail confirming this arrangement.", "Thank you for your time. Goodbye."],
      calls={"verify_identity": 2, "get_account": 1, "create_promise": 1, "add_note": 0})

    # ------------------------------------------------------------ who is on the line (rules 3, 4, 7 to 10)
    C("02", "Never confirms: two asks, then closed", "Opening", [("who", ""), ("who", "")], "no_contact", "unconfirmed", calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
    C("03", "A colleague answers: callback today at four", "Third party", [("who", "someone_else"), ("tp", {"cb_when_text": "today at four in the afternoon"})],
      "no_contact", "callback_booked", callbacks=[(T, "16:00")], calls={"verify_identity": 0}, modes=("orch", "v1"))
    C("04", "18:00 itself cannot be booked; 17:45 can", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "today at six in the evening"}), ("tp", {"cb_when_text": "today at a quarter to six"})],
      "no_contact", "callback_booked", callbacks=[(T, "17:45")], modes=("orch", "v1"))
    C("05", "08:00 itself cannot be booked, and a second time that does not fit ends it", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at eight in the morning"}), ("tp", {"cb_when_text": "tomorrow at seven in the morning"})],
      "no_contact", "callback_refused", calls={"schedule_callback": 0}, modes=("orch", "v1"))
    C("06", "A time earlier today has passed; Saturday is a business day and can be booked", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "today at ten"}), ("tp", {"cb_when_text": "Saturday at ten"})],
      "no_contact", "callback_booked", callbacks=[(day("2026-10-17"), "10:00")], modes=("orch", "v1"))
    C("07", "The fourth business day from today is too far", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "next Monday at ten"}), ("tp", {"cb_when_text": "Saturday at ten"})],
      "no_contact", "callback_booked", callbacks=[(day("2026-10-17"), "10:00")], modes=("orch", "v1"),
      note="from Wednesday 14 October the next three business days are Thursday, Friday and Saturday")
    C("08", "A holiday is skipped when the three business days are counted", "Third party", [("who", "someone_else"), ("tp", {"cb_when_text": "Saturday at nine"})],
      "no_contact", "callback_booked", callbacks=[(day("2026-10-31"), "09:00")], now="2026-10-28 15:00", modes=("orch", "v1"),
      note="from Wednesday 28 October: Thursday 29 is a holiday, so the three days are Friday 30, Saturday 31 and Monday 2 November")
    C("09", "Sunday is not a business day here either", "Third party", [("who", "someone_else"), ("tp", {"cb_when_text": "Sunday at ten"}), ("tp", {"cb_when_text": "Sunday at noon"})],
      "no_contact", "callback_refused", calls={"schedule_callback": 0}, modes=("orch", "v1"))
    C("10", "The contact has left the company", "Third party", [("who", "someone_else"), ("tp", {"tp_event": "contact_left"})], "no_contact", "contact_left",
      calls={"verify_identity": 0, "schedule_callback": 0}, modes=("orch", "v1"))
    C("11", "The company has stopped trading", "Third party", [("who", "ceased_trading")], "no_contact", "ceased_trading", modes=("orch", "v1"))

    # ------------------------------------------------------------ verification (rules 12 to 15)
    pay = [("neg", Customer("accept"))]
    C("12", "The registration number keeps its leading zero; the year in words", "Identity",
      [("who", "confirmed"), ("id", "company_number", "zero eight one two three four five six", "08123456"), ("id", "founded_year", "two thousand and five", "2005")] + pay,
      "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"))
    C("13", "The number with spaces and dashes, the year as 'twenty oh five'", "Identity",
      [("who", "confirmed"), ("id", "company_number", "08 123-456", "08123456"), ("id", "founded_year", "twenty oh five", "2005")] + pay,
      "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"), tier=2)
    C("14", "The number in two parts, as the pieces style does", "Identity",
      [("who", "confirmed"), ("id", "company_number", "0812", "0812"), ("id", "company_number", "3456", "08123456"), ("id", "founded_year", "2005", "2005")] + pay,
      "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"), tier=2,
      note="the prompt asks the model to wait for the rest; if it calls with the first half anyway, the hook keeps it and joins the rest. The bank counts the half as one wrong answer, of three")
    C("15", "'Oh eight, double one...' style: 'double' and 'oh'", "Identity",
      [("who", "confirmed"), ("id", "company_number", "oh eight one two three four five six", "08123456"), ("id", "founded_year", "2005", "2005")] + pay,
      "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"))
    C("16", "Two wrong answers, then the right ones: the service does not count for the assistant", "Identity",
      [("who", "confirmed"), ("id", "company_number", "08123457", "08123457"), ("id", "company_number", "08123465", "08123465"),
       ("id", "company_number", "08123456", "08123456"), ("id", "founded_year", "2005", "2005")] + pay, "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"))
    C("17", "Three wrong answers end the verification, though the service never says so", "Identity",
      [("who", "confirmed"), ("id", "company_number", "08123457", "08123457"), ("id", "company_number", "08123456", "08123456"),
       ("id", "founded_year", "2004", "2004"), ("id", "founded_year", "2006", "2006")], "unverified", "wrong_answers",
      said=["I cannot verify the company, so I have to end this call."], not_said=["business loan", "5400"], calls={"get_account": 0}, modes=("orch", "v1"))
    C("18", "Declines once, is told why, answers", "Identity", [("who", "confirmed"), ("decline",)] + V[1:] + pay, "agreed", promises=[("f1", 5400.0, T)], modes=("orch", "v1"))
    C("19", "Declines twice", "Identity", [("who", "confirmed"), ("decline",), ("decline",)], "unverified", "declined_checks", calls={"verify_identity": 0, "get_account": 0},
      modes=("orch", "v1"))
    C("20", "Asks what the call is about: that is not declining", "Identity", [("who", "confirmed"), ("id_question",), ("id_question",)] + V[1:] + pay, "agreed",
      promises=[("f1", 5400.0, T)], modes=("orch", "v1"))
    C("21", "Asks for the relationship manager before verification and insists", "Situations", [("who", "confirmed"), ("go", "manager")], "escalated", "manager_request",
      transfers=["relationship_manager"], calls={"verify_identity": 0, "get_account": 0, "add_note": 0}, modes=("orch", "v1"))
    C("22", "Says twice, before verification, that they do not want to talk", "Situations", [("who", "confirmed"), ("go", "not_talking")], "unverified", "declined_checks",
      calls={"get_account": 0}, modes=("orch", "v1"))

    # ------------------------------------------------------------ dates and the persuasion attempts, on six calendar days
    for tag, iso, why in DAYS:
        today, now = day(iso), iso + " 11:00"
        s = lad(LOAN_S, today)
        C(f"30-{tag}", f"Standard band: cannot today, takes the first offer ({why})", "Dates", V + [("neg", Customer("refuse", then=["accept"]))], "agreed",
          promises=[("f1", 5400.0, s[0][1])], offered=[s[0]], now=now)
        C(f"31-{tag}", f"Standard band refuses everything: the full amount, then half of it on the deadline ({why})", "Refusals",
          V + [("neg", Customer("refuse", then=["refuse"]))], "no_agreement", "declined", offered=s, now=now, calls={"create_promise": 0, "add_note": 0})
        p = lad(LEASE_P, today)
        C(f"32-{tag}", f"Priority band refuses everything: its deadline is the month's last business day ({why})", "Refusals",
          V + [("neg", Customer("refuse", then=["refuse"]))], "no_agreement", "declined", products=[LEASE_P], offered=p, now=now, calls={"add_note": 0})
        late = dl(LEASE_P, today)
        C(f"33-{tag}", f"Priority band: a date after the deadline is refused, the deadline itself is then named by the contact ({why})", "Dates",
          V + [("neg", Customer({"kind": "propose", "day": said_day(late + dt.timedelta(days=9)), "said": "We can pay then."},
                                then=[{"kind": "propose", "day": said_day(late), "said": "Then on that day."}]))], "agreed", products=[LEASE_P],
          promises=[("f1", 1980.0, late)], now=now)
        C(f"34-{tag}", f"Escalated band: no persuasion attempt at all ({why})", "Refusals", V + [("neg", Customer("refuse", then=["refuse"]))], "no_agreement", "declined",
          products=[CARD_X], offered=[], now=now, calls={"add_note": 0})
    C("35", "A Sunday is a day a payment can have", "Dates", V + [("neg", Customer({"kind": "propose", "day": "Sunday", "said": "We will pay on Sunday."}))], "agreed",
      promises=[("f1", 5400.0, day("2026-10-18"))])
    C("36", "A holiday is a day a payment can have", "Dates", V + [("neg", Customer({"kind": "propose", "day": "the 29th of October", "said": "On the 29th."}))], "agreed",
      products=[LEASE_P], promises=[("f1", 1980.0, day("2026-10-29"))])
    C("37", "A vague period twice: asked once for the exact day, then it counts as a flat refusal", "Dates",
      V + [("neg", Customer({"kind": "vague", "day": "next week", "said": "Next week."}, then=[{"kind": "vague", "day": "when our client pays us", "said": "When our client pays us."}, "accept"]))],
      "agreed", promises=[("f1", 5400.0, lad(LOAN_S)[0][1])], offered=[lad(LOAN_S)[0]])
    C("38", "'Next Friday' said on a Wednesday is the Friday of the following week", "Dates", V + [("neg", Customer({"kind": "propose", "day": "next Friday"}))], "agreed",
      promises=[("f1", 5400.0, day("2026-10-23"))])
    C("39", "'This Friday' is the Friday of this week", "Dates", V + [("neg", Customer({"kind": "propose", "day": "this Friday"}))], "agreed", promises=[("f1", 5400.0, day("2026-10-16"))])
    C("40", "A date after the deadline is not counted as a refusal: no attempt is used, no day is named for the contact", "Dates",
      V + [("neg", Customer({"kind": "propose", "day": said_day(dl(LOAN_S) + dt.timedelta(days=5)), "said": "We can pay then."},
                            then=[{"kind": "propose", "day": said_day(dl(LOAN_S)), "said": "Then on that day."}]))], "agreed", promises=[("f1", 5400.0, dl(LOAN_S))], offered=[], tier=2,
      note="the SPEC's reject has one follow-up: say the day is not possible and repeat the open offer (dev/specs/imaginary-d.md, D13, asks for exactly that). This brief asks for the other one: ask which day suits. No field of the SPEC tells the two apart")

    # ------------------------------------------------------------ amounts (rules 24 to 27, 29)
    C("41", "The full amount is too much: the minimum once, with the sentence", "Amounts", V + [("neg", Customer("too_much", then=["accept"]))], "agreed",
      promises=[("f1", 1350.0, T)], once=["The balance that remains is still overdue."])
    C("42", "Too much, then no: attempt 1 is the minimum at the week's end, attempt 2 half of the amount on the deadline", "Amounts",
      V + [("neg", Customer("too_much", then=["refuse"]))], "no_agreement", "declined", offered=[(1350.0, T)] + lad(LOAN_S, T, True))
    C("43", "Below the minimum, then accepts the minimum", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "500", "day": "Friday", "said": "We can pay 500 on Friday."}, then=["accept"]))], "agreed",
      promises=[("f1", 1350.0, day("2026-10-16"))], said=["That is below the minimum we can accept."])
    C("44", "Half of an amount with an odd cent is rounded up (rule 29)", "Amounts", V + [("neg", Customer("refuse", then=["refuse", "accept"]))], "agreed", products=[ODD_S],
      promises=[("f1", 212.63, dl(ODD_S))], tier=2, note="half of 425.25 is 212.625; the brief says exactly half a cent is rounded up")
    C("45", "A lease uses its rental as the minimum", "Amounts", V + [("neg", Customer("too_much", then=["accept"]))], "agreed", products=[LEASE_P], promises=[("f1", 660.0, T)],
      said=["equipment lease EL-2207"])

    # ------------------------------------------------------------ recording (rule 37): no second try
    C("50", "create_promise fails: no second try, the contact is told", "Recording", V + [("neg", Customer("accept"))], "no_agreement", "system_error",
      notes=[("f1", "system_error")], faults={"create_promise": 1}, calls={"create_promise": 1}, said=["I am sorry, the system could not take this arrangement."])

    # ------------------------------------------------------------ other situations (rules 39 to 47)
    C("55", "The company is in administration", "Situations", V + [("neg", Customer({"kind": "insolvency", "said": "The company went into administration last week."}))],
      "escalated", "insolvency", transfers=["specialist"], calls={"create_promise": 0, "add_note": 0})
    C("56", "Asks for the relationship manager: asked once whether the assistant can help, then transferred", "Situations",
      V + [("neg", Customer({"kind": "manager", "said": "I want to speak to my relationship manager."}, then=[{"kind": "manager", "said": "No, I want my relationship manager."}]))],
      "escalated", "manager_request", transfers=["relationship_manager"])
    C("57", "Asks for the manager once, then pays", "Situations",
      V + [("neg", Customer({"kind": "manager", "said": "Can I speak to my manager about this?"}, then=["accept"]))], "agreed", promises=[("f1", 5400.0, T)],
      calls={"transfer_to_agent": 0}, tier=2, note="after 'can I help first?' the contact says yes to the question that is open: paying today")
    C("58", "Already paid", "Situations", V + [("neg", Customer({"kind": "already_paid", "said": "We paid this on Monday."}))], "settled", notes=[("f1", "settled")],
      said=["Payments can take up to three business days to appear."])
    C("59", "The company does not owe this", "Situations", V + [("neg", Customer({"kind": "contested", "said": "The company does not owe this."}))], "no_agreement", "contested",
      notes=[("f1", "contested")])
    fire = {"kind": "difficulty", "said": "We had a fire in the workshop last month."}
    C("60", "A fire: accepts the business support desk", "Situations", V + [("neg", Customer(fire, offer="accept"))], "escalated", "support", transfers=["support_desk"],
      calls={"add_note": 0})
    C("61", "A fire: declines the business support desk", "Situations", V + [("neg", Customer(fire, offer="decline"))], "no_agreement", "difficulty", notes=[("f1", "difficulty")])
    C("62", "A bad moment, after verification: a callback is booked under rule 7", "Situations",
      V + [("neg", Customer({"kind": "call_back_later", "said": "This is a bad moment, please call me back later."})), ("tp", {"cb_when_text": "tomorrow at half past nine"})],
      "no_agreement", "callback_requested", callbacks=[(T + ONE, "09:30")], tier=2)
    C("63", "A bad moment, before verification", "Situations", [("who", "confirmed"), ("go", "call_back_later"), ("tp", {"cb_when_text": "Friday at two in the afternoon"})],
      "no_agreement", "callback_requested", callbacks=[(day("2026-10-16"), "14:00")], tier=2, modes=("orch", "v1"), calls={"get_account": 0})
    C("64", "Does not want to talk, twice", "Situations",
      V + [("neg", Customer({"kind": "not_talking", "said": "I do not want to talk about this."}, then=[{"kind": "not_talking", "said": "I said I do not want to talk."}]))],
      "no_agreement", "declined", calls={"add_note": 0})

    # ------------------------------------------------------------ several facilities (rules 28, 30, 48 to 54)
    C("70", "Three facilities, all today", "Several facilities", V + [("neg", Customer("accept"))], "agreed", products=THREE,
      promises=[("f1", 5400.0, T), ("f2", 1980.0, T), ("f3", 730.5, T)], said=["Can the company settle all of them today?", "company card ending 5512"], calls={"create_promise": 3})
    s3, p3 = lad(LOAN_S), lad(LEASE_P)
    C("71", "Three facilities refuse everything: three attempts for the whole call, and none for the escalated one", "Several facilities",
      V + [("neg", Customer("refuse", then=["refuse"]))], "no_agreement", "declined", products=THREE, offered=s3 + p3[:1], calls={"add_note": 0, "create_promise": 0},
      note="rule 30: at most three attempts in one call. The loan uses two, the lease gets the one that is left, the card is in the escalated band")
    C("72", "One date for both, allowed for both", "Several facilities", V + [("neg", Customer({"kind": "propose", "day": "Friday", "about": "both", "said": "Both on Friday."}))],
      "agreed", products=TWO, promises=[("f1", 5400.0, day("2026-10-16")), ("f2", 1980.0, day("2026-10-16"))])
    late = day("2026-10-28")                                # after the loan's deadline (Saturday 24), before the lease's (Saturday 31)
    C("73", "One date for both, too late for the loan: the lease takes it, the loan needs an earlier one (rules 21 and 49)", "Several facilities",
      V + [("neg", Customer({"kind": "propose", "day": said_day(late), "about": "both", "said": "Both on the 28th."},
                            then=[{"kind": "propose", "day": said_day(dl(LOAN_S)), "about": "the business loan", "said": "The loan on the 24th then."}]))],
      "agreed", products=TWO, promises=[("f1", 5400.0, dl(LOAN_S)), ("f2", 1980.0, late)], tier=2)
    C("74", "The loan is contested, the lease is paid on Friday", "Several facilities",
      V + [("neg", Customer({"kind": "contested", "about": "the business loan", "said": "We do not owe the business loan."},
                            then=[{"kind": "propose", "day": "Friday", "said": "The lease on Friday."}]))], "agreed", products=TWO,
      promises=[("f2", 1980.0, day("2026-10-16"))], notes=[("f1", "contested")])
    C("75", "The loan is already paid, the lease is refused: no note for a refused facility", "Several facilities",
      V + [("neg", Customer({"kind": "already_paid", "about": "the business loan", "said": "The business loan is already paid."}, then=["refuse"]))], "no_agreement", "declined",
      products=TWO, notes=[("f1", "settled")])
    C("76", "Both already paid", "Several facilities", V + [("neg", Customer({"kind": "already_paid", "about": "both", "said": "We paid both last week."}))], "settled",
      products=TWO, notes=[("f1", "settled"), ("f2", "settled")])
    C("78", "The loan is refused twice, then the lease is contested (rule 54: the first facility's reason)", "Several facilities",
      V + [("neg", Customer("refuse", then=["refuse", {"kind": "contested", "about": "the equipment lease", "said": "We never had that lease."}]))], "no_agreement", "declined",
      products=TWO, notes=[("f2", "contested")])
    C("79", "Agrees the loan, then the company is insolvent: nothing recorded, nothing noted", "Several facilities",
      V + [("neg", Customer({"kind": "propose", "day": "Friday", "about": "the business loan", "said": "The loan on Friday."},
                            then=[{"kind": "insolvency", "said": "To be honest, the company is going into liquidation."}]))], "escalated", "insolvency", products=TWO,
      transfers=["specialist"], calls={"create_promise": 0, "add_note": 0})
    C("80", "The first facility's promise fails, the second is recorded", "Several facilities", V + [("neg", Customer("accept"))], "agreed", products=TWO,
      promises=[("f2", 1980.0, T)], notes=[("f1", "system_error")], faults={"create_promise": 1}, calls={"create_promise": 2})
    return out
