"""An identity answer in the form the bank's tool reads.

    value = normalize_answer(kind, answer, hint)

`kind` is the answer's TYPE from the SPEC (date, digits, year, number, text), which the Reader takes from the tool
API's own description of the answer; the field's name plays no part. `hint` is that description in words (the
SPEC's answer_format and conversion), read only for what it says about letter case, spaces and the order of a date
given in numbers. Runs inside the verify tool's pre-hook on the platform and locally in tests: only re; no double
braces; never raises. The rule everywhere: an answer that is already in the right form goes out unchanged, and an
answer this code is not sure about goes out exactly as the model wrote it.
"""
import datetime as _dt
import re as _re

_ONES = {"zero": 0, "oh": 0, "o": 0, "nought": 0, "nil": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
        "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
        "twentieth": 20, "thirtieth": 30}
_MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_REPEAT = {"double": 2, "triple": 3, "treble": 3}


def _is_number_word(w):
    return w in _ONES or w in _TEENS or w in _TENS or w in _REPEAT or w in ("hundred", "thousand", "and")


def spoken_digits(words):
    """Number words said one after the other, as the digits they spell: ['four', 'four', 'seven', 'one'] -> '4471',
    ['forty', 'four', 'seventy', 'one'] -> '4471', ['double', 'four', 'oh', 'one'] -> '4401',
    ['nineteen', 'eighty', 'eight'] -> '1988', ['two', 'thousand', 'and', 'one'] -> '2001'. None if a word is no number."""
    words = [w for w in words if w != "and" or "hundred" in words or "thousand" in words]
    if not words or not all(_is_number_word(w) for w in words):
        return None
    if "hundred" in words or "thousand" in words:                 # a number said as a number: its value
        total, cur = 0, 0
        for w in words:
            if w in _ONES: cur += _ONES[w]
            elif w in _TEENS: cur += _TEENS[w]
            elif w in _TENS: cur += _TENS[w]
            elif w == "hundred": cur = (cur or 1) * 100
            elif w == "thousand": total, cur = total + (cur or 1) * 1000, 0
            elif w in _REPEAT: return None
        return str(total + cur)
    out, i = "", 0
    while i < len(words):
        w = words[i]
        if w in _REPEAT:
            if i + 1 >= len(words) or words[i + 1] not in _ONES:
                return None
            out += str(_ONES[words[i + 1]]) * _REPEAT[w]
            i += 2
        elif w in _TENS:
            if i + 1 < len(words) and words[i + 1] in _ONES and _ONES[words[i + 1]] > 0 and words[i + 1] not in ("oh", "o"):
                out += str(_TENS[w] + _ONES[words[i + 1]])
                i += 2
            else:
                out += str(_TENS[w])
                i += 1
        else:
            out += str(_ONES[w] if w in _ONES else _TEENS[w])
            i += 1
    return out


def _tokens(text):
    return _re.findall(r"[a-z]+|\d+", str(text or "").lower().replace("-", " "))


def _digits(answer):
    """Digits only. Words count when the answer is nothing but number words."""
    if _re.search(r"\d", answer):
        return _re.sub(r"\D", "", answer)
    return spoken_digits(_re.findall(r"[a-z]+", answer.lower().replace("-", " "))) or answer


def _year(answer):
    m = _re.search(r"(?<!\d)(\d{4})(?!\d)", answer)
    if m:
        return m.group(1)
    words, best = _re.findall(r"[a-z]+", answer.lower().replace("-", " ")), None
    i = 0
    while i < len(words):                                         # the longest run of number words that spells a year
        j = i
        while j < len(words) and _is_number_word(words[j]):
            j += 1
        if j > i:
            y = spoken_digits(words[i:j])
            if y and len(y) == 4 and 1900 <= int(y) <= 2100:
                best = y
            i = j
        else:
            i += 1
    return best or answer


def _day_number(words):
    """A day of the month said in words: ['fourteenth'] -> 14, ['twenty', 'first'] -> 21, ['three'] -> 3."""
    if len(words) == 1:
        w = words[0]
        return _ORD.get(w) or (_ONES.get(w) or None) or _TEENS.get(w) or _TENS.get(w)
    if len(words) == 2 and words[0] in _TENS:
        tail = _ORD.get(words[1]) if words[1] in _ORD and _ORD[words[1]] < 10 else (_ONES.get(words[1]) or None)
        return _TENS[words[0]] + tail if tail else None
    return None


