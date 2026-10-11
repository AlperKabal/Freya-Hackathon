# Mock briefs

Briefs we wrote to test the builder on rules it has not seen. None of them is an organiser brief, and nothing in
this folder may be copied into `builder/`. Only new files were added; no existing file was changed.

    python dev/test_mock_briefs.py                    # everything: no key, no model, about one minute
    python dev/test_mock_briefs.py packs d            # one section (packs universal variants odd random answers forms), some packs
    python dev/test_mock_briefs.py --only D-65 -v     # one customer: what the agent said, and the ledger
    python dev/test_mock_briefs.py variants --only no_callback
    python dev/run_mock_briefs.py --extract           # with the Claude login: read each pack's documents, compare with the oracle, walk the customers
    python dev/run_mock_briefs.py --simulate <agent>  # with the Freya keys: pack F's customers on the platform
    python dev/mock_briefs/make.py                    # rewrite the generated files after a change

A FAIL is a difference between what a brief's text requires and what the generated agent does. Tier 1: a rule of
the kind the final briefs announce. Tier 2: a plausible rule the kit's briefs do not have. Tier 3: exotic, or seen
only when a call is made on a day that is no business day. The exit code is 1 while a tier-1 check fails.

## What is here

| Part | What it is |
|---|---|
| `d-harbor-raw/` | consumer bank, raw bank material: an e-mail, a handbook extract, a memo that changes five rules, a code list (`;`-separated, quoted cells, one row the assistant never uses). Identity `postcode` + `birth_year`, outcome `unreached`, every tool field renamed, OpenAPI 3.1 with `$ref` and `allOf`, three bands, a calendar-day deadline rolled back, year-end closure days, a weekend day that is refused and not replaced, a product without a minimum, up to three accounts. 91 customers |
| `e-meridian-clean/` | business bank, one clean specification of 56 rules. Identity `company_number` (leading zero) + `founded_year`, outcome `no_contact`, an API that answers `success` and never says how many tries are left, Saturday as a business day, a month-end deadline, a band with no persuasion attempt, half of the amount, attempts counted for the whole call, no note for a refusal, no retry, a callback the contact asks for, `local_time` with a space. 84 customers |
| `f-freya-sibling/` | the kit's Brief A and B with twelve rules changed at once, on the kit's own tool API: the only pack that can be simulated on the platform. Each of its 23 customers borrows a practice customer and has a persona text and judge criteria |
| `g-meridian-raw/` | pack E's rules again, as raw bank material: an e-mail (plain text), a policy extract, a memo that changes six rules (a table cell, the holiday list, the callback rule, how attempts are counted, a band's attempts, the retry), an outcome list with a retired code, and a second code list for the facility types. Holidays are written in words. Same oracle SPEC and customers as E |
| `h-harbor-clean/` | pack D's rules again, as one clean specification of 56 rules with every value final. Same oracle SPEC and customers as D |
| `universal.py` | customers made from a SPEC alone: pays, refuses everything, too much, a date too late, a day that is no business day, a promise that cannot be saved, one per special situation, a callback, nobody confirms, the security questions. Their right endings are read from the SPEC's own rules. About 45 per SPEC and day |
| `variants.py` | 68 one-rule changes of a pack's SPEC (each with the sentence a brief would carry): every switch and number that D, E and F leave at one value |
| `lib.py` | what is independent of the builder: a day-by-day calendar (`Cal`), a stand-in bank that speaks the pack's own field names and refuses what an API would refuse (`Bank`), a walker for whole calls (`Sim`), the reactive customer, and what must hold in every call (`always`) |
| `make.py` | writes each pack's `tool-api.json`, `spec.json` (the oracle: what a careful reader takes from the documents) and pack F's documents |

The final gives one clean specification and one set of raw bank material, and does not say which bank gets which
form. So each bank is here in both forms (D and H, E and G): the Reader must bring the same SPEC back from either.
For every pack the test checks that its documents carry each name, holiday and prescribed sentence of its oracle
SPEC as written.

The identity questions and outcome names of D and E are not guesses: the kit's `tools/run_cases.py` already knows the
answers `postcode`, `birth_year`, `company_number` and `founded_year`, its `in_words` style says "Postcodes, years
and other codes you say digit by digit", and `tools/score.py` knows the outcomes `no_contact` and `unreached`.

The walker runs every code node, hook, engine-run bank call and deterministic transition of the generated workflow
for real. What the phone model would do (classify a reply, call a tool, take a transition) is given by the customer.
So it finds what code decides wrongly and what a fixed sentence says wrongly; it cannot find a model that classifies
wrongly. Mode v1 is walked up to the negotiation only: there the model decides.

## Findings on commit 92b2a45

### Tier 1

1. **"I already paid" on the last open product: the required sentence is never said.** With notes on (every Brief B
   kind of brief) a product-scope situation's sentence is put in front of the next offer; when no product is left
   the call closes and the sentence is lost. The ledger is right, the judge's sentence check is not. Seen on the
   team's own `dev/specs/brief-ab.json` and `imaginary-c.json` too; Brief A's agent is not affected.
   (`D-65`, `E-58`, `F-16`, universal `sit-already_paid`)
2. **The last recording failure is never told to the customer when no promise was recorded.** `finalize` adds
   `failure_say` only without an `outcomes.multi` rule; with one the farewell is the plain goodbye. Same SPECs as 1.
   (`D-61`, `E-50`, universal `norecord`)
