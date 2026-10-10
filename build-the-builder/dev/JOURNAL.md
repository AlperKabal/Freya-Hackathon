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

## Platform and kit facts (verified by us)

- The kit lives in `build-the-builder/`. All kit commands run from that folder (`freya.py` is imported from cwd).
- On this Windows machine `python3` is not available (Store alias); use `python` (3.14.6).
- `anthropic` and `claude_agent_sdk` are not installed yet.
- `.claude/skills/build-phone-agent/SKILL.md` is referenced by the README and by `examples/agent_builder.py`, but is
  **missing from the repository** (it was probably dropped because `.claude/` is a hidden folder). The example
  builder cannot run as shipped until we get the skill from the organisers' kit.
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

## Open questions

- Does the mock open a practice session for a case id that is not in the public set? (to test in Phase 0)
- Example builder: score, build time, cost on Brief A (blocked on the missing skill file).
- `docs/workflow-format.md` says "no `null` values", but `examples/base-agent.json` contains
  `"max_turn_transition": null` and `"passthrough_default_transition": null` (it looks like a platform export).
  Check with a dry run whether the API accepts these nulls; our generator will emit no nulls either way.
  **Partial answer (2026-10-10):** `POST /api/v2/workflow` accepted `base-agent.json` with these two nulls.
  Not tested: nulls in other fields. Rule for us stays: emit no nulls.
- The base agent's `close_call` bakes `{{outcome}}`/`{{reason}}`, but nothing in the workflow ever sets those
  variables, so the end-of-call model guesses them. Confirm in a transcript of the baseline run.
