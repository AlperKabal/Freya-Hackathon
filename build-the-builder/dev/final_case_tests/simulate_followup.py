"""Simulated customers for the decisions of the 10 October follow-up session and for the days that depend on `now`.

    python3 dev/final_case_tests/simulate_followup.py                 # all cases
    python3 dev/final_case_tests/simulate_followup.py --only 0,2      # some of them, by position
    python3 dev/final_case_tests/simulate_followup.py --list

Prints every call turn by turn with its tool calls, so a judge's verdict can be checked against what was said.
Needs FREYA_API_KEY (source env.sh) and the slot yasar-exp-date in .freya-agents.json. One simulation at a time.
"""
import json
import pathlib
import sys
import time

kit = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(kit))
import freya

FULL_NAMES = ('Currency names are always said in full (Türk Lirası, Dolar, Euro, İngiliz Sterlini); the assistant never says TL, USD, EUR, GBP '
              'or "Sterlin" without "İngiliz".')
cases = [
    ({'name': 'Follow-up: new card, no statement cut yet',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your credit card statement debt. Listen to the answer. If the assistant offers anything else, say "Hayır, teşekkürler." and end the call.',
      'successCriteria': 'The assistant says there is no statement debt because no statement has been cut yet for the card ending 2020, and may add that the first statement date will be 5 Kasım 2026. '
                         'It never says another date as a statement date or as a payment due date (for example 5 Ekim 2026), and it does not ask about another card.'},
     {'customerNumber': '97631186', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'Follow-up: another card is asked before the offer',
      'prompt': 'You are a Turkish speaking bank customer with two cards. Ask for your card debt. When asked which card, say "Yıldız Pratik". After that reading, if the assistant asks whether you want to hear another card, '
                'say "Evet, Yıldız Fly kartımı da öğrenmek istiyorum." After the second reading decline whatever is offered with "Hayır, teşekkürler." Never ask for the second card on your own.',
      'successCriteria': 'After reading the Yıldız Pratik card (7.300,45 Türk Lirası, minimum 2.920,18; 215 Dolar, minimum 86; due 15 Ekim 2026) the assistant asks whether the customer wants to hear another card BEFORE it offers '
                         'a statement date change or an e-mail. After the Yıldız Fly reading (5.600 Türk Lirası, remaining 3.360; 96,40 Euro) no card is left, so it goes on to the offer. ' + FULL_NAMES},
     {'customerNumber': '97116902', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'Follow-up: the call is on the statement cut day',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your credit card statement debt. Listen to the whole answer, then say "Teşekkürler, başka bir şey istemiyorum."',
      'successCriteria': 'Today is the card\'s statement cut day (5 Kasım 2026). The assistant first says that the statement date is today and the statement will be cut at 00.00, then reads the TOTAL debt of the card '
                         '(9.500 Türk Lirası and 85,20 Euro), not the last statement\'s debt of 12.000 with its minimum. ' + FULL_NAMES},
     {'customerNumber': '95004361', 'now': '2026-11-05T10:30:00+03:00'}),
    ({'name': 'Follow-up: the due date is today',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your credit card statement debt. Listen to the whole answer, then say "Teşekkürler, başka bir şey istemiyorum."',
      'successCriteria': 'The assistant reads the statement debt of the card ending 2000 (12.000 Türk Lirası, minimum 4.800, remaining 9.500, remaining minimum 2.000; 85,20 Euro, minimum 34,10) and says that the payment '
                         'due date is today ("bugün") instead of reading the date. ' + FULL_NAMES},
     {'customerNumber': '95004361', 'now': '2026-10-15T10:30:00+03:00'}),
    ({'name': 'Follow-up: the due date has passed',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your credit card statement debt. Listen to the whole answer, then say "Teşekkürler, başka bir şey istemiyorum."',
      'successCriteria': 'The payment due date of the card ending 1110 (19 Ekim 2026) has passed. The assistant says that the due date has passed and gives the total debt (5.000 Türk Lirası). '
                         'It does not present 19 Ekim 2026 as a date that is still to come. ' + FULL_NAMES},
     {'customerNumber': '96158684', 'now': '2026-10-21T10:30:00+03:00'}),
    ({'name': 'Follow-up: no statement debt, one card',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your credit card statement debt. Listen to the whole answer. If the assistant asks or offers anything, say "Hayır, teşekkürler."',
      'successCriteria': 'The card ending 1250 has no statement debt (it was paid). The assistant says there is no debt from the statement dated 5 Ekim 2026, gives the total debt including coming periods '
                         '(1.250 Türk Lirası) and the due date 15 Ekim 2026, does not ask about another card (there is only one) and sends the caller to the main menu. ' + FULL_NAMES},
     {'customerNumber': '96026000', 'now': '2026-10-12T10:30:00+03:00'}),
]

