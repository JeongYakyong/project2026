# -*- coding: utf-8 -*-
import sys, os
from playwright.sync_api import sync_playwright
path = os.path.abspath(sys.argv[1]); out = os.path.splitext(path)[0] + '.png'
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={'width':1000,'height':720}, device_scale_factor=2)
    pg.goto('file:///' + path.replace('\\', '/')); pg.wait_for_timeout(1200)
    el = pg.query_selector('.wrap'); (el or pg).screenshot(path=out); b.close()
print(out)
