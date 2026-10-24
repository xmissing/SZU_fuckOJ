# -*- coding: utf-8 -*-
"""AI 接口封装（OpenAI 兼容）

密钥不写死在代码里：优先用环境变量 OJ_AI_KEY，其次用 config.json 的 api_key。
运行时 webapp 会把配置里的值覆盖到本模块的 KEY 上。
"""
import os
import re
import time
import requests

KEY = os.getenv('OJ_AI_KEY', '')
BASE = os.getenv('OJ_AI_BASE', 'http://127.0.0.1:7863/v1')
MODEL = os.getenv('OJ_AI_MODEL', 'cn:deepseek-v4.1-flash')


def chat(prompt, system=None, max_tokens=12000, temperature=0.2, timeout=300):
    msgs = []
    if system:
        msgs.append({'role': 'system', 'content': system})
    msgs.append({'role': 'user', 'content': prompt})
    payload = {'model': MODEL, 'messages': msgs, 'max_tokens': max_tokens,
               'temperature': temperature}
    last = ''
    delay = 1.5
    for _ in range(4):
        try:
            r = requests.post(f'{BASE}/chat/completions',
                              headers={'Authorization': f'Bearer {KEY}'}, json=payload, timeout=timeout)
            d = r.json()
            if 'choices' not in d:
                code = str((d.get('error') or {}).get('code') or '')
                last = f'{code or r.status_code}: {str(d)[:200]}'
                # 网关账号池很小，并发一高就 no_healthy_account；退避重试，别把几次机会瞬间打光
                time.sleep(delay)
                delay *= 2
                continue
            c = d['choices'][0]['message'].get('content') or ''
            if c.strip():
                return c
            last = 'empty content'
            time.sleep(delay)
            delay *= 2
        except Exception as e:
            last = repr(e)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f'AI 调用失败: {last}')


def extract_code(text):
    m = re.findall(r'```(?:c|cpp|C|C\+\+)?\s*\n(.*?)```', text, re.S)
    code = m[-1] if m else text
    code = code.strip()
    # 去掉可能残留的 markdown 标记
    if code.startswith('```'):
        code = code.split('\n', 1)[-1]
    if code.endswith('```'):
        code = code.rsplit('```', 1)[0]
    return code.strip()
