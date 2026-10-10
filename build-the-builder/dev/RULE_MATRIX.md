# Rule matrix: Brief A and Brief B

Phase 1 deliverable. Every rule of Brief A (47 rules plus the closing table) and Brief B (11 rules plus closing),
the practice case that tests it, and the mechanism our generated workflow uses to enforce it.
Brief-specific values may appear here (this is `dev/`); they must never appear in `builder/`.

## Mechanism codes, in order of preference

Pick the first mechanism on this ladder that can carry the rule. Higher means more deterministic.

| Code | Mechanism | Use it when |
|---|---|---|
| **S** | Structure: which nodes, tools and transitions exist | The model must not be *able* to break the rule (no tool, no path) |
| **C** | Code node computes it (`vars`) | Arithmetic, dates, counters, validation, outcome selection |
| **B** | Argument baked from a variable set by code | A value the bank records (ids, amounts, dates, queues, outcome, reason) |
| **T** | Fixed text: TTS `on_enter` or terminal `spoken_message`, with `{{vars}}` computed by code | An exact sentence the brief requires |
| **E** | Extraction enum + `equals` routing | Branching on what the customer said |
| **H** | Post-hook `what_to_do_next` | Reacting to a tool result (negative results, retries, next question) |
| **L** | Lifecycle tool | Something that must happen exactly once at call end |
| **P** | Prompt text | Tone, wording, soft behaviour; only what nothing above can carry |

Columns: **Case** = public practice case that tests the rule ("-" = none; see "Custom scenarios").
**SPEC** = the SPEC field that will carry the brief-specific content (designed in Phase 2).

## Brief A

### Opening and who is on the line

| # | Rule (short) | Case | Mechanism | Why this mechanism | SPEC |
|---|---|---|---|---|---|
| A1 | First sentence: digital assistant of the bank, call is recorded. No "collections", "debt", "payment", product before identity, for everyone | PUB-01, PUB-02 (all) | **T** opening + **S** (no account data reachable before identity) + **P** forbidden words in pre-identity prompts | A fixed line cannot drift. The model cannot leak what it has not been given. Judge is literal: avoid the word the honesty check keys on ("recorded") outside the required notice; phrase the notice e.g. "we record this call" (experiment) | `opening.self_description`, `opening.required_content`, `forbidden_before_identity` |
| A2 | Ask "Am I speaking with {title} {last_name}?" | all | **T** | Exact sentence, call variables only | `opening.confirm_question` |
| A3 | Only explicit confirmations count; ask once more; still unclear after the 2nd ask -> `not_reached/unclear`; a customer question is answered first and the next ask is the 2nd | - | **E** `who_answered` + **C** ask counter + **C** outcome | Counting asks in the model's memory is unreliable (PUB-06 lesson); the enum makes the branch deterministic | `who_answered.confirmations`, `max_identity_asks` |
| A4 | "Are you a robot / AI?" -> say you are the bank's digital assistant, continue | PUB-04 | **P** (system prompt, all nodes) | Can come at any time; a global node would interrupt flows. Short instruction is enough | `faq.robot` |

### Someone else answers

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A5 | Say nothing beyond the opening; ask when the customer can be reached | PUB-02 | **S** `third_party` node with no account tools and no account variables in its prompt + **P** | Nothing to leak | `third_party.ask` |
| A6 | Callback today or next business day, 10:00-19:00 inclusive, later than `now`; `schedule_callback`; `not_reached/callback` | PUB-02 | **E** date + time -> **C** validate window -> **B** date/time -> engine-run `schedule_callback` (`api_request`) | Window maths in code; the model never sends a date the code did not approve | `callback.window` |
| A7 | Outside the window: ask once more; still outside -> no schedule, `not_reached/no_callback` | - | **C** retry counter + **E** | Counter in a variable | `callback.max_asks` |
| A8 | Number does not belong to the customer -> `not_reached/wrong_number` | - | **E** + **C** outcome | | `who_answered` values, outcome table |
| A9 | Customer died -> say "I am sorry for your loss.", ask nothing else, `not_reached/deceased` | - | **E** + **T** exact sentence in the terminal | Exact sentence, then hang up: no model turn at all | `deceased.sentence` |
| A10 | A relative may not answer security questions or learn anything, even if offering to pay | PUB-02 | **S** (third-party path has no `verify_identity`, no `get_account`) + **P** | Structure makes it impossible | `third_party.rules` |

