"""The mock briefs (dev/mock_briefs/): what the generated agent does with rules it has not seen, checked without
the platform and without a model.

    python dev/test_mock_briefs.py                    # everything, about three minutes
    python dev/test_mock_briefs.py packs              # one or more sections: packs universal variants odd random answers forms
    python dev/test_mock_briefs.py packs d e          # some packs (by letter)
    python dev/test_mock_briefs.py --only D-65 -v     # one customer, with everything the agent said and the ledger
    python dev/test_mock_briefs.py variants --only no_callback

Sections
  packs      every customer of packs D, E and F, played through the agent built from the pack's oracle SPEC
  universal  customers made from a SPEC alone (universal.py), on eight calendar days, for the kit's reference SPECs
             (Brief A, A+B, imaginary C) and the three packs
  variants   one rule changed at a time (variants.py), each met by the universal customers
  odd        accounts a tool API may return and a brief does not describe (unknown product type, no band, ...)
  random     unscripted customers; only what must hold in every call is checked
  answers    security answers as customers say them, by answer type
  forms      the same documents and tool API in other file forms

A FAIL is a difference between what the brief's text requires and what the generated agent does. Tier 1 is a rule
of the kind the final briefs announce (other numbers, names, calendars, identity questions, outcome tables); tier 2
is a plausible rule the kit's briefs do not have; tier 3 is exotic. Exit code 1 when anything of tier 1 fails.
"""
import collections, copy, json, pathlib, random, re, sys, tempfile, time, traceback, zipfile, zlib
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev" / "mock_briefs"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import lib, make, universal, variants
from builder import codegen, generate, ingest, verify
from builder.spec_schema import validate

FAILED = {1: 0, 2: 0, 3: 0}
SECTIONS = ("packs", "universal", "variants", "odd", "random", "answers", "forms")
DAYS = ["2026-10-14", "2026-10-16", "2026-10-17", "2026-10-31", "2026-11-10", "2026-12-23", "2026-12-24", "2026-12-31"]


def report(ok, label, detail="", tier=1):
    FAILED[tier] += not ok
    print(("PASS " if ok else f"FAIL [tier {tier}] ") + label + (f": {detail}" if detail and not ok else ""))


def mask(text):
    return re.sub(r"\d{4}-\d{2}-\d{2}|(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day \d+ \w+ \d{4}", "DATE", text)


def run(box, c, mode):
    try:
        sim = lib.play(box.sim(c, mode), c)
        return sim, lib.judge(box, c, sim)
    except Exception:
        return None, ["the walk raised: " + traceback.format_exc()[-700:]]


def builds(box, tier=1, days=None):
    """The SPEC fits the schema and its tool API; both modes build, lint clean and run on the sample days."""
    errs = validate(box.spec, box.tools)
    if errs:
        report(False, f"{box.name}: the SPEC fits the schema and the tool API", "; ".join(errs[:3]), tier)
        return False
    ok = True
    for mode in ("v1", "orch"):
        try:
            wf = generate.build(box.spec, box.tools, mode)
            bad = verify.lint(wf, box.spec, box.tools) + verify.run_snippets(wf, box.spec, days=days)
            words = [w for w in box.spec["opening"]["forbidden_before_identity"] if w.lower() in (wf["nodes"]["opening"]["on_enter"].get("text") or "").lower()]
            bad += [f"the opening line says a word forbidden before identity: {w}" for w in words]
        except Exception:
            bad = ["the build raised: " + traceback.format_exc()[-500:]]
        if bad:
            ok = False
            report(False, f"{box.name}, mode {mode}: builds, lints and its code runs", "; ".join(mask(b)[:200] for b in bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""), tier)
    return ok


def collect(box, days, clock=None):
    """The universal customers on these days: distinct problems (dates masked) -> the days they showed on."""
    seen, runs = collections.OrderedDict(), 0
    for d in days:
        try:
            cases = universal.cases(box, d, tag=d[5:] + "-", **({"clock": clock} if clock else {}))
        except Exception:
            seen.setdefault("universal.cases raised: " + traceback.format_exc()[-300:], []).append(d)
            continue
        for c in cases:
            for mode in c["modes"]:
                runs += 1
                sim, problems = run(box, c, mode)
                for p in problems:
                    seen.setdefault(f"{c['id'].split('-', 3)[3]} [{mode}] | {mask(p)[:300]}", []).append(d)
    return seen, runs


