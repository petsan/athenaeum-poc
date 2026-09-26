"""
Reviewer identity for the API's write endpoints (owner decision 7,
2026-09-26): per-reviewer bearer tokens, from a local file that is never
part of the repository.

The file (`<data_dir>/reviewers.json`, or the path in
$ATHENAEUM_REVIEWERS_FILE) holds only SHA-256 hashes of tokens -- a leaked
file doesn't leak a usable token -- plus the curator allow-list of hosts that
ingestion may fetch from:

    {"reviewers": [{"id": "alice", "role": "reviewer", "token_sha256": "..."}],
     "ingestion_allowlist": ["en.wikipedia.org", "arxiv.org"]}

`scripts/add_reviewer.py` mints a token, stores its hash, and prints the
token once. With no file (or no reviewers in it), every write endpoint is
refused: authentication is opt-in, and its absence means read-only, never
open.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REVIEWERS_FILE_ENV = "ATHENAEUM_REVIEWERS_FILE"
ROLES = ("owner", "reviewer", "member", "service")   # human_input.ROLES, Section 11.7


@dataclass(frozen=True)
class Identity:
    reviewer_id: str
    role: str


def reviewers_path(data_dir: Path) -> Path:
    return Path(os.environ.get(REVIEWERS_FILE_ENV) or Path(data_dir) / "reviewers.json")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    if not path.exists():
        return {"reviewers": [], "ingestion_allowlist": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"reviewers": list(data.get("reviewers", [])),
            "ingestion_allowlist": [h.lower() for h in data.get("ingestion_allowlist", [])]}


class Reviewers:
    """Read fresh from the file on every check, so adding or revoking a
    reviewer takes effect without restarting the server."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def configured(self) -> bool:
        return bool(_load(self.path)["reviewers"])

    @property
    def allowlist(self) -> list[str]:
        return _load(self.path)["ingestion_allowlist"]

    def authenticate(self, authorization: str | None) -> Identity | None:
        """`Authorization: Bearer <token>` -> the identity it belongs to, or
        None. Every stored hash is compared, in constant time, so neither a
        match nor its position is observable from timing."""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        presented = _hash(authorization[len("Bearer "):].strip())
        found = None
        for r in _load(self.path)["reviewers"]:
            if hmac.compare_digest(presented, r.get("token_sha256", "")):
                found = Identity(r["id"], r["role"])
        return found


def add_reviewer(path: Path, reviewer_id: str, role: str, allow_hosts: list[str] = ()) -> str:
    """Mints a token for `reviewer_id`, stores only its hash, and returns the
    token -- the only time it is ever available. Re-adding an id replaces
    its token (revoking the old one)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    path = Path(path)
    data = _load(path)
    token = secrets.token_urlsafe(32)
    data["reviewers"] = [r for r in data["reviewers"] if r["id"] != reviewer_id]
    data["reviewers"].append({"id": reviewer_id, "role": role, "token_sha256": _hash(token)})
    data["ingestion_allowlist"] = sorted(set(data["ingestion_allowlist"]) | {h.lower() for h in allow_hosts})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(path, 0o600)   # owner-only where the filesystem supports it
    except OSError:
        pass
    return token
