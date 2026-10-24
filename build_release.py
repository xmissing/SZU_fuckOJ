# -*- coding: utf-8 -*-
"""构建「解压即用」分发包：把 Python 运行时一起塞进 zip，机器上什么都不用装。

用法
    python build_release.py            只打包（要求 runtime/ 已就绪）
    python build_release.py --setup    先补 runtime（下嵌入式 Python + pip 装依赖），再打包

注意：本脚本必须用 Python 3.11 跑 —— runtime 里放的是 3.11，
用 3.12/3.13 装出来的 wheel 是 cp312/cp313，二进制不兼容，装进去也 import 不了。
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(ROOT, 'runtime')
DL = os.path.join(ROOT, '_dl')
PY_VER = '3.11.9'
EMBED_URL = f'https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip'
PKGS = ['fastapi', 'uvicorn', 'requests']

# 打进包里的东西（白名单，避免把 config.json / session / work 带出去）
INCLUDE_FILES = [
    'llm.py', 'oj_login.py', 'oj_main.py', 'oj_browser.py', 'solve_one.py', 'webapp.py',
    'start_web.bat', 'config.json.example', 'requirements.txt',
    'README.md', 'LICENSE', '.gitignore', '.gitattributes',
]
INCLUDE_DIRS = ['static', 'runtime']
# 无论在哪都跳过
SKIP_DIRS = {'__pycache__', 'work', '.git', '_dl'}
# 只跳字节码。千万别把 .zip 往这里加：嵌入式 Python 的标准库就在 runtime/python311.zip，
# 排掉它等于把运行时砍了半条命 —— 症状是包里的 python.exe 起不来，bat 悄悄退回系统 Python，
# 在你自己的机器上看不出问题，别人的机器上直接崩。
SKIP_EXT = {'.pyc', '.pyo'}
# 打完包必须存在的东西，少一个就说明过滤规则写错了
MUST_HAVE = ['runtime/python.exe', 'runtime/python311.zip', 'runtime/python311.dll',
             'runtime/python311._pth', 'start_web.bat', 'webapp.py', 'static/index.html']


def setup_runtime():
    if not os.path.exists(os.path.join(RUNTIME, 'python.exe')):
        os.makedirs(DL, exist_ok=True)
        zpath = os.path.join(DL, 'py-embed.zip')
        if not os.path.exists(zpath):
            print(f'[1/3] 下载嵌入式 Python {PY_VER} ...')
            urllib.request.urlretrieve(EMBED_URL, zpath)
        print('[1/3] 解压到 runtime/')
        if os.path.isdir(RUNTIME):
            shutil.rmtree(RUNTIME)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(RUNTIME)
    else:
        print('[1/3] runtime/ 已存在，跳过下载')

    pth = os.path.join(RUNTIME, 'python311._pth')
    print('[2/3] 写 _pth（让 site-packages 和项目根可导入）')
    with open(pth, 'w', encoding='utf-8', newline='\n') as f:
        f.write('python311.zip\n.\nLib\\site-packages\n..\n')

    print('[3/3] 安装依赖到 runtime/Lib/site-packages')
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade',
                           '--no-warn-script-location', '--target',
                           os.path.join(RUNTIME, 'Lib', 'site-packages')] + PKGS)


def collect():
    """返回 [(磁盘绝对路径, 包内相对路径)]"""
    items = []
    for name in INCLUDE_FILES:
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            items.append((p, name))
        else:
            print('  [警告] 缺文件，跳过:', name)
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            print('  [警告] 缺目录，跳过:', d)
            continue
        for cur, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for fn in files:
                if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                    continue
                ap = os.path.join(cur, fn)
                rp = os.path.relpath(ap, ROOT).replace('\\', '/')
                items.append((ap, rp))
    return items


def build():
    items = collect()
    out = os.path.join(ROOT, 'quick_OJ-v1.0.1-win64.zip')
    if os.path.exists(out):
        os.remove(out)
    print(f'打包 {len(items)} 个文件 -> {os.path.basename(out)}')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for ap, rp in items:
            z.write(ap, 'quick_OJ/' + rp)

    # 自检：缺文件就当场失败，别等用户解压后双击闪退
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
    missing = [m for m in MUST_HAVE if 'quick_OJ/' + m not in names]
    if missing:
        os.remove(out)
        sys.exit(f'[错误] 包内缺少关键文件，已丢弃产物：{missing}\n'
                 f'        检查 INCLUDE_DIRS / SKIP_DIRS / SKIP_EXT 是否过滤过头。')

    size = os.path.getsize(out) / 1024 / 1024
    print(f'完成：{out}  ({size:.1f} MB，{len(names)} 个条目，关键文件自检通过)')
    return out


if __name__ == '__main__':
    if '--setup' in sys.argv:
        if sys.version_info[:2] != (3, 11):
            sys.exit(f'[错误] 请用 Python 3.11 运行（当前 {sys.version.split()[0]}），'
                     f'否则装出来的依赖与内置 runtime 不兼容')
        setup_runtime()
    build()
