"""Customers every brief of this kind has, built from a SPEC alone: the one who pays today, the one who refuses
everything, the one who says it is too much, the one who names a date that is too late or a day that is no business
day, the one whose promise cannot be saved, one for every special situation the SPEC lists, the relative who offers
a callback, the person who never confirms, and the one who fails or declines the security questions.

    for c in universal.cases(box, "2026-10-14"): sim = lib.play(box.sim(c), c); problems = lib.judge(box, c, sim)

The expected records come from a small reading of the SPEC's own rules (lib.Cal for dates and amounts, the outcome
table for the close), never from the generator. A customer whose right answer the SPEC leaves open is not made;
what must hold in every call (lib.always) is checked for all of them. This is what lets a hand-changed SPEC (see
variants.py) or an extracted one be tried in seconds, on any calendar day.
"""
import datetime as dt, re
from lib import ONE, Customer, case, day

PH = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
COUNT = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def identity_for(spec):
    """A right answer for every security question, in the form its type and description ask for."""
    out = {}
    for q in spec["identity"]["questions"]:
        kind, how = q["value_type"], (q["answer_format"] + " " + q["conversion"]).lower()
        if kind == "date":
            out[q["field"]] = "1988-03-14"
        elif kind == "year":
            out[q["field"]] = "1988"
        elif kind in ("digits", "number"):
            m = re.search(r"\b(\d{1,2}|" + "|".join(COUNT) + r")[- ](?:digits?|numbers?|figures?)", how)
            n = (int(m.group(1)) if m.group(1).isdigit() else COUNT[m.group(1)]) if m else 4
            out[q["field"]] = "0812345679"[:n] if n >= 6 else "4471638205"[:n]
        else:
            out[q["field"]] = "AB12CD"
    return out


def wrong_for(spec, field):
    kind = next(q["value_type"] for q in spec["identity"]["questions"] if q["field"] == field)
    right = identity_for(spec)[field]
    return {"date": "1970-01-01", "year": "1901"}.get(kind, "ZZ99ZZ" if kind == "text" else "1" * len(right))


def products_for(spec, n=1, start=0):
    """n products, one per band in turn (from band `start`) and one per product type in turn."""
    pf, types, bands = spec["account"]["product_fields"], spec["account"]["product_types"], spec["bands"]
    out = []
    for i in range(n):
        b = bands[(start + i) % len(bands)] if bands else None
        t = types[(start + i) % len(types)]
        p = {pf["id"]: f"x{i + 1}", pf["type"]: t["type"], pf["past_due"]: [1250.5, 840.0, 2125.1][i % 3], pf["days_late"]: min(b["days_late_max"], b["days_late_min"] + 1) if b else 10}
        if t["floor_field"] != pf["past_due"]:
            p[t["floor_field"]] = [300.25, 210.0, 637.5][i % 3]
        for name in PH.findall(t["spoken_name"]):
            p.setdefault(name, "4821")
        out.append(p)
    return out


