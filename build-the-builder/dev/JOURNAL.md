# Journal: yasar/hybrid-builder

Branch owner: Yaşar. Plan and rules: `dev/DEV_AGENT_PROMPT.md`. Workflow slots on Freya start with `yasar-`.

## Decisions

| When (UTC) | Decision | Reason |
|---|---|---|
| 2026-10-10 | Branch `yasar/hybrid-builder` created from `main` (68398a9) | Own branch, teammate works in parallel |
| 2026-10-10 | `.gitignore` at repo root (not inside `build-the-builder/`) | Patterns without a leading slash cover the whole repo |
| 2026-10-10 | New code goes to `build-the-builder/builder/`, dev tools to `build-the-builder/dev/` | Kit files stay unchanged; `run_cases.py` resolves paths relative to the kit folder |
| 2026-10-10 | Phase 1: rule matrix in `dev/RULE_MATRIX.md`, mechanism ladder S > C > B > T > E > H > L > P | Pick the most deterministic mechanism that can carry each rule; 3-of-3 scoring punishes model-dependent rules |
| 2026-10-10 | Phase 2: SPEC = content, generator = mechanisms. Generic rule kinds with parameters (dates, amounts) and a situation catalogue with generic actions | A new brief's new numbers, tables or situations become SPEC data, not code changes |
| 2026-10-10 | Tools are found by their seven fixed names; request fields through `spec.tool_fields`, response fields through `identity.result_fields` and `account.product_fields` | The README guarantees tool names but not field names |
| 2026-10-10 | Builder stays standard library only (no pydantic, no jsonschema) for its own code | Fewer install problems on the organisers' rerun |
| 2026-10-10 | Generality test: imaginary Brief C (business customers, 3 bands, Mon-Sat, calendar-day deadline, renamed API fields, other outcomes) fits the schema with no schema change | Evidence the schema is not shaped only by Brief A/B |
| 2026-10-10 | Phone agent: one workflow of specialist nodes (extraction understands, code decides, TTS/LLM speaks); no `invoke_agent` | Exported workflow is loaded into the organisers' workspace, so cross-agent ids would break; also undocumented, model rule, latency (see ARCHITECTURE.md) |
| 2026-10-10 | Builder agents: light set, 1 Reader + Binder + Auditor (one repair round) | Yaşar's choice: Claude Pro quota and build time; two-Reader design kept as upgrade path |
| 2026-10-10 | v1 first: `builder/generate.py` = example builder's gen_a/gen_b structure, all content from the SPEC; then migrate to the orchestrator piece by piece, keeping only what wins in `run_cases.py`; decision point Sunday 14:00 TR (11:00 UTC) | A submittable agent at every moment; the orchestrator must beat a known baseline |
| 2026-10-10 | `builder/verify.py`: lint (15 planted workflow bugs, all caught) + every code node and hook executed on 36 calendar days | Self-test without practice cases |
| 2026-10-10 | Inspection found a semantic bug lint cannot see: hardship accept and decline went to the same exit (support transfer). Fixed with branch keys | Motivates the state-machine test in ARCHITECTURE.md section 3 |
| 2026-10-10 | `dev/check_no_brief_literals.py` before every commit; it derives brief values from the brief and API files at run time | It caught Brief A variable names in our own docstring examples |

## Freya slots (ours)

| Slot | workflow_id | agent_id | Content |
|---|---|---|---|
| `yasar-base` | `c11d1a5b-d386-4429-a11c-311ca824da28` | `96ec991c-9aaf-4c2b-b5aa-7635acc439a4` | `examples/base-agent.json`, unchanged |

## Test runs

| Time (UTC) | Workflow / version | Brief | Style | Reps | Score | Failed cases | Cause |
|---|---|---|---|---|---|---|---|
| 2026-10-10 16:04 | `yasar-base` v1 (base agent) | A | none | 1 | **0/10** (README said ~2/13) | all | see "Baseline analysis" below; median slowest turn 5 s, so not a slow-model run |
| 2026-10-10 16:28 | `yasar-base` v1 | A+B | none | 1 | **0/13** | all | A failures shift run to run (PUB-03 outcome `no_promise/refused` vs `None` before; PUB-08 `None` vs `promise`): the end-of-call guess is random. PUB-13: model put the sum 1200 on both products |
| 2026-10-10 17:16-17:48 | example builder (`brief-a` slot, agent `d620a1b2...`) | A | none | 1 (x7 runs) | 9, 1/1, 9, 9, 0/1 (reps 3), 8, **8/10 last** | a different case each run: PUB-10, PUB-04, PUB-06, then PUB-06+PUB-10 | see "Example builder baseline" |
| 2026-10-10 17:57-18:08 | example builder, A+B input (slots `brief-a` v7, `brief-b` v2) | A, B | none | 1 each | A **10/10**; B 2/3 then **3/3** | B run 1: PUB-13 | PUB-13: the model believed 2026-10-30 was a Saturday and moved the promise to 11-02 |

### Example builder on A+B (second session, warm start)

- Build: **659 s (11 min)**, 40 turns, reported API-equivalent $2.30. **Warm start**: it reused and patched
  `out/gen_a.py` from the first session, so 11 min is not a cold build time. Cold estimate for A+B: 32 + 11 min.
- With two briefs it built **two agents** (one per brief file = one per slot) and overwrote the `brief-a`
  workflow (old version backed up in `results/example-a/`, new outputs in `results/example-ab/`).
- Its fixes confirm two of our lessons: PUB-06 passed after the floor amount is named only once (later offers name
  only the date); PUB-10 passed after a fixed failure sentence without the word "recorded".
- Brief B design: one negotiation node per product count (1, 2 or 3 products), per-product tools
  `create_promise_N` / `add_note_N` with `product_id` baked, per-product deadlines and attempt counters in code,
  closing outcome computed in a code node from per-product state. 29 nodes, `gen_b.py` 343 lines.
- **Weekday hallucination**: the agent model got the weekday of a date wrong (PUB-13 run 1). Fix that worked:
  write the calendar into the prompt with explicit weekday names. Rule for us: the model never derives a weekday.
- Not tested by it: the B agent on single-product customers, transfers, paid, tool failure. Note that the A cases'
  expectations follow Brief A (e.g. no `add_note`), so a B agent that follows B rule 8 on an A case can fail on
  notes although it is right for Brief B.

### Example builder baseline (Brief A)

- Build: **1934 s (32 min, over the 30-minute limit)**, 34 turns, `claude-opus-5-5` via Claude Pro login,
  reported API-equivalent cost $1.70. It ran `run_cases.py` 7 times (the skill says at most 3 fix rounds).
- Last run 8/10; peak 9/10. Failing cases rotate between runs, so under the 3-of-3 rule it would score lower.
  PUB-06 with `--reps 3`: 0/3.
- It wrote a generator script `out/gen_a.py` (715 lines) and a 30-node workflow: `init` code node -> `opening`
  (extracts a `party` enum, branches with `equals`) -> `third_party` -> `check_callback` (code) -> `schedule_cb`
  (api_request) / `verify` (post-hook) -> `get_account` (api_request) -> `prepare_deal` (code) -> one big
  `negotiate` node with `create_promise` and **9 exits, 7 of them `matches_intent`** -> one `set_*` code node per
  outcome -> a single `final_end`. Very close to our planned design, except that its exits from `negotiate` are
  semantic.
- `gen_a.py` hard-codes Brief A values (holidays, bank name, a fallback `today_iso = '2026-10-14'`). Fine for a
  per-brief LLM builder, forbidden in our `builder/`.
