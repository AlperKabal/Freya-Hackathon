"""Tests for "a build always ends with an agent": odd input files, a tool API in another shape, a SPEC with
problems, model calls that fail or hang, a generator or a platform that refuses a candidate.

    python dev/test_robust.py

No model and no platform: the model calls and the Freya client are replaced by fakes that fail on purpose.
"""
import asyncio, copy, io, json, pathlib, shutil, sys, tempfile, time, types, zipfile
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import build, extract, generate, ingest, llm, minimal, robust, sentences, verify
from builder import spec_schema as S
import importlib.util

fails = 0
TMP = pathlib.Path(tempfile.mkdtemp(prefix="robust-"))
verify._sample_days = lambda spec: ["2026-10-14", "2026-10-16", "2026-12-24"]      # three days are enough here


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {str(got)[:300]}" + ("" if ok else f"   (want {want})"))


def load(path):
    return json.loads((KIT / path).read_text(encoding="utf-8"))


KIT_API = KIT / "tools/openapi.json"
TOOLS = ingest.parse_openapi(KIT_API)["tools"]
C_TOOLS = ingest.parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"]
SPEC_A, SPEC_AB, SPEC_C = load("dev/specs/brief-a.json"), load("dev/specs/brief-ab.json"), load("dev/specs/imaginary-c.json")

# ---------------------------------------------------------------- 1. files in other encodings and formats

text = "Rule 1: the café closes at 19:00 – no exceptions. Holidays: 2026-12-25."
for name, raw in (("utf8.md", text.encode("utf-8")), ("bom.md", b"\xef\xbb\xbf" + text.encode("utf-8")), ("cp1252.txt", text.encode("cp1252")),
                  ("utf16.txt", text.encode("utf-16"))):
    (TMP / name).write_bytes(raw)
    got, note = ingest.read_text(TMP / name)
    check(f"{name} is read whatever its encoding", (got, note), (text, ""))
docx = io.BytesIO()
with zipfile.ZipFile(docx, "w") as z:
    z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Policy extract</w:t></w:r></w:p><w:p><w:r><w:t xml:space=\"preserve\">Deadline: 5 days &amp; no more</w:t></w:r><w:r><w:tab/><w:t>.</w:t></w:r></w:p>"
               "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>refused</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>no promise</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>")
(TMP / "memo.docx").write_bytes(docx.getvalue())
got, note = ingest.read_text(TMP / "memo.docx")
check("a .docx is read as text, table rows as lines", (got.splitlines(), note), (["Policy extract", "Deadline: 5 days & no more.", "refused | no promise"], "office file read as text"))
xlsx = io.BytesIO()
with zipfile.ZipFile(xlsx, "w") as z:
    z.writestr("xl/sharedStrings.xml", "<sst><si><t>outcome</t></si><si><t>reason</t></si><si><t>closed</t></si></sst>")
    z.writestr("xl/worksheets/sheet1.xml", "<worksheet><sheetData><row><c t=\"s\"><v>0</v></c><c t=\"s\"><v>1</v></c></row><row><c t=\"s\"><v>2</v></c><c><v>7</v></c></row></sheetData></worksheet>")
(TMP / "codes.xlsx").write_bytes(xlsx.getvalue())
check("an .xlsx code list is read as rows", ingest.read_text(TMP / "codes.xlsx")[0].splitlines(), ["outcome,reason", "closed,7"])
check("a file that is not there is an empty text with a note, not an error", ingest.read_text(TMP / "nothing.md")[0], "")
docs = ingest.read_briefs([TMP / "utf8.md", TMP / "nothing.md"])
check("read_briefs never raises and marks the unreadable file", [("note" in d, d["name"]) for d in docs], [(False, "utf8"), (True, "nothing")])

# ---------------------------------------------------------------- 2. a tool API in another shape

api = json.loads(KIT_API.read_text(encoding="utf-8"))
alt = copy.deepcopy(api)
alt["components"] = {"schemas": {"Base": {"type": "object", "properties": {"customer_id": {"type": "string"}}, "required": ["customer_id"]}}}
paths = {}
for route, ops in api["paths"].items():
    op = copy.deepcopy(ops["post"])
    name = route.strip("/")
    body = op["requestBody"]["content"]["application/json"]["schema"]
    body["properties"].pop("customer_id")
    body["required"] = [r for r in body.get("required", []) if r != "customer_id"]
    op["requestBody"]["content"] = {"application/json; charset=utf-8": {"schema": {"allOf": [{"$ref": "#/components/schemas/Base"}, body]}}}
    op["operationId"] = "".join(w.capitalize() if i else w for i, w in enumerate(name.split("_")))          # verifyIdentity
    op["responses"] = {"default": op["responses"]["200"]}
    paths["/bank/v2/" + name.replace("_", "-")] = {"post": op, "parameters": []}
