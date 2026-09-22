"""Development-only browser viability probe for Discord webhook transport.

The webhook is read from DJGOO_TEST_WEBHOOK_URL or an ignored secrets file. It
is handed to a loopback-only test page in memory and is never printed or
written to the repository/build output.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HTML = r"""<!doctype html><meta charset="utf-8"><title>DjGoo transport probe</title>
<pre id="result">running</pre><script>
(async () => {
  const result = { browser: navigator.userAgent, operations: {} };
  let messageUrl = "";
  try {
    const config = await fetch('/credential', {cache: 'no-store'}).then(r => r.json());
    const marker = config.marker;
    const created = await fetch(config.webhook_url + '?wait=true', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: marker, allowed_mentions: {parse: []}})
    });
    result.operations.post = created.status;
    if (!created.ok) throw new Error('POST ' + created.status);
    const message = await created.json();
    messageUrl = config.webhook_url + '/messages/' + message.id;
    const read = await fetch(messageUrl, {cache: 'no-store'});
    result.operations.get = read.status;
    if (!read.ok || (await read.json()).content !== marker) throw new Error('GET verification');
    const editedMarker = marker + '-edited';
    const edited = await fetch(messageUrl, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: editedMarker, allowed_mentions: {parse: []}})
    });
    result.operations.patch = edited.status;
    if (!edited.ok) throw new Error('PATCH ' + edited.status);
    let detected = false;
    for (let i = 0; i < 5; i++) {
      const polled = await fetch(messageUrl, {cache: 'no-store'});
      if (polled.ok && (await polled.json()).content === editedMarker) { detected = true; break; }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    result.operations.edited_response_detected = detected;
    if (!detected) throw new Error('edited response not detected');
    const removed = await fetch(messageUrl, {method: 'DELETE'});
    result.operations.delete = removed.status;
    messageUrl = '';
    if (!removed.ok) throw new Error('DELETE ' + removed.status);
    result.ok = true;
  } catch (error) {
    result.ok = false;
    result.error = String(error && error.message || error).slice(0, 160);
  } finally {
    if (messageUrl) { try { await fetch(messageUrl, {method: 'DELETE'}); } catch (_) {} }
    await fetch('/result', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(result)});
    document.getElementById('result').textContent = JSON.stringify(result, null, 2);
  }
})();</script>"""


def _webhook(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"discord.com", "www.discord.com"}:
        raise ValueError("Test webhook must be an official Discord HTTPS webhook")
    parts = parsed.path.rstrip("/").split("/")
    if len(parts) < 5 or parts[-3] != "webhooks":
        raise ValueError("Test webhook URL is malformed")
    return value.strip().rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secrets-file", type=Path)
    parser.add_argument("--browser", type=Path, required=True)
    args = parser.parse_args()
    value = os.environ.get("DJGOO_TEST_WEBHOOK_URL", "")
    if not value and args.secrets_file:
        value = str(json.loads(args.secrets_file.read_text(encoding="utf-8")).get("webhook_url") or "")
    webhook = _webhook(value)
    marker = "DJGOO-CORS-PROBE-" + secrets.token_urlsafe(12)
    completed = threading.Event()
    outcome: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/":
                self._send(200, HTML.encode(), "text/html; charset=utf-8")
            elif self.path == "/credential":
                self._send(200, json.dumps({"webhook_url": webhook, "marker": marker}).encode(), "application/json")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/result":
                self._send(404, b"", "text/plain")
                return
            length = min(int(self.headers.get("Content-Length", "0")), 8192)
            try:
                data = json.loads(self.rfile.read(length))
                outcome.update(data if isinstance(data, dict) else {})
            except (ValueError, json.JSONDecodeError):
                outcome.update({"ok": False, "error": "invalid browser result"})
            completed.set()
            self._send(204, b"", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    port = server.server_address[1]
    if str(args.browser).lower().endswith(".exe") and shutil.which("cmd.exe"):
        windows_temp = subprocess.check_output(
            ["cmd.exe", "/d", "/c", "echo", "%TEMP%"], text=True
        ).strip().replace("\r", "")
        profile = Path(
            subprocess.check_output(
                ["wslpath", "-u", windows_temp], text=True
            ).strip()
        ) / ("djgoo-cors-" + secrets.token_hex(6))
        profile_arg = subprocess.check_output(
            ["wslpath", "-w", str(profile)], text=True
        ).strip()
    else:
        profile = Path(os.environ.get("TEMP", "/tmp")) / ("djgoo-cors-" + secrets.token_hex(6))
        profile_arg = str(profile)
    profile.mkdir(parents=True, exist_ok=True)
    command = [str(args.browser), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile_arg}", f"http://127.0.0.1:{port}/"]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        completed.wait(30)
    finally:
        process.terminate()
        server.shutdown()
        server.server_close()
        shutil.rmtree(profile, ignore_errors=True)
    safe = {"ok": bool(outcome.get("ok")), "browser_family": "Chromium", "operations": outcome.get("operations", {}), "error": outcome.get("error", "")}
    print(json.dumps(safe, indent=2, sort_keys=True))
    return 0 if safe["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
