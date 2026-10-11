"""Shared machinery for the mock briefs (see README.md in this folder).

A mock brief is a folder: the brief documents as a bank would send them, its own tool API file, the SPEC a careful
reader takes from them (`spec.json`, written by hand: the oracle) and customers with the bank records each must
leave behind (`cases.py`). Nothing here is an organiser brief and nothing here may be copied into builder/.

    P = Pack("d-harbor-raw")                 # documents, tool API, oracle SPEC, cases
    sim = P.sim(case, mode="orch")           # a whole call, from the first code node to close_call, without the platform
    play(sim, case)                          # the customer of the case talks; the bank stand-in keeps the ledger
    problems = judge(P, case, sim)           # ledger == expected, plus what must hold in every call

Three things are independent of the builder on purpose, so that two ways lead to every expected value:
- Cal: the bank's calendar and date rules, worked out day by day (never builder/snippets/dates.py);
- Bank: a stand-in for the bank's API that speaks the field names of the pack's own tool API file;
- the expected records of every case, written from the brief's text.
What the phone model would do (classify a reply, call a tool, take a transition) is given by the case; what code
decides is run for real: every code node, hook, engine-run bank call and deterministic transition of the workflow.
"""
import copy, datetime as dt, decimal, importlib.util, json, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
KIT = HERE.parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(HERE))
from builder import generate, ingest, verify                      # noqa: E402

ONE = dt.timedelta(days=1)
WD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MO = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
VAR = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)(?::json)?\}\}")
SPOKEN_DAY = re.compile(r"\b(" + "|".join(WD) + r") (\d{1,2}) (" + "|".join(MO) + r") (\d{4})\b")
MONEY = re.compile(r"(?<![\d.])(\d+\.\d{2})(?![\d.])")


def day(text):
    return dt.date.fromisoformat(text[:10])


def spoken(d):
    return f"{WD[d.weekday()]} {d.day} {MO[d.month - 1]} {d.year}"