alt["paths"] = paths
(TMP / "alt-api.json").write_text(json.dumps(alt), encoding="utf-8")
alt_tools = ingest.parse_openapi(TMP / "alt-api.json")["tools"]
check("camelCase operation ids and other paths give the seven fixed names", sorted(alt_tools), sorted(S.TOOL_NAMES))
check("allOf with a $ref, another content type and a default response read the same fields",
      {n: (sorted(t["request"]), sorted(t["required"]), sorted(t["response"])) for n, t in alt_tools.items()},
      {n: (sorted(t["request"]), sorted(t["required"]), sorted(t["response"])) for n, t in TOOLS.items()})
check("the enum values survive", alt_tools["close_call"]["request"]["outcome"]["enum"], TOOLS["close_call"]["request"]["outcome"]["enum"])
sw = {"swagger": "2.0", "host": "bank.example", "basePath": "/v1", "schemes": ["https"],
      "paths": {"/verify_identity": {"post": {"parameters": [{"in": "body", "name": "body", "schema": {"type": "object", "properties": {"field": {"type": ["string", "null"], "enum": ["a", None]}}}}],
                                              "responses": {"200": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}}},
                "/odd": {"post": "not an operation"}, "/broken": {"post": {"requestBody": {"$ref": "https://elsewhere/x"}}}}}
(TMP / "swagger.json").write_text(json.dumps(sw), encoding="utf-8")
sw_tools = ingest.parse_openapi(TMP / "swagger.json")["tools"]
check("Swagger 2: body parameter, host and basePath, a nullable type", (sw_tools["verify_identity"]["url"], sw_tools["verify_identity"]["request"]["field"]["type"], sw_tools["verify_identity"]["request"]["field"]["enum"], list(sw_tools["verify_identity"]["response"])),
      ("https://bank.example/v1/verify_identity", "string", ["a"], ["ok"]))
check("an operation that cannot be read is skipped, the rest stays", "odd" in sw_tools, False)
(TMP / "codes.json").write_text(json.dumps([{"outcome": "x"}]), encoding="utf-8")
check("the tool API is recognised by what it is, not by its place", build.pick_inputs([str(TMP / "alt-api.json"), str(TMP / "utf8.md"), str(TMP / "codes.json")]),
      ([str(TMP / "utf8.md"), str(TMP / "codes.json")], str(TMP / "alt-api.json")))
check("a brief document in JSON is not taken for the API", ingest.looks_like_api(TMP / "codes.json"), False)

# ---------------------------------------------------------------- 3. the field mapping by rule

for name, tools, spec in (("kit API", TOOLS, SPEC_AB), ("imaginary bank C (renamed fields)", C_TOOLS, SPEC_C), ("kit API in another shape", alt_tools, SPEC_AB)):
    b = robust.bind(tools)
    check(f"{name}: tool fields by rule equal the reference SPEC", b["tool_fields"], spec["tool_fields"])
    check(f"{name}: identity result fields by rule", b["result_fields"], spec["identity"]["result_fields"])
    check(f"{name}: product list and fields by rule", (b["products_field"], b["product_fields"]), (spec["account"]["products_field"], spec["account"]["product_fields"]))
    check(f"{name}: floor field per product type by rule", {p["type"]: p["floor_field"] for p in b["product_types"]}, {p["type"]: p["floor_field"] for p in spec["account"]["product_types"]})
check("an empty tool API binds to empty names, without an error", robust.bind({})["tool_fields"]["customer_id"], "")

# ---------------------------------------------------------------- 4. any SPEC becomes one that validates and builds

tss_spec = importlib.util.spec_from_file_location("tss", KIT / "dev/test_spec_schema.py")
tss = importlib.util.module_from_spec(tss_spec)
tss_spec.loader.exec_module(tss)


def builds(spec, tools):
    for mode in ("v1", "orch"):
        wf = generate.build(spec, tools, mode)
        problems = verify.lint(wf, spec, tools) + verify.run_snippets(wf, spec)
        if problems:
            return f"{mode}: {problems[:2]}"
    return True


