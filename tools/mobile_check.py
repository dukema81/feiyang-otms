# -*- coding: utf-8 -*-
"""飞洋手机APP（PWA）巡检：起本地后端 + 移动端静态/代理服务，Playwright 手机视口走查 5 Tab"""
import json
import os
import socket
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOBILE = os.path.join(ROOT, "mobile")
BACKEND = os.environ.get("OY_TEST_BASE", "http://127.0.0.1:8099")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=MOBILE, **kw)

    def log_message(self, *a):
        pass

    def _proxy(self):
        path = self.path
        if path.startswith("/ocean/"):
            path = path[len("/ocean"):] or "/"
        body = None
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            body = self.rfile.read(n)
        req = urllib.request.Request(BACKEND + path, data=body, method=self.command)
        for h in ("Authorization", "Content-Type", "Idempotency-Key", "X-Api-Key", "X-Token"):
            v = self.headers.get(h)
            if v:
                req.add_header(h, v)
        try:
            with OPENER.open(req, timeout=30) as r:
                data = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", e.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/") or self.path.startswith("/ocean/api/"):
            return self._proxy()
        return super().do_GET()

    def do_POST(self):
        return self._proxy()


def main():
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d/" % port

    from playwright.sync_api import sync_playwright
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True,
                            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(base + "index.html")
        pg.wait_for_timeout(900)
        # 登录
        pg.fill("#lg-u", "admin"); pg.fill("#lg-p", "123456")
        pg.click(".btn"); pg.wait_for_timeout(900)
        tabs = ["dash", "voyage", "booking", "container", "me"]
        for t in tabs:
            pg.evaluate("document.querySelector('#tabbar a[data-tab=%s]').click()" % json.dumps(t))
            pg.wait_for_timeout(700)
            txt = pg.inner_text("#main")
            ok = len(txt.strip()) >= 8 and "加载失败" not in txt and "暂无" not in txt
            if not ok:
                fails.append(t)
            print(("OK  " if ok else "FAIL"), t, "|", txt.replace("\n", " ")[:60])
            if ok:
                # 横向不溢出
                overflow = pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
                if overflow:
                    fails.append(t + ":overflow")
                    print("FAIL", t, "横向溢出")
        if errors:
            fails.append("js:" + ";".join(errors[:3]))
        # PWA 资源
        for f in ("manifest.webmanifest", "sw.js", "icon.svg"):
            try:
                code = OPENER.open(base + f, timeout=10).getcode()
                if code != 200:
                    fails.append(f)
                    print("FAIL asset", f, code)
            except Exception as e:
                fails.append(f)
                print("FAIL asset", f, e)
        b.close()
    srv.shutdown()
    print("==== MOBILE PASS=%d FAIL=%d ====" % (5 - len([f for f in fails if ':' not in f]), len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
