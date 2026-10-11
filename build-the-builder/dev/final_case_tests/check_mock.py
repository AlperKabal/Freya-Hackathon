import concurrent.futures
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

base = sys.argv[1].rstrip('/')
root = json.loads((Path(__file__).resolve().parents[2] / 'final-case-input/test-environment/test-customers.json').read_text())
selected = set(sys.argv[2:])
jobs = []
for customer in root['customers']:
    number = customer['customerNo']
    if selected and number not in selected:
        continue
    services = customer['services']
    cards = list((services.get('cards.balance') or {}).keys())
    for name, entry in services.items():
        if name == 'cards.list':
            jobs.append((number, name, {'customerNo': number, 'aiFlow': 'CardOps'}, entry))
        elif name == 'contact.email.get':
            jobs.append((number, name, {'customerNo': number, 'intAddressInfoType': 'E'}, entry))
        elif name == 'statement.pdf.send':
            jobs.append((number, name, {'customerNo': number, 'cardNumber': cards[0] if cards else 'unknown', 'currencyType': 'TL', 'statementDate': '05.10.2026', 'emailAddress': 'test@example.com'}, entry))
        elif name in ('cards.balance', 'statement.week.get'):
            jobs.extend((number, name, {'cardNumber': card}, answer) for card, answer in entry.items())
        else:
            jobs.extend((number, name, {'cardNumber': card, 'newStatementWeek': int(week), 'statementDay': 5}, answer) for card, weeks in entry.items() for week, answer in weeks.items())

def check(job):
    number, name, data, expected = job
    request = urllib.request.Request(base + '/voice/v1/' + name,
        data=json.dumps({'data': data, 'call': {'ani': '', 'lang': 'tr'}}).encode(),
        headers={'content-type': 'application/json', 'User-Agent': 'Freya-Agent'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, body = response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        status, body = error.code, json.loads(error.read())
    return (status == expected['http'] and body == expected['response'], number, name, status, expected['http'])

with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
    results = list(pool.map(check, jobs))
failures = [result for result in results if not result[0]]
print(f'{len(jobs) - len(failures)}/{len(jobs)} exact HTTP status and JSON matches')
for failure in failures[:20]:
    print('FAIL', failure)
sys.exit(bool(failures))