for name, tools, spec in (("brief-a", TOOLS, SPEC_A), ("brief-ab", TOOLS, SPEC_AB), ("imaginary-c", C_TOOLS, SPEC_C)):
    fixed, notes, left = robust.coerce(copy.deepcopy(spec), tools)
    check(f"{name}: a valid SPEC comes back unchanged", (fixed == spec, notes, left), (True, [], []))
    bad = []
    for label, broken in tss.mutations(spec):
        fixed, notes, left = robust.coerce(copy.deepcopy(broken), tools)
        if S.validate(fixed, tools) or left or builds(fixed, tools) is not True:
            bad.append(label)
    check(f"{name}: each of the validator's 23 kinds of broken SPEC is repaired and builds in both modes", bad, [])
    sk = robust.skeleton(tools)
    check(f"{name}: the skeleton validates and builds", (S.validate(sk, tools), builds(sk, tools)), ([], True))
for label, raw in (("nothing", None), ("a list", [1, 2]), ("a sentence", "the SPEC"), ("an empty object", {}), ("half a SPEC", {"opening": SPEC_A["opening"], "bands": "none"})):
    fixed, notes, left = robust.coerce(raw, TOOLS)
    check(f"a Reader answer that is {label} still gives a SPEC that validates and builds", (S.validate(fixed, TOOLS), builds(fixed, TOOLS)), ([], True))
fixed, notes, left = robust.coerce({"opening": SPEC_A["opening"], "bands": "none"}, TOOLS)
check("what the Reader did give is kept", fixed["opening"]["first_sentence"], SPEC_A["opening"]["first_sentence"])
extra = copy.deepcopy(SPEC_A)
extra["negotiation"]["special_rule"] = "On the first of the month no persuasion attempt is made."
fixed, notes, left = robust.coerce(extra, TOOLS)
check("a rule under a key the format does not have reaches the agent as a free rule", [r["text"] for r in fixed["free_rules"] if "first of the month" in r["text"]] != [], True)
check("...and with it the system prompt", "first of the month" in generate.build(fixed, TOOLS, "v1")["system_prompt"], True)
swap = copy.deepcopy(SPEC_A)
swap["identity"]["questions"][0]["field"] = "birthday_of_customer"
fixed, notes, left = robust.coerce(swap, TOOLS)
check("an identity question with an unknown field takes the one field left, in order", [q["field"] for q in fixed["identity"]["questions"]], [q["field"] for q in SPEC_A["identity"]["questions"]])
no_note = {k: v for k, v in TOOLS.items() if k != "add_note"}
fixed, notes, left = robust.coerce(copy.deepcopy(SPEC_AB), no_note)
check("a tool the API does not have: its feature is switched off, the error names the API", (fixed["notes"]["enabled"], [e[:14] for e in left]), (False, ["tool API: tool"]))

# ---------------------------------------------------------------- 5. model calls that fail, hang or answer badly

check("JSON in a fence", llm.parse_json('Here it is:\n```json\n{"a": 1}\n```'), {"a": 1})
check("a trailing comma", llm.parse_json('{"a": [1, 2,], "b": {"c": 3,},}'), {"a": [1, 2], "b": {"c": 3}})
check("a raw line break inside a string", llm.parse_json('{"a": "line one\nline two"}'), {"a": "line one\nline two"})


class Lines:
    def __init__(self): self.events, self.calls = [], []
    def event(self, kind, text): self.events.append((kind, text))
    def model_call(self, model, purpose): self.calls.append((model, purpose))


def fake_ask(script):
    """A stand-in for the SDK call: each entry is a reply text, an exception to raise, or a number of seconds to hang."""
    script = list(script)
    async def _ask(system, prompt, model):
        step = script.pop(0)
        if isinstance(step, BaseException): raise step
        if isinstance(step, (int, float)): await asyncio.sleep(step); return "{}"
        return step
    return _ask


real_ask = llm._ask
for label, script, want_calls, want in (
        ("a good first answer", ['{"ok": 1}'], 1, {"ok": 1}),
        ("not JSON, then JSON", ["I think that...", '{"ok": 2}'], 2, {"ok": 2}),
        ("an error, then an answer", [RuntimeError("overloaded"), '{"ok": 3}'], 2, {"ok": 3}),
        ("a call that hangs, then an answer", [5, '{"ok": 4}'], 2, {"ok": 4}),
        ("two failures, then the other model answers", [RuntimeError("x"), "nope", '{"ok": 5}'], 3, {"ok": 5})):
    tr_ = Lines()
    llm._ask = fake_ask(script)
    got = llm.run(llm.ask_json("s", "p", "Reader: test", tr_, timeout=0.3))
    check(f"model call: {label}", (got, len(tr_.calls)), (want, want_calls))
check("the third try names the other model", tr_.calls[-1][0] == llm.FALLBACK != llm.MODEL, True)
llm._ask = fake_ask([RuntimeError("a"), "b", RuntimeError("c")])
try:
    llm.run(llm.ask_json("s", "p", "Reader: test", Lines(), timeout=0.3)); got = "answered"
