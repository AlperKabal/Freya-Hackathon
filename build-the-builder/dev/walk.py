"""Walk a generated workflow without the platform: code nodes run, engine-run bank calls are recorded, and each
customer turn is given as the values the extraction would write.

    from walk import Call
    c = Call(spec, tools, products, mode="orch", now="2026-10-16T09:30")     # from the account step on
    c.say("refuse", "No, I can't.")           # one customer turn -> the node the call is in afterwards
    c.v["say_text"], c.calls, c.v["outcome"]

This is how a calendar day, a product mix or a customer the practice set does not have can be tried in seconds: what
the orchestrated agent decides is code, so it can be checked here; what the model says cannot.
"""
import json, pathlib, re, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from builder import generate, verify

VAR = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_.]*)(?::json)?\}\}")


def holds(c, v):
    """A transition condition, evaluated like the platform's deterministic operators."""
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
    return False                                              # matches_intent is a model's judgment: never taken here


class Call:
    """One call from the account step on. `answers` maps a tool name to the data the bank returns for it (a dict, or
    a list of dicts used one per call); without an entry every bank call succeeds."""

    def __init__(self, spec, tools, products, mode="orch", now="2026-10-14T11:00", variables=None, answers=None, wf=None):
        self.spec = spec
        self.wf = wf or generate.build(spec, tools, mode)
        self.by_url = {t["url"]: name for name, t in tools.items()}
        now_var = next(x["name"] for x in spec["call_variables"] if x["role"] == "now")
        cust = next(x["name"] for x in spec["call_variables"] if x["role"] == "customer_id")
        self.v = {now_var: now, cust: "c_test"}
        self.v.update(variables or {})
        self.calls, self.said, self.answers = [], [], {k: (list(a) if isinstance(a, list) else a) for k, a in (answers or {}).items()}
        self.run("setup")
        self.v["acct_items"] = products
        self.node = self.walk("prepare_deal")

    def run(self, name):
        exec(verify.code_of(self.wf["nodes"][name]), {"vars": self.v})

    def walk(self, name):
        for _ in range(300):
            n = self.wf["nodes"][name]
            entry = n.get("on_enter") or {}
            if entry.get("type") == "tts" and entry.get("text"):
                self.said.append(VAR.sub(lambda m: str(self.v.get(m.group(1), m.group(0))), entry["text"]))
            if n["node_type"] in ("conversation", "end_call"):
                return name
            if n["node_type"] == "code":
                self.run(name)
            else:
                fn = n["pre_actions"][0]
                props = fn["function"]["parameters"]["properties"]
                body = {}
                for field, p in props["body"]["properties"].items():
                    d = p.get("default")
                    m = VAR.fullmatch(d) if isinstance(d, str) else None
                    if m and self.v.get(m.group(1)) is None:
                        continue                              # an unresolved single placeholder: the field is dropped
                    body[field] = self.v[m.group(1)] if m else d
                if fn.get("pre_process_code"):
                    exec(fn["pre_process_code"], {"vars": self.v, "config": {"body": body}})
                tool = self.by_url[props["url"]["default"]]
                self.calls.append((tool, body))
                data = self.answers.get(tool, {"ok": True})
                if isinstance(data, list):
                    data = data.pop(0) if data else {"ok": True}
                for m in n.get("response_mapping") or []:
                    cur = {"data": data}
                    for part in m["path"].split("."):
                        cur = cur.get(part) if isinstance(cur, dict) else None
                    if cur is not None:
                        self.v[m["variable"]] = str(cur).lower() if isinstance(cur, bool) else cur
            name = next(t["target_node"] for t in n["transitions"] if holds(t["condition"], self.v))
        raise AssertionError("the walk did not reach a conversation or end node")

    def say(self, kind, said="", day="", amount="", about="", question="no"):
        """One customer turn in the current conversation node, as the extraction would write it."""
        key = self.node + ".total_turns"
        self.v[key] = int(self.v.get(key) or 0) + 1
        self.v.update(reply_kind=kind, said_text=said, day_text=day, amount_text=amount, about_text=about, asks_question=question)
        self.node = self.walk("neg_eval")
        return self.node

    def state(self):
        return json.loads(self.v.get("nst") or "{}")

    def of(self, tool):
        return [b for name, b in self.calls if name == tool]

    def promises(self):
        """(product id, amount, date) of every promise the bank was sent, as the scorer compares them."""
        f = self.spec["tool_fields"]["create_promise"]
        return sorted((b.get(f["product_id"]), round(float(b.get(f["amount"])), 2), b.get(f["date"])) for b in self.of("create_promise"))

    def notes(self):
        f = self.spec["tool_fields"]["add_note"]
        return sorted((b.get(f["product_id"]), b.get(f["reason"])) for b in self.of("add_note"))

    def closed(self):
        return (self.v.get("outcome"), self.v.get("reason") or None)
