"""The kit's tools/run_cases.py, with every Freya API call retried on a transient platform error.

    python dev/run_cases_retry.py <agent_id> --brief A --reps 3 --out results/x.json     (same arguments as run_cases.py)

On 11 October the platform answered 503 "API key validation is temporarily unavailable" and 504 for a while; one such
answer while run_cases.py polled a running simulation killed the whole run, although the simulation went on. The kit
files stay unchanged: this wrapper patches freya.api in memory, the same way builder/build.py decides what is
transient (any status but 400/404/409/413/422, a timeout, a lost connection), and then runs run_cases.main().
"""
import pathlib, runpy, sys, time
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))

import freya
from builder.build import transient

_api = freya.api


def api(method, path, body=None, **params):
    wait, deadline = 5, time.time() + 600                 # at most ten minutes of retries per call
    while True:
        try:
            return _api(method, path, body, **params)
        except Exception as e:
            if not transient(e) or time.time() + wait > deadline:
                raise
            print(f"  [platform] {method} {path}: {str(e)[:100]} - trying again in {wait} s", file=sys.stderr, flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 60)


freya.api = api
sys.argv = [str(KIT / "tools" / "run_cases.py")] + sys.argv[1:]
runpy.run_path(str(KIT / "tools" / "run_cases.py"), run_name="__main__")