except llm.LLMError as e:
    got = "LLMError"
check("model call: nothing works -> LLMError, not a crash of another kind", got, "LLMError")
llm.set_deadline(time.time() + 5)
tr_ = Lines()
llm._ask = fake_ask(['{"late": 1}'])
try:
    llm.run(llm.ask_json("s", "p", "Auditor: test", tr_)); got = "called"
except llm.LLMError:
    got = "not started"
check("no model call starts when the build's time is used up", (got, tr_.calls), ("not started", []))
llm.set_deadline(None)

# ---------------------------------------------------------------- 6. the extraction with a failing model


def scripted(replies):
    """ask_json replaced: `replies` maps the start of a call's purpose to a list of answers (or exceptions)."""
    asked = []
    async def ask(system, prompt, purpose, trace=None, model=None, timeout=None):
        asked.append(purpose)
        for key, answers in replies.items():
            if purpose.startswith(key) and answers:
                a = answers.pop(0)
                if isinstance(a, BaseException): raise a
                return copy.deepcopy(a)
        raise llm.LLMError(purpose + ": no answer scripted")
    return ask, asked


DOCS = [{"path": "x", "name": "brief", "text": (KIT / "briefs/brief-a.md").read_text(encoding="utf-8")}]
BINDING = extract.rule_binding(TOOLS)
real_ask_json = extract.ask_json

extract.ask_json, asked = scripted({"Reader: documents": [SPEC_A], "Binder": [BINDING]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("a good Reader answer: no repair, no rule repair", (S.validate(spec, TOOLS), rep["repairs"], rep["coerced"]), ([], 0, False))

extract.ask_json, asked = scripted({"Reader: documents": [SPEC_A], "Binder": [llm.LLMError("Binder: timeout")]})
tr_ = Lines()
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, tr_))
check("no Binder answer: the mapping by rule is used and the SPEC validates", (S.validate(spec, TOOLS), binding["tool_fields"] == SPEC_A["tool_fields"]), ([], True))

