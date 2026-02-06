#!/usr/bin/env python3
"""Docker-sandboxed Python execution demo.

This runs the provided Python file inside a locked-down Docker container:
  - --network none
  - --read-only
  - --cap-drop=ALL
  - --security-opt no-new-privileges
  - resource limits (cpu/mem/pids)

USAGE:
  python local/sandbox_docker.py examples/malicious.py

NOTES:
  - This is a demo baseline; containers still share the host kernel.
  - For higher assurance, consider gVisor/Kata/microVMs.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def require_docker() -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker not found. Install Docker Desktop or docker engine.")
    try:
        subprocess.run(
            ["docker", "version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception as e:
        raise RuntimeError(
            "Docker is installed but not working. Is the daemon running?"
        ) from e


def run_in_docker(
    script_path: Path,
    allow_network: bool,
    memory: str,
    cpus: str,
    pids: int,
    timeout_s: int,
) -> int:
    with tempfile.TemporaryDirectory(prefix="agent-sandbox-") as td:
        td_path = Path(td)
        work = td_path / "work"
        work.mkdir()
        (work / "main.py").write_text(
            script_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

        cmd = [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--network",
            "bridge" if allow_network else "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(pids),
            "--memory",
            memory,
            "--cpus",
            str(cpus),
            "--user",
            "65532:65532",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "-v",
            f"{work}:/work:rw",
            "-w",
            "/work",
            "python:3.13-slim",
            "python",
            "-I",
            "main.py",
        ]

        print("[+] Docker command:")
        print(" ".join(cmd))
        print("----- output -----")
        try:
            p = subprocess.run(cmd, text=True, capture_output=False, timeout=timeout_s)
            return p.returncode
        except subprocess.TimeoutExpired:
            print(f"[!] Timed out after {timeout_s}s")
            return 124


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script", type=str)
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--memory", default="256m")
    ap.add_argument("--cpus", default="0.5")
    ap.add_argument("--pids", default=128, type=int)
    ap.add_argument(
        "--timeout",
        default=int(os.getenv("SANDBOX_TIMEOUT", "120")),
        type=int,
    )
    args = ap.parse_args()

    require_docker()
    script = Path(args.script).expanduser().resolve()
    if not script.exists() or script.suffix != ".py":
        print(f"Not a python file: {script}")
        return 2

    mode = "(network allowed)" if args.allow_network else "(network disabled)"
    print(f"[+] SANDBOX MODE {mode}: executing in a hardened Docker container")
    return run_in_docker(
        script, args.allow_network, args.memory, args.cpus, args.pids, args.timeout
    )


if __name__ == "__main__":
    raise SystemExit(main())
