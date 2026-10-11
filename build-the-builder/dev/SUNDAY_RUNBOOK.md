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
python dev/test_negotiation.py | tail -1   # all good
python dev/test_generate.py | tail -1      # all good (about 2 minutes)
python dev/check_no_brief_literals.py | tail -1   # clean
```

- Decide the negotiation mode from `JOURNAL.md` (decision point 11:00 UTC): `--mode orch` if it beat v1 on A and B
  with `--reps 3`, otherwise `--mode v1`. Write the decision in the journal.
- Agree with the teammate who runs simulations on Sunday evening: none are needed for hidden briefs, keep the
  workspace free.

## 17:00 UTC: for each hidden brief

1. Put the files in a folder **outside** `builder/`, for example `hidden/1/` (all brief documents + its tool API
   `.json`). Do not open them in an editor session that writes code: nothing from them may enter `builder/`.
2. Build (one command, no flags other than slot and mode):
   ```bash
   time PYTHONUTF8=1 python builder/build.py hidden/1/*.md hidden/1/*.csv hidden/1/*.txt hidden/1/<api>.json --slot yasar-final-1 --mode <v1|orch>
   ```
   (Leave out globs that match nothing. Every non-`.json` file is read as a brief document; the last `.json` is the
   tool API.)
3. Read the trace `traces/yasar-final-1-<time>.log`. Check:
   - `status=ok`, total time far below 30 minutes;
   - `spec valid:` line: identity questions, bands, situations, outcomes, products and holidays look like the brief;
   - every `audit` line: is a finding real? if the auditor repair was not applied, read `out/yasar-final-1.audit.json`;
   - `lint: pass`, snippets `pass`, `dry run: pass`, `saved and published`, `exported`.
4. Open `out/yasar-final-1.spec.json` and compare by eye with the brief: dates and holidays, band thresholds and
   deadline rules, outcome and reason names (must be the API's enum values), memo overrides (look for `Override:`
   in `free_rules`).
5. Repeat for the second brief with slot `yasar-final-2`.

Do **not** run `tools/run_cases.py` on a hidden brief: the practice customers belong to Brief A/B and would test the
wrong rules.

## If something breaks

Allowed: a **bug fix that contains nothing from the hidden brief**, for example a parser that crashes on an
unexpected table shape, a validator that rejects a legal value, a code path that raises. Write in the journal:
what broke, the generic fix, and why it contains no brief content. Run the four test suites and the literal check,
commit, rebuild.

Not allowed: adding a value, a name, a rule or a sentence from the hidden brief to `builder/` or to a prompt;
editing the agent on the platform; changing `AGENT_LLM`; sending `agent_config`.

If the SPEC is wrong in one field and the builder cannot be fixed generically in time: rebuild once (extraction is
not deterministic); keep the run whose trace and SPEC are right, and submit that run's trace.

## Submission

```bash
cp out/yasar-final-1.export.json submission/<brief-1-name>.workflow.json
cp out/yasar-final-2.export.json submission/<brief-2-name>.workflow.json
git add builder dev/JOURNAL.md
git add -f traces/<selected-final-1>.log traces/<selected-final-2>.log
git commit -m "final: builds for the hidden briefs"
git push origin yasar/hybrid-builder
git rev-parse HEAD                          # the commit for the form
```

Submit: the two exported workflow files, the commit hash, the two traces (`traces/yasar-final-1-*.log`,
`traces/yasar-final-2-*.log`). Earlier submission wins ties: do not wait for the deadline.
