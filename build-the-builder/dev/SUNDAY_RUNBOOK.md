# Sunday runbook (hidden briefs, 11 October 2026)

Times in UTC (Turkey = UTC+3). Briefs open **17:00 UTC (20:00 TR)**. Submission closes **20:00 UTC (23:00 TR)**.
Target: both agents built, checked, exported and submitted by **19:00 UTC**.

All commands run in Git Bash, in `build-the-builder/`, on branch `yasar/hybrid-builder`.

## Before 17:00 UTC

```bash
git pull --ff-only                          # published branch with upstream configured
source env.sh                              # FREYA_API_KEY, FREYA_API_URL, FREYA_BANK_TEAM_KEY
python dev/check_claude_login.py           # "auth: Claude login" or API key, model answers
python dev/test_spec_schema.py | tail -1   # all good
python dev/test_dates.py | tail -1         # all good
python dev/test_not_today.py | tail -1     # all good
python dev/test_negotiation.py | tail -1   # all good
python dev/test_situation_guard.py | tail -1   # all good
python dev/test_answers.py | tail -1       # all good
python dev/test_robust.py | tail -1        # all good
python dev/test_calendar_days.py | tail -1 # all good
python dev/test_properties.py | tail -1    # all good
python dev/test_scenarios.py | tail -1     # all good
python dev/test_mutations.py | tail -1     # all good
python dev/test_generate.py | tail -1      # all good (about 2 minutes)
python dev/test_tuning.py | tail -1        # all good
python dev/check_no_brief_literals.py | tail -1   # clean
```

With time left and the workspace free (Brief A/B agents only, never a hidden brief's agent):

```bash
python dev/run_scenarios.py <agent_id> --brief A --grep cal-fri --out results/sc-a.json   # other calendar days
python dev/run_scenarios.py <agent_id> --brief A --grep look --out results/look-a.json    # replies that look like a transfer request
python dev/run_styles.py <agent_id> --brief A --tag final-a                               # the five speaking styles
```

A failed scenario is OUR reading of the brief against the agent: read the call (`dev/show_call.py`) before changing
anything.

- **Mode decided (11 October): orch.** It is the default of `build.py`, because the official run command passes no
  `--mode`; the organisers' rerun must produce the same agent as ours.
- Agree with the teammate who runs simulations on Sunday evening: none are needed for hidden briefs, keep the
  workspace free.

## 17:00 UTC: for each hidden brief

1. Put the files in a folder **outside** `builder/`, for example `hidden/1/` (all brief documents + its tool API
   `.json`). Do not open them in an editor session that writes code: nothing from them may enter `builder/`.
2. Build with the official run command (the one in the submission form), no options:
   ```bash
   cd build-the-builder && time PYTHONUTF8=1 python3 builder/build.py <brief_path> <tool_api_path>
   ```
   The slot is the brief file's name (`hidden-1.md` -> slot `hidden-1`), the mode is orch. A path may be given from
   the repository root or from `build-the-builder/`. The hidden brief is one Markdown file plus its tool API file;
   more brief files also work (every file that is not the API is a brief document).
3. Read the trace `traces/<slot>-<time>.log`. Check:
   - `status=ok`, total time far below 30 minutes. The build always ends with an agent, so a status other than plain
     `ok` means a fallback was used and must be read before submitting: `ok (mode ...)` names the mode that was
     saved (if it is not the one you asked for, the asked mode did not generate or the platform refused it);
     `SPEC repaired by rule` = the Reader's SPEC did not validate and was mended (the `spec-note` lines list what
     was dropped or replaced; that content is kept in `free_rules` as `builder-N`); `ok (last resort)` = no usable
     SPEC, the saved agent reads the documents itself (rebuild once before accepting it);
     `ok (an agent was saved before a later step failed)` = see the `fallback` and `error` lines;
   - `sentence` lines (`problem` or `note`): a forbidden word before identity, a word like "recorded" before a save,
     a placeholder said aloud, or one of the brief's exact sentences that no fixed line says. Each names the node;
   - `spec valid:` line: identity questions, bands, situations, outcomes, products and holidays look like the brief;
   - every `audit` line: is a finding real? if the auditor repair was not applied, read `out/<slot>.audit.json`;
   - the `selftest` lines end in `pass` (lint and local runs of every code node and hook; dry run), then
     `saved and published`, `exported`. Any `fallback` line says which step gave way and what was used instead.
4. Open `out/<slot>.spec.json` and compare by eye with the brief: dates and holidays, band thresholds and
   deadline rules, outcome and reason names (must be the API's enum values), memo overrides (look for `Override:`
   in `free_rules`). For every situation that transfers the call: `not_this` rules out a plain refusal and a question
   about options, and `evidence_words` holds only words of that request (no everyday word such as a word for paying).
5. Repeat for the second brief (its own file name gives its own slot).

Do **not** run `tools/run_cases.py` on a hidden brief: the practice customers belong to Brief A/B and would test the
wrong rules.

## If something breaks

Allowed: a **bug fix that contains nothing from the hidden brief**, for example a parser that crashes on an
unexpected table shape, a validator that rejects a legal value, a code path that raises. Write in the journal:
what broke, the generic fix, and why it contains no brief content. Run the checks listed above and the literal
check, commit, rebuild.

A slow or failing model does not need a fix: a call is retried and then repeated on `BUILDER_MODEL_FALLBACK`, and
the build keeps to `BUILD_BUDGET_S` (default 1500 s). If the Claude login's quota is gone, set `ANTHROPIC_API_KEY`
or another `BUILDER_MODEL` and rebuild.

Not allowed: adding a value, a name, a rule or a sentence from the hidden brief to `builder/` or to a prompt;
editing the agent on the platform; changing `AGENT_LLM`; sending `agent_config`.

If the SPEC is wrong in one field and the builder cannot be fixed generically in time: rebuild once (extraction is
not deterministic); keep the run whose trace and SPEC are right, and submit that run's trace.

## Submission

`submission/` at the repository root is committed (`out/` and `traces/` stay ignored). From `build-the-builder/`:

```bash
mkdir -p ../submission
cp out/<slot-1>.export.json ../submission/<brief-1-name>.workflow.json
cp out/<slot-2>.export.json ../submission/<brief-2-name>.workflow.json
cp traces/<slot-1>-<time>.log traces/<slot-2>-<time>.log ../submission/
git add ../submission builder dev/JOURNAL.md
git commit -m "final: builds for the hidden briefs"
git push origin <branch>
git rev-parse HEAD                          # the commit for the form
```

Form: run_command `cd build-the-builder && python3 builder/build.py {brief_path} {tool_api_path}`; the two exported
workflow files, the commit hash, the two traces. The repository must be readable by the organisers (public, or
access given: ask them). Earlier submission wins ties: do not wait for the deadline.
