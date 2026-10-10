"""The builder: brief files + tool API file -> a phone agent on Freya. One command, no manual step.

    python builder/build.py <brief files...> <tool_api.json> --slot yasar-brief-a [--spec dev/specs/x.json] [--no-save]

Stages (dev/ARCHITECTURE.md): ingest -> SPEC -> validate -> generate -> lint + local snippet runs -> dry run ->
save (publishes) -> export -> trace. Until extraction (Phase 4) exists, the SPEC comes from --spec.
Practice cases are never run here: they belong to Brief A/B only (see the self-test trap in DEV_AGENT_PROMPT.md).
"""
import argparse, json, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from builder import generate, verify
from builder.ingest import parse_openapi, read_briefs
from builder.spec_schema import validate
from builder.trace import Trace


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="brief files, then the tool API file (.json) last")
    ap.add_argument("--slot", required=True)
    ap.add_argument("--spec", help="use this SPEC file instead of extracting one")
    ap.add_argument("--no-save", action="store_true", help="stop after the local checks")
    ap.add_argument("--out", default=str(KIT / "out"))
    a = ap.parse_args(argv)
    api_path = next((f for f in reversed(a.files) if f.endswith(".json")), None)
    briefs = [f for f in a.files if f != api_path]
    if not api_path or not briefs:
        sys.exit("give one or more brief files and the tool API .json file")
    t = Trace(KIT / "traces", a.slot)
    status = "error"
    try:
        t.event("input", f"briefs={briefs} tool_api={api_path}")
        docs = read_briefs(briefs)
        tools = parse_openapi(api_path)["tools"]
        t.event("ingest", f"{len(docs)} brief file(s), {sum(len(d['text']) for d in docs)} chars; tools: {', '.join(sorted(tools))}")

        if a.spec:
            spec = json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8"))
            t.event("spec", f"from file {a.spec} (no model call)")
        else:
            raise SystemExit("SPEC extraction is not implemented yet (Phase 4); pass --spec")
        errs = validate(spec, tools)
        if errs:
            for e in errs: t.event("spec-error", e)
            raise SystemExit(f"SPEC invalid: {len(errs)} problem(s)")
        t.event("spec", f"valid: bank={spec['meta']['bank_name']!r}, identity questions={len(spec['identity']['questions'])}, "
                        f"bands={len(spec['bands'])}, situations={len(spec['situations'])}, outcomes={len(spec['outcomes']['table'])}, "
                        f"max products={spec['account']['max_products']}, notes={'on' if spec['notes']['enabled'] else 'off'}, "
                        f"holidays={len(spec['calendar']['holidays'])}")

        wf = generate.build(spec, tools)
        out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
        wf_path = out / f"{a.slot}.workflow.json"
        wf_path.write_text(json.dumps(wf, indent=1, ensure_ascii=False), encoding="utf-8")
        n_tools = sum(len(n.get("tools") or []) for n in wf["nodes"].values()) + len(wf.get("tools") or [])
        t.event("generate", f"{len(wf['nodes'])} nodes, {n_tools} tools -> {wf_path.relative_to(KIT)}")

        problems = verify.lint(wf, spec, tools)
        for p in problems: t.event("lint", p)
        t.event("selftest", f"lint: {'pass' if not problems else str(len(problems)) + ' problem(s)'}")
        runs = verify.run_snippets(wf, spec)
        for p in runs: t.event("snippet", p)
        t.event("selftest", f"code nodes and hooks executed locally on {len(verify._sample_days(spec))} calendar days: {'pass' if not runs else str(len(runs)) + ' problem(s)'}")
        if problems or runs:
            raise SystemExit("self-tests failed; nothing was saved")
        if a.no_save:
            status = "ok (not saved)"; return 0

        import freya                                     # only needed from here on (needs FREYA_API_KEY)
        freya.validate_workflow(a.slot + " dry run", wf)
        t.event("selftest", "dry run (validate_workflow): pass")
        ids = freya.save_workflow(a.slot, wf, state_file=str(KIT / ".freya-agents.json"))
        t.event("freya", f"saved and published: workflow_id={ids['workflow_id']} agent_id={ids['agent_id']} version={ids.get('version', 1)}")
        exp = freya.export_workflow(ids["workflow_id"], str(out / f"{a.slot}.export.json"))
        t.event("freya", f"exported -> {pathlib.Path(exp).relative_to(KIT)}")
        status = "ok"
        print(json.dumps(ids))
        return 0
    finally:
        print(f"trace: {t.close(status)}")


if __name__ == "__main__":
    sys.exit(main())
