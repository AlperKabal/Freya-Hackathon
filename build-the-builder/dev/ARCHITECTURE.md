# Architecture: a multi-agent builder that generates a specialist-node phone agent

Status: design for Phase 3 (generator) and Phase 4 (extraction). Read with `RULE_MATRIX.md` and `JOURNAL.md`.

## 0. Where the agents go, and why

"More than one agent" can live in two places. We put it where it helps and keep it out of where it hurts.

| | **Builder** (build time, our machine) | **Phone agent** (call time, on Freya) |
|---|---|---|
| Agents | Several LLM agents with separate jobs that check each other | One workflow whose nodes are narrow specialists, orchestrated by code nodes |
| Model | Any (Opus via the Agent SDK) | Fixed: `AGENT_LLM`, never changed |
| Cost of an extra agent | Seconds of build time, done in parallel | One more model call per customer turn: latency, and customers hang up after long silences |
| Failure mode | Caught by validation before anything is saved | Happens live, in 1 of 3 runs, and loses the customer |

### Why not separate Freya agents inside the phone agent (`invoke_agent`)

1. **Export portability.** The organisers load our exported workflow into *their* workspace ("what you export is what
   we score", README). A node that invokes another agent points at an agent id in *our* workspace. It does not exist
   there. The call breaks.
2. **Undocumented.** `invoke_agent` is listed in `docs/workflow-format.md` and explicitly not described.
3. **Rules.** "The phone agent runs on the model set in freya.py" and "may call only the bank's tool API". A second
   agent is at best a grey zone.
4. **Latency.** Every turn already makes three model calls (extraction, routing, dialogue). More agents per turn means
   more silence on the line.

### What we do instead: specialists + a code orchestrator, inside one workflow

Each turn is split by job, which is the accuracy benefit of multi-agent without its costs:

```
customer turn ─► EXTRACTION specialist   (understands: one enum + the raw words, per node)
              ─► CODE orchestrator       (decides: state machine in a passthrough code node, deterministic)
              ─► SPEAKER                 (says it: a fixed TTS line built by code, or a short LLM line when free wording is needed)
```

Most turns then cost **one** model call (extraction): routing runs on variables (no model) and TTS needs no model.
That is faster than the example builder's design, where a large negotiation node lets the dialogue model decide
everything and routes with seven `matches_intent` conditions.

## 1. The builder: agents and stages

**Decision (2026-10-10, Yaşar): light set = 1 Reader + Binder + Auditor**, to save Claude Pro quota and build time.
The Auditor's findings go back to the Reader for one repair round; code re-validates after it. The full design
below (two Readers + Adjudicator) stays documented as the upgrade path if extraction quality turns out too low in
Phase 4; switching only adds agents in stage 1 and 3, the rest is unchanged.

Original full design:

```
                       ┌────────────── Stage 1, in parallel ───────────────┐
brief files ─► ingest ─┤ Reader A  (rule by rule)      → SPEC draft A      │
tool API    ─► (code)  │ Reader B  (section by section) → SPEC draft B     │
                       │ Binder    (tool API + brief)  → tool_fields, result/product fields, enums
                       └───────────────────────────────────────────────────┘
                                       │
                 Stage 2 (code): validate both drafts against schema + tool API; field-by-field diff
                                       │
                 Stage 3 Adjudicator: only if drafts differ or fail validation; picks per field with a source quote
                                       │
                 Stage 4 Auditor (independent): brief + final SPEC, never the drafts; every brief sentence
                 must map to a SPEC field or free_rule; contradictions and omissions with quotes
                                       │  (at most one repair round, then code re-validates)
                 Stage 5 generate (code, deterministic): SPEC → workflow JSON
                                       │
                 Stage 6 verify: lint · local snippet tests on many `now` values · state-machine tests ·
                 dry run · chat smoke test · practice cases only with an explicit --practice flag
                                       │
                 Stage 7 save · export · trace
```

| Agent | Input | Output | Why a separate agent |
|---|---|---|---|
| Reader A | all brief files (with names and order), tool summary, SPEC schema + field docs | SPEC draft | Two independent readings: an error one makes, the other usually does not |
| Reader B | same, different instruction order (by brief section) | SPEC draft | Diversity is what makes the comparison useful |
| Binder | tool API file + brief | `tool_fields`, `identity.result_fields`, `account.product_fields`, `products_field`, hint values, floor fields | Field mapping is a different skill from reading policy; renamed fields (Phase 2 question: `queue` -> `team`) land here and nowhere else |
| Adjudicator | brief + both drafts + diff + validation errors | final SPEC | Resolves disagreements with evidence instead of averaging |
| Auditor | brief + final SPEC | list of omissions / contradictions with quotes | Fresh eyes; it never saw the drafts, so it does not inherit their mistakes |

Rules for every builder agent: JSON only, parsed defensively, one retry on invalid JSON; exact sentences copied
verbatim; conflicts resolved by the brief's own precedence (a later memo that says it replaces a rule wins); every
SPEC value carries a source quote in `rule_map`. Model and purpose of every call go to the trace.

Raw bank material (email + policy extract + memo + code list): the Readers get all files at once, with file names,
and are told to build one consistent rule set and to record each override in `free_rules` with both quotes.

Time budget (30-minute limit, tie-break on build time): Stage 1 in parallel ~2-4 min, Stage 3 often skipped, Stage 4
~1-2 min, generate + local tests < 10 s, dry run + chat < 1 min. Target under 10 minutes.

## 2. The phone agent: nodes

Every node below is generated from the SPEC. Names in `code font` are mechanisms, not brief values.

### 2.1 State (all strings, written by code)

| Variable | Meaning |
|---|---|
| `stage` | opening / third_party / identity / negotiation / confirmation / closing |
| `outcome`, `reason` | **always set**, updated at each stage so that a hang-up still closes with the best outcome for that stage |
| `asks`, `declines`, `cb_asks`, `count_<situation>` | counters for thresholds |
| `p<i>_id`, `p<i>_type`, `p<i>_due`, `p<i>_floor`, `p<i>_days`, `p<i>_band`, `p<i>_deadline`, `p<i>_name` | product facts, i = 1..max_products |
| `p<i>_status` | open / agreed / recorded / failed / noted |
| `p<i>_attempt`, `p<i>_offer_amount`, `p<i>_offer_date`, `p<i>_floor_offered`, `p<i>_note` | negotiation state per product |
| `cursor` | which product is being negotiated |
| `say_text`, `say_mode` | what the speaker says next, and whether it is TTS (exact) or LLM (free wording) |
| `calendar_text`, `date_facts` | finished facts for prompts, with weekday names from code |
| `transferred`, `notes_allowed` | transfer and note rules |

**Stale extraction rule.** Variables are never cleared on a transition (docs). After the orchestrator consumes an
extracted value, it writes `""` back to it, so the same answer can never be acted on twice.

### 2.2 Graph

```
setup (code, initial) ──► opening (conv, TTS opening + confirm question; extract who_answered)
                              │ code: opening_eval (asks counter, faq answer-then-reask)
          ┌───────────────────┼──────────────────────────────┬────────────────────┐
          ▼                   ▼                              ▼                    ▼
   third_party (conv)     identity (conv + verify tool)   situation exits     unclear exit
   extract day/time text  post-hook: next question,        (wrong number,      (opening.unclear)
   code: callback_eval    hints, wrong answers left       deceased, human)
   api: schedule_callback  code: identity_eval (declines)
          │                   │ all verified
          ▼                   ▼
     end nodes          load_account (api_request) ──► account_facts (code)
                              ▼
                         negotiate (conv: speaks say_text; extract reply_kind + day/amount text + product_ref)
                              │  always ──► negotiate_eval (code: date + amount rules, ladder, attempts, cursor,
                              │                            situations, next say_text, next node)
                              ▼
                         confirm (conv: TTS read-back of all products + question; extract confirm_reply)
                              │  always ──► confirm_eval (code)
                              ▼
                         record_p1 … record_pN (api_request, baked args, one retry each, TTS "try once more")
                              ▼
                         notes_p1 … notes_pN (api_request, only when notes_allowed and status needs one)
                              ▼
                         finish (code: final outcome from SPEC rules) ──► end (TTS: success sentence if recorded + farewell)

lifecycle tool: close_call with outcome/reason baked from variables; pre-hook drops reason where the SPEC says none
```

### 2.3 Node by node

**setup (code, initial, passthrough).** Parse `now` (role from SPEC). Write `today`, `calendar_text` (the next ~20
days with weekday names and business-day marks), callback window dates, default `outcome/reason` = opening.unclear.
Never raises; fallbacks for every variable.

**opening (conversation).** `on_enter` TTS = SPEC `first_sentence` + `confirm_question` (placeholders -> call
variables). Extraction `who_answered`: enum built from the SPEC: `confirmed`, `someone_else`, `unclear`,
`question`, plus one value per situation whose stages include `opening` (e.g. the SPEC's wrong-number and deceased
rows). Each value's description comes from the SPEC (`confirmations`, `non_confirmations`, `trigger`, `not_this`).
Transition `always` to `opening_eval`.

**opening_eval (code).** `confirmed` -> identity. `someone_else` -> third_party. A situation value -> that exit.
`question` -> faq answer (LLM mode) then re-ask; counts as an ask. `unclear` -> re-ask; at `max_asks` -> unclear exit.

**third_party (conversation, no tools, no account data).** Speaks per SPEC instructions. Extracts `cb_day_text`,
`cb_time_text`, and the opening-stage situations. `third_party_eval` (code) resolves the day with
`dates.resolve_spoken_date`, parses the time, checks the window (include_today, business_days_ahead, start/end,
inclusive, after `now`); valid -> `schedule_callback` (api_request, date/time baked) -> callback exit; invalid ->
ask again (cb_asks); at max -> no-callback exit.

**identity (conversation + `verify_identity`).** Prompt: the SPEC questions in order, one at a time, answer formats
and conversions; `field` enum from the tool API; `answer` model-filled. Post-hook (`what_to_do_next`): verified ->
"Correct. Now ask: <next question>"; all verified -> "Verified. Say nothing about the account yet."; wrong with
attempts left -> "Not correct. Ask the same question again."; hint -> the SPEC hint instruction; `ok` false
(unreadable) -> "Ask again in the format <format>". Extraction `identity_reply`: answering / declines / asks_purpose
/ + identity-stage situations. Routing: all_verified true/True -> load_account; wrong_left == 0 -> failed exit;
`identity_eval` counts declines (purpose questions count when the SPEC says so) and situation thresholds.

**load_account (api_request) + account_facts (code).** Products from `products_field` via `product_fields`;
per product: type -> spoken name (placeholders = product fields) and floor field, band by days late, deadline by
the band's rule, ladder dates. Builds `say_text` = statement intro + one sentence per product (Brief B: all before any
ask) + the first ask (`first_ask_all` when several products and the SPEC enables it). Failure -> service-error exit.

