"""Customers of mock brief D (Harbor Retail Bank). Every expected record is worked out from the documents in this
folder with lib.Cal, the day-by-day calendar that does not use the builder's date code.

Section numbers are the handbook's; "memo" is 3-memo.md, "email" is 1-email.md.
"""
import datetime as dt
from lib import MO, ONE, Customer, case, day, spoken, verified

OKAFOR = {"variables": {"salutation": "Ms", "given_name": "Adaeze", "family_name": "Okafor"}, "identity": {"postcode": "LS62AB", "birth_year": "1984"}}
CARD_A = {"account_id": "a1", "kind": "credit_card", "last_digits": "0417", "arrears": 380.0, "days_overdue": 7, "min_payment": 95.0}            # band A
LOAN_B = {"account_id": "a1", "kind": "personal_loan", "arrears": 1240.0, "days_overdue": 25, "monthly_instalment": 310.0}                      # band B
CARD_C = {"account_id": "a1", "kind": "credit_card", "last_digits": "7730", "arrears": 2125.10, "days_overdue": 64, "min_payment": 637.5}       # band C
DRAFT_B = {"account_id": "a1", "kind": "arranged_overdraft", "arrears": 640.0, "days_overdue": 15}                                               # band B, no minimum
THREE = [CARD_A, dict(LOAN_B, account_id="a2"), dict(DRAFT_B, account_id="a3")]
TWO = [CARD_A, dict(CARD_C, account_id="a2")]
NOW = "2026-11-03T09:40"                                    # a Tuesday, the day after a closure day
DAYS = [("tue", "2026-11-03", "the day after a closure day"), ("thu", "2026-11-12", "the day before a closure day and a weekend"),
        ("fri", "2026-11-06", "a Friday"), ("dec22", "2026-12-22", "two days before four closure days in ten"), ("dec23", "2026-12-23", "the last business day before Christmas"),
        ("nov30", "2026-11-30", "the last day of a month")]


def said_day(d):
    return f"{d.day} {MO[d.month - 1]}"