def cases(B, today, tag="", clock="{d}T11:00"):
    spec, cal, out = B.spec, B.cal, []
    T = day(today) if isinstance(today, str) else today
    now = clock.format(d=T.isoformat())
    pf, types = spec["account"]["product_fields"], {t["type"]: t for t in spec["account"]["product_types"]}
    ident = identity_for(spec)
    variables = {v["name"]: {"title": "Ms", "salutation": "Ms"}.get(v["name"], "Avery") for v in spec["call_variables"] if v["role"] not in ("customer_id", "now")}
    V = [("who", "confirmed")] + [("id", q["field"], ident[q["field"]], ident[q["field"]]) for q in spec["identity"]["questions"]]
    am, dts, neg, rec, notes_on = spec["amounts"], spec["dates"], spec["negotiation"], spec["recording"], spec["notes"]["enabled"]
    ex, table = neg["attempts_exhausted"], {r["outcome"]: r["reasons"] for r in spec["outcomes"]["table"]}
    rule = spec["outcomes"].get("multi") if notes_on else None
    multi = spec["multi_product"]["enabled"] and int(spec["account"]["max_products"]) > 1

    def C(cid, title, steps, outcome, reason=None, products=None, **kw):
        out.append(case(f"U-{tag}{cid}", title, "Universal", now, steps, outcome, reason or None, variables=variables, identity=ident,
                        products=products if products is not None else products_for(spec), **kw))

    def facts(p):
        t = types[p[pf["type"]]]
        full = float(p[pf["past_due"]])
        return p[pf["id"]], full, min(float(p.get(t["floor_field"], full)), full), p[pf["days_late"]]

    def close_without_promise(reasons, fallback):
        """How a call with no promise closes when every product ended for one of `reasons` (in product order)."""
        if rule:
            if all(r == rule["all_notes_match"]["note_reason"] for r in reasons):
                return rule["all_notes_match"]["outcome"], rule["all_notes_match"]["reason"] or None
            return rule["otherwise"]["outcome"], next(r for r in reasons if r != rule["all_notes_match"]["note_reason"])
        return fallback

    def sound(ps):
        """Every product has a band, a day a promise can have, and persuasion offers on allowed days."""
        for p in ps:
            pid, full, floor, days = facts(p)
            if cal.band(days) is None or cal.first_day(days, T) is None:
                return False
            if any(not cal.allowed(d, days, T) for _, d in cal.ladder(days, T, full, floor)):
                return False
        return True

    first_amount = lambda full, floor: min(cal.amount(am["first_offer"], full, floor), full)
    exhausted_note = ex.get("note_reason") or ex["reason"]
    sets = [(f"band{i + 1}", products_for(spec, 1, i)) for i in range(len(spec["bands"]))]
    if multi:
        sets.append(("all", products_for(spec, min(int(spec["account"]["max_products"]), max(2, len(spec["bands"]))), 0)))

    for key, ps in sets:
        if not sound(ps):                                          # no single right ending: only what must hold in every call is checked
            C(f"pay-{key}", f"Pays what is asked ({key}; a product without a band, without a possible day, or with an offer on a day no promise can have)",
              V + [("neg", Customer("accept"))], "", products=ps, free=True)
            C(f"refuse-{key}", f"Refuses everything ({key}; as above)", V + [("neg", Customer("refuse", then=["refuse"]))], "", products=ps, free=True)
            continue
        # ---- pays today
        C(f"pay-{key}", f"Pays what is asked, as early as a promise can be ({key})", V + [("neg", Customer("accept"))], spec["outcomes"]["promise"]["outcome"],
          spec["outcomes"]["promise"]["reason"], products=ps, promises=[(facts(p)[0], first_amount(*facts(p)[1:3]), cal.first_day(facts(p)[3], T)) for p in ps],
          calls={"create_promise": len(ps), "transfer_to_agent": 0})
        # ---- refuses everything
        want = []
        limit = int(neg.get("call_attempt_limit") or 0)
        per_product = spec["multi_product"]["attempts_per_product"] or not multi
        for p in ps:
            pid, full, floor, days = facts(p)
            lad = cal.ladder(days, T, full, floor)
            want += lad if per_product else lad[:max(0, limit - len(want))]
        note_each = notes_on and spec["notes"]["for_each_product_without_promise"]
        outcome, reason = close_without_promise([exhausted_note] * len(ps), (ex["outcome"], ex["reason"]))
        C(f"refuse-{key}", f"Refuses everything ({key})", V + [("neg", Customer("refuse", then=["refuse"]))], outcome, reason, products=ps,
          notes=[(facts(p)[0], exhausted_note) for p in ps] if note_each else [], offered=want if (per_product or limit) else None,
          calls={"create_promise": 0, "transfer_to_agent": 0})
    for key, ps in sets[:len(spec["bands"])]:
        if not sound(ps):
            continue
        pid, full, floor, days = facts(ps[0])
        dl, first = cal.deadline(days, T), cal.first_day(days, T)
        promise = (spec["outcomes"]["promise"]["outcome"], spec["outcomes"]["promise"]["reason"])
        # ---- the amount is too much
        if int(am["too_much"]["times"]) >= 1:
            low = min(cal.amount(am["too_much"]["offer"], full, floor), full)
            C(f"toomuch-{key}", f"Says the amount is too much, takes what is offered instead ({key})", V + [("neg", Customer("too_much", then=["accept"]))], *promise,
              products=ps, promises=[(pid, low, first)], once=[am["too_much"]["say"]] if am["too_much"]["say"] and low < first_amount(full, floor) else [])
        # ---- a date after the deadline
        if dl and dts["after_deadline"] == "offer_deadline" and cal.allowed(dl, days, T):
            C(f"late-{key}", f"Names a date after the deadline, takes the deadline ({key})",
              V + [("neg", Customer({"kind": "propose", "day": (dl + dt.timedelta(days=10)).isoformat(), "said": "I can pay then."}, then=["accept"]))], *promise,
              products=ps, promises=[(pid, first_amount(full, floor), dl)])
        # ---- a day that is no business day
        if dl and dts["business_day_only"] and dts["non_business_day"] == "offer_next_business_day":
            off = next((T + ONE * i for i in range(1, 40) if not cal.biz(T + ONE * i) and cal.next_biz(T + ONE * i) <= dl and T + ONE * i >= cal.earliest(T)), None)
            if off:
                C(f"offday-{key}", f"Names a day that is no business day, takes the next one ({key})",
                  V + [("neg", Customer({"kind": "propose", "day": off.isoformat(), "said": "I can pay then."}, then=["accept"]))], *promise,
                  products=ps, promises=[(pid, first_amount(full, floor), cal.next_biz(off))])
    ps = sets[0][1] if sets and sound(sets[0][1]) else None
    if ps:
        pid, full, floor, days = facts(ps[0])
        # ---- the promise cannot be saved
        fail = rec["on_final_failure"]
        fail_note = fail.get("note_reason") if notes_on else None
        outcome, reason = close_without_promise([fail_note], (fail["outcome"], fail["reason"])) if fail_note else (fail["outcome"], fail["reason"])
        C("norecord", "Agrees, but the promise cannot be saved", V + [("neg", Customer("accept"))], outcome, reason, products=ps, faults={"create_promise": 99},
          notes=[(pid, fail_note)] if fail_note else [], said=[rec["failure_say"]] if rec["failure_say"] else [], calls={"create_promise": max(1, int(rec["max_attempts"]))})
        # ---- one customer per special situation of the negotiation
        for x in spec["situations"]:
            if "negotiation" not in x["stages"]:
                continue
            words = " ".join(x.get("evidence_words") or [])
            say = {"kind": x["id"], "said": (x["trigger"] + " " + words).strip()}
            by = (x["effect"].get("outcome_by_stage") or {}).get("after_identity")

            def effect_of(eff, with_stage=None):
                o = with_stage or eff
                acts = eff["actions"]
                return {"outcome": o["outcome"], "reason": o["reason"] or None, "transfers": [a["queue"] for a in acts if a["type"] == "transfer"],
                        "notes": [(pid, a["note_reason"]) for a in acts if a["type"] == "note"] if notes_on else [], "callback": any(a["type"] == "callback" for a in acts)}
            if x["scope"] == "product" and notes_on and any(a["type"] == "note" for a in x["effect"]["actions"]):
                r = next(a["note_reason"] for a in x["effect"]["actions"] if a["type"] == "note")
                outcome, reason = close_without_promise([r], (x["effect"]["outcome"], x["effect"]["reason"] or None))
                C(f"sit-{x['id']}", f"Situation {x['id']} on the only product: noted, no promise", V + [("neg", Customer(say))], outcome, reason, products=ps, notes=[(pid, r)],
                  said=[x["say"]] if x["say_exact"] and x["say"] else [], calls={"create_promise": 0, "transfer_to_agent": 0})
                continue
            if x.get("offer"):
                for answer, eff in (("accept", x["offer"]["on_accept"]), ("decline", x["offer"]["on_decline"])):
                    e = effect_of(eff)
                    if answer == "decline" and e["notes"]:
                        e["outcome"], e["reason"] = close_without_promise([e["notes"][0][1]], (e["outcome"], e["reason"]))
                    C(f"sit-{x['id']}-{answer}", f"Situation {x['id']}: the offer is {answer}ed", V + [("neg", Customer(say, offer=answer))], e["outcome"], e["reason"], products=ps,
                      transfers=e["transfers"], notes=[] if e["transfers"] and spec["notes"]["on_transfer"] == "none" else e["notes"], calls={"create_promise": 0})
                continue
            e = effect_of(x["effect"], by)
            steps = V + [("neg", Customer(say, then=[say]))]
            callbacks = []
            if e["callback"]:
                slot = good_slot(cal, spec, T)
                if not slot:
                    continue
                steps.append(("tp", {"cb_when_text": f"{slot[0].isoformat()} at {slot[1]}"}))
                callbacks = [slot]
            notes = [] if e["transfers"] and spec["notes"]["on_transfer"] == "none" else e["notes"]
            if notes and not e["transfers"] and rule and x["scope"] == "call":
                pass                                               # a call-scope close keeps its own outcome; the notes are only written
            C(f"sit-{x['id']}", f"Situation {x['id']}" + (f", said {x['threshold']} times" if x["threshold"] > 1 else ""), steps, e["outcome"], e["reason"], products=ps,
              transfers=e["transfers"], notes=notes, callbacks=callbacks, said=[x["say"]] if x["say_exact"] and x["say"] else [], calls={"create_promise": 0})

    # ---- nobody confirms; someone else answers; the security questions
    o, tp, idn = spec["opening"], spec["third_party"], spec["identity"]
    C("unclear", f"Never confirms who is speaking: {o['max_asks']} ask(s)", [("who", "")] * max(1, int(o["max_asks"])), o["unclear"]["outcome"], o["unclear"]["reason"],
      products=[], calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
    if tp["enabled"] and tp["callback"]["enabled"]:
        cb, slot = tp["callback"], good_slot(cal, spec, T)
        if slot:
            C("callback", "Someone else answers and offers a time that fits", [("who", "someone_else"), ("tp", {"cb_when_text": f"{slot[0].isoformat()} at {slot[1]}"})],
              cb["scheduled"]["outcome"], cb["scheduled"]["reason"], products=[], callbacks=[slot], calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
        far = (T + dt.timedelta(days=45)).isoformat() + " at 10:30"
        C("nocallback", f"Someone else answers and offers a day that is too far, {cb['max_asks']} time(s)",
          [("who", "someone_else")] + [("tp", {"cb_when_text": far})] * max(1, int(cb["max_asks"])), cb["not_scheduled"]["outcome"], cb["not_scheduled"]["reason"], products=[],
          calls={"schedule_callback": 0, "verify_identity": 0}, modes=("orch", "v1"))
    for x in spec["situations"]:
        if x.get("offer") or x["threshold"] > 1:
            continue
        before = (x["effect"].get("outcome_by_stage") or {}).get("before_identity") or x["effect"]
        acts = x["effect"]["actions"]
        if any(a["type"] == "callback" for a in acts):
            continue
        queues = [a["queue"] for a in acts if a["type"] == "transfer"]
        if "opening" in x["stages"]:
            C(f"open-{x['id']}", f"Situation {x['id']}, said to the opening question", [("who", x["id"])], before["outcome"], before["reason"], products=[], transfers=queues,
              said=[x["say"]] if x["say_exact"] and x["say"] else [], calls={"verify_identity": 0, "get_account": 0}, modes=("orch", "v1"))
        if "third_party" in x["stages"] and tp["enabled"]:
            C(f"tp-{x['id']}", f"Situation {x['id']}, said by someone else", [("who", "someone_else"), ("tp", {"tp_event": x["id"]})], before["outcome"], before["reason"],
              products=[], transfers=queues, said=[x["say"]] if x["say_exact"] and x["say"] else [], calls={"verify_identity": 0}, modes=("orch", "v1"))
    for x in spec["situations"]:
        if "identity" not in x["stages"]:
            continue
        before = (x["effect"].get("outcome_by_stage") or {}).get("before_identity") or x["effect"]
        acts = x["effect"]["actions"]
        steps, callbacks = [("who", "confirmed"), ("go", x["id"])], []
        if any(a["type"] == "callback" for a in acts):
            slot = good_slot(cal, spec, T)
            if not slot:
                continue
            steps.append(("tp", {"cb_when_text": f"{slot[0].isoformat()} at {slot[1]}"}))
            callbacks = [slot]
        C(f"id-{x['id']}", f"Situation {x['id']}, before the security questions are passed", steps, before["outcome"], before["reason"], products=[],
          transfers=[a["queue"] for a in acts if a["type"] == "transfer"], callbacks=callbacks, calls={"get_account": 0, "add_note": 0}, modes=("orch", "v1"))
    if idn["questions"]:
        first = idn["questions"][0]["field"]
        if idn["wrong_may_retry"]:
            C("idfail", f"{idn['max_wrong_total']} wrong answer(s) end the check", [("who", "confirmed")] + [("id", first, wrong_for(spec, first))] * max(1, int(idn["max_wrong_total"])),
              idn["on_failed"]["outcome"], idn["on_failed"]["reason"], products=products_for(spec), said=[idn["on_failed"]["say"]] if idn["on_failed"]["say"] else [],
              calls={"get_account": 0}, modes=("orch", "v1"))
        C("iddecline", f"Declines the security questions {idn['decline']['max_declines']} time(s)", [("who", "confirmed")] + [("decline",)] * max(1, int(idn["decline"]["max_declines"])),
          idn["decline"]["outcome"], idn["decline"]["reason"], products=products_for(spec), calls={"get_account": 0, "verify_identity": 0}, modes=("orch", "v1"))
        C("idpass", "Passes the security questions: the account is read and the negotiation begins", V + [("neg", Customer("accept"))], spec["outcomes"]["promise"]["outcome"],
          spec["outcomes"]["promise"]["reason"], products=products_for(spec), modes=("v1",))
    return out


def good_slot(cal, spec, T):
    """(day, HH:MM) of a callback the SPEC allows, for a call at 11:00: half an hour into the window, later than now."""
    cb = spec["third_party"]["callback"]
    if not cb["enabled"]:
        return None
    start = int(cb["window_start"][:2]) * 60 + int(cb["window_start"][3:])
    for d in cal.callback_days(T):
        for plus in (30, 15, 5, 60, 120, 240, 0):
            mins = max(start + plus, 11 * 60 + 30) if d == T else start + plus
            hhmm = "%02d:%02d" % (mins // 60, mins % 60)
            if mins < 24 * 60 and cal.callback_ok(d, hhmm, dt.datetime.combine(T, dt.time(11, 0))):
                return (d, hhmm)
    return None
