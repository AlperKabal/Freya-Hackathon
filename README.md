# Freya-Hackathon

A hybrid builder that turns bank briefs and an OpenAPI tool definition into a
published Freya phone-agent workflow. All runtime commands run from
`build-the-builder/` in Git Bash.

## Setup

```bash
git clone --branch yasar/hybrid-builder https://github.com/AlperKabal/Freya-Hackathon.git
cd Freya-Hackathon
python -m pip install -r requirements.txt
cd build-the-builder
cp env.example env.sh
```

Set the workspace credentials privately in `env.sh`, then:

```bash
source env.sh
export PYTHONUTF8=1
```

Use Python 3.10 or newer. Builder extraction uses the Claude Agent SDK with an
authenticated Claude login or `ANTHROPIC_API_KEY`. The default builder model is
`claude-opus-5-5`; override it with `BUILDER_MODEL` if needed. Never commit keys.

## Build

The official run command (also the one in the submission form):

```bash
cd build-the-builder && python3 builder/build.py {brief_path} {tool_api_path}
```

Examples from `build-the-builder/`:

```bash
python builder/build.py briefs/brief-a.md tools/openapi.json                     # slot brief-a, mode orch
python builder/build.py briefs/brief-a.md briefs/brief-b.md tools/openapi.json   # slot brief-a+brief-b
```

The tool API file is recognised by its content. The slot defaults to the brief file
names and the mode to `orch` (the shipped mode, decided 11 October): the organisers'
rerun passes no options and must build the same agent. `--slot` and `--mode v1` still
exist for development; `--spec <file>` reuses a previously extracted SPEC; `--no-save`
runs generation and local checks without publishing. Paths may be given from the
repository root or from `build-the-builder/`.

Outputs are written to `out/` and `traces/`, both ignored by Git; the files to submit
(exported workflows, selected traces) are copied to `submission/`, which is committed.
Reuse slot names to update workflows in place. A transient platform error (5xx, a 401
during an outage, a timeout) is retried within the build budget; only a refusal of the
request (400, 404, 409, 413, 422) makes the builder try its next candidate.

A build always ends with an agent. Each step has a fallback, and the trace says
which one was used:

- an unreadable or oddly shaped input file is read as far as it can be;
- a model call has a time limit, is retried, then repeated on a second model;
- a SPEC with problems is repaired by rule, and what the SPEC format cannot hold
  is kept as a free rule for the agent to read;
- the first agent that passes is saved at once; the audit pass only replaces it
  with an agent that is at least as sound;
- if the chosen mode does not generate or the platform refuses it, the other mode
  is tried; with no usable SPEC at all, a simple agent that reads the documents
  itself is saved.

The final status of the trace is plain `ok` only for the normal path. Anything else
(`ok (mode v1)` when orch was asked, `ok (..., SPEC repaired by rule)`,
`ok (last resort)`) means a fallback was used: read the trace before submitting.

| Variable | Default | Meaning |
|---|---|---|
| `BUILDER_MODEL` | `claude-opus-5-5` | model for extraction |
| `BUILDER_MODEL_FALLBACK` | `claude-sonnet-5-5` | used when the first model fails twice |
| `BUILDER_CALL_TIMEOUT_S` | `480` | time limit of one model call |
| `BUILD_BUDGET_S` | `1500` | time budget of the whole build |

## Checks

None of these needs a key or a model:

```bash
python dev/test_spec_schema.py
python dev/test_dates.py
python dev/test_not_today.py
python dev/test_negotiation.py
python dev/test_situation_guard.py
python dev/test_answers.py          # identity answers sent in the form the tool API asks for
python dev/test_robust.py           # broken inputs, failing model calls, the fallback ladder
python dev/test_calendar_days.py    # the agent walked on every day of three months
python dev/test_properties.py       # thousands of random conversations against fixed rules
python dev/test_scenarios.py        # our own customers and their runner
python dev/test_mutations.py        # changed copies of Brief A: the generator follows each change
python dev/test_generate.py         # about 2 minutes
python dev/check_no_brief_literals.py
```

## Testing an agent beyond the practice set

These need `env.sh` (and, for the last one, the Claude login). One simulation runs
at a time in the shared workspace. They are for Brief A/B agents only.

```bash
python dev/run_scenarios.py --list                      # no network: our own customers and what each must leave behind
python dev/run_scenarios.py <agent_id> --brief A        # other calendar days, untested rules, look-alike replies
python dev/run_styles.py <agent_id> --brief A --plain   # the practice customers in each of the five speaking styles
python dev/mutate_brief.py --run --only six_day_week,third_band   # does the builder read a changed brief?
```

## Collaboration

- Read `dev/DEV_AGENT_PROMPT.md`, `dev/JOURNAL.md`, `dev/ARCHITECTURE.md`, then
  `dev/SUNDAY_RUNBOOK.md` before making changes.
- Use separate clones or worktrees for concurrent coding sessions, and agree on
  file ownership. Do not edit the same files in parallel.
- Use distinct `yasar-` slot names for separate agents, but reuse each slot across
  rebuilds. Only one simulation may run at a time in the shared workspace.
- The Claude login quota is shared. Reuse extracted SPECs when testing generator
  changes.
- Keep the supplied kit unchanged. Runtime code is in `builder/`; tests, fixtures,
  and developer utilities are in `dev/`.
- Never run practice cases against hidden briefs. Follow the Sunday runbook.
- Generated results, caches, local credentials, and archives are not repository
  inputs. Final submission traces must be selected explicitly when staging.

Historical one-off experiments were removed during repository cleanup. Their
verified findings remain in the journal, and their source remains in Git history.
