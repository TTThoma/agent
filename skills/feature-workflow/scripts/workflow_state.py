#!/usr/bin/env python3
"""Deterministic state ledger for the feature-workflow skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_ORDER = (
    "spec",
    "plan-review",
    "implementation",
    "verification",
    "reconstruction",
    "intent-comparison",
    "deep-review",
    "candidate",
    "reviewer-map",
    "approval",
    "published",
)

REQUIRED_ORDER = tuple(name for name in ARTIFACT_ORDER if name != "deep-review")

DEPENDENCIES = {
    "spec": (),
    "plan-review": ("spec",),
    "implementation": ("spec", "plan-review"),
    "verification": ("implementation",),
    "reconstruction": ("implementation",),
    "intent-comparison": ("reconstruction", "spec"),
    "deep-review": ("intent-comparison",),
    "candidate": ("verification", "intent-comparison"),
    "reviewer-map": ("candidate", "reconstruction", "verification"),
    "approval": ("reviewer-map", "candidate"),
    "published": ("approval", "candidate"),
}

PATH_REQUIRED = {
    "spec",
    "plan-review",
    "verification",
    "reconstruction",
    "intent-comparison",
    "deep-review",
    "reviewer-map",
    "approval",
}

HEAD_BOUND = set(ARTIFACT_ORDER) - {"spec", "plan-review"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")


class WorkflowError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed"
        raise WorkflowError(detail)
    return proc.stdout.strip()


def repo_root(value: str) -> Path:
    candidate = Path(value).expanduser().resolve()
    root = run_git(candidate, "rev-parse", "--show-toplevel")
    return Path(root).resolve()


def validate_slug(slug: str) -> None:
    if not SLUG_RE.fullmatch(slug):
        raise WorkflowError("slug must use lowercase letters, digits, dots, underscores, or hyphens")


def state_dir(repo: Path, slug: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    raw = run_git(repo, "rev-parse", "--git-path", f"feature-workflow/{slug}")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def state_path(repo: Path, slug: str, override: str | None) -> Path:
    return state_dir(repo, slug, override) / "state.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(repo: Path, base_ref: str) -> dict[str, Any]:
    run_git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    head_sha = run_git(repo, "rev-parse", "HEAD")
    base_sha = run_git(repo, "merge-base", base_ref, "HEAD")
    dirty = run_git(repo, "status", "--porcelain", "--untracked-files=normal")
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "worktree_clean": not bool(dirty),
        "dirty_entries": dirty.splitlines(),
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"run not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid state file {path}: {exc}") from exc
    if data.get("schema_version") != 1 or not isinstance(data.get("artifacts"), dict):
        raise WorkflowError(f"unsupported state file: {path}")
    return data


def write_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    fd, temporary = tempfile.mkstemp(prefix="state.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def evaluate(state: dict[str, Any], repo: Path) -> dict[str, Any]:
    current = snapshot(repo, state["base_ref"])
    statuses: dict[str, dict[str, Any]] = {}

    for name in ARTIFACT_ORDER:
        record = state["artifacts"].get(name)
        if record is None:
            statuses[name] = {"status": "absent", "reasons": []}
            continue

        reasons: list[str] = []
        status = "current"

        if record.get("invalidated"):
            status = "stale"
            reasons.append(record.get("invalidation_reason") or "explicitly invalidated")

        artifact_path = record.get("path")
        if artifact_path:
            file_path = Path(artifact_path)
            if not file_path.is_file():
                status = "missing"
                reasons.append("artifact file is missing")
            elif sha256_file(file_path) != record.get("sha256"):
                status = "stale"
                reasons.append("artifact content changed after it was recorded")

        if name in HEAD_BOUND:
            if record.get("base_sha") != current["base_sha"]:
                status = "stale"
                reasons.append("base SHA changed")
            if record.get("head_sha") != current["head_sha"]:
                status = "stale"
                reasons.append("HEAD changed")
            if not current["worktree_clean"]:
                status = "stale"
                reasons.append("worktree has uncommitted changes")

        for dependency, recorded_revision in record.get("dependencies", {}).items():
            dependency_record = state["artifacts"].get(dependency)
            dependency_status = statuses.get(dependency, {}).get("status")
            if dependency_record is None:
                status = "stale"
                reasons.append(f"dependency {dependency} is missing")
            elif dependency_record.get("revision") != recorded_revision:
                status = "stale"
                reasons.append(f"dependency {dependency} was replaced")
            elif dependency_status != "current":
                status = "stale"
                reasons.append(f"dependency {dependency} is {dependency_status}")

        statuses[name] = {"status": status, "reasons": sorted(set(reasons))}

    next_artifact = None
    for name in REQUIRED_ORDER:
        if statuses[name]["status"] != "current":
            next_artifact = name
            break

    return {
        "run": state["slug"],
        "source": state["source"],
        "base_ref": state["base_ref"],
        **current,
        "complete": statuses["published"]["status"] == "current",
        "next_artifact": next_artifact,
        "artifacts": statuses,
    }


def require_current_dependencies(state: dict[str, Any], repo: Path, artifact: str) -> dict[str, Any]:
    report = evaluate(state, repo)
    blocked = [
        dependency
        for dependency in DEPENDENCIES[artifact]
        if report["artifacts"][dependency]["status"] != "current"
    ]
    if blocked:
        raise WorkflowError(f"cannot record {artifact}; dependencies are not current: {', '.join(blocked)}")
    if artifact in {"candidate", "approval", "published"}:
        deep_status = report["artifacts"]["deep-review"]["status"]
        if deep_status not in {"absent", "current"}:
            raise WorkflowError(f"cannot record {artifact}; optional deep-review is {deep_status}")
    return report


def cmd_init(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    if path.exists():
        if not args.resume:
            raise WorkflowError(f"run already exists: {path}; use --resume or choose another slug")
        state = load_state(path)
        print(json.dumps(evaluate(state, repo), indent=2, sort_keys=True))
        return 0

    current = snapshot(repo, args.base_ref)
    if not current["worktree_clean"] and not args.allow_dirty:
        raise WorkflowError("worktree is dirty; isolate the work or pass --allow-dirty after inspecting it")

    now = utc_now()
    state = {
        "schema_version": 1,
        "slug": args.slug,
        "source": args.source,
        "repo_root": str(repo),
        "base_ref": args.base_ref,
        "created_at": now,
        "updated_at": now,
        "initial_base_sha": current["base_sha"],
        "initial_head_sha": current["head_sha"],
        "revision": 0,
        "artifacts": {},
        "invalidations": [],
    }
    write_state(path, state)
    print(path)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    state = load_state(path)
    report = require_current_dependencies(state, repo, args.artifact)

    if args.artifact in PATH_REQUIRED and not args.path:
        raise WorkflowError(f"{args.artifact} requires --path")
    if args.artifact in HEAD_BOUND and not report["worktree_clean"]:
        raise WorkflowError(f"{args.artifact} requires a clean committed worktree")

    resolved_path = None
    digest = None
    if args.path:
        candidate = Path(args.path).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (repo / candidate).resolve()
        if not resolved.is_file():
            raise WorkflowError(f"artifact file not found: {resolved}")
        resolved_path = str(resolved)
        digest = sha256_file(resolved)

    state["revision"] += 1
    dependencies = {
        name: state["artifacts"][name]["revision"] for name in DEPENDENCIES[args.artifact]
    }
    if args.artifact == "candidate" and "deep-review" in state["artifacts"]:
        dependencies["deep-review"] = state["artifacts"]["deep-review"]["revision"]
    state["artifacts"][args.artifact] = {
        "revision": state["revision"],
        "recorded_at": utc_now(),
        "path": resolved_path,
        "sha256": digest,
        "base_sha": report["base_sha"] if args.artifact in HEAD_BOUND else None,
        "head_sha": report["head_sha"] if args.artifact in HEAD_BOUND else None,
        "dependencies": dependencies,
        "invalidated": False,
        "invalidation_reason": None,
    }
    write_state(path, state)
    print(json.dumps(state["artifacts"][args.artifact], indent=2, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    state = load_state(path)
    report = evaluate(state, repo)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"run: {report['run']}")
        print(f"source: {report['source']}")
        print(f"base: {report['base_ref']} @ {report['base_sha']}")
        print(f"head: {report['head_sha']}")
        print(f"worktree: {'clean' if report['worktree_clean'] else 'dirty'}")
        for name in ARTIFACT_ORDER:
            item = report["artifacts"][name]
            suffix = f" ({'; '.join(item['reasons'])})" if item["reasons"] else ""
            print(f"{name}: {item['status']}{suffix}")
        print(f"next: {report['next_artifact'] or 'none'}")
    return 0 if report["worktree_clean"] else 2


def cmd_invalidate(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    state = load_state(path)
    start = ARTIFACT_ORDER.index(args.from_artifact)
    affected = []
    for name in ARTIFACT_ORDER[start:]:
        record = state["artifacts"].get(name)
        if record is None:
            continue
        record["invalidated"] = True
        record["invalidation_reason"] = args.reason
        affected.append(name)
    state["invalidations"].append(
        {"from": args.from_artifact, "reason": args.reason, "at": utc_now(), "affected": affected}
    )
    write_state(path, state)
    print(json.dumps({"affected": affected, "reason": args.reason}, sort_keys=True))
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    print(state_path(repo, args.slug, args.state_dir))
    return 0


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository or worktree path")
    parser.add_argument("--slug", required=True, help="stable lowercase run identifier")
    parser.add_argument("--state-dir", help="override the default worktree-local state directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a run ledger")
    add_common(init)
    init.add_argument("--source", required=True, help="issue URL, issue number, or concise idea")
    init.add_argument("--base-ref", default="origin/main")
    init.add_argument("--resume", action="store_true", help="show existing run instead of failing")
    init.add_argument("--allow-dirty", action="store_true")
    init.set_defaults(handler=cmd_init)

    record = subparsers.add_parser("record", help="record a completed artifact")
    add_common(record)
    record.add_argument("--artifact", required=True, choices=ARTIFACT_ORDER)
    record.add_argument("--path", help="artifact file path, required for Markdown artifacts")
    record.set_defaults(handler=cmd_record)

    status = subparsers.add_parser("status", help="evaluate missing and stale artifacts")
    add_common(status)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    invalidate = subparsers.add_parser("invalidate", help="mark an artifact and downstream records stale")
    add_common(invalidate)
    invalidate.add_argument("--from", dest="from_artifact", required=True, choices=ARTIFACT_ORDER)
    invalidate.add_argument("--reason", required=True)
    invalidate.set_defaults(handler=cmd_invalidate)

    where = subparsers.add_parser("where", help="print the run state path")
    add_common(where)
    where.set_defaults(handler=cmd_where)

    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.handler(args)
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