**negotiate (conversation) + negotiate_eval (code): the core.** The node speaks `say_text`: TTS when the SPEC sentence
must be exact (first ask, floor offer with "the rest stays overdue", deadline offer), LLM with a one-line instruction
when free wording is fine (sympathy, answering a question and returning to the offer). Extraction per turn:
`reply_kind` (accept / refuse / propose / too_much / vague / question / unclear + negotiation-stage situations),
`day_text`, `amount_text`, `product_ref`. `negotiate_eval` applies, in this order:
1. situations by SPEC `priority` (hardship first: suppresses persuasion; `proposal_still_handled`);
2. a proposal (date and/or amount): `check_promise_date`, amount in [accept_min, accept_max]; below min -> SPEC
   `below_min` once; valid -> mark agreed; multi-product one-date: clamp each product to its own deadline;
3. too_much -> floor offer once (`floor_offered` flag, so the floor amount is never named twice outside the ladder);
4. vague -> ask for the exact day `ask_exact_times`, then the SPEC `then` rule;
5. refusal / non-answer -> next ladder step for this product (attempt counter per product); exhausted -> product
   closed with `attempts_exhausted` (+ note reason);
6. next product (cursor, `get_account` order, attempt 1, no second "today" ask) or confirm when all are decided.
It never repeats an offer the customer refused (state kept in variables).

