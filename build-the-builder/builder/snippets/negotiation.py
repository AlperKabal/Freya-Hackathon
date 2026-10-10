"""The negotiation as a state machine: code decides which product is discussed, which offer is made and when a
product is done; the model only says the sentence. Runs unchanged in the platform sandbox (embedded after the
dates snippet, which it uses) and locally in tests. Only json, re, datetime; no double braces; never raises.

    state = new_state(plan)                      # plan: one dict per product, built by the account code node
    state, say, nxt = step(state, event, plan, today, CFG)
    event: {"kind": ..., "day": words, "amount": words, "about": words}   (kind from the extraction enum)
    nxt: "talk" (say it and wait) | "record" (the customer confirmed the read-back) | "close" (nothing agreed)
A say text that starts with ASK_FIRST: means: answer the customer's question in one sentence, then say the rest.

A special situation that cannot be undone (a transfer, the end of the call) is checked before it acts:
    ok = situation_confirmed(kind, said, state, words)      # words: the SPEC's evidence words of that situation
When the customer's own words do not carry it, the turn goes through step() as the kind UNCONFIRMED instead.
"""

UNCONFIRMED = "unconfirmed"      # an event kind only code writes: the extraction named a situation the words did not carry

_SMALL = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
          "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ALL = _re.compile(r"\b(all|every|everything|both|them|each|three|two)\b")


def _words_value(words):
    total, cur, seen = 0, 0, False
    for w in words:
        if w in _SMALL:
            cur += _SMALL[w]; seen = True
        elif w == "hundred":
            cur = (cur or 1) * 100; seen = True
        elif w in ("thousand", "million"):
            total += (cur or 1) * (1000 if w == "thousand" else 1000000); cur = 0; seen = True
        elif w in ("and", "a"):
            continue
        else:
            break
    return (total + cur) if seen else None


def parse_amount(text):
    """'four hundred and fifty-five' -> 455.0, '153.50' -> 153.5, '1,320' -> 1320.0, 'one twenty five' -> 125.0,
    '637 pounds 50' -> 637.5. None if no amount."""
    t = str(text or "").lower().replace(",", "").replace("-", " ")
    m = _re.search(r"\b(\d+(?:\.\d{1,2})?)\b", t)
    if m:
        v = float(m.group(1))
        cents = _re.search(r"\d+\s*(?:pounds?|euros?|dollars?|lira)\s*(?:and\s*)?\b(\d{1,2})\b", t)
        if cents and "." not in m.group(1):
            v += int(cents.group(1)) / 100.0
        return round(v, 2)
    words = _re.findall(r"[a-z]+", t)
    for i, w in enumerate(words):
        if w in _SMALL or w in ("hundred", "thousand"):
            seq = words[i:]
            point = seq.index("point") if "point" in seq else None
            head = seq[:point] if point is not None else []
            if point is None:
                for j, x in enumerate(seq):
                    if x not in _SMALL and x not in ("hundred", "thousand", "and", "a"):
                        head = seq[:j]
                        break
                else:
                    head = seq
            whole = _words_value(head)
            if whole is None:
                return None
            if len(head) >= 2 and head[0] in _SMALL and head[1] in _SMALL and _SMALL[head[1]] >= 10:
                if _SMALL[head[0]] < 10 or (10 <= _SMALL[head[0]] <= 99):
                    whole = _SMALL[head[0]] * 100 + (_words_value(head[1:]) or 0)          # "one twenty five" = 125, "twelve fifty" = 1250
            frac = 0.0
            if point is not None:
                digits = [str(_SMALL[x]) for x in seq[point + 1:point + 3] if x in _SMALL and _SMALL[x] < 10]
                frac = float("0." + "".join(digits)) if digits else 0.0
            else:
                tail = seq[len(head):]
                cents_head = []
                for x in tail:
                    if x in _SMALL: cents_head.append(x)
                    elif cents_head and x not in ("and", "a", "cents", "cent", "pence", "pennies", "penny"): break
                if cents_head:
                    cv = _words_value(cents_head)
                    if cv is not None and cv < 100:
                        frac = cv / 100.0
            return round(whole + frac, 2)
    return None
    return None


def money(x):
    return "%.2f" % float(x)


def _plain(text):
    """Lower case, letters and digits only, a doubled letter as one: spelling variants of a word compare equal."""
    t = _re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    return _re.sub(r"([a-z])\1+", r"\1", t)


def has_evidence(said, words):
    """Do the customer's own words contain one of the evidence words (a word stem or a phrase, at the start of a word)?"""
    t = " " + _plain(said)
    for w in words or []:
        w = _plain(w)
        if w and (" " + w) in t:
            return True
    return False


