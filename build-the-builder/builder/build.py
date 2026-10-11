"""The builder: brief files + tool API file -> a phone agent on Freya. One command, no manual step.

    python builder/build.py <brief files...> <tool_api.json> --slot yasar-brief-a [--spec dev/specs/x.json] [--mode v1|orch] [--no-save]

Stages (dev/ARCHITECTURE.md): ingest -> SPEC -> validate -> generate -> lint + local snippet runs -> dry run ->
save (publishes) -> export -> trace.
Practice cases are never run here: they belong to Brief A/B only (see the self-test trap in DEV_AGENT_PROMPT.md).

A hidden brief gets one run, so a run must end with an agent whatever happens on the way. Each stage has a way down:
- a brief file in another encoding or format is read as well as it can be; the tool API is recognised by what it is;
- a SPEC with problems is repaired by rule (builder/robust.py), never refused;
- the workflow is generated in the asked mode, else in the other mode; a candidate the local checks or the platform's
  dry run reject gives way to the next one;
- with no SPEC at all (no model answer in time), or when nothing generated from it can be saved, the last resort
  is an agent that reads the documents itself (builder/minimal.py);
- the first agent that passes is saved at once (a checkpoint); the Auditor's corrections come after it and replace
  it only when the corrected agent passes the same checks;
- every model call has a time limit and the whole run a budget (BUILD_BUDGET_S, default 1500 s of the 30 minutes).
The trace says which way was taken.
"""
import argparse, json, os, pathlib, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from builder import generate, ingest, llm, minimal, robust, sentences, verify
from builder.spec_schema import validate
from builder.trace import Trace

BUDGET = float(os.environ.get("BUILD_BUDGET_S", "1500"))
MODES = ("v1", "orch")


def pick_inputs(files):
    """(brief files, tool API file): the API is the file that reads as an API description (the last one, if several),
    whatever its name; every other file is a brief document."""
    apis = [f for f in files if ingest.looks_like_api(f)]
    api = apis[-1] if apis else next((f for f in reversed(files) if str(f).lower().endswith((".json", ".yaml", ".yml"))), None)
    return [f for f in files if f != api], api


def check(wf, spec, tools, t, label):
    """Every local check on one candidate. A check that itself fails counts as a problem, it does not end the run."""
    problems = []
    for name, run in (("lint", lambda: verify.lint(wf, spec, tools)), ("snippet", lambda: verify.run_snippets(wf, spec))):
        try:
            found = run()
        except Exception as e:
            found = [f"{name} check could not run ({type(e).__name__}: {str(e)[:120]})"]
        for p in found: t.event(name, f"{label}: {p}")
        problems += found
    t.event("selftest", f"{label}: lint and local runs of every code node and hook: {'pass' if not problems else str(len(problems)) + ' problem(s)'}")
    return problems


def spoken_check(wf, spec, t, label):
    """The fixed sentences the agent can say, read against the SPEC (builder/sentences.py). Findings are written to
    the trace; they never stop a save."""
    try:
        found = sentences.audit(wf, spec)
    except Exception as e:
        found = [f"note: the sentence check could not run ({type(e).__name__}: {str(e)[:120]})"]
    for f in found: t.event("sentence", f"{label}: {f}")
    t.event("selftest", f"{label}: fixed sentences against the SPEC: {sum(f.startswith('problem') for f in found)} problem(s), {sum(f.startswith('note') for f in found)} note(s)")
    return found


def candidates(spec, tools, mode, t):
    """Workflows from the SPEC in every mode, the asked one first: (mode, workflow, problems). The other mode is
    built too, so it is at hand when the platform refuses the first; clean candidates come before the others."""
    out = []
    for m in [mode] + [x for x in MODES if x != mode]:
        try:
            wf = generate.build(spec, tools, m)
        except Exception as e:
            t.event("fallback", f"mode {m}: could not be generated ({type(e).__name__}: {str(e)[:160]})")
            continue
        n_tools = sum(len(n.get("tools") or []) for n in wf["nodes"].values()) + len(wf.get("tools") or [])
        t.event("generate", f"mode {m}: {len(wf['nodes'])} nodes, {n_tools} tools")
        out.append((m, wf, check(wf, spec, tools, t, f"mode {m}")))
    return sorted(out, key=lambda c: len(c[2]) > 0)      # stable: clean first, else the asked order