# ---------------------------------------------------------------- sections

def packs_section(names, only, verbose):
    stale = make.main(["--check"])
    report(not stale, "the generated pack files are what dev/mock_briefs/make.py writes")
    for P in lib.packs(names or None):
        print(f"\n== {P.title}")
        builds(P)
        cases, runs, bad = P.cases(), 0, 0
        for c in cases:
            if only and c["id"] not in only:
                continue
            for mode in c["modes"]:
                runs += 1
                sim, problems = run(P, c, mode)
                if problems:
                    bad += 1
                    report(False, f"[{mode}] {c['id']}: {c['title']}", tier=c["tier"])
                    for p in problems:
                        print("       - " + p[:500])
                    if c.get("note"):
                        print("       note: " + c["note"])
                if verbose and sim:
                    print(f"     {c['id']} [{mode}] said:")
                    for node, text in sim.said:
                        print(f"        {node}: {text[:400]}")
                    print(f"        ledger: {sim.bank.ledger()}")
        print(f"{runs - bad} of {runs} runs of {len(cases)} customers match the brief")


def references():
    kit = ingest.parse_openapi(KIT / "tools/openapi.json")["tools"]
    load = lambda p: json.loads((KIT / p).read_text(encoding="utf-8"))
    return [lib.Box("brief-a (dev/specs)", load("dev/specs/brief-a.json"), kit), lib.Box("brief-ab (dev/specs)", load("dev/specs/brief-ab.json"), kit),
            lib.Box("imaginary-c (dev/specs)", load("dev/specs/imaginary-c.json"), ingest.parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"])]


def by_tier(box, seen, tier):
    """Problems that show only on days that are no business day of that bank are tier 3: whether a call is made on
    such a day at all is not known. (problem, days) lists per tier."""
    out = collections.OrderedDict()
    for k, days in seen.items():
        off = all(d != "-" and not box.cal.biz(lib.day(d)) for d in days)
        out.setdefault(3 if off else tier, []).append((k + ("   (only on days that are no business day)" if off else ""), days))
    return out


def universal_section(names):
    print("\n== customers made from the SPEC alone, on eight calendar days")
    for box in references() + lib.packs(names or None):
        seen, runs = collect(box, DAYS)
        if not seen:
            report(True, f"{box.name}: {runs} runs")
        for tier, rows in by_tier(box, seen, 1).items():
            report(False, f"{box.name}: {len(rows)} distinct problem(s) in {runs} runs", tier=tier)
            for k, days in rows:
                print(f"       - [{len(days)} day(s), first {days[0]}] {k}")


def variants_section(only):
    print("\n== one rule changed at a time (the problems the unchanged pack has too are not repeated)")
    base, ok = {}, 0
    vs = variants.variants(only)
    for v in vs:
        box = v["box"]
        if v["base"] not in base:
            base[v["base"]] = set(collect(next(p for p in lib.packs() if p.name == v["base"]), v["days"])[0])
        if not builds(box, v["tier"], v["days"][:3]):
            print(f"       rule: {v['rule']}")
            continue
        seen, runs = collect(box, v["days"], v["now"])
        new = collections.OrderedDict((k, d) for k, d in seen.items() if k not in base[v["base"]])
        ok += not new
        for n, (tier, rows) in enumerate(by_tier(box, new, v["tier"]).items()):
            report(False, f"{box.name}: {len(rows)} distinct problem(s) in {runs} runs", tier=tier)
            if n == 0:
                print(f"       rule: {v['rule']}" + (f"  ({v['note']})" if v["note"] else ""))
            for k, days in rows[:5]:
                print(f"       - [{len(days)} day(s), first {days[0]}] {k}")
            if len(rows) > 5:
                print(f"       - ... and {len(rows) - 5} more")
    print(f"{ok} of {len(vs)} variants: every universal customer ends as the changed rule requires")


def odd_section(names):
    """Accounts the brief does not describe. There is no single right ending: the call must end, close with a
    pair from the brief's table, and never record what the brief forbids."""
    print("\n== accounts a brief does not describe")
    for P in lib.packs(names or None):
        spec = P.spec
        pf, t = spec["account"]["product_fields"], spec["account"]["product_types"][0]
        good = universal.products_for(spec, 1)[0]
        lows, highs = min(b["days_late_min"] for b in spec["bands"]), max(b["days_late_max"] for b in spec["bands"])
        odd = {"a product type the brief does not name": dict(good, **{pf["type"]: "mortgage_arrears"}),
               "fewer days late than any band": dict(good, **{pf["days_late"]: lows - 1}),
               "more days late than any band": dict(good, **{pf["days_late"]: highs + 1}),
               "a minimum above the overdue amount": dict(good, **{t["floor_field"]: float(good[pf["past_due"]]) + 50}) if t["floor_field"] != pf["past_due"] else None,
               "no minimum field at all": {k: v for k, v in good.items() if k != t["floor_field"] or k == pf["past_due"]},
               "amounts sent as text": dict(good, **{pf["past_due"]: "%.2f" % float(good[pf["past_due"]]), pf["days_late"]: str(good[pf["days_late"]])}),
               "an overdue amount of zero": dict(good, **{pf["past_due"]: 0.0}),
               "one cent overdue": dict(good, **{pf["past_due"]: 0.01, t["floor_field"]: 0.01}),
               "a very large amount": dict(good, **{pf["past_due"]: 1234567.89})}
        ident = universal.identity_for(spec)
        variables = {v["name"]: "Avery" for v in spec["call_variables"] if v["role"] not in ("customer_id", "now")}
        V = [("who", "confirmed")] + [("id", q["field"], ident[q["field"]], ident[q["field"]]) for q in spec["identity"]["questions"]]
        bad = collections.OrderedDict()
        for label, product in odd.items():
            if product is None:
                continue
            for who, cust in (("pays", lib.Customer("accept")), ("refuses", lib.Customer("refuse", then=["refuse"])),
                              ("names a day", lib.Customer({"kind": "propose", "day": "tomorrow", "amount": "100"}, then=["accept"]))):
                for d in ("2026-11-03", "2026-11-07"):
                    c = lib.case(f"odd-{label}-{who}", label, "Odd", d + "T11:00", V + [("neg", cust)], "", variables=variables, identity=ident, products=[product], free=True)
                    sim, problems = run(P, c, "orch")
                    problems = [p for p in problems if "outside what the brief accepts" not in p or "unknown" in label]
                    for p in problems:
                        bad.setdefault(f"{label}, the customer {who} | {mask(p)[:260]}", []).append(d)
        four = universal.products_for(spec, int(spec["account"]["max_products"]) + 1)
        c = lib.case("odd-more-products", "more products than the brief allows", "Odd", "2026-11-03T11:00", V + [("neg", lib.Customer("accept"))], "", variables=variables,
                     identity=ident, products=four, free=True)
        sim, problems = run(P, c, "orch")
        for p in problems:
            bad.setdefault(f"one product more than the brief allows, the customer pays | {mask(p)[:260]}", []).append("2026-11-03")
        report(not bad, f"{P.name}: nine odd accounts, three customers each, two days", f"{len(bad)} distinct problem(s)", tier=3)
        for k, days in bad.items():
            print(f"       - [{len(days)} run(s)] {k}")


def random_section(names, runs=150):
    """Unscripted customers. No single answer is expected; lib.always must hold in all of them."""
    print("\n== unscripted customers: what must hold in every call")
    words = ["today", "tomorrow", "Friday", "next Friday", "this Saturday", "Sunday", "the 30th", "in three days", "next week", "2026-11-11", "2026-12-25", "the first of December", ""]
    amounts = ["", "", "50", "200", "one hundred and fifty", "999999", "0", "the minimum", "half"]
    for box in references()[1:] + lib.packs(names or None):
        spec = box.spec
        sits = [x["id"] for x in spec["situations"] if "negotiation" in x["stages"]]
        ident = universal.identity_for(spec)
        variables = {v["name"]: "Avery" for v in spec["call_variables"] if v["role"] not in ("customer_id", "now")}
        V = [("who", "confirmed")] + [("id", q["field"], ident[q["field"]], ident[q["field"]]) for q in spec["identity"]["questions"]]
        bad, n = collections.OrderedDict(), 0
        for seed in range(runs):
            rng = random.Random(f"{box.name}|{seed}")

            def answer():
                kind = rng.choice(["accept", "accept", "refuse", "refuse", "too_much", "propose", "propose", "propose", "vague", "question", "unclear"] + sits)
                ev = {"kind": kind, "said": rng.choice(["", "No.", "I want a plan", "call me later", "Put me through to a person", "I paid it", "that is not mine"])}
                if kind == "propose" or rng.random() < 0.2:
                    ev["day"] = rng.choice(words)
                if kind == "propose" and rng.random() < 0.6:
                    ev["amount"] = rng.choice(amounts)
                if rng.random() < 0.3:
                    ev["about"] = rng.choice(["all of them", "both", "the first one", "the loan", "the card", "the last one"])
                if rng.random() < 0.15:
                    ev["question"] = "yes"
                return ev
            # after eight unscripted answers the customer only says no, so every conversation has an end of its own
            cust = lib.Customer(answer(), then=[answer() for _ in range(8)] + ["refuse"], readback=[rng.choice(["accept", "accept", "refuse", answer()]) for _ in range(3)] + ["accept"],
                                offer=rng.choice(["accept", "decline", {"kind": "propose", "day": rng.choice(words), "amount": rng.choice(amounts)}]))
            k = rng.randint(1, max(1, int(spec["account"]["max_products"])))
            d = rng.choice(DAYS + variants.DAYS)
            faults = {"create_promise": rng.choice([0, 0, 0, 1, 2, 99])}
            c = lib.case(f"random-{seed}", "an unscripted customer", "Random", d + "T11:00", V + [("neg", cust)], "", variables=variables, identity=ident,
                         products=universal.products_for(spec, k, rng.randint(0, 5)), faults=faults, free=True)
            n += 1
            sim, problems = run(box, c, "orch")
            if sim is not None and not sim.ended and sim.node.startswith("cb_"):          # a callback the customer asked for: give a time, or none
                problems = [p for p in problems if "did not end" not in p]
            for p in problems:
                bad.setdefault(mask(p)[:260], []).append(f"seed {seed} on {d}")
        if not bad:
            report(True, f"{box.name}: {n} unscripted customers")
        off = lambda where: all(not box.cal.biz(lib.day(w.split(" on ")[1])) for w in where)
        for tier in (2, 3):
            rows = [(k, w) for k, w in bad.items() if (3 if off(w) else 2) == tier]
            if rows:
                report(False, f"{box.name}: {n} unscripted customers", f"{len(rows)} distinct problem(s)" + (" only on days that are no business day" if tier == 3 else ""), tier=tier)
                for k, where in rows[:8]:
                    print(f"       - [{len(where)}x, first: {where[0]}] {k}")


def answers_section():
    """What reaches the bank when a customer says a security answer the way customers do. The model may tidy the
    words before the hook sees them; the hook is the net under it."""
    print("\n== security answers as they are said (builder/snippets/answers.py)")
    ns = {}
    exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("answers"), ns)
    norm, whole = ns["normalize_answer"], ns["whole_answer"]
    POST, DIG8, YEAR = "capital letters without a space", "eight digits, leading zeros included", "four digits (YYYY)"
    rows = [  # tier, type, the description's words, what the customer says, what the bank must get
        (1, "text", POST, "LS6 2AB", "LS62AB"), (1, "text", POST, "ls6 2ab", "LS62AB"), (1, "text", POST, "L S 6 2 A B", "LS62AB"),
        (1, "text", POST, "L S six two A B", "LS62AB"), (1, "text", POST, "L, S, six, two, A, B", "LS62AB"), (2, "text", POST, "LS6, 2AB.", "LS62AB"),
        (2, "text", POST, "LS6-2AB", "LS62AB"), (2, "text", POST, "It's LS6 2AB", "LS62AB"), (2, "text", POST, "L for Lima, S for Sierra, 6, 2, A for Alpha, B for Bravo", "LS62AB"),
        (2, "text", POST, "double L one, two A B", "LL12AB"), (2, "text", "five characters", "three four seven one zero", "34710"),
        (1, "digits", "five digits", "three four seven one zero", "34710"), (1, "digits", "five digits", "34710", "34710"), (1, "digits", "five digits", "34 710", "34710"),
        (1, "digits", DIG8, "zero eight one two three four five six", "08123456"), (1, "digits", DIG8, "oh eight one two three four five six", "08123456"),
        (1, "digits", DIG8, "08 12 34 56", "08123456"), (1, "digits", DIG8, "0812-3456", "08123456"), (1, "digits", DIG8, "nought eight, twelve, thirty-four, fifty-six", "08123456"),
        (2, "digits", DIG8, "double oh, one two three four five six", "00123456"), (2, "digits", DIG8, "It is 08123456.", "08123456"),
        (2, "digits", DIG8, "the number is zero eight one two three four five six", "08123456"), (2, "digits", DIG8, "eight million one hundred and twenty-three thousand four hundred and fifty-six", "08123456"),
        (2, "text", "the two letters and six digits, no spaces, capital letters", "S C one two three four five six", "SC123456"),
        (2, "text", "the two letters and six digits, no spaces, capital letters", "sc 123456", "SC123456"),
        (1, "digits", "four digits", "four four seven one", "4471"), (1, "digits", "four digits", "forty-four seventy-one", "4471"), (1, "digits", "four digits", "double four seven one", "4471"),
        (1, "digits", "four digits", "4471", "4471"), (2, "digits", "four digits", "the last four are 4471", "4471"), (2, "digits", "four digits", "four thousand four hundred and seventy-one", "4471"),
        (1, "year", YEAR, "1984", "1984"), (1, "year", YEAR, "nineteen eighty-four", "1984"), (1, "year", YEAR, "one nine eight four", "1984"),
        (1, "year", YEAR, "two thousand and five", "2005"), (1, "year", YEAR, "twenty oh five", "2005"), (1, "year", YEAR, "two thousand", "2000"),
        (1, "year", YEAR, "twenty ten", "2010"), (2, "year", YEAR, "in eighty-four", "1984"), (2, "year", YEAR, "'84", "1984"), (2, "year", YEAR, "I was born in 1984.", "1984"),
        (2, "year", YEAR, "nineteen hundred and eighty-four", "1984"), (2, "year", YEAR, "two thousand five", "2005"), (2, "year", YEAR, "nineteen ninety", "1990"),
        (1, "date", "YYYY-MM-DD", "14 March 1988", "1988-03-14"), (1, "date", "YYYY-MM-DD", "the fourteenth of March nineteen eighty-eight", "1988-03-14"),
        (1, "date", "YYYY-MM-DD", "March 14th, 1988", "1988-03-14"), (1, "date", "YYYY-MM-DD", "14/03/1988", "1988-03-14"), (1, "date", "YYYY-MM-DD", "14.03.1988", "1988-03-14"),
        (2, "date", "YYYY-MM-DD", "one four, oh three, one nine eight eight", "1988-03-14"), (2, "date", "YYYY-MM-DD", "14 3 88", "1988-03-14"),
        (2, "date", "YYYY-MM-DD", "the 14th of the third, 1988", "1988-03-14"), (2, "date", "YYYY-MM-DD. Month first, then day.", "03/14/1988", "1988-03-14"),
        (2, "number", "a whole number", "one hundred and fifty", "150"), (2, "number", "a whole number", "150", "150"),
        (2, "text", "", "Smith", "Smith"), (2, "text", "small letters", "SMITH", "smith")]
    for tier in (1, 2):
        bad = [f"{kind} ({hint or 'no format'}): {said!r} -> {norm(kind, said, hint)!r}, the bank needs {want!r}" for t, kind, hint, said, want in rows if t == tier and norm(kind, said, hint) != want]
        n = sum(1 for r in rows if r[0] == tier)
        report(not bad, f"{n - len(bad)} of {n} answers reach the bank in the form the brief asks for" + (" (as people commonly say them)" if tier == 1 else " (less common ways)"),
               f"{len(bad)} do not", tier=tier)
        for b in bad:
            print("       - " + b)
    parts = [(2, "text", POST, "LS6", "2AB", "LS62AB"), (1, "digits", DIG8, "0812", "3456", "08123456"), (1, "digits", "four digits", "44", "71", "4471"),
             (1, "year", YEAR, "nineteen", "eighty-four", "1984"), (1, "date", "YYYY-MM-DD", "14 March", "1988", "1988-03-14"), (2, "digits", "five digits", "three four", "seven one zero", "34710")]
    bad = []
    for tier, kind, hint, first, second, want in parts:
        sent, kept = whole(kind, "", first, hint)
        sent2, _ = whole(kind, kept, second, hint)
        if sent2 != want:
            bad.append((tier, f"{kind} ({hint}): {first!r} then {second!r} -> {sent2!r}, the bank needs {want!r}"))
    for tier in (1, 2):
        mine = [b for t, b in bad if t == tier]
        report(not mine, f"an answer given in two turns is sent whole ({'numbers, years and dates' if tier == 1 else 'codes with letters, digits said as words'})", f"{len(mine)} are not", tier=tier)
        for b in mine:
            print("       - " + b)


def _docx(text):
    paras = "".join("<w:p><w:r><w:t xml:space=\"preserve\">" + line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</w:t></w:r></w:p>" for line in text.splitlines())
    return {"[Content_Types].xml": "<Types/>", "word/document.xml": "<?xml version=\"1.0\"?><w:document xmlns:w=\"x\"><w:body>" + paras + "</w:body></w:document>"}


def _xlsx(text, sep):
    import csv
    rows = "".join("<row>" + "".join("<c t=\"inlineStr\"><is><t>" + cell.replace("&", "&amp;").replace("<", "&lt;") + "</t></is></c>" for cell in line) + "</row>"
                   for line in csv.reader(text.splitlines(), delimiter=sep))
    return {"[Content_Types].xml": "<Types/>", "xl/worksheets/sheet1.xml": "<?xml version=\"1.0\"?><worksheet><sheetData>" + rows + "</sheetData></worksheet>"}


def _zip(path, parts):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)


def _pdf(text):
    lines = b"".join(b"BT (" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1", "replace") + b") Tj ET\n" for line in text.splitlines())
    return b"%PDF-1.4\n1 0 obj\n<< /Filter /FlateDecode >>\nstream\n" + zlib.compress(lines) + b"\nendstream\nendobj\n%%EOF\n"


def facts(text):
    """What a reader must still find in a document after it changed its file form: every number, date, time, quoted
    sentence and code-like word."""
    words = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}\b|\b\d+(?:st|nd|rd|th)\b|`[a-z_]+`|\b[a-z]+_[a-z_]+\b", text))
    words |= {q.strip() for q in re.findall(r"\"([^\"\n]{12,120})\"", text)}
    return {w.strip("`") for w in words}