wrong = copy.deepcopy(BINDING); wrong["tool_fields"]["transfer_to_agent"]["queue"] = "team"; wrong["product_fields"]["past_due"] = "overdue_sum"
extract.ask_json, asked = scripted({"Reader: documents": [SPEC_A], "Binder": [wrong]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("a Binder name the API does not have is settled by rule, without a repair round", (S.validate(spec, TOOLS), rep["repairs"], asked.count("Reader: repair SPEC (validation errors)")), ([], 0, 0))

typo = copy.deepcopy(SPEC_A); typo["identity"]["max_wrong_total"] = "3"; typo["opening"]["max_asks"] = "2"
extract.ask_json, asked = scripted({"Reader: documents": [typo], "Binder": [BINDING]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("a slip the rules fix without loss costs no model call", (spec == SPEC_A, rep["repairs"], [a for a in asked if "repair" in a]), (True, 0, []))

lossy = copy.deepcopy(SPEC_A); lossy["bands"][0]["deadline"] = {"kind": "third_friday"}
extract.ask_json, asked = scripted({"Reader: documents": [lossy], "Binder": [BINDING], "Reader: repair": [SPEC_A]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("a rule the format cannot hold goes back to the Reader; its valid answer is taken", (spec == SPEC_A, rep["repairs"], rep["coerced"]), (True, 1, False))

extract.ask_json, asked = scripted({"Reader: documents": [lossy], "Binder": [BINDING], "Reader: repair": [llm.LLMError("timeout")]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("...and when the Reader does not answer, the rule-repaired SPEC is used", (S.validate(spec, TOOLS), rep["coerced"], any("third_friday" in r["text"] for r in spec["free_rules"])), ([], True, True))

extract.ask_json, asked = scripted({"Reader: documents": [llm.LLMError("Reader: no reply within 480 s")], "Binder": [BINDING]})
try:
    llm.run(extract.draft(DOCS, TOOLS, Lines())); got = "returned"
except llm.LLMError:
    got = "LLMError"
check("no Reader answer at all is the one failure the caller has to handle", got, "LLMError")

claim = copy.deepcopy(SPEC_A)
claim["opening"]["first_sentence"] = "Hello, this call is recorded."
claim["amounts"]["below_min"]["say"] = "That amount cannot be recorded."
claim["recording"]["failure_say"] = "The promise was not saved."
dec = next(x for x in claim["situations"] if x["id"] == "deceased")
dec["say"], dec["say_exact"] = "It is logged. I am sorry for your loss.", True
extract.ask_json, asked = scripted({"Reader: documents": [claim], "Binder": [BINDING],
                                    "Reworder: opening.first_sentence": [{"sentence": "Hello, we record this call."}],
                                    "Reworder: amounts.below_min.say": [{"sentence": "I am not able to accept that amount."}],
                                    "Reworder: recording.failure_say": [llm.LLMError("timeout")]})
spec, binding, rep = llm.run(extract.draft(DOCS, TOOLS, Lines()))
check("sentences said before any save are reworded, also the ones about amounts",
      (spec["opening"]["first_sentence"], spec["amounts"]["below_min"]["say"]), ("Hello, we record this call.", "I am not able to accept that amount."))
check("a Reworder call that fails leaves its sentence; the brief's exact words are never reworded",
      (spec["recording"]["failure_say"], dec["say"] == next(x for x in spec["situations"] if x["id"] == "deceased")["say"], any("deceased" in a for a in asked)),
      ("The promise was not saved.", True, False))

better = copy.deepcopy(SPEC_A); better["calendar"]["holidays"].append("2026-12-24")
extract.ask_json, asked = scripted({"Auditor": [{"issues": [{"rule": "holidays", "problem": "one missing", "fix": "add it"}]}], "Reader: repair": [better]})
spec, rep = llm.run(extract.audit(copy.deepcopy(SPEC_A), BINDING, DOCS, TOOLS, Lines()))
check("the Auditor's finding is repaired and the valid result applied", (rep["audit_applied"], "2026-12-24" in spec["calendar"]["holidays"]), (True, True))
extract.ask_json, asked = scripted({"Auditor": [llm.LLMError("timeout")]})
spec, rep = llm.run(extract.audit(copy.deepcopy(SPEC_A), BINDING, DOCS, TOOLS, Lines()))
check("an Auditor that does not answer leaves the SPEC as it was", (spec == SPEC_A, rep["audit_applied"]), (True, False))
broken = copy.deepcopy(SPEC_A); broken.pop("calendar")
extract.ask_json, asked = scripted({"Auditor": [{"issues": [{"rule": "r", "problem": "p", "fix": "f"}]}], "Reader: repair": [broken]})
spec, rep = llm.run(extract.audit(copy.deepcopy(SPEC_A), BINDING, DOCS, TOOLS, Lines()))
check("an audit repair that does not validate is not applied", (spec == SPEC_A, rep["audit_applied"], len(rep["audit_issues"])), (True, False, 1))
extract.ask_json = real_ask_json

# ---------------------------------------------------------------- 7. the last resort: an agent without a SPEC

for name, briefs, tools, want in (
        ("Brief A (a table)", [KIT / "briefs/brief-a.md"], TOOLS, 16),
        ("raw material (a CSV code list)", sorted((KIT / "dev/specs/raw-a").glob("*")), TOOLS, 16),
        ("imaginary bank C", [KIT / "dev/specs/imaginary-c.md"], C_TOOLS, 13)):
    docs = ingest.read_briefs(briefs)
    wf, shim = minimal.build(docs, tools)
    exits = [k for k in wf["nodes"] if k.startswith("end_")]
    check(f"last resort, {name}: lint and code pass, one closing per row of the documents", (verify.lint(wf, shim, tools), minimal.selftest(wf), len(exits)), ([], [], want))
    check(f"last resort, {name}: the documents are its instructions and every bank tool is offered",
          (docs[0]["text"][:200] in wf["system_prompt"], sorted(t["function"]["name"] for t in wf["nodes"]["call"]["tools"])), (True, sorted(n for n in S.TOOL_NAMES if n != "close_call")))
pairs = minimal.closings(ingest.read_briefs([KIT / "briefs/brief-a.md"]), TOOLS["close_call"]["request"]["outcome"]["enum"])
table = {(r["outcome"], x) for r in SPEC_A["outcomes"]["table"] for x in (r["reasons"] or [""])}
check("last resort: the closings read from Brief A are the reference SPEC's closing table", set(pairs), table)
wf, shim = minimal.build([], {})
check("last resort: no documents and no tools still gives a workflow", (wf["initial_node"], minimal.selftest(wf)), ("setup", []))

# ---------------------------------------------------------------- 8. the whole build, with a platform that refuses


class Freya:
    """A stand-in for the kit's freya module that records what was saved."""
    def __init__(self, refuse=lambda wf: False, save_error=None):
        self.refuse, self.save_error, self.saved, self.validated = refuse, save_error, [], 0
    def validate_workflow(self, name, wf):
        self.validated += 1
        if self.refuse(wf): raise RuntimeError("POST /api/v2/workflow -> 400: schema validation failed")
    def save_workflow(self, slot, wf, state_file=None):
        if self.save_error: raise RuntimeError(self.save_error)
        self.saved.append(wf)
        return {"workflow_id": "w1", "agent_id": "a1", "version": len(self.saved)}
    def export_workflow(self, workflow_id, path):
        pathlib.Path(path).write_text(json.dumps({"workflow": self.saved[-1]}), encoding="utf-8"); return path


def run_build(args, freya=None, patches=()):
    """build.main with fakes; returns (exit code, the fake platform, the trace text)."""
    fake = freya or Freya()
    mod = types.ModuleType("freya")
    for k in ("validate_workflow", "save_workflow", "export_workflow"):
        setattr(mod, k, getattr(fake, k))
    sys.modules["freya"] = mod
    old = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
    for obj, name, new in patches: setattr(obj, name, new)
    out = TMP / f"out{len(list(TMP.glob('out*')))}"
    buf, stdout = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        code = build.main(list(args) + ["--out", str(out)])
    finally:
        sys.stdout = stdout
        for obj, name, value in old: setattr(obj, name, value)
        sys.modules.pop("freya", None)
    return code, fake, buf.getvalue(), out


A_MD, AB = str(KIT / "briefs/brief-a.md"), [str(KIT / "briefs/brief-a.md"), str(KIT / "briefs/brief-b.md")]
has = lambda wf, node: node in wf["nodes"]

code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-ok", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch"])
check("a good SPEC: one save, in the asked mode, status ok", (code, len(fr.saved), has(fr.saved[0], "neg_eval"), "status=ok model_calls" in log), (0, 1, True, True))
check("the saved workflow and its export are written", ((out / "test-robust-ok.workflow.json").exists(), (out / "test-robust-ok.export.json").exists()), (True, True))

bad_spec = copy.deepcopy(SPEC_A); bad_spec.pop("calendar"); bad_spec["bands"][0]["deadline"] = {"kind": "next_full_moon"}
(TMP / "bad.spec.json").write_text(json.dumps(bad_spec), encoding="utf-8")
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-bad", "--spec", str(TMP / "bad.spec.json"), "--mode", "orch"])
check("a SPEC with problems is repaired by rule and saved, and the trace says so", (code, len(fr.saved), "repaired by rule" in log, "SPEC repaired by rule" in log.splitlines()[-2]), (0, 1, True, True))


def no_orch(spec, tools, mode="v1"):
    if mode == "orch": raise KeyError("a field this generator did not expect")
    return real_build(spec, tools, mode)


real_build = generate.build
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-gen", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch"], patches=[(generate, "build", no_orch)])
check("the asked mode cannot be generated: the other mode is saved, the status names it", (code, len(fr.saved), has(fr.saved[0], "negotiate_1"), "status=ok (mode v1)" in log), (0, 1, True, True))

code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-dry", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch"], freya=Freya(refuse=lambda wf: "neg_eval" in wf["nodes"]))
check("the platform's dry run refuses the asked mode: the other mode is saved", (code, len(fr.saved), has(fr.saved[0], "negotiate_1"), fr.validated), (0, 1, True, 2))

class Flaky(Freya):
    """A platform that answers 504 to the first `n` dry runs and one save, then works (seen on 11 October)."""
    def __init__(self, n):
        super().__init__()
        self.n, self.save_fails = n, 1
    def validate_workflow(self, name, wf):
        self.validated += 1
        if self.validated <= self.n: raise RuntimeError("POST /api/v2/workflow -> 504: error code: 504")
    def save_workflow(self, slot, wf, state_file=None):
        if self.save_fails:
            self.save_fails -= 1
            raise TimeoutError("The read operation timed out")
        return super().save_workflow(slot, wf, state_file)


no_wait = [(build.time, "sleep", lambda s: None)]
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-504", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch"], freya=Flaky(3), patches=no_wait)
check("a 504 and a timeout are retried: the asked mode is saved, no step down", (code, len(fr.saved), has(fr.saved[0], "neg_eval"), "status=ok model_calls" in log, "fallback" in log, fr.validated),
      (0, 1, True, True, False, 4))
