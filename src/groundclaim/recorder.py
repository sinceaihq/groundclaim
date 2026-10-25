"""Write GroundClaim JSONL traces from an agent harness.

    from groundclaim import Recorder

    with Recorder("run.jsonl") as rec:
        rec.command("pytest -q", exit_code=0, output=out)   # a command the agent ran
        rec.file_write("src/app.py")                        # a file the agent changed
        rec.message("Fixed the bug; all tests pass.")       # the agent's final words

The harness, not the agent, should write the trace: evidence from a trace is
"observed", i.e. as trustworthy as whatever recorded it. Output is stored as a
redacted tail, never in full.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from .trace import redact, snippet


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


class Recorder:
    def __init__(self, path: str | Path, revision: str | None = None):
        self.path = Path(path)
        self.revision = revision
        self._fh = self.path.open("a", encoding="utf-8")

    def _write(self, row: dict[str, Any]) -> None:
        row.setdefault("time", _now())
        self._fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._fh.flush()

    def command(
        self, command: str, exit_code: int | None, output: str = "", revision: str | None = None
    ) -> None:
        row: dict[str, Any] = {
            "type": "command",
            "command": redact(command),
            "exit_code": exit_code,
            "output": snippet(output, 4000),
        }
        if revision or self.revision:
            row["revision"] = revision or self.revision
        self._write(row)

    def run(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """Run a command for the agent (no shell) and record it."""
        kwargs.setdefault("capture_output", True)
        kwargs.setdefault("text", True)
        proc = subprocess.run(list(args), check=False, **kwargs)
        self.command(" ".join(args), proc.returncode, f"{proc.stdout or ''}\n{proc.stderr or ''}")
        return proc

    def file_write(self, path: str) -> None:
        self._write({"type": "file_write", "path": path})

    def message(self, text: str) -> None:
        self._write({"type": "message", "role": "assistant", "text": text})

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