def forms_section(names):
    print("\n== the same documents and tool API in other file forms")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mock-forms-"))
    for P in lib.packs(names or None):
        lost = collections.OrderedDict()
        for doc in P.docs:
            text = doc.read_text(encoding="utf-8")
            want = facts(text)
            forms = {"utf-8 with a byte-order mark": lambda p: p.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8")),
                     "utf-16": lambda p: p.write_bytes(text.encode("utf-16")),
                     "windows-1252 with curly quotes": lambda p: p.write_bytes(text.replace('"', "”").replace("'", "’").encode("cp1252", "replace")),
                     "windows line ends": lambda p: p.write_bytes(text.replace("\n", "\r\n").encode("utf-8")),
                     "a Word file": lambda p: _zip(p.with_suffix(".docx"), _docx(text)),
                     "a PDF": lambda p: p.with_suffix(".pdf").write_bytes(_pdf(text))}
            if doc.suffix == ".csv":
                forms["an Excel sheet"] = lambda p: _zip(p.with_suffix(".xlsx"), _xlsx(text, ";" if text.count(";") > text.count(",") else ","))
            for label, write in forms.items():
                folder = tmp / P.name / label.replace(" ", "_")
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / doc.name
                write(target)
                made = next(folder.glob(doc.stem + ".*"))
                got, note = ingest.read_text(made)
                got = got.replace("”", '"').replace("’", "'")
                missing = sorted(w for w in want if w not in got)
                if missing:
                    lost.setdefault(f"{doc.name} as {label}: {len(missing)} of {len(want)} facts are not in the text that was read ({'; '.join(missing[:4])})", []).append(note)
        report(not lost, f"{P.name}: every number, date, quoted sentence and code survives eight file forms of each document", f"{len(lost)} form(s) lose facts", tier=2)
        for k in lost:
            print("       - " + k)
        # the tool API in other shapes
        api = json.loads(P.api_path.read_text(encoding="utf-8"))
        want_tools = P.tools
        shapes = {}
        swagger = copy.deepcopy(api)                           # Swagger 2: host, basePath, a body parameter, definitions
        if not swagger.get("components", {}).get("schemas"):
            url = swagger.pop("servers")[0]["url"]
            swagger.pop("openapi", None)
            swagger.update(swagger="2.0", host=url.split("//")[1].split("/")[0], basePath="/" + "/".join(url.split("//")[1].split("/")[1:]), schemes=["https"])
            for route, ops in swagger["paths"].items():
                op = ops["post"]
                op["parameters"] = [{"in": "body", "name": "body", "required": True, "schema": op.pop("requestBody")["content"]["application/json"]["schema"]}]
                op["responses"] = {"200": {"description": "ok", "schema": op["responses"]["200"]["content"]["application/json"]["schema"]}}
            shapes["Swagger 2"] = swagger
        renamed = copy.deepcopy(api)                           # other spellings of the seven names, on longer paths
        renamed["paths"] = {"/bank/v9/" + ingest.tool_name(ops["post"].get("operationId"), route).replace("_", "-").title().replace("-", ""): ops for route, ops in api["paths"].items()}
        for ops in renamed["paths"].values():
            ops["post"].pop("operationId", None)
        shapes["CamelCase paths without operation ids"] = renamed
        extra = copy.deepcopy(api)                             # tools the agent does not use, a GET health check, a path-level parameter
        extra["paths"]["/health"] = {"get": {"summary": "Is the service up?", "responses": {"200": {"description": "ok"}}}}
        extra["paths"]["/send_sms"] = {"post": {"summary": "Not for the assistant.", "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"text": {"type": "string"}}}}}},
                                                "responses": {"200": {"description": "ok"}}}}
        shapes["two more operations than the seven tools"] = extra
        nullable = json.loads(json.dumps(api).replace('"type": "string"', '"type": ["string", "null"]'))
        shapes["every string nullable (OpenAPI 3.1)"] = nullable
        bad = []
        for label, doc in shapes.items():
            try:
                tools = ingest.parse_api(doc)["tools"]
            except Exception as e:
                bad.append(f"{label}: parse_api raised {type(e).__name__}: {e}")
                continue
            for name, t in want_tools.items():
                g = tools.get(name)
                if not g:
                    bad.append(f"{label}: tool {name} was not found (found: {sorted(tools)[:9]})")
                elif set(g["request"]) != set(t["request"]) or set(g["required"]) != set(t["required"]) or set(g["response"]) != set(t["response"]):
                    bad.append(f"{label}: {name} has other fields: request {sorted(g['request'])}, required {sorted(g['required'])}, response {sorted(g['response'])}")
                elif any(g["request"][f]["enum"] != t["request"][f]["enum"] for f in t["request"]):
                    bad.append(f"{label}: {name} lost allowed values")
            if not bad and validate(P.spec, {k: v for k, v in tools.items() if k in want_tools}):
                bad.append(f"{label}: the oracle SPEC no longer fits: {validate(P.spec, tools)[:2]}")
        report(not bad, f"{P.name}: the seven tools are read alike from {len(shapes)} other shapes of the API file", "; ".join(bad[:3]), tier=2)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in args
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    words = [a for a in args if not a.startswith("-") and not (only and a == ",".join(only))]
    sections = [w for w in words if w in SECTIONS] or list(SECTIONS)
    names = [w for w in words if w not in SECTIONS]
    t0 = time.time()
    if "packs" in sections:
        packs_section(names, only if only and any(o[:2] in ("D-", "E-", "F-") for o in only) else None, verbose)
    if "universal" in sections and not only:
        universal_section(names)
    if "variants" in sections and not (only and any(o[:2] in ("D-", "E-", "F-") for o in only)):
        variants_section(only)
    if "odd" in sections and not only:
        odd_section(names)
    if "random" in sections and not only:
        random_section(names)
    if "answers" in sections and not only:
        answers_section()
    if "forms" in sections and not only:
        forms_section(names)
    print(f"\nfailing checks: tier 1: {FAILED[1]}, tier 2: {FAILED[2]}, tier 3: {FAILED[3]}   ({time.time() - t0:.0f} s)")
    return 1 if FAILED[1] else 0


if __name__ == "__main__":
    sys.exit(main())
