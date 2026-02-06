#!/usr/bin/env python3
"""LLM-driven toy agent that executes Python code via a *pluggable executor*.

Purpose
  Demo the control-plane / data-plane split:
    - Control plane: LLM plans which actions to take.
    - Data plane: a tool executes code either UNSAFELY on the host or SAFELY in a Docker sandbox.

This version uses Z.AI as the LLM backend via the OpenAI Python SDK compatibility layer,
including *streaming* output.

Prereqs
  pip install --upgrade 'openai>=1.0'
  export ZAI_API_KEY='...'

Run
  # Prefer docker for safety
  python local/agent.py --default-executor docker

  # If you want to show the "bad" case (do this only on a throwaway VM)
  python local/agent.py --default-executor unsafe

Then in chat, try:
  - "List files"
  - "Read secure-agent-exec-demo/README.md"
  - "Run examples/benign.py in docker"
  - "Run examples/malicious.py in unsafe mode and explain what happened"

Safety
  The unsafe executor runs with your user permissions. Treat it as RCE.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

Json = dict[str, Any]
ToolFn = Callable[[Json], str]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Json
    fn: ToolFn

    def as_openai_tool(self) -> Json:
        # OpenAI-compatible function tool shape
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    path: Path


SKILLS: list[SkillMetadata] = []
SKILLS_BY_NAME: dict[str, SkillMetadata] = {}


def _parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}

    out: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        if key in {"name", "description"}:
            out[key] = value
    return out


def discover_skills(skill_dirs: list[Path]) -> list[SkillMetadata]:
    skills: list[SkillMetadata] = []
    for root in skill_dirs:
        if not root.exists() or not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            meta = _parse_frontmatter(content)
            name = meta.get("name") or skill_md.parent.name
            desc = meta.get("description") or ""
            skills.append(SkillMetadata(name=name, description=desc, path=skill_md))

    # De-duplicate by skill name, keeping the first occurrence.
    seen: set[str] = set()
    deduped: list[SkillMetadata] = []
    for skill in skills:
        if skill.name in seen:
            continue
        seen.add(skill.name)
        deduped.append(skill)
    return deduped


def exec_unsafe(code_path: Path) -> int:
    return subprocess.call([sys.executable, "local/unsafe_exec.py", str(code_path)])


def exec_docker(code_path: Path) -> int:
    return subprocess.call([sys.executable, "local/sandbox_docker.py", str(code_path)])


def tool_list_files(inp: Json) -> str:
    raw = (inp.get("path") or ".").strip() or "."
    root = Path(raw)
    if not root.exists():
        raise FileNotFoundError(f"{root} does not exist")

    items: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if str(rel) == ".":
            continue
        items.append(rel.as_posix() + ("/" if p.is_dir() else ""))

    return json.dumps(items)


def tool_read_file(inp: Json) -> str:
    path = (inp.get("path") or "").strip()
    if not path:
        raise ValueError("path is required")
    p = Path(path)
    if not p.exists() or p.is_dir():
        raise FileNotFoundError(f"Not a file: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


def tool_list_skills(inp: Json) -> str:
    payload = [
        {
            "name": s.name,
            "description": s.description,
            "path": s.path.as_posix(),
        }
        for s in SKILLS
    ]
    return json.dumps(payload)


def tool_read_skill(inp: Json) -> str:
    name = (inp.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    skill = SKILLS_BY_NAME.get(name)
    if not skill:
        raise FileNotFoundError(f"Unknown skill: {name}")
    return skill.path.read_text(encoding="utf-8", errors="replace")


def tool_run_python(inp: Json) -> str:
    """Execute a python file via the selected executor."""
    script = (inp.get("script") or "").strip()
    executor = (inp.get("executor") or "").strip()

    if not script:
        raise ValueError("script is required")
    if executor not in {"unsafe", "docker"}:
        raise ValueError("executor must be 'unsafe' or 'docker'")

    script_path = Path(script).expanduser().resolve()
    if not script_path.exists() or script_path.suffix != ".py":
        raise FileNotFoundError(f"Not a python file: {script_path}")

    print(f"\n[tool] run_python executor={executor} script={script_path}")
    exec_fn = exec_docker if executor == "docker" else exec_unsafe
    rc = exec_fn(script_path)
    return json.dumps({"exit_code": rc})


def tool_run_js(inp: Json) -> str:
    """Execute a JavaScript file via a Node.js isolated-vm runner."""
    script = (inp.get("script") or "").strip()
    executor = (inp.get("executor") or "node_vm").strip()

    if not script:
        raise ValueError("script is required")
    if executor != "node_vm":
        raise ValueError("executor must be 'node_vm'")

    script_path = Path(script).expanduser().resolve()
    if not script_path.exists() or script_path.suffix != ".js":
        raise FileNotFoundError(f"Not a JavaScript file: {script_path}")

    print(f"\n[tool] run_js executor={executor} script={script_path}")
    p = subprocess.run(
        [sys.executable, "local/sandbox_node.py", str(script_path)],
        text=True,
        capture_output=True,
    )

    if p.stdout:
        print(p.stdout, end="")
    if p.stderr:
        print(p.stderr, end="", file=sys.stderr)

    output_dir = None
    for line in reversed(p.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict) and "output_dir" in parsed:
            output_dir = parsed.get("output_dir")
            break

    payload: Json = {"exit_code": p.returncode}
    if output_dir:
        payload["output_dir"] = output_dir
    return json.dumps(payload)


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="list_files",
            description="List files and directories recursively under a path (default: current directory).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default: '.')",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            fn=tool_list_files,
        ),
        Tool(
            name="read_file",
            description="Read a UTF-8 text file and return its contents.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to a text file"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            fn=tool_read_file,
        ),
        Tool(
            name="list_skills",
            description="List available skills and their metadata.",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            fn=tool_list_skills,
        ),
        Tool(
            name="read_skill",
            description="Read a skill's SKILL.md by name.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name from metadata",
                    }
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            fn=tool_read_skill,
        ),
        Tool(
            name="run_python",
            description=(
                "Run a local Python script using either a SAFE docker sandbox or an UNSAFE host executor. "
                "Use docker unless the user explicitly requests unsafe."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "Path to a .py script (e.g. 'examples/benign.py')",
                    },
                    # "executor": {
                    #     "type": "string",
                    #     "enum": ["docker", "unsafe"],
                    #     "description": "Execution backend",
                    # },
                },
                "required": ["script"],
                "additionalProperties": False,
            },
            fn=tool_run_python,
        ),
        Tool(
            name="run_js",
            description=(
                "Run a JavaScript file using a Node.js isolated-vm runner. "
                "This is a demo-only isolation boundary, not a hardened sandbox."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "Path to a .js script (e.g. 'examples/benign.js')",
                    },
                    "executor": {
                        "type": "string",
                        "enum": ["node_vm"],
                        "description": "Execution backend",
                    },
                },
                "required": ["script"],
                "additionalProperties": False,
            },
            fn=tool_run_js,
        ),
    ]


SYSTEM_PROMPT = """You are a demo coding-agent controller.

