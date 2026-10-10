"""The builder's trace: plain text, one line per event, written as it happens. Never contains keys.

    t = Trace("traces", slot)
    t.event("stage", "generate")
    t.model_call("claude-opus-5-5", "Reader: brief -> SPEC")
    t.close()
"""
import os, pathlib, re, time

_SECRET = re.compile(r"(fak_[A-Za-z0-9_\-]+|sk-ant-[A-Za-z0-9_\-]+)")


class Trace:
    def __init__(self, folder, slot):
        self.t0 = time.time()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.path = pathlib.Path(folder) / f"{slot}-{stamp}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "w", encoding="utf-8")
        self.calls = 0
        self.line("start", time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    def line(self, kind, text):
        text = _SECRET.sub("[redacted]", str(text))
        self.f.write(f"[{time.time() - self.t0:7.1f}s] {kind:<10} {text}\n")
        self.f.flush()
        print(f"  [{kind}] {text}", flush=True)

    def event(self, kind, text): self.line(kind, text)

    def model_call(self, model, purpose):
        self.calls += 1
        self.line("model", f"#{self.calls} {model}: {purpose}")

    def close(self, status="ok"):
        self.line("end", f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} status={status} model_calls={self.calls} seconds={time.time() - self.t0:.0f}")
        self.f.close()
        return self.path