def situation_confirmed(kind, said, state, words):
    """May the special situation the extraction named act now? Code overrules the extraction only on evidence:
    with no evidence words, or without the customer's words, the extraction stands. With the words at hand and none
    of the evidence words in them, the first time is not acted on; the second time the customer insists and it is."""
    if not words or not _plain(said):
        return True
    if has_evidence(said, words):
        return True
    weak = state.setdefault("weak", dict())
    weak[kind] = int(weak.get(kind, 0)) + 1
    return weak[kind] >= 2


def _answer_first(say, nxt):
    return ("ASK_FIRST: " + say) if (nxt == "talk" and say) else say


def new_state(plan):
    return {"phase": "today", "cursor": 0, "pending_amount": None,
            "p": [{"status": "open", "attempt": 0, "too_much": False, "floor_offered": False, "vague_asks": 0, "below_asks": 0,
                   "offer_amt": pp["full"], "offer_date": pp["today"], "amt": None, "date": None, "note": "", "clamped": False} for pp in plan]}


def _open(state):
    return [i for i, x in enumerate(state["p"]) if x["status"] == "open"]


def _day(pp, iso):
    return pp["spoken"].get(iso, iso)


def _offer_text(pp, x, cfg, new_floor=False):
    """The floor amount is named once (with the SPEC's sentence); later offers of it name only the date."""
    if x["offer_amt"] < pp["full"] and x["floor_offered"] and not new_floor:
        return "Could you make that payment for your " + pp["name"] + " on " + _day(pp, x["offer_date"]) + "?"
    s = "Can you pay " + money(x["offer_amt"]) + " for your " + pp["name"] + " on " + _day(pp, x["offer_date"]) + "?"
    if x["offer_amt"] < pp["full"] and cfg.get("too_much_say"):
        s += " " + cfg["too_much_say"]
        x["floor_offered"] = True
    return s


def _ladder_offer(pp, x):
    """Set the product's next persuasion offer; False when its attempts are used up."""
    if x["attempt"] >= len(pp["ladder"]):
        return False
    st = pp["ladder"][x["attempt"]]
    x["attempt"] += 1
    amt = st["amount"]
    if st["kind"] == "full_or_floor_if_too_much":
        amt = pp["floor"] if x["too_much"] else pp["full"]
    x["offer_amt"], x["offer_date"] = amt, st["date"]
    return True


def _end(x, reason):
    x["status"], x["note"] = "ended", reason


def _agree(x, amt, date):
    x["status"], x["amt"], x["date"] = "agreed", amt, date


def _check_day(day_iso, pp, today, cfg):
    """SPEC date rules for one product -> (date to use or None, changed, why)."""
    dl = _dt.date.fromisoformat(pp["deadline"]) if pp["deadline"] else None
    v = check_promise_date(_dt.date.fromisoformat(day_iso), today, dl, cfg)
    if v["verdict"] == "ok":
        return v["date"], False, ""
    if v["verdict"] == "offer":
        return v["date"], True, v["why"]
    return None, True, v["why"]


def _which(about, plan, default):
    """The product the customer talks about, by the words of its spoken name; else `default`."""
    a = str(about or "").lower()
    if a:
        best, score = default, 0
        for i, pp in enumerate(plan):
            words = [w for w in _re.findall(r"[a-z0-9]+", pp["name"].lower()) if len(w) > 2]
            hit = sum(1 for w in words if w in a)
            if hit > score:
                best, score = i, hit
        return best
    return default


def _to_all(about, multi):
    return multi and bool(_ALL.search(str(about or "").lower()))


def _next_product(state, plan, cfg):
    """Move to the next open product and make its first persuasion offer; or go to the read-back / close."""
    while True:
        op = _open(state)
        if not op:
            return _finish(state, plan, cfg)
        i = op[0]
        state["cursor"] = i
        x, pp = state["p"][i], plan[i]
        if _ladder_offer(pp, x):
            return "talk", _offer_text(pp, x, cfg)
        _end(x, cfg["exhausted_note"])


def _finish(state, plan, cfg):
    agreed = [i for i, x in enumerate(state["p"]) if x["status"] == "agreed"]
    if not agreed:
        state["phase"] = "closed"
        return "close", ""
    state["phase"] = "confirm"
    parts = []
    for i in agreed:
        x, pp = state["p"][i], plan[i]
        line = money(x["amt"]) + " for your " + pp["name"] + " on " + _day(pp, x["date"])
        if x["clamped"]:
            line += ", which is the latest date I can record for it"
        parts.append(line)
    return "talk", "So that is " + "; and ".join(parts) + ". " + cfg["confirm_question"]


