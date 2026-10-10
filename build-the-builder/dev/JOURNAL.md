# Journal: yasar/hybrid-builder

Branch owner: Yaşar. Plan and rules: `dev/DEV_AGENT_PROMPT.md`. Workflow slots on Freya start with `yasar-`.

## Decisions

| When (UTC) | Decision | Reason |
|---|---|---|
| 2026-10-10 | Branch `yasar/hybrid-builder` created from `main` (68398a9) | Own branch, teammate works in parallel |
| 2026-10-10 | `.gitignore` at repo root (not inside `build-the-builder/`) | Patterns without a leading slash cover the whole repo |
| 2026-10-10 | New code goes to `build-the-builder/builder/`, dev tools to `build-the-builder/dev/` | Kit files stay unchanged; `run_cases.py` resolves paths relative to the kit folder |

## Freya slots (ours)

| Slot | workflow_id | agent_id | Content |
|---|---|---|---|
| `yasar-base` | `c11d1a5b-d386-4429-a11c-311ca824da28` | `96ec991c-9aaf-4c2b-b5aa-7635acc439a4` | `examples/base-agent.json`, unchanged |

## Test runs

| Time (UTC) | Workflow / version | Brief | Style | Reps | Score | Failed cases | Cause |
|---|---|---|---|---|---|---|---|
| 2026-10-10 16:04 | `yasar-base` v1 (base agent) | A | none | 1 | **0/10** (README said ~2/13) | all | see "Baseline analysis" below; median slowest turn 5 s, so not a slow-model run |

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
- On this Windows machine `python3` is not available (Store alias); use `python` (3.14.6).
- `anthropic` and `claude_agent_sdk` are not installed yet.
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

- Example builder: score, build time, cost on Brief A (blocked on the missing skill file).
- `docs/workflow-format.md` says "no `null` values", but `examples/base-agent.json` contains
  `"max_turn_transition": null` and `"passthrough_default_transition": null` (it looks like a platform export).
  Check with a dry run whether the API accepts these nulls; our generator will emit no nulls either way.
  **Partial answer (2026-10-10):** `POST /api/v2/workflow` accepted `base-agent.json` with these two nulls.
  Not tested: nulls in other fields. Rule for us stays: emit no nulls.
- The base agent's `close_call` bakes `{{outcome}}`/`{{reason}}`, but nothing in the workflow ever sets those
  variables, so the end-of-call model guesses them. Confirm in a transcript of the baseline run.
