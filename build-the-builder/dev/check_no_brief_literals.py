"""Fail if builder/ contains a value copied from a known brief or its tool API. Run before every commit.

    python dev/check_no_brief_literals.py                       # briefs/*.md + tools/openapi.json
    python dev/check_no_brief_literals.py --brief X.md --api Y.json

What counts as a brief value, built from the files at run time (nothing is listed by hand):
- every `backticked` identifier in the briefs, every ISO date, every HH:MM time, every quoted sentence;
- the bank's name (the words before "Bank" in the brief title, plus "Bank");
- every request/response field name and enum value in the tool API file.
What is allowed: the seven tool names (fixed by the event) and the SPEC schema's own vocabulary (its keys and enum
values, e.g. the role names), because those describe mechanisms.

Python files: every string constant (docstrings and f-string parts included) and every comment is checked.
Other files under builder/ (prompt templates): the whole text is checked.
Limit: plain integers (band thresholds, day counts) are not checked; review those by hand.
"""
import argparse, ast, io, json, pathlib, re, sys, tokenize
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from builder import spec_schema

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
GENERIC = {"ok", "true", "false", "error", "null", "none", "string", "number", "integer", "boolean", "object", "array", "yes", "no", "hint"}


def schema_vocabulary():
    words = set(spec_schema.TOOL_NAMES) | set(spec_schema.STAGES) | set(spec_schema.CALL_VARIABLE_ROLES) | set(spec_schema.VALUE_TYPES)
    words |= set(spec_schema.ACTION_TYPES) | set(spec_schema.DATE_RULE_KINDS) | set(spec_schema.AMOUNT_RULE_KINDS) | set(spec_schema.ROLL_VALUES)
    for params in list(spec_schema.DATE_RULE_KINDS.values()) + list(spec_schema.AMOUNT_RULE_KINDS.values()): words |= set(params)
    def walk(t):
        if isinstance(t, spec_schema.Opt): walk(t.t)
        elif isinstance(t, spec_schema.Enum): words.update(v for v in t.values if isinstance(v, str))
        elif isinstance(t, list): walk(t[0])
        elif isinstance(t, dict):
            for k, v in t.items():
                words.add(k.t if isinstance(k, spec_schema.Opt) else k); walk(v)
    walk(spec_schema.SCHEMA); walk(spec_schema.EFFECT); walk(spec_schema.ACTION); walk(spec_schema.OUTCOME)
    return words


def brief_values(brief_paths, api_paths):
    tokens, dates, times, sentences, names = set(), set(), set(), set(), set()
    for p in brief_paths:
        text = pathlib.Path(p).read_text(encoding="utf-8")
        for bt in re.findall(r"`([^`]+)`", text): tokens.update(IDENT.findall(bt))
        dates.update(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text))
        times.update(re.findall(r"\b\d{2}:\d{2}\b", text))
        # pair the quotes of each line in order first, then drop short ones (filtering inside the regex shifts the pairs)
        for line in text.splitlines():
            sentences.update(s.strip() for s in re.findall(r"\"([^\"]*)\"", line) if len(s.strip()) >= 12)
        title = text.splitlines()[0] if text else ""
        names.update(m.group(0) for m in re.finditer(r"(?:[A-Z][a-z]+ )+Bank\b", title + " " + text[:2000]))
    for p in api_paths:
        api = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        def walk(node):
            if isinstance(node, dict):
                for k, v in (node.get("properties") or {}).items(): tokens.add(k)
                for e in node.get("enum") or []:
                    if isinstance(e, str): tokens.add(e)
                for v in node.values(): walk(v)
            elif isinstance(node, list):
                for v in node: walk(v)
        walk(api.get("paths", {}))
        names.update(re.findall(r"(?:[A-Z][a-z]+ )+Bank\b", json.dumps(api.get("info", {}))))
    allowed = schema_vocabulary() | GENERIC
    tokens = {t for t in tokens if t not in allowed and len(t) > 2}
    return {"tokens": tokens, "dates": dates, "times": times, "sentences": sentences, "names": names}


def problems_in_text(text, v, mode="template"):
    """mode: "constant" (a Python string), "comment" or "template" (a prompt file).
    An identifier token (with "_" or a digit, e.g. a field name) is flagged anywhere. A plain word (e.g. a queue
    name that is also an English word) is flagged only where it stands as a value: a whole constant, or quoted or
    backticked in a template. In comments plain words are prose."""
    out = []
    low = text.lower()
    for t in v["tokens"]:
        word = rf"(?<![A-Za-z0-9_]){re.escape(t)}(?![A-Za-z0-9_])"
        if re.search(r"[_0-9]", t):
            hit = re.search(word, text)
        elif mode == "constant":
            hit = text.strip() == t
        elif mode == "template":
            hit = re.search(rf"[`'\"]{re.escape(t)}[`'\"]", text)
        else:
            hit = False
        if hit: out.append(f"token {t!r}")
    for d in v["dates"] | v["times"]:
        if d in text: out.append(f"value {d!r}")
    for n in v["names"]:
        if n.lower() in low: out.append(f"name {n!r}")
    for s in v["sentences"]:
        if s.lower() in low: out.append(f"sentence {s[:40]!r}")
    return out


def check_python(path, v):
    src = path.read_text(encoding="utf-8")
    found = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [(node.lineno, p) for p in problems_in_text(node.value, v, "constant")]
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            found += [(tok.start[0], p) for p in problems_in_text(tok.string, v, "comment")]
    return sorted(set(found))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brief", action="append"); ap.add_argument("--api", action="append"); ap.add_argument("--root", default=str(KIT / "builder"))
    a = ap.parse_args()
    briefs = a.brief or sorted(str(p) for p in (KIT / "briefs").glob("*.md"))
    apis = a.api or [str(KIT / "tools" / "openapi.json")]
    v = brief_values(briefs, apis)
    print(f"checking {a.root} against {len(v['tokens'])} tokens, {len(v['dates'])} dates, {len(v['times'])} times, "
          f"{len(v['sentences'])} sentences, names {sorted(v['names'])}")
    bad = 0
    for path in sorted(pathlib.Path(a.root).rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts: continue
        rel = path.relative_to(KIT) if KIT in path.parents else path
        hits = check_python(path, v) if path.suffix == ".py" else [(0, p) for p in problems_in_text(path.read_text(encoding="utf-8", errors="replace"), v)]
        for line, p in hits:
            print(f"  {rel}:{line}: {p}"); bad += 1
    print("clean" if not bad else f"{bad} brief value(s) found in builder/")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
