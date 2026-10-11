# NEXT AGENT: final case, handoff of 11 Oct 2026, 21:55 Istanbul. Deadline 23:00 Istanbul (20:00 UTC)

Speak **Turkish** to Yaşar. Code, comments, commits and this file are English. Act at once; every minute counts.

## Hard boundaries (Yaşar's)

- **No submission, no `submission.json`, no e-mail until Yaşar says so** after he has seen the test results.
- Commits carry no AI credit line of any kind. Never force-push, never rebase, never push `main`. Push only on
  Yaşar's word, to `fix-agent-logic`.
- The builder stays independent of the case: nothing from `final-case-input/` goes into `builder/`
  (`python3 dev/check_no_brief_literals.py` stays clean). Never edit the generated workflow by hand: fix the
  builder and rebuild.
- Never print or commit `env.sh` or a key. Before a commit: `git diff --cached | grep -iE "fak_[a-z0-9]{8}|sk-ant-"`
  finds nothing; the same check on `traces/final.log` before it is shared.
- The mock `https://freya-final-mock.yasardelibas33.workers.dev` stays up until the results are out. Do not log
  out of Wrangler, do not redeploy unless the bank's data changes.
- One simulation at a time in the workspace. Our slot is `yasar-exp-date` (agent
  `bd040ef6-d402-4963-aa60-cddbf2788b61`, workflow `4b9a3b74-0db2-4cd9-bb92-fc2a5707b574`). Leave `alper-*` alone.

## What is running right now

A full build was started **detached at 21:53:31** from the code of the commit that carries this file:

    pgrep -f "builder/build.py final-case-input"      # still running?
    tail -3 traces/final.log                           # its trace, written as it goes
    cat traces/final.exit                              # "exit 0" once it has ended

It takes 12 to 13 minutes (contract about 40 s, script about 300 s, prepare() about 330 s, then publish and
export), so it ends at about **22:06**. Do not start a second build while it runs: both would write the same files
and publish to the same slot. Do not change anything under `builder/` before it has ended, or the commit no longer
is the code that was run. If it died without an `[end] ... status=ok` line, start it again (command below).

## What this session added (all general, nothing about the case in `builder/`)

1. A new source document from the organisers' Drive (added there at 20:54):
   `final-case-input/sources/meetings/2026-10-10-follow-up-session-transcript.txt`. It is the newest document and
   decides four things: currencies always by full name (`İngiliz Sterlini`, never `Sterlin`); with several cards
   the other-card question comes before the offer (never with one card; after a no-debt reading no offer at
   all); a new card with no statement gets one fixed sentence plus the first statement date and no other date;
   on the statement cut day the 00.00 sentence comes first, then the **total** debt.
2. `builder/casework.py`, **prepared speech**: a third model call (`read_speech`) has the Reader write
   `prepare(service, answer, today, status)`. It runs in every tool's post-hook and puts `prepared.say` (the
   script's sentences, finished: right branch, amounts as Turkish words, dates compared with `now`) and
   `prepared.facts` (decisions, what may come next) into the tool result. The dialogue model reads them out
   instead of working them out. The code is checked before anything runs it (`parse_code`: imports, names, one
   function) and run at build time on every example answer of the pack with every date the answer names
   (`run_speech`; the trace line starts with `prepare():`). `BUILDER_PREPARED_SPEECH=0` switches the step off; a
   failed step is a `warning` in the trace and the agent then composes its sentences itself, as version 20 did.
3. `builder/casework.py`, **fields the workflow knows**: a request field named like a call variable
   (`customerNo` and `customerNumber`) and a field with exactly one allowed value (`aiFlow`) are no longer tool
   parameters. The pre-hook writes them into the body (`BIND`). Confirmed on the platform.
4. An ending's closing words are taken off the end of every prepared sentence and the prompt says not to speak
   them, so the ending step says them once. **Not tested on the platform yet.**
5. `builder/llm.py`: `ask_json(..., parse=...)` for a reply that is code. `builder/build.py`: the new step.
6. `dev/final_case_tests/`: `simulate_followup.py` (six customers for the new decisions and for the days that
   depend on `now`; `--set more` runs eight more; every call is printed turn by turn with its tool calls),
   `check_speech.py` (what prepare() says for every test answer), `drive_refresh.py` (Drive against the pack).

## What the tests showed (read transcripts, not only verdicts)

| Version | What it was | Examples (6) | Follow-up (6) | Edges (5) | More (8) |
|---|---|---|---|---|---|
| 20 | full build 21:11, sentences composed by the model | 5 | 4 | not run | not run |
| 21 | version 20's script + prepared speech + filled fields (a `--design` test build) | 6 | 5 | 5 | 6 |

- Version 20's failures were real: the wrong Turkish-lira branch on the partial-payment customer of Example 1, and
  the cut day not noticed. Prepared speech fixed both.
- Version 21, follow-up: the one "fail" is my criterion, not the agent ("... lira ... kuruş" is the bank's own way
  to say an amount with kuruş). The same holds for "more" case 4: the bank prescribes repeating the last four
  digits in «Son dört hanesi ... olan birden fazla kartınız var».