**confirm (conversation) + confirm_eval.** TTS read-back of every agreed product (spoken name, amount, date with
weekday from code; clamped products say "the latest date for your <product> is <date>") + SPEC question.
`confirm_reply`: yes / no / change / situations. change -> back to negotiate_eval with the new values (revalidated).
yes -> record.

**record_p<i> (api_request, one per product slot).** Body baked from `p<i>_id`, `p<i>_offer_amount` (`:json`),
`p<i>_offer_date`, customer id; field names from `tool_fields`. Failure count > 0 -> `retry_p<i>` (TTS `retry_say`,
same call). Second failure -> `p<i>_status = failed` (+ service-error note in B). Success -> `recorded`.
No model involvement, so the agent cannot say "recorded" before the bank answered: the success sentence is spoken
later, by code, only for recorded products.

**notes_p<i> (api_request).** Only when `notes.enabled`, `notes_allowed` (no transfer) and the product has no recorded
promise. Reason baked from `p<i>_note`.

**Situation exits.** Generic from the catalogue: a code node sets outcome/reason (`outcome_by_stage` before/after
identity), writes `transferred`/`notes_allowed`, then api_request nodes for the actions (transfer with baked queue,
callback, note), then an end node with the SPEC `say` (TTS when `say_exact`). `scope: product` marks the product and
returns to negotiate_eval instead of ending.

