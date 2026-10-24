# -*- coding: utf-8 -*-
"""OJ 登录模块：AI 识别验证码

要点（都是踩坑换来的）：
- 用视觉专用快模型，不要用推理模型：推理模型回答 4 个字符要先想几百 token，
  单张 8~45 秒；视觉模型只要 1~1.5 秒。
- 验证码有效期只有 20~40 秒，所以必须「取一张 → 立刻识别 → 立刻提交」，
  批量取多张再并发识别时，最慢那张回来时已经作废。
"""
import base64
import os
import re
import time

import requests

import llm

# 视觉专用快模型，专门用来认验证码；做题生成代码仍用 llm.MODEL
CAPTCHA_MODEL = os.getenv('OJ_CAPTCHA_MODEL', 'cn:glm-5v-turbo')

# 站点可切换：set_site('http://your-oj.example.com')
DEFAULT_SITE = os.getenv('OJ_SITE_BASE', 'http://oj.example.com')
SITE_BASE = DEFAULT_SITE
OJS = SITE_BASE + '/api'

PROMPT = ('这是登录验证码，恰好 4 个字符（字母区分大小写，也可能是数字）。'
          '只输出这 4 个字符，不要解释、标点或空格。')


def set_site(base):
    """切换 OJ 站点（同时更新 Referer 与 /api 前缀）"""
    global SITE_BASE, OJS
    SITE_BASE = (base or DEFAULT_SITE).rstrip('/')
    OJS = SITE_BASE + '/api'
    return SITE_BASE


def _ai_url():
    """实时取接口地址：webapp 可能在运行时改 llm.BASE"""
    return llm.BASE.rstrip('/') + '/chat/completions'


def ai_read(imgbase64):
    """让模型认这张验证码，返回 4 个字符；失败返回空串"""
    payload = {
        'model': CAPTCHA_MODEL, 'temperature': 0,
        'max_tokens': 64,          # 只要 4 个字符，不用留思考预算
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': PROMPT},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + imgbase64}},
        ]}],
    }
    delay = 1.2
    for _ in range(3):
        try:
            r = requests.post(_ai_url(), headers={'Authorization': f'Bearer {llm.KEY}'},
                              json=payload, timeout=180)
            j = r.json()
            if 'choices' not in j:
                err = j.get('error') or {}
                code = str(err.get('code') or '')
                # 网关账号池很小，并发一高就 no_healthy_account；这种要退避等，不能立刻重试
                if code == 'no_healthy_account' or r.status_code in (429, 500, 502, 503, 504):
                    print(f'  [验证码] ai busy({code or r.status_code}) {delay:.1f}s 后重试')
                    time.sleep(delay)
                    delay *= 2
                    continue
                print('  [验证码] ai bad resp:', r.text[:200])
                return ''
            txt = j['choices'][0]['message'].get('content') or ''
            c = re.sub(r'[^A-Za-z0-9]', '', txt)
            if len(c) >= 4:
                return c[:4]
            print(f'  [验证码] ai 空/短返回: {txt[:40]!r}')
        except Exception as e:
            print('  [验证码] ai err', type(e).__name__, e)
            time.sleep(delay)
            delay *= 2
    return ''


class OJLogin:
    def __init__(self, username, password):
        self.u, self.p = username, password
        self.s = requests.Session()
        self.s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': SITE_BASE + '/',
            'Content-Type': 'application/json'})

    def _captcha(self):
        d = self.s.post(f'{OJS}/captcha/', json={}, timeout=10).json()
        return d['captcha_key'], base64.b64decode(d['captcha_image'])

    def login(self, tries=5, deadline=60):
        """逐张串行：取一张图 → 立刻识别 → 立刻提交。

        为什么不并发批量：
        - 快模型单张只要 1~1.5s，串行 5 次总共 8s 左右，比抢网关还快；
        - 验证码只有 20~40 秒有效期，批量取 3 张再并发识别时，
          最慢那张返回时可能已经过期（`Invalid captcha value`），白白浪费机会。
        """
        t0 = time.time()
        for i in range(tries):
            if time.time() - t0 > deadline:
                print(f'  [验证码] 超过 {deadline}s 时限，放弃本次登录')
                break
            try:
                key, raw = self._captcha()
            except Exception as e:
                print('  [验证码] 取图失败', type(e).__name__, e)
                time.sleep(1)
                continue
            # 原图直送：90x40 本来就清晰，放大 5 倍体积涨 8.5 倍，只会更慢。
            # raw 本身就是 PNG 字节，直接 base64 即可，不必再经 PIL 重编码。
            code = ai_read(base64.b64encode(raw).decode())
            if not code:
                print(f'  [验证码] 第{i+1}次识别为空')
                continue
            try:
                r = self.s.post(f'{OJS}/user/login/', json={
                    'username': self.u, 'password': self.p,
                    'captcha_key': key, 'captcha_value': code}, timeout=20)
            except Exception as e:
                print('  [验证码] 提交失败', type(e).__name__, e)
                continue
            if r.status_code == 200:
                self.user = r.json()
                self.s.headers['x-csrftoken'] = self.s.cookies.get('csrftoken', '')
                print(f'  [验证码] 第{i+1}次命中 {code}，登录成功: {self.user.get("nickname")}'
                      f' (id={self.user.get("id")}) 耗时 {time.time() - t0:.1f}s')
                return True
            print(f'  [验证码] 第{i+1}次 {code} -> {r.status_code} {r.text[:80]}')
        return False


if __name__ == '__main__':
    t = time.time()
    lg = OJLogin(os.getenv('OJ_USER', ''), os.getenv('OJ_PASS', ''))
    print('OK' if lg.login() else 'FAIL', f'{time.time() - t:.1f}s')