You can interact with the local repo only via tools.

Rules:
- Prefer run_python for any code execution.
 - The run_js tool uses isolated-vm and is demo-only, not a hardened sandbox.
- If you need to inspect files before running code, call list_files/read_file.
- If a task matches an available skill, load its instructions with read_skill before acting.
- After tool calls, explain what happened and what the result implies for security.
"""


RATIONALITY_ADDENDUM = """
When you respond, include a short section titled 'Rationale' (1-3 sentences) that explains at a high level why you chose the next action/tool(s).

Constraints:
- Do NOT reveal private chain-of-thought or hidden reasoning. Keep it brief and user-facing.
- It's OK to say you need to inspect files first, run in docker for safety, etc.
"""


def _truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "...<truncated>"


def _print_trace_line(label: str, payload: str) -> None:
    # Keep trace lines readable and non-spammy.
    print(f"\n[trace] {label}: {payload}")


def _execute_tool(tools_by_name: dict[str, Tool], name: str, arguments: str) -> str:
    if name not in tools_by_name:
        return json.dumps({"error": f"unknown tool: {name}"})
    tool = tools_by_name[name]
    try:
        parsed = (
            json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        )
        out = tool.fn(parsed)
        return out if isinstance(out, str) else json.dumps(out)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def _stream_chat_with_tools(
    client: OpenAI,
    model: str,
    messages: list[Json],
    tools: list[Json],
    extra_body: Json | None = None,
    show_thinking: bool = False,
) -> tuple[str, list[Json], str]:
    """Stream assistant text; accumulate any tool calls and reasoning content.

    Returns:
        - assistant_text (what we streamed)
        - tool_calls (OpenAI-compatible list of tool calls, if any)
        - reasoning_content (raw reasoning content, if any)

    Z.AI supports streaming via the OpenAI SDK-compatible interface.
    """

    streamed_text_parts: list[str] = []
    reasoning_parts: list[str] = []
    thinking_started = False

    # Accumulate tool calls from streaming deltas.
    # OpenAI streaming tool_calls arrive as incremental deltas per call index.
    tool_calls_acc: dict[int, dict[str, Any]] = {}

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        stream=True,
        extra_body=extra_body,
    )

    for chunk in stream:
        choice = chunk.choices[0]
        delta = choice.delta

        if getattr(delta, "content", None):
            s = delta.content
            streamed_text_parts.append(s)
            sys.stdout.write(s)
            sys.stdout.flush()

        # Preserve reasoning content (optionally print inline to stderr).
        if getattr(delta, "reasoning_content", None):
            s = delta.reasoning_content
            reasoning_parts.append(s)
            if show_thinking:
                if not thinking_started:
                    sys.stderr.write("\n[thinking]\n")
                    thinking_started = True
                sys.stderr.write(s)
                sys.stderr.flush()

        # Tool call deltas
        tc_delta = getattr(delta, "tool_calls", None)
        if tc_delta:
            for tcd in tc_delta:
                idx = tcd.index
                cur = tool_calls_acc.setdefault(
                    idx,
                    {
                        "id": None,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )

                if getattr(tcd, "id", None):
                    cur["id"] = tcd.id
                if getattr(tcd, "type", None):
                    cur["type"] = tcd.type

                fn = getattr(tcd, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        cur["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        cur["function"]["arguments"] += fn.arguments

        if choice.finish_reason is not None:
            # End of stream for this response.
            break

    print()  # newline after streaming

    if show_thinking and thinking_started:
        sys.stderr.write("\n[/thinking]\n")
        sys.stderr.flush()

    tool_calls: list[Json] = [tool_calls_acc[i] for i in sorted(tool_calls_acc.keys())]
    return "".join(streamed_text_parts), tool_calls, "".join(reasoning_parts)


def _build_thinking_body(
    thinking_mode: str,
    preserve_thinking: bool | None,
) -> Json | None:
    if thinking_mode == "auto" and preserve_thinking is None:
        return None

    body: Json = {}
    if thinking_mode != "auto":
        body["thinking"] = {"type": thinking_mode}
    else:
        body["thinking"] = {}

    if preserve_thinking is not None:
        body["thinking"]["clear_thinking"] = not preserve_thinking

    if not body["thinking"]:
        return None
    return body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.getenv("ZAI_MODEL", "glm-4.7"))
    ap.add_argument(
        "--base-url",
        default=os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4/"),
        help="Z.AI OpenAI-compatible base URL",
    )
    ap.add_argument(
        "--default-executor",
        choices=["docker", "unsafe"],
        default=os.getenv("DEFAULT_EXECUTOR", "docker"),
        help="Default executor if the user doesn't specify one",
    )
    ap.add_argument(
        "--show-rationale",
        action="store_true",
        help=(
            "Ask the model to include a brief 'Rationale' section (high-level, user-facing; not chain-of-thought)."
        ),
    )
    ap.add_argument(
        "--show-trace",
        action="store_true",
        help="Print tool-call trace (tool names/args + tool outputs; useful for demos and debugging).",
    )
    ap.add_argument(
        "--show-thinking",
        action="store_true",
        help="Stream model reasoning_content inline to stderr.",
    )
    ap.add_argument(
        "--trace-max-chars",
        type=int,
        default=4000,
        help="Max characters to print per traced tool output (default: 4000).",
    )
    ap.add_argument(
        "--skills-dir",
        action="append",
        default=["skills"],
        help="Directory to scan for skills (repeatable)",
    )
    ap.add_argument(
        "--thinking",
        choices=["auto", "enabled", "disabled"],
        default=os.getenv("ZAI_THINKING", "auto"),
        help="Thinking mode per request (auto omits the field).",
    )

    args = ap.parse_args()

    api_key = os.getenv("ZAI_API_KEY")
    if not api_key:
        print("Missing ZAI_API_KEY env var")
        return 2

    # Z.AI is OpenAI-SDK compatible via api_key + base_url. citeturn1view0
    client = OpenAI(api_key=api_key, base_url=args.base_url)

    skill_dirs = [Path(p).expanduser().resolve() for p in args.skills_dir]
    skills = discover_skills(skill_dirs)
    SKILLS.clear()
    SKILLS.extend(skills)
    SKILLS_BY_NAME.clear()
    SKILLS_BY_NAME.update({s.name: s for s in skills})

    tools = build_tools()
    tools_by_name = {t.name: t for t in tools}
    tool_specs = [t.as_openai_tool() for t in tools]

    extra_body = _build_thinking_body(args.thinking, True)

    messages: list[Json] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Repo context: You are running inside secure-agent-exec-demo. "
                "Example scripts: examples/benign.py and examples/malicious.py. "
                f"Default executor is '{args.default_executor}' unless the user says otherwise."
            ),
        },
    ]

    if args.show_rationale:
        messages.insert(1, {"role": "system", "content": RATIONALITY_ADDENDUM})

    if SKILLS:
        skills_lines: list[str] = ["Available skills:"]
        cwd = Path.cwd()
        for s in SKILLS:
            try:
                loc = s.path.relative_to(cwd).as_posix()
            except Exception:
                loc = s.path.as_posix()
            skills_lines.append(f"- name: {s.name}")
            skills_lines.append(f"  description: {s.description}")
            skills_lines.append(f"  location: {loc}")
        messages.append({"role": "system", "content": "\n".join(skills_lines)})

    print("Chat with agent (streaming). Ctrl+C to quit.\n")

    while True:
        user = input("\033[94mYou\033[0m: ").strip()
        if not user:
            continue

        messages.append({"role": "user", "content": user})

        print("\033[93mAgent\033[0m: ", end="", flush=True)
        assistant_text, tool_calls, reasoning_content = _stream_chat_with_tools(
            client=client,
            model=args.model,
            messages=messages,
            tools=tool_specs,
            extra_body=extra_body,
            show_thinking=args.show_thinking,
        )

        # Record assistant message in the transcript.
        assistant_msg: Json = {"role": "assistant", "content": assistant_text}
        if reasoning_content:
            assistant_msg["reasoning_content"] = reasoning_content
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        while tool_calls:
            # Execute tools in order, then send tool results back and stream a follow-up.
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args_json = fn.get("arguments") or "{}"

                # Convenience: if the model omitted executor for run_python, patch in default.
                if name == "run_python":
                    try:
                        parsed = (
                            json.loads(args_json)
                            if isinstance(args_json, str)
                            else dict(args_json)
                        )
                    except Exception:
                        parsed = {}
                    if "executor" not in parsed:
                        parsed["executor"] = args.default_executor
                        args_json = json.dumps(parsed)
                if name == "run_js":
                    try:
                        parsed = (
                            json.loads(args_json)
                            if isinstance(args_json, str)
                            else dict(args_json)
                        )
                    except Exception:
                        parsed = {}
                    if "executor" not in parsed:
                        parsed["executor"] = "node_vm"
                        args_json = json.dumps(parsed)

                if args.show_trace:
                    _print_trace_line(
                        "tool_call", f"{name} args={_truncate(str(args_json), 800)}"
                    )

                tool_output = _execute_tool(tools_by_name, name, args_json)

                if args.show_trace:
                    _print_trace_line(
                        "tool_output",
                        f"{name} -> {_truncate(str(tool_output), args.trace_max_chars)}",
                    )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": tool_output,
                    }
                )

            print("\033[93mAgent\033[0m: ", end="", flush=True)
            followup_text, tool_calls, followup_reasoning = _stream_chat_with_tools(
                client=client,
                model=args.model,
                messages=messages,
                tools=tool_specs,
                extra_body=extra_body,
                show_thinking=args.show_thinking,
            )
            assistant_followup: Json = {"role": "assistant", "content": followup_text}
            if followup_reasoning:
                assistant_followup["reasoning_content"] = followup_reasoning
            if tool_calls:
                assistant_followup["tool_calls"] = tool_calls
            messages.append(assistant_followup)


if __name__ == "__main__":
    raise SystemExit(main())
