"""Cek manual fitur ambil halaman RBV di jendela WebView2 beneran, tanpa login ke UT.

Jalankan: python scripts/check_rbv_grab.py
"""
import functools
import http.server
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import webview
from PIL import Image

import run_app

site = tempfile.mkdtemp()
Image.new("RGB", (800, 1100), "white").save(os.path.join(site, "page1.png"))
pages = {
    # Gambar dari domain lain harus dilewati karena canvas-nya tercemar
    "module": '<body style="margin:0"><div>Menu RBV</div><img src="page1.png" style="width:800px">'
              '<img src="https://www.microsoft.com/favicon.ico" style="width:400px"></body>',
    "login": "<body>Login dengan SSO</body>",
    "text": "<body>" + "Isi modul teks panjang. " * 40 + "</body>",
}
for name, html in pages.items():
    with open(os.path.join(site, f"{name}.html"), "w") as f:
        f.write(html)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=site)
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"

run_app.RBV_HOST = "127.0.0.1"
api = run_app.DesktopApi()
results = {}


def run(window):
    results["closed"] = api.grab_rbv_page()
    api._rbv_window = window
    for name in pages:
        window.load_url(f"{base}/{name}.html")
        time.sleep(2)
        results[name] = api.grab_rbv_page()
    window.destroy()


window = webview.create_window("check rbv", "about:blank")
webview.start(run, window)

assert "error" in results["closed"]
assert len(results["module"]["images"]) == 1
assert results["module"]["images"][0].startswith("data:image/jpeg;base64,")
assert "error" in results["login"]
assert "Isi modul" in results["text"]["text"]
print("OK")
