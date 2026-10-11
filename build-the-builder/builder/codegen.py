"""Build the Python source of the workflow's code nodes and hooks.

A code node's source = the shared snippet (builder/snippets/*.py, which is also tested locally) + a config made
from the SPEC + a short body. The config is embedded as hex, so the source never contains braces from JSON:
the platform may treat double braces in code as a variable placeholder (docs/tools-and-code.md).
"""
import json, pathlib, re

SNIPPETS = pathlib.Path(__file__).resolve().parent / "snippets"


def snippet(name):
    """The snippet's source without its module docstring."""
    src = (SNIPPETS / f"{name}.py").read_text(encoding="utf-8")
    return re.sub(r'^\s*"""[\s\S]*?"""\s*', "", src, count=1)


# Seen on the platform (2026-10-11, a v1 call): one sandbox run's output was cut, and the platform stored its error
# message, which quotes that output with the sandbox's result marker, in the tool's `<tool>_response.message`
# variable. Every later run prints all `vars`, so its output then holds the marker twice; the platform splits on the
# wrong one and fails again, for the rest of the call (30 failed identity checks in a row). So every code node and
# hook first takes the marker out of the variables. The marker is assembled at run time and never appears as one
# word in the source.
SCRUB = ("try:\n"
         "    _mk = '__CODE_EXEC' + '_RESULT__'\n"
         "    for _k in list(vars):\n"
         "        if isinstance(vars[_k], str) and _mk in vars[_k]:\n"
         "            vars[_k] = vars[_k].replace(_mk, '[sandbox result]')\n"
         "except Exception:\n"
         "    pass\n")


def scrubbed(src):
    """A hook's source with the marker scrub in front (see SCRUB)."""
    return SCRUB + src if src and not src.startswith(SCRUB) else src


def embed(config, body, snippets=("dates",)):
    """Full source of one code node. `body` reads `vars` and `CFG` and must not raise (wrap it in try)."""
    hexcfg = json.dumps(config, ensure_ascii=False).encode("utf-8").hex()
    src = "import json\n" + SCRUB + "\n".join(snippet(s) for s in snippets) + \
          f"\nCFG = json.loads(bytes.fromhex('{hexcfg}').decode('utf-8'))\n" + body
    if "{{" in src or "}}" in src:
        raise ValueError("generated code contains a double brace")
    compile(src, "<code node>", "exec")
    return src


def date_config(spec):
    """The part of the SPEC the date snippet needs."""
    return {
        "business_weekdays": spec["calendar"]["business_weekdays"],
        "holidays": spec["calendar"]["holidays"],
        "bands": spec["bands"],
        "earliest": spec["dates"]["earliest"],
        "business_day_only": spec["dates"]["business_day_only"],
        "non_business_day": spec["dates"]["non_business_day"],
        "after_deadline": spec["dates"]["after_deadline"],
        "relative_weekday": spec["dates"]["relative_weekday"],
        "vague_examples": spec["dates"]["vague"]["examples"],
    }
