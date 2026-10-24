# -*- coding: utf-8 -*-
"""
浏览器版自动登录（DrissionPage + AI 验证码）
- 修正了原脚本的 XPath / 元素取值问题
- 验证码用 AI 接口识别，失败自动换图重试
"""
import base64, io, json, os, re, time
import numpy as np
import requests
from PIL import Image, ImageFilter
from DrissionPage import ChromiumPage

import llm

SITE_BASE = os.getenv('OJ_SITE_BASE', 'http://172.31.221.62').rstrip('/')
LOGIN_URL = SITE_BASE + '/#/login'
USERNAME, PASSWORD = os.getenv('OJ_USER', ''), os.getenv('OJ_PASS', '')

GET_CAP_JS = """var x=new XMLHttpRequest();x.open('POST','/api/captcha/',false);
x.setRequestHeader('Content-Type','application/json');x.send('{}');return x.responseText;"""

SET_VALUE_JS = """
var el = document.querySelectorAll('.el-form-item input')[%d];
var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
setter.call(el, %s);
el.dispatchEvent(new Event('input',{bubbles:true}));
el.dispatchEvent(new Event('change',{bubbles:true}));
return el.value;
"""


def flatten_lines(raw):
    """去掉贯穿整行的干扰线 -> 中值去噪 -> 放大 5 倍"""
    im = Image.open(io.BytesIO(raw)).convert('L')
    a = np.array(im)
    h, w = a.shape
    rowsum = (a < 120).sum(axis=1)
    for y in range(h):
        if rowsum[y] > w * 0.85:
            a[y, :] = 255
    im = Image.fromarray(a).filter(ImageFilter.MedianFilter(3))
    im = im.resize((w * 5, h * 5), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def ai_read_captcha(img_b64):
    payload = {
        'model': llm.MODEL, 'temperature': 0, 'max_tokens': 8000,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': '这张验证码图片恰好有4个字符（字母区分大小写，也可能是数字）。'
                                     '只输出这4个字符，不要解释、标点或空格。'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + img_b64}},
        ]}],
    }
    try:
        r = requests.post(f'{llm.BASE}/chat/completions',
                          headers={'Authorization': f'Bearer {llm.KEY}'}, json=payload, timeout=180)
        ans = r.json()['choices'][0]['message'].get('content') or ''
    except Exception as e:
        print('   AI 异常:', e)
        return ''
    c = re.sub(r'[^A-Za-z0-9]', '', ans)
    return c if len(c) == 4 else ''


def login_browser(page, retry=8):
    page.get(LOGIN_URL)
    time.sleep(2.5)
    page.listen.start('/api/captcha/')
    for i in range(retry):
        # 点击图片让前端自己请求验证码，保证 captcha_key 与图片一致
        try:
            page.ele('css:.el-col-12 img').click()
        except Exception:
            pass
        pkt = page.listen.wait(timeout=10)
        if not pkt:
            print(f'  [{i}] 未捕获验证码请求')
            continue
        try:
            d = pkt.response.body
            if isinstance(d, str):
                d = json.loads(d)
        except Exception as e:
            print('  解析验证码失败:', e)
            continue
        img_b64 = d.get('captcha_image', '')
        code = ai_read_captcha(flatten_lines(base64.b64decode(img_b64)))
        print(f'  [{i}] 验证码识别: {code!r}')
        if len(code) != 4:
            continue
        page.run_js(SET_VALUE_JS % (0, json.dumps(USERNAME)))
        page.run_js(SET_VALUE_JS % (1, json.dumps(PASSWORD)))
        page.run_js(SET_VALUE_JS % (2, json.dumps(code)))
        time.sleep(0.3)
        page.ele('css:button.el-button--primary').click()
        time.sleep(2.5)
        if '/login' not in page.url:
            print('  登录成功:', page.url)
            page.listen.stop()
            return True
    page.listen.stop()
    return False


if __name__ == '__main__':
    page = ChromiumPage()
    if not login_browser(page):
        raise SystemExit('登录失败')

    # 进入课程列表（路径按你自己的 OJ 调整）
    page.get(SITE_BASE + '/#/course/courseList')
    time.sleep(4)
    print('课程页:', page.url)
    page.get_screenshot(path='course.png', full_page=True)

    # 想看某个实验页就设环境变量 OJ_CONTEST_ID
    cid = os.getenv('OJ_CONTEST_ID', '')
    if cid:
        page.get(f'{SITE_BASE}/#/contest/{cid}')
        time.sleep(4)
        print('实验页:', page.url)
        page.get_screenshot(path='contest.png', full_page=True)
        print('题目列表:', page.ele('tag:body').text[:400].replace('\n', ' | '))
