# -*- coding: utf-8 -*-
"""
OJ 自动刷题 Web 控制台
    python webapp.py   ->  http://127.0.0.1:17865   （换端口：set OJ_PORT=xxxxx）
"""
import asyncio, io, json, os, queue, sys, threading, time, traceback

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import llm
import oj_login
import oj_main
from oj_login import OJLogin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_FILE = os.path.join(BASE_DIR, 'config.json')
LOG_FILE = os.path.join(BASE_DIR, 'run.log')

# 支持切换的站点（改成你自己的 OJ 地址）
SITE_META = {
    '62': {'base': 'http://oj.example.com', 'name': '站点 1'},
    '61': {'base': 'http://oj2.example.com', 'name': '站点 2'},
}

DEFAULT_CFG = {
    'site': '62',
    'sites': {
        '62': {'base': 'http://oj.example.com', 'name': '站点 1',
               'username': '', 'password': ''},
        '61': {'base': 'http://oj2.example.com', 'name': '站点 2',
               'username': '', 'password': ''},
    },
    'api_base': 'http://127.0.0.1:7863/v1',
    'api_key': '',          # 填你自己的密钥，或设环境变量 OJ_AI_KEY
    'model': 'cn:deepseek-v4.1-flash',
    'max_retry': 3,
    'limit': 0,            # 单次最多做几题，0 = 全部
    'contest_id': None,
}

app = FastAPI(title='OJ Auto Console')

LOGS = []                      # [(ts, level, text)]
SUBSCRIBERS = set()            # Queue
STATE_LOCK = threading.Lock()
LOGIN_LOCK = threading.Lock()   # 同一时刻只允许一个「测试连接」登录在跑
STATE = {
    'running': False,
    'site': '62',
    'contest': None,
    'problems': [],
    'current': None,
    'done': 0,
    'total': 0,
    'started_at': None,
    'finished_at': None,
    'error': None,
    'summary': None,
}

LOG_MAX = 4000


# ---------------- 配置 ----------------
def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))     # 深拷贝，别改到默认值
    if os.path.exists(CFG_FILE):
        try:
            raw = json.load(open(CFG_FILE, encoding='utf-8'))
        except Exception:
            raw = {}
        # 兼容老格式（顶层 username/password）
        if 'sites' not in raw and raw.get('username'):
            cfg['sites']['62']['username'] = raw['username']
            cfg['sites']['62']['password'] = raw.get('password', '')
        for k, v in raw.items():
            if k == 'sites' and isinstance(v, dict):
                for sk, sv in v.items():
                    cfg['sites'].setdefault(sk, {}).update(sv or {})
            elif k in DEFAULT_CFG and k != 'sites':
                cfg[k] = v
    # 补齐站点元信息
    for sk, meta in SITE_META.items():
        cfg['sites'].setdefault(sk, {}).setdefault('base', meta['base'])
        cfg['sites'][sk].setdefault('name', meta['name'])
    if cfg.get('site') not in cfg['sites']:
        cfg['site'] = '62'
    return cfg


