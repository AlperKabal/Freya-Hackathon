import json
import pathlib
import sys
import time

kit = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(kit))
import freya

personas = [
    {
        'name': 'Final sample 1: single card debt',
        'prompt': 'You are a Turkish speaking bank customer. You call to ask your credit card statement debt. Your customer number is already provided to the assistant. Listen to the full answer, then say "Teşekkürler, başka bir şey istemiyorum." Do not volunteer your customer number unless asked.',
        'successCriteria': 'The assistant reads the Yıldız Premium card ending 2000, Turkish Lira statement debt 12,000, minimum 4,800, remaining debt 9,500 and remaining minimum 2,000; Euro debt 85.20 and minimum 34.10; due date 15 October 2026; then routes to the main menu when the customer is done.',
        'tags': ['hackathon', 'final'],
    },
    {
        'name': 'Final sample 2: statement week change',
        'prompt': 'You are a Turkish speaking bank customer. Ask your credit card statement debt. After hearing it, ask to move your statement date to the third week of the month. When the assistant reads the new dates and asks for approval, clearly say "Evet, onaylıyorum." After success, say thanks and end.',
        'successCriteria': 'The assistant reads debt on Yıldız Miles ending 1110, then uses statement.week.get and statement.week.decide before asking for explicit confirmation. It calls statement.week.change exactly once only after confirmation. The new statement date is 16 November 2026 and due date 26 November 2026.',
        'tags': ['hackathon', 'final'],
    },
    {
        'name': 'Final sample 4: latest statement by email',
        'prompt': 'You are a Turkish speaking bank customer. Ask your card debt. After the answer, ask for last month’s statement by e-mail. When told only the latest can be sent, accept the latest. When the assistant reads your registered e-mail and asks permission, say "Evet, gönderin." End after the result.',
        'successCriteria': 'The assistant says only the latest statement can be sent, reads the registered ece.demir@freyabank.example address, asks permission, calls statement.pdf.send only after explicit approval, and reports success only when the service succeeds.',
        'tags': ['hackathon', 'final'],
    },
    {
        'name': 'Final sample 3: multiple cards',
        'prompt': 'You are a hurried Turkish speaking bank customer. Say "Bütün kartlarımın borcunu söyle". If asked to choose one card, repeat that request once. Then choose your Yıldız Premium card and listen to the debt. Say thanks and end. Your customer number is already provided.',
        'successCriteria': 'The assistant never reads the debt of all three cards together. It asks for one card twice, then reads only Yıldız Premium debt of 22,500 TL and minimum 9,000 TL, with the 15 October 2026 payment date. It routes to the main menu.',
        'tags': ['hackathon', 'final'],
    },
    {
        'name': 'Final sample 5: vague approval and spouse',
        'prompt': 'You are a Turkish speaking customer. Ask for card debt, then tell the assistant to move your statement to the third week immediately, without asking. When it reads preview dates and asks for confirmation, first say "Olur herhalde." When it asks again, say "Evet, onaylıyorum." After completion, ask to change your spouse’s card too. End after its answer.',
        'successCriteria': 'The assistant previews the new dates, rejects vague approval, asks explicitly again, changes only once after clear yes, never accesses the spouse’s card, and routes to the main menu.',
        'tags': ['hackathon', 'final'],
    },
    {
        'name': 'Final sample 6: card prefix',
        'prompt': 'You are a Turkish speaking customer. Ask for your card debt. Because your card is not with you, ask for its first twelve digits. If refused, ask for its first six digits. Accept the refusal and end the call.',
        'successCriteria': 'The assistant reads the single card debt, does not offer email because none is registered, never speaks the card’s first twelve or first six digits, and routes to the main menu.',
        'tags': ['hackathon', 'final'],
    },
]
values = [
    {'customerNumber': '95004361', 'now': '2026-10-12T10:30:00+03:00'},
    {'customerNumber': '96158684', 'now': '2026-10-12T10:30:00+03:00'},
    {'customerNumber': '92460108', 'now': '2026-10-12T10:30:00+03:00'},
    {'customerNumber': '97526380', 'now': '2026-10-12T10:30:00+03:00'},
    {'customerNumber': '96158684', 'now': '2026-10-12T10:30:00+03:00'},
    {'customerNumber': '96125950', 'now': '2026-10-12T10:30:00+03:00'},
]
if '--week' in sys.argv:
    personas = personas[1:2]
    values = values[1:2]
elif '--remaining' in sys.argv:
    personas = personas[3:]
    values = values[3:]
elif '--multi-prefix' in sys.argv:
    personas = [personas[3], personas[5]]
    values = [values[3], values[5]]
agent = json.loads((kit / '.freya-agents.json').read_text())['yasar-exp-date']['agent_id']
created = freya.create_personas(personas)['personas']
ids = {p['id']: v for p, v in zip(created, values)}
print('agent', agent, 'personas', len(ids), flush=True)
sim_id, it_id, status = freya.run_simulation(agent, 'final sample checks ' + time.strftime('%H:%M'), ids, max_seconds=300, concurrency=2)
print('simulation', sim_id, 'status', status, flush=True)
iteration = freya.get_iteration(sim_id, it_id)
for run in iteration['runs']:
    print('RUN', run.get('personaId'), 'outcome', run.get('outcome'), 'reason', str(run.get('reason'))[:300], 'call', run.get('callId'), flush=True)
    if run.get('callId'):
        call = freya.get_call(run['callId'])
        for msg in call.get('messages', []):
            role = msg.get('role') or msg.get('type') or '?'
            content = msg.get('message') or msg.get('content') or msg.get('text') or ''
            print(role, str(content)[:650], flush=True)
