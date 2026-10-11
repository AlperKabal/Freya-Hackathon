"""What Brief A and Brief B require on a given calendar day, worked out without the builder's date code.

    from expect import biz, spoken, next_business_day, attempt_1, deadline, HOLIDAYS

A plain day-by-day calendar with the holidays read from the brief's own text. The tests and the custom scenarios
compare the generated agent with these values: two independent ways to the same date. Brief values are fixtures
here (dev/), never in builder/.
"""
import datetime as dt, pathlib, re
KIT = pathlib.Path(__file__).resolve().parent.parent

BRIEF = (KIT / "briefs/brief-a.md").read_text(encoding="utf-8")
HOLIDAYS = set(re.findall(r"\d{4}-\d{2}-\d{2}", next(line for line in BRIEF.splitlines() if "holidays" in line and "Business days" in line)))
WD = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MO = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def biz(d):
    """Rule 18: Monday to Friday, except the bank's holidays."""
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def spoken(d):
    return f"{WD[d.weekday()]} {d.day} {MO[d.month - 1]} {d.year}"


def nth_business_day_after(d, n):
    while n:
        d += dt.timedelta(days=1)
        n -= biz(d)
    return d


def next_business_day(d):
    return nth_business_day_after(d, 1)


def last_business_day_of_week(d, weeks_ahead=0):
    x = d - dt.timedelta(days=d.weekday()) + dt.timedelta(days=6 + 7 * weeks_ahead)      # that week's Sunday
    while not biz(x):
        x -= dt.timedelta(days=1)
    return x


def attempt_1(today):
    """Rule 30: the last business day of this week; if today is that day (or it is past), of next week."""
    x = last_business_day_of_week(today)
    return x if x > today else last_business_day_of_week(today, 1)


def band(days_late):
    return "early" if 1 <= days_late <= 7 else "late" if 8 <= days_late <= 45 else None


def deadline(days_late, today):
    """Rule 18: the 12th business day after today for the early band, the 7th for the late band."""
    return nth_business_day_after(today, {"early": 12, "late": 7}[band(days_late)])


def attempts(days_late):
    return {"early": 1, "late": 2}[band(days_late)]


def callback_days(today):
    """Rule 6: today or the next business day."""
    return [today, next_business_day(today)]
