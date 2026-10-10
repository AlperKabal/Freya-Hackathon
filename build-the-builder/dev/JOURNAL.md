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