- PUB-06 cause: the floor was offered twice (attempt counting lives in the model's memory).
- PUB-10 cause: the judge read the check "does not say 'recorded' before a successful call" literally and
  flagged both the required opening "this call is recorded" and "the promise was not recorded". Lesson: the judge
  is literal. Before a success, avoid the confirmation word even in negations and in unrelated sentences, while
  still stating the recording notice (e.g. "we record this call"). To verify with an experiment.
- The example builder lists `dev/` and read `dev/show_call.py`; it did not open the journal or the prompt. An agent
  run inside the kit folder can see everything in it.

### Baseline analysis (base agent, Brief A)

| Case | Root cause | Mechanism that fixes it |
|---|---|---|
| PUB-01 | Text-message sentence after the promise never said | Post-hook on `create_promise` + required sentence from SPEC |
| PUB-02 | No `schedule_callback` tool, no third-party path; outcome guessed `unclear` | Structure: `who_answered` enum -> third-party node with callback tool, validated in code |
| PUB-03 | Outcome `(None, None)`; app/branch not mentioned; agent claims a transfer that never happened | Code sets outcome/reason; post-hook `what_to_do_next` on `verify_identity` |
| PUB-04 | Promise recorded on the customer's date (11-06), past the deadline (10-23) | Deadline computed in code; date validated in code before baking |
| PUB-05 | Support team not offered; reason `refused` instead of `hardship` | Hardship exit with `transfer_to_agent`; reason from code |
| PUB-06 | "Rest stays overdue" sentence missing | Prompt rule from SPEC (floor offer wording) |
| PUB-07 | Holiday 10-26 accepted | Business-day check in code |
| PUB-08 | "Already paid" turned into a promise; `paid` not in the outcome enum | Intent enum -> paid exit; outcome enum taken from the tool API file |
| PUB-09 | No `transfer_to_agent` tool | Restructuring exit with transfer, queue baked |
| PUB-10 | No retry after the first `create_promise` failure; outcome `(None, None)` | Retry once (post-hook says so); outcome from code |

## Platform and kit facts (verified by us)

- The kit lives in `build-the-builder/`. All kit commands run from that folder (`freya.py` is imported from cwd).
- On this Windows machine `python3` resolved to the Windows Store alias. **Fixed outside the repo**: a shim
  `~/bin/python3` (`exec python "$@"`); Git Bash puts `~/bin` first on PATH, so `python3` now runs
  `C:\Python314\python.exe` (3.14.6). Kit files and the skill stay unchanged. Several Pythons are installed
  (3.12, 3.13, 3.14, anaconda, msys2): install packages with `python -m pip`, not bare `pip`.
- `claude-agent-sdk` 0.2.165 is installed; `anthropic` is not.
- **The Agent SDK works with the Claude Pro login, no API key** (2026-10-10, `dev/check_claude_login.py`): with
  `ANTHROPIC_API_KEY` unset, a one-turn query answered on `claude-opus-5-5` in 2.5 s. `total_cost_usd` is still
  reported (an API-price estimate, not a charge). The login's usage limits are shared with the Claude Code session
  used for development.
- `.claude/skills/build-phone-agent/SKILL.md` was **missing from the repository** (dropped because `.claude/` is a
  hidden folder). **Restored** from the organisers' `build-the-builder-v3.zip`; every other file in the zip is
  identical to the repo (line endings ignored). The skill saves under slot `<brief file name>` (e.g. `brief-a`),
  calls `python3`, and tests with `run_cases.py --brief A` up to 4 times, i.e. it relies on the practice cases
  (the self-test trap of DEV_AGENT_PROMPT section 8).
- There are two `public-test-set.json` files. The root one is older and has no `identity` block. `run_cases.py`
  reads `build-the-builder/public-test-set.json` (it resolves `ROOT` from its own location), which is the right one.
- `run_cases.py` opens a practice session per case at the mock (`/v1/practice/sessions` with `{"case": id}`); the
  mock returns the call variables (including `customer_id`). The ledger is read back from
  `/v1/practice/ledger/<customer_id>`.
- `score.py` passes a case only if the last ledger call is `close_call` and outcome+reason, promises, notes,
  callbacks and transfers all match exactly. Then the judge model must also pass the transcript checks.
- Brief A dates for `now = 2026-10-14` (a Wednesday), computed by hand: late-band deadline (7th business day) =
  2026-10-23; early-band deadline (12th business day, skipping the holiday 2026-10-26) = 2026-11-02; attempt-1 date
  (last business day of this week) = 2026-10-16. These match PUB-04, PUB-06, PUB-07, PUB-10 and PUB-13.

- **`type: "date"` extraction resolves relative dates against the REAL clock, not the call variable `now`**
  (2026-10-10, `dev/exp_date_anchor.py`, `results/exp-date-anchor.txt`): with `now = 2026-10-14T11:00` and the real
  date 2026-10-10, "I can pay tomorrow." gave `when_date = 2026-10-11`. The same turn's `type: "string"` field
  `when_text` held "tomorrow" verbatim (confidence 1). "Today is {{now}}" in the `task_message` did not help: the
  extractor does not see the dialogue prompt. Rule for the generator: never extract customer dates with
  `type: "date"`; extract the words as a string and resolve them in code (`builder/snippets/dates.py`).
  Every practice case uses `now = 2026-10-14`, while the final is scored on other days, so an agent that trusts
  the built-in date type is wrong on every relative date.
- **Mock rejects unknown case ids** (2026-10-10): `POST /v1/practice/sessions {"case": "PUB-99"}` ->
  `{"ok": false, "error": "unknown practice case"}`. So the builder cannot create its own test customers on a
  hidden brief; the hidden-brief self-test must be brief-independent (lint, local snippet runs, dry run, chat).

- **Lifecycle `close_call` with unset `{{outcome}}`: a model guesses it** (seen in the baseline). PUB-08 got
  `outcome: promise` from the conversation. In PUB-03 and PUB-10 the ledger shows `(None, None)`: the guess left
  the field out. So outcome and reason must be set in code during the call.
- The base agent's `pre_process_code` on `close_call` removed `reason` when outcome was `promise` (PUB-08 body has
  no `reason`). Pre-hooks on lifecycle tools work.
- `end_call` as a tool with `trigger_pattern` ends the call after the agent says the phrase; `endedReason` is then
  `assistant-ended-call`, and `close_call` runs about 3 s later.
- `dev/show_call.py` works on real calls (PUB-02, PUB-08).

## Open questions

- Builder LLM calls: the plain `anthropic` Messages API needs an API key; the Agent SDK `query()` also works with
  a Claude login. Decide in Phase 4 whether `extract.py` calls the model through the SDK (works with both).

- Example builder: score, build time, cost on Brief A (blocked on the missing skill file).
- `docs/workflow-format.md` says "no `null` values", but `examples/base-agent.json` contains
  `"max_turn_transition": null` and `"passthrough_default_transition": null` (it looks like a platform export).
  Check with a dry run whether the API accepts these nulls; our generator will emit no nulls either way.
  **Partial answer (2026-10-10):** `POST /api/v2/workflow` accepted `base-agent.json` with these two nulls.
  Not tested: nulls in other fields. Rule for us stays: emit no nulls.
- The base agent's `close_call` bakes `{{outcome}}`/`{{reason}}`, but nothing in the workflow ever sets those
  variables, so the end-of-call model guesses them. Confirm in a transcript of the baseline run.

### v1 first run (Brief A) and fixes

| Time (UTC) | Workflow / version | Brief | Style | Reps | Score | Failed cases | Cause |
|---|---|---|---|---|---|---|---|
| 2026-10-10 16:5x | `yasar-brief-a` v1 | A | none | 1 | **7/10** | PUB-02, PUB-05, PUB-07 | see below; median slowest turn 5 s |

- PUB-02: day and time were two extraction fields behind an AND condition; the time was extracted, the day failed,
  so the callback check never ran. The model then called an invented sibling tool (`transition_to_set_callback_scheduled`)
  and told the person it could not book. Also: a code-node write that violates a field's `validation_pattern` is
  rejected (`setup_response.validation_errors`). Fix: one field `cb_when_text`, day AND time parsed in code
  (`parse_spoken_time` added to the date snippet), partial answers remembered, prompt says there is no booking tool.
- PUB-05: the support transfer was offered twice; the offer count lived in the model's memory. Fix: an offer node per
  situation with an offer, made once, answer read as an enum (accept / decline / proposal), deterministic routing;
  in multi-product briefs the decline path writes notes through an engine-run chain (`notes_chain`).
