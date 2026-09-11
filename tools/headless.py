#!/usr/bin/env python3
"""A very small Chrome DevTools Protocol client. Stdlib only, no pip install.

Why this exists: `chromium --dump-dom` is not dependable. On some builds it
hangs forever with a virtual time budget, and a review gate that can hang is a
review gate that gets skipped. Driving the browser over its own protocol is
deterministic, works the same on Ubuntu and macOS, and is the only way to see
console errors and uncaught exceptions at all -- the CLI flags never report
them.

Implements just enough of RFC 6455 to send a few JSON messages: the handshake,
masked client frames, unmasked server frames, and ping/pong.

    from headless import Page
    with Page() as p:
        r = p.visit("http://127.0.0.1:8000/index.html")
        r.text, r.html, r.errors
"""

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
              "chrome", "/usr/bin/chromium",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def find_chrome():
    for c in CANDIDATES:
        p = c if (c.startswith("/") and os.path.exists(c)) else shutil.which(c)
        if p:
            return p
    raise RuntimeError("no chromium or chrome found -- cannot render, so cannot pass")


class Result:
    def __init__(self, text, html, errors):
        self.text, self.html, self.errors = text, html, errors


class _WS:
    def __init__(self, url, timeout=30):
        _, rest = url.split("://", 1)
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake closed early")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError("websocket handshake refused: " + buf[:120].decode("latin1"))
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        head = bytes([0x81])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask +
                          bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("websocket closed")
            self.buf += chunk

    def recv(self):
        """Next text message, reassembling fragments, answering pings."""
        payload = b""
        while True:
            self._need(2)
            b0, b1 = self.buf[0], self.buf[1]
            fin, op, ln = b0 & 0x80, b0 & 0x0F, b1 & 0x7F
            off = 2
            if ln == 126:
                self._need(4); ln = struct.unpack(">H", self.buf[2:4])[0]; off = 4
            elif ln == 127:
                self._need(10); ln = struct.unpack(">Q", self.buf[2:10])[0]; off = 10
            self._need(off + ln)
            body = self.buf[off:off + ln]
            self.buf = self.buf[off + ln:]
            if op == 0x9:                     # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op == 0x8:
                raise RuntimeError("websocket closed by browser")
            if op == 0xA:
                continue
            payload += body
            if fin:
                return json.loads(payload.decode("utf-8", "replace"))

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Page:
    def __init__(self, binary=None, settle=2.5):
        self.binary = binary or find_chrome()
        self.settle = settle
        self.profile = tempfile.mkdtemp(prefix="margin-headless-")
        self.proc = subprocess.Popen(
            [self.binary, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--disable-dev-shm-usage", "--remote-debugging-port=0",
             "--user-data-dir=" + self.profile, "--window-size=1200,2200",
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.port = self._await_port()
        self.ws = None
        self._id = 0

    def _await_port(self, limit=30):
        f = os.path.join(self.profile, "DevToolsActivePort")
        end = time.time() + limit
        while time.time() < end:
            if os.path.exists(f):
                try:
                    line = open(f).readline().strip()
                    if line:
                        return int(line)
                except (OSError, ValueError):
                    pass
            if self.proc.poll() is not None:
                raise RuntimeError("browser exited before it opened a debug port")
            time.sleep(0.15)
        raise RuntimeError("browser never opened a debug port")

    def _connect(self):
        end = time.time() + 20
        while time.time() < end:
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json/list", timeout=5).read()
                for t in json.loads(raw):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return _WS(t["webSocketDebuggerUrl"])
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("no debuggable page target")

    def _call(self, method, params=None, wait=True):
        self._id += 1
        mid = self._id
        self.ws.send({"id": mid, "method": method, "params": params or {}})
        if not wait:
            return None
        while True:
            msg = self.ws.recv()
            if msg.get("id") == mid:
                return msg
            self._note(msg)

    def _note(self, msg):
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Log.entryAdded" and p.get("entry", {}).get("level") == "error":
            e = p["entry"]
            # The URL is the whole point of a network error; without it the
            # message says only that something, somewhere, failed to load.
            where = e.get("url") or ""
            self.errors.append(
                f"{e.get('source','')}: {e.get('text','')}"
                + (f" [{where}]" if where else ""))
        elif m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.errors.append("uncaught: " + (
                d.get("exception", {}).get("description") or d.get("text", "")))
        elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
            parts = [str(a.get("value", a.get("description", "")))
                     for a in p.get("args", [])]
            self.errors.append("console.error: " + " ".join(parts))

    def visit(self, url):
        self.errors = []
        if self.ws is None:
            self.ws = self._connect()
        for m in ("Runtime.enable", "Log.enable", "Page.enable"):
            self._call(m)
        self._call("Page.navigate", {"url": url})
        # Drain events until the load event, then let fetch() settle.
        end = time.time() + 30
        self.ws.sock.settimeout(3)
        loaded = False
        while time.time() < end and not loaded:
            try:
                msg = self.ws.recv()
            except (socket.timeout, TimeoutError):
                break
            self._note(msg)
            if msg.get("method") == "Page.loadEventFired":
                loaded = True
        time.sleep(self.settle)
        self.ws.sock.settimeout(30)
        # Flush anything the settle period produced.
        self.ws.sock.settimeout(0.4)
        while True:
            try:
                self._note(self.ws.recv())
            except Exception:
                break
        self.ws.sock.settimeout(30)

        text = self._eval("document.body ? document.body.innerText : ''")
        html = self._eval("document.documentElement.outerHTML")
        return Result(text or "", html or "", list(self.errors))

    def screenshot(self, path, full=True):
        """PNG of the current page. Used by the reviewer to show its work."""
        if full:
            m = self._call("Page.getLayoutMetrics")
            css = (m or {}).get("result", {}).get("cssContentSize") or {}
            h = min(int(css.get("height") or 2200), 12000)
            self._call("Emulation.setDeviceMetricsOverride",
                       {"width": int(css.get("width") or 1200), "height": h,
                        "deviceScaleFactor": 1, "mobile": False})
        r = self._call("Page.captureScreenshot", {"format": "png"})
        data = ((r or {}).get("result", {}) or {}).get("data")
        if not data:
            raise RuntimeError("browser returned no image")
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        if full:
            self._call("Emulation.clearDeviceMetricsOverride")
        return path

    def _eval(self, expr):
        r = self._call("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True})
        return ((r or {}).get("result", {}).get("result", {}) or {}).get("value")

    def close(self):
        try:
            if self.ws:
                self.ws.close()
        finally:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
