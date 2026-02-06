#!/usr/bin/env python3
"""Minimal HTTP code executor service (demo).

This is a tiny "execution API" you can deploy to a sandboxed runtime
(e.g., Cloud Run / Azure Container Apps) to demonstrate the agent pattern:
  agent -> POST /run -> {stdout, stderr, exit_code}

WARNING: subprocess + rlimits is NOT a perfect sandbox. Combine with stronger
isolation and egress controls in production.
"""

from __future__ import annotations

import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from tempfile import TemporaryDirectory


def _run_python(code: str, timeout_s: int = 8) -> tuple[int, str, str]:
    with TemporaryDirectory(prefix="exec-") as td:
        path = os.path.join(td, "main.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        p = subprocess.run(
            ["python", "-I", path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return p.returncode, p.stdout, p.stderr


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        try:
            data = json.loads(payload.decode("utf-8"))
            code = data.get("code", "")
            if not isinstance(code, str):
                raise ValueError("code must be a string")
        except Exception as e:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        try:
            rc, out, err = _run_python(code)
            resp = {"exit_code": rc, "stdout": out, "stderr": err}
        except subprocess.TimeoutExpired:
            resp = {"exit_code": 124, "stdout": "", "stderr": "timed out"}

        body = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # reduce noise for demos
        return


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
