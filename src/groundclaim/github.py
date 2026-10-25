"""Read-only GitHub REST API queries (independent evidence about CI, PRs, deployments, releases).

Only GET requests are made. A token is optional (public repositories work without
one, at a lower rate limit); it is read from the environment by the CLI and is
never written to reports.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .git import safe_ref

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
# (path with query) -> (HTTP status, parsed JSON body)
Transport = Callable[[str], tuple[int, Any]]


class GitHubError(RuntimeError):
    pass


def http_transport(token: str | None, api: str = "https://api.github.com", timeout: float = 20) -> Transport:
    def get(path: str) -> tuple[int, Any]:
        req = urllib.request.Request(api + path, method="GET")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "groundclaim")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read(20_000_000) or b"null")
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read(100_000) or b"null")
            except ValueError:
                body = None
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise GitHubError(f"GitHub API request failed: {exc}") from exc

    return get


def fixture_transport(path: Path) -> Transport:
    """Answers from a JSON file {"/repos/o/r/...": {"status": 200, "body": ...}}; anything else is a 404.

    For list endpoints queried with filters (``?sha=``, ``?environment=``, ``?head=``) the
    unfiltered list is filtered the way GitHub does, so fixtures need one entry per endpoint.
    """
    table = json.loads(path.read_text(encoding="utf-8"))

    def get(p: str) -> tuple[int, Any]:
        if p in table:
            return table[p]["status"], table[p].get("body")
        base, _, query = p.partition("?")
        hit = table.get(base)
        if not hit:
            return 404, {"message": "Not Found"}
        body = hit.get("body")
        if isinstance(body, list):
            for key, value in urllib.parse.parse_qsl(query):
                if key == "sha":
                    body = [x for x in body if x.get("sha") == value or x.get("ref") == value]
                elif key == "environment":
                    body = [x for x in body if x.get("environment") == value]
                elif key == "head":
                    body = [x for x in body if (x.get("head") or {}).get("label") == value]
        return hit["status"], body

    return get


class GitHub:
    def __init__(self, repo: str, transport: Transport):
        if not REPO_RE.match(repo):
            raise GitHubError(f"not an owner/name repository: {repo!r}")
        self.repo = repo
        self.owner = repo.split("/", 1)[0]
        self._get = transport
        self._cache: dict[str, tuple[int, Any]] = {}

    def get(self, path: str, **query: str | int) -> tuple[int, Any]:
        full = f"/repos/{self.repo}{path}"
        if query:
            full += "?" + urllib.parse.urlencode(query)
        if full not in self._cache:
            status, body = self._get(full)
            if status in (401, 403, 429) or status >= 500:
                msg = (body or {}).get("message", "") if isinstance(body, dict) else ""
                raise GitHubError(f"GitHub API {status} for {path}: {msg}".strip())
            self._cache[full] = (status, body)
        return self._cache[full]

    def refresh(self) -> None:
        """Forget cached answers (to poll for changes)."""
        self._cache.clear()

    def check_runs(self, sha: str) -> list[dict[str, Any]]:
        status, body = self.get(f"/commits/{safe_ref(sha)}/check-runs", per_page=100)
        return list(body.get("check_runs", [])) if status == 200 and isinstance(body, dict) else []

    def statuses(self, sha: str) -> list[dict[str, Any]]:
        status, body = self.get(f"/commits/{safe_ref(sha)}/status")
        return list(body.get("statuses", [])) if status == 200 and isinstance(body, dict) else []

    def commit_exists(self, sha: str) -> bool:
        return self.get(f"/commits/{safe_ref(sha)}")[0] == 200

    def branch_contains(self, branch: str, sha: str) -> bool | None:
        """True if ``sha`` is in the history of ``branch`` on GitHub; None if the branch or commit is unknown there."""
        b = urllib.parse.quote(safe_ref(branch), safe="")
        status, body = self.get(f"/compare/{b}...{safe_ref(sha)}")
        if status != 200 or not isinstance(body, dict):
            return None
        return body.get("status") in ("identical", "behind")

    def branch_exists(self, branch: str) -> bool:
        return self.get(f"/branches/{urllib.parse.quote(safe_ref(branch), safe='')}")[0] == 200

    def pull(self, number: int) -> dict[str, Any] | None:
        status, body = self.get(f"/pulls/{int(number)}")
        return body if status == 200 and isinstance(body, dict) else None

    def pulls_for_branch(self, branch: str) -> list[dict[str, Any]]:
        status, body = self.get("/pulls", head=f"{self.owner}:{safe_ref(branch)}", state="all")
        return list(body) if status == 200 and isinstance(body, list) else []

    def deployments(self, sha: str, environment: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, str | int] = {"sha": safe_ref(sha)}
        if environment:
            query["environment"] = environment
        status, body = self.get("/deployments", **query)
        return list(body) if status == 200 and isinstance(body, list) else []

    def deployment_statuses(self, deployment_id: int) -> list[dict[str, Any]]:
        status, body = self.get(f"/deployments/{int(deployment_id)}/statuses")
        return list(body) if status == 200 and isinstance(body, list) else []

    def release(self, tag: str) -> dict[str, Any] | None:
        status, body = self.get(f"/releases/tags/{urllib.parse.quote(safe_ref(tag), safe='')}")
        return body if status == 200 and isinstance(body, dict) else None