- PUB-07: "Monday the 26th" (a holiday) was answered with the deadline instead of the next business day; the model
  misapplied rule B. Fix: every calendar line carries the code-computed answer ("IF THE CUSTOMER NAMES THIS DAY:
  offer ..."), per product, from `check_promise_date`.
- All three fixes use only mechanisms already seen working (on_enter llm on entry, tool-call transitions, enum +
  equals). None depends on the unverified loop assumptions X1-X3.

### Phase 4: extraction runs (Brief A, local, Claude Pro login, claude-opus-5-5)

| Run | Time | Calls | Result | Cause / note |
|---|---|---|---|---|
| 1 | 242 s | 4 | invalid SPEC (13 errors after 2 repairs) | Binder returned call_variables as strings and tool_fields as lists; merge_binding treated the Binder as authoritative and overwrote the Reader's correct values after every repair. Fix: Binder shapes from the schema; a Binder part is merged only if it validates |
| 2 | 121 s | 3 | valid, lint + 36-day snippets pass | calendar, bands, dates, tool_fields, notes identical to the hand-written SPEC; 50 rule_map rows cover all 47 rules. Issues: `human_request.say` held the first-response question (would be spoken after the transfer); opening sentence used "recorded" (judge-literal risk seen in the example builder's PUB-10). Auditor answered `{"issues": []}` in 15 s: too shallow. Fixes: say = spoken when the effect happens; generic honesty wording rule; Auditor gets a concrete checklist |

Lesson: in a multi-agent pipeline, an "authoritative" agent's output must be validated before it overrides another
agent's output; and an auditor without a checklist tends to approve.
| 3 (A) / 3 (A+B), parallel | 122 s / 143 s | 3 / 3 | both valid, lint + snippets pass | `human_request.say` fixed (first_response holds the question). A+B: multi_product, notes, outcomes.multi, product-scope paid/dispute with notes, hardship decline note: all match the reference. Opening still used "recorded" in A but not in A+B (same prompt, different result). Fix: code finds claim words in pre-success sentences and a small Reworder call rewrites only that sentence (6 s) |

- Tooling lesson: writing Python source from a Python heredoc turned `\b` into a backspace character, so a regex
  silently never matched. Check generated regexes with a positive and a negative example.

### Platform findings from experiments (2026-10-10 evening)

- **Chat route skips the initial code node** (X9, `results/exp-loop.txt`): `setup_ran` never set, the TTS used the
  `test_variables` fallback.
- **Chat route fails when a call enters a code node mid-call**: both experiments returned 503 / 504 at the first
  conversation -> code transition. Simulations run code nodes fine. Consequence: experiments run as simulations
  (`dev/exp_sim.py`); a chat smoke test can only cover paths without code nodes.
- **Same-turn reply after a code-node hop works** (`results/exp-hop.txt`, simulation): user answer -> extraction ->
  code node writes a note -> back to the same conversation node -> the reply in that turn uses the new note.
- **The extractor re-reads old values from the history**: after code cleared `colour`, a turn without a colour still
  produced a value and hopped. Rule: code decides what is new (it remembers the last value it consumed).
- PUB-07 failed the same way in three runs (hand SPEC x2, extracted SPEC x1): systematic, not noise. Fix: a
  `date_check` hop after every turn that names a day; code resolves it against `now`, applies the SPEC date rules
  per product, and writes `date_note`, shown first in the negotiation prompt.

| Time (UTC) | Workflow / version | Brief | Style | Reps | Score | Failed cases | Cause |
|---|---|---|---|---|---|---|---|
| 2026-10-10 17:5x | `yasar-extract-a` v1 (SPEC extracted by the builder, no hand input) | A | none | 1 | **9/10** | PUB-07 | systematic date-rule error, see above; median slowest turn 2 s |

### Raw-material stress test (Phase 4)

`dev/specs/raw-a/`: Brief A rewritten as an email, a handbook extract, a later legal memo that changes three rules,
and a CSV code list. Extraction (125 s, 4 calls): **all three memo overrides applied** (late deadline 7 -> 5 business
days, holiday 2026-11-11 removed and 2026-10-30 added, callback window 09:00-18:00), the unchanged early band kept,
the CSV became the outcome table exactly, every override recorded in `free_rules` with both quotes, and the Reworder
fixed "this call is recorded". Lint and snippet runs pass.

### Reps-3 and the first orchestrated runs (2026-10-10, ~19:00-20:00 UTC)

| Time (UTC) | Workflow / version | Brief | Style | Reps | Score | Failed cases | Cause |
|---|---|---|---|---|---|---|---|
| ~18:40 | `yasar-extract-a` v3 (v1 mode) | A | none | 1 | **10/10** | - | second 10/10 in a row |
| ~18:40 | `yasar-extract-ab` v3 (v1 mode) | B | none | 1 | 2/3 | PUB-12 | model made a second offer on the early-band car loan |
| ~19:00-19:15 | `yasar-extract-ab` v3 (v1 mode) | B | none | **3** | **2/3** (PUB-11 3/3, PUB-12 0/3, PUB-13 3/3) | PUB-12 | same cause in every run: systematic |
| ~19:30 | `yasar-orch-ab` v1 (orch mode) | B | none | 1 | 0/3 | all | agent silent after "yes": record node had `on_enter: silent` |
| ~19:40 | `yasar-orch-a` v1 (orch mode) | A | none | 1 | 5/10 | every promise case | same: silent record node; median "slowest turn" 61 s = customers waiting, then hanging up |

- **A node entered with `on_enter: silent` does not speak or call a tool in that turn.** The negotiation state
  machine itself worked on the platform (accept -> read-back -> confirm -> record decided correctly). The hop
  experiment had passed only because it re-entered the same node whose `on_enter` was first-entry-only. Fix: the
  record node uses `on_enter: llm`.
- Writing `''` to an enum extraction variable from code is rejected (`validation_errors`); the turn-number guard
  (`negotiate.total_turns`) is what prevents double processing.
| ~19:15-20:00 | `yasar-extract-a` v3 (v1 mode, SPEC extracted by the builder) | A | none | **3** | **10/10** (every case 3/3) | - | the submittable baseline |
| ~20:00 | `yasar-orch-ab` v2 (orch, record speaks on entry) | B | none | 1 | 2/3 | PUB-12 | code decided right; the MODEL said a different offer than SAY NOW and the customer's "yes" went to the wrong product |
| ~20:10 | `yasar-orch-a` v2 | A | none | 1 | 9/10 | PUB-04 | code read back the deadline; the model said the attempt-1 date from FACTS and passed that date to create_promise; it also said "recorded" before the tool result |

- **v1 baseline under the final rule: A 10/10 at 3 of 3, B 2/3 (PUB-12 0/3) = 12/13.**
- Orchestrator lesson: deciding in code is not enough while the model still SPEAKS and FILLS the tool arguments.
- Experiment `dev/exp_engine.py` (simulation, `results/exp-engine.txt`): **X2** a conversation node with
  `on_enter: tts {{say_text}}` (not first-entry-only) speaks the new text exactly on every re-entry and nothing else;
  **X4** an engine-run `create_promise` (api_request) with amount and date baked from code variables records the
  amount as a number; **X5** a `pre_process_code` on a pre_actions api_call runs (it can write variables).
  Consequence: orchestrator v3 speaks by TTS and records by engine-run calls; the model only answers questions.

### Repository cleanup before branch publication (2026-10-10)

- Paused negotiation changes at the owner's request; publish the current builder
  on `yasar/hybrid-builder` for parallel development.
- Removed tracked generated traces from the current tree (local copies retained),
  five completed one-off experiment scripts, and the obsolete root test-set copy.
  Runtime modules, regression tests, reference SPECs, and the supplied kit remain.
- Ignore generated traces, archives, hidden inputs, submission copies, and local
  environments. Selected final traces must be staged explicitly with `git add -f`.
- Added root setup/build/check instructions and pinned the tested SDK version.
- Cleanup does not change workflow generation or qualify orch for submission.
- Verification after cleanup: `test_spec_schema.py`, `test_dates.py`, and
  `test_negotiation.py` passed; `check_no_brief_literals.py` reported clean.

### An ambiguous reply must not transfer the call (2026-10-11, branch `yasar/fix-situation-guard`)

**Failure (orch, `--style pieces`).** Opening, identity ("44 71" joined) and the debt statement were right. To the
first ask the customer said "I can't, what are the other options". Extraction wrote `reply_kind` = the situation
that transfers to the restructuring queue, and `neg_eval` transferred at once. Brief A wants: a no to today with no
date and no amount is a flat refusal (rule 30, attempt 1); a question the agent cannot answer gets a short answer
(rules 33, 44); rule 41 transfers only on a request for a new plan or lower instalments. The ledger would close as
`transferred` where a promise or `refused` is expected.

**Cause.** Code decided correctly on a wrong classification. Three things let it through: the enum text said "When a
special situation applies, choose it over the others" and gave a question about options no better home; the SPEC's
`not_this` did not rule that reply out; nothing checked the customer's own words before an action that cannot be
undone. Reproduced without the platform: on `main` the generated `neg_eval`, fed that turn, goes to the transfer
node; on this branch it goes to `negotiate_q` with attempt 1 (`dev/test_situation_guard.py`, part 3).

**Fix, three layers.**

| Layer | Where | What |
|---|---|---|
| Understand | `generate.py` (orch enum text; v1 prompt and tool-call descriptions) | A situation is chosen only when the message itself clearly says it; by itself a plain no, "cannot pay" or a question about options is not a situation (the text does not say which other value, so "too much" keeps its own definition). v1: the same sentence above the situation list (a plain no stays with the rules above it), and each exit tool's description carries `not_this` |
| Describe | `spec_schema.py`, `extract.py` (field guide, Reader, Auditor) | For a situation that transfers or ends the call the Reader writes `not_this` so that it rules out those everyday replies, and the new optional `evidence_words`: word stems from the brief's own wording of the request, plus synonyms |
| Decide | `snippets/negotiation.py`, `neg_eval` | `situation_confirmed`: a situation with evidence words acts only when the customer's own words (`said_text`, a new extraction field) contain one. Otherwise the turn is the kind `UNCONFIRMED`: answer first in one sentence, then the next persuasion offer; at the read-back, read back again; with no attempt left, repeat the open offer |

| Decision | Reason |
|---|---|
| Evidence words live in the SPEC, never in `builder/` | They are the brief's vocabulary; `check_no_brief_literals.py` stays clean |
| The generator drops an evidence word that occurs in the agent's own fixed sentences (first ask, debt statement, product names, read-back question) or has fewer than three letters | A list with an everyday word of the call (a word for paying, the product's name) would let the echo of the agent's question count as evidence; the builder runs once on a hidden brief and nobody can correct the list |
| Code overrules the extraction only on evidence: no evidence words, or no extracted words, and the extraction stands | Never worse than before the change, whatever the platform does with the new field |
| Words without evidence: not acted on the first time, acted on the second | A real request made in unexpected words costs one extra turn instead of never being transferred |
| `reply_kind` is set to `unclear` after every turn | An enum variable cannot be cleared with `''`, so a turn whose kind was not extracted repeated the last kind (a second count of a situation, a second "accept") |
| `said_text` only when a situation has evidence words; `min_confidence` 0.05 | No extra field for a SPEC without them; a copy needs no confidence gate and a long value must not be dropped |
| v1 gets the text layers only | A code gate there needs a tool-call transition into a code node and back in the same turn, which is not verified |
| "I am connecting you now." is added only when the situation's sentence does not announce the transfer | The two sentences said the same thing twice |

**Not verified on the platform (this clone has no keys): check before relying on it.**
- That the extraction model copies the latest message into `said_text` and that a long value is kept. If it is not,
  the guard is off for that turn (the extraction stands), nothing else changes.
- That a code node may write a valid enum value (`unclear`) to an extraction variable. Only `''` is known to be
  rejected; in the hop experiment the note written by the same node as a `''` write did arrive, so a rejected write
  should not take the node's other writes with it.
- The agent model's wording of the one-sentence answer in `negotiate_q`.
- That a fresh extraction fills `evidence_words` well. A SPEC extracted before this change has none: rebuild
  without `--spec`, or the code layer stays off.

To run with keys: `--only PUB-09 --reps 3` on orch (a real request must still transfer), then
`--style pieces`, `asks_back` and `talkative` on Brief A, reading every call that ends `transferred`.
Local result: `test_situation_guard.py` 111 checks, the three older suites and the literal check pass; lint and
local runs pass for Brief A, A+B and imaginary C in both modes. No simulation was run for this change.

### Merge of the situation guard into `fix-agent-logic` (2026-10-11)

`yasar/fix-situation-guard` was merged into `fix-agent-logic` at `d25cb09` ("fixed issues": callback and note
actions in situation exits, a tool-call transition from identity to the account step, amount rules worded from the
SPEC, `multi_product.one_date_rule`, "not today" and "next week <weekday>" in the date snippet, amounts such as
"twelve fifty"). No textual conflict. A clean text merge proves little, so the merged tree was checked:

- the six suites (`test_not_today.py` included) and the literal check pass; lint and local runs pass for Brief A,
  A+B and imaginary C in both modes;
- the workflows generated by the merged code differ from those of `d25cb09` only in `neg_eval`, in the extraction
  and prompt text of the negotiation nodes, and in the transfer sentence; every other node is identical, with the
  fixtures of either side;
- the reported turn still transfers on `d25cb09` and no longer does on the merge; a real request transfers on both.

**Added after the merge: a refusal that mentions today proposes no day.** The "not today" fix shows that the
extraction copies a day the customer refuses into `day_text`. A list of wordings in the date snippet cannot cover
them all: "I can't pay today" and "no way today" still resolved to today, and the state machine then took the
refusal as a proposal, agreed the full amount for today and read that back. Now, in `_step`, a day that resolves to
today is dropped when the kind is refuse, too_much or `UNCONFIRMED`. Any other day in a refusal is still a proposal,
and a yes or a question with today ("can I pay today?") still means today.

**Two points of `d25cb09` to watch in a simulation (not changed here).**
- Identity now also offers the model a tool-call transition to the account step. If the model calls it before
  both answers are verified, the bank refuses `get_account`, and the scorer fails the case for calling it before
  identity was verified.
- v1 with several products: the fixed sentence for "one date for everything" is replaced by
  `multi_product.one_date_rule`, but the field guide in `extract.py` says nothing about that field. A SPEC keeps
  the rule only if the Reader fills the field unprompted or writes it as a free rule (the reference SPEC has it as
  B6b). PUB-13 on v1 depends on it. One sentence in the field guide for `multi_product` would close this.

Local result after the merge: `test_situation_guard.py` 124 checks. No simulation was run.
### Branch `alper/hybrid-builder`: human-phrasing parser fixes (2026-10-11, group A)

Found by manual tests (`tools/practice.py`) and a review; all verified locally first (12 failing date tests, amount
tests failing) and fixed in the snippets only. No build, no simulation yet.

- `resolve_spoken_date`: a negated today ("not today, Friday", "I can't pay right now", "not now") was read as
  TODAY, which would record a promise for today. Negated today/now is now removed before matching. A
  self-correction ("tomorrow, no sorry, Friday") keeps the last day named. "next week Tuesday" / "Tuesday next week"
  is always the following calendar week (it was this week's Tuesday when said on a Monday). "end of October",
  "early November", "mid October" are vague periods (they were `none`).
- `parse_amount`: a day number in the amount field was taken as the amount ("on the 16th I can pay 200" -> 16);
  day tokens are removed first. Cents in words ("... and twenty cents") are added. A spoken pair ("twelve fifty")
  is read as hundreds (1250) unless only the decimal reading (12.50) lies in the account's range (smallest floor,
  largest full amount), which `step` now passes.
- `step` keeps an internal error in `state['err']`; `neg_eval` writes it to `vars['neg_error']`, so a silent
  "Sorry, could you say that again?" loop shows in the transcript. `codegen.date_config` already writes
  `business_day_only`; a new test checks every config key the date snippet reads is written.
- All new phrasings are tests in `dev/test_dates.py` (3b, 3c) and `dev/test_negotiation.py`. Checks: the four
  suites pass, literal check clean; local `generate` + `verify.lint` + `verify.run_snippets` clean for the extracted
  A and A+B SPECs in v1 and orch mode.
- Still to verify on the platform: one practice run per brief after the remaining group B/C changes.

### Branch `alper/hybrid-builder`: classification and counters (2026-10-11, group B)

Found in manual calls: "I can't, what are the other options" was classified `restructuring_request` and transferred
(expected: a flat refusal, attempt 1, the question answered); in identity, a decline after the explanation was
handled one turn late (the model counted declines). No build, no simulation yet.

- Situations that end or transfer the call (call scope, no offer, reachable after the opening) get a generic
  look-alike guard in every place a model reads them (v1 prompt and tool transitions, orch `reply_kind`): only an
  explicit request counts; a plain no, "I can't pay", or a question about options is not it. Mechanism text only.
- `not_this` was appended to the trigger without a label, so the look-alikes read like part of the trigger
  ("requests a new plan. Saying the full amount is too much ..."). Now `Gen.sit_desc`: "<trigger>. NOT this: <...>".
  The extractor prompt asks `not_this` of a call-ending situation to also name the everyday look-alikes.
- orch `reply_kind`: "when a special situation applies, choose it over the others" replaced by "only when its
  description clearly fits; a refusal plus a question is refuse". New field `asks_question` (yes/no): when the turn
  is decided as `talk` and the customer also asked something, `neg_eval` routes to `negotiate_q` so the question is
  answered and the decided sentence is still said word for word.
- identity: new enum `id_reply` (answer / decline / question / unclear; decline wins over a question) routes a
  decline to code node `id_count`, which counts one decline per customer turn (guard: `identity.total_turns`) and
  closes on `identity.decline.max_declines`; the SPEC's explanation is said once, at the first decline. The
  model-driven `transition_to_set_identity_declined` is removed. Unverified on the platform: that the identity node
  answers in the same turn after the code hop (seen for other nodes, see "Same-turn reply after a code-node hop").
- The transfer farewell adds "I am connecting you now." only when the SPEC's sentence does not already say it.
- `dev/show_call.py` warns when the call had no readable `now` (`clock_ok = no`) or `neg_error` is set.
- New test `dev/test_generate.py` (50 checks: lint, snippets, the id_count counter run step by step, guards, orch
  fields) for brief-a and brief-ab in v1 and orch. All five suites pass, literal check clean.

### Branch `alper/hybrid-builder`: generality fixes (2026-10-11, group C)

SPEC fields that the extractor fills but the generator ignored, and API shapes the generator assumed. Each fix keeps
the reference behaviour when the SPEC matches Brief A/B (checked: for the extracted A and A+B SPECs the v1 workflow
changes only by group B's guard text and the new `id_count` node). No build, no simulation yet.

- C11 identity API without `all_verified` / `wrong_left`: the routing to the account needed `all_verified == true`,
  so such an API would never leave identity. The verify pre-hook stores the question field; the post-hook marks
  each verified field and sets `id_all_ok` when every SPEC question is verified (the API's own flag wins when it is
  present); wrong answers are counted against `identity.max_wrong_total` (was unused) into `id_left`. Routing reads
  both; response mappings to empty field names are no longer emitted.
- C12 amount rules: `amounts.first_offer`, `accept_min`, `accept_max`, `too_much.offer`, `below_min.offer` were
  unused (the prompt and the state machine assumed full / floor). `prepare_deal` computes them per product into the
  plan (`first`, `lo`, `hi`, `tm`, `bm`); `negotiation.py` uses them (older plans fall back). When the rules are
  the common ladder (`Gen.amount_std`), the v1 prompt keeps its wording; otherwise each product's FACTS list its
  AMOUNT RULES and the prompt points there.
- C13 situations with a `callback` action did nothing (only `transfer` ran). New `callback_flow`: ask for a day and
  a time, the shared window check (`CB_CHECK`, the third-party code moved into `callback_nodes`), engine-run
  `schedule_callback`, then the situation's other actions and outcome; not booked -> the SPEC's not-scheduled outcome.
- C14 `multi_product.one_date_clamped_per_product` (was unused; Brief B rule 6 was hard-wired in the v1 prompt and
  in `_date_for_all`) now gates both.
- Still unused SPEC fields (not changed here): `outcomes.transfer_after_promise`, `multi_product.unrecorded_on_transfer`,
  `single_read_back`, `state_all_first`, `ask_all_today_once`, `attempts_per_product`,
  `notes.for_each_product_without_promise`, `situations[].say_exact`. The generator behaves as Brief A/B say for these.
- `dev/test_generate.py` now 80 checks (C11-C14 on modified SPEC copies, run through the real hooks, code nodes
  and state machine). All five suites pass, literal check clean; extracted A, A+B and raw-A SPECs lint and run their
  snippets clean in both modes.

### Branch `alper/hybrid-builder`: the remaining SPEC switches (2026-10-11)

The eight SPEC fields the generator ignored now drive the agent, in both modes. Reviewed with a second model first;
its two corrections are in: finalize takes a product's reason from its state (not only from a note), and the
call-wide attempt count has its own field. No build, no simulation yet.

| Field | v1 (prompt) | orch (code) |
|---|---|---|
| `outcomes.transfer_after_promise` = promise_wins | exit node: a recorded promise (`res_i`) sets the promise outcome | same exit node |
| `multi_product.unrecorded_on_transfer` = record | situation line: call create_promise for confirmed, unrecorded promises first | `neg_eval` marks agreed products pending; a second record chain (`rx_<situation>_*`) runs before the transfer |
| `notes.for_each_product_without_promise` = false | rule G: no note for used-up attempts; "every product done" includes "no promise" | `pnote_i` skips a product that ended by used-up attempts (`p<i>_end_why`) and keeps `p<i>_end_reason` |
| finalize (both) | a product without a note has a reason from its state (else the exhausted reason), in product order, when the switch above is false | same |
| `multi_product.single_read_back` = false | rule E: read back each promise alone when agreed, then record it | state machine: per-product read-back (`confirming`), record when all agreed ones are confirmed |
| `multi_product.state_all_first` = false | opening states product 1; FACTS carry each Statement | each product's statement is said when it is reached (implies "today" per product) |
| `multi_product.ask_all_today_once` = false | "ask about today for each product" | per-product today question; a no to it is not an attempt |
| `multi_product.attempts_per_product` = false + new `negotiation.call_attempt_limit` | step 2 names the call's limit, or that earlier attempts count | `state['used']` caps the call's attempts; without a limit the band's own limit caps the total; build trace warns |
| `situations[].say_exact` | product situation: "Say exactly: '<say>'" | offers with exact words are spoken by TTS (also v1) |

- New SPEC field `negotiation.call_attempt_limit` (optional int); schema comments and extractor hints say what each
  switch means, so a hidden brief is read the same way.
- Checked with a before/after compare of the generated workflows (prompts, transitions, tools identical; every code
  node and hook run old and new on the same vars): for the extracted A, A+B and the reference SPECs the only
  differences are the new `statement` key in the plan and, for the hand-written brief-ab SPEC only, the say_exact
  line for `already_paid` (its `say_exact` is true there, false in the extracted SPEC).
- `dev/test_generate.py`: 146 checks (66 for the switches, each on a brief-ab copy with one switch changed, run through
  the real prepare_deal plan and state machine). All five suites pass. The literal check caught a Brief A sentence
  used as a fallback in the new per-product today question; replaced by a generic sentence.
- Imaginary Brief C lints with 56 (v1) / 50 (orch) problems against Brief A's tool API: the same before this branch
  (its field names are renamed and it has no tool API file of its own). Not a regression.

### Merge of `alper/hybrid-builder` into `fix-agent-logic` (2026-10-11)

Both branches fixed some of the same problems in different ways; conflicts were resolved by decision, not by side.

- Kept from `fix-agent-logic`: evidence words for situations that cannot be undone (`evidence_words`, `stem_in`,
  `Gen.evidence`, `said_text`, `situation_confirmed`, kind `unconfirmed`), the extractor's narrower situation
  wording, `sit_trigger(with_not)` and NOT-this in v1 transitions, the v1 look-alike line before the situations,
  `multi_product.one_date_rule` (the brief's own sentence, used when present), the orch `lead` text and the wider
  `question` kind, the `reply_kind` reset in `neg_eval`, the wider "connecting you" check, `test_not_today.py`,
  `test_situation_guard.py`.
- Kept from `alper/hybrid-builder`: `parse_amount` (day numbers removed, cents, account range), the error kept in
  `state['err']` -> `vars['neg_error']`, the callback flow that asks the customer for a day and a time, the identity
  routing through code (`id_all_ok`, `id_count`; the model-driven "all questions answered" exit was NOT taken: a
  wrong call would state the debt before verification), the SPEC amount rules in FACTS, the SPEC switches,
  `asks_question`, guards and `sit_desc`.
- Combined: the orch situation descriptions (`sit_desc` + guard + the evidence sentence), the `ASK_FIRST`
  instruction (unconfirmed -> "cannot offer"; refusal plus question -> answer it), rule 3 (`one_date_rule` if the
  SPEC has it, else the `one_date_clamped_per_product` switch).
- Bug found in the merge and fixed: the new call-scope `note` action wrote one `add_note` for `p1` even before
  identity (no account loaded, empty product id) and only for the first product after it. Now: only with notes on
  and after identity, one note per product without a promise through `notes_chain(reason, after, prefix)`, then the
  situation's exit. Tested in `test_generate.py`.
- `test_situation_guard.py`: two expected field lists gained `asks_question` (the field is part of the merge).
- Checks after the merge: test_spec_schema 3, test_dates 135, test_not_today 14, test_negotiation 62,
  test_situation_guard 124, test_generate 158 checks, all pass; literal check clean; the extracted A, A+B, raw-A and
  the reference SPECs lint and run their snippets clean in both modes.

### Optimisation round on `fix-agent-logic` (2026-10-11): a build that cannot fail, other days, our own customers

Seven points from the advisor's list. None of it was run on the platform: this clone has no keys and no Claude
login, so everything below is checked offline (no model, no simulation). What must still be run with keys is at the
end.

**1. A build always ends with an agent** (`build.py`, `robust.py`, `minimal.py`, `llm.py`, `ingest.py`, `extract.py`).
- Each step has a way down: tolerant file reading (encodings, `.docx`/`.xlsx`/`.pdf` as text, Swagger 2 and
  `allOf`/`$ref` shapes); every model call has a time limit, one retry and a second model; a SPEC with problems is
  repaired by rule (`robust.coerce`) and what the format cannot hold becomes a free rule `builder-N`; the first agent
  that passes is saved before the Auditor runs, and the audited agent replaces it only when it builds as well; both
  modes are generated and a platform refusal moves to the next; with no usable SPEC `minimal.build` saves an agent
  that reads the documents itself.
- The trace status says which path was taken (`ok`, `ok (mode ...)`, `..., SPEC repaired by rule`,
  `ok (last resort)`). `BUILD_BUDGET_S` (1500), `BUILDER_CALL_TIMEOUT_S` (480), `BUILDER_MODEL_FALLBACK`.
- `dev/test_robust.py`, 108 checks with inputs and model calls that fail on purpose.

**2. Identity answers by type, not by field name** (`snippets/answers.py`, the verify tool's pre-hook).
- The SPEC's `value_type` decides the form: a date as the API asks, a year in four digits, a digit string without
  spaces even when said in parts or in words, a code in upper case without spaces. An answer already in the right
  form is unchanged; one the code is not sure about goes out as the model wrote it. `dev/test_answers.py`, 89 checks.

**3. Sentences read against a literal judge** (`sentences.py`, run before every save, findings in the trace).
- Forbidden words before identity, words that read as "it was saved" before a save, a placeholder said aloud, one
  of the brief's exact sentences that no fixed line says. The Reworder now also covers the amount sentences, the
  failure sentence and situation sentences.
- Found in our own fixtures: the below-minimum sentence said "cannot be recorded". The reference SPECs now say
  "I am not able to accept that amount."
- A sentence that code writes into a spoken variable is said as it stands, so a call variable inside it was spoken
  as a brace: code nodes now fill the call's variables in (`_say`), and a step before the end node (`say_farewell`)
  does it for every farewell.

**4. Other calendar days and unscripted customers, offline** (`dev/test_calendar_days.py`, `dev/test_properties.py`,
`dev/walk.py`, `dev/expect.py`).
- The generated agent is walked on every day of three months (61 business days, 31 weekend days and holidays), with
  the expected dates worked out from the brief's own text by a plain calendar (`dev/expect.py`), not by the builder's
  date code; and 7200 random conversations are checked against rules that must always hold (amount inside the
  range, date a business day up to the deadline, full amount first, attempts within the band, read-back equal to
  what is recorded).
- Four bugs found and fixed in the state machine: a call on a weekend day or a holiday recorded "yes, today" on
  that day; one non-business day named for all products moved only the first; an amount waiting for its day leaked
  to the next product or survived a new offer; at the read-back a proposal naming another product changed the
  promise being read back.
- v1 gets the same fact in its FACTS: "TODAY IS NOT A DAY A PROMISE CAN HAVE ... offer <next business day>".

**5. Our own customers for the platform** (`dev/scenarios.py`, `dev/run_scenarios.py`, `dev/test_scenarios.py`).
- 77 scenarios (58 Brief A, 19 Brief B) on the practice customers' accounts: seven Brief A and three Brief B
  conversations on five other days (a Friday, a Friday before a Monday holiday, the eve of a mid-week holiday, the
  month's last business day, 24 December), the callback window with the clock at 18:30, the rules no practice
  customer tests (unclear, wrong number, deceased, no callback, month as a word, declining, human before and after
  identity, dispute, scam question, below the floor, change at and after the read-back, hardship accepted, vague
  twice, not talking, Brief B closing rules), and the replies that only look like a restructuring request.
- The mock records any date, so only `now` is replaced in the session's variables. Scored like the kit's runner
  (ledger equal, judge's checks). More than 15 scenarios need `--all` and run as simulations of 12.
- Every expectation is checked twice without the platform: against the brief's rules (closing table, business day
  up to the deadline, floor to full amount, one record per product), and by playing the scenario through the
  generated orchestrated agent (`dev/walk.py`) and scoring its bank calls with the kit's scorer: 58 of the 58
  scenarios that reach the negotiation and all 12 callback scenarios leave exactly the expected records. The other
  seven end before the account step or in a model-driven step.
- That cross-check found one agent fault: "I paid both" noted only the product being discussed and then asked for
  the next one. A product situation now applies to every open product the customer means ("both", "all of them",
  "both loans"); one named product stays one product; an agreed promise is not undone (`_meant`,
  `dev/test_negotiation.py` 67 checks).
- Also added: a callback "in an hour" / "in half an hour" / "in 45 minutes" is a day and a time counted from `now`
  (`relative_time` in `snippets/dates.py`, used by the callback check; the extraction's example list names it).

**6. Speaking styles** (`dev/run_styles.py`): the kit's runner once per style (pieces, corrects, talkative,
asks_back, in_words), then a customer x style table from the result files.
- For the "pieces" style (a number or a date in two turns) the identity step now has two guards: its prompt says not
  to send half an answer, and the verify tool's pre-hook keeps a part that cannot be a whole answer and joins it
  with the next one ("44" then "71" -> 4471; "14 March" then "1988" -> the date; `whole_answer`, `digits_wanted` in
  `snippets/answers.py`). A whole answer is never joined with anything. This is the one change of this round to a
  prompt every call passes through: run the practice customers on a fresh build before anything else.

**7. Does the builder read a changed brief?** (`dev/mutate_brief.py`, `dev/test_mutations.py`).
- 16 copies of Brief A, each with one change (holiday added or removed, band limit moved, a third band, an outcome
  renamed in brief and API, six-day week, deadline in calendar days, a new situation with its own queue, a memo
  that overrides two rules, another identity question, two attempts in the early band, first ask reworded, callback
  window moved, two wrong answers, two retries, vague asked twice). `--run` extracts each (model calls: Claude
  login needed) and reports READ / MISSED / NOISY against a baseline extraction.
- Without a model, the generator's half is tested: the SPEC with each change made by hand builds clean in both
  modes and the walked agent follows it (29 checks). No change needed a generator fix.

**Tie-breakers.** The full amount is asked first on every path and the floor comes only after "too much" or as the
band's own second attempt (property test). The builder runs no simulation: build time is extraction plus about
ten seconds.

**Checks after this round**: test_spec_schema, test_dates 155, test_not_today 14, test_negotiation 67,
test_situation_guard 124, test_answers 89, test_robust 108, test_calendar_days 35, test_properties 13,
test_scenarios 24, test_mutations 29, test_generate 158: all pass; literal check clean. For the reference SPECs
the generated workflows differ from `df57913` only in: one new code node (`say_farewell`), the identity pre-hook,
the code of `setup`, `prepare_deal`, `finalize`, `check_callback`, `neg_eval` (orch) / `date_check` (v1), one
sentence added to the identity step's prompt (half an answer) and one example added to the callback extraction
text. System prompt, the other node prompts, transitions and tool definitions are the same.

**Not verified on the platform** (run these first, in this order, one simulation at a time):
1. A fresh build of A and A+B in both modes without `--spec` (the Reader must fill `evidence_words` and
   `value_type`; old extracted SPECs lack them, which only turns the new guards off). Read the trace: status,
   `sentence` lines, `fallback` lines.
2. `python tools/run_cases.py <agent> --brief A` and `--brief B` on the new agents: the extra hop through
   `say_farewell`, the identity pre-hook and `said_text` must not cost a practice customer.
3. `python dev/run_scenarios.py <agent> --brief A --grep look` (the reply that started this work), then
   `--grep cal-fri` and `--grep rule`. A failed scenario is our reading against the agent: read the call first.
4. `python dev/run_styles.py <agent> --brief A --plain`.
5. `python dev/mutate_brief.py --run --only six_day_week,third_band,memo_overrides_two_rules` when the Claude quota
   allows, then the rest.
6. The last resort has never spoken on the platform: `BUILD_BUDGET_S=1 python builder/build.py briefs/brief-a.md
   tools/openapi.json --slot yasar-exp-minimal` builds it on purpose; run the practice customers on it once.

### Tuning round from the practice runs of 11 October (~08:00-09:00 UTC, both modes, builds of `7bdf964`)

| Time (UTC) | Agent / mode | Brief | Reps | Score | Failed | Cause |
|---|---|---|---|---|---|---|
| 08:07 | `f0f76ac4` v1 | B | 1 | 3/3 | - | |
| 08:10 | `f0f76ac4` v1 | B | 1 | 2/3 | PUB-12 | model made a second offer (46.00) on the early-band car loan after a flat no; systematic in v1 (4 of 5 runs) |
| 08:15 | `8cfaf7c8` orch | B | 1 | 3/3 | - | |
| 08:18 | `9d9d0eda` v1 | A | 1 | 7/10 + 1 inconclusive | PUB-07, PUB-09 (PUB-05 judge inconclusive) | see below |
| 08:52 | `9abb796e` orch | A | 1 | 9/10 | PUB-06 | see below |

Calls read one by one (`GET /api/v2/call/<id>`); causes and fixes, all generic:

- **v1 PUB-07, 30 failed identity checks: a platform failure that fed itself.** The first `verify_identity`
  pre-hook run failed with `Failed to parse sandbox result JSON: Unterminated string ... (char 9971)`: the sandbox
  output was cut (the variables were about 5 KB, the same size as in calls where the same hook worked, so this
  looks like a one-off platform cut, not a size limit of ours). The platform then stored its error message, which
  quotes the output with the result marker `__CODE_EXEC` `_RESULT__`, in `verify_identity_response.message`. Every
  later sandbox run prints all variables, so its output holds the marker twice; the platform splits on the wrong
  one and fails with `Expecting property name enclosed in double quotes: line 1 column 2` (the text after the
  marker inside a JSON string starts with `{\"`). That repeated for the rest of the call. Fix: every code node
  (`codegen.embed`) and every hook (`codegen.scrubbed`, used by `api_fn` and `minimal.py`) first replaces the
  marker in any variable. A one-off cut now costs one retry, not the call.
- **v1 PUB-09, "I cannot pay this amount. I want lower instalments." four times, no transfer.** The look-alike
  guard ("a plain no, saying they cannot pay ... is NOT this"), repeated in every situation of the v1 prompt and
  in each exit's description, won over the explicit request. orch passed it (the evidence check in code saw the
  words). Fix: the guard now says that a message that ALSO asks for the situation in so many words IS that
  situation, even if it says they cannot pay, and names the SPEC's evidence words as examples when there are
  any; the v1 situation list and the orch classifier say the same. The agent of this run was built from an
  older SPEC without `evidence_words`, so the rule must and does work without them.
- **orch PUB-06, "How much is the minimum payment?"**: `negotiate_q` answered "The minimum payment is 637.50"
  and then said the open offer again with its date; the judge counted two offers of the floor. Fix: after
  answering a question about the offer that was the agent's last sentence, the state machine says only
  "Does that work for you?"; the answer instruction says to state an amount or day already offered as a fact,
  not as a new offer. A question after another sentence (for example "On which day ...?") still repeats that.
- **Open findings from the first review, fixed now**: a self-correction in an amount ("150, no actually 200",
  "two hundred, sorry, two fifty") keeps the last amount; a no to today said after the day ("right now I can't,
  maybe Friday") is not today.
- **Not changed: v1 PUB-12.** The facts and rule D already forbid the second offer; the model counts attempts.
  orch decides attempts in code and passed PUB-12 in every orch run so far. Reason to prefer orch.
- **Latency (orch)**: most of a slow turn is the extraction call (3 to 17 s in PUB-06), not code (0.3 to 3 s).
  The `reply_kind` description is long (every situation's trigger and look-alikes). Not changed this round.

New: `dev/test_tuning.py` (the four fixes, on brief-a, brief-ab and imaginary-c, both modes). All suites pass.

### Decisions after the tuning round (11 October, ~10:00 UTC)

| Decision | Reason |
|---|---|
| **orch is the shipped mode and the default of `build.py`** | orch A 9/10 (its one loss fixed in `e4dc922`), orch B 3/3 in every run; v1 A 7/10, v1 B fails PUB-12 in 4 of 5 runs (the model counts attempts). The official run command passes no `--mode`, so the organisers' rerun must get orch by default |
| `--slot` is optional: the brief file names give it (`hidden-1.md` -> `hidden-1`) | The official run command is `cd build-the-builder && python3 builder/build.py {brief_path} {tool_api_path}`, with no options |
| Paths are found from the working directory, the repository root or the kit folder | The form's paths may be relative to the repository root while the command runs in `build-the-builder/` |
| `submission/` (repository root) is committed; `out/` and `traces/` stay ignored | The exported workflows and the selected traces are submitted from the repository |
| A transient platform error is retried, not taken as a refusal | Both builds of this morning (fresh extraction, orch) got 504 on every dry run, then 401 "invalid JWT" to a valid key while the platform was down; `publish` read each as "the dry run refused it" and stepped down to v1, then to the last resort, and saved nothing. Now only 400/404/409/413/422 is a refusal; anything else (5xx, 401/403, 408, 429, timeouts, lost connections) is retried with a growing wait (5 s up to 60 s) while 97% of the budget lasts. Tested with a fake platform in `test_robust.py` |

Checkpoint before these changes: tag `checkpoint-tuning-1` (= `e4dc922`, pushed).
The two builds' extracted SPECs are in `out/yasar-tune-a.spec.json` and `out/yasar-tune-ab.spec.json` (Reader +
audit done; not saved on Freya): `--spec` builds them in seconds once the platform answers.

### Platform outage, 11 October ~09:30-10:30 UTC

- The API answered 504, then 401 "invalid JWT" to a valid key, then 503 "API key validation is temporarily
  unavailable". `run_cases.py` died twice while polling a simulation that had started (sim `875ade46`).
- `dev/run_cases_retry.py`: the kit's `run_cases.py` unchanged, with `freya.api` patched in memory to retry a
  transient error (same rule as `build.transient`, at most ten minutes per call). Use it for practice runs while the
  platform is unsteady.
- Fresh-extraction SPECs of this morning saved as orch agents with `--spec`: `yasar-tune-a` (agent `2c7148d5`),
  `yasar-tune-ab` (agent `62a00865`, version 2: its opening said "this call is recorded" because the Reworder's
  answer still held "recorded" and was dropped silently; fixed in `184897c` and the SPEC re-run through it).

### orch PUB-06, rep 2 (11 October, ~10:35 UTC): the read-back counted as a second floor offer

- Sim `929efc9f`, PUB-06 judged **fail**: "the minimum payment (637.50) was offered in Message 8 and then again in
  Message 10 for a different date ... the second offer did not include the note that the rest stays overdue".
  Rep 1 of the same agent passed the same flow. Replayed with `dev/walk.py` (the platform answered 504 again): the
  floor is offered for today ("Can you pay 637.50 ... on Wednesday 14 October 2026? The rest stays overdue."), the
  customer names Friday, and the read-back "So that is 637.50 ... on Friday 16 October 2026. Do you confirm?" reads
  like a new offer of the floor on another day. Code did the right thing (one offer, one promise 637.50 / 16 Oct).
- Fix: the read-back is worded as the customer's own promise: "Let me read your promise back: you will pay 637.50
  ... Do you confirm?" (orch, `_read_back`); v1's task says the same in words. Test in `dev/test_tuning.py`.
- The agent on Freya must be rebuilt (`--spec out/yasar-tune-a.spec.json`) to carry it; not done while the API is down.

### Generalisation round 1 (11 October, offline while the platform answered 504)

Principle: every failure is a rule the machine does not have yet; it is fixed at the layer that decides (code,
sentence, classification, SPEC, noise) and tested on every bank. New bank **imaginary-d** (`dev/specs/imaginary-d.md`,
reference SPEC and a tool API with other field names): no third party, a promise never for today ("Could you pay this
tomorrow?"), refused days are refused (not moved), attempts counted for the whole call, a read-back per promise,
promise_wins on transfer, three identity questions with one wrong answer ending the check.

What D found, all fixed in `builder/`, none of it visible with A, B or C:
- **The first ask was always about today.** A yes to "Could you pay this tomorrow?" was turned into "today" and
  refused. The plan now carries `ask_day` (the SPEC's earliest day); a yes agrees on the first day a promise can
  have. The per-product ask agrees on that day too (it agreed on today, also on a Saturday). v1's facts say so.
- **"Could you make that payment" for another amount.** After the floor was named, every later offer below the full
  amount dropped its amount: D's attempt 2 (60 percent) would have been agreed as "that payment" and recorded at
  540 while the customer heard 150. The short form is now used only for the SAME amount said before with the note.
- **"Too much" twice without a SPEC sentence** offered the floor again and again (`floor_offered` was only set with
  the sentence). Now set whenever the floor is offered.
- **A refused day dropped the customer's own amount**: "1000 on 30 October" (after the deadline, reject mode) went
  back to the full amount. The amount now waits for another day ("On which day can you pay 1000.00 ...?").
- **No day between the earliest day and the deadline** (last business day of the month = today, earliest tomorrow):
  the agent agreed on today. The deadline is now moved to the earliest day, and ladder days never fall before it.
- A day past the plan's 70-day list was said as an ISO date; it is now spoken with its weekday.
- Fallback paths: `robust.bind` finds the product key as the field the promise request shares with the account's
  products (D calls it `facility`); `robust.coerce` no longer raises a disabled callback's `max_asks`;
  `minimal.closings` also reads "close as `x` / `y`" in running text.

Tests: `dev/test_generalize.py` (new, by rule family); D added to test_properties (2160 random conversations),
test_tuning, test_situation_guard, test_spec_schema, test_robust. Two properties were Brief-A-shaped and are now read
from the SPEC (a day is checked against the SPEC's earliest day, not today; a read-back per promise).
Known limit: `notes.on_transfer = "add"` has no field for the note's reason; D does not use it.

### Generalisation round 2: the customer's language, and the Reader on a brief it never saw

- `dev/test_language.py` (new): random amounts and days said the way people say them (digits, words, cents,
  currency words, "the 16th", "Saturday the 28th", "16/10", "in twenty-seven days", fillers, self-corrections),
  thousands per run, the expected value worked out with datetime. Amounts: all pass. Days, two fixes in
  `snippets/dates.py`: a weekday with a day number and no month ("Saturday the 28th") now names the month (the next
  28th that is a Saturday; it took the next 28th of any weekday); "in twenty-seven days" (a hyphen) was not read.
- **The Reader on imaginary-d, twice** (`--no-save`, 270 s each): both SPECs valid, both workflows pass every local
  check in both modes. Every field that decides behaviour (calendar, the three bands' deadlines and ladders, the
  earliest day, the refuse modes, the vague rule, the amounts, the call's attempt limit, the multi-product flags,
  recording, identity, outcomes) is identical in both and equal to the reference. The Reader also found D4 (not the
  member) that the hand-written reference had missed. The one field that differed between the two runs: whether a
  facility whose attempts ran out gets a note (the brief is ambiguous: D21 says close as declined, D30 says "the
  first note's reason"). Field guide tightened: `for_each_product_without_promise` is true only when the brief says
  so in words; a "first note's reason" closing alone does not.

### Mock briefs merged into `fix-agent-logic`, and what they found (11 October, ~14:00 UTC)

`dev/mock_briefs/` (branch `mock-briefs`, only new files) was merged into `fix-agent-logic` at `54266e9`. It holds
five briefs we wrote, each bank in both forms the final announces (a consumer bank as raw material and as a clean
specification, a business bank the same, and the kit's Brief A+B with twelve rules changed on the kit's own API),
their oracle SPECs, 198 customers with the bank records each brief requires, customers made from any SPEC alone,
68 one-rule variants of a SPEC, and a walker that plays whole calls through the generated workflow without the
platform. `dev/mock_briefs/README.md` has the layout and the findings; `python dev/test_mock_briefs.py` runs it all
in a minute.

Every check of the repository on the merged branch: the 16 existing ones pass. `test_mock_briefs` failed 13 tier-1
checks, all from four causes, two of them in the Brief A+B agent itself (orch): the "already paid" sentence was
never said when that product was the last open one, and a promise that could not be saved was never told to the
customer. The other two are in `snippets/answers.py`: a numbers-only date of birth was read month first with Brief
A's own format words, and a code said character by character went out as words. All four are fixed in `bb8e28e`,
with four tier-2 closes (no callback, notes without a closing rule for several products, half a cent, a persuasion
date on a Sunday). After it: the 16 existing checks pass, `test_mock_briefs` has tier 1: 0, tier 2: 8, tier 3: 12.

Not verified: the Reader on the mock briefs (`python dev/run_mock_briefs.py --extract`, about two minutes of model
time per pack; this clone has no Claude login) and pack F on the platform (`--simulate`, needs the keys). What is
still open is listed in the README, by tier.

Second round, same afternoon: an evidence word that only begins a longer word of the agent's own sentences ("person"
before a product name) is kept as a whole word instead of dropped (`=` marks it; `has_evidence` reads it); one day
for several products that none of them can have says so and asks for another day instead of using up an attempt.
A single product's refused day was left as it is: `imaginary-d.md` D13 asks to repeat the open offer, packs D and E
ask which day suits, and `reject` is one value (listed under "Rules the SPEC cannot say").
`dev/walk_practice.py` (new) plays the 13 practice customers through the walker and scores the records with
`tools/score.py`: 13 of 13 on the reference SPECs, in two seconds. It checks what code decides, not the conversation.

