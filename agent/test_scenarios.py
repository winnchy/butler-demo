"""21场景自动化测试"""
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

EMOJI_STARTERS = set('🥇🥈🥉⭐📍💰🏷💡✅⚠🎯🚗🚕🚇🚲🚶🌡👔🎒🌧☀☂🌩🍽🛵🍜🎬🔔📅📋🚘⏱🎫🔑📢👶🐶💊🏥🏪🅿🌤⚡🔴🟡🟢📌🍴👵🏠🍲🧧💊🩺🧹🗑📝🔎📊📈🏃💨')

def check_reply(reply):
    lines = [l.strip() for l in reply.split('\n') if l.strip()]
    if not lines:
        return 0, {'空回复': True}
    issues = {}
    first_line_emoji = lines[0][0] in EMOJI_STARTERS if lines[0] else False
    if not first_line_emoji:
        issues['首行缺emoji'] = lines[0][:40] if lines[0] else '空'
    emoji_lines = sum(1 for l in lines[:10] if l and l[0] in EMOJI_STARTERS)
    if emoji_lines < min(3, len(lines)):
        issues['emoji覆盖率低'] = f'{emoji_lines}/{min(10, len(lines))}'
    last_line = lines[-1].strip() if lines else ''
    if last_line.endswith('？') or last_line.endswith('?'):
        issues['结尾问句'] = last_line[-30:]
    if '王总' in reply:
        issues['王总幻觉'] = True
    import re
    leak_kw = ['数据查询','让我回顾','我先查','帮你调','Mock后端','未找到匹配','数据库没记录','让我再试','扩大范围','后端.*连不上','工具调用失败']
    for kw in leak_kw:
        if re.search(kw, reply):
            issues[f'泄露({kw})'] = True
    if '**' in reply:
        issues['Markdown加粗'] = True
    if '```' in reply:
        issues['代码块'] = True
    if reply.count('🥇') > 1:
        issues['多个🥇'] = reply.count('🥇')
    score = 5 - len(issues)
    return max(0, score), issues

print('=' * 70)
print('21 SCENARIO TEST — ' + time.strftime('%H:%M:%S'))
print('=' * 70)

results = []
for sid in sorted(SCENARIO_SCRIPTS.keys(), key=int):
    s = SCENARIO_SCRIPTS[sid]
    uid, title, opener = s['user'], s['title'], s['opener']
    user_name = {'white_collar':'小琴','parent':'小冉','student':'小晴'}[uid]
    mode, reply = chat(opener, uid, 120)
    score, issues = check_reply(reply)
    if score == 5: status = 'OK'
    elif score >= 3: status = 'WARN'
    else: status = 'FAIL'
    print(f'{status} S{sid:>2s} [{user_name}] {title[:22]:22s} | {mode:16s} | {len(reply):>4d}ch | {score}/5')
    if issues:
        for k, v in issues.items():
            print(f'     {k}: {str(v)[:80]}')
    results.append((sid, user_name, mode, score, issues, len(reply)))
    time.sleep(1.5)

print()
print('=' * 70)
print('SUMMARY')
print('=' * 70)
perfect = sum(1 for _,_,_,s,_,_ in results if s == 5)
good = sum(1 for _,_,_,s,_,_ in results if s == 4)
ok = sum(1 for _,_,_,s,_,_ in results if s == 3)
bad = sum(1 for _,_,_,s,_,_ in results if s <= 2)
print(f'Perfect(5)={perfect} Good(4)={good} OK(3)={ok} Bad(<=2)={bad} / 21')
issue_counts = {}
for _,_,_,_,issues,_ in results:
    for k in issues:
        issue_counts[k] = issue_counts.get(k, 0) + 1
print('Issue frequency:')
for k, v in sorted(issue_counts.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v}/21')
