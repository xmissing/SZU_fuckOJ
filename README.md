# quick_OJ · 自动登录 + AI 刷题控制台

针对 **SZUOJ / OJds_ai** 系 OJ 的自动化工具：AI 识别验证码完成登录，读取进行中的实验与题目，
逐题让大模型生成 C 代码，本地编译验样例后提交，轮询判题结果，失败自动重试。

附带一个原生前端控制台（FastAPI + SSE 实时日志），支持**多站点并存**——每个 OJ 实例
独立账号、独立会话缓存，界面顶部一键切换。

> **免责声明**：仅供个人学习与技术研究（HTTP 接口、验证码识别、LLM 代码生成）。
> 请勿用于刷分、代做、绕过任何教学考核。使用前请确认符合你所在学校的规定。

---

## 特性

- **AI 识别验证码**：原图直送视觉模型，逐张串行，取图→识别→提交全链路 3 秒级
- **多站点切换**：不同 OJ 实例各自独立账号 / 会话 / 实验数据，互不串号
- **端到端自动答题**：AI 出码 → 本地 gcc 编译 + 样例比对 → 提交 → 轮询 → 失败带反馈重试
- **Web 控制台**：SSE 实时日志、题目进度环、实验下拉、随时停止、一键退出登录
- **纯原生前端**：无构建步骤，改完刷新即生效（自带版本号热更新提示）
- **零硬编码凭据**：所有敏感信息走 `config.json` 或环境变量

---

## 快速开始

### 1. 装依赖

```bash
pip install -r requirements.txt
```

> `numpy` / `pillow` / `DrissionPage` 只有 `oj_browser.py`（浏览器版登录、截图）才用得到，
> 只想跑控制台的话可以不装。

还需要本机有 **gcc**（用于本地编译验样例）：

```bash
gcc --version     # Windows 可用 MinGW-w64 / TDM-GCC
```

### 2. 配自己的信息

```bash
cp config.json.example config.json
```

编辑 `config.json`，填账号和 AI 密钥。

**站点地址是内置的，不用改**（两个固定的内网 OJ 实例）：

| 站点键 | 地址 | 说明 |
|---|---|---|
| `62` | `http://172.31.221.62` | 内网，需连校园网 / VPN |
| `61` | `http://172.31.221.61` | 内网，需连校园网 / VPN |

```json
{
  "site": "62",
  "sites": {
    "62": {
      "base": "http://172.31.221.62",
      "name": "站点 1",
      "username": "你的学号",
      "password": "你的密码"
    },
    "61": {
      "base": "http://172.31.221.61",
      "name": "站点 2",
      "username": "另一个学号",
      "password": "另一个密码"
    }
  },
  "api_base": "http://127.0.0.1:7863/v1",
  "api_key": "你的 AI 密钥",
  "model": "cn:deepseek-v4.1-flash",
  "max_retry": 3,
  "limit": 0
}
```

`api_base` 任意 **OpenAI 兼容**端点都行（官方、自建网关、Ollama、one-api 等）。
只有一个 OJ 的话，把 `sites` 里多余的那个删掉，并让 `site` 指向留下的那个即可；
`base` 也能改（比如走反向代理换了域名），界面上的齿轮「站点设置」就是干这个的。

### 3. 启动

```bash
python webapp.py          # 或双击 start_web.bat（Windows）
```

打开 <http://127.0.0.1:17865>，填好学号密码和 AI 密钥，直接点「开始刷题」就行——
没登录会自动登录，登录成功后立刻开始做题；想先确认账号和实验对不对，再点「测试连接」。

`start_web.bat` 会自己找一个装了 `fastapi + uvicorn + requests` 的 Python
（依次试 `py -3` / `python` / `python3`），不用改脚本里的路径。

端口默认 **17865**（故意选了个偏门号，避开 3000 / 5000 / 8000 / 8080 / 8765 这些
天天被别的工具占用的），可换：

```bash
set OJ_PORT=17866 && python webapp.py     # Windows
OJ_PORT=17866 python webapp.py            # Linux / macOS
```

端口被占用时会直接提示「已被占用，多半是已经在跑」，不会甩一坨 `[Errno 10048]`。

---

## 配置项

### 环境变量（优先级高于 `config.json`）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `OJ_AI_KEY` | AI 接口密钥 | 空 |
| `OJ_AI_BASE` | AI 接口地址 | `http://127.0.0.1:7863/v1` |
| `OJ_AI_MODEL` | 生成代码用的模型 | `cn:deepseek-v4.1-flash` |
| `OJ_CAPTCHA_MODEL` | 识别验证码用的视觉模型 | `cn:glm-5v-turbo` |
| `OJ_SITE_BASE` | OJ 地址（命令行模式） | `http://172.31.221.62` |
| `OJ_USER` / `OJ_PASS` | 账号 / 密码（命令行模式） | 空 |
| `OJ_CONTEST_ID` | 限定实验 id（命令行模式） | 空 |

只想临时跑一次、不想落盘写密钥时最方便：

```bash
OJ_AI_KEY=sk-xxx OJ_USER=学号 OJ_PASS=密码 python oj_main.py
```

