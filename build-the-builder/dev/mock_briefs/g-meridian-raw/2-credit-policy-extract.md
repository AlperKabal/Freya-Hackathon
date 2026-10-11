# Meridian Business Bank - Credit Policy

Extract: chapter 7, "Calls to companies with overdue facilities". Edition of 1 July 2026.

## 7.1 Purpose

A company can be overdue on one, two or three facilities at a time. The caller finds the company's named contact, verifies the company, states what is overdue, obtains a payment promise where that is possible, and closes the call with an outcome code.

## 7.2 When the contact is not on the line

The caller does not say why it is calling and asks when the contact can be reached. A callback may be booked for today or for the next business day, from 09:00 to 17:00, both included, and later than the time of the call. It is booked with schedule_callback (date and time); the call then closes as no_contact / callback_booked. If the day or time offered does not fit, the caller asks once for another time. If that does not fit either, nothing is booked and the call closes as no_contact / callback_refused.

If the person says the contact no longer works for the company, the call closes as no_contact / contact_left. If the person says the company has stopped trading, it closes as no_contact / ceased_trading.

Nobody but the contact may answer the verification questions, and nobody else is told anything about the facilities.

## 7.3 Verification

Two questions, one at a time: first the company registration number, then the year in which the company was founded. Each answer is checked with verify_identity. The registration number is sent as its eight digits, with any leading zeros and nothing else. The year is sent as four digits.

A wrong answer may be asked again. Three wrong answers in total end the verification, whichever question they were on. The service does not report how many tries are left, so the caller counts them.

After the third wrong answer the caller states nothing about the facilities. It says "I cannot verify the company, so I have to end this call." and closes as unverified / wrong_answers.

A contact who does not want to answer is told once: "These checks protect the company's accounts." If the contact still declines, the call closes as unverified / declined_checks. Asking what the call is about is not declining: the caller says that it can explain after the checks and asks the question again.

## 7.4 Stating what is overdue

After both questions are passed the caller calls get_account, which returns one to three overdue facilities. It says: "I am calling about overdue amounts on your company's facilities." It then states every facility, one sentence each, before it asks for anything: the facility's name, the overdue amount and the number of days it is overdue. The names are in the facility type list.

## 7.5 Business days, bands and deadlines

Business days are Monday to Saturday. The bank's holidays are not business days: 29 October 2026, Christmas Day and the day after it (25 and 26 December 2026), and New Year's Day 2027.

How long a facility is overdue decides its band. The band decides the deadline and the number of persuasion attempts.

| Days overdue | Band | Deadline | Persuasion attempts |
|---|---|---|---|
| 1 to 14 | standard | the 14th calendar day after today; if that day is not a business day, the next business day | 2 |
| 15 to 60 | priority | the last business day of the current calendar month | 2 |
| more than 60 | escalated | the 2nd business day after today | 1 |

For the priority band: when today is the last business day of the month, the deadline is today. When that day has already passed, the deadline is the last business day of the next month.

A payment date must be today or later and not after the deadline. It may be any calendar day, because payments can also be made on Sundays and on holidays.

A date after the deadline cannot be recorded. The caller says that this date is too late and asks for an earlier one. This is not a refusal.

A vague period ("next week", "at the end of the quarter", "when our client pays us"): the caller asks once for the exact day. If there is still no day, it is a flat refusal (7.7).

"Next" with a weekday means that weekday in the following calendar week. "This" with a weekday means the one in the current week.

## 7.6 Amounts

The caller asks for the full overdue amount first. It does not ask the contact to name an amount. The caller proposes every amount.

The minimum of a facility is in the field named in the facility type list.

If the contact says the full amount is too much, the caller offers the minimum, once, and says: "The balance that remains is still overdue." A contact who refuses the minimum has flatly refused (7.7).

An amount the contact proposes is accepted when it is at least the minimum and at most the full overdue amount. For a lower amount the caller says "That is below the minimum we can accept." and offers the minimum once. If the contact does not accept the minimum, that is a flat refusal (7.7).

## 7.7 Obtaining the promise

With one facility the first question is: "Can the company settle this today?" With several the first question is: "Can the company settle all of them today?" If not, the caller goes through the facilities one by one, in the order in which get_account returned them. It does not ask about today again for each facility.

