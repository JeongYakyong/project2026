# -*- coding: utf-8 -*-
"""HTML 다이어그램 → PNG 렌더 (검수용). 사용: python _render.py <file.html>"""
import sys, os
from playwright.sync_api import sync_playwright

html = sys.argv[1]
path = os.path.abspath(html)
out = os.path.splitext(path)[0] + '.png'
url = 'file:///' + path.replace('\\', '/')

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width': 1000, 'height': 720}, device_scale_factor=2)
    pg.goto(url)
    pg.wait_for_timeout(1200)
    el = pg.query_selector('.wrap')
    (el or pg).screenshot(path=out)
    b.close()
print(out)
