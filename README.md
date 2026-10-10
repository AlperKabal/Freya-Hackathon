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

```bash
python builder/build.py briefs/brief-a.md tools/openapi.json --slot yasar-a --mode v1
python builder/build.py briefs/brief-a.md briefs/brief-b.md tools/openapi.json --slot yasar-ab --mode v1
```

The tool API must be the final JSON input. `--mode orch` selects the experimental
code-orchestrated negotiation. `--spec <file>` reuses a previously extracted SPEC;
`--no-save` runs generation and local checks without publishing.

Outputs are written to `out/` and `traces/`, both ignored by Git. Reuse slot names
to update workflows in place. v1 is the verified fallback: A 10/10 and B 2/3 under
the three-of-three rule. Orch is not yet qualified; see `dev/JOURNAL.md`.

## Checks

```bash
python dev/test_spec_schema.py
python dev/test_dates.py
python dev/test_not_today.py
python dev/test_negotiation.py
python dev/test_situation_guard.py
python dev/check_no_brief_literals.py
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
