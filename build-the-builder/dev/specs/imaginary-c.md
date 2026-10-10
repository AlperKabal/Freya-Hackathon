# Imaginary Brief C: Northwind Business Bank, overdue business accounts

Written by us to test that the SPEC schema is general. Not an organiser brief. Everything differs from Brief A on
purpose: business customers, other identity questions, three bands, Saturdays as business days, a calendar-day
deadline, other outcome, reason, queue and field names, and a new situation.

## Call variables

| Variable | Meaning |
|---|---|
| `account_ref` | Pass it to every tool call. |
| `company_name` | The business that owes the money. |
| `contact_name` | The person to ask for, by full name. |
| `today` | The current date and time. |

## Opening

1. Say: "Good morning, this is the automated assistant of Northwind Business Bank. This call may be recorded."
2. Ask: "May I speak with {contact_name} from {company_name}?"
3. Only "yes" or the contact's name counts. Ask at most three times, then close as `no_contact` / `unconfirmed`.
4. Never say "arrears", "overdue" or "debt" before verification.

## Someone else answers

5. Ask for a callback within the next two business days, not today, between 09:00 and 17:30. Ask once more if the
   time is outside. Close as `no_contact` / `callback_booked` or `no_contact` / `callback_refused`.
6. If the business has closed down, close as `no_contact` / `business_closed`.

## Verification

7. Ask the company registration number, then the year the company was founded. Two wrong answers end the check:
   close as `unverified` / `wrong_answers`. A refusal closes as `unverified` / `refused_security`.

## The debt

8. Products: `business_loan` (floor: `min_due`), `overdraft` (floor: `min_due`), `equipment_lease` (floor:
   `lease_rate`). Say "your business loan", "your overdraft", "your equipment lease ending {lease_ref}".
9. Business days are Monday to Saturday, except 2027-01-06 and 2027-04-23.

| Days overdue | Deadline | Attempts |
|---|---|---|
| 1 to 10 | 15 calendar days from today, moved to the next business day | 1 |
| 11 to 30 | the 10th business day after today | 2 |
| 31 to 90 | the 5th business day after today | 3 |

10. Attempt 1: the full amount at the end of this month (last business day of the month). Attempt 2: the floor on
    the deadline. Attempt 3: half of the overdue amount on the deadline.
11. Up to three products. Note each product without an agreement with reason `declined`, `contested`, `settled` or
    `system_error`. One read-back for all.

## Situations

12. Insolvency or administration: do not negotiate, transfer to queue `specialist`, close `escalated` / `insolvency`.
13. Wants an account manager: transfer to `account_manager` at once, close `escalated` / `manager_request`.
14. Already settled: say it can take two business days to show; note `settled`; close `settled`.

## Closing

| Outcome | Reasons |
|---|---|
| `agreed` | none |
| `settled` | none |
| `escalated` | `insolvency`, `manager_request` |
| `no_agreement` | `declined`, `contested`, `system_error` |
| `unverified` | `wrong_answers`, `refused_security` |
| `no_contact` | `unconfirmed`, `callback_booked`, `callback_refused`, `business_closed` |