### config.json

| 字段 | 说明 |
|---|---|
| `site` | 当前站点键（`62` / `61`，可自定义） |
| `sites.<键>.base` | 该站点的 OJ 根地址，末尾斜杠会自动去掉 |
| `sites.<键>.username` / `password` | 该站点的账号 |
| `api_base` / `api_key` / `model` | AI 接口 |
| `max_retry` | 单题最多提交几次 |
| `limit` | 本次最多做几题，`0` = 全部 |

> `config.json` 和 `session_*.json` 已在 `.gitignore` 里。**别把它们提交到仓库**——
> 会话文件里的 `sessionid` 等同于登录凭证。

---

## 命令行用法

```bash
python webapp.py                # Web 控制台（推荐）
python oj_main.py               # 命令行全自动刷题
python oj_browser.py            # 浏览器版登录（可视化 / 截图）
python solve_one.py 130         # 单题调试：自动挑一个进行中的实验
python solve_one.py 130 35      # 单题调试：指定实验 35
python solve_one.py 130 35 -k   # 只生成代码 + 本地验样例，不提交
```

命令行切站点：

```python
import oj_login, oj_main
oj_login.set_site('http://你的OJ地址2')
oj_main.SITE = '61'
oj_main.USERNAME, oj_main.PASSWORD = '学号', '密码'
oj_main.main('all', limit=1)   # 'all' = 全部进行中实验；limit=1 只做一道
```

---

## Web 控制台

左侧两个分类：**控制台** / **API 连接**（视图状态记在 localStorage，刷新后保持）。

**站点选择**

- 顶部是站点大按钮，只显示站号 + 网址，当前站点蓝底白字
- 点一下切换整套上下文：账号密码、会话缓存、实验与题目数据、`config.json` 的 `site`；
  页面标题、侧边栏副标题、账号卡跟着变；运行中按钮置灰
- 旁边徽章显示登录态：`未登录` / `已登录 <昵称>`（悬停看站点与网址）
- 登录后出现 **退出登录**：清掉该站点本地会话缓存，并清空实验与题目展示。
  **OJ 服务端 token 不会因此失效**，只是本地不再复用
- 齿轮 **站点设置** 可改网址，写入 `config.json` 的 `sites[站点].base`，改完需重新「测试连接」

**控制台**

- 顶部 4 个指标卡：题目总数 / 已 AC / 当前题目 / 运行时长
- 中部并排：账号卡（学号、密码、每题重试、本次最多题数）+ 题目进度卡（完成度环 + 可滚动列表）
- 底部运行日志占满剩余高度，支持级别过滤与清屏
- 「测试连接」AI 识别验证码登录，读取进行中实验与完成情况
- 「开始刷题」后台线程跑主流程，SSE 实时推送日志与题目状态
  - **没登录 / 会话过期 → 自动登录，登录成功后直接开始做题**，不用先点「测试连接」；
    登录成功的瞬间右上角徽章会从「未登录」变成「已登录 昵称」
  - 学号密码没填会直接拦下；正在登录时再点会提示「等登录结束」，避免两条登录线程抢验证码
  - 本站有过期会话时会先试着复用，失败才重新登录（省掉一次验证码识别）
- 「停止」当前步骤结束后安全退出
- 实验下拉：多个进行中实验可切换，首项为「全部进行中实验（待做 N 题）」+ 倒计时
- 「本次最多题数」：`1` 只做一道（调试用），`0` 全部做完

**API 连接**（与主流程解耦）

- Base URL / API Key / 模型（带常用模型候选）
- 「测试接口」→ `POST /api/ping`：只发一条最小对话，验证端点、密钥、模型可用，
  返回往返耗时与模型回复，不触碰 OJ 登录
- 「保存配置」写入 `config.json`；输入框改动也会自动保存（防抖 500ms）

前端资源带 `?v=<mtime>` 版本号，`/` 返回 `Cache-Control: no-store`；页面每 15 秒查
`/api/version`，发现前端文件变了就在顶部弹「界面已更新，立即刷新」。

---

## 目录结构

```
quick_OJ/
├── webapp.py              # Web 控制台后端（FastAPI + SSE）
├── oj_main.py             # 主流程：找实验 → 逐题生成 → 验样例 → 提交 → 轮询
├── oj_login.py            # AI 识别验证码 + requests 登录（set_site 切站点）
├── oj_browser.py          # DrissionPage 浏览器版登录（可视化 / 截图）
├── solve_one.py           # 单题调试
├── llm.py                 # AI 接口封装（chat / 代码块提取 / 重试退避）
├── static/                # 前端（原生 HTML/CSS/JS，深蓝主题）
├── config.json.example    # 配置模板，复制成 config.json 再填
├── start_web.bat          # Windows 一键启动
└── requirements.txt
```

运行时生成（已在 `.gitignore`）：`config.json`、`session_<站点>.json`、
`session_<站点>.user`、`work/`（生成的 C 源码与 exe）。

---

## 原理

### 关键接口（实测）