def _iso(y, m, d):
    try:
        return _dt.date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def _date(answer, hint):
    a = answer.strip()
    m = _re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", a)
    if m:
        return _iso(m.group(1), m.group(2), m.group(3)) or answer
    low = a.lower()
    month = next((i + 1 for i, name in enumerate(_MONTH_NAMES) if _re.search(r"\b" + name + r"\b|\b" + name[:3] + r"\b\.?", low)), None)
    if month:                                                     # a month said as a word leaves nothing to guess
        toks = [t for t in _tokens(_re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", low)) if t not in ("of", "the", "on", "in", "year")]
        idx = next(i for i, t in enumerate(toks) if t == _MONTH_NAMES[month - 1] or t == _MONTH_NAMES[month - 1][:3])
        rest = toks[:idx] + ["|"] + toks[idx + 1:]
        year = next((t for t in rest if t.isdigit() and len(t) == 4), None)
        nums = [int(t) for t in rest if t.isdigit() and len(t) <= 2]
        day = next((n for n in nums if 1 <= n <= 31), None)
        words = [t for t in rest if t.isalpha()]
        if day is None or year is None:                           # the day or the year in words
            runs, cur = [], []
            for t in rest:
                if t.isalpha() and (_is_number_word(t) or t in _ORD):
                    cur.append(t)
                    if t in _ORD:                                 # an ordinal ends a day: "fourteenth | nineteen eighty-eight"
                        runs.append(cur); cur = []
                else:
                    if cur: runs.append(cur)
                    cur = []
            if cur: runs.append(cur)
            for run in runs:
                if day is None and _day_number(run):
                    day = _day_number(run)
                elif year is None:
                    y = spoken_digits([w for w in run if w not in _ORD])
                    if y and len(y) == 4:
                        year = y
        return (_iso(year, month, day) if day and year else None) or answer
    m = _re.fullmatch(r"\D*(\d{1,2})\s*[-/. ]\s*(\d{1,2})\s*[-/. ]\s*(\d{4})\D*", a)
    if m:                                                         # numbers only: the order the documents give, when it reads as a date
        first, second, year = int(m.group(1)), int(m.group(2)), m.group(3)
        month_first = bool(_re.search(r"month[, ]+(?:then )?(?:the )?day|month first|mm[-/. ]dd", str(hint or "").lower()))
        day, mon = (second, first) if month_first else (first, second)
        return _iso(year, mon, day) or answer
    return answer


def normalize_answer(kind, answer, hint=""):
    try:
        a = str(answer if answer is not None else "").strip()
        if not a:
            return answer
        if kind in ("digits", "number"):
            return _digits(a)
        if kind == "year":
            return _year(a)
        if kind == "date":
            return _date(a, hint)
        if kind == "text":
            h = str(hint or "").lower()
            a = _re.sub(r"\s+", " ", a)
            if _re.search(r"no spaces?|without (?:a |any )?spaces?", h):
                a = a.replace(" ", "")
            if _re.search(r"upper[- ]?case|capital letters|in capitals", h):
                a = a.upper()
            return a
        return answer
    except Exception:
        return answer


_HOW_MANY = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}


def digits_wanted(kind, hint=""):
    """How many digits a complete answer has, when its type or its description says so; else None."""
    if kind == "year":
        return 4
    if kind not in ("digits", "number"):
        return None
    m = _re.search(r"\b(\d{1,2}|" + "|".join(_HOW_MANY) + r")[- ](?:digits?|numbers?|figures?)\b", str(hint or "").lower())
    if not m:
        return None
    return int(m.group(1)) if m.group(1).isdigit() else _HOW_MANY[m.group(1)]


def whole_answer(kind, earlier, answer, hint=""):
    """An answer given in two turns ('44' then '71'; '14 March' then '1988'; 'nineteen' then 'eighty-eight').
    -> (the value to send, the part to keep for the next call). `earlier` is the part kept by the call before, ''
    if none. Two parts are joined only when the latest alone is not a complete answer and the two together are one:
    an answer that is complete by itself goes out as normalize_answer() gives it. Never raises."""
    value = normalize_answer(kind, answer, hint)
    try:
        earlier, v = str(earlier or ""), str(value)
        n = digits_wanted(kind, hint)
        done = {"date": r"\d{4}-\d{2}-\d{2}", "year": r"\d{4}"}.get(kind)
        if (done and _re.fullmatch(done, v)) or (n and v.isdigit() and len(v) >= n):
            return value, ""                                       # complete by itself
        if n and v.isdigit() and earlier.isdigit() and len(earlier) + len(v) == n:
            return earlier + v, ""
        if done and earlier:
            both = normalize_answer(kind, earlier + " " + str(answer), hint)
            if _re.fullmatch(done, str(both)):
                return both, ""
        if done:
            return value, str(answer)[:60]
        if n and v.isdigit():
            return value, v
        return value, ""
    except Exception:
        return value, ""