**finish (code).** Final outcome from the SPEC: any recorded promise -> `outcomes.promise` unless a transfer
happened and `transfer_after_promise` is `transfer_wins`; else multi rule (`all_notes_match` / first non-matching
note) or the single-product situation outcome.

**end nodes.** `message_mode: custom`, `spoken_message` = success sentence (only if recorded) + farewell; one end
node per distinct ending so `endedReason` is readable.

**System prompt.** Agent self-description, language, faq answers, forbidden offers and questions, free rules, the
honesty rule ("never say something was done before the tool result says so"), forbidden words before identity (only
in pre-identity nodes' task messages, since the system prompt is shared).

## 3. Self-tests that do not depend on the practice cases

1. **Static lint** on the generated JSON: every node reachable and every path ends in an end node; every passthrough
   node ends with `always`; no `null`; no `{{`/`}}` in code; every `{{var}}` in a fixed spoken line is written by an
   earlier code node on every path; tools only on conversation nodes, pre_actions only on api/code nodes; every tool
   field and enum value exists in the tool API file.
2. **Snippet tests**: every generated code node is executed locally with sample `vars` on many `now` values (Fridays,
   days before holidays, month and year ends) and checked against properties from the SPEC (deadline is a business
   day, attempt dates never after the deadline, outcome always set).
3. **State-machine tests**: a local interpreter walks the generated graph with scripted extraction values (no LLM):
   for every situation, every band, every outcome row and the multi-product rules, it checks the outcome, reason,
   notes, and the tool calls that would be made. This tests the brief's logic on a hidden brief without the mock.
4. **Dry run** (`validate_workflow`) and a **chat smoke test** (opening line, nothing disclosed before identity,
   third-party path).
5. **Practice cases** only with an explicit `--practice A|B` flag, never by recognising the brief.

## 4. Assumptions to verify before relying on them (experiments)

| # | Assumption | Why it matters | Experiment |
|---|---|---|---|
| X1 | An `always` transition on a conversation node fires after the user's message, not right after the node's own `on_enter` | The whole speaker/orchestrator loop depends on it | 2-node workflow, chat turns |
| X2 | Re-entering a node runs its `on_enter` TTS again with the new `{{say_text}}` | The speaker re-speaks each turn | same |
| X3 | An extracted variable can be overwritten with `""` by a code node and is then re-extracted on the next turn | Stale-extraction rule | same |
| X4 | A baked number with `{{x:json}}` reaches the API as a number | `create_promise` amount | api_request to the mock with a practice customer |
| X5 | Routing on a `pre_actions` failure counter works for a retry node | One retry on failure | PUB-10 (`fail_first_n: 1`) |
| X6 | `on_enter: {"type": "llm", "prompt": ...}` speaks one line from the prompt | LLM speaker mode | chat turn |
| X7 | A post-hook can write variables (seen once in a test by the organisers) | Tracking which identity question passed | chat turns with verify_identity on a practice customer |
| X8 | Latency of the loop (extraction + code + TTS) per turn | Customers hang up on long silences | slowest-turn line of run_cases |

X1 to X3 and X6 decide the design; they come first in Phase 3.

## 5. Coverage check

Every row of `RULE_MATRIX.md` maps to a node above:
A1-A4 opening · A5-A10 third_party + situations · A11-A15 identity · A16-A17 account_facts · A18-A23 dates snippet +
negotiate_eval · A24-A27 amounts in negotiate_eval · A28-A33 negotiate/negotiate_eval + situations · A34-A36 confirm
· A37-A38 record + end · A39-A45 situations + faq · A46-A47 lifecycle + finish + end · B1-B11, Bc account_facts,
negotiate_eval (cursor, per-product attempts, clamp), confirm (single read-back), record/notes per product, finish.

## 6. Known limits

- Fixed stage order (opening, third party, identity, negotiation, confirmation): "the same kind of call".
- English speech formatting of dates and amounts.
- Extraction quality on very unusual phrasing; mitigated by "unclear -> ask again" paths and SPEC descriptions.
- A brief rule that fits no SPEC field goes to `free_rules` and therefore only reaches prompts (mechanism P).
