"""Look at what the builder's prepare() code makes of the pack's example answers.

    python3 dev/final_case_tests/check_speech.py --make                      # one model call: write out/<slot>.speech.py from the last script
    python3 dev/final_case_tests/check_speech.py --today 2026-10-12          # every card of every test customer, as it would be read
    python3 dev/final_case_tests/check_speech.py --today 2026-11-05 --customer 95004361 --service cards.balance --facts

Reads out/<slot>.design.json, out/<slot>.contract.json and out/<slot>.speech.py (written by a build of the case
folder). The checks at the end are general: a sentence must not carry a digit, a currency code or a placeholder.
"""
import argparse, json, pathlib, re, sys

kit = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(kit))
from builder import build, casework, ingest, llm
from builder.trace import Trace

ap = argparse.ArgumentParser()
ap.add_argument("--slot", default="yasar-exp-date")
ap.add_argument("--case", default=str(kit / "final-case-input"))
ap.add_argument("--url", default="https://freya-final-mock.yasardelibas33.workers.dev")
ap.add_argument("--make", action="store_true")
ap.add_argument("--today", default="2026-10-12")
ap.add_argument("--customer")
ap.add_argument("--service")
ap.add_argument("--facts", action="store_true")
ap.add_argument("--quiet", action="store_true")
a = ap.parse_args()

out = kit / "out"
case = pathlib.Path(a.case)
files = [str(x) for x in sorted(case.rglob("*")) if x.is_file() and x.suffix.lower() not in build.SKIP and not any(p.startswith(".") for p in x.parts)]
docs = [d for d in ingest.read_briefs(files) if d["text"].strip()]
tools = casework.contract_tools(json.loads((out / f"{a.slot}.contract.json").read_text(encoding="utf-8")), a.url)
design = casework.clean(json.loads((out / f"{a.slot}.design.json").read_text(encoding="utf-8")))

if a.make:
    t = Trace(kit / "traces", a.slot + "-speech")
    code, report = llm.run(casework.read_speech(design, tools, docs, t))
    (out / f"{a.slot}.speech.py").write_text(code, encoding="utf-8")
    print(report)
    print("trace:", t.close("ok"))

code = casework.parse_code((out / f"{a.slot}.speech.py").read_text(encoding="utf-8"))
ns = {}
exec(code, ns)
prepare = ns["prepare"]

root = json.loads((case / "test-environment" / "test-customers.json").read_text(encoding="utf-8"))
bad = 0
count = 0
for c in root["customers"]:
    if a.customer and str(c["customerNo"]) != a.customer:
        continue
    for service, entry in c["services"].items():
        if a.service and service != a.service:
            continue
        found = []

        def walk(node, key):
            if isinstance(node, dict):
                if isinstance(node.get("response"), dict):
                    found.append((key, node.get("http", 200), node["response"]))
                    return
                for k, v in node.items():
                    walk(v, k)
        walk(entry, "")
        for key, status, body in found:
            got = prepare(service, json.loads(json.dumps(body)), a.today, status)
            count += 1
            say, facts = got.get("say") or {}, got.get("facts") or {}
            flags = []
            for name, text in say.items():
                if re.search(r"\d", re.sub(r"\b\d{1,2} (Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık) \d{4}\b|\b00\.00\b|[\w.+-]+@[\w.-]+", "", text)):
                    flags.append(f"digit in {name}")
                if re.search(r"\b(TL|USD|EUR|GBP|TRY)\b|\[|\]|\bNone\b|\bnan\b", text):
                    flags.append(f"code or placeholder in {name}")
            bad += bool(flags)
            if a.quiet and not flags:
                continue
            print(f"\n### {c['customerNo']} {service} {key} HTTP {status}" + (f"   !!! {flags}" if flags else ""))
            for name, text in say.items():
                print(f"  say.{name}: {text}")
            if a.facts or not say:
                for name, text in facts.items():
                    print(f"  fact.{name}: {text}")
print(f"\n{count} answer(s), {bad} with a flagged sentence")