| 用途 | 接口 |
|---|---|
| 验证码 | `POST /api/captcha/` → `{captcha_key, captcha_image(base64)}` |
| 登录 | `POST /api/user/login/` `{username, password, captcha_key, captcha_value}` |
| 我的班级 | `GET /api/groups/` |
| 实验列表 | `GET /api/contests/`（`begin_time` / `end_time` 判断进行中） |
| 实验详情 + 题目 | `GET /api/contests/{id}/` → `problem_json["0"]` |
| 我的提交 | `GET /api/code-submission/?contest={id}&search={学号}` |
| 提交代码 | `POST /api/code-submission/` `{code, language:"c", contest, problem}` |
| 判题结果 | `GET /api/code-submission/{id}/` → `status`, `result.data[]` |

控制台自身接口：`/api/config`、`/api/sites`、`/api/status`、`/api/stream`(SSE)、
`/api/test`（登录并读实验）、`/api/ping`（只测 AI）、`/api/run`、`/api/stop`、
`/api/logout`（清本地会话）、`/api/version`（前端版本号）。

判题状态码：`0=AC`、`1=部分通过`、`-1=WA`、`-2=RE`、`-3=TLE`、`-4=MLE`、`4=CE`、`8=系统错误`。
**`5/6/7` 是排队 / 判题中，必须继续等**——早期版本误判成失败，导致重复提交。

### 验证码方案

1. 请求 `/api/captcha/` 拿 base64 PNG（约 90×40，4 位字符）
2. **原图直送，不放大**：这个尺寸本来就清晰；放大 5 倍后 PNG 从 ~2KB 涨到 ~21KB（8.5 倍），
   视觉 token 更多，只会更慢
3. 交给视觉专用快模型（如 `cn:glm-5v-turbo`），`max_tokens=64`。
   **不要用推理模型**：推理模型会先想几百个 token，同一张图实测 8~45s，
   而视觉快模型只要 **1.1~1.5s**
4. **逐张串行**：取一张 → 立刻识别 → 立刻提交，最多 5 次

### 为什么不能并发批量（关键教训）

验证码的**有效期只有 20~40 秒**。实测证据：

| 单次 AI 耗时 | 取图到提交 | 结果 |
|---|---|---|
| 20.2s | 20.2s | ✅ 200 登录成功 |
| 44.7s | 44.8s | ❌ 400 `Invalid captcha value` |

所以「一次取 3 张并发识别」的做法，最慢那张回来时已经过期；再叠加慢模型，
一批全过期 → 全报 `Invalid captcha value` → 很容易误以为「识别不准」。
真相是**识别没错，是提交太晚，验证码已经作废**。

### 网关并发上限（另一个坑）

自建 AI 网关的账号池通常只有两三路，一次并发 6 个请求会有一半直接
`503 {"error":{"code":"no_healthy_account"}}`；拿不到 `choices` 又容易被 `except`
吞成一行无信息的 `KeyError: 'choices'`。现在遇 `503/429` 会指数退避（1.2s→2.4s→4.8s），
串行之后并发压力自然消失。

### 实测效果

| 场景 | 旧方案（推理模型 + 5 倍放大 + 并发） | 新方案（视觉快模型 + 原图 + 串行） |
|---|---|---|
| 站点 A 登录 | 60~95s，且经常失败 | **2.6~5s** |
| 站点 B 登录 | 120s，多数失败 | 30~45s（该站验证码干扰强，要试 3~4 次） |

### 浏览器版注意

`oj_browser.py` **必须让页面自己发验证码请求**（点击图片并监听响应），
否则前端 state 里的 `captcha_key` 与你通过 XHR 拿到的不是同一个，必然报
`Invalid captcha value`。

---

## 常见问题

**双击 `start_web.bat` 闪一下就没了 / 说找不到 Python**
脚本按 `py -3` → `python` → `python3` 的顺序找一个**装了依赖**的解释器，都没找到就停住并提示。
装依赖：`pip install -r requirements.txt`；机器上多套 Python 时直接指定：
`"C:\Python313\python.exe" webapp.py`。脚本里没有任何个人路径。

**启动后提示「端口 17865 已被占用」**
已经有一个控制台在跑（或者被别的程序占了）。直接开 <http://127.0.0.1:17865>，
或者 `set OJ_PORT=17866 && python webapp.py` 换端口。
**注意不要同时开两个控制台**——它们共用同一份 `config.json`，并发写会把配置搅乱。

**登录一直 `Invalid captcha value`**
识别慢或网络慢导致验证码过期。确认用的是视觉快模型、没有并发批量、机器到 OJ 的延迟正常。

**`no_healthy_account` / 503**
AI 网关账号池被打满了。降低并发（本工具现在默认串行），或换一个 `api_base`。

**一直停在「排队中」**
判题队列堵了，不是代码错了。状态码 `5/6/7` 要等，别重复提交。

**`gcc: command not found`**
本地验样例依赖 gcc，装 MinGW-w64 并把 `bin` 加进 PATH；不想装也可以不管，
只是失去提交前的样例自检。

**换站点后账号串了**
每个站点必须有独立的 `sites.<键>`，`session_<站点>.json` 会自动隔离。
如果 `config.json` 已经写串，直接手改回去。

---

## License

[MIT](LICENSE)
