# Handoff: `fix-agent-logic` on Sunday 11 October 2026, 15:35 UTC (18:35 TR)

For whoever continues: another agent session, on another machine or in the cloud. Read this, then `dev/JOURNAL.md`
from "Mock briefs merged into `fix-agent-logic`" to the end, then `dev/mock_briefs/README.md`. The older
`dev/HANDOFF.md` and `dev/SUNDAY_RUNBOOK.md` still hold for the build and submission steps.

## Rules of this repository

- Talk to Yaşar in Turkish. Code, comments, commit messages and the journal are in English.
- Commits carry no `Co-Authored-By` and no "Generated with" line. Push only when Yaşar says so, to the branch he
  names. Never force-push, never rebase a shared branch, never push to `main`.
- Before every commit: `git diff --cached | grep -iE "fak_[a-z0-9]{8}|sk-ant-"` finds nothing. `env.sh` is never
  committed and never printed.
- Nothing from a brief (ours or a hidden one) goes into `builder/`: `python dev/check_no_brief_literals.py` stays
  clean. Kit files (`freya.py`, `tools/`, `docs/`, `examples/`, `briefs/`) stay unchanged.
- One simulation runs at a time per workspace. Never run the practice customers against a hidden brief's agent.
- Hidden briefs open at 17:00 UTC and close at 20:00 UTC today. After they open: bug fixes only.

## Where things stand

`origin/fix-agent-logic` holds everything. Every check passes:

    cd build-the-builder
    for t in check_no_brief_literals test_spec_schema test_dates test_not_today test_negotiation test_situation_guard \
             test_answers test_robust test_calendar_days test_properties test_scenarios test_mutations test_tuning \
             test_generalize test_language test_generate walk_practice test_mock_briefs; do
      PYTHONUTF8=1 python3 dev/$t.py > /tmp/t.out 2>&1; echo "$t exit $? | $(tail -1 /tmp/t.out)"; done

`test_mock_briefs` ends with "tier 1: 0, tier 2: 4, tier 3: 5" and exit code 0; the others say "all good" or "clean".
The whole list takes about five minutes.

On the platform, with agents built from the reference SPECs (mode orch) at `609c66d`, three runs each
(16:04-16:15 UTC): **Brief A 10/10 in every run, Brief B 3/3 in every run** (each customer 3 of 3), and the
"already paid" and dispute scenarios pass with the judge. PUB-06 was 1 of 4 before the lowest amount was named.

## Confirmed on the platform after the outage (16:00 UTC, agent built from `609c66d`)

The platform's model stopped answering from about 15:14 to 15:50 UTC (a bug on Freya's side, confirmed by them):
every call hung after the customer's first reply and the customer hung up after 60 seconds. Runs from that window
say nothing about the agent. After it:

- Brief B, one run: PUB-11 and PUB-12 pass. PUB-13 failed because the platform played that customer twice against
  one bank session (the first attempt had recorded the card's promise, so the bank refused it the second time:
  "this product already has a promise"); the agent retried, noted `service_error` and said so, as the brief asks.
- RULE-B-dispute-one, RULE-B-both-paid, RULE-B-paid-and-refused: 3/3, with the judge. So the two changes that were
  open are confirmed: the product a situation is about, and the close being known once a promise is recorded.

How to run things (read every failure in its transcript before changing anything):

    source env.sh
    python3 dev/attach_slot.py yasar-exp-date                 # once per clone: update that workflow, do not create one
    PYTHONUTF8=1 python3 builder/build.py briefs/brief-a.md briefs/brief-b.md tools/openapi.json --spec dev/specs/brief-ab.json --slot yasar-exp-date
    python3 dev/run_cases_retry.py <agent_id> --brief B --only PUB-11 --out results/probe.json     # a probe: one customer
    python3 dev/run_cases_retry.py <agent_id> --brief B --reps 3 --out results/b.json
    python3 dev/run_scenarios.py <agent_id> --only RULE-B-dispute-one,RULE-B-both-paid,RULE-B-paid-and-refused --reps 3
    PYTHONUTF8=1 python3 builder/build.py briefs/brief-a.md tools/openapi.json --spec dev/specs/brief-a.json --slot yasar-exp-date
    python3 dev/run_cases_retry.py <agent_id> --brief A --reps 3 --out results/a.json
    python3 dev/show_call.py results/a.json PUB-06 > results/pub06.txt        # one call, turn by turn

`--spec` skips the model. Without it the Reader extracts the SPEC (needs `pip install claude-agent-sdk` and a Claude
login or `ANTHROPIC_API_KEY`; about three model calls). `yasar-exp-date` is the shared slot for experiments; the
slots `yasar-tune-a`, `yasar-tune-ab`, `alper-*` belong to other work and must not be overwritten.

## What the platform taught us today (all in the journal)

- A customer hangs up after about 60 seconds of silence. The end of a call is a chain of small code nodes and hooks,
  and each one is a sandbox run: about 1 to 2 seconds normally, 7 seconds when the platform is slow. With three
  products the chain after "Yes, I confirm" is about 15 runs. Shortening it (one router instead of a gate per
  product, one node that plans all notes, no separate node after each recorded promise) would make every call
  faster; it was not done because it could not be tested on the platform. It is the largest open risk.
- The judge is literal and the simulated customer waits for the brief's own words. Offer a product's lowest amount
  by its name ("the minimum payment of 637.50"), not as a bare number.
- "Analysis never arrived" and a run whose slowest turn is far above 10 seconds are the platform's, not the agent's.

## Open, by value

1. Done: `--reps 3` on A and B (see above). What is left for the practice set is the Reader: these agents were
   built with `--spec`, so a build without it (fresh extraction) should be run once on A and on A+B.
2. Shorten the end-of-call chain (see above), then measure "slowest agent turn" again.
3. The Reader on the mock briefs: `python3 dev/run_mock_briefs.py --extract` (about two minutes of model time per
   pack). It was never run. Packs D and H say one bank's rules in two forms, E and G the other's: the SPEC must come
   out the same from both.
4. Pack F on the platform: build from `dev/mock_briefs/f-freya-sibling/` (see `dev/run_mock_briefs.py`), then
   `python3 dev/run_mock_briefs.py --simulate <agent_id>`.
5. What is still open in `dev/mock_briefs/README.md` (tier 2 and 3).

## For a session without this machine's files

`env.sh`, `.freya-agents.json`, `results/` and `out/` are local and ignored by git. A new environment needs
`FREYA_API_KEY`, `FREYA_API_URL=https://staging-app.freyavoice.ai` and `FREYA_BANK_TEAM_KEY` as environment
variables (set by Yaşar, never pasted into a conversation), and network access to `staging-app.freyavoice.ai` and
`freya-bank-mock.freyavoice.workers.dev`. Without them every offline check above still runs.
