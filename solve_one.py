# -*- coding: utf-8 -*-
"""单题端到端：AI 出码 -> 本地编译验样例 -> 提交 -> 轮询判题

用法：
    python solve_one.py <题目id>               # 自动挑一个进行中的实验
    python solve_one.py <题目id> <实验id>       # 指定实验
    python solve_one.py <题目id> <实验id> -k    # 只生成 + 本地验样例，不提交
"""
import html, json, os, re, subprocess, sys, time

import llm
import oj_login
from oj_main import active_contests, get_session

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work')
os.makedirs(WORK, exist_ok=True)


def _ojs():
    """当前站点的 /api 前缀（运行时读取，支持中途切站点）"""
    return oj_login.OJS


def strip_html(t):
    return html.unescape(re.sub(r'<[^>]+>', '', t or '')).strip()


def build_prompt(p):
    return f"""你是 ACM 竞赛选手。请用 **C 语言**（C99，标准输入输出）解决下面的题目。

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
{p['sample_input'][0] if p['sample_input'] else ''}```
## 样例输出
```
{p['sample_output'][0] if p['sample_output'] else ''}```

要求：
1. 只输出一个完整可编译的 C 程序，用 ```c 代码块包裹。
2. 不要 printf 任何提示语，严格按题目格式输出（包括行尾空格、空行）。
3. 读取全部输入（多组数据），不要假设输入组数固定以外的格式。
4. 不要用 freopen 读文件，只用 stdin/stdout。
"""


def run_local(code, sample_in, p):
    src = os.path.join(WORK, f"p{p['id']}.c")
    exe = os.path.join(WORK, f"p{p['id']}.exe")
    open(src, 'w', encoding='utf-8').write(code)
    r = subprocess.run(['gcc', '-O2', '-std=c99', '-o', exe, src],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None, 'COMPILE ERROR:\n' + r.stderr[:800]
    try:
        r2 = subprocess.run([exe], input=sample_in, capture_output=True, text=True,
                            timeout=10, encoding='utf-8', errors='replace')
        return r2.stdout, None
    except subprocess.TimeoutExpired:
        return None, 'LOCAL TIMEOUT'


def submit(s, contest, problem_id, code, lang='c'):
    r = s.post(f'{_ojs()}/code-submission/', json={
        'code': code, 'language': lang, 'contest': contest, 'problem': problem_id}, timeout=30)
    print('  submit:', r.status_code, r.text[:300])
    return r.json() if r.status_code in (200, 201) else None


def poll(s, sub_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = s.get(f'{_ojs()}/code-submission/{sub_id}/', timeout=20)
        if r.status_code == 200:
            d = r.json()
            st = d.get('status')
            if st not in ('pending', 'judging', 'Pending', None, -99):
                return d
        time.sleep(2)
    return None


def pick_problem(s, pid, contest_id=0):
    """从 OJ 实时拉题目，不再依赖本地缓存文件"""
    if not contest_id:
        cs = active_contests(s)
        if not cs:
            raise SystemExit('没有进行中的实验，请先在网页里开始一个实验或手动指定实验 id')
        contest_id = cs[0]['id']
        print('实验:', contest_id, cs[0].get('title', ''))
    r = s.get(f'{_ojs()}/contests/{contest_id}/', timeout=20)
    r.raise_for_status()
    problems = r.json().get('problem_json', {}).get('0', [])
    hit = [x for x in problems if str(x['id']) == str(pid)]
    if not hit:
        raise SystemExit(f'实验 {contest_id} 里没有题目 {pid}')
    return contest_id, hit[0]


if __name__ == '__main__':
    argv = sys.argv[1:]
    keep_only = '-k' in argv
    nums = [a for a in argv if not a.startswith('-')]
    if not nums:
        raise SystemExit('用法: python solve_one.py <题目id> [实验id] [-k]')
    pid = int(nums[0])
    contest_id = int(nums[1]) if len(nums) > 1 else int(os.getenv('OJ_CONTEST_ID', '0') or 0)

    s = get_session()
    contest_id, p = pick_problem(s, pid, contest_id)
    print('题目:', p['title'])

    ans = llm.chat(build_prompt(p))
    code = llm.extract_code(ans)
    print('--- 代码 ---')
    print(code[:1500])

    out, err = run_local(code, p['sample_input'][0] if p['sample_input'] else '', p)
    print('--- 本地运行 ---')
    print('ERR:', err)
    print('OUT:', repr(out))
    want = p['sample_output'][0] if p['sample_output'] else ''
    print('期望:', repr(want))
    if out is not None:
        print('样例一致:', out.strip() == want.strip())

    if keep_only:
        sys.exit(0)

    sub = submit(s, contest_id, p['id'], code)
    if sub:
        print('提交 id', sub.get('id'), 'status', sub.get('status'))
        d = poll(s, sub['id'])
        print('判题结果:', json.dumps(d, ensure_ascii=False)[:600] if d else 'TIMEOUT')
