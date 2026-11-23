"""GitHub status and PR-head checks used by the trusted commit identity workflow."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

MAX_OPEN_PRS = 1000


class GitHub:
    def __init__(self, token: str, repo: str, api: str = "https://api.github.com"):
        self.token, self.repo, self.api = token, repo, api.rstrip("/")

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, object, dict]:
        url = path if path.startswith("http") else f"{self.api}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, json.loads(raw) if raw else None, dict(resp.headers)
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = None
            return err.code, payload, dict(err.headers)

    def get(self, path: str) -> object:
        status, payload, _ = self.request("GET", path)
        if status != 200:
            raise RuntimeError(f"GET {path} failed with {status}: {payload}")
        return payload

    def paginate(self, path: str, limit: int | None = None) -> list:
        items: list = []
        url = f"{self.api}{path}{'&' if '?' in path else '?'}per_page=100"
        while url:
            status, payload, headers = self.request("GET", url)
            if status != 200:
                raise RuntimeError(f"GET {url} failed with {status}: {payload}")
            items.extend(payload)
            if limit and len(items) >= limit:
                return items
            links = headers.get("Link") or headers.get("link") or ""
            url = next((part.split(";")[0].strip(" <>") for part in links.split(",") if 'rel="next"' in part), None)
        return items


def open_prs_at_head(gh: GitHub, sha: str) -> list[dict]:
    """A commit status is shared by every PR at a SHA; require a unique owner."""
    pulls = gh.paginate(f"/repos/{gh.repo}/pulls?state=open", limit=MAX_OPEN_PRS)
    if len(pulls) >= MAX_OPEN_PRS:
        raise RuntimeError("Open PR listing reached its safety limit; cannot prove head uniqueness")
    if any(not isinstance(pr, dict) or not isinstance(pr.get("number"), int)
           or pr.get("state") != "open" or not (pr.get("head") or {}).get("sha") for pr in pulls):
        raise RuntimeError("Incomplete open PR listing; cannot prove head uniqueness")
    return [pr for pr in pulls if pr["head"]["sha"] == sha]


def head_blockers(gh: GitHub, pr: dict) -> list[str]:
    """Require the current PR to be the only open PR publishing a status on this SHA."""
    peers = open_prs_at_head(gh, pr["head"]["sha"])
    numbers = sorted({peer["number"] for peer in peers})
    if pr["number"] not in numbers:
        raise RuntimeError("Pull request changed while checking its head; recheck")
    if len(numbers) > 1:
        refs = ", ".join(f"#{number}" for number in numbers)
        return [f"Open pull requests {refs} share the same head commit. Close duplicates, then recheck the remaining pull request."]
    return []


def set_status(gh: GitHub, sha: str, state: str, description: str, *, context: str) -> None:
    body = {"state": state, "context": context, "description": description[:140]}
    status, _, _ = gh.request("POST", f"/repos/{gh.repo}/statuses/{sha}", body)
    if status != 201:
        raise RuntimeError(f"Could not write {context} status ({status})")