check("each retry is in the trace", log.count("hit a platform error"), 4)
check("a 400 or 404 is a refusal; a 5xx, a 401 in an outage, a 429 or a timeout is not",
      tuple(build.transient(e) for e in (RuntimeError("POST /x -> 400: bad"), RuntimeError("PUT /x -> 404: no such workflow"), RuntimeError("GET /x -> 502: x"),
                                         RuntimeError('POST /x -> 401: {"message":"invalid JWT"}'), RuntimeError("POST /x -> 429: slow down"), TimeoutError("t"))),
      (False, False, True, True, True, True))

# the official run command: no --slot, no --mode, paths from the repository root while the kit folder is the cwd
code, fr, log, out = run_build(["briefs/brief-a.md", "build-the-builder/tools/openapi.json", "--spec", str(KIT / "dev/specs/brief-a.json")])
check("no --slot and no --mode: orch is saved under a slot named after the brief",
      (code, len(fr.saved), has(fr.saved[0], "neg_eval"), (out / "brief-a.workflow.json").exists(), (out / "brief-a.export.json").exists()), (0, 1, True, True, True))
check("the default slot comes from the brief files' names", (build.default_slot(["x/hidden-1.md"]), build.default_slot(["a/Brief A.md", "b/brief-b.md"])),
      ("hidden-1", "brief-a+brief-b"))