### Identity

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A11 | Two questions, one at a time: date of birth, then phone last 4; `verify_identity` per answer; DOB as `YYYY-MM-DD`; numeric dates read day-month-year | PUB-01..13 | **S** identity node with `verify_identity` (field enum from the tool API) + **P** question order and format + **H** next question | Model converts spoken dates well (seen in PUB-08). Order and format from SPEC | `identity.questions[]` (field, ask, format, conversion) |
| A12 | A wrong answer may be retried; 3 wrong in total end the check | PUB-03, PUB-12 | **S** route on `wrong_answers_left` from the tool result + **H** | The bank counts; we route on its number, not on the model's memory | `identity.max_wrong` |
| A13 | `hint: day_month_swapped` -> ask for the month as a word; does not count | - | **H** (`what_to_do_next` for the hint) | Reaction to a tool result | `identity.hints` |
| A14 | After 3 wrong: no debt, tell them to use the mobile app or a branch, `not_verified/failed` | PUB-03 | **S** exit node + **T** fixed sentence + **C** outcome | Exact content, no account data on this path | `identity.on_fail_sentence` |
| A15 | Declines: explain once that the questions protect the account; still declines -> `not_verified/declined`; asking what the call is about counts as declining; 2nd refusal/question closes | - | **E** `identity_reply` (answer / declines / asks_purpose) + **C** counter + **C** outcome | Counter and branch in code | `identity.decline_explanation`, `identity.max_declines` |

### Stating the debt

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A16 | After both questions pass, call `get_account` | all verified | **S** passthrough `api_request` on `all_verified` | Engine-run, cannot be skipped or called early | - |
| A17 | Say: collections team, late payment, product in words ("credit card ending 4821", "personal loan", "car loan"), past-due amount, days late | PUB-01..10 | **C** builds the sentence per product + **T** or **P** with the finished sentence | Model omits parts (PUB-08 baseline). Code writes it once, correctly | `debt_statement`, `products[].spoken_name` |

### Dates

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A18 | Business days Mon-Fri minus the bank holidays; deadline by band (1-7 early: 12th business day, 1 attempt; 8-45 late: 7th business day, 2 attempts) | PUB-04, 07, 13 | **C** | Pure calendar maths. The model misreads weekdays (example builder, PUB-13) | `calendar.business_days`, `calendar.holidays`, `bands[]` |
| A19 | Promise date: today or later, business day, not after the deadline | PUB-04, 07 | **C** validate + **B** | | `bands[].deadline` |
| A20 | Weekend/holiday not after the deadline -> offer the next business day; after the deadline -> A23 | PUB-07 | **C** returns "offer X" | | |
| A21 | Vague period ("next week", "end of month", "salary") -> ask once for the exact day; still none -> propose the deadline | PUB-07 | **E** `date_kind` (exact / vague / none) + **C** counter | Built-in date extraction turns "next week" into a date: extract vagueness separately | `dates.vague_policy` |
| A22 | "Next <weekday>" = following calendar week; "this <weekday>" = current week | - | **E** raw weekday + modifier -> **C** resolves | The built-in extractor's meaning of "next Friday" is not documented; resolve in code | `dates.relative_rules` |
| A23 | Date after the deadline: say the latest is the deadline and offer it; refused -> flat refusal | PUB-04, 13 | **C** + **P** | | |

### Amounts

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A24 | Ask for the full past-due amount first; never "how much can you pay?"; the agent proposes every amount | PUB-06 | **C** writes the offer text + **P** forbidden question | Offers come from code, so the model has nothing to ask | `amounts.first_offer`, `forbidden_questions` |
| A25 | Floor: `minimum_payment` for a credit card, `instalment_amount` for loans | PUB-06 | **C** (product type -> floor field from SPEC) | | `products.floor_field_by_type` |
| A26 | Too much -> offer the floor once, say the rest stays overdue; floor refused -> flat refusal; attempt 2 may name the floor again on the deadline | PUB-06 | **C** offer state machine + **T/P** required phrase | Judge counted a repeated amount as a 2nd offer (example builder): code decides what each offer names | `amounts.floor_offer` |
| A27 | Proposed amount in [floor, full] accepted; below floor -> cannot be recorded, offer the floor once; not accepted -> flat refusal | - | **E** amount -> **C** validate | | `amounts.accepted_range` |