def _refused(state, i, plan, cfg):
    x, pp = state["p"][i], plan[i]
    if _ladder_offer(pp, x):
        return state, _offer_text(pp, x, cfg), "talk"
    _end(x, cfg["exhausted_note"])
    nxt, say = _next_product(state, plan, cfg)
    return state, say, nxt


def _below_min(state, i, plan, cfg):
    x, pp = state["p"][i], plan[i]
    if x["below_asks"] >= 1:
        return _refused(state, i, plan, cfg) if cfg["floor_refused_is_flat"] else (state, _offer_text(pp, x, cfg), "talk")
    x["below_asks"] += 1
    x["offer_amt"] = pp["floor"]
    return state, ((cfg["below_min_say"] + " ") if cfg["below_min_say"] else "") + _offer_text(pp, x, cfg, new_floor=True), "talk"


def _date_for_all(state, iso, plan, today, cfg):
    """One date for everything: each open product on that date, or on its own deadline (said in the read-back)."""
    for i in _open(state):
        x, pp = state["p"][i], plan[i]
        d, changed, why = _check_day(iso, pp, today, cfg)
        if d is None:
            continue
        x["clamped"] = changed and why.startswith("after") and d == pp["deadline"]
        if changed and not x["clamped"]:                      # e.g. a holiday: offer the next business day first
            x["offer_amt"], x["offer_date"] = (pp["floor"] if x["too_much"] else pp["full"]), d
            state["cursor"] = i
            return state, "That day is not possible for your " + pp["name"] + ". " + _offer_text(pp, x, cfg), "talk"
        _agree(x, pp["floor"] if x["too_much"] else pp["full"], d)
    nxt, say = _next_product(state, plan, cfg)
    return state, say, nxt


def step(state, ev, plan, today, cfg):
    """One customer turn. Never raises: on any error it asks the customer to repeat."""
    try:
        return _step(state, ev, plan, today, cfg)
    except Exception as e:
        state["neg_error"] = str(e)
        return state, "Sorry, could you say that again?", "talk"


def _step(state, ev, plan, today, cfg):
    kind = str(ev.get("kind") or "unclear")
    multi = len(plan) > 1
    if state["phase"] in ("closed", "record"):
        return state, "", ("close" if state["phase"] == "closed" else "record")
    day = resolve_spoken_date(ev.get("day"), today, cfg) if ev.get("day") else {"status": "none", "date": ""}
    amount = parse_amount(ev.get("amount")) if ev.get("amount") else None
    sits = cfg["product_situations"]
    if kind not in sits:
        if day["status"] == "exact" or (amount is not None and kind in ("accept", "unclear", "refuse", "propose", UNCONFIRMED)):
            kind = "propose"
        elif day["status"] == "vague" and kind in ("refuse", "unclear", "propose", UNCONFIRMED):
            kind = "vague"
    # ---- the read-back was answered
    if state["phase"] == "confirm":
        if kind == "accept":
            state["phase"] = "record"
            return state, "", "record"
        if kind == "refuse":
            for x in state["p"]:
                if x["status"] == "agreed":
                    _end(x, cfg["exhausted_note"])
            nxt, say = _finish(state, plan, cfg)
            return state, say, nxt
        if kind == "propose":
            agreed = [i for i, x in enumerate(state["p"]) if x["status"] == "agreed"]
            target = agreed if _to_all(ev.get("about"), multi) or len(agreed) == 1 else [_which(ev.get("about"), plan, agreed[0])]
            for i in target:
                state["p"][i]["status"] = "open"
            state["phase"] = "offer"
            if day["status"] == "exact" and len(target) > 1:
                return _date_for_all(state, day["date"], plan, today, cfg)
            state["cursor"] = target[0]
            return _on_product(state, kind, day, amount, plan, today, cfg)
        nxt, say = _finish(state, plan, cfg)
        return state, _answer_first(say, nxt) if kind in ("question", UNCONFIRMED) else say, nxt
    # ---- a situation about one product (only in briefs that note products and continue)
    if kind in sits:
        i = _which(ev.get("about"), plan, state["cursor"])
        _end(state["p"][i], sits[kind]["note"])
        state["phase"] = "offer"
        nxt, say = _next_product(state, plan, cfg)
        pre = sits[kind]["say"]
        return state, ((pre + " ") if pre else "") + say, nxt
    # ---- the first ask, about today, for every product at once
    if state["phase"] == "today":
        state["phase"] = "offer"
        if kind == "accept":
            for i, x in enumerate(state["p"]):
                _agree(x, plan[i]["full"], plan[i]["today"])
            nxt, say = _finish(state, plan, cfg)
            return state, say, nxt
        # one date for several products (multi-product rule: each on its own deadline if needed, said in the read-back);
        # a single product goes through the single-product rules (a late date is offered as the deadline first)
        if multi and kind == "propose" and day["status"] == "exact" and (_to_all(ev.get("about"), multi) or not ev.get("about")) and amount is None:
            return _date_for_all(state, day["date"], plan, today, cfg)
        if multi and kind == "propose":
            state["cursor"] = _which(ev.get("about"), plan, 0)
            return _on_product(state, kind, day, amount, plan, today, cfg)
        if multi and kind in ("refuse", "too_much", "unclear", UNCONFIRMED):
            if kind == "too_much":
                for x in state["p"]:
                    x["too_much"] = True
            nxt, say = _next_product(state, plan, cfg)
            return state, _answer_first(say, nxt) if kind == UNCONFIRMED else say, nxt
        state["cursor"] = 0
        return _on_product(state, kind, day, amount, plan, today, cfg)
    if kind == "propose" and day["status"] == "exact" and _to_all(ev.get("about"), multi) and amount is None:
        return _date_for_all(state, day["date"], plan, today, cfg)
    return _on_product(state, kind, day, amount, plan, today, cfg)