check("a path from the repository root is found from the kit folder", pathlib.Path(build.resolve_path("build-the-builder/tools/openapi.json")).exists(), True)

code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-all", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch"], freya=Freya(refuse=lambda wf: "prepare_deal" in wf["nodes"]))
check("the platform refuses everything generated from the SPEC: the last resort is saved", (code, len(fr.saved), has(fr.saved[0], "call"), "status=ok (last resort)" in log), (0, 1, True, True))


async def no_reader(docs, tools, trace=None, max_repairs=2):
    raise llm.LLMError("Reader: no reply within 480 s")


code, fr, log, out = run_build(AB + [str(KIT_API), "--slot", "test-robust-nollm"], patches=[(extract, "draft", no_reader)])
check("no answer from the model at all: the last resort is saved, not nothing", (code, len(fr.saved), has(fr.saved[0], "call"), "no SPEC from the Reader" in log), (0, 1, True, True))


async def good_draft(docs, tools, trace=None, max_repairs=2):
    return copy.deepcopy(SPEC_A), BINDING, {"repairs": 0, "audit_issues": [], "audit_applied": False, "coerced": False, "notes": [], "errors": []}


async def good_audit(spec, binding, docs, tools, trace=None):
    s = copy.deepcopy(spec); s["calendar"]["holidays"].append("2026-12-24")
    return s, {"audit_issues": [{"rule": "holidays", "problem": "one missing"}], "audit_applied": True}


async def failing_audit(spec, binding, docs, tools, trace=None):
    raise RuntimeError("the connection dropped")


async def harmful_audit(spec, binding, docs, tools, trace=None):
    s = copy.deepcopy(spec); s["meta"]["bank_name"] = "poison"
    return s, {"audit_issues": [{"rule": "r", "problem": "p"}], "audit_applied": True}


code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-cp", "--mode", "orch"], patches=[(extract, "draft", good_draft), (extract, "audit", good_audit)])
holidays = lambda wf: sentences._cfg(wf["nodes"]["setup"])["holidays"]           # a code node's config is the SPEC's calendar
check("a checkpoint is saved from the drafted SPEC, then the audited agent replaces it",
      (code, len(fr.saved), "2026-12-24" in holidays(fr.saved[0]), "2026-12-24" in holidays(fr.saved[1])), (0, 2, False, True))
check("the SPEC written next to it is the audited one", "2026-12-24" in (out / "test-robust-cp.spec.json").read_text(encoding="utf-8"), True)
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-cp2", "--mode", "orch"], patches=[(extract, "draft", good_draft), (extract, "audit", failing_audit)])
check("an audit that crashes leaves the checkpoint: one save, status ok", (code, len(fr.saved), "status=ok model_calls" in log), (0, 1, True))


def poison(spec, tools, mode="v1"):
    if spec["meta"]["bank_name"] == "poison": raise ValueError("the audited SPEC cannot be generated")
    return real_build(spec, tools, mode)


code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-cp3", "--mode", "orch"], patches=[(extract, "draft", good_draft), (extract, "audit", harmful_audit), (generate, "build", poison)])
check("an audited SPEC that builds worse than the draft does not replace the checkpoint", (code, len(fr.saved), "the checkpoint stays" in log), (0, 1, True))

code, fr, log, out = run_build([A_MD, str(TMP / "swagger.json"), "--slot", "test-robust-api", "--spec", str(KIT / "dev/specs/brief-a.json")])
check("a tool API without the bank's tools: an agent is still saved, by rule and by the last resort", (code, len(fr.saved)), (0, 1))
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-plan", "--spec", str(KIT / "dev/specs/brief-a.json")], freya=Freya(save_error="Workspace plan limit reached"))
check("a platform that cannot save anything: exit code 1 and a trace, not a traceback", (code, len(fr.saved), "nothing could be saved" in log, "Traceback" in log), (1, 0, True, False))
code, fr, log, out = run_build([A_MD, str(KIT_API), "--slot", "test-robust-nosave", "--spec", str(KIT / "dev/specs/brief-a.json"), "--mode", "orch", "--no-save"])
check("--no-save: nothing is sent to the platform, the candidate is written", (code, fr.validated, len(fr.saved), (out / "test-robust-nosave.workflow.json").exists()), (0, 0, 0, True))

