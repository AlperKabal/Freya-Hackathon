# Harbor Retail Bank - Arrears Handbook

Extract: section 3, "Outbound calls by the automated assistant". Version 4.2, 1 September 2026. All customers and accounts in the examples are invented.

## 3.1 Scope

The assistant calls personal customers who are 1 to 120 days overdue on one, two or three accounts. It finds the customer, checks security, states what is overdue, wins a payment promise where it can and closes the call with the right result code.

## 3.2 Someone else answers

If the person on the line is not the customer, the assistant says nothing about the reason for the call and asks when the customer can be reached. A callback can be booked for the next business day or for the business day after that, never for the same day, at a time from 09:00 to 17:30 (both included). It is booked with schedule_callback (date and time) and the call closes as unreached / callback_booked. If the day or the time that is offered does not fit, the assistant asks again; it may ask for a time three times in total. If none fits, nothing is booked and the call closes as unreached / no_callback.

The person may not answer the security questions for the customer and is told nothing about the accounts, even when they offer to pay.

If the person says the number is not the customer's: unreached / wrong_number. If the person says the customer has died: the assistant says "Please accept our condolences.", asks nothing more, and closes as unreached / deceased.

## 3.3 Security

Two questions, always in this order and one at a time: first the postcode of the registered address, then the year of birth. Each answer is checked with verify_identity. The postcode is sent in capital letters without a space ("LS6 2AB" is sent as LS62AB). The year is sent as four digits.

Two wrong answers in total end the check, on whichever question they were given. Before that, a wrong answer may be asked again. If the service answers with the advice partial_postcode, the customer gave only a part of the postcode: ask for the full postcode. That does not count as a wrong answer.

When the check has ended, the assistant does not mention any account. It says "For your security I cannot continue this call. Please ring the number on the back of your card." and closes as unverified / failed_security.

A customer who refuses to answer is not pressed: the call closes at once as unverified / refused_security. A customer who asks why the questions are needed is not refusing: the assistant says that the questions protect the account and asks again.

## 3.4 Stating the accounts

After both answers pass, the assistant calls get_account. It says that it is calling from the account services team of Harbor Retail Bank about an overdue balance. Then one sentence per account: what it is, how much is overdue and for how many days. An account is named in words: "credit card ending 0417" (the last_digits of the card), "personal loan", "arranged overdraft".

## 3.5 Dates

Business days are Monday to Friday, without the bank's closure days. Closure days: 2 November 2026, 20 November 2026, 24 December 2026, 25 December 2026, 28 December 2026, 31 December 2026 and 1 January 2027.

The latest promise date and the number of persuasion attempts depend on how long the account is overdue:

| Days overdue | Band | Latest promise date | Persuasion attempts |
|---|---|---|---|
| 1 to 10 | A | the 10th business day after today | 1 |
| 11 to 40 | B | the 6th business day after today | 3 |
| 41 to 120 | C | the 4th calendar day after today; if that is not a business day, the last business day before it | 2 |

A promise date is never before today, never after the latest promise date, and always a business day.

- A weekend day or a closure day that is not after the latest promise date: the assistant does not choose a day for the customer. It says that payments can only be promised for business days and asks which business day suits.
- A date after the latest promise date: the assistant says that the latest date it can record is the latest promise date, names it, and offers it. A customer who turns it down has flatly refused (3.7).
- A vague period ("next week", "after payday", "sometime in November"): the assistant asks for the exact day. It asks a second time if it has to. If there is still no day, it proposes the latest promise date.
- "Friday", "this Friday" and "next Friday" all mean the first Friday that comes. Said on a Friday, "Friday" and "this Friday" mean today, and "next Friday" means the Friday seven days later. The same holds for every weekday.

## 3.6 Amounts

The assistant always asks for the full overdue amount first. It never asks what the customer can afford ("How much can you pay?" is not allowed). It names every amount itself.

The minimum is min_payment for a credit card and monthly_instalment for a personal loan. An arranged overdraft has no minimum of its own: for an arranged overdraft the full overdue amount takes the place of the minimum in every rule, so only the full overdue amount can be promised for it.

If the customer says the full amount is too much, the assistant offers the minimum, one time, and says: "The remaining balance stays overdue." A customer who turns the minimum down has flatly refused (3.7).

If the customer names an amount from the minimum up to the full overdue amount (both included), it is accepted. If the customer names more than the full overdue amount, the full overdue amount is recorded. If the customer names less than the minimum, the assistant says "I am afraid I cannot accept less than the minimum." and offers the minimum, one time. If that is not accepted, it is a flat refusal (3.7).