def cents(x):
    """Money rounded to the cent the way a bank clerk does it: exactly half a cent goes up."""
    return float(decimal.Decimal(str(x)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


# ---------------------------------------------------------------- the bank's calendar, independent of the builder

class Cal:
    """Date and amount rules of one SPEC, by plain day-by-day counting."""

    def __init__(self, spec):
        self.spec = spec
        self.weekdays = set(spec["calendar"]["business_weekdays"])
        self.holidays = set(spec["calendar"]["holidays"])

    def biz(self, d):
        return d.weekday() in self.weekdays and d.isoformat() not in self.holidays

    def next_biz(self, d):
        d += ONE
        while not self.biz(d):
            d += ONE
        return d

    def nth_biz_after(self, d, n):
        for _ in range(int(n)):
            d = self.next_biz(d)
        return d

    def roll(self, d, how):
        step = {"next_business_day": ONE, "previous_business_day": -ONE}.get(how)
        while step and not self.biz(d):
            d += step
        return d

    def last_biz_of_week(self, d, weeks=0):
        x = d + dt.timedelta(days=6 - d.weekday() + 7 * int(weeks))                # that week's Sunday
        return self.roll(x, "previous_business_day")

    def last_biz_of_month(self, d, months=0):
        m = d.month - 1 + int(months) + 1                                           # the month after the one meant
        first_next = dt.date(d.year + m // 12, m % 12 + 1, 1)
        return self.roll(first_next - ONE, "previous_business_day")

    def date(self, rule, today, deadline=None):
        k = rule["kind"]
        if k == "today":
            return today
        if k == "deadline":
            return deadline
        if k == "nth_business_day_after_today":
            return self.nth_biz_after(today, rule["n"])
        if k == "nth_calendar_day_after_today":
            return self.roll(today + dt.timedelta(days=int(rule["n"])), rule.get("roll", "none"))
        if k == "last_business_day_of_week":
            x = self.last_biz_of_week(today, rule.get("week_offset", 0))
            if x <= today and rule.get("if_today_week_offset") is not None:
                x = self.last_biz_of_week(today, rule["if_today_week_offset"])
            return x
        if k == "last_business_day_of_month":
            x = self.last_biz_of_month(today, rule.get("month_offset", 0))
            return x if x >= today else self.last_biz_of_month(today, int(rule.get("month_offset", 0)) + 1)
        raise ValueError(k)

    def band(self, days_late):
        return next((b for b in self.spec["bands"] if b["days_late_min"] <= int(days_late) <= b["days_late_max"]), None)

    def deadline(self, days_late, today):
        b = self.band(days_late)
        return self.date(b["deadline"], today) if b else None

    def earliest(self, today):
        return self.date(self.spec["dates"]["earliest"], today)

    def allowed(self, d, days_late, today):
        """May a promise have this date? (the brief's own date rules, nothing offered instead)"""
        dl = self.deadline(days_late, today)
        return d >= self.earliest(today) and (dl is None or d <= dl) and (self.biz(d) or not self.spec["dates"]["business_day_only"])

    def first_day(self, days_late, today):
        """The first day a promise can have: today, unless today is no day for a promise."""
        d = self.earliest(today)
        for _ in range(40):
            if self.allowed(d, days_late, today):
                return d
            d += ONE
        return None

    def amount(self, rule, full, floor, too_much=False):
        k = rule["kind"]
        if k == "floor" or (k == "full_or_floor_if_too_much" and too_much):
            return cents(min(floor, full))
        if k == "percent_of_full":
            return cents(decimal.Decimal(str(full)) * decimal.Decimal(str(rule["percent"])) / 100)
        return cents(full)

    def ladder(self, days_late, today, full, floor, too_much=False):
        """The persuasion offers of a product, in order: [(amount, date)]. No offer is later than the deadline."""
        b = self.band(days_late)
        if not b:
            return []
        dl = self.deadline(days_late, today)
        out = []
        for st in b["ladder"]:
            d = self.date(st["date"], today, dl)
            out.append((self.amount(st["amount"], full, floor, too_much), min(d, dl) if dl else d))
        return out

    def callback_days(self, today):
        cb = self.spec["third_party"]["callback"]
        days, d = ([today] if cb["include_today"] else []), today
        for _ in range(int(cb["business_days_ahead"])):
            d = self.next_biz(d)
            days.append(d)
        return days

    def callback_ok(self, d, hhmm, now):
        cb = self.spec["third_party"]["callback"]
        mins = lambda t: int(t[:2]) * 60 + int(t[3:])
        inside = mins(cb["window_start"]) <= mins(hhmm) <= mins(cb["window_end"]) if cb["inclusive"] else mins(cb["window_start"]) < mins(hhmm) < mins(cb["window_end"])
        later = not cb["after_now"] or dt.datetime.combine(d, dt.time(int(hhmm[:2]), int(hhmm[3:]))) > now
        return d in self.callback_days(now.date()) and inside and later


# ---------------------------------------------------------------- the bank, speaking the pack's own API

class Bank:
    """Answers the seven tools with the field names of the pack's tool API file and keeps the ledger a scorer would
    read. It enforces what an API can know (required fields, allowed values, identity before the account), never
    the brief."""

    def __init__(self, spec, tools, identity, products, faults=None):
        self.spec, self.tools, self.tf = spec, tools, spec["tool_fields"]
        self.identity, self.faults = dict(identity or {}), dict(faults or {})
        pf = spec["account"]["product_fields"]
        self.products = [dict(p) for p in products or []]
        for i, p in enumerate(self.products):
            p.setdefault(pf["id"], f"p{i + 1}")
        self.passed, self.wrong, self.closed = set(), 0, False
        self.calls, self.promises, self.notes, self.callbacks, self.transfers, self.outcome = [], [], [], [], [], None
        self.errors = []                                           # what a real API would have refused

    # -- helpers
    def _ok(self, tool, good, **more):
        name = self.spec["recording"]["success_field"] if tool == "create_promise" else self.spec["identity"]["result_fields"]["ok"]
        return dict({name or "ok": bool(good)}, **more)

    def _refuse(self, tool, why):
        self.errors.append(f"{tool}: {why}")
        return self._ok(tool, False, error=why)

    def _enum(self, tool, field):
        return ((self.tools.get(tool) or {}).get("request", {}).get(field) or {}).get("enum") or []

    def call(self, tool, body):
        body = dict(body or {})
        if self.closed:
            data = self._refuse(tool, "the call is closed: nothing is accepted after close_call")
        else:
            missing = [r for r in (self.tools.get(tool) or {}).get("required", []) if body.get(r) in (None, "")]
            wrong = [f"{k}={v!r}" for k, v in body.items() if self._enum(tool, k) and v not in self._enum(tool, k)]
            unknown = [k for k in body if k not in (self.tools.get(tool) or {}).get("request", {})]
            if missing:
                data = self._refuse(tool, f"required field(s) missing: {', '.join(missing)}")
            elif wrong:
                data = self._refuse(tool, f"value not allowed by the API: {', '.join(wrong)}")
            elif unknown:
                data = self._refuse(tool, f"field(s) not in the API: {', '.join(unknown)}")
            else:
                n = sum(1 for t, _, _ in self.calls if t == tool)
                if n < int(self.faults.get(tool, 0)):
                    data = self._ok(tool, False, error="service unavailable")
                else:
                    data = getattr(self, "_" + tool)(body)
        self.calls.append((tool, body, data))
        return data

    # -- the seven tools
    def _verify_identity(self, b):
        idn, f, rf = self.spec["identity"], self.tf["verify_identity"], self.spec["identity"]["result_fields"]
        field, answer = b.get(f["field"]), str(b.get(f["answer"]))
        q = next((x for x in idn["questions"] if x["field"] == field), None)
        left = lambda: max(0, int(idn["max_wrong_total"]) - self.wrong)
        if q is None or field not in self.identity:
            return self._refuse("verify_identity", f"unknown question {field!r}")
        if left() == 0:
            return self._refuse("verify_identity", "the check has ended")
        if q["value_type"] == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", answer):
            return self._ok("verify_identity", False, error="unreadable value")      # not counted as a wrong answer
        right, out = str(self.identity[field]), {}
        good = answer == right
        if good:
            self.passed.add(field)
        else:
            hint = next((h for h in idn["hints"] if _hint_fits(h["value"], answer, right, q["value_type"])), None)
            if hint and rf["hint"]:
                out[rf["hint"]] = hint["value"]
            if not hint or hint["counts_as_wrong"]:
                self.wrong += 1
        out[rf["verified"] or "verified"] = good
        if rf["all_verified"]:
            out[rf["all_verified"]] = self.verified()
        if rf["wrong_left"]:
            out[rf["wrong_left"]] = left()
        return self._ok("verify_identity", True, **out)

    def verified(self):
        return all(q["field"] in self.passed for q in self.spec["identity"]["questions"])

    def _get_account(self, b):
        if not self.verified():
            return self._refuse("get_account", "identity not verified")
        return self._ok("get_account", True, **{self.spec["account"]["products_field"]: copy.deepcopy(self.products)})

    def _create_promise(self, b):
        f, pf = self.tf["create_promise"], self.spec["account"]["product_fields"]
        if not self.verified():
            return self._refuse("create_promise", "identity not verified")
        pid, amount, date = b.get(f["product_id"]), b.get(f["amount"]), str(b.get(f["date"]))
        if pid not in [p[pf["id"]] for p in self.products]:
            return self._refuse("create_promise", f"unknown product id {pid!r}")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return self._refuse("create_promise", f"the amount is not a number: {amount!r}")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return self._refuse("create_promise", f"the date is not YYYY-MM-DD: {date!r}")
        if pid in [p[0] for p in self.promises]:
            return self._refuse("create_promise", f"a second promise for {pid}")
        self.promises.append((pid, round(float(amount), 2), date))
        return self._ok("create_promise", True, promise_id="pr_" + str(len(self.promises)))

    def _add_note(self, b):
        f, pf = self.tf["add_note"], self.spec["account"]["product_fields"]
        pid = b.get(f["product_id"]) if f["product_id"] else None
        if f["product_id"] and pid not in [p[pf["id"]] for p in self.products]:
            return self._refuse("add_note", f"unknown product id {pid!r}")
        self.notes.append((pid, b.get(f["reason"])))
        return self._ok("add_note", True)

    def _schedule_callback(self, b):
        f = self.tf["schedule_callback"]
        date, time = str(b.get(f["date"])), str(b.get(f["time"]))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
            return self._refuse("schedule_callback", f"date or time not readable: {date!r} {time!r}")
        self.callbacks.append((date, time))
        return self._ok("schedule_callback", True)

    def _transfer_to_agent(self, b):
        self.transfers.append(b.get(self.tf["transfer_to_agent"]["queue"]))
        return self._ok("transfer_to_agent", True)

    def _close_call(self, b):
        f = self.tf["close_call"]
        self.outcome = (b.get(f["outcome"]), (b.get(f["reason"]) if f["reason"] else None) or None)
        self.closed = True
        return self._ok("close_call", True)

    def ledger(self):
        return {"outcome": self.outcome[0] if self.outcome else None, "reason": self.outcome[1] if self.outcome else None,
                "promises": sorted(self.promises), "notes": sorted(self.notes, key=str), "callbacks": sorted(self.callbacks),
                "transfers": sorted(map(str, self.transfers)), "calls": [t for t, _, _ in self.calls]}


def _hint_fits(name, answer, right, kind):
    """When would a bank answer with this hint? Read from the hint's own name (each pack names its hints so)."""
    n = name.lower()
    if "swap" in n:
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", answer)
        return bool(m) and f"{m.group(1)}-{m.group(3)}-{m.group(2)}" == right
    if "transpos" in n:
        return answer != right and sorted(answer) == sorted(right)
    if "partial" in n or "incomplete" in n or "short" in n:
        return answer != right and bool(answer) and right.startswith(answer)
    return False


# ---------------------------------------------------------------- a whole call without the platform

_COMPILED = {}


def _exec(src, env, label="code"):
    code = _COMPILED.get(src)
    if code is None:
        code = _COMPILED[src] = compile(src, label, "exec")
    exec(code, env)


def holds(c, v):
    """A transition condition, evaluated like the platform's deterministic operators (docs/workflow-format.md)."""
    if c.get("operator") == "always":
        return True
    if "logic" in c:
        r = [holds(x, v) for x in c["conditions"]]
        return all(r) if c["logic"] == "and" else any(r)
    val, op = v.get(c["variable"]), c["operator"]
    if op == "equals": return val is not None and str(val) == str(c["operand"])
    if op == "not_equals": return not (val is not None and str(val) == str(c["operand"]))
    if op == "is_set": return val is not None
    if op == "greater_than":
        try: return float(val) > float(c["operand"])
        except (TypeError, ValueError): return False
    return False                                                   # matches_intent is the model's judgment


class Sim:
    """One call through a generated workflow. Code nodes, hooks, engine-run bank calls, spoken fixed lines and
    deterministic transitions run as on the platform; a customer turn is given as what the extraction would write
    (`turn`), a tool the model would call (`tool`) or a transition the model would take (`go`)."""

    def __init__(self, spec, tools, bank, mode="orch", now="2026-10-14T11:00", variables=None, wf=None):
        self.spec, self.tools, self.bank, self.mode = spec, tools, bank, mode
        self.wf = wf or generate.build(spec, tools, mode)
        self.by_url = {t["url"]: name for name, t in tools.items()}
        roles = {x["role"]: x["name"] for x in spec["call_variables"]}
        self.now_var = roles["now"]
        self.v = dict(variables or {})
        self.v[self.now_var] = now
        self.v.setdefault(roles["customer_id"], "c_test")
        self.said, self.trail, self.entered, self.ended, self.problems, self.stopped = [], [], set(), False, [], False
        self.node = self._walk(self.wf["initial_node"])

    # -- the engine
    def _fill(self, text):
        return VAR.sub(lambda m: str(self.v.get(m.group(1), m.group(0))), text or "")

    def _api(self, fn, name, args=None):
        props = fn["function"]["parameters"]["properties"]
        body = {}
        for field, p in props["body"]["properties"].items():
            if args is not None and field in args:
                body[field] = args[field]
                continue
            d = p.get("default")
            m = VAR.fullmatch(d) if isinstance(d, str) else None
            if m:
                if self.v.get(m.group(1)) is None:
                    continue                                        # an unresolved placeholder: the field is dropped
                body[field] = self.v[m.group(1)]
            elif isinstance(d, str):
                body[field] = self._fill(d)
            elif d is not None:
                body[field] = d
        if fn.get("pre_process_code"):
            _exec(fn["pre_process_code"], {"vars": self.v, "config": {"body": body}}, name + ".pre")
        tool = self.by_url[props["url"]["default"]]
        data = self.bank.call(tool, body)
        result = {"status": "success", "data": data, "header": {}}
        if fn.get("post_process_code"):
            _exec(fn["post_process_code"], {"vars": self.v, "result": result}, name + ".post")
        for k, val in (result.get("data") or {}).items():
            self.v[f"{name}_response.data.{k}"] = str(val).lower() if isinstance(val, bool) else val
        return result

    def _map(self, mapping, result):
        for m in mapping or []:
            cur = result
            for part in m["path"].split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is not None:
                self.v[m["variable"]] = str(cur).lower() if isinstance(cur, bool) else cur

    def _walk(self, name):
        nodes = self.wf["nodes"]
        for _ in range(400):
            n = nodes[name]
            self.trail.append(name)
            entry = n.get("on_enter") or {}
            if entry.get("type") == "tts" and entry.get("text") and not (n.get("on_enter_first_entry_only") and name in self.entered):
                self.said.append((name, self._fill(entry["text"])))
            self.entered.add(name)
            kind = n["node_type"]
            if kind == "conversation":
                return name
            if kind == "end_call":
                term = (n.get("terminal") or {}).get("function", {}).get("parameters", {}).get("properties", {})
                self.said.append((name, self._fill((term.get("spoken_message") or {}).get("default", ""))))
                for fn in self.wf.get("tools") or []:
                    if (fn.get("config") or {}).get("alwaysRunsAt") == ["end_of_call"]:
                        self._api(fn, fn["function"]["name"])
                self.ended = True
                return name
            if kind == "code":
                _exec(verify.code_of(n), {"vars": self.v}, name)
            else:
                self._map(n.get("response_mapping"), self._api(n["pre_actions"][0], name))
            name = next(t["target_node"] for t in n["transitions"] if holds(t["condition"], self.v))
        raise AssertionError("the call went through 400 nodes without waiting for the customer or ending")

    def _route(self):
        n = self.wf["nodes"][self.node]
        for t in n.get("transitions") or []:
            if t["condition"].get("operator") != "matches_intent" and holds(t["condition"], self.v):
                self.node = self._walk(t["target_node"])
                return self.node
        if n.get("max_turn_transition") and int(self.v.get(self.node + ".total_turns") or 0) >= int(n.get("max_node_turns") or 10 ** 9):
            self.node = self._walk(n["max_turn_transition"])
        return self.node

    # -- what the customer's turn makes the model do
    def turn(self, **extracted):
        """One customer turn in the current step: the extraction writes these values, then the routes are tried."""
        if self.ended:
            return self.node
        key = self.node + ".total_turns"
        self.v[key] = int(self.v.get(key) or 0) + 1
        self.v.update(extracted)
        return self._route()

    def say(self, kind, said="", day="", amount="", about="", question="no", **more):
        """A turn of the negotiation as the orchestrated agent's extraction writes it."""
        return self.turn(reply_kind=kind, said_text=said, day_text=day, amount_text=amount, about_text=about, asks_question=question, **more)

    def tool(self, name, **args):
        """The model calls a tool of the current step (verify_identity, create_promise_2, ...)."""
        n = self.wf["nodes"][self.node]
        fn = next(t for t in n.get("tools") or [] if t["function"]["name"] == name)
        result = self._api(fn, name, args)
        self._map(fn.get("response_mapping"), result)
        self._route()
        return result

    def exits(self):
        """The transitions the model may take in the current step (tool-call transitions)."""
        return [t["target_node"] for t in self.wf["nodes"][self.node].get("transitions") or [] if t.get("is_tool_call")]

    def go(self, part):
        """The model takes the tool-call transition whose target contains `part`."""
        hits = [t for t in self.exits() if part in t]
        if len(hits) != 1:
            raise AssertionError(f"in step {self.node!r}: {len(hits)} transition tool(s) match {part!r} (there are: {self.exits()})")
        self.node = self._walk(hits[0])
        return self.node

    # -- reading the call
    def last(self):
        """The agent's last decided sentence (the orchestrated negotiation says it word for word)."""
        return str(self.v.get("say_text") or "")

    def lines(self, node=None):
        return [text for name, text in self.said if node is None or name == node]

    def everything_said(self):
        return " ".join(self.lines())


def offers(lines):
    """(amount or None, ISO date, weekday right?) of every day a spoken line names: the offers and read-backs, in
    order. A line that names the same day twice ("the latest date is X. Can you pay 10.00 on X?") is one offer."""
    out = []
    for text in lines:
        row = []
        for m in SPOKEN_DAY.finditer(text):
            d = dt.date(int(m.group(4)), MO.index(m.group(3)) + 1, int(m.group(2)))
            before = MONEY.findall(text[:m.start()])
            item = [float(before[-1]) if before else None, d.isoformat(), m.group(1) == WD[d.weekday()]]
            same = next((r for r in row if r[1] == item[1] and (r[0] is None or item[0] is None or r[0] == item[0])), None)
            if same:
                same[0] = same[0] if same[0] is not None else item[0]
                same[2] = same[2] and item[2]
            else:
                row.append(item)
        out += [tuple(r) for r in row]
    return out


# ---------------------------------------------------------------- packs and cases

class Box:
    """A SPEC with its tools: enough to generate the agent and walk calls through it."""

    def __init__(self, name, spec, tools, title=None, tier=1):
        self.name, self.spec, self.tools, self.title, self.tier = name, spec, tools, title or name, tier
        self.cal = Cal(spec)
        self.roles = {x["role"]: x["name"] for x in spec["call_variables"] if x["role"] in ("customer_id", "now")}
        self._wf = {}

    def wf(self, mode, spec=None):
        if spec is not None:
            return generate.build(spec, self.tools, mode)
        if mode not in self._wf:
            self._wf[mode] = generate.build(self.spec, self.tools, mode)
        return self._wf[mode]

    def bank(self, case, spec=None):
        return Bank(spec or self.spec, self.tools, case.get("identity"), case.get("products"), case.get("faults"))

    def sim(self, case, mode="orch", spec=None):
        spec = spec or self.spec
        return Sim(spec, self.tools, self.bank(case, spec), mode, case["now"], case.get("variables"), self.wf(mode, None if spec is self.spec else spec))

    def with_spec(self, spec, name=None):
        """The same documents and tools with another reading of them (an extracted SPEC instead of the oracle)."""
        b = Box(name or self.name, spec, self.tools, self.title, self.tier)
        b.cases = self.cases
        return b

    def cases(self):
        return []


class Pack(Box):
    def __init__(self, name):
        self.dir = HERE / name
        meta = json.loads((self.dir / "pack.json").read_text(encoding="utf-8"))
        self.meta = meta
        self.docs = [self.dir / f for f in meta["docs"]]
        self.api_path = (KIT / meta["api"]) if meta.get("api") else self.dir / "tool-api.json"
        Box.__init__(self, name, json.loads((self.dir / "spec.json").read_text(encoding="utf-8")), ingest.parse_openapi(self.api_path)["tools"], meta["title"], meta.get("tier", 1))

    def text(self):
        return "\n\n".join(ingest.read_text(p)[0] for p in self.docs)

    def cases(self):
        path = (HERE / self.meta["cases_from"] if self.meta.get("cases_from") else self.dir) / "cases.py"
        if not path.exists():
            return []
        mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location(f"cases_{self.name.replace('-', '_')}", path))
        mod.__spec__.loader.exec_module(mod)
        out = mod.cases(self)
        ids = [c["id"] for c in out]
        assert len(ids) == len(set(ids)), f"{self.name}: case ids are not unique"
        return out

def case(cid, title, family, now, steps, outcome, reason=None, promises=(), notes=(), callbacks=(), transfers=(), variables=None, identity=None,
         products=None, faults=None, script="", checks=(), said=(), not_said=(), once=(), offered=None, tier=1, modes=("orch",), calls=None, base=None, note="", free=False):
    """One customer. `steps` is how the walker plays it; `script` and `checks` are the same customer for a
    simulation on the platform (the persona's text and the judge's criteria)."""
    return {"id": cid, "title": title, "family": family, "now": now, "steps": list(steps), "variables": dict(variables or {}),
            "identity": dict(identity or {}), "products": [dict(p) for p in products or []], "faults": dict(faults or {}),
            "script": script, "checks": list(checks), "said": list(said), "not_said": list(not_said), "once": list(once), "offered": offered, "tier": tier,
            "modes": list(modes), "calls": calls, "base": base, "note": note, "free": free,
            "expected": {"outcome": outcome, "reason": reason, "promises": sorted((p, round(float(a), 2), d if isinstance(d, str) else d.isoformat()) for p, a, d in promises),
                         "notes": sorted(((p, r) for p, r in notes), key=str),
                         "callbacks": sorted((d if isinstance(d, str) else d.isoformat(), t) for d, t in callbacks), "transfers": sorted(transfers)}}


# -- the customer of a case

class Customer:
    """A customer in the negotiation who reacts to what the agent just asked, like a persona does: one answer to the
    first ask, then answers to the offers that follow (the last one repeats), and an answer to every read-back.
    An answer is a kind ("accept", "refuse", "too_much", "question", "unclear") or a dict of what the extraction
    would write: {"kind": "propose", "day": "Friday", "amount": "200", "about": "the loan", "said": "..."}.
    `offer` is the answer when a situation's offer is made ("accept", "decline", or a dict for a proposal)."""

    def __init__(self, first, then=("accept",), readback=("accept",), offer="decline"):
        self.first, self.then, self.readback, self.offer = first, list(then), list(readback), offer
        self.n_then = self.n_read = 0
        self.started = False

    def reply(self, sim):
        if sim.spec["confirmation"]["question"] and sim.spec["confirmation"]["question"] in sim.last() and sim.node in ("negotiate", "negotiate_q"):
            self.n_read += 1
            return self.readback[min(self.n_read, len(self.readback)) - 1]
        if not self.started:
            self.started = True
            return self.first
        self.n_then += 1
        return self.then[min(self.n_then, len(self.then)) - 1]


SAID = {"accept": "Yes, that is fine.", "refuse": "No, I cannot do that.", "too_much": "That is too much for me.", "question": "Why is that?",
        "unclear": "Hm.", "vague": "Sometime next week."}


def _event(answer):
    ev = {"kind": answer} if isinstance(answer, str) else dict(answer)
    ev.setdefault("said", SAID.get(ev["kind"], ""))
    return ev


def negotiate(sim, customer, limit=40):
    """Let the customer answer until the call ends or leaves the negotiation."""
    for _ in range(limit):
        if sim.ended:
            return
        if sim.node.startswith("offer_"):
            a = customer.offer
            if isinstance(a, dict):                                # a proposal instead of an answer to the offer
                sim.say(**dict(_event(a), offer_reply="proposal"))
            else:
                sim.turn(offer_reply=a)
        elif sim.node in ("negotiate", "negotiate_q"):
            sim.say(**_event(customer.reply(sim)))
        else:
            return
    sim.problems.append(f"the negotiation did not end within {limit} customer turns (step {sim.node!r}, last sentence {sim.last()[:120]!r})")


def play(sim, c):
    """Play the steps of a case. Returns the sim. A step:
    ("who", value)                      the opening's extraction: "confirmed", "someone_else", a situation id, "" (unclear)
    ("tp", {...})                       a turn with someone else: {"cb_when_text": "tomorrow at ten"} or {"tp_event": "deceased"}
    ("id", field, words[, sent])        the model calls verify_identity with the customer's own words; `sent` is what must reach the bank
    ("decline",) / ("id_question",)     the customer declines the security question / only asks something
    ("go", part)                        the model takes the transition tool whose target contains `part`
    ("neg", Customer)                   the customer negotiates until the call ends
    ("say", {...})                      one scripted negotiation turn
    """
    f = sim.spec["tool_fields"]["verify_identity"]
    for step in c["steps"]:
        if sim.ended:
            sim.problems.append(f"the call had ended before step {step!r}")
            break
        op = step[0]
        if op == "who":
            sim.turn(who=step[1])
        elif op == "tp":
            sim.turn(**step[1])
        elif op == "id":
            if sim.node != "identity":
                sim.problems.append(f"step {step!r}: the call is in {sim.node!r}, not in the identity step")
                break
            before = len(sim.bank.calls)
            sim.v["identity.total_turns"] = int(sim.v.get("identity.total_turns") or 0) + 1
            sim.v["id_reply"] = "answer"
            sim.tool("verify_identity", **{f["field"]: step[1], f["answer"]: step[2]})
            got = sim.bank.calls[before][1].get(f["answer"]) if len(sim.bank.calls) > before else None
            if len(step) > 3 and got != step[3]:
                sim.problems.append(f"{step[1]}: the customer said {step[2]!r}, the bank was sent {got!r}, the brief asks for {step[3]!r}")
        elif op == "decline":
            sim.turn(id_reply="decline")
        elif op == "id_question":
            sim.turn(id_reply="question")
        elif op == "go":
            try:
                sim.go(step[1])
            except AssertionError as e:
                sim.problems.append(str(e))
                break
        elif op == "neg":
            if sim.mode == "v1":                                  # the model negotiates there: the walk ends where it begins
                sim.stopped = True
                if not sim.node.startswith("negotiate_"):
                    sim.problems.append(f"the negotiation was not reached: the call is in {sim.node!r}")
                elif sim.node != "negotiate_" + str(len(c["products"])):
                    sim.problems.append(f"{len(c['products'])} product(s), but the call is in {sim.node!r}")
                break
            if sim.node not in ("negotiate", "negotiate_q"):
                sim.problems.append(f"the negotiation was not reached: the call is in {sim.node!r}")
                break
            negotiate(sim, copy.deepcopy(step[1]))
        elif op == "say":
            sim.say(**_event(step[1]))
        else:
            raise ValueError(step)
    return sim


def verified(P, c_identity, spoken_answers=None):
    """The steps of a customer who confirms and answers every security question correctly, in the brief's order."""
    steps = [("who", "confirmed")]
    for q in P.spec["identity"]["questions"]:
        words = (spoken_answers or {}).get(q["field"], c_identity[q["field"]])
        steps.append(("id", q["field"], words, c_identity[q["field"]]))
    return steps


# -- judging a played case

def judge(P, c, sim, spec=None):
    """Problems of one played case: the ledger against the expected records, the sentences the case names, and
    what must hold in every call of every brief (always())."""
    spec = spec or P.spec
    out = list(sim.problems)
    led, exp = sim.bank.ledger(), c["expected"]
    if sim.stopped or c.get("free"):                              # mode v1 up to the negotiation; or a customer with no single right ending
        if c.get("free") and not sim.ended and not sim.stopped:
            out.append(f"the call did not end (it waits in step {sim.node!r}; last sentence: {sim.last()[:140]!r})")
        return out + always(P, c, sim, spec)
    if not sim.ended:
        out.append(f"the call did not end (it waits in step {sim.node!r}; last sentence: {sim.last()[:140]!r})")
    if (led["outcome"], led["reason"]) != (exp["outcome"], exp["reason"]):
        out.append(f"closed as {led['outcome']} / {led['reason']}, the brief requires {exp['outcome']} / {exp['reason']}")
    for key in ("promises", "notes", "callbacks", "transfers"):
        if led[key] != exp[key]:
            out.append(f"{key}: the bank has {led[key]}, the brief requires {exp[key]}")
    text = sim.everything_said()
    out += [f"never said: {s!r}" for s in c["said"] if s not in text]
    out += [f"said, and must not be: {s!r}" for s in c["not_said"] if s.lower() in text.lower()]
    out += [f"said {text.count(s)} time(s), the brief says once: {s!r}" for s in c["once"] if text.count(s) != 1]
    if c.get("offered") is not None:
        question = sim.spec["confirmation"]["question"]            # the agent's own read-back question
        got = [(a, d) for line in sim.lines("negotiate") if not (question and question in line) for a, d, _ in offers([line])]
        want = [(a, d if isinstance(d, str) else d.isoformat()) for a, d in c["offered"]]
        same = len(got) == len(want) and all(g[1] == w[1] and (g[0] is None or abs(g[0] - w[0]) < 0.005) for g, w in zip(got, want))
        if not same:
            out.append(f"the agent's offers were {got}; the brief's offers, in order: {want}")
    if c.get("calls") is not None:
        for tool, n in c["calls"].items():
            if led["calls"].count(tool) != n:
                out.append(f"{tool} called {led['calls'].count(tool)} time(s), expected {n}")
    return out + always(P, c, sim, spec)


def always(P, c, sim, spec=None):
    """What must hold in every call, whatever the brief and whatever the customer does."""
    spec = spec or P.spec
    cal, led, out = Cal(spec), sim.bank.ledger(), []
    today = day(c["now"])
    out += [f"the bank refused a call: {e}" for e in sim.bank.errors]
    if sim.v.get("neg_error"):
        out.append(f"the negotiation code hit an internal error: {sim.v['neg_error']}")
    if sim.ended:
        if led["calls"].count("close_call") != 1 or led["calls"][-1] != "close_call":
            out.append(f"close_call must be called exactly once, last: {led['calls'][-6:]}")
        table = {r["outcome"]: r["reasons"] for r in spec["outcomes"]["table"]}
        if led["outcome"] not in table:
            out.append(f"outcome {led['outcome']!r} is not in the brief's table")
        elif led["reason"] and led["reason"] not in table[led["outcome"]]:
            out.append(f"reason {led['reason']!r} is not listed for outcome {led['outcome']!r}")
        elif not led["reason"] and table[led["outcome"]] and led["outcome"] not in spec["outcomes"]["reason_omitted_for"]:
            out.append(f"outcome {led['outcome']!r} needs a reason")
    pf = spec["account"]["product_fields"]
    by_id = {p.get(pf["id"], f"p{i + 1}"): p for i, p in enumerate(c.get("products") or [])}
    types = {t["type"]: t for t in spec["account"]["product_types"]}
    seen = set()
    for pid, amount, date in led["promises"]:
        p = by_id.get(pid)
        if p is None or pid in seen:
            out.append(f"promise for {pid!r}: unknown product or a second promise")
            continue
        seen.add(pid)
        full = float(p[pf["past_due"]])
        t = types.get(p[pf["type"]])
        floor = float(p.get(t["floor_field"], full)) if t else full
        lo = min(cal.amount(spec["amounts"]["accept_min"], full, floor), full)
        lowest = min([lo] + [a for a, _ in cal.ladder(p[pf["days_late"]], today, full, floor, True)])
        if not lowest - 0.005 <= amount <= full + 0.005:
            out.append(f"promise for {pid}: {amount:.2f} is outside what the brief accepts ({lowest:.2f} to {full:.2f})")
        if cal.first_day(p[pf["days_late"]], today) is None:
            continue                                               # no day fits the brief's own rules: what then happens is not the brief's to say
        if not cal.allowed(day(date), p[pf["days_late"]], today):
            out.append(f"promise for {pid} on {date}: not a day the brief allows (today {today}, deadline {cal.deadline(p[pf['days_late']], today)}, "
                       f"business day: {cal.biz(day(date))})")
    if led["notes"] and not spec["notes"]["enabled"]:
        out.append(f"notes were added although the brief has none: {led['notes']}")
    for pid, reason in led["notes"]:
        if spec["notes"]["enabled"] and reason not in spec["notes"]["reasons"]:
            out.append(f"note reason {reason!r} is not one of the brief's")
        if pid in seen:
            out.append(f"{pid} has a promise and a note")
    if len(led["notes"]) != len({p for p, _ in led["notes"]}):
        out.append(f"a product was noted twice: {led['notes']}")
    if led["transfers"] and spec["notes"]["enabled"] and spec["notes"]["on_transfer"] == "none" and led["notes"]:
        out.append(f"notes on a transferred call: {led['notes']}")
    if len(led["transfers"]) > 1:
        out.append(f"more than one transfer: {led['transfers']}")
    if len(by_id) == 1 and sim.mode == "orch" and cal.first_day(list(by_id.values())[0][pf["days_late"]], today) is not None:
        # one product, and some day fits the brief's rules: every day the agent itself names must be such a day
        p, question = list(by_id.values())[0], sim.spec["confirmation"]["question"]
        for line in sim.lines("negotiate"):
            if not (question and question in line):
                for a, d, _ in offers([line]):
                    if not cal.allowed(day(d), p[pf["days_late"]], today):
                        out.append(f"the agent itself named {d}, which is not a day a promise can have (today {today}, deadline {cal.deadline(p[pf['days_late']], today)}, "
                                   f"business day: {cal.biz(day(d))})")
    lines = sim.lines()
    named = any(isinstance(a, dict) and a.get("day") for st in c.get("steps") or [] if st[0] == "neg"
                for a in [st[1].first] + list(st[1].then) + list(st[1].readback) + [st[1].offer])
    # on a day no promise can have, a yes to "today" names today: then the sentence is right
    named = named or any(cal.first_day(p[pf["days_late"]], today) != today for p in by_id.values())
    for text in lines:
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
            out.append(f"a spoken line reads a date as digits: {text[:160]!r}")
        if not named and re.search(r"\b(that|this) day is not possible\b", text, re.I):
            out.append(f"the agent said a day is not possible although the customer named none: {text[:160]!r}")
        if "{" in text or "}" in text:
            out.append(f"a spoken line still has a placeholder: {text[:160]!r}")
        if re.search(r"\bNone\b|\bnan\b|\[\]|_response", text):
            out.append(f"a spoken line shows a raw value: {text[:160]!r}")
    for a, d, weekday_ok in offers(lines):
        if not weekday_ok:
            out.append(f"a spoken date has the wrong weekday: {d}")
    ok_say = spec["recording"]["after_success_say"].strip()
    if ok_say and (ok_say in sim.everything_said()) != bool(led["promises"]):
        out.append(f"the sentence after a recorded promise ({ok_say!r}) was " + ("not said although a promise was recorded" if led["promises"] else "said although no promise was recorded"))
    if not led["promises"] and re.search(r"\b(is|are|was|were|has been|have been) (now )?(recorded|saved|booked)\b", " ".join(text for name, text in sim.said if name != "opening"), re.I):
        out.append("a spoken line claims something was recorded although no promise was")
    return out


def score_like_the_kit(c, led):
    """The case and the ledger in the shape tools/score.py reads (for packs that keep the kit's field names)."""
    exp = c["expected"]
    case_ = {"expected": {"outcome": exp["outcome"], "reason": exp["reason"], "promises": [{"product_id": p, "amount": a, "date": d} for p, a, d in exp["promises"]],
                          "notes": [{"product_id": p, "reason": r} for p, r in exp["notes"]], "callbacks": [{"date": d, "time": t} for d, t in exp["callbacks"]],
                          "transfers": [{"queue": q} for q in exp["transfers"]]}}
    return case_


def packs(only=None, distinct=False):
    """The packs, by folder name or first letter. distinct: without the packs that say another pack's rules in another form."""
    names = sorted(p.name for p in HERE.iterdir() if (p / "pack.json").exists())
    out = [Pack(n) for n in names if not only or n in only or n.split("-")[0] in only]
    return [p for p in out if not (distinct and p.meta.get("same_rules_as"))]


MONTHS_SPOKEN = {"01-01": "New Year's Day", "12-25": "Christmas Day"}


def anchors(P):
    """Names, dates and sentences of the oracle SPEC that the pack's documents must carry as written: [missing]."""
    text, spec, miss = P.text(), P.spec, []
    everywhere = text + "\n" + P.api_path.read_text(encoding="utf-8")       # field and type names live in the tool API file
    said = lambda sentence: sentence.strip().rstrip(".?!").lower() in text.lower()
    names = [r["outcome"] for r in spec["outcomes"]["table"]] + [x for r in spec["outcomes"]["table"] for x in r["reasons"]]
    names += [q["field"] for q in spec["identity"]["questions"]] + [h["value"] for h in spec["identity"]["hints"]] + [t["type"] for t in spec["account"]["product_types"]]
    names += [v["name"] for v in spec["call_variables"]] + list(spec["notes"]["reasons"])
    for x in spec["situations"]:
        for eff in [x["effect"]] + ([x["offer"]["on_accept"], x["offer"]["on_decline"]] if x.get("offer") else []):
            names += [a["queue"] for a in eff["actions"] if a["type"] == "transfer"]
    miss += [f"the name {n!r}" for n in dict.fromkeys(names) if n not in everywhere]
    for h in spec["calendar"]["holidays"]:
        d = day(h)
        forms = [h, f"{d.day} {MO[d.month - 1]} {d.year}"]
        loose = (f"{d.day} and" in text or f"and {d.day} {MO[d.month - 1]}" in text or MONTHS_SPOKEN.get(h[5:], "~") in text) and (f"{MO[d.month - 1]} {d.year}" in text or str(d.year) in text)
        if not any(f in text for f in forms) and not loose:
            miss.append(f"the holiday {h}")
    for path in P.meta.get("exact") or []:
        node = spec
        for part in path.split("."):
            node = node[part]
        if node and not said(node):
            miss.append(f"the sentence {path}: {node!r}")
    miss += [f"the sentence of situation {x['id']}: {x['say']!r}" for x in spec["situations"] if x["say_exact"] and x["say"] and not said(x["say"])]
    return miss
