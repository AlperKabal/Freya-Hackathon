"""The fixed sentences of a generated agent, read against the SPEC.

    findings = audit(wf, spec)        # ["problem: ...", "note: ..."]; empty means nothing to say

The judge reads words literally (a check "does not say 'recorded' before a successful call" failed an agent that
said "the promise was not recorded"). So the sentences the engine itself says are checked word by word before the
agent is saved:
- before identity is verified, no fixed line holds a word the SPEC forbids there;
- no fixed line said while nothing is saved holds a word that reads as "it was saved";
- no fixed line would say a placeholder aloud;
- every sentence the SPEC gives as the brief's exact words is said by a fixed line (a note when only a prompt
  holds it, so the model says it: that is how v1 speaks most of the negotiation; a problem when nothing holds it).
Findings go to the build trace. They never stop a save: an agent with a doubtful word is better than no agent.
Nothing here knows a brief; node names are the generator's.
"""
import json, re

from builder import verify
from builder.extract import CLAIM_WORDS as CLAIM       # one list of such words for the extractor and for this check

BRACE = re.compile(r"(?<![{])[{]([a-zA-Z_][a-zA-Z0-9_]*)[}](?![}])")
ACCOUNT_STEP = "load_account"          # identity is verified once the call passes this node
# which configured sentences a code node speaks (the shared config holds more than a node says)
SAYS = {"setup": ["farewell"], "prepare_deal": ["intro", "first_ask", "first_ask_all"], "finalize": ["farewell", "after_success", "fail_say"],
        "neg_eval": ["too_much_say", "below_min_say", "confirm_question", "first_ask"]}
AFTER_SAVE = {"after_success"}         # said only when a promise is recorded


def _cfg(node):
    src = verify.code_of(node) or ""
    m = re.search(r"bytes\.fromhex\('([0-9a-f]+)'\)", src)
    try:
        return json.loads(bytes.fromhex(m.group(1)).decode("utf-8")) if m else {}
    except ValueError:
        return {}


def fixed_lines(wf):
    """(node, key, text) of every sentence the engine can say by itself: a spoken line on entry, the end node's
    message, and the sentences a code node is configured to say."""
    out = []
    for name, n in wf["nodes"].items():
        oe = n.get("on_enter") or {}
        if oe.get("type") == "tts" and str(oe.get("text") or "").strip():
            out.append((name, "on_enter", oe["text"]))
        term = (((n.get("terminal") or {}).get("function") or {}).get("parameters") or {}).get("properties") or {}
        if str((term.get("spoken_message") or {}).get("default") or "").strip():
            out.append((name, "spoken_message", term["spoken_message"]["default"]))
        if n.get("node_type") != "code":
            continue
        cfg = _cfg(n)
        keys = ["f"] if name.startswith("set_") else SAYS.get(name, [])
        out += [(name, k, cfg[k]) for k in keys if isinstance(cfg.get(k), str) and cfg[k].strip()]
        if name == "neg_eval":
            out += [(name, "situation " + sid, x["say"]) for sid, x in (cfg.get("product_situations") or {}).items() if isinstance(x, dict) and str(x.get("say") or "").strip()]
    return out


def before_identity(wf):
    """The nodes a call can be in while identity is not verified."""
    seen, todo = set(), [wf["initial_node"]]
    while todo:
        k = todo.pop()
        if k in seen or k not in wf["nodes"] or k == ACCOUNT_STEP:
            continue
        seen.add(k)
        n = wf["nodes"][k]
        todo += [t["target_node"] for t in n.get("transitions") or []] + [n[x] for x in ("passthrough_default_transition", "max_turn_transition") if n.get(x)]
    return seen


def exact_sentences(spec):
    """(where, sentence) for what the SPEC holds as the brief's own words."""
    names = {v["name"] for v in spec["call_variables"]}
    ph = lambda text: re.sub(r"[{]([a-zA-Z_][a-zA-Z0-9_]*)[}]", lambda m: "{{" + m.group(1) + "}}" if m.group(1) in names else m.group(0), text or "")
    out = [("opening.first_sentence", ph(spec["opening"]["first_sentence"])), ("opening.confirm_question", ph(spec["opening"]["confirm_question"])),
           ("negotiation.first_ask", spec["negotiation"]["first_ask"]), ("confirmation.question", spec["confirmation"]["question"]),
           ("recording.after_success_say", spec["recording"]["after_success_say"]), ("recording.retry_say", spec["recording"]["retry_say"]),
           ("amounts.too_much.say", spec["amounts"]["too_much"]["say"])]
    out += [(f"situations.{x['id']}.say", x["say"]) for x in spec["situations"] if x.get("say_exact") and x["say"]]
    return [(w, s.strip()) for w, s in out if s and s.strip()]


def audit(wf, spec):
    findings = []
    lines = fixed_lines(wf)
    early = before_identity(wf)
    names = {v["name"] for v in spec["call_variables"]}
    # 1. words the SPEC forbids before identity is verified
    for word in spec["opening"]["forbidden_before_identity"]:
        w = str(word).strip().lower()
        if not w:
            continue
        pat = re.compile(r"(?<![a-z])" + re.escape(w))
        for node, key, text in lines:
            if node in early and node != "final_end" and pat.search(text.lower()):
                findings.append(f"problem: before identity is verified, {node} ({key}) says the forbidden word {word!r}: {text!r}")
    # 2. words that read as "it was saved" in a line said while nothing is saved, and placeholders said aloud
    for node, key, text in lines:
        if key not in AFTER_SAVE:
            m = CLAIM.search(text)
            if m:
                findings.append(f"problem: {node} ({key}) says {m.group(0)!r} although nothing may be saved at that point: {text!r}")
        for m in BRACE.finditer(text):
            # a code node fills the call's own variables into the sentences it writes; a line on entry is said as it is
            if key in ("on_enter", "spoken_message") or m.group(1) not in names:
                findings.append(f"problem: {node} ({key}) would say the placeholder {m.group(0)} aloud: {text!r}")
    # 3. the brief's exact words: said by a fixed line, or at least held by a prompt
    said = [text for _, _, text in lines]
    prompts = [str(n.get("task_message") or "") for n in wf["nodes"].values()] + [str(wf.get("system_prompt") or "")]
    for where, sentence in exact_sentences(spec):
        if any(sentence in text for text in said):
            continue
        if any(sentence in p for p in prompts):
            findings.append(f"note: {where} is said by the model, not by a fixed line: {sentence!r}")
        else:
            findings.append(f"problem: {where} is not said anywhere: {sentence!r}")
    return list(dict.fromkeys(findings))
