"""Deliberately "malicious" demo payload.

This is NOT real malware. It's a short script that attempts common exfil steps:
  - read env vars
  - read local files
  - call out to the network

Run it with:
  DEMO_SECRET=super-secret python local/unsafe_exec.py examples/malicious.py
  DEMO_SECRET=super-secret python local/sandbox_docker.py examples/malicious.py
"""

import os
import pathlib
import urllib.request

print('[*] env DEMO_SECRET =', os.environ.get('DEMO_SECRET'))

targets = [
    pathlib.Path('~/.ssh/id_rsa').expanduser(),
    pathlib.Path('~/.ssh/config').expanduser(),
    pathlib.Path('~/.aws/credentials').expanduser(),
]
for p in targets:
    try:
        data = p.read_text(encoding='utf-8', errors='ignore')
        print(f"[*] Read {p}: {len(data)} bytes")
    except Exception as e:
        print(f"[!] Could not read {p}: {e}")

try:
    with urllib.request.urlopen('https://example.com', timeout=3) as r:
        print('[*] Network OK, status =', r.status)
except Exception as e:
    print('[!] Network request failed:', e)