3. **A date of birth given in numbers is read month first, with Brief A's own format words.** In
   `snippets/answers.py` the test for "month first" (`mm[-/. ]dd`) matches inside "YYYY-MM-DD", which is in every
   date question's format. `14/03/1988` goes to the bank unchanged, `05/03/1988` goes as `1988-05-03`. The bank's
   swap hint and its "unreadable" answer hide it (neither counts as wrong), at the price of a turn. `test_answers.py`
   passes because its hint has no "YYYY-MM-DD". (section `answers`)
4. **A code said character by character is sent as words.** "L S six, two A B" reaches the bank as `LSSIX,TWOAB`:
   for a text answer number words are not turned into digits and punctuation is kept. The kit's own `in_words`
   style talks this way. The model may tidy it first; the hook is the net under it. (`D-14`, section `answers`)

### Tier 2

5. **`third_party.callback.enabled: false` leaves a node nobody can reach** (`set_callback_scheduled`), in both
   modes: `verify.lint` reports it, so every candidate of such a brief carries a local problem. (`e+no_callback`)
6. **Notes on, but no `outcomes.multi` rule: every call without a promise closes as the refusal.** Hardship
   declined, a dispute, "already paid" and a failed recording all close as `attempts_exhausted`. A one-product brief
   that uses `add_note` has no closing rule for several products. (`f+one_product_with_notes_no_closing_rule`)
7. **An evidence word that is part of a product name is dropped.** "person" is in "personal loan", so "Can I speak
   to a real person?" is not acted on the first time and a persuasion attempt is used instead. (`D-69`)
8. **A day that is refused, not replaced** (`non_business_day: reject`, `after_deadline: reject`): the agent says
   "That day is not possible." and then repeats its open offer, which names today, instead of asking for another
   day. With several products the first one's attempt 1 is used up as well. (`D-34s`, `E-40`, `D-89`)
9. **An attempt "in three days" is offered on a Sunday.** A persuasion date counted in calendar days is not moved to
   a business day, and a yes to it is recorded on that day. (`d+attempt_in_calendar_days`)
10. **A date more than ten weeks ahead is said as digits** ("... on 2027-01-29?"): the table of spoken dates covers
    70 days. The same happens with a deadline that lies before today. (`d+deadline_sixty_business_days`)
11. **Half of an odd amount**: `round(212.625, 2)` is 212.62; the brief (and a scorer that rounds half up) says
    212.63. (`E-44`)
12. **When no day is possible** (the earliest day is after the deadline) the agent still offers and records the
    deadline. (`d+earliest_tomorrow`, `d+earliest_next_business_day`, on the last business day before Christmas)
13. **Answers in less common words** are sent as they are: "It's LS6 2AB", a code with a comma or a dash, a code in
    two turns, "the number is zero eight one...", "'84", "in eighty-four", a date digit by digit, a brief that asks
    for small letters. (section `answers`, 15 of 28)

### Tier 3

14. **Calls on a day that is no business day.** With several products and a refused weekend day, a yes to "today"
    uses persuasion attempts; when none is left (or the call's limit is reached) a customer who wanted to pay ends
    without a promise (`d+no_attempts_at_all`, `d+attempts_for_the_call`). When "today" is asked per product, the
    later products are recorded on that day (`d+one_by_one`, `d+today_asked_per_product`). A deadline that has
    already passed is offered (`d+deadline_is_the_weeks_end`, pack D on 24 December). More than 15 closure days in a
    row defeat the search for the first possible day (`d+holiday_run`).
15. **A tool API that requires a text with every note**: no note can be sent; lint says so. (`d+note_text_required`)

A question for the team, not a finding: `dev/specs/brief-ab.json` gives `not_talking` no note. Brief B rule 8 says
every product without a promise is noted, "also when no product gets a promise". Pack D states this case in so many
words (3.9 f) and the generated agent follows it there.

### What holds

51 of the 68 one-rule variants end every universal customer as the changed rule requires, among them: another
number of identity questions and of wrong answers, one band or four, a month-end or calendar-day deadline, another
business week, no holidays, another callback window, minimum first, only the full amount, at least half, one try or
four, each promise read back on its own, products stated one by one, attempts for the whole call, promises recorded
before a transfer, no notes with several products, an outcome table without reasons, no special situation at all,
and the call's time with seconds, with a zone or with a space. Nine odd accounts per pack (an unknown product type,
no band, a minimum above the debt, amounts as text, one cent, one product too many) end without an error. 750
unscripted customers break nothing on a business day. Every document survives eight file forms (byte-order mark,
UTF-16, Windows-1252, Windows line ends, Word, PDF, Excel) and the seven tools are read alike from Swagger 2,
CamelCase paths without operation ids, extra operations and nullable types.

## Rules the SPEC cannot say

From reading `builder/spec_schema.py`, not from a run. A brief with one of these is read into the nearest thing
the SPEC has, or into a free rule that the orchestrated negotiation does not act on:

- a deadline on a fixed date, or taken from a field of the account (a statement date);
- a day that is no business day replaced by the business day **before** it;
- a limit of wrong answers per question (when the API does not report the tries left);
- products in another order than the tool returned them (most overdue first);
- a close that depends on whether all or only some products were promised, or on full against part payment;
- another close when a callback the customer asked for cannot be booked (the third party's close is used);
- another success field per tool (the callback booking reads the identity tool's);
- an amount the customer must be asked to name;
- how a percentage is rounded;
- callback hours that differ by weekday;
- a language other than English (the sentences of `snippets/negotiation.py` are English).