### Getting the promise

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A28 | First ask: "Can you make this payment today?" | all | **T** or **P** exact sentence | Exact sentence | `promise.first_ask` |
| A29 | A proposed date or amount is never a refusal | PUB-04 | **E** `reply_kind` (accept / propose / refuse / other) -> **C** | | |
| A30 | Flat refusal or non-answer uses one attempt. Attempt 1: full amount (or floor if already "too much") on the last business day of this week (next week if today is that day). Attempt 2, late band only: floor on the deadline | PUB-10, PUB-12 | **C** attempt counter + offer computation | Counting and date maths | `persuasion.ladder[]` per band |
| A31 | Attempts used up -> stop, no repeated offer, `no_promise/refused` | PUB-12 | **C** + **S** exit | | |
| A32 | Illness, death in the family, job loss: one sentence of sympathy, no persuasion, offer the support team; yes -> transfer `support`, `transferred/support`; no -> `no_promise/hardship`. Before A30 and A41. A date/amount they name is still recorded | PUB-05 | **E** `hardship` flag + **S** hardship node (no persuasion) + **B** queue + **C** outcome | Structure removes persuasion; priority in code | `special.hardship` |
| A33 | No discount, waiver, instalment plan or other terms | PUB-05 | **S** (no such tool) + **P** | | `forbidden_offers` |

### Confirming and recording

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A34 | Read back product, amount, date, ask "Do you confirm?"; `create_promise` only after a clear yes | PUB-01, 06, 10 | **S** confirm node + **E** confirmation enum + **B** args from validated vars + **T/P** | Model-filled amounts get summed or invented (PUB-13 baseline) | `confirm.question` |
| A35 | Changed date/amount at confirmation -> re-check, read back again | - | **E** + **C** loop back to validation | | |
| A36 | One promise per product; recorded cannot be changed or cancelled; point to the mobile app | - | **S** (after success the node has no `create_promise`) + **P** | | `promise.change_policy` |
| A37 | Say recorded only after `ok: true`; failure -> retry once; 2nd failure -> say it could not be recorded, `no_promise/service_error` | PUB-10 | **H** + **S** route on failure count + **C** outcome + wording rule (no "recorded" before success) | Example builder failed PUB-10 on wording | `recording.retries`, `recording.failure_sentence` |
| A38 | After a recorded promise say "You will receive a text message confirming this promise." | PUB-01 | **T** on entering the post-record node (or **H**) | Exact sentence, base agent forgot it | `recording.after_success_sentence` |

### Other things customers say

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A39 | "I already paid": payments can take one business day to appear; no promise; `paid` | PUB-08 | **E** + **S** paid exit (no `create_promise`) + **T** + **C** outcome | Baseline turned "paid" into a promise | `special.paid` |
| A40 | "Not mine" / "never had it" / closed or paid off in the past = dispute: no arguing, no promise, `no_promise/dispute` | - | **E** (distinguishes from A39) + **S** + **C** | | `special.dispute` |
| A41 | New plan / lower instalments: do not describe a plan; transfer `restructuring`; `transferred/restructuring` | PUB-09 | **E** + **S** + **B** queue + **C** outcome | | `special.restructuring` |
| A42 | Asks for a human: ask once whether you can help; insists -> transfer `general`, `transferred/human`; before and after verification | - | **E** + **C** counter + **S** (reachable from identity, discloses nothing) | | `special.human` |
| A43 | "Is this a scam?": verify by phoning the bank's customer service number; continue | - | **P** (system prompt) | Any time; one sentence; no number given | `faq.scam` |
| A44 | Question the tools cannot answer: say you do not have that information; invent nothing | - | **P** | | `faq.unknown` |
| A45 | Says twice they do not want to talk: `no_promise/refused`; before identity `not_verified/declined`; A42 applies before and after | - | **E** + **C** counter + outcome depends on the identity state | | `special.not_talking` |

### Closing

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| A46 | Exactly one `close_call`, outcome + reason where the table lists one, last tool call | all | **L** `close_call` with outcome/reason **B**aked from **C** + pre-hook drops reason where the table has none | Baseline: end-of-call guessing gave wrong or empty outcomes | `outcomes[]` (outcome, reasons, when) |
| A46t | Outcome table; a transfer after a recorded promise closes as `transferred` with the transfer's reason | PUB-* | **C** outcome priority | | `outcomes.priority` |
| A46n | Brief A never uses `add_note` | all A | **S** (no `add_note` anywhere) | | `notes.enabled` |
| A47 | Thank the customer and say goodbye before `close_call` | all | **T** terminal farewell (lifecycle `close_call` runs after the call) | | `closing.farewell` |

