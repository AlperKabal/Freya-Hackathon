"""The kit's tools/run_cases.py, with every Freya API call retried on a transient platform error.

    python dev/run_cases_retry.py <agent_id> --brief A --reps 3 --out results/x.json     (same arguments as run_cases.py)

On 11 October the platform answered 503 "API key validation is temporarily unavailable" and 504 for a while; one such
answer while run_cases.py polled a running simulation killed the whole run, although the simulation went on. The kit
files stay unchanged: this wrapper patches freya.api in memory, the same way builder/build.py decides what is
transient (any status but 400/404/409/413/422, a timeout, a lost connection), and then runs run_cases.main().
"""
import pathlib, re, runpy, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

import freya
from builder.build import transient

_api = freya.api


def _started(body):
    """The simulation a failed start request may have created anyway (seen: a 504 answer, the simulation ran)."""
    try:
        r = _api("GET", "/api/v2/simulations", limit=10)
        sims = r.get("simulations") if isinstance(r, dict) else r
        for s in sims or []:
            if s.get("name") == body.get("name") and (s.get("agentId") or body.get("agentId")) == body.get("agentId"):
                return {"simulation": s}
    except Exception:
        pass
    return None


def api(method, path, body=None, **params):
    start = method == "POST" and path == "/api/v2/simulations"
    wait, deadline = 5, time.time() + (3600 if start else 600)    # a start may wait for another simulation to end
    while True:
        try:
            return _api(method, path, body, **params)
        except Exception as e:
            busy = start and re.search(r"plan limit|concurrent simulations", str(e), re.I)
            if start and (busy or transient(e)):
                made = _started(body or {})
                if made:                                  # the request failed but the simulation exists: use it
                    print(f"  [platform] the start answered {str(e)[:60]}, but simulation {made['simulation'].get('id')} exists: using it", file=sys.stderr, flush=True)
                    return made
            if not (busy or transient(e)) or time.time() + wait > deadline:
                raise
            print(f"  [platform] {method} {path}: {str(e)[:100]} - trying again in {wait} s", file=sys.stderr, flush=True)
            time.sleep(wait)
            wait = 30 if busy else min(wait * 2, 60)


freya.api = api
sys.argv = [str(KIT / "tools" / "run_cases.py")] + sys.argv[1:]
runpy.run_path(str(KIT / "tools" / "run_cases.py"), run_name="__main__")
