"""Quick test: 'not today' and related negative temporal expressions."""
import sys, pathlib, json, datetime as dt
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from builder import codegen
from builder.snippets.dates import resolve_spoken_date

A = codegen.date_config(json.loads((KIT / "dev" / "specs" / "brief-a.json").read_text(encoding="utf-8")))
W = dt.date(2026, 10, 14)  # Wednesday

cases = [
    # (input, expected_status, expected_date)
    ("not today, Friday",              "exact",  "2026-10-16"),
    ("I can't pay right now, maybe on Friday", "exact",  "2026-10-16"),
    ("not now",                        "none",   ""),
    ("not today but I can on Friday",  "exact",  "2026-10-16"),
    ("Not today, but the 20th",        "exact",  "2026-10-20"),
    ("not today",                      "none",   ""),
    # These should STILL resolve to today:
    ("today",                          "exact",  "2026-10-14"),
    ("right now",                      "exact",  "2026-10-14"),
    ("Can I pay today?",               "exact",  "2026-10-14"),
    # Edge: "next week Tuesday"
    ("next week Tuesday",              "exact",  "2026-10-20"),
    ("next Tuesday",                   "exact",  "2026-10-20"),
    # Edge: "end of October"
    ("end of October",                 "vague",  ""),
    ("end of the month",               "vague",  ""),
    # Amount as "twelve fifty" should NOT be a date
    ("twelve fifty",                   "none",   ""),
]

fails = 0
for said, want_status, want_date in cases:
    r = resolve_spoken_date(said, W, A)
    ok = r["status"] == want_status and r["date"] == want_date
    if not ok:
        fails += 1
    print(f"{'PASS' if ok else 'FAIL'} {said!r:50s} -> status={r['status']!r:8s} date={r['date']!r:12s}" +
          (f"   (want {want_status}/{want_date})" if not ok else ""))

print(f"\n{'all good' if not fails else f'{fails} failure(s)'}")
sys.exit(1 if fails else 0)
