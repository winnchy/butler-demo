import urllib.request, json, io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from agent.scenario_scripts import SCENARIO_SCRIPTS

def chat(msg, uid, t=90):
    data = json.dumps({'message':msg,'user_id':uid}).encode()
    req = urllib.request.Request('https://butler-agent-production.up.railway.app/chat', data=data, headers={'Content-Type':'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=t)
        d = json.loads(resp.read().decode())
        return d.get('mode','?'), d.get('reply','')
    except Exception as e:
        return 'error', str(e)[:100]

EMOJI_STARTERS = set('🥇🥈🥉⭐📍💰🏷💡✅⚠🎯🚗🚕🚇🚲🚶🌡👔🎒🌧☀☂🌩🍽🛵🍜🎬🔔📅📋🚘⏱🎫🔑📢👶🐶💊🏥🏪🅿')

print('=' * 60)
print('21 SCENARIO TEST')
print('=' * 60)

results = []
for sid in sorted(SCENARIO_SCRIPTS.keys(), key=int):
    s = SCENARIO_SCRIPTS[sid]
    uid = s['user']
    title = s['title']
    opener = s['opener']
    user_name = {'white_collar':'小琴','parent':'小冉','student':'小晴'}[uid]

    mode, reply = chat(opener, uid, 120)

    first_line = reply.split('\n')[0].strip() if reply else ''
    has_emoji = len(first_line) > 0 and first_line[0] in EMOJI_STARTERS if first_line else False
    no_wang = '王总' not in reply
    no_q_end = not reply.strip().endswith('？')
    no_leak = all(kw not in reply for kw in ['数据查询','让我回顾','我先查','帮你调','Mock后端','未找到匹配'])
    no_md = '**' not in reply

    score = sum([has_emoji, no_wang, no_q_end, no_leak, no_md])

    issues = []
    if not has_emoji: issues.append('缺emoji')
    if not no_wang: issues.append('王总幻觉')
    if not no_q_end: issues.append('结尾问句')
    if not no_leak: issues.append('系统泄露')
    if not no_md: issues.append('Markdown')

    status = 'OK' if score >= 4 else ('WARN' if score >= 3 else 'FAIL')

    line = f'{status} S{sid:>2s} [{user_name}] {title[:20]:20s} | mode={mode:12s} len={len(reply):>4d} | emoji={has_emoji} no_w={no_wang} no_q={no_q_end} no_l={no_leak} no_md={no_md}'
    if issues:
        line += f' | {issues}'
    print(line)
    results.append((sid, status, score, issues))
    time.sleep(1)

print()
print('SUMMARY:')
ok = sum(1 for _,s,_,_ in results if s == 'OK')
warn = sum(1 for _,s,_,_ in results if s == 'WARN')
fail = sum(1 for _,s,_,_ in results if s == 'FAIL')
print(f'OK={ok} WARN={warn} FAIL={fail} / 21')
if fail > 0:
    print('FAIL scenarios:')
    for sid, s, sc, iss in results:
        if s == 'FAIL':
            print(f'  S{sid}: score={sc} issues={iss}')
