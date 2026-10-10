"""The builder's model calls. Uses the Claude Agent SDK, so it works with a Claude login or with ANTHROPIC_API_KEY.

    data = await ask_json(system, prompt, purpose="Reader: brief -> SPEC", trace=t)

JSON only, parsed defensively, one retry with the parse error on invalid JSON. Model from BUILDER_MODEL.
No tools, no project settings: the model reads only what the prompt gives it.
"""
import asyncio, json, os, re, time

MODEL = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")


def parse_json(text):
    """The first JSON object in a reply, with or without a ``` fence."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    obj, _ = json.JSONDecoder().raw_decode(t[start:])
    return obj


async def _ask(system, prompt, model):
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query
    opts = ClaudeAgentOptions(model=model, system_prompt=system, max_turns=1, allowed_tools=[], setting_sources=[])
    out = []
    async for m in query(prompt=prompt, options=opts):
        if isinstance(m, AssistantMessage):
            out += [b.text for b in m.content if isinstance(b, TextBlock)]
    return "".join(out)


async def ask_json(system, prompt, purpose, trace=None, model=None):
    model = model or MODEL
    last = None
    for attempt in (1, 2):
        t0 = time.time()
        if trace: trace.model_call(model, purpose + ("" if attempt == 1 else " (retry after invalid JSON)"))
        text = await _ask(system, prompt if attempt == 1 else prompt + f"\n\nYour previous reply was not valid JSON ({last}). Reply with the JSON object only.", model)
        try:
            data = parse_json(text)
            if trace: trace.event("model", f"{purpose}: {len(text)} chars in {time.time() - t0:.0f} s")
            return data
        except ValueError as e:
            last = str(e)[:200]
    raise ValueError(f"{purpose}: no valid JSON after a retry ({last})")


def run(coro):
    return asyncio.run(coro)
