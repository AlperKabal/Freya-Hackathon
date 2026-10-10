"""Mutation tests for builder/spec_schema.py: every broken copy of a good SPEC must be rejected.

    python dev/test_spec_schema.py
"""
import copy, json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from builder.ingest import parse_openapi
from builder.spec_schema import validate

GOOD = [("dev/specs/brief-a.json", "tools/openapi.json"), ("dev/specs/brief-ab.json", "tools/openapi.json"),
        ("dev/specs/imaginary-c.json", "dev/specs/imaginary-c.openapi.json")]


def mutations(spec):
    """(name, change) pairs; each change breaks one rule the validator must catch."""
    def m(fn):
        s = copy.deepcopy(spec); fn(s); return s
    yield "missing key", m(lambda s: s.pop("calendar"))
    yield "unknown key", m(lambda s: s["opening"].__setitem__("surprise", 1))
    yield "null value", m(lambda s: s["closing"].__setitem__("farewell", None))
    yield "wrong type", m(lambda s: s["identity"].__setitem__("max_wrong_total", "3"))
    yield "bad enum", m(lambda s: s["dates"].__setitem__("non_business_day", "maybe"))
    yield "unknown date rule", m(lambda s: s["bands"][0].__setitem__("deadline", {"kind": "next_full_moon"}))
    yield "date rule missing param", m(lambda s: s["bands"][0].__setitem__("deadline", {"kind": "nth_business_day_after_today"}))
    yield "overlapping bands", m(lambda s: s["bands"][-1].__setitem__("days_late_min", s["bands"][0]["days_late_max"]))
    yield "ladder gap", m(lambda s: s["bands"][-1]["ladder"].pop(0))
    yield "outcome not in table", m(lambda s: s["opening"]["unclear"].__setitem__("outcome", "nobody_home"))
    yield "reason not in table", m(lambda s: s["identity"]["on_failed"].__setitem__("reason", "unlucky"))
    yield "bad holiday", m(lambda s: s["calendar"]["holidays"].append("25/12/2026"))
    yield "bad window", m(lambda s: s["third_party"]["callback"].__setitem__("window_start", "10am"))
    yield "unknown placeholder", m(lambda s: s.__setitem__("addressing", "{honorific} {surname_x}"))
    yield "duplicate situation", m(lambda s: s["situations"].append(copy.deepcopy(s["situations"][0])))
    yield "transfer without queue", m(lambda s: s["situations"][0]["effect"]["actions"].append({"type": "transfer"}))
    # cross-checks against the tool API
    yield "identity field not in API", m(lambda s: s["identity"]["questions"][0].__setitem__("field", "mothers_maiden_name"))
    yield "outcome not in API", m(lambda s: (s["outcomes"]["table"].append({"outcome": "maybe_later", "reasons": [], "when": "x"})))
    yield "queue not in API", m(lambda s: next(a for x in s["situations"] for a in x["effect"]["actions"] + sum([[*o["actions"]] for o in ([x["offer"]["on_accept"], x["offer"]["on_decline"]] if x.get("offer") else [])], []) if a["type"] == "transfer").__setitem__("queue", "nowhere"))
    yield "product field not in API", m(lambda s: s["account"]["product_fields"].__setitem__("past_due", "overdue_sum"))
    yield "floor field not in API", m(lambda s: s["account"]["product_types"][0].__setitem__("floor_field", "magic_floor"))
    yield "tool field not in API", m(lambda s: s["tool_fields"]["transfer_to_agent"].__setitem__("queue", "team"))
    yield "result field not in API", m(lambda s: s["identity"]["result_fields"].__setitem__("wrong_left", "tries"))


def main():
    failed = 0
    for spec_path, api_path in GOOD:
        p = KIT / spec_path
        if not p.exists():
            print(f"SKIP {spec_path} (not written yet)"); continue
        spec, tools = json.loads(p.read_text(encoding="utf-8")), parse_openapi(KIT / api_path)["tools"]
        errs = validate(spec, tools)
        print(("PASS" if not errs else "FAIL"), spec_path, "is valid" if not errs else errs[:5])
        failed += bool(errs)
        for name, broken in mutations(spec):
            errs = validate(broken, tools)
            ok = bool(errs)
            failed += not ok
            print(f"  {'PASS' if ok else 'FAIL'} rejects {name}" + (f": {errs[0]}" if ok else " (NOT caught)"))
    print("\nall good" if not failed else f"\n{failed} problem(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
