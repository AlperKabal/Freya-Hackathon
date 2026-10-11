import json
import pathlib
import sys

kit = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(kit))
import freya

for sim_id in sys.argv[1:]:
    items = freya.api('GET', f'/api/v2/simulations/{sim_id}/iterations')
    iterations = items.get('iterations') or items.get('items') or items
    iteration = freya.get_iteration(sim_id, iterations[0]['id'])
    print('SIM', sim_id)
    for run in iteration['runs']:
        print('RUN', run.get('outcome'), run.get('callId'))
        if not run.get('callId'):
            continue
        for entry in freya.get_call(run['callId']).get('messages', []):
            role = entry.get('role') or entry.get('type') or '?'
            message = entry.get('message') or entry.get('content') or entry.get('text') or ''
            if role in ('assistant', 'user'):
                print(role.upper(), str(message).replace('\n', ' ')[:1800])
            elif role == 'system':
                try:
                    event = json.loads(message)
                except (TypeError, ValueError):
                    continue
                if event.get('event') == 'function_call_start' and event.get('function') not in ('code_exec', 'end_call'):
                    args = event.get('args') or {}
                    print('TOOL', event['function'], (args.get('body') or {}).get('data'))
                elif event.get('event') == 'function_call_complete' and event.get('function') not in ('code_exec', 'end_call'):
                    result = event.get('result') or {}
                    data = result.get('data') or {}
                    print('RESULT', event['function'], data.get('http_status'), (data.get('result') or {}).get('returnCode'), (data.get('data') or {}).get('exitState'))