# ---------------------------------------------------------------- 9. the sentence check

wf = generate.build(SPEC_A, TOOLS, "orch")
check("the reference SPEC's fixed sentences are clean in orch", [f for f in sentences.audit(wf, SPEC_A) if f.startswith("problem")], [])
s = copy.deepcopy(SPEC_A)
s["opening"]["first_sentence"] = "Hello, I am calling about your debt. This call is recorded."
s["amounts"]["below_min"]["say"] = "That amount cannot be recorded."
s["closing"]["farewell"] = "Thank you, {title} {last_name}. Goodbye, {nickname}."
found = sentences.audit(generate.build(s, TOOLS, "orch"), s)
check("a forbidden word before identity is found", any("forbidden word 'debt'" in f and "opening" in f for f in found), True)
check("a word that reads as a save is found in the opening and in the amount sentence", sum("says 'recorded'" in f for f in found), 2)
check("a placeholder nothing fills would be said aloud: found; the call's own variables are not reported",
      (any("placeholder {nickname}" in f for f in found), any("placeholder {title}" in f for f in found)), (True, False))

# the call's own variables in a sentence that code writes are filled in by the code node (the platform fills only a node's own text)
s = copy.deepcopy(SPEC_AB)
s["closing"]["farewell"] = "Thank you, {title} {last_name}. Goodbye."
s["account"]["statement_intro"] = "{title} {last_name}, I am calling about a late payment."
call_vars = {"title": "Ms", "last_name": "Lin", "first_name": "Grace", "now": "2026-10-14T11:00", "customer_id": "c1"}
run_code = lambda node, v: (exec(verify.code_of(node), {"vars": v}), v)[1]
for mode in ("v1", "orch"):
    wf = generate.build(s, TOOLS, mode)
    v = run_code(wf["nodes"]["prepare_deal"], dict(call_vars, acct_items=[{"product_id": "p1", "type": "car_loan", "past_due": 140.0, "days_late": 7, "instalment_amount": 46.0}]))
    check(f"{mode}: the debt statement carries the customer's name", v["deal_intro"].startswith("Ms Lin, I am calling about a late payment."), True)
    ends = {t["target_node"] for n in wf["nodes"].values() for t in n.get("transitions") or []} | {n.get("max_turn_transition") for n in wf["nodes"].values()}
    check(f"{mode}: every way to the end node passes the farewell step", ("final_end" in ends - {None}, [k for k, n in wf["nodes"].items() if any(t["target_node"] == "final_end" for t in n.get("transitions") or [])]), (True, ["say_farewell"]))
    for exit_node in ("set_opening_unclear", "finalize"):
        v = run_code(wf["nodes"][exit_node], dict(call_vars, n_products="1", res_1="promise"))
        v = run_code(wf["nodes"]["say_farewell"], v)
        check(f"{mode}: the farewell after {exit_node} carries the customer's name and no brace", ("Thank you, Ms Lin. Goodbye." in v["farewell"], "{" in v["farewell"]), (True, False))
v = run_code(wf["nodes"]["say_farewell"], {"farewell": "Bye {title} {unknown_thing}.", "title": "Mr"})
check("a name that is no call variable, or has no value, stays as written", v["farewell"], "Bye Mr {unknown_thing}.")
check("the retry sentence, said on a node's entry, uses the platform's own placeholder", "{{" not in "".join(n["on_enter"].get("text", "") for k, n in generate.build(SPEC_A, TOOLS, "orch")["nodes"].items() if k.startswith("rec_")), True)
s = copy.deepcopy(SPEC_A)
s["recording"]["after_success_say"] = "Your promise is recorded and saved."
check("the sentence after a recorded promise may say so", [f for f in sentences.audit(generate.build(s, TOOLS, "orch"), s) if "recorded" in f], [])
v1 = sentences.audit(generate.build(SPEC_A, TOOLS, "v1"), SPEC_A)
check("v1: the exact sentences only the model says are listed as notes", sorted(f.split(" is said")[0] for f in v1 if f.startswith("note")),
      ["note: amounts.too_much.say", "note: confirmation.question", "note: recording.retry_say"])

shutil.rmtree(TMP, ignore_errors=True)
for p in (KIT / "traces").glob("test-robust-*.log"):
    p.unlink()
print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