more = [
    ({'name': 'More: a question outside the flow, then go on',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your card debt and listen. Then ask "Kredi kartı faiz oranı ne kadar?". If the assistant asks whether you want to go to the main menu, say "Hayır, devam edelim, ekstremi e-postama gönderin." When it reads an address and asks, say "Evet, gönderin."',
      'successCriteria': 'The assistant gives no interest rate. It says it cannot help with that and asks whether to transfer to the main menu. After the customer prefers to go on, it continues: it reads the registered address ece.demir@freyabank.example, asks, and sends the statement only after the yes.'},
     {'customerNumber': '92460108', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: wants to pay',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your card debt and listen. Then say "Borcumu şimdi ödemek istiyorum, nasıl ödeyebilirim?"',
      'successCriteria': 'After the debt reading, when the customer wants to pay, the assistant does not explain payment channels: it says it transfers the customer to an agent for the payment and ends with a transfer to a human agent, not to the main menu.'},
     {'customerNumber': '90000001', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: says the debt is wrong',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your card debt and listen. Then say "Bu borç yanlış, ben geçen hafta ödeme yaptım, neden görünmüyor?"',
      'successCriteria': 'The assistant does not argue or explain booking dates. It says an agent will help with this and transfers the customer to a human agent.'},
     {'customerNumber': '98390128', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: another e-mail address',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your card debt. Then ask for the statement by e-mail, but to another address: "Ekstremi yeni.adresim@ornek.example adresine gönderin." If the assistant refuses and offers the registered address, say "Tamam, kayıtlı adrese gönderin, evet."',
      'successCriteria': 'The assistant never sends to the address the customer dictates and does not repeat or accept it. It says the statement can only go to the registered address, asks for confirmation for that address and sends only after a clear yes.'},
     {'customerNumber': '94896459', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: several cards with one name and the same last four digits',
      'prompt': 'You are a Turkish speaking bank customer with several cards. Ask for your card debt. When asked which card, say "Yıldız Pratik". When asked for the last four digits say "dört iki beş üç". When asked for the last six digits say "sıfır sıfır dört iki beş üç". When asked for the card number say "beş dört beş sıfır sıfır sıfır bir iki üç dört beş altı dört iki beş üç". After the reading say "Hayır, teşekkürler" to everything.',
      'successCriteria': 'The assistant asks for the last four digits, then, because two cards share them, for the last six, and then for the card number. It never says back the digits the customer gave and never says more than the last four digits of a card. It then reads the debt of exactly one card ending 4253.'},
     {'customerNumber': '92030487', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: the customer speaks English',
      'prompt': 'You are a bank customer who speaks only English. Say "Hello, I would like to know my credit card statement balance, please." Keep speaking English whatever the assistant says.',
      'successCriteria': 'The assistant does not continue the conversation in English. It says in Turkish that it transfers the caller to the main menu and ends.'},
     {'customerNumber': '94835408', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: the e-mail lookup fails',
      'prompt': 'You are a Turkish speaking bank customer. Ask for your card debt and listen to the answer.',
      'successCriteria': 'The contact.email.get service fails for this customer. The assistant does not invent an address and does not pretend everything worked: it tells the customer it cannot complete the transaction now and transfers to a human agent. It may read the card debt (18.500 Türk Lirası, 650 Dolar, 380 Euro) before that.'},
     {'customerNumber': '92335586', 'now': '2026-10-12T10:30:00+03:00'}),
    ({'name': 'More: a card that cannot be queried and a long address',
      'prompt': 'You are a Turkish speaking bank customer with three cards. Ask for your card debt. When asked which card, say "Yıldız Platinum". After the reading, if asked about another card say "Hayır". Then ask "Ekstremi e-posta ile gönderir misiniz?" and when the assistant asks about the address say "Evet".',
      'successCriteria': 'The assistant reads the Yıldız Platinum card ending 7103 (15.800 Türk Lirası, remaining 12.300). When it asks about the e-mail it does not spell the long address letter by letter: it refers to it in a short form (first letter and provider). It sends only after the yes and says it was sent only on success.'},
     {'customerNumber': '93261864', 'now': '2026-10-12T10:30:00+03:00'}),
]
if '--set' in sys.argv and sys.argv[sys.argv.index('--set') + 1] == 'more':
    cases = more

if '--list' in sys.argv:
    for i, (p, v) in enumerate(cases):
        print(i, p['name'], v)
    sys.exit(0)
if '--only' in sys.argv:
    keep = [int(x) for x in sys.argv[sys.argv.index('--only') + 1].split(',')]
    cases = [cases[i] for i in keep]

agent = json.loads((kit / '.freya-agents.json').read_text())['yasar-exp-date']['agent_id']
created = freya.create_personas([dict(p, tags=['hackathon', 'follow-up']) for p, _ in cases])['personas']
values = {person['id']: case[1] for person, case in zip(created, cases)}
names = {person['id']: case[0]['name'] for person, case in zip(created, cases)}
print('agent', agent, 'personas', len(values), flush=True)
sim_id, iteration_id, status = freya.run_simulation(agent, 'follow-up checks ' + time.strftime('%H:%M'), values, max_seconds=300, concurrency=3)
print('simulation', sim_id, 'status', status, flush=True)
for run in freya.get_iteration(sim_id, iteration_id)['runs']:
    print('\nRUN', names.get(run.get('personaId'), run.get('personaId')), '|', values.get(run.get('personaId')), '|', run.get('outcome'), '|', str(run.get('reason'))[:500], flush=True)
    if not run.get('callId'):
        continue
    for entry in freya.get_call(run['callId']).get('messages', []):
        role = entry.get('role') or entry.get('type') or '?'
        message = entry.get('message') or entry.get('content') or entry.get('text') or ''
        if role in ('assistant', 'user'):
            print(' ', role.upper(), str(message).replace('\n', ' ')[:1500])
        elif role == 'system':
            try:
                event = json.loads(message)
            except (TypeError, ValueError):
                continue
            if event.get('event') == 'function_call_start' and event.get('function') not in ('code_exec', 'end_call'):
                print('  TOOL', event['function'], ((event.get('args') or {}).get('body') or {}).get('data'))
            elif event.get('event') == 'function_call_complete' and event.get('function') not in ('code_exec', 'end_call'):
                data = (event.get('result') or {}).get('data') or {}
                print('  RESULT', event['function'], data.get('http_status'), (data.get('result') or {}).get('returnCode'), (data.get('data') or {}).get('exitState'))
