"""Compare an extracted SPEC with a hand-written reference, field by field. Values that change behaviour are
reported first (dates, numbers, outcomes, enums, flags); wording differences after.

    python dev/compare_specs.py dev/specs/brief-a.json out/dev-extract-a.spec.json
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORDING = ("first_sentence", "confirm_question", "say", "ask", "explanation", "instructions", "trigger", "not_this", "first_response",
           "statement_intro", "statement_per_product", "meaning", "answer", "text", "when", "question", "retry_say", "failure_say",
           "after_success_say", "after_record_change_say", "farewell", "flat_refusal_definition", "conversion", "answer_format",
           "self_description", "source", "examples", "forbidden_offers", "forbidden_questions", "confirmations", "non_confirmations", "sources")


def keyed(lst):
    """Lists of objects with a natural key are compared by key, not by position."""
    if lst and all(isinstance(x, dict) for x in lst):
        for k in ("id", "name", "field", "type", "outcome", "value", "attempt", "rule"):
            if all(k in x for x in lst):
                return {str(x[k]): x for x in lst}
    return None


def diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a: out.append(("extra", f"{path}.{k}", None, b[k]))
            elif k not in b: out.append(("missing", f"{path}.{k}", a[k], None))
            else: diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        ka, kb = keyed(a), keyed(b)
        if ka is not None and kb is not None:
            diff(ka, kb, path, out)
        elif sorted(map(json.dumps, a)) != sorted(map(json.dumps, b)):
            out.append(("differs", path, a, b))
    elif a != b:
        out.append(("differs", path, a, b))


def main(ref, got):
    a, b = (json.load(open(p, encoding="utf-8")) for p in (ref, got))
    out = []
    diff(a, b, "", out)
    out = [x for x in out if not x[1].startswith((".rule_map", ".free_rules", ".meta.sources"))]
    words = [x for x in out if x[1].split(".")[-1] in WORDING]
    logic = [x for x in out if x not in words]
    print(f"{len(logic)} behaviour difference(s), {len(words)} wording difference(s)  (rule_map and free_rules not compared)\n")
    for kind, path, x, y in logic:
        print(f"[{kind}] {path}\n    reference: {json.dumps(x, ensure_ascii=False)[:220]}\n    extracted: {json.dumps(y, ensure_ascii=False)[:220]}")
    if words:
        print("\n--- wording (check by eye)")
        for kind, path, x, y in words:
            print(f"[{kind}] {path}\n    ref: {json.dumps(x, ensure_ascii=False)[:160]}\n    got: {json.dumps(y, ensure_ascii=False)[:160]}")
    print(f"\nfree_rules: reference {len(a.get('free_rules', []))}, extracted {len(b.get('free_rules', []))}; "
          f"rule_map rows: reference {len(a.get('rule_map', []))}, extracted {len(b.get('rule_map', []))}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
