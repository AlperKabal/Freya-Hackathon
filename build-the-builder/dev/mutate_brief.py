"""Does the builder READ a brief, or does it know Brief A? Fifteen copies of Brief A, each changed in one place
(a holiday, a band limit, a third band, another outcome name, a six-day week, a deadline in calendar days, a new
situation, a memo that overrides two rules, another identity question, ...), are given to the builder; the SPEC it
extracts must show that change, and no other.

    python dev/mutate_brief.py --selftest                     # no model: the checks themselves are sound
    python dev/mutate_brief.py --write out/mutations          # the changed briefs and tool API files, to look at
    python dev/mutate_brief.py --run [--only six_day_week,third_band] [--parallel 3] [--baseline <spec.json>] [--out out/mutations]
    python dev/mutate_brief.py --check out/mutations          # read the SPECs of an earlier --run again

--run calls the model: one extraction per change (about three calls and two minutes each, like a build), so it uses
the Claude login's quota. Run it when the quota is not needed for a build, and pass --only for a first look.
A change the builder misses names a kind of rule it cannot read yet; that is fixed in the extractor's field guide or
in the SPEC format, never by writing the changed value into builder/.
"""
import argparse, asyncio, copy, json, pathlib, re, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT)); sys.path.insert(0, str(KIT / "dev"))
from compare_specs import WORDING, diff

BRIEF = (KIT / "briefs/brief-a.md").read_text(encoding="utf-8")
API = json.loads((KIT / "tools/openapi.json").read_text(encoding="utf-8"))


def rep(text, old, new, count=1):
    """Replace, and fail loudly when the brief no longer reads as this mutation expects."""
    assert text.count(old) == count, f"expected {count} x {old!r} in the brief, found {text.count(old)}"
    return text.replace(old, new)


