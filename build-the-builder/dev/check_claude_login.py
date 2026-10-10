"""Check that the Claude Agent SDK can reach a model before a long builder run. One tiny model call.

    python dev/check_claude_login.py              # uses BUILDER_MODEL if set, else the SDK default

Without ANTHROPIC_API_KEY the SDK uses the Claude login of this machine (a Pro or Max subscription).
"""
import asyncio, os, time

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query


async def main():
    print("auth:", "ANTHROPIC_API_KEY (API billing)" if os.environ.get("ANTHROPIC_API_KEY") else "Claude login (subscription)")
    model = os.environ.get("BUILDER_MODEL")
    opts = ClaudeAgentOptions(max_turns=1, allowed_tools=[], setting_sources=[], **({"model": model} if model else {}))
    t0 = time.time()
    async for m in query(prompt="Reply with the single word OK.", options=opts):
        if isinstance(m, AssistantMessage):
            print("model:", m.model, "| reply:", " ".join(b.text for b in m.content if isinstance(b, TextBlock)))
        elif isinstance(m, ResultMessage):
            print(f"result: is_error={m.is_error}, {time.time() - t0:.1f} s, reported cost ${m.total_cost_usd or 0:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
