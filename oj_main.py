# -*- coding: utf-8 -*-
"""
OJ 自动刷题主程序
1. AI 识别验证码登录
2. 找到未结束的实验（按 begin_time / end_time 判断）
3. 逐题：AI 生成 C 代码 -> 本地编译验样例 -> 提交 -> 轮询判题 -> 失败重试
"""
import html, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

import llm
import oj_login
from oj_login import OJLogin

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')
os.makedirs(WORK, exist_ok=True)
# 凭据不写死：命令行 / 网页会把 config.json 里的值注入这里
USERNAME, PASSWORD = os.getenv('OJ_USER', ''), os.getenv('OJ_PASS', '')
SITE = '62'          # 站点标识（对应 config.json 里的 sites 键）
LIMIT = 0            # 单次最多做几题，0 = 全部


def _ojs():
    """当前站点的 /api 前缀（运行时读取，支持切站点）"""
    return oj_login.OJS


def _sess_files():
    """会话缓存按站点隔离，避免 61/62 互相串号"""
    return f'session_{SITE}.json', f'session_{SITE}.user'

STATUS_NAME = {0: 'Accepted', 1: 'Partial Accepted', -1: 'Wrong Answer', -2: 'Runtime Error',
               -3: 'Time Limit Exceeded', -4: 'Memory Limit Exceeded', 4: 'Compile Error',
               8: 'System Error', -99: 'Pending'}


def strip_html(t):
    return html.unescape(re.sub(r'<[^>]+>', '', t or '')).strip()


# ---------------- 登录 ----------------
def save_session(cookies_dict):
    sf, su = _sess_files()
    json.dump(cookies_dict, open(sf, 'w'))
    open(su, 'w', encoding='utf-8').write(USERNAME)


def get_session():
    import requests
    sf, su = _sess_files()
    if os.path.exists(sf):
        cached_user = ''
        try:
            cached_user = open(su, encoding='utf-8').read().strip()
        except Exception:
            pass
        use_cache = (not cached_user) or cached_user == USERNAME
        if not use_cache:
            print(f'[登录] 缓存会话属于 {cached_user}，当前 {USERNAME}，重新登录')
        else:
            d = json.load(open(sf))
            s = requests.Session()
            s.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': oj_login.SITE_BASE + '/',
                              'Content-Type': 'application/json',
                              'x-csrftoken': d.get('csrftoken', '')})
            s.cookies.update(d)
            try:
                r = s.get(f'{_ojs()}/user/profile/', timeout=10)
                if r.status_code == 200:
                    print(f'[登录] 复用会话: {r.json().get("nickname")}')
                    return s
            except Exception:
                pass
    lg = OJLogin(USERNAME, PASSWORD)
    print('[登录] AI 识别验证码中...')
    if not lg.login():
        raise SystemExit('登录失败')
    save_session(lg.s.cookies.get_dict())
    return lg.s


# ---------------- 实验 / 题目 ----------------
def active_contests(s):
    """进行中 = 已开始且未结束"""
    cs = s.get(f'{_ojs()}/contests/', params={'limit': 50}, timeout=20).json()['results']
    now = datetime.now(timezone.utc)
    out = []
    for c in cs:
        try:
            begin = datetime.fromisoformat(c['begin_time'].replace('Z', '+00:00'))
        except Exception:
            begin = now
        end = datetime.fromisoformat(c['end_time'].replace('Z', '+00:00'))
        if begin <= now < end:
            out.append(c)
    return out


def my_ac(s, contest_id):
    r = s.get(f'{_ojs()}/code-submission/', params={
        'contest': contest_id, 'search': USERNAME, 'limit': 200}, timeout=20)
    subs = r.json().get('results', [])
    return {x['problem'] for x in subs if x['status'] == 0}, subs


