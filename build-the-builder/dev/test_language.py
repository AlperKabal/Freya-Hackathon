"""Customers say amounts and days in many ways. Random amounts and days, said in the forms people use (digits, words,
cents, currency words, a day with or without its month, a weekday, "in five days", a filler sentence around it, a
self-correction), must come back as the same value from parse_amount and resolve_spoken_date. The expected value
is worked out here with datetime and plain arithmetic, not with the agent's code.

    python dev/test_language.py [--seed N] [--n 400]
"""
import datetime as dt, json, pathlib, random, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen

ns = {}
exec("import json\nimport datetime as _dt\nimport re as _re\n" + codegen.snippet("dates") + "\n" + codegen.snippet("negotiation"), ns)
parse_amount, resolve = ns["parse_amount"], ns["resolve_spoken_date"]
args = sys.argv[1:]
SEED = int(args[args.index("--seed") + 1]) if "--seed" in args else 7
N = int(args[args.index("--n") + 1]) if "--n" in args else 400
fails = 0

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
ORD = {1: "first", 2: "second", 3: "third", 5: "fifth", 8: "eighth", 9: "ninth", 12: "twelfth"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def check(label, bad, total):
    global fails
    fails += bool(bad)
    print(f"{'PASS' if not bad else 'FAIL'} {label}: {total - len(bad)} / {total}" + ("" if not bad else "\n   " + "\n   ".join(bad[:12])))


def below_100(n, hyphen=True):
    if n < 20:
        return ONES[n]
    return TENS[n // 10] + (("-" if hyphen else " ") + ONES[n % 10] if n % 10 else "")


def words(n, rng):
    """An integer in words, the way people say it: 'two thousand one hundred and twenty-five', 'twelve hundred'."""
    if n == 0:
        return "zero"
    parts = []
    if 1100 <= n < 2000 and n % 100 == 0 and rng.random() < 0.5:
        return below_100(n // 100) + " hundred"
    if n >= 1000:
        parts.append(("a" if n // 1000 == 1 and rng.random() < 0.3 else below_100(n // 1000)) + " thousand")
        n %= 1000
    if n >= 100:
        parts.append(ONES[n // 100] + " hundred")
        n %= 100
    if n:
        parts.append(("and " if parts and rng.random() < 0.6 else "") + below_100(n, hyphen=rng.random() < 0.5))
    return " ".join(parts)


def ordinal(n):
    if n in ORD:
        return ORD[n]
    if n < 20:
        return ONES[n] + "th"
    if n % 10 == 0:
        return TENS[n // 10][:-1] + "ieth"
    return TENS[n // 10] + "-" + (ORD.get(n % 10) or ONES[n % 10] + "th")


def suffix(n):
    return str(n) + ("th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


# ---------------------------------------------------------------- amounts
rng = random.Random(SEED)
FILL = ["{}", "I can pay {}", "maybe {}?", "{} would work", "I could do {} I think", "how about {}", "ok, {}", "let's say {}"]
bad, total = [], 0
for _ in range(N):
    whole = rng.choice([rng.randint(1, 99), rng.randint(100, 999), rng.randint(1000, 9999), rng.randint(1, 50) * 100])
    cents = rng.choice([0, 0, 0, 50, 25, rng.randint(1, 99)])
    value = round(whole + cents / 100.0, 2)
    forms = [("%.2f" % value) if cents else str(whole), "{:,}".format(whole) + ("." + "%02d" % cents if cents else "")]
    if not cents:
        forms += [words(whole, rng), words(whole, rng) + " dollars", "$" + str(whole), str(whole) + " pounds"]
    else:
        forms += [words(whole, rng) + " dollars and " + below_100(cents) + " cents", str(whole) + " pounds " + "%02d" % cents if cents >= 10 else "%.2f" % value,
                  words(whole, rng) + " and " + str(cents) + " cents"]
    for f in forms:
        said = rng.choice(FILL).format(f)
        total += 1
        got = parse_amount(said)
        if got is None or abs(got - value) > 0.005:
            bad.append(f"{said!r} -> {got} (want {value})")
check("an amount said in digits, words, with cents or a currency word comes back exactly", bad, total)

bad, total = [], 0
for _ in range(N // 4):
    a, b = rng.randint(50, 900), rng.randint(50, 900)
    for f in ("{a}, sorry, {b}", "{wa}, no actually {wb}", "I can do {a}, I mean {b}", "make that {b}"):
        said = f.format(a=a, b=b, wa=words(a, rng), wb=words(b, rng))
        total += 1
        got = parse_amount(said)
        if got != float(b):
            bad.append(f"{said!r} -> {got} (want {b})")
check("a self-corrected amount keeps the last one", bad, total)

bad, total = [], 0
for _ in range(N // 4):
    amt, day = rng.randint(20, 3000), rng.randint(1, 28)
    mon = MONTHS[rng.randint(0, 11)]
    for f in ("{a} on the {s}", "on the {s} I can pay {a}", "{a} on {d} {m}", "{wa} on {m} {s}", "{a} by the {o}"):
        said = f.format(a=amt, wa=words(amt, rng), s=suffix(day), d=day, m=mon, o=ordinal(day))
        total += 1
        got = parse_amount(said)
        if got != float(amt):
            bad.append(f"{said!r} -> {got} (want {amt})")
check("an amount next to a day of the month is the amount, never the day", bad, total)

# ---------------------------------------------------------------- days
SPEC_A = json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8"))
SPEC_D = json.loads((KIT / "dev/specs/imaginary-d.json").read_text(encoding="utf-8"))
DFILL = ["{}", "I can pay on {}", "{} works for me", "maybe {}?", "{}, I think", "I get paid so {} is fine", "can we do {}"]


def expected_weekday(today, wd, mod, spec):
    """'Friday' / 'this Friday' / 'next Friday' by the SPEC's own rule, worked out day by day."""
    monday = today - dt.timedelta(days=today.weekday())
    upcoming = today + dt.timedelta(days=(wd - today.weekday()) % 7)                 # today counts
    if mod == "next":
        if spec["dates"]["relative_weekday"]["next"] == "following_week":
            return monday + dt.timedelta(days=7 + wd)
        nxt = today + dt.timedelta(days=(wd - today.weekday()) % 7 or 7)
        return nxt
    if mod == "this":
        return monday + dt.timedelta(days=wd) if spec["dates"]["relative_weekday"]["this"] == "current_week" else upcoming
    return upcoming


for spec_name, spec in (("brief A", SPEC_A), ("bank D", SPEC_D)):
    cfg = codegen.date_config(spec)
    bad, total = [], 0
    for _ in range(N):
        today = dt.date(2026, 10, 1) + dt.timedelta(days=rng.randint(0, 180))
        target = today + dt.timedelta(days=rng.randint(1, 40))
        d, m, wd = target.day, MONTHS[target.month - 1], DAYS[target.weekday()]
        forms = [f"{d} {m}", f"{m} {d}", f"{m} {suffix(d)}", f"the {suffix(d)} of {m}", f"{wd} {d} {m}",
                 f"{m} the {ordinal(d)}", f"the {ordinal(d)} of {m}", f"{d}/{target.month}", target.isoformat(), f"{suffix(d)} {m[:3]}"]
        if (target - today).days <= 27:
            forms += [f"the {suffix(d)}", f"on the {ordinal(d)}"]
        n = (target - today).days
        forms += [f"in {n} days", f"in {words(n, rng)} days"] if n > 1 else ["tomorrow"]
        if n == 2:
            forms.append("the day after tomorrow")
        for f in forms:
            said = rng.choice(DFILL).format(f)
            total += 1
            got = resolve(said, today, cfg)
            if got.get("date") != target.isoformat():
                bad.append(f"[{today} {DAYS[today.weekday()][:3]}] {said!r} -> {got} (want {target})")
        # "Saturday the 28th" without a month: the nearest day with that number on that weekday (February and March
        # of a common year have the same weekdays, so the nearest one is the answer, not the one we had in mind)
        said = rng.choice(DFILL).format(f"{wd} the {suffix(d)}")
        want = next(x for x in (today + dt.timedelta(days=k) for k in range(0, 800)) if x.day == d and x.weekday() == target.weekday())
        total += 1
        got = resolve(said, today, cfg)
        if got.get("date") != want.isoformat():
            bad.append(f"[{today} {DAYS[today.weekday()][:3]}] {said!r} -> {got} (want {want})")
        for mod in ("", "this", "next"):
            wd_i = rng.randint(0, 6)
            want = expected_weekday(today, wd_i, mod, spec)
            said = rng.choice(DFILL).format((mod + " " if mod else "") + DAYS[wd_i])
            total += 1
            got = resolve(said, today, cfg)
            if got.get("date") != want.isoformat():
                bad.append(f"[{today} {DAYS[today.weekday()][:3]}] {said!r} -> {got} (want {want}, {spec['dates']['relative_weekday']})")
    check(f"{spec_name}: a day said in the usual forms (with month, without, a weekday, 'in n days') comes back exactly", bad, total)

print(f"\n{'all good' if not fails else f'{fails} failure(s)'}")
sys.exit(1 if fails else 0)