def cases(P):
    cal, out = P.cal, []
    T = day(NOW)
    V = verified(P, OKAFOR["identity"])

    def C(cid, title, family, steps, outcome, reason=None, products=(CARD_A,), now=NOW, **kw):
        out.append(case("D-" + cid, title, family, now, steps, outcome, reason, variables=OKAFOR["variables"], identity=OKAFOR["identity"], products=products, **kw))

    full, floor = lambda p: p["arrears"], lambda p: p.get("min_payment", p.get("monthly_instalment", p["arrears"]))
    dl = lambda p, today=T: cal.deadline(p["days_overdue"], today)
    lad = lambda p, today=T, tm=False: cal.ladder(p["days_overdue"], today, full(p), floor(p), tm)

    # ------------------------------------------------------------ the simplest call
    C("01", "Confirms, passes security and pays the full amount today", "Happy path", V + [("neg", Customer("accept"))], "arrangement", promises=[("a1", 380.0, T)],
      said=["Shall I record that?", "credit card ending 0417", "A confirmation letter will be sent to your registered address.", "Thank you, Ms Okafor. Goodbye."],
      calls={"verify_identity": 2, "get_account": 1, "create_promise": 1, "add_note": 0})

    # ------------------------------------------------------------ who is on the line (email 4, handbook 3.2)
    C("02", "Never confirms who is speaking: three asks, then closed", "Opening", [("who", ""), ("who", ""), ("who", "")], "unreached", "not_confirmed",
      calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
    C("03", "A partner answers: callback tomorrow at ten", "Third party", [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at ten in the morning"})],
      "unreached", "callback_booked", callbacks=[(T + ONE, "10:00")], calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
    C("04", "Today is never possible, 09:00 is before the window, 16:30 is its last minute (memo 3)", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "today at three in the afternoon"}), ("tp", {"cb_when_text": "tomorrow at nine"}),
       ("tp", {"cb_when_text": "tomorrow at half past four in the afternoon"})],
      "unreached", "callback_booked", callbacks=[(T + ONE, "16:30")], modes=("orch", "v1"))
    C("05", "Three times that do not fit: nothing is booked", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "today at four"}), ("tp", {"cb_when_text": "Saturday morning at ten"}),
       ("tp", {"cb_when_text": "the day after tomorrow at five in the evening"})],
      "unreached", "no_callback", calls={"schedule_callback": 0}, modes=("orch", "v1"))
    C("06", "The handbook's old window (17:00) is no longer bookable after the memo", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at 5 pm"}), ("tp", {"cb_when_text": "tomorrow at 4 pm"})],
      "unreached", "callback_booked", callbacks=[(T + ONE, "16:00")], modes=("orch", "v1"))
    thu = day("2026-11-12")
    C("07", "Tomorrow is a closure day the memo added: the next business day is Monday", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at eleven"}), ("tp", {"cb_when_text": "Monday at eleven"})],
      "unreached", "callback_booked", callbacks=[(day("2026-11-16"), "11:00")], now="2026-11-12T14:15", modes=("orch", "v1"))
    C("08", "The business day after the next one is allowed too", "Third party", [("who", "someone_else"), ("tp", {"cb_when_text": "Tuesday at a quarter past ten"})],
      "unreached", "callback_booked", callbacks=[(day("2026-11-17"), "10:15")], now="2026-11-12T14:15", modes=("orch", "v1"))
    C("09", "The day the memo took off the closure list (20 November) can be booked", "Third party",
      [("who", "someone_else"), ("tp", {"cb_when_text": "tomorrow at noon"})], "unreached", "callback_booked", callbacks=[(day("2026-11-20"), "12:00")],
      now="2026-11-19T10:00", modes=("orch", "v1"))
    C("10", "Wrong number, said to the opening question", "Third party", [("who", "wrong_number")], "unreached", "wrong_number",
      calls={"verify_identity": 0, "schedule_callback": 0}, modes=("orch", "v1"))
    C("11", "Wrong number, said after a first reply", "Third party", [("who", "someone_else"), ("tp", {"tp_event": "wrong_number"})], "unreached", "wrong_number", modes=("orch", "v1"))
    C("12", "The customer has died", "Third party", [("who", "someone_else"), ("tp", {"tp_event": "deceased"})], "unreached", "deceased",
      said=["Please accept our condolences."], calls={"schedule_callback": 0, "verify_identity": 0}, modes=("orch", "v1"))

    # ------------------------------------------------------------ security (3.3)
    pay = [("neg", Customer("accept"))]
    C("13", "Postcode with a space and in small letters, year in words", "Identity",
      [("who", "confirmed"), ("id", "postcode", "ls6 2ab", "LS62AB"), ("id", "birth_year", "nineteen eighty-four", "1984")] + pay, "arrangement", promises=[("a1", 380.0, T)], modes=("orch", "v1"))
    C("14", "Says the codes character by character, as the in_words style does", "Identity",
      [("who", "confirmed"), ("id", "postcode", "L S six, two A B", "LS62AB"), ("id", "birth_year", "one nine eight four", "1984")] + pay,
      "arrangement", promises=[("a1", 380.0, T)], modes=("orch", "v1"),
      note="tools/run_cases.py, style in_words: 'Postcodes, years and other codes you say digit by digit.'")
    C("15", "The postcode as speech-to-text may write it: with a comma and a full stop", "Identity",
      [("who", "confirmed"), ("id", "postcode", "LS6, 2AB.", "LS62AB"), ("id", "birth_year", "It was 1984.", "1984")] + pay,
      "arrangement", promises=[("a1", 380.0, T)], tier=2, modes=("orch", "v1"))
    C("16", "Only the first half of the postcode: the bank's advice is followed and nothing is counted", "Identity",
      [("who", "confirmed"), ("id", "postcode", "LS6", "LS6"), ("id", "postcode", "LS6 2AB", "LS62AB"), ("id", "birth_year", "1984", "1984")] + pay,
      "arrangement", promises=[("a1", 380.0, T)], modes=("orch", "v1"))
    C("17", "One wrong answer, then the right ones", "Identity",
      [("who", "confirmed"), ("id", "postcode", "M14 6QT", "M146QT"), ("id", "postcode", "LS6 2AB", "LS62AB"), ("id", "birth_year", "1984", "1984")] + pay,
      "arrangement", promises=[("a1", 380.0, T)], modes=("orch", "v1"))
    C("18", "Two wrong answers end the check (not three, as in the kit's brief)", "Identity",
      [("who", "confirmed"), ("id", "postcode", "M14 6QT", "M146QT"), ("id", "postcode", "EH3 9DQ", "EH39DQ")], "unverified", "failed_security",
      said=["For your security I cannot continue this call. Please ring the number on the back of your card."], not_said=["credit card", "380"],
      calls={"get_account": 0, "verify_identity": 2}, modes=("orch", "v1"))
    C("19", "Right postcode, then the year wrong twice", "Identity",
      [("who", "confirmed"), ("id", "postcode", "LS62AB", "LS62AB"), ("id", "birth_year", "1948", "1948"), ("id", "birth_year", "1985", "1985")], "unverified", "failed_security",
      calls={"get_account": 0}, modes=("orch", "v1"))
    C("20", "Refuses the security questions: closed at once, without a second ask", "Identity", [("who", "confirmed"), ("decline",)], "unverified", "refused_security",
      calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
    C("21", "Asks why the questions are needed, then answers", "Identity", [("who", "confirmed"), ("id_question",)] + V[1:] + pay, "arrangement", promises=[("a1", 380.0, T)],
      modes=("orch", "v1"))
    C("22", "Asks for a person before security: transferred at once (3.9 e)", "Situations", [("who", "confirmed"), ("go", "person")], "handed_over", "agent_request",
      transfers=["agents"], calls={"verify_identity": 0, "get_account": 0, "add_note": 0}, modes=("orch", "v1"))
    C("23", "Tells the assistant to stop calling, before security (3.9 f)", "Situations", [("who", "confirmed"), ("go", "not_wanted")], "unverified", "refused_security",
      calls={"get_account": 0, "add_note": 0}, modes=("orch", "v1"))

    # ------------------------------------------------------------ dates (3.5, memo 1 and 2), on six calendar days
    for tag, iso, why in DAYS:
        today, now = day(iso), iso + "T09:40"
        a1 = lad(CARD_A, today)[0]
        C(f"30-{tag}", f"Cannot pay today, takes the first date offered ({why})", "Dates", V + [("neg", Customer("refuse", then=["accept"]))], "arrangement",
          promises=[("a1", 380.0, a1[1])], offered=[a1], now=now, said=[spoken(a1[1])])
        late = dl(LOAN_B, today)
        C(f"31-{tag}", f"Names a date after the latest promise date, accepts the latest one ({why})", "Dates",
          V + [("neg", Customer({"kind": "propose", "day": said_day(late + dt.timedelta(days=14)), "said": "I can pay then."}, then=["accept"]))], "arrangement",
          products=[LOAN_B], promises=[("a1", 1240.0, late)], offered=[(1240.0, late)], now=now, said=["The latest date I can record", spoken(late)])
        b = lad(LOAN_B, today)
        C(f"32-{tag}", f"Band B refuses everything: three attempts, each with its own amount and date ({why})", "Refusals",
          V + [("neg", Customer("refuse", then=["refuse"]))], "no_arrangement", "declined", products=[LOAN_B], notes=[("a1", "declined")], offered=b, now=now,
          calls={"create_promise": 0, "transfer_to_agent": 0})
        c = lad(CARD_C, today)
        C(f"33-{tag}", f"Band C refuses everything: two attempts, the latest date four calendar days on, rolled back ({why})", "Refusals",
          V + [("neg", Customer("refuse", then=["refuse"]))], "no_arrangement", "declined", products=[CARD_C], notes=[("a1", "declined")], offered=c, now=now)
    C("34", "Names a Saturday: it is refused, not replaced; then names the Monday", "Dates",
      V + [("neg", Customer({"kind": "propose", "day": "Saturday", "said": "I can pay on Saturday."}, then=[{"kind": "propose", "day": "Monday", "said": "Monday then."}]))],
      "arrangement", promises=[("a1", 380.0, day("2026-11-09"))], not_said=["Saturday 7 November 2026?"])
    C("34s", "...and the assistant names no day of its own after refusing the Saturday (3.5)", "Dates",
      V + [("neg", Customer({"kind": "propose", "day": "Saturday", "said": "I can pay on Saturday."}, then=[{"kind": "propose", "day": "Monday", "said": "Monday then."}]))],
      "arrangement", promises=[("a1", 380.0, day("2026-11-09"))], offered=[], tier=2)
    C("35", "Names the closure day the memo added (13 November), then the day before it", "Dates",
      V + [("neg", Customer({"kind": "propose", "day": "the 13th of November"}, then=[{"kind": "propose", "day": "Thursday the 12th"}]))],
      "arrangement", promises=[("a1", 380.0, day("2026-11-12"))])
    C("36", "The day the memo took off the closure list (20 November) is a business day", "Dates",
      V + [("neg", Customer({"kind": "propose", "day": "the 20th of November"}))], "arrangement", promises=[("a1", 380.0, day("2026-11-20"))], now="2026-11-12T09:40")
    C("37", "A vague period three times: the exact day is asked twice, then the latest date is proposed", "Dates",
      V + [("neg", Customer({"kind": "vague", "day": "next week", "said": "Next week sometime."},
                            then=[{"kind": "vague", "day": "after payday", "said": "After payday."}, {"kind": "vague", "day": "sometime in November", "said": "Sometime in November."}, "accept"]))],
      "arrangement", promises=[("a1", 380.0, dl(CARD_A))], offered=[(380.0, dl(CARD_A))])
    C("38", "'Next Friday' said on a Tuesday is the first Friday that comes", "Dates", V + [("neg", Customer({"kind": "propose", "day": "next Friday"}))],
      "arrangement", promises=[("a1", 380.0, day("2026-11-06"))])
    C("39", "'This Friday' said on a Friday is today", "Dates", V + [("neg", Customer({"kind": "propose", "day": "this Friday"}))],
      "arrangement", promises=[("a1", 380.0, day("2026-11-06"))], now="2026-11-06T09:40")
    C("40", "'Next Friday' said on a Friday is seven days later", "Dates", V + [("neg", Customer({"kind": "propose", "day": "next Friday"}))],
      "arrangement", promises=[("a1", 1240.0, day("2026-11-27"))], products=[LOAN_B], now="2026-11-20T09:40")

    # ------------------------------------------------------------ amounts (3.6)
    C("41", "The full amount is too much: the minimum is offered once, with the sentence", "Amounts", V + [("neg", Customer("too_much", then=["accept"]))],
      "arrangement", promises=[("a1", 95.0, T)], offered=[(95.0, T)], once=["The remaining balance stays overdue."])
    C("42", "Too much, and not today either: attempt 1 is for the minimum on the next business day", "Amounts",
      V + [("neg", Customer("too_much", then=["refuse", "accept"]))], "arrangement", promises=[("a1", 95.0, T + ONE)], offered=[(95.0, T), (95.0, T + ONE)],
      once=["The remaining balance stays overdue."])
    C("43", "Offers less than the minimum, then accepts the minimum", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "50", "day": "today", "said": "I can pay 50 today."}, then=["accept"]))], "arrangement", promises=[("a1", 95.0, T)],
      said=["I am afraid I cannot accept less than the minimum."])
    C("44", "Offers an amount between the minimum and the full amount, on Friday", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "200", "day": "Friday", "said": "I can pay 200 on Friday."}))], "arrangement", promises=[("a1", 200.0, day("2026-11-06"))])
    C("45", "Offers more than is overdue: the overdue amount is recorded", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "500", "day": "tomorrow", "said": "I will pay 500 tomorrow."}))], "arrangement", promises=[("a1", 380.0, T + ONE)])
    C("46", "The amount in words and with a self-correction", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "two hundred, sorry, two hundred and fifty", "day": "tomorrow, no wait, Thursday", "said": "Two hundred, sorry, two hundred and fifty, tomorrow, no wait, Thursday."}))],
      "arrangement", promises=[("a1", 250.0, day("2026-11-05"))])
    od = lad(DRAFT_B)
    C("47", "An overdraft has no minimum: a part payment is refused and every offer is the full amount", "Amounts",
      V + [("neg", Customer({"kind": "propose", "amount": "300", "day": "Monday", "said": "I can pay 300 on Monday."}, then=["refuse"]))], "no_arrangement", "declined",
      products=[DRAFT_B], notes=[("a1", "declined")], offered=[(640.0, day("2026-11-09"))] + od, said=["I am afraid I cannot accept less than the minimum."], not_said=["The remaining balance stays overdue."])
    C("48", "An overdraft, 'too much': there is nothing lower to offer, and the full amount on the first date is taken", "Amounts",
      V + [("neg", Customer("too_much", then=["refuse", "accept"]))], "arrangement", products=[DRAFT_B], promises=[("a1", 640.0, od[0][1])], tier=2)

    # ------------------------------------------------------------ refusals and the one-attempt band (3.7)
    a = lad(CARD_A)
    C("50", "Band A refuses everything: exactly one attempt", "Refusals", V + [("neg", Customer("refuse", then=["refuse"]))], "no_arrangement", "declined",
      notes=[("a1", "declined")], offered=a, calls={"create_promise": 0, "transfer_to_agent": 0})
    C("51", "'I can't, what are my options?' is a refusal with a question, not a hand-over", "Refusals",
      V + [("neg", Customer({"kind": "refuse", "said": "I can't. What are my options?", "question": "yes"}, then=["accept"]))], "arrangement", promises=[("a1", 380.0, a[0][1])],
      calls={"transfer_to_agent": 0})
    C("52", "Asks for a payment plan: withdrawn by the memo, so no hand-over; then takes the first date", "Refusals",
      V + [("neg", Customer({"kind": "question", "said": "Can I get a payment plan?", "question": "yes"}, then=["refuse", "accept"]))], "arrangement",
      promises=[("a1", 380.0, a[0][1])], calls={"transfer_to_agent": 0})

    # ------------------------------------------------------------ hardship (3.7, memo 4)
    job = {"kind": "hardship", "said": "I lost my job last month, I cannot pay anything."}
    C("55", "Lost the job, accepts the welfare team: the queue has the memo's new name", "Hardship", V + [("neg", Customer(job, offer="accept"))], "handed_over", "welfare",
      transfers=["care"], calls={"create_promise": 0, "add_note": 0})
    C("56", "Lost the job, declines the welfare team", "Hardship", V + [("neg", Customer(job, offer="decline"))], "no_arrangement", "hardship", notes=[("a1", "hardship")],
      calls={"transfer_to_agent": 0})
    C("57", "Lost the job, but names a day: the promise is taken", "Hardship",
      V + [("neg", Customer(job, offer={"kind": "propose", "day": "Friday", "said": "But I can pay on Friday."}))], "arrangement", promises=[("a1", 380.0, day("2026-11-06"))])

    # ------------------------------------------------------------ recording (3.8)
    C("60", "create_promise fails twice, the third try records it", "Recording", V + [("neg", Customer("accept"))], "arrangement", promises=[("a1", 380.0, T)],
      faults={"create_promise": 2}, calls={"create_promise": 3})
    C("61", "create_promise fails three times", "Recording", V + [("neg", Customer("accept"))], "no_arrangement", "system_fault", notes=[("a1", "system_fault")],
      faults={"create_promise": 3}, calls={"create_promise": 3}, said=["I am sorry, I was unable to save the arrangement."])
    C("62", "Changes the day at the read-back", "Recording",
      V + [("neg", Customer("accept", readback=[{"kind": "propose", "day": "Thursday", "said": "No, make it Thursday."}, "accept"]))], "arrangement",
      promises=[("a1", 380.0, day("2026-11-05"))], calls={"create_promise": 1})

    # ------------------------------------------------------------ other situations (3.9)
    C("65", "Says it is already paid", "Situations", V + [("neg", Customer({"kind": "already_paid", "said": "I paid that yesterday."}))], "settled", notes=[("a1", "already_paid")],
      said=["Payments can take up to two working days to show."])
    C("66", "Says the account is not theirs", "Situations", V + [("neg", Customer({"kind": "dispute", "said": "That card is not mine."}))], "no_arrangement", "disputed",
      notes=[("a1", "disputed")], calls={"create_promise": 0})
    C("67", "Wants to complain", "Situations", V + [("neg", Customer({"kind": "complaint", "said": "I want to make a complaint about this bank."}))], "handed_over", "complaints",
      transfers=["complaints"], calls={"add_note": 0})
    C("68", "Asks for a human, after security: at once, without 'can I help first'", "Situations",
      V + [("neg", Customer({"kind": "person", "said": "I want to talk to a human."}))], "handed_over", "agent_request", transfers=["agents"], calls={"add_note": 0})
    C("69", "Asks for 'a real person': the word is also part of 'personal loan', a product the bank names", "Situations",
      V + [("neg", Customer({"kind": "person", "said": "Can I speak to a real person, please?"}))], "handed_over", "agent_request", transfers=["agents"], tier=2,
      note="generate.Gen.evidence drops an evidence word that occurs in the agent's own sentences; 'person' is in 'personal loan'")
    C("69b", "Asks for a person in words the reader did not list, and insists", "Situations",
      V + [("neg", Customer({"kind": "person", "said": "Put me through to your supervisor."}, then=[{"kind": "person", "said": "I said, put me through to your supervisor."}]))],
      "handed_over", "agent_request", transfers=["agents"], tier=2)
    C("70", "Tells the assistant to stop calling, after security: noted and closed", "Situations",
      V + [("neg", Customer({"kind": "not_wanted", "said": "Stop calling me. I do not want this call."}))], "no_arrangement", "declined", notes=[("a1", "declined")])

    # ------------------------------------------------------------ more than one account (3.10)
    C("80", "Three accounts, all today", "Several accounts", V + [("neg", Customer("accept"))], "arrangement", products=THREE,
      promises=[("a1", 380.0, T), ("a2", 1240.0, T), ("a3", 640.0, T)], said=["Are you able to clear all of these today?", "arranged overdraft", "personal loan"], calls={"create_promise": 3})
    C("81", "Three accounts, one day for all of them", "Several accounts", V + [("neg", Customer({"kind": "propose", "day": "Thursday", "about": "all of them", "said": "All of them on Thursday."}))],
      "arrangement", products=THREE, promises=[("a1", 380.0, day("2026-11-05")), ("a2", 1240.0, day("2026-11-05")), ("a3", 640.0, day("2026-11-05"))])
    C("82", "One day for both, after the latest date of one: that one is recorded on its own latest date", "Several accounts",
      V + [("neg", Customer({"kind": "propose", "day": "Monday the 9th", "about": "both", "said": "Both on Monday the 9th."}))], "arrangement", products=TWO,
      promises=[("a1", 380.0, day("2026-11-09")), ("a2", 2125.10, dl(CARD_C))], said=["latest date"])
    C("83", "Promises the card, refuses the other two: each has its own attempts", "Several accounts",
      V + [("neg", Customer({"kind": "propose", "day": "tomorrow", "about": "the credit card", "said": "The credit card tomorrow."}, then=["refuse"]))], "arrangement", products=THREE,
      promises=[("a1", 380.0, T + ONE)], notes=[("a2", "declined"), ("a3", "declined")], offered=lad(LOAN_B) + lad(DRAFT_B))
    C("84", "Disputes the card, pays the other two on one day", "Several accounts",
      V + [("neg", Customer({"kind": "dispute", "about": "the credit card", "said": "That credit card is not mine."},
                            then=[{"kind": "propose", "day": "Thursday", "about": "both", "said": "Both of the others on Thursday."}]))], "arrangement", products=THREE,
      promises=[("a2", 1240.0, day("2026-11-05")), ("a3", 640.0, day("2026-11-05"))], notes=[("a1", "disputed")])
    C("85", "The card is already paid, the other two are refused", "Several accounts",
      V + [("neg", Customer({"kind": "already_paid", "about": "the credit card", "said": "I paid the credit card yesterday."}, then=["refuse"]))], "no_arrangement", "declined",
      products=THREE, notes=[("a1", "already_paid"), ("a2", "declined"), ("a3", "declined")])
    C("86", "Says all three are already paid", "Several accounts", V + [("neg", Customer({"kind": "already_paid", "about": "all of them", "said": "I paid all of them this morning."}))],
      "settled", products=THREE, notes=[("a1", "already_paid"), ("a2", "already_paid"), ("a3", "already_paid")])
    C("87", "Agrees the card, then wants to complain: nothing is recorded, nothing is noted", "Several accounts",
      V + [("neg", Customer({"kind": "propose", "day": "tomorrow", "about": "the credit card", "said": "The credit card tomorrow."},
                            then=[{"kind": "complaint", "said": "Actually I want to make a complaint."}]))], "handed_over", "complaints", products=THREE, transfers=["complaints"],
      calls={"create_promise": 0, "add_note": 0})
    C("88", "The first account's promise fails three times, the others are recorded", "Several accounts", V + [("neg", Customer("accept"))], "arrangement", products=THREE,
      promises=[("a2", 1240.0, T), ("a3", 640.0, T)], notes=[("a1", "system_fault")], faults={"create_promise": 3}, calls={"create_promise": 5})
    C("89", "Names a Saturday for all three, then the Monday: no persuasion attempt is used up by it", "Several accounts",
      V + [("neg", Customer({"kind": "propose", "day": "Saturday", "about": "all of them", "said": "All of them on Saturday."},
                            then=[{"kind": "propose", "day": "Monday", "about": "all of them", "said": "Monday then, all of them."}]))], "arrangement", products=THREE,
      promises=[("a1", 380.0, day("2026-11-09")), ("a2", 1240.0, day("2026-11-09")), ("a3", 640.0, day("2026-11-09"))], offered=[], tier=2)
    C("90", "Lost the job, declines the welfare team, three accounts: each is noted hardship", "Several accounts", V + [("neg", Customer(job, offer="decline"))],
      "no_arrangement", "hardship", products=THREE, notes=[("a1", "hardship"), ("a2", "hardship"), ("a3", "hardship")])
    C("91", "Tells the assistant to stop calling, three accounts: each is noted declined", "Several accounts",
      V + [("neg", Customer({"kind": "not_wanted", "said": "Stop calling me."}))], "no_arrangement", "declined", products=THREE,
      notes=[("a1", "declined"), ("a2", "declined"), ("a3", "declined")])
    return out