A date or an amount the contact proposes is never a refusal. It is handled under 7.5 and 7.6.

A flat refusal, or no real answer, uses one persuasion attempt:

- Attempt 1: the full overdue amount on the last business day of this week. If the contact already said the full amount is too much, attempt 1 is for the minimum. If today is the last business day of this week, attempt 1 names the last business day of next week.
- Attempt 2: half of the overdue amount on the deadline. Half is rounded to the cent, and exactly half a cent is rounded up.

No attempt names a date after the deadline. If its date would be later, it names the deadline.

Each facility has its own persuasion attempts. When they are used up, that facility ends without a promise.

When nothing was promised and nothing else in this chapter applies, the call closes as no_agreement / declined.

The caller never offers a discount, a waiver, a payment holiday or a new repayment schedule.

## 7.8 Read-back and recording

The caller reads all agreed promises back together: for each one the facility, the amount and the date. It asks "Is that correct?". Only after a clear yes it calls create_promise, once per facility. If the contact changes a date or an amount at this point, the new value is checked under 7.5 and 7.6 and read back again.

One promise per facility. A recorded promise cannot be changed in the same call. If the contact asks, the caller says that their relationship manager can change it.

The caller says that a promise is recorded only after create_promise returned success true. If the call fails, the caller tries once more. If it fails again, it says "I am sorry, the system could not take this arrangement." If no promise was recorded in the call, the call closes as no_agreement / system_error.

After a recorded promise the caller says: "You will receive an e-mail confirming this arrangement."

## 7.9 Other things a contact may say

(a) The company is insolvent, in administration or in liquidation: the caller does not negotiate and takes no promise. It calls transfer_to_agent with the desk specialist and closes as escalated / insolvency.

(b) The contact asks for the relationship manager, or for a person: the caller asks once whether it can help first. If the contact insists, it calls transfer_to_agent with the desk relationship_manager and closes as escalated / manager_request. This holds before and after verification.

(c) "We have already paid this": the caller says "Payments can take up to three business days to appear." and takes no promise for that facility.

(d) "The company does not owe this", or "we never had this facility": the caller does not argue and takes no promise for that facility.

(e) The company is in temporary difficulty, for example after a fire, a flood or the loss of a major client: the caller says one short sentence of understanding and makes no persuasion attempt. It offers to put the contact through to the business support desk. If the contact accepts: transfer_to_agent with the desk support_desk, and the call closes as escalated / support. If the contact declines: no_agreement / difficulty. If the contact still names a date or an amount, the promise is taken under 7.5 and 7.6.

(f) The contact says it is a bad moment and asks to be called back: the caller books a callback under the rules of 7.2 with schedule_callback and closes as no_agreement / callback_requested. This holds once the contact is confirmed, before and after verification.

(g) The contact says twice that they do not want to talk: the call closes as no_agreement / declined. Before verification the same contact is closed as unverified / declined_checks.

## 7.10 Several facilities

The band, the deadline and the minimum belong to each facility.

If the contact names one date for everything, it is used for every facility whose deadline allows it. A facility whose deadline is earlier is handled on its own: the date is too late for it (7.5).

A facility that ended under 7.9 (c) gets a note: add_note with that facility and the reason settled. Under 7.9 (d) the reason is contested. Under 7.9 (e), when the support desk was declined, it is difficulty. When its create_promise failed, it is system_error. A facility that was simply refused gets no note.

7.9 (c) and (d) on one facility do not end the call. The facility is noted and the caller goes on with the others.

On a transfer (7.9 a, b and e) no notes are added at all, and promises that were agreed but not yet recorded are not recorded.

## 7.11 Closing

Every call ends with exactly one close_call, with an outcome and, where the code list has one, a reason.

With no promise recorded and several facilities: if every facility ended under 7.9 (c), the outcome is settled. Otherwise the outcome is no_agreement, with the reason of the first facility, in the order of get_account, that did not end under 7.9 (c): declined for a refused facility, or contested, difficulty or system_error.

If a transfer follows a recorded promise, the call closes as escalated with that transfer's reason.
