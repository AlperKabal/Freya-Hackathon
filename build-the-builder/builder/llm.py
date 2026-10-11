"""The builder's model calls. Uses the Claude Agent SDK, so it works with a Claude login or with ANTHROPIC_API_KEY.

    data = await ask_json(system, prompt, purpose="Reader: brief -> SPEC", trace=t)

JSON only, parsed defensively. No tools, no project settings: the model reads only what the prompt gives it.
A build runs once on a hidden brief, so a call must never hang it or end it:
- every call has a time limit (BUILDER_CALL_TIMEOUT_S, or the `timeout` argument);
- a failed call (an error, a timeout, a reply that is not JSON) is tried again once with the same model, then once
  with BUILDER_MODEL_FALLBACK when that names another model;
- when nothing worked, LLMError is raised: the caller decides what to build without this answer.
"""
import asyncio, json, os, re, time

MODEL = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")
FALLBACK = os.environ.get("BUILDER_MODEL_FALLBACK", "claude-sonnet-5-5")
TIMEOUT = float(os.environ.get("BUILDER_CALL_TIMEOUT_S", "480"))


class LLMError(RuntimeError):
    """No usable answer from the model."""


_deadline = None


def set_deadline(epoch_seconds):
    """The moment after which no call may still be running (the build's time budget). None switches it off."""
    global _deadline
    _deadline = epoch_seconds


def time_left():
    return None if _deadline is None else _deadline - time.time()


def parse_json(text):
    """The first JSON object in a reply, with or without a ``` fence. A trailing comma or a raw line break inside a
    string, which models sometimes write, does not make the reply unusable."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    last = None
    for attempt in (t[start:], re.sub(r",(\s*[}\]])", r"\1", t[start:])):
        try:
            obj, _ = json.JSONDecoder(strict=False).raw_decode(attempt)
            return obj
        except ValueError as e:
            last = e
    raise last


async def _ask(system, prompt, model):
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
    opts = ClaudeAgentOptions(model=model, system_prompt=system, max_turns=1, allowed_tools=[], setting_sources=[])
    out = []
    async for m in query(prompt=prompt, options=opts):
        if isinstance(m, AssistantMessage):
            out += [b.text for b in m.content if isinstance(b, TextBlock)]
    return "".join(out)


async def ask_json(system, prompt, purpose, trace=None, model=None, timeout=None, parse=None):
    """`parse` reads the reply (default: the JSON object in it) and raises ValueError for one that cannot be used."""
    model = model or MODEL
    limit = float(timeout or TIMEOUT)
    plan = [(model, ""), (model, " (second try)")]
    if FALLBACK and FALLBACK != model:
        plan.append((FALLBACK, " (other model)"))
    last = "no attempt"
    for m, tag in plan:
        t0 = time.time()
        left = time_left()
        if left is not None:
            if left < 20:                                # the build's budget is used up: do not start another call
                last = last if last != "no attempt" else "no time left in the build's budget"
                break
            limit = min(limit, left)
        if trace: trace.model_call(m, purpose + tag)
        again = "was not valid JSON ({}). Reply with the JSON object only." if parse is None else "could not be used ({}). Reply in the required form only."
        ask = prompt if last == "no attempt" or not last.startswith("not JSON") else \
            prompt + "\n\nYour previous reply " + again.format(last[10:])
        try:
            text = await asyncio.wait_for(_ask(system, ask, m), timeout=limit)
            data = (parse or parse_json)(text)
            if trace: trace.event("model", f"{purpose}: {len(text)} chars in {time.time() - t0:.0f} s")
            return data
        except ValueError as e:
            last = "not JSON: " + str(e)[:200]
        except asyncio.TimeoutError:
            last = f"no reply within {limit:.0f} s"
        except Exception as e:                           # the SDK, the login, the network: all end the same way here
            last = f"{type(e).__name__}: {str(e)[:200]}"
        if trace: trace.event("model", f"{purpose}{tag}: failed after {time.time() - t0:.0f} s ({last})")
    raise LLMError(f"{purpose}: {last}")


def run(coro):
    return asyncio.run(coro)