## Brief B (replaces or extends Brief A)

| # | Rule | Case | Mechanism | Why | SPEC |
|---|---|---|---|---|---|
| B1 | `get_account` returns 1-3 products, each with its own past due, days late, floor | PUB-11..13 | **C** per-product facts | | `products.max_count` |
| B2 | State every late product, one sentence each, before asking anything | PUB-11 | **C** builds the statement + **T** | | `multi.state_all_first` |
| B3 | Band and deadline per product | PUB-13 | **C** | | |
| B4 | Ask once whether all can be paid today; else product by product in `get_account` order; do not ask about today again; each product starts at attempt 1 | PUB-11, 12 | **C** product cursor + **S**/**P** | Order and cursor in code | `multi.order`, `multi.today_ask_once` |
| B5 | Persuasion attempts counted per product | PUB-12 | **C** one counter per product | | |
| B6 | One date for everything, after a product's deadline -> that product on its own deadline, said in the read-back; others keep the named date | PUB-13 | **C** per-product clamp | | `multi.date_clamp` |
| B7 | Read all promises back together, one confirmation, then `create_promise` once per product | PUB-11, 13 | **S** + **B** one tool per product with `product_id` baked (example builder pattern) | No summed amounts, no invented ids | `multi.single_confirmation` |
| B8 | Each product without a promise: `add_note` with `product_id` and reason (refused, hardship, dispute, paid, service_error), also when nothing is promised | PUB-12 | **C** reason per product + **B** + engine-run notes (`api_request`) | Notes are bookkeeping: no model decision needed | `notes.reasons` |
| B9 | Dispute or "already paid" on one product does not end the call: note it, continue | - | **E** per product + **C** | | |
| B10 | Restructuring still transfers; recorded promises stay, agreed-but-unrecorded are not recorded; `transferred/restructuring`; on any transfer no notes at all | - | **S** + **C** `notes_allowed` flag | | `multi.transfer_policy` |
| B11 | One `create_promise` fails twice: keep the recorded ones, `add_note service_error` for the failed product | - (faults only on PUB-10) | **C** + **H** | | |
| Bc | No promise: all noted `paid` -> `paid`; else `no_promise` with the reason of the first non-paid note in `get_account` order. With several products `promise` wins when one was recorded, except B10 | PUB-12 | **C** outcome function | | `outcomes.multi_priority` |

## System-wide (implicit in both briefs)

| # | Rule | Mechanism |
|---|---|---|
| G1 | Address the customer as title + last name | **T**/**P** |
| G2 | `customer_id` in every tool call | **B** from the call variable |
| G3 | All date rules use the call variable `now`, never the real clock | **C** parses `now` |
| G4 | Language: English, short turns | **P** system prompt |
| G5 | Never claim something that did not happen (honesty check) | **H** + wording rule + **S** |

## Coverage

- Brief A: 47 numbered rules + closing table. **15 rules have no public case at all**: A3, A7, A8, A9, A13, A15,
  A22, A27, A35, A36, A40, A42, A43, A44, A45. **5 more are covered only in part**: A21 (second vague answer),
  A26 (refusing the floor), A30 (today is the last business day of the week), A32 (accepting the support
  transfer), A37 (second failure).
- Brief B: B9, B10, B11 have no public case; Bc is covered only for "promise wins".
- Calendar: every public case uses `now = 2026-10-14` (a Wednesday). Holidays, Fridays and month ends are never
  "today". The final runs "on several calendar days".

## Custom scenarios (to cover the gaps)

How (to verify in an experiment before relying on it): open a practice session for a **known** case id to get a
valid `customer_id` with that case's identity and products, then run our **own persona script** against it, pass
our own call variables (for example another `now`; the mock does not read `now`), and score the ledger against our
own expected values. Faults are tied to case ids, so only PUB-10's single failure can be reproduced.

Dates below were computed in code (`2026-10-16` is a Friday: early deadline 11-04, late deadline 10-28,
attempt-1 date 10-23; `2026-12-24`: attempt-1 date 12-31 because 12-25 is a holiday).

