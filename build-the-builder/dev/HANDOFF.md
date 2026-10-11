# Handoff: state of `yasar/hybrid-builder` (Saturday 10 Oct 2026, ~20:00 UTC)

You are taking over a hackathon builder from another agent. Read, in this order: `dev/DEV_AGENT_PROMPT.md`
(the rules and the teaching protocol: explain to Yaşar in Turkish, code/commits/journal in English),
`dev/JOURNAL.md` (every decision, run and verified platform fact), `dev/ARCHITECTURE.md`, `dev/SUNDAY_RUNBOOK.md`.

## Setup
- Repo root `Freya-Hackathon/`, kit in `build-the-builder/`; run everything from there in Git Bash.
- `source env.sh` (you may run simulations; never print keys). Use `PYTHONUTF8=1`. `python3` works via a shim.
- Builder model calls go through the Claude Agent SDK with Yaşar's Claude Pro login (shared quota: be frugal).
- **Commits: no Co-Authored-By / Claude attribution, ever.** Branch is local only (never pushed): ask before pushing.
- Before every commit: the four checks below + `git diff --cached | grep -iE "fak_[a-z0-9]{8}|sk-ant-"`.

## What exists
`python builder/build.py <brief files...> <tool_api.json> --slot <name> [--spec file] [--mode v1|orch] [--no-save]`
- ingest -> extraction agents (Reader + Binder in parallel, validation/repair, Reworder, Auditor; ~2 min) ->
  `generate.py` (SPEC -> workflow, deterministic) -> lint + code nodes run on 36 calendar days -> dry run -> save
  -> export -> trace in `traces/`. Outputs in `out/<slot>.*` (spec, audit, workflow, export).
- `--mode v1`: one LLM negotiation node (proven). `--mode orch`: state machine `builder/snippets/negotiation.py`
  decides offers, TTS says them, engine-run `create_promise`; model only answers questions (`negotiate_q`).
- Checks (no key, no model): `python dev/test_spec_schema.py`, `dev/test_dates.py`, `dev/test_not_today.py`,
  `dev/test_negotiation.py`, `dev/test_situation_guard.py`, `dev/test_answers.py`, `dev/test_robust.py`,
  `dev/test_calendar_days.py`, `dev/test_properties.py`, `dev/test_scenarios.py`, `dev/test_mutations.py`,
  `dev/test_generate.py` (about 2 minutes), `dev/check_no_brief_literals.py`.
- Beyond the practice set (need keys; Brief A/B agents only): `dev/run_scenarios.py` (our own customers on other
  calendar days, expected records from `dev/expect.py`), `dev/run_styles.py` (the five speaking styles),
  `dev/mutate_brief.py --run` (changed copies of Brief A through the extractor; needs the Claude login).
- A build always ends with an agent (fallback ladder in `builder/build.py`, `robust.py`, `minimal.py`): a trace
  status other than plain `ok` names the fallback that was used.
- Debug a run: `python dev/show_call.py results/<run>.json PUB-xx > results/x.txt` (speech, nodes, tools, variable changes).

## Scores (practice cases; SPECs extracted by the builder itself)
- **v1, `--reps 3`: A 10/10, B 2/3 (PUB-12 0/3)** -> submittable baseline 12/13. PUB-12 cause: the model makes a
  second offer on the early-band car loan (1 attempt allowed).
- orch v2: A 9/10, B 2/3: code decided right, but the model said other offers and filled other tool dates.
- **orch v3 (TTS + engine recording) was just started**: results land in `results/o3-b.log`, `results/o3-a.log`
  (summary `results/o3.out`). Read them first.

## Freya slots (`.freya-agents.json`)
| slot | agent_id | content |
|---|---|---|
| yasar-extract-a | 46fb1c38-f443-4417-b2c8-a4cb717fd9ec | v1, Brief A (spec `out/yasar-extract-a.spec.json`) |
| yasar-extract-ab | 4e8fa2ea-3a1c-4420-be33-57f537eacb05 | v1, Brief A+B (spec `out/yasar-extract-ab.spec.json`) |
| yasar-orch-a | a20dfc9a-7009-4333-96ad-a0bdeb7d4a88 | orch v3, Brief A |
| yasar-orch-ab | 29085d75-22d4-43f6-86c9-db38fb207568 | orch v3, Brief A+B |
| yasar-exp-date | - | shared slot for experiments (`dev/exp_sim.py`, `dev/exp_engine.py`) |
Rebuild an agent fast without re-extracting: `--spec out/yasar-extract-<a|ab>.spec.json`.

## Verified platform facts you will otherwise relearn (details in JOURNAL)
- `type: "date"` extraction uses the REAL clock, not `now`: extract words as strings, resolve in code.
- Chat API skips the initial code node and fails (503/504) on code nodes mid-call: test with simulations.
- The extractor re-reads old values from history; code decides what is new (turn-number guard).
- A node entered with `on_enter: silent` says and does nothing that turn; `on_enter: tts {{var}}` re-speaks on
  every re-entry; same-node re-entry after a code hop answers in the same turn.
- Engine-run api_request with amount baked from a code var records a number; pre-hooks run in pre_actions.
- Writing `''` to an enum extraction var is rejected; a code write violating a field's validation_pattern too.
- Parallel tool calls run their post-hooks on separate copies: decide "all done" in routing conditions.
- The judge is literal (e.g. "recorded" before a successful save).

## Next steps
1. Read orch v3 results; if a case fails, find the cause in the transcript before changing anything.
2. If orch v3 >= v1 on single runs: `--reps 3` on A and B for orch (one simulation at a time, shared with the teammate).
3. **Decision point Sunday 11:00 UTC (14:00 TR)**: ship the mode that passes more cases 3 of 3; record it in JOURNAL.
4. `--style pieces|corrects|talkative|asks_back|in_words` once each on the chosen mode.
5. Rehearsal from a fresh clone per `SUNDAY_RUNBOOK.md` (time it), then ask Yaşar to push.
6. 17:00 UTC: hidden briefs, follow the runbook. Never run `run_cases.py` on a hidden brief; bug fixes only, nothing
   from a hidden brief into `builder/`.

## Gotchas in this environment
- Python source written through a bash heredoc loses escapes (`\b` became a backspace, `\n` a newline): write code
  with the file tools, then check regexes with a positive and a negative example.
- `cmd1 && cmd2 && (...) &` backgrounds the whole chain; use the tool's background option instead.
