"""The repository being checked may have been prepared by the agent. Reading it must never run its programs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from groundclaim.git import GitError, Repo, find_test_tampering, safe_ref

from .conftest import Workspace


def _plant(ws: Workspace) -> Path:
    marker = ws.root / "pwned"
    m = marker.as_posix()  # git runs these through sh, also on Windows
    for key, value in [
        ("filter.evil.clean", f"touch {m}-clean; cat"),
        ("filter.evil.smudge", f"touch {m}-smudge; cat"),
        ("diff.evil.textconv", f"touch {m}-textconv; cat"),
        ("diff.external", f"touch {m}-external"),
        ("core.fsmonitor", f"touch {m}-fsmonitor"),
        ("core.pager", f"touch {m}-pager"),
        ("log.showSignature", "true"),
        ("gpg.program", f"touch {m}-gpg"),
    ]:
        ws.git("config", key, value)
    (ws.path / ".gitattributes").write_text("*.py filter=evil diff=evil\n")
    (ws.path / "app.py").write_text("def f():\n    return 2\n")
    os.utime(ws.path / "app.py", (978307200, 978307200))  # stat-dirty, so git status runs the clean filter
    return marker


def test_reading_a_hostile_repository_runs_nothing(ws: Workspace) -> None:
    _plant(ws)
    repo = Repo(ws.path)
    assert repo.is_repo()
    repo.head()
    repo.uncommitted()
    repo.changed_files(ws.base, None)
    repo.diff_text(ws.base, None)
    repo.commit_info("HEAD")
    find_test_tampering(repo, ws.base, None)
    planted = sorted(p.name for p in ws.root.iterdir() if p.name.startswith("pwned"))
    assert planted == []


def test_the_hostile_repository_is_really_hostile(ws: Workspace) -> None:
    # Control: plain git does run the planted programs, so the test above is meaningful.
    marker = _plant(ws)
    subprocess.run(["git", "-C", str(ws.path), "status", "--short"], capture_output=True, check=False)
    subprocess.run(["git", "-C", str(ws.path), "diff"], capture_output=True, check=False)
    assert any(p.name.startswith(marker.name) for p in ws.root.iterdir())


@pytest.mark.parametrize("ref", ["--output=/tmp/x", "-c", "a..b", "x;rm -rf /", "$(id)", "", "a b"])
def test_unsafe_refs_are_refused(ref: str) -> None:
    with pytest.raises(GitError):
        safe_ref(ref)


def test_tampering_is_detected(ws: Workspace) -> None:
    ws.write("tests/test_app.py", "import pytest\n\n@pytest.mark.skip\ndef test_f():\n    assert True\n")
    (ws.path / "tests" / "test_other.py").write_text("def test_g():\n    pass\n")
    ws.commit("add")
    base2 = ws.rev()
    (ws.path / "tests" / "test_other.py").unlink()
    repo = Repo(ws.path)
    found = find_test_tampering(repo, ws.base, None)
    assert any("test disabled" in f for f in found)
    assert any("deleted: tests/test_other.py" in f for f in find_test_tampering(repo, base2, None))
