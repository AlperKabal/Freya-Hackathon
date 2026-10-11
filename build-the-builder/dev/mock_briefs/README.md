# Mock briefs

Briefs we wrote to test the builder on rules it has not seen. None of them is an organiser brief, and nothing in
this folder may be copied into `builder/`. Only new files were added; no existing file was changed.

    python dev/test_mock_briefs.py                 # every customer of every pack, no key and no model, about 10 s
    python dev/test_mock_briefs.py --only D-65 -v  # one customer: what the agent said, and the ledger
    python dev/mock_briefs/make.py                 # rewrite the generated files after a change

## The packs

| Pack | Form | What it stresses |
|---|---|---|
| `d-harbor-raw` | raw bank material: an e-mail, a handbook extract, a memo that changes five rules, a code list (`;`-separated, quoted cells, one row the assistant never uses) | consumer bank; identity `postcode` + `birth_year`; outcome `unreached`; every tool field renamed; OpenAPI 3.1 with `$ref` and `allOf`; three bands; a calendar-day deadline rolled back; year-end closure days; a weekend day is refused, not replaced; a product without a minimum; up to three accounts. 91 customers |
| `e-meridian-clean` | one clean specification, 56 rules | business bank; identity `company_number` (leading zero) + `founded_year`; outcome `no_contact`; the API answers `success`, not `ok`, and never says how many tries are left; Saturday is a business day; a month-end deadline; a band with no persuasion attempt; half of the amount; attempts counted for the whole call; a refused facility gets no note; no retry; a callback the contact asks for; `local_time` with a space. 84 customers |
| `f-freya-sibling` | the kit's Brief A and B with twelve rules changed, on the kit's own tool API | the only pack that can be simulated on the platform (each customer borrows a practice customer, has a persona text and judge criteria). 23 customers |

The identity questions and the outcome names of D and E are not guesses: `tools/run_cases.py` of the kit already
knows the answers `postcode`, `birth_year`, `company_number` and `founded_year`, its `in_words` style says
"Postcodes, years and other codes you say digit by digit", and `tools/score.py` knows the outcomes `no_contact`
and `unreached`.

Each pack has the documents, `tool-api.json`, `spec.json` (the oracle: what a careful reader takes from the
documents; written in `make.py`), and `cases.py`. `lib.py` holds what is independent of the builder: a day-by-day
calendar (`Cal`), a stand-in for the bank that speaks the pack's own field names (`Bank`), and a walker that runs a
whole call through the generated workflow (`Sim`): every code node, hook, engine-run bank call and deterministic
transition is run for real; what the phone model would do is given by the case.

## Findings on commit 92b2a45 (orch mode), most important first

Found by the walker; the first two were confirmed on the team's own `dev/specs/brief-ab.json`.

1. **Tier 1. "I already paid" on the last open product: the required sentence is never said** (D-65, E-58, F-16).
   With notes on (every Brief B kind of brief), the product-scope situation's sentence is put in front of the next
   offer; when no product is left the call closes at once and the sentence is lost. The ledger is right, the
   judge's sentence check is not. Brief A's agent is not affected (notes off: the sentence is in the farewell).
2. **Tier 1. The last recording failure is never told to the customer when no promise was recorded** (D-61, E-50).
   `finalize` adds `failure_say` only when there is no `outcomes.multi` rule; with one, the farewell is the plain
   goodbye. The customer hears the retry sentence and then goodbye.
3. **Tier 1. A code said character by character is sent as words** (D-14): "L S six, two A B" goes to the bank as
   `LSSIX,TWOAB`. `normalize_answer("text", ...)` neither turns number words into digits nor drops punctuation
   (D-15, tier 2: "LS6, 2AB." is sent as `LS6,2AB.`). The model may convert it first; the hook is the net.
4. **Tier 2. An evidence word that is part of a product name is dropped** (D-69): "person" is in "personal loan",
   so "Can I speak to a real person?" is not acted on the first time, and a persuasion attempt is used instead.
5. **Tier 2. A day that is refused, not replaced** (`non_business_day: reject`, `after_deadline: reject`; D-34s,
   E-40, D-89): the agent says "That day is not possible." and then repeats its open offer, which names today,
   instead of asking for another day. For several products (D-89) it also uses up attempt 1 of the first product.
6. **Tier 2. Half of an odd amount** (E-44): `round(212.625, 2)` is 212.62; a scorer that rounds half up expects
   212.63.

A question for the team, not a finding: `dev/specs/brief-ab.json` gives `not_talking` no note. Brief B rule 8 says
every product without a promise is noted, "also when no product gets a promise". Pack D states this case
explicitly (3.9 f) and the generated agent follows it there.

## Not done yet (the session ran out)

- `dev/run_mock_briefs.py`: extract each pack with the model, compare the SPEC with the oracle, and simulate pack F
  on the platform. Until it exists: `python builder/build.py dev/mock_briefs/d-harbor-raw/*.md
  dev/mock_briefs/d-harbor-raw/4-code-list.csv dev/mock_briefs/d-harbor-raw/tool-api.json --slot mock-d --no-save`,
  then `python dev/compare_specs.py dev/mock_briefs/d-harbor-raw/spec.json out/mock-d.spec.json`.
- One-rule variations of pack E, a SPEC matrix with random customers, document and API form tests.