def _on_product(state, kind, day, amount, plan, today, cfg):
    i = state["cursor"]
    x, pp = state["p"][i], plan[i]
    if kind == "accept":
        _agree(x, x["offer_amt"], x["offer_date"])
        nxt, say = _next_product(state, plan, cfg)
        return state, say, nxt
    if kind == "propose":
        amt = amount if amount is not None else (state["pending_amount"] if state["pending_amount"] is not None else x["offer_amt"])
        amt = min(amt, pp["full"])
        if amt < pp["floor"]:
            if day["status"] == "exact":
                d, _, _ = _check_day(day["date"], pp, today, cfg)
                x["offer_date"] = d or x["offer_date"]
            return _below_min(state, i, plan, cfg)
        if day["status"] != "exact":
            state["pending_amount"] = amt
            x["offer_amt"] = amt
            return state, "On which day can you pay " + money(amt) + " for your " + pp["name"] + "?", "talk"
        d, changed, why = _check_day(day["date"], pp, today, cfg)
        if d is None:
            return state, "That day is not possible. " + _offer_text(pp, x, cfg), "talk"
        if changed:
            x["offer_amt"], x["offer_date"] = amt, d
            lead = ("The latest date I can record for your " + pp["name"] + " is " + _day(pp, d) + ". ") if why.startswith("after") else "That day is not possible. "
            return state, lead + _offer_text(pp, x, cfg), "talk"
        state["pending_amount"] = None
        _agree(x, amt, d)
        nxt, say = _next_product(state, plan, cfg)
        return state, say, nxt
    if kind == "too_much":
        x["too_much"] = True
        if not x["floor_offered"]:
            x["offer_amt"] = pp["floor"]
            return state, _offer_text(pp, x, cfg, new_floor=True), "talk"
        return _refused(state, i, plan, cfg) if cfg["floor_refused_is_flat"] else (state, _offer_text(pp, x, cfg), "talk")
    if kind == "vague":
        if x["vague_asks"] < cfg["vague_asks"]:
            x["vague_asks"] += 1
            return state, "Which exact day could you pay for your " + pp["name"] + "?", "talk"
        if cfg["vague_then"] == "propose_deadline" and pp["deadline"]:
            x["offer_date"] = pp["deadline"]
            return state, _offer_text(pp, x, cfg), "talk"
        return _refused(state, i, plan, cfg)
    if kind == "refuse":
        return _refused(state, i, plan, cfg)
    if kind == UNCONFIRMED:
        # the customer asked for something else, not clearly enough to act on: a non-answer, so the next persuasion
        # offer if one is left; with none left the open offer is repeated (a question never ends a product)
        if x["attempt"] < len(pp["ladder"]):
            state, say, nxt = _refused(state, i, plan, cfg)
        else:
            say, nxt = _offer_text(pp, x, cfg), "talk"
        return state, _answer_first(say, nxt), nxt
    return state, ("ASK_FIRST: " if kind == "question" else "") + _offer_text(pp, x, cfg), "talk"