def save_cfg(cfg):
    json.dump(cfg, open(CFG_FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def apply_cfg(cfg, site=None):
    """把配置同步进 oj_main / oj_login / llm"""
    site = str(site or cfg.get('site') or '62')
    info = cfg.get('sites', {}).get(site, {})
    base = (info.get('base') or SITE_META.get(site, {}).get('base') or 'http://oj.example.com')
    oj_login.set_site(base)
    oj_main.SITE = site
    oj_main.USERNAME = info.get('username', '')
    oj_main.PASSWORD = info.get('password', '')
    oj_main.MAX_RETRY = int(cfg.get('max_retry') or 3)
    oj_main.LIMIT = int(cfg.get('limit') or 0)
    llm.BASE = (cfg.get('api_base') or llm.BASE).rstrip('/')
    llm.KEY = cfg.get('api_key') or llm.KEY
    llm.MODEL = cfg.get('model') or llm.MODEL
    return site


# ---------------- 日志与广播 ----------------
ORIG_STDOUT = sys.stdout


def log(text, level='info'):
    ts = time.strftime('%H:%M:%S')
    item = {'type': 'log', 'ts': ts, 'level': level, 'text': text}
    LOGS.append(item)
    if len(LOGS) > LOG_MAX:
        del LOGS[:len(LOGS) - LOG_MAX]
    publish(item)


def publish(msg):
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def push_state():
    with STATE_LOCK:
        snap = json.loads(json.dumps(STATE, ensure_ascii=False))
    publish({'type': 'state', **snap})


class LogWriter(io.TextIOBase):
    """把 print 输出切成行 -> 日志流"""

    def __init__(self):
        self.buf = ''
        self.echo = True

    def writable(self):
        return True

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            if line.strip():
                log(line.rstrip(), self._level(line))
                if self.echo:
                    try:
                        ORIG_STDOUT.write(line + '\n')
                        ORIG_STDOUT.flush()
                    except Exception:
                        pass
        return len(s)

    def flush(self):
        if self.buf.strip():
            log(self.buf.rstrip(), self._level(self.buf))
            self.buf = ''

    @staticmethod
    def _level(line):
        low = line.lower()
        if 'error' in low or '失败' in line or '未通过' in line:
            return 'error'
        if 'warn' in low or '超时' in line or '重试' in line:
            return 'warn'
        if 'ac' in low or '成功' in line or '🎉' in line:
            return 'success'
        return 'info'


# ---------------- 事件处理 ----------------
def on_event(kind, data):
    global STATE
    if kind == 'contest':
        STATE['contest'] = {'id': data.get('id'), 'title': data.get('title'),
                            'end_time': data.get('end_time')}
        if data.get('site'):
            STATE['site'] = data.get('site')
        STATE['total'] = data.get('total', 0)
        STATE['done'] = 0
    elif kind == 'problems':
        STATE['problems'] = data.get('list', [])
        STATE['done'] = sum(1 for p in STATE['problems'] if p.get('state') == 'ac')
    elif kind == 'problem_start':
        STATE['current'] = {'id': data.get('id'), 'title': data.get('title')}
        for p in STATE['problems']:
            if p['id'] == data.get('id'):
                p['state'] = 'running'
    elif kind == 'problem_result':
        for p in STATE['problems']:
            if p['id'] == data.get('id'):
                p['state'] = data.get('state', 'failed')
        STATE['done'] = sum(1 for p in STATE['problems'] if p.get('state') == 'ac')
        if STATE['current'] and STATE['current'].get('id') == data.get('id'):
            STATE['current'] = None
    elif kind == 'judged':
        for p in STATE['problems']:
            if p['id'] == data.get('id'):
                p['last_status'] = data.get('name')
    elif kind == 'done':
        STATE['summary'] = {'ac': data.get('ac'), 'total': data.get('total')}
    push_state()


oj_main.EVENT_HOOK = on_event


# ---------------- 任务线程 ----------------
def run_job(contest_id=None, site='62', limit=0):
    writer = LogWriter()
    old = sys.stdout
    sys.stdout = writer
    try:
        STATE.update({'running': True, 'started_at': time.time(), 'finished_at': None,
                      'error': None, 'summary': None, 'current': None, 'site': site})
        push_state()
        log(f'=== 任务开始（站点 {site}）===', 'success')
        oj_main.STOP_FLAG = False
        oj_main.main(contest_id, limit=limit)
        log('=== 任务结束 ===', 'success')
    except SystemExit as e:
        log(f'任务终止: {e}', 'warn')
    except Exception as e:
        STATE['error'] = str(e)
        log(f'任务异常: {e}', 'error')
        log(traceback.format_exc()[:1500], 'error')
    finally:
        writer.flush()
        sys.stdout = old
        STATE['running'] = False
        STATE['finished_at'] = time.time()
        push_state()


def login_once(cfg, site):
    """独立登录，返回 session（供预览/测试）

    同一时刻只允许一个登录在跑。否则连点「测试连接」会叠出好几条登录线程：
    它们一起抢 AI 网关（503 更多），日志还会互相穿插——上一次登录的
    `Invalid captcha value` 会打印到下一次任务的日志中间，看起来像任务挂了。
    """
    if not LOGIN_LOCK.acquire(blocking=False):
        return None, '上一个登录还在进行中，请稍等（约 1~2 分钟）'
    try:
        site = apply_cfg(cfg, site)
        info = cfg['sites'][site]
        _drop_session(site)
        lg = OJLogin(info.get('username', ''), info.get('password', ''))
        log(f'[测试] {oj_login.SITE_BASE} · AI 识别验证码登录中...', 'info')
        if not lg.login():
            return None, '登录失败（验证码多次未通过或被限流）'
        oj_main.save_session(lg.s.cookies.get_dict())
        return lg.s, None
    finally:
        LOGIN_LOCK.release()


def ping_ai(cfg):
    """最小成本试探 AI 接口是否可用"""
    apply_cfg(cfg)
    t0 = time.time()
    # 推理模型会先消耗 thinking token，max_tokens 给足否则 content 为空
    reply = llm.chat('只回复两个字：可用', max_tokens=2000, temperature=0, timeout=90)
    return reply.strip()[:80], time.time() - t0


def merge_cfg(cur, inc):
    """把前端提交的配置合并进当前配置（支持 sites 部分更新）"""
    if not isinstance(inc, dict):
        return cur
    if inc.get('site') is not None:
        cur['site'] = str(inc['site'])
    for k, v in inc.items():
        if k == 'sites' and isinstance(v, dict):
            for sk, sv in v.items():
                cur['sites'].setdefault(str(sk), {}).update(sv or {})
        elif k in DEFAULT_CFG and k != 'sites':
            cur[k] = v
    return cur


# ---------------- API ----------------
@app.get('/api/config')
def api_get_config():
    return load_cfg()


@app.post('/api/config')
async def api_set_config(req: Request):
    cfg = await req.json()
    cur = merge_cfg(load_cfg(), cfg)
    save_cfg(cur)
    return {'ok': True, 'config': cur}


@app.get('/api/sites')
def api_sites():
    cfg = load_cfg()
    return {'site': cfg['site'], 'sites': cfg['sites'], 'meta': SITE_META}


@app.get('/api/status')
def api_status():
    with STATE_LOCK:
        snap = json.loads(json.dumps(STATE, ensure_ascii=False))
    snap['logs'] = LOGS[-200:]
    return snap


@app.post('/api/test')
async def api_test(req: Request):
    cfg = await req.json()
    cur = merge_cfg(load_cfg(), cfg)
    save_cfg(cur)
    site = apply_cfg(cur, cfg.get('site'))
    if STATE['running']:
        return JSONResponse({'ok': False, 'msg': '任务运行中，无法测试'}, status_code=400)
    try:
        s, err = await asyncio.get_event_loop().run_in_executor(None, login_once, cur, site)
        if err:
            return {'ok': False, 'msg': err}
        prof = s.get(f'{oj_login.OJS}/user/profile/', timeout=10).json()
        log(f"[测试] {site} 登录成功: {prof.get('nickname')}", 'success')
        contests = oj_main.active_contests(s)
        out = []
        for c in contests:
            d = s.get(f'{oj_login.OJS}/contests/{c["id"]}/', timeout=20).json()
            ps = d['problem_json'].get('0', [])
            ac, _ = oj_main.my_ac(s, c['id'])
            out.append({'id': c['id'], 'title': c['title'],
                        'begin_time': c.get('begin_time'), 'end_time': c.get('end_time'),
                        'problems': [{'id': p['id'], 'title': p['title'],
                                      'state': 'ac' if p['id'] in ac else 'todo'} for p in ps]})
        # 优先展示还有未做题的，同级按 id 升序（题库按 顺序→选择→循环 排列）
        out.sort(key=lambda x: (sum(1 for p in x['problems'] if p['state'] != 'ac') == 0,
                                x['end_time'] or '', x['id']))
        if out:
            STATE['site'] = site
            STATE['contest'] = out[0]
            STATE['problems'] = out[0]['problems']
            STATE['total'] = len(out[0]['problems'])
            STATE['done'] = sum(1 for p in out[0]['problems'] if p['state'] == 'ac')
            push_state()
        return {'ok': True, 'site': site, 'user': prof.get('nickname'),
                'nickname': prof.get('nickname'), 'base': oj_login.SITE_BASE, 'contests': out}
    except Exception as e:
        log(f'[测试] 失败: {e}', 'error')
        return {'ok': False, 'msg': str(e)}


@app.post('/api/ping')
async def api_ping(req: Request):
    """只测 AI 接口连通性，不碰 OJ 登录"""
    cfg = await req.json()
    cur = merge_cfg(load_cfg(), cfg)
    save_cfg(cur)
    try:
        reply, cost = await asyncio.get_event_loop().run_in_executor(None, ping_ai, cur)
        log(f'[接口] {cur["model"]} 连通正常 {cost:.1f}s', 'success')
        return {'ok': True, 'model': cur['model'], 'reply': reply, 'cost': round(cost, 1)}
    except Exception as e:
        log(f'[接口] 连通失败: {e}', 'error')
        return {'ok': False, 'msg': str(e)[:300]}


@app.post('/api/run')
async def api_run(req: Request):
    cfg = await req.json()
    cur = merge_cfg(load_cfg(), cfg)
    save_cfg(cur)
    site = apply_cfg(cur, cfg.get('site'))
    if STATE['running']:
        return {'ok': False, 'msg': '任务已在运行'}
    limit = int(cur.get('limit') or 0)
    threading.Thread(target=run_job, args=(cur.get('contest_id'), site, limit), daemon=True).start()
    return {'ok': True, 'site': site, 'limit': limit}


@app.post('/api/stop')
def api_stop():
    oj_main.STOP_FLAG = True
    log('已请求停止，等待当前步骤结束...', 'warn')
    return {'ok': True}


def ui_version():
    """静态资源的版本号（取三者最新 mtime），用来破缓存 + 提示前台刷新"""
    try:
        files = ('index.html', 'app.js', 'styles.css')
        return str(int(max(os.path.getmtime(os.path.join(BASE_DIR, 'static', f)) for f in files)))
    except Exception:
        return '0'


@app.get('/api/version')
def api_version():
    return {'ver': ui_version()}


def _drop_session(site):
    """清除本地会话缓存：删 → 改名 → 清空，三级降级（部分环境禁止直接删文件）"""
    done = []
    for name in (f'session_{site}.json', f'session_{site}.user'):
        path = os.path.join(BASE_DIR, name)
        off = path + '.off'
        # 先清掉上次降级改名留下的 .off，别让它在目录里越堆越多
        if os.path.exists(off):
            try:
                os.remove(off)
            except Exception:
                pass
        if not os.path.exists(path):
            continue
        for act in ('deleted', 'renamed', 'cleared'):
            try:
                if act == 'deleted':
                    os.remove(path)
                elif act == 'renamed':
                    os.replace(path, off)
                else:
                    open(path, 'w', encoding='utf-8').write('{}')
                done.append(f'{name}:{act}')
                break
            except Exception:
                continue
        else:
            return None, f'{name} 清不掉（删除/改名/清空均失败）'
    return done, None


@app.post('/api/logout')
async def api_logout(req: Request):
    """退出登录：只清本地会话缓存（OJ 侧 token 不会主动失效）"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if STATE.get('running'):
        return {'ok': False, 'msg': '任务运行中，先停止再退出登录'}
    site = str((body or {}).get('site') or load_cfg().get('site') or '62')
    removed, err = _drop_session(site)
    if err:
        log(f'[退出] {err}', 'error')
        return {'ok': False, 'msg': err}
    log(f"[退出] 站点 {site} 本地会话已清除：{removed or '本来就没有缓存'}", 'warn')
    return {'ok': True, 'site': site, 'removed': removed}


@app.get('/api/stream')
async def api_stream(request: Request):
    async def gen():
        q = queue.Queue()
        SUBSCRIBERS.add(q)
        try:
            for item in list(LOGS)[-300:]:
                yield f'data: {json.dumps(item, ensure_ascii=False)}\n\n'
            with STATE_LOCK:
                snap = json.loads(json.dumps(STATE, ensure_ascii=False))
            yield f'data: {json.dumps({"type": "state", **snap}, ensure_ascii=False)}\n\n'
            last_ping = time.time()
            while True:
                if await request.is_disconnected():
                    break
                got = False
                while True:
                    try:
                        msg = q.get_nowait()
                    except queue.Empty:
                        break
                    got = True
                    yield f'data: {json.dumps(msg, ensure_ascii=False)}\n\n'
                if not got:
                    await asyncio.sleep(0.25)
                if time.time() - last_ping > 15:
                    last_ping = time.time()
                    yield ': ping\n\n'
        finally:
            SUBSCRIBERS.discard(q)

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/')
def index():
    p = os.path.join(BASE_DIR, 'static', 'index.html')
    html = open(p, encoding='utf-8').read().replace('?v=0', '?v=' + ui_version())
    return HTMLResponse(html, headers={'Cache-Control': 'no-store, must-revalidate'})


app.mount('/static', StaticFiles(directory=os.path.join(BASE_DIR, 'static')), name='static')


if __name__ == '__main__':
    import socket
    import threading
    import webbrowser
    import uvicorn

    PORT = int(os.environ.get('OJ_PORT', '17865'))
    URL = f'http://127.0.0.1:{PORT}'

    # 端口占用时给一句人话，而不是甩一坨 [Errno 10048]
    with socket.socket() as _s:
        try:
            _s.bind(('127.0.0.1', PORT))
        except OSError:
            print(f'[错误] 端口 {PORT} 已被占用 —— 多半是控制台已经在跑。')
            print(f'       直接打开 {URL} 看；或换个端口：')
            print(f'           set OJ_PORT={PORT + 1} && python webapp.py      (Windows)')
            print(f'           OJ_PORT={PORT + 1} python webapp.py             (Linux/macOS)')
            raise SystemExit(2)

    print(f'控制台: {URL}')
    if os.environ.get('OJ_NO_BROWSER') != '1':
        threading.Timer(1.5, lambda: webbrowser.open(URL)).start()
    uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='warning')