# ---------------- 代码生成 ----------------
def build_prompt(p, feedback=None):
    si = p['sample_input'][0] if p['sample_input'] else ''
    so = p['sample_output'][0] if p['sample_output'] else ''
    base = f"""你是 ACM 竞赛选手。请用 **C 语言**（C99，标准输入输出）解决下面的题目。

## 题目：{p['title']}
{strip_html(p['description'])}

## 输入
{strip_html(p['input_description'])}

## 输出
{strip_html(p['output_description'])}

## 提示
{strip_html(p['hint'])}

## 样例输入
```
{si}```
## 样例输出
```
{so}```

要求：
1. 只输出一个完整可编译的 C 程序，用 ```c 代码块包裹。
2. 不要输出任何提示语，严格按题目格式（包括行尾空格、换行）。
3. 读取全部输入（可能多组数据），只使用 stdin/stdout。
"""
    if feedback:
        base += f"""
## 上一次提交失败，请修正后重新给出完整代码
{feedback}
"""
    return base


def run_local(code, sample_in, pid):
    src = os.path.join(WORK, f'p{pid}.c')
    exe = os.path.join(WORK, f'p{pid}.exe')
    open(src, 'w', encoding='utf-8').write(code)
    r = subprocess.run(['gcc', '-O2', '-std=c99', '-o', exe, src],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, r.stderr[:800]
    try:
        r2 = subprocess.run([exe], input=sample_in, capture_output=True, text=True,
                            timeout=10, encoding='utf-8', errors='replace')
        return r2.stdout, None
    except subprocess.TimeoutExpired:
        return None, 'LOCAL_TIMEOUT'


def submit(s, contest, pid, code):
    r = s.post(f'{_ojs()}/code-submission/', json={
        'code': code, 'language': 'c', 'contest': contest, 'problem': pid}, timeout=30)
    if r.status_code in (200, 201):
        return r.json()
    print('   提交失败:', r.status_code, r.text[:200])
    return None


PENDING = {None, 5, 6, 7}   # 5/6/7 = 排队 / 判题中


def poll(s, sid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = s.get(f'{_ojs()}/code-submission/{sid}/', timeout=20)
        if r.status_code == 200:
            d = r.json()
            if d.get('status') not in PENDING and d.get('result') is not None:
                return d
        time.sleep(3)
    return None


def feedback_of(d):
    st = d.get('status')
    name = STATUS_NAME.get(st, str(st))
    lines = [f'判题结果: {name} (status={st})']
    res = d.get('result') or {}
    if res.get('err'):
        lines.append(f"错误信息: {str(res['err'])[:800]}")
    for case in res.get('data', []) or []:
        if case.get('result') != 0:
            lines.append(f"测试点 {case.get('test_case')}: result={case.get('result')} "
                         f"error={case.get('error')} cpu={case.get('cpu_time')}ms "
                         f"mem={case.get('memory')}")
            if case.get('output'):
                lines.append(f"  实际输出片段: {str(case['output'])[:300]}")
    return '\n'.join(lines)


# ---------------- 事件钩子（供 Web 控制台消费） ----------------
EVENT_HOOK = None      # callable(kind: str, data: dict)
STOP_FLAG = False
MAX_RETRY = 3


def emit(kind, **data):
    if EVENT_HOOK:
        try:
            EVENT_HOOK(kind, data)
        except Exception:
            pass


# ---------------- 主流程 ----------------
def solve_problem(s, contest, p, max_try=None):
    if max_try is None:
        max_try = MAX_RETRY
    pid, title = p['id'], p['title']
    print(f'\n=== [{pid}] {title}')
    emit('problem_start', id=pid, title=title)
    feedback = None
    for attempt in range(1, max_try + 1):
        if STOP_FLAG:
            print('   已手动停止')
            emit('problem_result', id=pid, state='stopped', name='已停止')
            return False
        print(f'  第 {attempt} 次生成中...', flush=True)
        emit('attempt', id=pid, attempt=attempt, max=max_try)
        try:
            code = llm.extract_code(llm.chat(build_prompt(p, feedback)))
        except Exception as e:
            print('   AI 失败:', e)
            continue
        out, cerr = run_local(code, p['sample_input'][0] if p['sample_input'] else '', pid)
        if cerr:
            print('   本地编译/运行问题:', cerr[:300])
            feedback = f'本地编译错误：\n{cerr[:600]}'
            continue
        expect = (p['sample_output'][0] if p['sample_output'] else '').strip()
        if out.strip() != expect:
            print('   样例不符，实际:', repr(out[:200]), '期望:', repr(expect[:200]))
            feedback = (f'本地样例运行结果与标准答案不一致。\n实际输出:\n{out[:500]}\n'
                        f'期望输出:\n{expect[:500]}')
            continue
        print('   样例通过，提交...')
        emit('submitting', id=pid)
        sub = submit(s, contest, pid, code)
        if not sub:
            continue
        d = poll(s, sub['id'])
        if not d:
            print('   判题超时')
            continue
        st = d.get('status')
        name = STATUS_NAME.get(st, f'status={st}')
        print(f'   判题: {name} (id={sub["id"]})')
        emit('judged', id=pid, status=st, name=name, submission=sub['id'])
        if st == 0:
            open(os.path.join(WORK, f'p{pid}_ac.c'), 'w', encoding='utf-8').write(code)
            emit('problem_result', id=pid, state='ac', name='AC', submission=sub['id'])
            return True
        feedback = feedback_of(d)
        print('   反馈:', feedback[:400])
    emit('problem_result', id=pid, state='failed', name='未通过')
    return False


def run_contest(s, cid, limit=0):
    """跑一个实验，返回 (实际尝试题数, AC 数, 总题数)"""
    detail = s.get(f'{_ojs()}/contests/{cid}/', timeout=20).json()
    problems = detail['problem_json'].get('0', [])
    print(f'[题目] {detail["title"]} 共 {len(problems)} 题')

    ac, _ = my_ac(s, cid)
    print(f'[进度] 已 AC {len(ac)} 题')
    emit('contest', id=cid, title=detail['title'], site=SITE,
         end_time=detail.get('end_time'), total=len(problems))
    emit('problems', list=[{'id': p['id'], 'title': p['title'],
                            'state': 'ac' if p['id'] in ac else 'todo'} for p in problems])

    todo = [p for p in problems if p['id'] not in ac]
    print(f'[待做] {len(todo)} 题' + (f'，本次最多 {limit} 题' if limit else ''))
    emit('todo', count=len(todo), limit=limit)
    if not todo:
        print('全部已完成 🎉')
        emit('done', ac=len(ac), total=len(problems))
        return 0, len(ac), len(problems)

    if limit and limit > 0:
        todo = todo[:limit]

    used = 0
    for p in todo:
        if STOP_FLAG:
            print('已手动停止')
            break
        solve_problem(s, cid, p)
        used += 1

    ac2, subs2 = my_ac(s, cid)
    tried = {x['problem'] for x in subs2}
    print('\n========== 总结 ==========')
    for p in problems:
        if p['id'] in ac2:
            mark = 'AC'
        elif p['id'] in tried:
            mark = '已提交未通过'
        else:
            mark = '未做'
        print(f"  [{p['id']}] {p['title']}: {mark}")
    emit('done', ac=len(ac2), total=len(problems),
         results=[{'id': p['id'], 'title': p['title'],
                   'state': 'ac' if p['id'] in ac2 else ('failed' if p['id'] in tried else 'todo')}
                  for p in problems])
    return used, len(ac2), len(problems)


def main(contest_id=None, limit=None):
    if limit is None:
        limit = LIMIT
    print(f'[站点] {oj_login.SITE_BASE}  账号 {USERNAME}')
    s = get_session()
    contests = active_contests(s)
    if not contests:
        raise SystemExit('没有进行中的实验')
    print('[实验] 进行中:', [(c['id'], c['title']) for c in contests])

    key = '' if contest_id is None else str(contest_id).lower()
    if key == 'all':
        targets = sorted(c['id'] for c in contests)
        print(f'[计划] 全部进行中实验，共 {len(targets)} 个：{targets}')
    elif key in ('', 'none'):
        targets = [contests[0]['id']]
    else:
        targets = [int(contest_id)]

    left = limit or 0
    for i, cid in enumerate(targets):
        if STOP_FLAG:
            print('已手动停止')
            break
        if len(targets) > 1:
            print(f'\n######## 实验 {i + 1}/{len(targets)}：#{cid} ########')
        used, _, _ = run_contest(s, cid, left)
        if left:
            left = max(0, left - used)
            if left == 0:
                print(f'[上限] 本次已完成 {limit} 题，停止')
                break


if __name__ == '__main__':
    main()
