#!/usr/bin/env python3
"""Node.js isolated-vm JavaScript execution demo.

This runs the provided JavaScript file using the `isolated-vm` package. This is a
demo-only boundary, not a hardened sandbox. Do not treat it as a strong security
boundary.

USAGE:
    npm install
    python local/sandbox_node.py examples/benign.js
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def require_node() -> None:
    if shutil.which("node") is None:
        raise RuntimeError("Node.js not found. Install Node.js first.")
    try:
        subprocess.run(
            ["node", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception as e:
        raise RuntimeError("Node.js is installed but not working.") from e


def require_isolated_vm(repo_root: Path) -> None:
    try:
        subprocess.run(
            ["node", "-e", "require('isolated-vm')"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception as e:
        raise RuntimeError(
            "The 'isolated-vm' package is not installed. Run 'npm install' in the repo root."
        ) from e


def run_in_node(script_path: Path, timeout_s: int) -> tuple[int, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    runner = Path(__file__).resolve().parent / "js_isolate_runner.js"
    outputs_root = repo_root / "outputs" / "js"

    with tempfile.TemporaryDirectory(prefix="agent-js-") as td:
        td_path = Path(td)
        work = td_path / "work"
        out_dir = work / "out"
        work.mkdir()
        out_dir.mkdir(parents=True)

        (work / "main.js").write_text(
            script_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

        cmd = [
            "node",
            str(runner),
            str(work / "main.js"),
            str(out_dir),
        ]

        print("[+] Node command:")
        print(" ".join(cmd))
        print("----- output -----")
        try:
            p = subprocess.run(cmd, text=True, capture_output=False, timeout=timeout_s)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            print(f"[!] Timed out after {timeout_s}s")
            rc = 124

        run_id = uuid.uuid4().hex
        dest = outputs_root / run_id
        dest.mkdir(parents=True, exist_ok=True)

        if out_dir.exists():
            for item in out_dir.rglob("*"):
                rel = item.relative_to(out_dir)
                target = dest / rel
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)

        print(f"[+] Output directory: {dest}")
        return rc, dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("script", type=str)
    ap.add_argument("--timeout", default=10, type=int)
    args = ap.parse_args()

    require_node()
    require_isolated_vm(Path(__file__).resolve().parents[1])
    script = Path(args.script).expanduser().resolve()
    if not script.exists() or script.suffix != ".js":
        print(f"Not a JavaScript file: {script}")
        return 2

    print("[+] JS IVM MODE: executing with isolated-vm (demo-only)")
    rc, out_dir = run_in_node(script, args.timeout)
    print(json.dumps({"exit_code": rc, "output_dir": str(out_dir)}))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
