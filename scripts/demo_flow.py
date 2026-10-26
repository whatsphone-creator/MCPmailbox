#!/usr/bin/env python3
"""Start a local mailbox and prove A post → B list → B ack → no longer pending.

Run from the repo root: python scripts/demo_flow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from mcpmailbox.scenario import IMAGE_URL, POST_TEXT, run_p0_demo  # noqa: E402

TOKEN_A = "demo-token-grok"
TOKEN_B = "demo-token-codex"
AGENT_A = "grok-博士"
AGENT_B = "codex-main"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_health(port: int, proc: subprocess.Popen[bytes], log_path: Path) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"server exited {proc.returncode}\n{log_path.read_text(encoding='utf-8')}")
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise SystemExit(f"server did not become healthy\n{log_path.read_text(encoding='utf-8')}")


def main() -> None:
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        log_path = tmp_path / "server.log"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        env["MAILBOX_HOST"] = "127.0.0.1"
        env["MAILBOX_PORT"] = str(port)
        env["MAILBOX_DB"] = str(tmp_path / "mailbox.sqlite")
        env["MAILBOX_PUBLIC_URL"] = url
        env["MAILBOX_TOKENS"] = json.dumps({TOKEN_A: AGENT_A, TOKEN_B: AGENT_B}, ensure_ascii=False)
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "mcpmailbox"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                _wait_health(port, proc, log_path)
                summary = asyncio.run(run_p0_demo(url, TOKEN_A, TOKEN_B, agent_b=AGENT_B))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

    print(f"A ({AGENT_A}) mailbox_post text={POST_TEXT!r} image={IMAGE_URL}")
    print(f"B ({AGENT_B}) mailbox_list pending 看到 {summary['id']}")
    print(f"B mailbox_ack {summary['id']}")
    print("B mailbox_list pending 不再包含這則")
    print(f"A mailbox_list pending 不包含這則；A mailbox_get status={summary['status']}")
    print("demo ok")


if __name__ == "__main__":
    main()