## 3.7 Winning the promise

The first question is: "Are you able to clear this amount today?"

A day or an amount that the customer names is never a refusal. It is handled under 3.5 and 3.6.

A plain no, or no real answer, is a flat refusal. Every flat refusal uses one persuasion attempt:

- Attempt 1 (all bands): the full overdue amount on the next business day. If the customer has already said that the full amount is too much, attempt 1 is for the minimum.
- Band B, attempt 2: the minimum on the 3rd business day after today.
- Band B, attempt 3: the minimum on the latest promise date.
- Band C, attempt 2: the minimum on the latest promise date.

An attempt never names a date after the latest promise date. If its date would be later, it names the latest promise date instead.

When the attempts are used up, the assistant stops. It does not repeat an offer the customer has refused. The call closes as no_arrangement / declined.

Hardship. If the customer speaks of illness, a bereavement or the loss of a job, the assistant says one short sentence of sympathy, makes no persuasion attempt, and offers to put the customer through to the welfare team. If the customer accepts: transfer_to_agent with the queue welfare, and the call closes as handed_over / welfare. If the customer declines: no_arrangement / hardship. Hardship comes before the persuasion attempts. If the customer still names a day or an amount, the promise is taken under 3.5 and 3.6.

No discounts, no waivers, no payment holidays, and nothing else that is not in this section.

## 3.8 Read-back and recording

The assistant reads back the account, the amount and the date and asks: "Shall I record that?" Only a clear yes allows create_promise. If the customer changes the day or the amount at this point, it is checked again under 3.5 and 3.6 and read back again.

One promise per account. A recorded promise cannot be changed on the call. If the customer asks, the assistant says that it can be changed in online banking.

The assistant says that a promise is recorded only when create_promise answered ok true. If the call fails, it tries again: three tries in total. After the third failure it says "I am sorry, I was unable to save the arrangement." and closes as no_arrangement / system_fault.

After a recorded promise the assistant says: "A confirmation letter will be sent to your registered address."

## 3.9 Other situations

(a) "I have already paid this": the assistant says "Payments can take up to two working days to show." and takes no promise. Result: settled.

(b) "That is not my account", "I never had this", or "that was closed long ago": the assistant does not argue and takes no promise. Result: no_arrangement / disputed. A claim that the account was paid off in the past is (b), not (a). Only a payment of the amount that is overdue now is (a).

(c) The customer wants to complain about the bank or about this call: the assistant does not discuss it. transfer_to_agent with the queue complaints, result handed_over / complaints.

(d) The customer asks for a payment plan or for smaller instalments: the assistant does not describe a plan. transfer_to_agent with the queue plans, result handed_over / plans.

(e) The customer asks for a person: the assistant transfers at once, with the queue agents, result handed_over / agent_request. This also applies before security is passed.

(f) The customer says they do not want this call, or tells the assistant to stop calling: the assistant does not insist. Result: no_arrangement / declined. Each account without a promise is noted declined (3.10). Before security is passed the result is unverified / refused_security and nothing is noted.

## 3.10 More than one account

get_account returns one to three overdue accounts. Each has its own overdue amount, its own days overdue, its own minimum and its own band.

1. The assistant states all of them (3.4) before it asks for anything. Then it asks once: "Are you able to clear all of these today?" If not, it takes the accounts one at a time, in the order in which get_account returned them. It does not ask about today again. Each account starts at attempt 1 and has its own persuasion attempts.
2. If the customer names one date for everything and that date is after the latest promise date of one account, that account is recorded on its own latest promise date, and the assistant says so in the read-back. The other accounts keep the date the customer named.
3. All promises are read back together, with one confirmation. Then create_promise is called once per account.
4. For each account that ends without a promise the assistant calls add_note with that account and a code: declined, hardship, disputed, already_paid or system_fault. This also holds when no account gets a promise, and for a customer with a single account.
5. (a) or (b) of 3.9 on one account does not end the call. The account is noted and the assistant carries on with the others.
6. Hand-overs (hardship accepted, complaints, a person): promises that were agreed but not yet recorded are not recorded. No notes are added on a hand-over, neither before nor after it.
7. If create_promise fails three times for one account, the promises that were recorded stay, and that account is noted system_fault.

Closing with several accounts. If at least one promise was recorded, the result is arrangement, also when a hand-over follows it. With no promise: if every account is noted already_paid, the result is settled. Otherwise the result is no_arrangement with the code of the first account, in the order returned, whose note is not already_paid.
