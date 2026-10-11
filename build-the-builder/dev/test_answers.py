"""Tests for builder/snippets/answers.py: an identity answer goes to the bank in the form its TYPE asks for.

    python dev/test_answers.py

Two properties matter more than any single case: an answer that is already right goes out unchanged, and an answer
the code is not sure about goes out exactly as the model wrote it.
"""
import copy, json, pathlib, sys
KIT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from builder import codegen, generate
from builder.ingest import parse_openapi

ns = {}
exec(codegen.snippet("answers"), ns)
norm = ns["normalize_answer"]
fails = 0


def check(label, got, want=True):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f"   (want {want!r})"))


# digits: whatever the question is called
for said, want in [("4471", "4471"), ("44 71", "4471"), ("4-4-7-1", "4471"), ("four four seven one", "4471"), ("forty-four seventy-one", "4471"),
                   ("double four seven one", "4471"), ("oh three five eight", "0358"), ("zero, three, five, eight", "0358"), ("triple nine four", "9994"),
                   ("the last four are four four seven one", "the last four are four four seven one"),      # not sure: unchanged
                   ("I don't know", "I don't know"), ("", "")]:
    check(f"digits {said!r}", norm("digits", said), want)
check("a number is read like digits", norm("number", "one two three four five"), "12345")

# year
for said, want in [("1988", "1988"), ("in 1988", "1988"), ("nineteen eighty-eight", "1988"), ("born in nineteen eighty eight", "1988"),
                   ("two thousand and one", "2001"), ("twenty twenty-six", "2026"), ("nineteen oh five", "1905"), ("nineteen hundred", "1900"),
                   ("eighty-eight", "eighty-eight"), ("no idea", "no idea")]:
    check(f"year {said!r}", norm("year", said), want)

# date -> YYYY-MM-DD
DMY = "Read a date given only as numbers as day, then month, then year."
for said, want in [("1988-03-14", "1988-03-14"), ("1988/03/14", "1988-03-14"), ("1988.3.14", "1988-03-14"),
                   ("14 March 1988", "1988-03-14"), ("March 14, 1988", "1988-03-14"), ("14th of March 1988", "1988-03-14"), ("the 2nd of November, 1979", "1979-11-02"),
                   ("3 Feb 1990", "1990-02-03"), ("fourteenth of March nineteen eighty-eight", "1988-03-14"), ("March fourteenth nineteen eighty-eight", "1988-03-14"),
                   ("the twenty-first of July nineteen ninety-two", "1992-07-21"), ("twenty first July 1992", "1992-07-21"),
                   ("14/03/1988", "1988-03-14"), ("14.03.1988", "1988-03-14"), ("11/02/1979", "1979-02-11"),      # day first: the bank's own hint handles a swap
                   ("03/14/1988", "03/14/1988"),                                                             # no month 14: unchanged, the bank says it cannot read it
                   ("31 February 1990", "31 February 1990"), ("March 1988", "March 1988"), ("sometime in spring", "sometime in spring")]:
    check(f"date {said!r}", norm("date", said, DMY), want)
check("numbers only, where the documents put the month first", norm("date", "03/14/1988", "Numbers are read as month, then day, then year."), "1988-03-14")
check("...and MM/DD in the format text", norm("date", "03/14/1988", "MM/DD/YYYY"), "1988-03-14")

# text: only what the API's description says
check("a code stays as said when the API says nothing about its form", norm("text", "sw1a 1aa", "the postcode of the registered address"), "sw1a 1aa")
check("upper case when the description asks for it", norm("text", "sw1a 1aa", "the postcode in upper case"), "SW1A 1AA")
check("no spaces when the description asks for it", norm("text", "sw1a  1aa", "Postcode in capital letters, without spaces."), "SW1A1AA")
check("inner spaces are single", norm("text", "  ab   12  ", ""), "ab 12")

# never raises, never invents
for kind in ("date", "digits", "year", "number", "text", "unknown", None):
    for value in (None, 12, 4.5, [], {"a": 1}, "\n", "{}"):
        try:
            norm(kind, value)
        except Exception as e:
            check(f"{kind!r} with {value!r} raised", repr(e), "no exception")
check("an unknown type changes nothing", norm("colour", "Blue  sky"), "Blue  sky")
for kind, right in (("date", "1988-03-14"), ("digits", "4471"), ("year", "1988"), ("text", "AB12")):
    check(f"a right {kind} answer is unchanged", norm(kind, right), right)

# through the generated hook: the tool's body is rewritten before it reaches the bank
tools = parse_openapi(KIT / "tools/openapi.json")["tools"]
spec = json.loads((KIT / "dev/specs/brief-a.json").read_text(encoding="utf-8"))
hook = generate.build(spec, tools, "v1")["nodes"]["identity"]["tools"][0]["pre_process_code"]
check("the hook has no double brace", "{{" in hook or "}}" in hook, False)


def send(field, answer, source=hook):
    body, vars_ = {"field": field, "answer": answer, "customer_id": "c1"}, {}
    exec(source, {"config": {"body": body}, "vars": vars_})
    return body["answer"], vars_.get("id_last_field")


check("hook: a date of birth in words becomes the API's date form", send("date_of_birth", "14 March 1988"), ("1988-03-14", "date_of_birth"))
check("hook: digits said in two parts become four digits", send("phone_last4", "44 71"), ("4471", "phone_last4"))
check("hook: digits said as words", send("phone_last4", "four four seven one"), ("4471", "phone_last4"))
check("hook: a right answer is untouched", send("date_of_birth", "1988-03-14"), ("1988-03-14", "date_of_birth"))
check("hook: an unknown field is left alone", send("something_else", "Hello"), ("Hello", "something_else"))
try:
    exec(hook, {"config": {"body": None}, "vars": {}}); exec(hook, {"config": {}, "vars": {}}); got = "ran"
except Exception as e:
    got = repr(e)
check("hook: an odd request does not raise", got, "ran")

# another bank: the type decides, not the name (imaginary bank C asks for a company number and a founding year)
ctools = parse_openapi(KIT / "dev/specs/imaginary-c.openapi.json")["tools"]
cspec = json.loads((KIT / "dev/specs/imaginary-c.json").read_text(encoding="utf-8"))
chook = generate.build(cspec, ctools, "v1")["nodes"]["identity"]["tools"][0]["pre_process_code"]
ctf = cspec["tool_fields"]["verify_identity"]
for q in cspec["identity"]["questions"]:
    said = {"digits": "zero one two three four five six seven", "year": "nineteen ninety-eight", "date": "3 May 2001", "number": "one two", "text": "ab"}[q["value_type"]]
    want = {"digits": "01234567", "year": "1998", "date": "2001-05-03", "number": "12", "text": "ab"}[q["value_type"]]
    body = {ctf["field"]: q["field"], ctf["answer"]: said}
    exec(chook, {"config": {"body": body}, "vars": {}})
    check(f"another bank: {q['field']} ({q['value_type']}) said in words", body[ctf["answer"]], want)

print("\nall good" if not fails else f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