def last_resort(docs, tools, t):
    try:
        wf, shim = minimal.build(docs, tools)
        problems = []
        try:
            problems = verify.lint(wf, shim, tools) + minimal.selftest(wf)
        except Exception as e:
            problems = [f"check could not run ({type(e).__name__})"]
        for p in problems: t.event("lint", f"last resort: {p}")
        t.event("generate", f"last resort (no SPEC: the agent reads the documents itself): {len(wf['nodes'])} nodes, {'pass' if not problems else str(len(problems)) + ' problem(s)'}")
        return [("minimal", wf, problems)]
    except Exception as e:
        t.event("fallback", f"last resort could not be built ({type(e).__name__}: {str(e)[:160]})")
        return []


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="brief files and the tool API file")
    ap.add_argument("--slot", required=True)
    ap.add_argument("--spec", help="use this SPEC file instead of extracting one")
    ap.add_argument("--no-save", action="store_true", help="stop after the local checks")
    ap.add_argument("--mode", choices=list(MODES), default="v1", help="v1: one LLM negotiation node; orch: code decides every offer")
    ap.add_argument("--out", default=str(KIT / "out"))
    a = ap.parse_args(argv)
    briefs, api_path = pick_inputs(a.files)
    if not api_path or not briefs:
        sys.exit("give one or more brief files and the tool API file")
    t0 = time.time()
    t = Trace(KIT / "traces", a.slot)
    status, saved = "error", None
    out = pathlib.Path(a.out)

    def publish(mode, wf, label):
        """Dry run, save (publishes), export. False when the platform refuses this candidate."""
        nonlocal saved
        import freya                                     # only needed from here on (needs FREYA_API_KEY)
        try:
            freya.validate_workflow(a.slot + " dry run", wf)
            t.event("selftest", f"{label}: dry run (validate_workflow): pass")
        except Exception as e:
            t.event("fallback", f"{label}: the dry run refused it ({str(e)[:300]})")
            return False
        try:
            ids = freya.save_workflow(a.slot, wf, state_file=str(KIT / ".freya-agents.json"))
        except Exception as e:
            t.event("fallback", f"{label}: could not be saved ({str(e)[:300]})")
            return False
        t.event("freya", f"saved and published ({label}): workflow_id={ids['workflow_id']} agent_id={ids['agent_id']} version={ids.get('version', 1)}")
        saved = dict(ids, mode=mode)
        (out / f"{a.slot}.workflow.json").write_text(json.dumps(wf, indent=1, ensure_ascii=False), encoding="utf-8")
        for attempt in (1, 2):
            try:
                exp = freya.export_workflow(ids["workflow_id"], str(out / f"{a.slot}.export.json"))
                t.event("freya", f"exported -> {pathlib.Path(exp).relative_to(KIT) if KIT in pathlib.Path(exp).resolve().parents else exp}")
                break
            except Exception as e:
                t.event("warning", f"export attempt {attempt} failed ({str(e)[:200]})")
        return True

    def ship(cands, what):
        """Save the first candidate the platform accepts; with --no-save, name the one that would be tried first."""
        for mode, wf, problems in cands:
            label = f"{what}, mode {mode}" + (f", {len(problems)} local problem(s)" if problems else "")
            if a.no_save:
                (out / f"{a.slot}.workflow.json").write_text(json.dumps(wf, indent=1, ensure_ascii=False), encoding="utf-8")
                t.event("generate", f"not saved (--no-save): would try {label} -> {(out / (a.slot + '.workflow.json')).name}")
                return mode
            if publish(mode, wf, label):
                return mode
        return None

    try:
        out.mkdir(parents=True, exist_ok=True)
        t.event("input", f"briefs={briefs} tool_api={api_path}")
        docs = ingest.read_briefs(briefs)
        for d in docs:
            if d.get("note"): t.event("warning", f"{d['path']}: {d['note']}")
        try:
            tools = ingest.parse_openapi(api_path)["tools"]
        except Exception as e:
            t.event("fallback", f"the tool API file could not be read ({type(e).__name__}: {str(e)[:160]})")
            tools = {}
        t.event("ingest", f"{len(docs)} brief file(s), {sum(len(d['text']) for d in docs)} chars; tools: {', '.join(sorted(tools)) or 'none'}")

        # ---- the SPEC
        spec, binding, rep = None, None, {"repairs": 0, "audit_issues": [], "audit_applied": False, "coerced": False, "notes": [], "errors": []}
        if a.spec:
            try:
                spec = json.loads(pathlib.Path(a.spec).read_text(encoding="utf-8"))
                t.event("spec", f"from file {a.spec} (no model call)")
            except Exception as e:
                t.event("fallback", f"the SPEC file could not be read ({type(e).__name__}: {str(e)[:160]})")
        elif tools:
            from builder import extract
            llm.set_deadline(t0 + BUDGET * 0.6)
            try:
                spec, binding, rep = llm.run(extract.draft(docs, tools, t))
                t.event("spec", f"extracted: {rep['repairs']} repair round(s) with the Reader" + (f", repaired by rule ({len(rep['notes'])} value(s) dropped or replaced)" if rep["coerced"] else ""))
            except Exception as e:
                t.event("fallback", f"no SPEC from the Reader ({type(e).__name__}: {str(e)[:200]})")
        if spec is not None and tools:
            errs = validate(spec, tools)
            if errs:                                     # a SPEC file with problems, or errors about the tool API itself
                for e in errs[:30]: t.event("spec-error", e)
                spec, notes, left = robust.coerce(spec, tools)
                rep.update(coerced=True, notes=rep["notes"] + notes, errors=left)
                t.event("spec", f"repaired by rule: {len(notes)} value(s) dropped or replaced, {len(left)} problem(s) that only the tool API could solve")
                for n in notes[:20]: t.event("spec-note", n)
            (out / f"{a.slot}.spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
            try:
                t.event("spec", f"valid: bank={spec['meta']['bank_name']!r}, identity questions={len(spec['identity']['questions'])}, "
                                f"bands={len(spec['bands'])}, situations={len(spec['situations'])}, outcomes={len(spec['outcomes']['table'])}, "
                                f"max products={spec['account']['max_products']}, notes={'on' if spec['notes']['enabled'] else 'off'}, "
                                f"holidays={len(spec['calendar']['holidays'])}")
                mp = spec["multi_product"]
                if mp["enabled"] and not mp["attempts_per_product"] and not spec["negotiation"].get("call_attempt_limit"):
                    t.event("warning", "the brief counts persuasion attempts for the whole call but gives no number: "
                                       "each product's own band limit caps the call's total")
            except Exception as e:
                t.event("warning", f"SPEC summary not available ({type(e).__name__})")

        # ---- the agent: a checkpoint from the first SPEC, then the Auditor's corrections
        cands = candidates(spec, tools, a.mode, t) if spec is not None and tools else []
        if cands:
            spoken_check(cands[0][1], spec, t, f"mode {cands[0][0]}")
        shipped = ship(cands, "SPEC as drafted" if not a.spec else "SPEC from file") if cands else None
        if shipped and shipped != a.mode:
            t.event("fallback", f"mode {a.mode} was asked, mode {shipped} is used")
        if binding is not None and spec is not None:
            left = BUDGET * 0.55 - (time.time() - t0)
            if left < 60:
                t.event("warning", "no time left for the Auditor: the agent of the drafted SPEC stays")
            else:
                from builder import extract
                llm.set_deadline(t0 + BUDGET * 0.85)
                try:
                    spec2, rep2 = llm.run(extract.audit(spec, binding, docs, tools, t))
                except Exception as e:
                    t.event("warning", f"the audit failed ({type(e).__name__}: {str(e)[:160]}); the agent of the drafted SPEC stays")
                    spec2, rep2 = spec, {}
                rep.update(rep2)
                for i in rep.get("audit_issues") or []: t.event("audit", f"{str(i.get('rule', ''))[:80]} | {str(i.get('problem', ''))[:120]}")
                t.event("spec", f"audit: {len(rep.get('audit_issues') or [])} finding(s), repair {'applied' if rep.get('audit_applied') else 'not applied'}")
                if rep.get("audit_applied") and spec2 != spec and not validate(spec2, tools):
                    cands2 = candidates(spec2, tools, a.mode, t)
                    best1 = next((c for c in cands if c[0] == shipped), None)
                    # the corrected agent replaces the checkpoint only if it is at least as sound and not a step down
                    if cands2 and (not shipped or (len(cands2[0][2]) <= len(best1[2]) and (cands2[0][0] == shipped or cands2[0][0] == a.mode))):
                        spoken_check(cands2[0][1], spec2, t, f"mode {cands2[0][0]}")
                        again = ship(cands2[:1], "SPEC after the audit")
                        if again:
                            shipped, spec = again, spec2
                            (out / f"{a.slot}.spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
                    else:
                        t.event("warning", "the SPEC after the audit did not build as well as the drafted one: the checkpoint stays")
        (out / f"{a.slot}.audit.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
        if not shipped:
            shipped = ship(last_resort(docs, tools, t), "no SPEC") if tools else None
        llm.set_deadline(None)

        if a.no_save:
            status = f"ok (not saved, {shipped})" if shipped else "error"
            return 0 if shipped else 1
        if not saved:
            t.event("fallback", "nothing could be saved")
            return 1
        status = "ok" if shipped == a.mode and not rep.get("coerced") else f"ok ({'mode ' + shipped if shipped in MODES else 'last resort'}{', SPEC repaired by rule' if rep.get('coerced') else ''})"
        print(json.dumps({k: v for k, v in saved.items()}))
        return 0
    except Exception as e:                               # whatever was saved before stays saved
        t.event("error", f"{type(e).__name__}: {str(e)[:300]}")
        if saved:
            status = "ok (an agent was saved before a later step failed)"
            print(json.dumps(saved))
            return 0
        return 1
    finally:
        llm.set_deadline(None)
        t.event("time", f"{time.time() - t0:.0f} s of a {BUDGET:.0f} s budget")
        print(f"trace: {t.close(status)}")


if __name__ == "__main__":
    sys.exit(main())
