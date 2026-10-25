from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class Workspace:
    """A throwaway git repository with helpers to script an agent run."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / "repo"
        self.path.mkdir()
        self.trace: list[dict[str, Any]] = []
        self.git("init", "-q", "-b", "main")
        self.write("app.py", "def f():\n    return 1\n", record=False)
        self.write("tests/test_app.py", "def test_f():\n    assert True\n", record=False)
        self.commit("init")
        self.base = self.rev()

    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True,
                              env={**os.environ, **GIT_ENV}, check=True)  # fmt: skip
        return proc.stdout.strip()

    def rev(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref)

    def write(self, rel: str, text: str, record: bool = True) -> None:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        if record:
            self.trace.append({"type": "file_write", "path": rel})

    def commit(self, msg: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def cmd(self, command: str, exit_code: int | None, output: str = "") -> None:
        self.trace.append({"type": "command", "command": command, "exit_code": exit_code, "output": output})

    def save_trace(self) -> Path:
        p = self.root / "trace.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in self.trace))
        return p


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


@pytest.fixture
def fixture_file(tmp_path: Path) -> Callable[[dict[str, Any]], Path]:
    def make(table: dict[str, Any]) -> Path:
        p = tmp_path / "github.json"
        p.write_text(json.dumps(table))
        return p

    return make
