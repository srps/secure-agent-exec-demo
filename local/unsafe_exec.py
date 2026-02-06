#!/usr/bin/env python3
"""Unsafe code execution demo (INTENTIONALLY INSECURE).

This script demonstrates why running LLM- (or user-) generated code directly on
your host is dangerous.

USAGE:
  python local/unsafe_exec.py examples/benign.py
  python local/unsafe_exec.py examples/malicious.py

WARNING
  Do not run this on a machine with real secrets. Prefer a throwaway VM.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python local/unsafe_exec.py <path/to/script.py>")
        return 2

    script = Path(sys.argv[1]).expanduser().resolve()
    if not script.exists() or script.suffix != ".py":
        print(f"Not a python file: {script}")
        return 2

    print("[!] UNSAFE MODE: executing on the host with your user permissions")
    print(f"[!] Running: {script}")
    print("----- output -----")
    runpy.run_path(str(script), run_name="__main__")
    print("------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