def api_enum(api, path, field, change):
    a = copy.deepcopy(api)
    props = a["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]
    props[field]["enum"] = change(list(props[field]["enum"]))
    return a


def band(spec, low):
    return next((b for b in spec["bands"] if b["days_late_min"] <= low <= b["days_late_max"]), None)


def sit_with_queue(spec, queue):
    for x in spec["situations"]:
        for eff in [x["effect"]] + ([x["offer"]["on_accept"], x["offer"]["on_decline"]] if x.get("offer") else []):
            if any(a.get("type") == "transfer" and a.get("queue") == queue for a in eff["actions"]):
                return x, eff
    return None, None


def pairs(node):
    if isinstance(node, dict):
        if isinstance(node.get("outcome"), str):
            yield node
        for v in node.values():
            yield from pairs(v)
    elif isinstance(node, list):
        for v in node:
            yield from pairs(v)


HOL = "Freya Bank holidays: 2026-10-26, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01."
MEMO = """MEMO - Legal and Compliance
Date: 9 October 2026
Re: Collections specification, changes effective immediately

1. Rule 12 and rule 14: four wrong answers in total end the identity check (was three).
2. Rule 6: callbacks may only be booked between 09:00 and 18:00, both included (was 10:00 to 19:00).

Everything else in the specification stays as it is.
"""


def mutations():
    """name -> {"docs": [(file name, text)], "api": dict, "expect": spec -> [problems], "oracle": spec -> spec with
    the change made by hand, "may_change": top-level SPEC parts this change is allowed to touch}."""
    M = {}

    def add(name, docs, expect, oracle, may_change, api=None):
        M[name] = {"docs": docs if isinstance(docs, list) else [("brief.md", docs)], "api": api or API, "expect": expect, "oracle": oracle, "may_change": may_change}

    def o(fn):                                           # an oracle from an in-place edit
        def run(spec):
            s = copy.deepcopy(spec); fn(s); return s
        return run

    add("holiday_added", rep(BRIEF, HOL, HOL[:-1].replace("2026-10-26", "2026-10-19, 2026-10-26") + "."),
        lambda s: [] if set(s["calendar"]["holidays"]) == {"2026-10-19", "2026-10-26", "2026-11-11", "2026-11-26", "2026-12-25", "2027-01-01"} else [f"holidays are {s['calendar']['holidays']}"],
        o(lambda s: s["calendar"]["holidays"].insert(0, "2026-10-19")), ["calendar"])
    add("holiday_removed", rep(BRIEF, "2026-11-11, ", ""),
        lambda s: [] if set(s["calendar"]["holidays"]) == {"2026-10-26", "2026-11-26", "2026-12-25", "2027-01-01"} else [f"holidays are {s['calendar']['holidays']}"],
        o(lambda s: s["calendar"]["holidays"].remove("2026-11-11")), ["calendar"])
    add("band_limit_moved", rep(rep(BRIEF, "| 1 to 7 | early |", "| 1 to 10 | early |"), "| 8 to 45 | late |", "| 11 to 45 | late |"),
        lambda s: [] if band(s, 10) and band(s, 11) and band(s, 10)["attempts"] == 1 and band(s, 11)["attempts"] == 2 and band(s, 10) is not band(s, 11) else
        [f"bands are {[(b['days_late_min'], b['days_late_max'], b['attempts']) for b in s['bands']]}"],
        o(lambda s: (s["bands"][0].__setitem__("days_late_max", 10), s["bands"][1].__setitem__("days_late_min", 11))), ["bands"])
    third = rep(rep(rep(BRIEF, "| 8 to 45 | late | the 7th business day after today | 2 |", "| 8 to 45 | late | the 7th business day after today | 2 |\n| 46 to 90 | very late | the 3rd business day after today | 2 |"),
                    "1 to 45 days late on one product", "1 to 90 days late on one product"), "Attempt 2, late band only:", "Attempt 2, late and very late bands:")

    def third_expect(s):
        b = band(s, 60)
        if not b or len(s["bands"]) != 3:
            return [f"bands are {[(x['days_late_min'], x['days_late_max']) for x in s['bands']]}"]
        return [] if (b["days_late_min"], b["days_late_max"], b["attempts"], b["deadline"].get("kind"), b["deadline"].get("n")) == (46, 90, 2, "nth_business_day_after_today", 3) else [f"the third band is {b}"]
    add("third_band", third, third_expect,
        o(lambda s: s["bands"].append(dict(copy.deepcopy(s["bands"][1]), name="very late", days_late_min=46, days_late_max=90, deadline={"kind": "nth_business_day_after_today", "n": 3}))), ["bands"])
    renamed = BRIEF.replace("`no_promise`", "`no_agreement`")
    assert renamed.count("`no_agreement`") >= 6

    def renamed_expect(s):
        used = {p["outcome"] for p in pairs(s)}
        return [] if "no_agreement" in used and "no_promise" not in used and s["negotiation"]["attempts_exhausted"]["outcome"] == "no_agreement" else [f"outcomes in use: {sorted(used)}"]

    def renamed_oracle(spec):
        return json.loads(json.dumps(spec).replace('"no_promise"', '"no_agreement"'))
    add("outcome_renamed", renamed, renamed_expect, renamed_oracle, ["outcomes", "negotiation", "recording", "situations", "identity", "opening", "third_party"],
        api=api_enum(API, "/close_call", "outcome", lambda e: ["no_agreement" if x == "no_promise" else x for x in e]))
    add("six_day_week", rep(BRIEF, "Business days are Monday to Friday", "Business days are Monday to Saturday"),
        lambda s: [] if s["calendar"]["business_weekdays"] == [0, 1, 2, 3, 4, 5] else [f"business weekdays are {s['calendar']['business_weekdays']}"],
        o(lambda s: s["calendar"].__setitem__("business_weekdays", [0, 1, 2, 3, 4, 5])), ["calendar"])

    def cal_expect(s):
        d = band(s, 5)["deadline"]
        return [] if (d.get("kind"), d.get("n"), d.get("roll")) == ("nth_calendar_day_after_today", 14, "next_business_day") else [f"the early deadline is {d}"]
    add("deadline_in_calendar_days", rep(BRIEF, "the 12th business day after today", "the 14th calendar day after today; if that is not a business day, the next business day"),
        cal_expect, o(lambda s: s["bands"][0].__setitem__("deadline", {"kind": "nth_calendar_day_after_today", "n": 14, "roll": "next_business_day"})), ["bands"])
    staff = rep(rep(BRIEF, "45. If the customer says twice", "48. If the customer says they work for Freya Bank themselves: do not negotiate and take no promise. Call `transfer_to_agent` with queue `staff` and close as `transferred` / `staff`.\n45. If the customer says twice"),
                "| `transferred` | `restructuring`, `human`, `support` | rules 41, 42, 32 |", "| `transferred` | `restructuring`, `human`, `support`, `staff` | rules 41, 42, 32, 48 |")

    def staff_expect(s):
        x, eff = sit_with_queue(s, "staff")
        return [] if x and (eff["outcome"], eff["reason"]) == ("transferred", "staff") and "negotiation" in x["stages"] else ["no situation transfers to the queue staff and closes as transferred / staff"]

    def staff_oracle(spec):
        s = copy.deepcopy(spec)
        base = copy.deepcopy(next(x for x in s["situations"] if x["id"] == "restructuring"))
        base.update(id="staff_member", trigger="The customer says they work for the bank themselves.", not_this="", evidence_words=["work for", "staff", "employee"], guidance="Do not negotiate.")
        base["effect"] = {"actions": [{"type": "transfer", "queue": "staff"}], "outcome": "transferred", "reason": "staff"}
        s["situations"].append(base)
        next(r for r in s["outcomes"]["table"] if r["outcome"] == "transferred")["reasons"].append("staff")
        return s
    add("new_situation", staff, staff_expect, staff_oracle, ["situations", "outcomes"], api=api_enum(API, "/transfer_to_agent", "queue", lambda e: e + ["staff"]))

    def memo_expect(s):
        cb, bad = s["third_party"]["callback"], []
        if s["identity"]["max_wrong_total"] != 4: bad.append(f"max_wrong_total is {s['identity']['max_wrong_total']}, the memo says 4")
        if (cb["window_start"], cb["window_end"]) != ("09:00", "18:00"): bad.append(f"callback window is {cb['window_start']}-{cb['window_end']}, the memo says 09:00-18:00")
        return bad
    add("memo_overrides_two_rules", [("1-specification.md", BRIEF), ("2-memo.md", MEMO)], memo_expect,
        o(lambda s: (s["identity"].__setitem__("max_wrong_total", 4), s["third_party"]["callback"].update(window_start="09:00", window_end="18:00"))), ["identity", "third_party"])
    post = rep(rep(BRIEF, "then the last four digits of the phone number on file", "then the postcode of the registered address"), "`YYYY-MM-DD`, whatever way the customer said it.", "`YYYY-MM-DD`, whatever way the customer said it. Send the postcode in capital letters without spaces.")
    post_api = api_enum(API, "/verify_identity", "field", lambda e: ["postcode" if x == "phone_last4" else x for x in e])
    ans = post_api["paths"]["/verify_identity"]["post"]["requestBody"]["content"]["application/json"]["schema"]["properties"]["answer"]
    ans["description"] = ans["description"].replace("For phone_last4: four digits.", "For postcode: capital letters, no spaces.")

    def post_expect(s):
        q = s["identity"]["questions"]
        return [] if len(q) == 2 and q[1]["field"] == "postcode" and q[1]["value_type"] == "text" and q[0]["value_type"] == "date" else [f"identity questions are {[(x['field'], x['value_type']) for x in q]}"]
    add("identity_question_changed", post, post_expect,
        o(lambda s: s["identity"]["questions"][1].update(field="postcode", value_type="text", ask="What is the postcode of your registered address?", answer_format="capital letters, no spaces")), ["identity"], api=post_api)
    two = rep(rep(BRIEF, "| 1 to 7 | early | the 12th business day after today | 1 |", "| 1 to 7 | early | the 12th business day after today | 2 |"), "Attempt 2, late band only:", "Attempt 2, both bands:")
    add("early_band_two_attempts", two,
        lambda s: [] if band(s, 5)["attempts"] == 2 and len(band(s, 5)["ladder"]) == 2 and band(s, 5)["ladder"][1]["amount"].get("kind") == "floor" else [f"the early band is {band(s, 5)['attempts']} attempt(s), ladder {band(s, 5)['ladder']}"],
        o(lambda s: s["bands"][0].update(attempts=2, ladder=copy.deepcopy(s["bands"][1]["ladder"]))), ["bands"])
    add("first_ask_reworded", rep(BRIEF, "First ask: \"Can you make this payment today?\".", "First ask: \"Are you able to settle this amount today?\"."),
        lambda s: [] if s["negotiation"]["first_ask"].strip() == "Are you able to settle this amount today?" else [f"first_ask is {s['negotiation']['first_ask']!r}"],
        o(lambda s: s["negotiation"].__setitem__("first_ask", "Are you able to settle this amount today?")), ["negotiation"])
    add("callback_window_moved", rep(BRIEF, "from 10:00 to 19:00, both included", "from 09:30 to 17:30, both included"),
        lambda s: [] if (s["third_party"]["callback"]["window_start"], s["third_party"]["callback"]["window_end"]) == ("09:30", "17:30") else [f"window is {s['third_party']['callback']['window_start']}-{s['third_party']['callback']['window_end']}"],
        o(lambda s: s["third_party"]["callback"].update(window_start="09:30", window_end="17:30")), ["third_party"])
    add("two_wrong_answers", rep(rep(BRIEF, "Three wrong answers in total end the check", "Two wrong answers in total end the check"), "After three wrong answers", "After two wrong answers"),
        lambda s: [] if s["identity"]["max_wrong_total"] == 2 else [f"max_wrong_total is {s['identity']['max_wrong_total']}"],
        o(lambda s: s["identity"].__setitem__("max_wrong_total", 2)), ["identity"])
    add("two_retries", rep(BRIEF, "If it fails, try once more. If it fails again, say you could not record it", "If it fails, try twice more. If it fails a third time, say you could not record it"),
        lambda s: [] if s["recording"]["max_attempts"] == 3 else [f"recording.max_attempts is {s['recording']['max_attempts']} (first try plus two retries is 3)"],
        o(lambda s: s["recording"].__setitem__("max_attempts", 3)), ["recording"])
    add("vague_asked_twice", rep(BRIEF, "ask once for the exact day. If they still give none, propose the deadline.", "ask twice for the exact day. If they still give none, treat it as a flat refusal (rule 30)."),
        lambda s: [] if (s["dates"]["vague"]["ask_exact_times"], s["dates"]["vague"]["then"]) == (2, "flat_refusal") else [f"vague is {s['dates']['vague']['ask_exact_times']} ask(s), then {s['dates']['vague']['then']}"],
        o(lambda s: s["dates"]["vague"].update(ask_exact_times=2, then="flat_refusal")), ["dates"])
    return M


def collateral(baseline, spec, may_change):
    """Behaviour that differs from the baseline SPEC outside the parts this change may touch. Wording, the rule map
    and the free rules are not compared: two readings of the same brief word them differently."""
    out = []
    diff(baseline, spec, "", out)
    quiet = (".rule_map", ".free_rules", ".meta", ".spec_version")
    return [f"{kind} {path}" for kind, path, a, b in out
            if not path.startswith(quiet) and path.split(".")[-1].split("[")[0] not in WORDING and path.strip(".").split(".")[0] not in may_change
            and not any(w in path for w in (".source", ".evidence_words", ".guidance", ".priority"))]


def judge(name, m, spec, baseline=None):
    problems = [f"missed: {p}" for p in m["expect"](spec)]
    if baseline is not None:
        problems += [f"also changed: {p}" for p in collateral(baseline, spec, m["may_change"])[:8]]
    return problems


def selftest():
    """No model: for every change, the brief text really differs, a SPEC with the change made by hand passes its
    check, the unchanged reference SPEC fails it, and the hand-made change touches only the parts it may touch."""
    from builder.ingest import parse_api
    from builder.spec_schema import validate
    ref = json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8"))
    bad = []
    for name, m in mutations().items():
        if all(text == BRIEF for _, text in m["docs"]) and len(m["docs"]) == 1: bad.append(f"{name}: the brief text did not change")
        made = m["oracle"](ref)
        errs = validate(made, parse_api(m["api"])["tools"])
        if errs: bad.append(f"{name}: the hand-made SPEC does not validate against its tool API: {errs[:2]}")
        if m["expect"](made): bad.append(f"{name}: the hand-made SPEC fails its own check: {m['expect'](made)}")
        if not m["expect"](ref): bad.append(f"{name}: the unchanged SPEC passes the check, so the check proves nothing")
        if collateral(ref, made, m["may_change"]): bad.append(f"{name}: the hand-made change touches other parts: {collateral(ref, made, m['may_change'])[:3]}")
    return bad


def write(folder, only=None):
    folder = pathlib.Path(folder)
    for name, m in mutations().items():
        if only and name not in only: continue
        d = folder / name
        d.mkdir(parents=True, exist_ok=True)
        for fname, text in m["docs"]: (d / fname).write_text(text, encoding="utf-8")
        (d / "tool-api.json").write_text(json.dumps(m["api"], indent=1), encoding="utf-8")
    return folder


async def run(folder, only, parallel, baseline_path):
    from builder import extract
    from builder.ingest import parse_api
    from builder.trace import Trace
    folder = write(folder, only)
    gate = asyncio.Semaphore(parallel)

    async def one(name, docs, api):
        async with gate:
            t = Trace(KIT / "traces", f"dev-mutation-{name}")
            try:
                spec, rep_ = await extract.extract([{"path": n, "name": pathlib.Path(n).stem, "text": x} for n, x in docs], parse_api(api)["tools"], t)
                (folder / f"{name}.spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
                t.close("ok")
                return name, spec
            except Exception as e:
                t.close("error")
                return name, f"{type(e).__name__}: {e}"

    M = {k: v for k, v in mutations().items() if not only or k in only}
    jobs = [one(n, m["docs"], m["api"]) for n, m in M.items()]
    if baseline_path:
        base = json.loads(pathlib.Path(baseline_path).read_text(encoding="utf-8"))
    else:
        jobs.append(one("baseline", [("brief.md", BRIEF)], API))
    done = dict(await asyncio.gather(*jobs))
    if not baseline_path:
        base = done.pop("baseline")
        base = base if isinstance(base, dict) else None
    return report({n: s for n, s in done.items()}, base)


def report(specs, baseline):
    M, missed = mutations(), 0
    for name, spec in specs.items():
        if not isinstance(spec, dict):
            print(f"ERROR  {name}: {spec}"); missed += 1; continue
        problems = judge(name, M[name], spec, baseline)
        missed += bool([p for p in problems if p.startswith("missed")])
        print(("READ   " if not problems else "MISSED " if any(p.startswith("missed") for p in problems) else "NOISY  ") + name)
        for p in problems: print("         " + p[:240])
    print(f"\n{len(specs) - missed} of {len(specs)} changes were read" + ("" if baseline is not None else " (no baseline SPEC: other changes not checked)"))
    return missed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true"); ap.add_argument("--write"); ap.add_argument("--run", action="store_true"); ap.add_argument("--check")
    ap.add_argument("--only"); ap.add_argument("--parallel", type=int, default=3); ap.add_argument("--baseline"); ap.add_argument("--out", default=str(KIT / "out" / "mutations"))
    a = ap.parse_args(argv)
    only = a.only.split(",") if a.only else None
    if a.selftest:
        bad = selftest()
        for b in bad: print("FAIL", b)
        print(f"{len(mutations())} changes; " + ("all good" if not bad else f"{len(bad)} failure(s)"))
        return 1 if bad else 0
    if a.write:
        print("written to", write(a.write, only)); return 0
    if a.check:
        folder = pathlib.Path(a.check)
        specs = {p.name[:-10]: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.spec.json")) if p.name != "baseline.spec.json" and (not only or p.name[:-10] in only)}
        base = folder / "baseline.spec.json"
        return 1 if report(specs, json.loads(pathlib.Path(a.baseline).read_text(encoding="utf-8")) if a.baseline else (json.loads(base.read_text(encoding="utf-8")) if base.exists() else None)) else 0
    if a.run:
        t0 = time.time()
        missed = asyncio.run(run(a.out, only, a.parallel, a.baseline))
        print(f"{time.time() - t0:.0f} s")
        return 1 if missed else 0
    ap.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())