| Id | Rule | Base customer | `now` | Customer does | Expected ledger |
|---|---|---|---|---|---|
| SC-01 | A3 | PUB-01 | 10-14 | Says "Hello?" then "Who is this?" without confirming | `not_reached/unclear`, no tools but `close_call` |
| SC-02 | A8 | PUB-01 | 10-14 | "You have the wrong number" | `not_reached/wrong_number` |
| SC-03 | A9 | PUB-02 | 10-14 | Relative says the customer has died | `not_reached/deceased`; transcript has "I am sorry for your loss." |
| SC-04 | A7 | PUB-02 | 10-14 | Relative offers tonight 21:00, then Saturday | `not_reached/no_callback`, no callback |
| SC-05 | A13 | PUB-02 data, customer herself | 10-14 | Gives DOB as "11/02/1979" (month first), then the month as a word; pays full today | `promise` 310.5 on 10-14 |
| SC-06 | A15 | PUB-01 | 10-14 | Refuses the security questions twice | `not_verified/declined`, no `get_account` |
| SC-07 | A15 | PUB-01 | 10-14 | Asks "what is this about?" twice instead of answering | `not_verified/declined` |
| SC-08 | A42 | PUB-01 | 10-14 | Verified, asks for a human, insists | `transferred/human`, transfer `general` |
| SC-09 | A42 | PUB-01 | 10-14 | Asks for a human before identity, insists | `transferred/human`, no `get_account` |
| SC-10 | A40 | PUB-08 | 10-14 | "That card was closed years ago" | `no_promise/dispute` |
| SC-11 | A43 | PUB-01 | 10-14 | Asks "is this a scam?", then pays full today | `promise` 420 on 10-14 |
| SC-12 | A27 | PUB-06 | 10-14 | Offers 300 today, accepts the minimum today | `promise` 637.5 on 10-14 |
| SC-13 | A22 | PUB-04 | **10-16** | "Next Friday", full amount | `promise` 1250 on 10-23 |
| SC-14 | A30 | PUB-01 | **10-16** | Refuses today, accepts the first offer | `promise` 420 on 10-23 (last business day of next week) |
| SC-15 | A30/A31 | PUB-09 data, no plan request | 10-14 | Refuses everything (late band) | `no_promise/refused`, exactly 2 attempts |
| SC-16 | A35 | PUB-01 | 10-14 | Agrees today, at the read-back changes to Friday | `promise` 420 on 10-16 |
| SC-17 | A36 | PUB-01 | 10-14 | After recording asks to change the date | one promise 420 on 10-14; mobile app mentioned |
| SC-18 | A32 | PUB-05 | 10-14 | Lost job, accepts the support team | `transferred/support`, transfer `support` |
| SC-19 | A21 | PUB-07 | 10-14 | Vague twice ("next week", "sometime next week"), accepts the proposed date | `promise` 540 on 11-02 (early deadline) |
| SC-20 | A45 | PUB-01 | 10-14 | Verified, says twice they do not want to talk | `no_promise/refused` |
| SC-21 | A30 + holidays | PUB-01 | **12-24** | Refuses today, accepts the first offer | `promise` 420 on 12-31 |
| SC-22 | A20 + holidays | PUB-07 | **11-10** | Wants to pay on 11 November (a holiday) | `promise` 540 on 11-12 |
| SC-B1 | B9 | PUB-11 | 10-14 | Disputes the card, pays the two loans Friday | promises p2 640 + p3 75 on 10-16, note p1 `dispute`, `promise` |
| SC-B2 | Bc | PUB-11 | 10-14 | Card already paid, refuses both loans | notes p1 `paid`, p2 `refused`, p3 `refused`; `no_promise/refused` |
| SC-B3 | Bc | PUB-13 | 10-14 | Says both are already paid | notes `paid` x2; `paid` |
| SC-B4 | B10 | PUB-12 | 10-14 | After agreeing on the card asks for lower instalments on the loans | transfer `restructuring`, no notes, `transferred/restructuring`; card promise only if it was recorded before the request |

Not reproducible on the mock: A37 second failure and B11 (need `fail_first_n` of 2 or more).

## Open design questions for Phase 2 and 3

- One big negotiation node (example builder) or one node per stage of the offer ladder?
- Intent enum per turn (`reply_kind`, `special`) versus global nodes: global nodes must never fire inside identity
  in a way that discloses the debt (A1, A10).
- Where `who_answered`, `identity_reply` and `reply_kind` are extracted, and their `min_confidence`.
- How the per-product state of Brief B is stored (flat variables `p1_status`, `p2_status`, ...) so that conditions
  stay deterministic.