- **Version 21, "more" case 5 (the caller speaks English) is a real defect**: the agent answered
  «Sizi ana menüye aktarıyorum.» eighty times and never called the ending tool. Change 4 above is meant to cure
  it (the words can then only be said by calling the tool). **Test this first on the new build**:
  `python3 dev/final_case_tests/simulate_followup.py --set more --only 5`.
- Seen once: `statement.pdf.send` failed in its pre-hook with "Sandbox did not return a parseable result
  (returncode=0)" (customer 94896459), and the agent said the service-error sentence. The same customer run
  again: sent, 200 DONE. Cause unknown; it looks like the platform. If it shows again, read the call's
  `function_call_error` events.
- A closing sentence said twice in a row («Sizi ana menüye yönlendiriyorum.» by the model and again by the ending
  step) was common in version 21. Change 4 should remove it; check.
- Mock against the pack at 21:14: 617 of 617 exact. Drive against the pack at 21:41: 19 files, all identical.

## Next steps, in order

1. Wait for the build. Then: `cat traces/final.exit` is `exit 0`; the trace ends with `status=ok`; its
   `prepare():` line says `0 failed`; no `warning` line. A warning "no prepared speech" means the code step failed:
   run the build once more.
2. `PYTHONUTF8=1 python3 dev/final_case_tests/check_speech.py --today 2026-10-12 --quiet` ends with
   "0 with a flagged sentence". Look at two or three readings, for example
   `--customer 95004361 --service cards.balance --facts` and `--today 2026-11-05` for the cut day.
3. Simulations, one after the other (each two to four minutes):

       python3 dev/final_case_tests/simulate_followup.py --set more --only 5      # the English loop, first
       python3 dev/final_case_tests/simulate_final.py                             # the pack's six examples
       python3 dev/final_case_tests/simulate_followup.py                          # new decisions and special days
       python3 dev/final_case_tests/simulate_followup.py --set more
       python3 dev/final_case_tests/simulate_edges.py                             # then: audit_sim.py <simulation id>

4. A defect that is the agent's: fix it generally in `builder/casework.py` (the prompt blocks in `assemble()`,
   or the Reader's instructions), then a full build again and the affected simulations again. After about 22:15
   only one more build fits before the deadline. A new build asks the Reader again, so its script and its
   prepare() differ a little every time: test again after every build.
5. Compare the Drive once more before the last build is chosen:
   `python3 -I dev/final_case_tests/drive_refresh.py 1r9KOek3SXiE0mu1wBofezD0bjiAJhcYQ <new empty directory> final-case-input`.
   A NEW or CHANGED file: look at it, copy it into `final-case-input/`, rebuild. Changed customer data also means
   updating `final-mock/src/data.json`, `npx wrangler deploy` in `final-mock/`, and `check_mock.py` again.
6. Tell Yaşar in Turkish what passes, what fails and what is open. **Stop there until he approves.**
7. On his approval, the submission (shape in `final-case-input/BRIEF.md`):
   - `mkdir -p submission && cp out/yasar-exp-date.export.json submission/final.workflow.json` (the export of the
     last successful full build, never edited);
   - `traces/final.log` is the trace of that same build (`traces/` is ignored by git: `git add -f traces/final.log`);
   - `submission.json` with team `AYYA`, the two members (ask Yaşar for the exact names; mails
     `yasar.delibas@outlook.com`, `alperkabal14@gmail.com`), the repo URL, `commit` = the commit the build ran
     from, `run_command` = `cd build-the-builder && python3 builder/build.py {case_folder} https://freya-final-mock.yasardelibas33.workers.dev --slot yasar-exp-date`,
     `workflow`, `trace` (paths from the repo root) and `mock_url`;
   - commit, push, and Yaşar e-mails the three files to the address in BRIEF.md before 23:00 Istanbul.

## Commands

    cd /Users/yasardelibas/Desktop/Freya/Freya-Hackathon/build-the-builder
    source env.sh; export SSL_CERT_FILE=/etc/ssl/cert.pem PYTHONUTF8=1
    # the full build (never with --design for the final):
    python3 builder/build.py final-case-input https://freya-final-mock.yasardelibas33.workers.dev --slot yasar-exp-date > traces/final.log 2>&1; echo "exit $?" > traces/final.exit
    # a fast test build from the last script and the last prepare() (no model call, about 40 s; not a final):
    python3 builder/build.py final-case-input https://freya-final-mock.yasardelibas33.workers.dev --design out/yasar-exp-date.design.json --slot yasar-exp-date
    python3 dev/final_case_tests/check_mock.py https://freya-final-mock.yasardelibas33.workers.dev
    python3 dev/check_no_brief_literals.py; python3 -m py_compile builder/build.py builder/casework.py builder/llm.py builder/ingest.py

On this Mac two shell commands sent at the same time share one working directory: give absolute paths. The
builder's model calls use the Claude login of this machine (`claude-agent-sdk` is installed).

---

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
