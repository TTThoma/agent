#!/usr/bin/env python3
"""Deterministic run ledger (v2) for the feature-workflow skill: tiered stages, HEAD- and patch-bound artifacts."""

from __future__ import annotations

import argparse
import builtins
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA_VERSION = 2
ARTIFACT_ORDER = ("brief", "build", "verification", "cold-read", "packet", "approval", "published")
TIERS = ("t0", "t1", "t2")
REQUIRED = {
    "t0": ("build", "verification", "packet", "published"),
    "t1": ("brief", "build", "verification", "packet", "approval", "published"),
    "t2": ARTIFACT_ORDER,
}
DEPENDENCIES = {
    "brief": (),
    "build": ("brief",),
    "verification": ("build",),
    "cold-read": ("build",),
    "packet": ("verification", "cold-read"),
    "approval": ("packet",),
    "published": ("approval", "packet", "verification"),
}
PATH_REQUIRED = {"brief", "verification", "cold-read", "packet", "approval"}
HEAD_BOUND = {"build", "verification"}
PATCH_BOUND = {"cold-read", "packet", "approval", "published"}
FLOOR_GATED = ("packet", "approval", "published")
FLOOR_GATE = "tier below path floor"
SPLIT_GATE = "split required"
RULES_GATE = "rules changed since run start"
NO_RULES_GATE = "no rules file found"
NO_PIN = {"path": None, "sha256": None}
REBASED_NOTE = "rebased; patch identical"
DEFAULT_RULES = Path(".feature-workflow") / "tiers.json"
# Branch-controlled .gitattributes (-diff, binary) and .gitmodules (ignore=all) must not hide content.
DIFF_FLAGS = ("--text", "--no-ext-diff", "--no-textconv", "--ignore-submodules=none", "-M")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
# Project landing recipes (<repo>/.feature-workflow/project.json); a missing file or key takes these defaults.
PROJECT_DEFAULTS: dict[str, Any] = {
    "approval_status": None,
    "mark_ready": "gh pr ready {pr}",
    "pr_head": "gh pr view {pr} --json headRefOid -q .headRefOid",
    "retrigger": None,
    "required_checks": [],
    "merge_mode": None,
    "checks": "gh pr checks {pr} --json name,bucket",
}
TEMPLATE_KEYS = ("approval_status", "mark_ready", "pr_head", "retrigger", "checks")
MERGE_MODES = ("bot", "manual")
PLACEHOLDERS = ("pr", "sha", "patch_id", "approver", "date", "head_ref")
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_]+)\}")
# Substituted values must stay inside these sets, so none can become an option, a path trick or shell syntax.
VALUE_RES = {"pr": "[0-9]+", "sha": "[0-9a-f]{40,64}", "patch_id": "[0-9a-f]{40,64}", "date": "[0-9T:Z-]+",
             "approver": r"[A-Za-z0-9_(][A-Za-z0-9_ .:()'-]*", "head_ref": "[A-Za-z0-9._/][A-Za-z0-9._/-]*"}
GRANT_ROW_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
GRANT_MAX_SECONDS = 12 * 3600  # the longest delegation window (references/delegation.md)
SHELLS = ("sh", "bash", "zsh", "dash", "ksh")  # a convenience denylist; VALUE_RES is the guard
IN_TREE_PROJECT = ".feature-workflow/project.json"
CARRIED = ("cold-read", "packet", "approval")  # patch-bound records a carry moves to the new patch
HUNK_HEADER_RE = re.compile(rb"^@@ [^\n]*", re.M)
# Moved-line detection: pin every colour git uses, so each +/- line starts with one known code.
MOVE_COLOURS = {"old": "red", "new": "green", "oldMoved": "magenta", "oldMovedAlternative": "blue",
                "newMoved": "cyan", "newMovedAlternative": "yellow", "meta": "normal", "frag": "normal",
                "func": "normal", "context": "normal", "commit": "normal", "whitespace": "normal"}
MOVE_CONFIG = [arg for key, colour in MOVE_COLOURS.items() for arg in ("-c", f"color.diff.{key}={colour}")] \
    + ["-c", "diff.suppressBlankEmpty=false"]
MOVED_CODES = {b"35", b"34", b"36", b"33"}
# No whitespace allowance (and any diff.colorMovedWS config overridden): a re-indented line is a changed line.
MOVE_FLAGS = ("--color=always", "--color-moved=zebra", "--color-moved-ws=no", "--ws-error-highlight=none")
MIN_MOVED_BLOCK = 5
HUNK_RE = re.compile(rb"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@.*", re.S)
RECORDED_BY_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
DIFF_LINE_RE = re.compile(rb"(?:\x1b\[([0-9;]+)m)?([ +\-])(.*?)(?:\x1b\[m)?", re.S)
EXCLUSIONS = ("moved",)


class WorkflowError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_bytes(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, input=data, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip() or f"git {' '.join(args)} failed"
        raise WorkflowError(detail)
    return proc.stdout


def run_git(repo: Path, *args: str) -> str:
    return git_bytes(repo, *args).decode("utf-8", errors="surrogateescape").strip()


def repo_root(value: str) -> Path:
    return Path(run_git(Path(value).expanduser().resolve(), "rev-parse", "--show-toplevel")).resolve()


def validate_slug(slug: str) -> None:
    if not SLUG_RE.fullmatch(slug):
        raise WorkflowError("slug must use lowercase letters, digits, dots, underscores, or hyphens")


def state_path(repo: Path, slug: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve() / "state.json"
    path = Path(run_git(repo, "rev-parse", "--git-path", f"feature-workflow/{slug}"))
    return (path if path.is_absolute() else repo / path).resolve() / "state.json"


def resolve_in_repo(repo: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    return (candidate if candidate.is_absolute() else repo / candidate).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_PATCH_ID_MODE: list[str] = []


def patch_id_mode(repo: Path) -> str:
    """--verbatim (git >= 2.40) keeps whitespace, so a re-indent changes the id; older git falls back to --stable."""
    if not _PATCH_ID_MODE:
        sample = b"diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1 +1 @@\n-a\n+b\n"
        probe = subprocess.run(["git", "patch-id", "--verbatim"], cwd=repo, input=sample, capture_output=True,
                               check=False)
        verbatim = probe.returncode == 0 and re.match(rb"[0-9a-f]{40}", probe.stdout) is not None
        _PATCH_ID_MODE.append("--verbatim" if verbatim else "--stable")
    return _PATCH_ID_MODE[0]


def patch_id(repo: Path, base_sha: str, head_sha: str) -> str:
    diff = git_bytes(repo, "-c", "core.quotePath=false", "diff", *DIFF_FLAGS, "--no-color", base_sha, head_sha)
    if not diff.strip():
        return "empty"
    fields = git_bytes(repo, "patch-id", patch_id_mode(repo), data=diff).decode().split()
    return fields[0] if fields else "empty"


def is_ancestor(repo: Path, older: str, newer: str) -> bool:
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=repo, capture_output=True,
                          check=False)
    return proc.returncode == 0


def snapshot(repo: Path, base_ref: str, build_base: str | None = None) -> dict[str, Any]:
    """With `build_base`, a branch already merged into `base_ref` (merge-base == HEAD) is judged against the
    base recorded at build, so its artifacts stay bound to the reviewed patch."""
    run_git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    head_sha = run_git(repo, "rev-parse", "HEAD")
    base_sha = run_git(repo, "merge-base", base_ref, "HEAD")
    merged = bool(build_base) and base_sha == head_sha and build_base != head_sha \
        and is_ancestor(repo, build_base or "", head_sha)
    if merged:
        base_sha = build_base or base_sha
    dirty = run_git(repo, "status", "--porcelain", "--untracked-files=normal")
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "patch_id": patch_id(repo, base_sha, head_sha),
        "merged": merged,
        "squashed": False,
        "worktree_clean": not bool(dirty),
        "dirty_entries": dirty.splitlines(),
    }


def build_snapshot(repo: Path, build: dict[str, Any]) -> dict[str, Any]:
    """A squash-merged branch never reaches the base, so it is judged at the base and head recorded at build."""
    dirty = run_git(repo, "status", "--porcelain", "--untracked-files=normal")
    return {
        "base_sha": build["base_sha"],
        "head_sha": build["head_sha"],
        "patch_id": patch_id(repo, build["base_sha"], build["head_sha"]),
        "merged": False,
        "squashed": True,
        "worktree_clean": not bool(dirty),
        "dirty_entries": dirty.splitlines(),
    }


def run_snapshot(repo: Path, state: dict[str, Any]) -> dict[str, Any]:
    build = state["artifacts"].get("build") or {}
    published = state["artifacts"].get("published") or {}
    if published.get("landing") == "squash" and build.get("head_sha"):
        return build_snapshot(repo, build)
    return snapshot(repo, state["base_ref"], build.get("base_sha"))


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob: `**/` = zero or more dirs, `**` = anything, `*`/`?` stop at `/`."""
    tokens = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    table = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(table.get(token, re.escape(token)) for token in tokens), re.DOTALL)


def in_commit(repo: Path, sha: str, rel: str) -> bool:
    spec = f"{sha}:{rel}"
    return subprocess.run(["git", "cat-file", "-e", spec], cwd=repo, capture_output=True, check=False).returncode == 0


def blob_lines(repo: Path, sha: str, rel: str | None) -> int:
    if not rel or not in_commit(repo, sha, rel):
        return 0
    try:
        data = git_bytes(repo, "cat-file", "blob", f"{sha}:{rel}")
    except WorkflowError:  # gitlink or tree: count it rather than skip it
        return 1
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def origin_name(repo: Path) -> str | None:
    proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True, check=False)
    url = proc.stdout.decode(errors="replace").strip().rstrip("/") if proc.returncode == 0 else ""
    url = url[:-5] if url.lower().endswith("/.git") else url
    name = re.split(r"[/:\\]", url)[-1]
    name = name[:-4] if name.lower().endswith(".git") else name
    return name if name not in ("", ".", "..") else None


def find_rules(repo: Path, explicit: str | None) -> Path | None:
    """The run's --rules if given; else the first `.feature-workflow/<origin-name>.tiers.json` in an ancestor
    of the worktree (outside the tree, so every worktree of a clone shares it); else the in-tree fallback."""
    if explicit:
        path = Path(explicit)
        return path.resolve() if path.is_file() else None
    name = origin_name(repo)
    found = ancestor_config(repo, f"{name}.tiers.json") if name else None
    fallback = repo / DEFAULT_RULES
    return found or (fallback.resolve() if fallback.is_file() else None)


def ancestor_config(repo: Path, filename: str) -> Path | None:
    """The first `.feature-workflow/<filename>` in an ancestor of the worktree, outside the main checkout."""
    common = Path(run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    main = common.parent.resolve() if common.name == ".git" else None
    for directory in repo.parents:
        if main and (directory == main or main in directory.parents):
            continue  # the main checkout's tree is branch-controlled too
        candidate = directory / ".feature-workflow" / filename
        if candidate.is_file():
            return candidate.resolve()
    return None


def find_project(repo: Path, explicit: str | None) -> Path | None:
    """--project if given; else an ancestor `.feature-workflow/<origin-name>.project.json` (like the rules)."""
    if explicit:
        path = resolve_in_repo(repo, explicit)
        if not path.is_file():
            raise WorkflowError(f"project config not found: {path}")
        return path
    name = origin_name(repo)
    return ancestor_config(repo, f"{name}.project.json") if name else None


def project_config(repo: Path, explicit: str | None, base_sha: str) -> dict[str, Any]:
    """The found config, else the in-tree one as of the base commit: the worktree copy is the branch's
    (it may even be untracked behind a .gitignore)."""
    found = find_project(repo, explicit)
    if found:
        return load_project(found)
    entry = run_git(repo, "ls-tree", base_sha, "--", IN_TREE_PROJECT)
    if not entry:
        return load_project(None)
    if not entry.startswith("100"):
        raise WorkflowError(f"{IN_TREE_PROJECT} at base {base_sha} is not a regular file; refusing it")
    text = git_bytes(repo, "show", f"{base_sha}:{IN_TREE_PROJECT}").decode("utf-8", errors="replace")
    return load_project(f"{base_sha}:{IN_TREE_PROJECT}", text)


def load_project(path: Path | str | None, text: str | None = None) -> dict[str, Any]:
    """Validate the project's landing recipes; JSON null switches a template off."""
    config = {**PROJECT_DEFAULTS, "required_checks": [], "path": str(path) if path else None}
    if path is None:
        return config
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8") if text is None else text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid project config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"invalid project config {path}: expected a JSON object")
    unknown = sorted(key for key in data if key not in PROJECT_DEFAULTS and not key.startswith("_"))
    if unknown:
        raise WorkflowError(f"invalid project config {path}: unknown keys {', '.join(unknown)}")
    for key in TEMPLATE_KEYS:
        value = data.get(key, config[key])
        if value is not None:
            bad = sorted(set(PLACEHOLDER_RE.findall(value)) - set(PLACEHOLDERS)) if isinstance(value, str) else []
            try:
                argv = shlex.split(value) if isinstance(value, str) else []
                if not argv or bad:
                    raise ValueError(f"unknown placeholders {bad}" if bad else "expected a non-empty string")
                if Path(argv[0]).name in SHELLS and any(re.fullmatch(r"-[a-z]*c[a-z]*", arg) for arg in argv[1:]):
                    raise ValueError("a shell with -c; give the command itself")
            except ValueError as exc:
                raise WorkflowError(f"invalid project config {path}: {key}: {exc}") from exc
        config[key] = value
    checks, mode = data.get("required_checks", []), data.get("merge_mode")
    if not isinstance(checks, list) or not all(isinstance(check, str) for check in checks):
        raise WorkflowError(f"invalid project config {path}: required_checks must be a list of names")
    if mode is not None and mode not in MERGE_MODES:
        raise WorkflowError(f"invalid project config {path}: merge_mode must be one of {', '.join(MERGE_MODES)}")
    config.update({"required_checks": checks, "merge_mode": mode})
    return config


def render(template: str, values: dict[str, str]) -> list[str]:
    """Split first, then fill placeholders per argument, so a value can never add or split arguments."""
    def fill(match: re.Match[str]) -> str:
        if match.group(1) not in values:
            raise WorkflowError(f"placeholder {{{match.group(1)}}} has no value here")
        return values[match.group(1)]
    return [PLACEHOLDER_RE.sub(fill, token) for token in shlex.split(template)]


def run_command(repo: Path, argv: list[str]) -> dict[str, Any]:
    """Run one argv list, never through a shell."""
    try:
        proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise WorkflowError(f"cannot run {shlex.join(argv)}: {exc}") from exc
    if proc.returncode != 0:
        raise WorkflowError(f"{shlex.join(argv)} exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
    return {"argv": argv, "returncode": 0, "stdout": proc.stdout.strip()[-500:], "at": utc_now()}


def load_rules(path: Path | None) -> tuple[dict[str, Any] | None, dict[str, str | None]]:
    """Parse the rules and pin {path, sha256} from the same bytes."""
    if path is None:
        return None, dict(NO_PIN)
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"invalid rules file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"invalid rules file {path}: expected a JSON object")
    default_tier = data.get("default_tier", "t2")
    budget = data.get("must_read_budget")
    if default_tier not in TIERS or not (budget is None or isinstance(budget, int)):
        raise WorkflowError(f"invalid rules file {path}: bad default_tier or must_read_budget")
    rules = []
    for rule in data.get("rules", []):
        if not isinstance(rule.get("glob"), str) or rule.get("tier") not in TIERS:
            raise WorkflowError(f"invalid rule in {path}: {rule}")
        rules.append((glob_regex(rule["glob"]), rule["tier"], bool(rule.get("skip_read", False))))
    pin = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"path": str(path), "default_tier": default_tier, "budget": budget, "rules": rules}, pin


def path_tier(rules: dict[str, Any] | None, path: str) -> tuple[str, bool]:
    if not rules:  # fail closed: without rules every file is t2 must-read
        return "t2", False
    for regex, rule_tier, rule_skip in rules["rules"]:
        if regex.fullmatch(path):
            return rule_tier, rule_skip
    return rules["default_tier"], False


def numstat(repo: Path, base_sha: str, head_sha: str, specs: list[str] | None = None) -> list[tuple[str, ...]]:
    """(added, deleted, path, old_path) per file pair, in git's order; added is "-" for a binary file."""
    raw = git_bytes(repo, "diff", *DIFF_FLAGS, "--numstat", "-z", base_sha, head_sha, "--", *(specs or []))
    tokens = raw.decode("utf-8", errors="surrogateescape").split("\0")
    entries, index = [], 0
    while index < len(tokens):
        entry, index = tokens[index], index + 1
        if not entry:
            continue
        added, deleted, path = entry.split("\t", 2)
        old_path = ""
        if not path:  # rename: "added\tdeleted\t\0old\0new"
            old_path, path, index = tokens[index], tokens[index + 1], index + 2
        entries.append((added, deleted, path, old_path))
    return entries


def moved_sections(repo: Path, base_sha: str, head_sha: str, specs: list[str]) -> list[list[tuple]]:
    """Per file pair, its hunk lines as (sign, colour code, content). Git colours a line as moved when an
    identical block (>= 20 alphanumerics) is removed in one place and added in another within these files."""
    out = git_bytes(repo, "-c", "core.quotePath=false", *MOVE_CONFIG, "diff", *DIFF_FLAGS, *MOVE_FLAGS,
                    base_sha, head_sha, "--", *specs)
    sections: list[list[tuple]] = []
    old_left = new_left = 0
    for raw in out.split(b"\n"):
        if old_left > 0 or new_left > 0:
            match = DIFF_LINE_RE.fullmatch(raw)
            if not match:
                if raw.lstrip(b"\x1b[m").startswith(b"\\"):  # "\ No newline at end of file"
                    continue
                raise WorkflowError(f"unparsed diff line {raw[:60]!r}")
            code, sign, content = match.groups()
            old_left -= sign != b"+"
            new_left -= sign != b"-"
            sections[-1].append((sign, code, content))
        elif raw.startswith(b"diff --git "):
            sections.append([])
        elif raw.startswith(b"@@") and sections:
            hunk = HUNK_RE.fullmatch(raw)
            if not hunk:
                raise WorkflowError(f"unparsed hunk header {raw[:60]!r}")
            old_left, new_left = (int(value) if value is not None else 1 for value in hunk.groups())
            sections[-1].append((b" ", None, b""))  # a hunk boundary ends any run
    return sections


def moved_runs(lines: list[tuple]) -> list[tuple[bytes, int, bytes]]:
    """Runs of consecutive moved lines with one sign and one zebra colour: (sign, length, wrapped text)."""
    runs: list[tuple[bytes, bytes | None, list[bytes]]] = []
    previous_moved = False
    for sign, code, content in lines:
        moved = sign != b" " and code in MOVED_CODES
        if moved and runs and runs[-1][:2] == (sign, code) and previous_moved:
            runs[-1][2].append(content)
        elif moved:
            runs.append((sign, code, [content]))
        previous_moved = moved
    return [(sign, len(body), b"\n" + b"\n".join(body) + b"\n") for sign, _, body in runs]


def moved_out(index: int, runs: list[list[tuple[bytes, int, bytes]]]) -> tuple[int, int]:
    """(added, deleted) lines of file `index` excluded as moved: only runs of >= MIN_MOVED_BLOCK lines whose
    opposite side is in a different file, and never one that also matches within its own file (a reorder).
    Each excluded run keeps one counted anchor line, so the reader sees where code left and where it landed."""
    excluded = {b"+": 0, b"-": 0}
    for sign, length, text in runs[index]:
        if length < MIN_MOVED_BLOCK:
            continue
        def found(file_runs: list[tuple[bytes, int, bytes]]) -> bool:
            return any(other != sign and text in body for other, _, body in file_runs)
        if not found(runs[index]) and any(found(file_runs) for at, file_runs in enumerate(runs) if at != index):
            excluded[sign] += length - 1
    return excluded[b"+"], excluded[b"-"]


def exclude(repo: Path, base_sha: str, head_sha: str, files: list[dict[str, Any]]) -> str | None:
    """Lower each diff-counted file's must-read by blocks moved between must-read files; any parse doubt leaves
    the raw count. Returns a note when exclusion was skipped."""
    plain = [item for item in files if item["must_read"] and not item["whole_file"]]
    if not plain:
        return None
    specs = [f":(literal){name}" for item in plain for name in (item["old_path"], item["path"]) if name]
    try:
        entries = numstat(repo, base_sha, head_sha, specs)
        sections = moved_sections(repo, base_sha, head_sha, specs)
    except WorkflowError as exc:
        return f"no exclusions: {exc}"
    if len(entries) != len(sections):
        return "no exclusions: diff sections do not line up with numstat"
    by_path = {item["path"]: item for item in plain}
    runs = [moved_runs(lines) for lines in sections]
    for index, ((added, deleted, path, old_path), lines) in enumerate(zip(entries, sections)):
        item = by_path.get(path)
        signs = [line[0] for line in lines]
        if item is None or (old_path or None) != item["old_path"] or added == "-" \
                or (int(added), int(deleted)) != (signs.count(b"+"), signs.count(b"-")):
            continue  # unmatched or a different pairing: keep the raw count
        moved_added, moved_deleted = moved_out(index, runs)
        item.update({"must_read": item["must_read"] - moved_added - moved_deleted,
                     "read_added": item["added"] - moved_added, "read_deleted": item["deleted"] - moved_deleted,
                     "excluded": {"moved": moved_added + moved_deleted}})
    return None


def classify(repo: Path, base_sha: str, head_sha: str, rules: dict[str, Any] | None) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    floor: str | None = None
    for added, deleted, path, old_path in numstat(repo, base_sha, head_sha):
        binary = added == "-"
        item = {"path": path, "old_path": old_path or None,
                "added": 0 if binary else int(added), "deleted": 0 if binary else int(deleted)}
        # A rename is judged by both paths: the higher tier, and skipped only if both paths skip.
        tier, skip = path_tier(rules, path)
        old_counts = False
        if old_path:
            old_tier, old_skip = path_tier(rules, old_path)
            old_counts = old_tier == "t2" and not old_skip
            if TIERS.index(old_tier) > TIERS.index(tier):
                tier = old_tier
            skip = skip and old_skip
        if floor is None or TIERS.index(tier) > TIERS.index(floor):
            floor = tier
        counts = tier == "t2" and not skip
        read_added, read_deleted = (item["added"], item["deleted"]) if counts else (0, 0)
        whole = counts and (binary or (bool(old_path) and not old_counts))
        if counts and binary:  # unreadable as a diff: the whole old and new content is must-read
            read_added = blob_lines(repo, head_sha, path)
            read_deleted = blob_lines(repo, base_sha, old_path or path)
        elif whole:  # renamed into must-read from a lower tier or a skip-read path: read all of it, even unchanged
            read_added = blob_lines(repo, head_sha, path)
        files.append({**item, "binary": binary, "tier": tier, "skip_read": skip, "whole_file": whole,
                      "must_read": read_added + read_deleted, "read_added": read_added, "read_deleted": read_deleted,
                      "excluded": dict.fromkeys(EXCLUSIONS, 0)})
    note = exclude(repo, base_sha, head_sha, files)
    excluded = {key: sum(item["excluded"][key] for item in files) for key in EXCLUSIONS}
    added_total = sum(item.pop("read_added") for item in files)
    deleted_total = sum(item.pop("read_deleted") for item in files)
    return {
        "files": files,
        "path_floor": floor,
        "must_read_lines": added_total + deleted_total,
        "must_read_added": added_total,
        "must_read_deleted": deleted_total,
        "must_read_excluded": excluded,
        "must_read_note": note,
        "must_read_budget": rules["budget"] if rules else None,
        "rules_path": rules["path"] if rules else None,
    }


def rules_gates(pinned: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    if pinned == current:
        return []
    if pinned is None:
        detail = "run predates rules pinning; pin it with set-rules --reason"
        return [{"gate": RULES_GATE, "detail": detail, "blocks": list(FLOOR_GATED)}]
    detail = (f"pinned {pinned['path'] or 'no rules'} (sha256 {pinned['sha256'] or '-'}); now "
              f"{current['path'] or 'no rules'} (sha256 {current['sha256'] or '-'}); re-pin with set-rules --reason")
    return [{"gate": RULES_GATE, "detail": detail, "blocks": list(FLOOR_GATED)}]


def ruled(repo: Path, state: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Classify base..head under the run's rules; a rules file that moved or changed since the pin blocks."""
    rules, now = load_rules(find_rules(repo, state.get("rules_path")))
    classified = classify(repo, current["base_sha"], current["head_sha"], rules)
    pinned = state.get("rules_pin")
    classified.update({"rules_pin": pinned, "rules_sha256": now["sha256"]})
    missing = [] if rules else [{"gate": NO_RULES_GATE, "blocks": [], "detail": "no --rules, ancestor "
                                 "<origin-name>.tiers.json or in-tree tiers.json; every changed file is t2 must-read"}]
    return classified, rules_gates(pinned, now) + missing + tier_gates(state["tier"], classified)


def tier_gates(tier: str, classified: dict[str, Any]) -> list[dict[str, Any]]:
    gates = []
    floor, lines, budget = classified["path_floor"], classified["must_read_lines"], classified["must_read_budget"]
    if floor and TIERS.index(tier) < TIERS.index(floor):
        detail = f"run tier {tier} < path floor {floor}; raise it with set-tier or reclassify files in the rules file"
        gates.append({"gate": FLOOR_GATE, "detail": detail, "blocks": list(FLOOR_GATED)})
    if tier == "t2" and budget is not None and lines > budget:
        detail = f"{lines} must-read lines exceed budget {budget}; split the PR or reclassify files in the rules file"
        gates.append({"gate": SPLIT_GATE, "detail": detail, "blocks": ["packet"]})
    return gates


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"run not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid state file {path}: {exc}") from exc
    if data.get("schema_version") == 1:
        raise WorkflowError("v1 run ledger; finish it with the v1 skill or start a new v2 run")
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("artifacts"), dict) \
            or data.get("tier") not in TIERS:
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


@contextmanager
def ledger_lock(path: Path) -> Iterator[None]:
    """Exclusive lock beside state.json; closing the file releases it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.parent / "state.lock", "a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def locked(handler: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        validate_slug(args.slug)
        with ledger_lock(state_path(repo_root(args.repo), args.slug, args.state_dir)):
            return handler(args)
    return run


def refuse_closed(state: dict[str, Any]) -> None:
    if (state["artifacts"].get("published") or {}).get("landing") == "squash":
        raise WorkflowError("run is closed: it was published as a squash merge; start a new run")


def live_carry(state: dict[str, Any], patch: str | None = None) -> dict[str, Any] | None:
    """The carry of the current approval, if it moved that approval to `patch` (to any patch when None)."""
    carry, approval = state["artifacts"].get("carry"), state["artifacts"].get("approval")
    if not carry or not approval or carry.get("invalidated") or carry["approval_revision"] != approval["revision"]:
        return None
    return carry if patch is None or carry["patch_id"] == patch else None


def effective_patch(name: str, record: dict[str, Any], carry: dict[str, Any] | None) -> str | None:
    if carry and name in CARRIED and record.get("patch_id") == carry["from_patch_id"]:
        return carry["patch_id"]
    return record.get("patch_id")


def evaluate(state: dict[str, Any], repo: Path, current: dict[str, Any] | None = None) -> dict[str, Any]:
    current = current or run_snapshot(repo, state)
    classified, gates = ruled(repo, state, current)
    carry = live_carry(state, current["patch_id"])
    tier = state["tier"]
    required = REQUIRED[tier]
    statuses: dict[str, dict[str, Any]] = {}
    hard: dict[str, bool] = {}  # stale for a reason other than HEAD/base movement

    for name in ARTIFACT_ORDER:
        record = state["artifacts"].get(name)
        if record is None:
            statuses[name] = {"status": "absent", "reasons": [], "notes": [], "required": name in required}
            hard[name] = False
            continue
        reasons: set[str] = set()
        moved: set[str] = set()
        notes: set[str] = set()
        missing = False

        if record.get("invalidated"):
            reasons.add(record.get("invalidation_reason") or "explicitly invalidated")
        if record.get("path"):
            file_path = Path(record["path"])
            if not file_path.is_file():
                missing = True
                reasons.add("artifact file is missing")
            elif sha256_file(file_path) != record.get("sha256"):
                reasons.add("artifact content changed after it was recorded")
        if name != "brief" and not current["worktree_clean"]:
            reasons.add("worktree has uncommitted changes")

        shifted = [label for key, label in (("base_sha", "base SHA changed"), ("head_sha", "HEAD changed"))
                   if record.get(key) != current[key]]
        if name in HEAD_BOUND:
            moved.update(shifted)
        elif name in PATCH_BOUND:
            patch = effective_patch(name, record, carry)
            if patch != current["patch_id"]:
                reasons.add("patch changed")
            elif carry and patch != record.get("patch_id"):
                notes.add(f"approval carried: only {', '.join(carry['changed_files']) or 'no files'} changed")
            elif shifted:
                notes.add(REBASED_NOTE)
        override = record.get("budget_override")
        for gate in gates:
            if gate["gate"] == SPLIT_GATE and override \
                    and override["must_read_lines"] == classified["must_read_lines"] \
                    and override["marked_lines"] <= classified["must_read_budget"]:
                notes.add(f"budget override: {override['marked_lines']} marked of {override['must_read_lines']} "
                          f"must-read lines ({override['reason']})")
                continue
            if name in gate["blocks"]:
                reasons.add(f"{FLOOR_GATE} ({tier} < {classified['path_floor']})"
                            if gate["gate"] == FLOOR_GATE else gate["gate"])

        recorded = record.get("dependencies", {})
        for dep in DEPENDENCIES[name]:
            dep_record = state["artifacts"].get(dep)
            if dep_record is None:
                if dep in required or dep in recorded:
                    reasons.add(f"dependency {dep} is missing")
                continue
            dep_status = statuses[dep]["status"]
            if name in PATCH_BOUND and dep in HEAD_BOUND:
                # Patch-level dependency: a re-run on a new HEAD with the same patch still satisfies it.
                if hard[dep]:
                    reasons.add(f"dependency {dep} is {dep_status}")
                elif dep_record.get("patch_id") != effective_patch(name, record, carry):
                    reasons.add(f"dependency {dep} covers a different patch")
            elif dep not in recorded:
                reasons.add(f"dependency {dep} was recorded after {name}")
            elif dep_record.get("revision") != recorded[dep]:
                reasons.add(f"dependency {dep} was replaced")
            elif dep_status != "current":
                (reasons if hard[dep] else moved).add(f"dependency {dep} is {dep_status}")

        hard[name] = bool(reasons)
        status = "missing" if missing else ("stale" if reasons or moved else "current")
        statuses[name] = {"status": status, "reasons": sorted(reasons | moved), "notes": sorted(notes),
                          "required": name in required, "recorded_at": record.get("recorded_at"),
                          "recorded_by": record.get("recorded_by") or record.get("approver"),
                          "packet_check_skipped": (record.get("packet_check") or {}).get("skipped"),
                          "pr_checked": bool((record.get("packet_check") or {}).get("pr"))}

    next_artifact = next((name for name in ARTIFACT_ORDER
                          if name in required and statuses[name]["status"] != "current"), None)
    return {
        "run": state["slug"],
        "source": state["source"],
        "purpose": state.get("purpose"),
        "carries": state.get("carries", []),
        "base_ref": state["base_ref"],
        "tier": tier,
        **current,
        "path_floor": classified["path_floor"],
        "must_read_lines": classified["must_read_lines"],
        "must_read_added": classified["must_read_added"],
        "must_read_deleted": classified["must_read_deleted"],
        "must_read_excluded": classified["must_read_excluded"],
        "must_read_note": classified["must_read_note"],
        "must_read_budget": classified["must_read_budget"],
        "rules_path": classified["rules_path"],
        "rules_sha256": classified["rules_sha256"],
        "rules_pin": classified["rules_pin"],
        "gates": gates,
        "budget_overrides": state.get("budget_overrides", []),
        "complete": statuses["published"]["status"] == "current",
        "next_artifact": next_artifact,
        "artifacts": statuses,
    }


def repin(state: dict[str, Any], new: dict[str, str | None], reason: str) -> None:
    old = state.get("rules_pin") or dict(NO_PIN)
    state["rules_pin"] = new
    state.setdefault("rules_changes", []).append(
        {"from_sha": old["sha256"], "to_sha": new["sha256"], "path": new["path"], "reason": reason, "at": utc_now()})
    invalidate_from(state, "packet", f"rules re-pinned: {reason}")


def apply_rules_arg(repo: Path, path: Path, state: dict[str, Any], args: argparse.Namespace) -> None:
    """The run's --rules is sticky: switching it needs a recorded reason and re-earns packet onward."""
    reason = getattr(args, "rules_override_reason", None)
    if not getattr(args, "rules", None):
        if reason:
            raise WorkflowError("--rules-override-reason requires --rules")
        return
    wanted, stored = str(resolve_in_repo(repo, args.rules)), state.get("rules_path")
    if wanted == stored or (stored is None and str(find_rules(repo, None)) == wanted):
        return
    if not reason:
        raise WorkflowError(f"run uses rules {stored or 'found by lookup'}; "
                            f"switching to {wanted} requires --rules-override-reason")
    found = find_rules(repo, wanted)
    if found is None:
        raise WorkflowError(f"rules file not found: {wanted}")
    _, pin = load_rules(found)
    state["rules_path"] = wanted
    repin(state, pin, reason)
    write_state(path, state)


def open_run(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any]]:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    state = load_state(path)
    apply_rules_arg(repo, path, state, args)
    return repo, path, state


def emit(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def invalidate_from(state: dict[str, Any], start: str, reason: str) -> list[str]:
    affected = []
    for name in ARTIFACT_ORDER[ARTIFACT_ORDER.index(start):]:
        record = state["artifacts"].get(name)
        if record is not None:
            record["invalidated"] = True
            record["invalidation_reason"] = reason
            affected.append(name)
    state["invalidations"].append({"from": start, "reason": reason, "at": utc_now(), "affected": affected})
    return affected


def cmd_init(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    repo = repo_root(args.repo)
    path = state_path(repo, args.slug, args.state_dir)
    if path.exists():
        if not args.resume:
            raise WorkflowError(f"run already exists: {path}; use --resume or choose another slug")
        state = load_state(path)
        apply_rules_arg(repo, path, state, args)
        if args.purpose and args.purpose != state.get("purpose"):
            state["purpose"] = args.purpose
            write_state(path, state)
            print(f"purpose updated: {args.purpose}", file=sys.stderr)
        emit(evaluate(state, repo))
        return 0

    current = snapshot(repo, args.base_ref)
    if not current["worktree_clean"] and not args.allow_dirty:
        raise WorkflowError("worktree is dirty; isolate the work or pass --allow-dirty after inspecting it")
    if args.rules_override_reason:
        raise WorkflowError("--rules-override-reason applies only to an existing run")
    rules_path = str(resolve_in_repo(repo, args.rules)) if args.rules else None
    found = find_rules(repo, rules_path)
    if rules_path and found is None:
        raise WorkflowError(f"rules file not found: {rules_path}")
    _, pin = load_rules(found)
    now = utc_now()
    state = {
        "schema_version": SCHEMA_VERSION, "slug": args.slug, "source": args.source, "repo_root": str(repo),
        "base_ref": args.base_ref, "tier": args.tier, "rules_path": rules_path, "rules_pin": pin,
        "purpose": args.purpose,
        "created_at": now, "updated_at": now, "revision": 0,
        "initial_base_sha": current["base_sha"], "initial_head_sha": current["head_sha"],
        "artifacts": {}, "invalidations": [], "tier_changes": [], "rules_changes": [],
    }
    write_state(path, state)
    print(path)
    return 0


def first_parent_line(repo: Path, base_ref: str) -> set[str]:
    return set(run_git(repo, "rev-list", "--first-parent", base_ref).split())


def resolve_commit(repo: Path, value: str) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{value.strip()}^{{commit}}"], cwd=repo,
                          capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def squash_candidate(repo: Path, state: dict[str, Any], remote: str) -> tuple[str | None, str]:
    """A single-parent commit on the base's first-parent line that does not contain HEAD: a squash merge.
    Returns (sha, "") or (None, the check that failed)."""
    build = state["artifacts"].get("build") or {}
    sha = resolve_commit(repo, remote)
    if not sha:
        return None, "it is not a known commit"
    if not build.get("head_sha"):
        return None, "no build is recorded"
    if is_ancestor(repo, build["head_sha"], sha):
        return None, "it contains the build head, so it is a merge or push, not a squash"
    parents = len(run_git(repo, "rev-list", "--parents", "-n", "1", sha).split()) - 1
    if parents != 1:
        return None, f"it has {parents} parents; a squash has one"
    if not is_ancestor(repo, build["base_sha"], f"{sha}^1"):
        return None, f"its parent does not descend from the build base {build['base_sha']}"
    if sha not in first_parent_line(repo, state["base_ref"]):
        return None, f"it is not on {state['base_ref']}'s first-parent line"
    return sha, ""


def approved_patch(state: dict[str, Any], patch: str) -> str:
    """The approved patch id that `patch` should match: a carry's when it carried to `patch`."""
    record = live_carry(state, patch) or state["artifacts"].get("approval") or state["artifacts"]["packet"]
    return record["patch_id"]


def verify_merge(repo: Path, state: dict[str, Any], remote: str | None, report: dict[str, Any]) -> tuple[str, str]:
    """A merged branch publishes on the commit that landed it on the base's first-parent line: a merge commit
    whose first-parent diff is the approved patch, or HEAD itself after a fast-forward."""
    if not remote:
        raise WorkflowError("branch is merged into its base; published requires --remote-sha <merge commit>")
    merge_sha = run_git(repo, "rev-parse", "--verify", f"{remote.strip()}^{{commit}}")
    on_line = merge_sha in first_parent_line(repo, state["base_ref"])
    if not on_line or not is_ancestor(repo, report["head_sha"], merge_sha):
        raise WorkflowError(f"--remote-sha {merge_sha} is not a commit on {state['base_ref']}'s first-parent line "
                            "that contains HEAD")
    merged_patch = report["patch_id"] if merge_sha == report["head_sha"] else \
        patch_id(repo, f"{merge_sha}^1", merge_sha)
    approved = approved_patch(state, merged_patch)
    if merged_patch != approved:
        raise WorkflowError(f"merge {merge_sha} brings patch {merged_patch}, not the approved patch {approved}")
    return merge_sha, merged_patch


def budget_override(artifact: str, args: argparse.Namespace) -> dict[str, Any] | None:
    """The maintainer may let the budget apply to the lines a packet marks as must-read, per packet revision."""
    reason, marked = args.budget_override_reason, args.marked_lines
    if reason is None and marked is None:
        return None
    if artifact != "packet":
        raise WorkflowError("--budget-override-reason and --marked-lines apply only to the packet")
    if not (reason or "").strip() or marked is None or marked < 0:
        raise WorkflowError("a budget override needs both --budget-override-reason and --marked-lines N >= 0")
    return {"marked_lines": marked, "reason": reason}


def cmd_record(args: argparse.Namespace) -> int:
    artifact = args.artifact
    if artifact in PATH_REQUIRED and not args.path:
        raise WorkflowError(f"{artifact} requires --path")
    if artifact == "approval" and not args.approver:
        raise WorkflowError("approval requires --approver <name>")
    if artifact == "approval":
        check_approver(args.approver)
    if args.recorded_by is not None and not RECORDED_BY_RE.fullmatch(args.recorded_by):
        raise WorkflowError("--recorded-by must match [A-Za-z0-9._:-]{1,64}")
    if artifact != "packet" and (args.pr or args.project or args.skip_packet_check is not None):
        raise WorkflowError("--pr, --project and --skip-packet-check apply only to the packet")

    repo, path, state = open_run(args)
    if (state["artifacts"].get("published") or {}).get("landing") == "squash" and artifact != "published":
        raise WorkflowError("run is closed: it was published as a squash merge; start a new run")
    squash, not_squash = squash_candidate(repo, state, args.remote_sha) \
        if artifact == "published" and args.remote_sha else (None, "")
    override = budget_override(artifact, args)
    report = evaluate(state, repo, build_snapshot(repo, state["artifacts"]["build"]) if squash else None)
    statuses = report["artifacts"]
    required = REQUIRED[state["tier"]]
    blocked = [f"{dep} ({statuses[dep]['status']})" for dep in DEPENDENCIES[artifact]
               if (dep in required or statuses[dep]["status"] != "absent") and statuses[dep]["status"] != "current"]
    if blocked:
        raise WorkflowError(f"cannot record {artifact}; dependencies are not current: {', '.join(blocked)}")
    for gate in report["gates"]:
        if artifact in gate["blocks"]:
            if gate["gate"] == SPLIT_GATE and override:
                if override["marked_lines"] > report["must_read_budget"]:
                    raise WorkflowError(f"cannot record packet; --marked-lines {override['marked_lines']} exceeds "
                                        f"budget {report['must_read_budget']}")
                override.update({"must_read_lines": report["must_read_lines"], "patch_id": report["patch_id"]})
                continue
            raise WorkflowError(f"cannot record {artifact}; {gate['gate']}: {gate['detail']}"
                                + ("; or mark lines with --marked-lines and --budget-override-reason"
                                   if gate["gate"] == SPLIT_GATE else ""))
    if override and "must_read_lines" not in override:
        raise WorkflowError("no split-required gate to override; record the packet without the budget flags")
    if artifact != "brief" and not report["worktree_clean"]:
        raise WorkflowError(f"{artifact} requires a clean committed worktree")
    merge_patch, landing = None, "push"
    if squash:
        merge_patch, landing = (squash, patch_id(repo, f"{squash}^1", squash)), "squash"
        if merge_patch[1] != approved_patch(state, merge_patch[1]):
            raise WorkflowError(f"squash {squash} brings patch {merge_patch[1]}, not the approved patch "
                                f"{approved_patch(state, merge_patch[1])}")
        if run_git(repo, "rev-parse", "HEAD") not in first_parent_line(repo, state["base_ref"]):
            live = snapshot(repo, state["base_ref"], state["artifacts"]["build"]["base_sha"])["patch_id"]
            if live != approved_patch(state, live):  # commits after approval must not ride a rebase-merge
                raise WorkflowError(f"HEAD carries patch {live}, not the approved patch; re-run from build")
    elif artifact == "published" and report["merged"]:
        merge_patch, landing = verify_merge(repo, state, args.remote_sha, report), "merge"
    elif args.remote_sha and resolve_commit(repo, args.remote_sha) != report["head_sha"]:
        raise WorkflowError(f"--remote-sha {args.remote_sha} does not match HEAD {report['head_sha']}"
                            + (f" and is not a squash landing: {not_squash}" if not_squash else ""))

    resolved_path = source = None
    if args.path:
        resolved = resolve_in_repo(repo, args.path)
        if not resolved.is_file():
            raise WorkflowError(f"artifact file not found: {resolved}")
        if artifact == "brief":  # the brief is a shared project document: bind the run to its own copy
            source, resolved = str(resolved), path.parent / f"brief.{state['revision'] + 1}.md"
            fd, temporary = tempfile.mkstemp(prefix="brief.", suffix=".tmp", dir=path.parent)
            os.close(fd)
            shutil.copyfile(source, temporary)
            os.replace(temporary, resolved)
        resolved_path = str(resolved)

    extra: dict[str, Any] = {"source_path": source, "recorded_by": args.recorded_by} if artifact == "brief" \
        else {"recorded_by": args.recorded_by}
    if artifact == "packet":  # the packet-check gate; the hash is of the bytes that were checked
        data, text = read_packet(Path(resolved_path or ""))
        problems = packet_problems(text, state, report, override)
        found, note = pr_problems(repo, args.project, args.pr, report) if args.pr else ([], "")
        problems += found
        if problems and not (args.skip_packet_check or "").strip():
            raise WorkflowError("cannot record packet; packet-check refused (or pass --skip-packet-check REASON):"
                                "\n- " + "\n- ".join(problems))
        extra.update({"sha256": hashlib.sha256(data).hexdigest(), "packet_check": {
            "pr": args.pr, "note": note or None, "skipped": args.skip_packet_check if problems else None,
            "overridden": problems}})
    if source:
        warn_shared_brief(repo, path, source)
    if artifact == "approval":
        extra.update({"approver": args.approver, "evidence_url": args.evidence_url})
    if override:
        override.update({"packet_revision": state["revision"] + 1, "at": utc_now()})
        extra["budget_override"] = override
        state.setdefault("budget_overrides", []).append(override)
    if artifact == "published":
        extra.update({"url": args.url, "remote_sha": args.remote_sha, "merged": report["merged"], "landing": landing})
        if merge_patch:
            extra.update({"remote_sha": merge_patch[0], "merge_patch_id": merge_patch[1]})
    emit(store(state, path, artifact, report, resolved_path, extra))
    return 0


def warn_shared_brief(repo: Path, path: Path, source: str) -> None:
    """Each run snapshots its brief; several open runs pointed at one mutable file is still a smell."""
    common = Path(run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    found = {*common.glob("feature-workflow/*/state.json"), *common.glob("worktrees/*/feature-workflow/*/state.json"),
             *path.parent.parent.glob("*/state.json")} - {path}
    for other in sorted(found):
        try:
            artifacts = json.loads(other.read_text(encoding="utf-8")).get("artifacts", {})
        except (OSError, ValueError):
            continue
        if (artifacts.get("brief") or {}).get("source_path") == source and "published" not in artifacts:
            print(f"warning: open run {other.parent.name} also records its brief from {source}; give each run its "
                  "own brief file (each run keeps a snapshot, so later edits there do not reach this run)",
                  file=sys.stderr)


def store(state: dict[str, Any], path: Path, artifact: str, report: dict[str, Any], file_path: str | None,
          extra: dict[str, Any]) -> dict[str, Any]:
    carry = live_carry(state, report.get("patch_id")) if artifact == "approval" else None
    state["revision"] += 1
    if carry:  # re-approving the carried patch: cold-read and packet still reach it through the carry
        carry["approval_revision"] = state["revision"]
    entry: dict[str, Any] = {
        "revision": state["revision"],
        "recorded_at": utc_now(),
        "tier": state["tier"],
        "path": file_path,
        "sha256": sha256_file(Path(file_path)) if file_path else None,
        "dependencies": {dep: state["artifacts"][dep]["revision"]
                         for dep in DEPENDENCIES[artifact] if dep in state["artifacts"]},
        "invalidated": False,
        "invalidation_reason": None,
    }
    if artifact != "brief":
        entry.update({key: report[key] for key in ("base_sha", "head_sha", "patch_id")})
    entry.update(extra)
    state["artifacts"][artifact] = entry
    write_state(path, state)
    return entry


def require_current(report: dict[str, Any], state: dict[str, Any], artifact: str) -> None:
    """Every artifact before `artifact` that the tier requires (or that exists) must be current."""
    statuses, required = report["artifacts"], REQUIRED[state["tier"]]
    blocked = [f"{name} ({statuses[name]['status']}: {'; '.join(statuses[name]['reasons']) or 'not recorded'})"
               for name in ARTIFACT_ORDER[:ARTIFACT_ORDER.index(artifact)]
               if (name in required or statuses[name]["status"] != "absent") and statuses[name]["status"] != "current"]
    gates = [gate["gate"] for gate in report["gates"] if artifact in gate["blocks"]]
    if blocked or gates or not report["worktree_clean"]:
        raise WorkflowError(f"cannot {'approve' if artifact == 'approval' else 'carry'}: "
                            + "; ".join(blocked + gates + ([] if report["worktree_clean"] else ["worktree is dirty"])))


def check_approver(name: str, delegated: bool = False) -> None:
    """ASCII only (no homoglyphs); the `delegated` prefix is reserved for approve --grant."""
    if not re.fullmatch(VALUE_RES["approver"], name):
        raise WorkflowError(f"approver {name!r} must be ASCII letters, digits, space and . _ - ( ) ' :, "
                            "not starting with a symbol")
    lowered = name.lower()
    if not delegated and (lowered.startswith("delegated") or "delegated:" in lowered):
        raise WorkflowError("approver names starting with 'delegated' or holding 'delegated:' are reserved for "
                            "approve --grant")


def parse_utc(value: str, flag: str) -> datetime:
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2})?Z", value or "")
    if not match:
        raise WorkflowError(f"{flag} must be a UTC time like 2026-01-31T09:00Z, got {value!r}")
    return datetime.strptime(match.group(1) + (match.group(2) or ":00"), "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def delegated_approver() -> str:
    raw = os.environ.get("FEATURE_WORKFLOW_SESSION") or socket.gethostname()
    return "delegated:" + (re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:40].strip("-.") or "session")


def grant_request(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any] | None:
    """The delegation grant this approve claims, checked against its window and the project config."""
    if not args.grant:
        if args.grant_at or args.grant_until or args.grant_merges:
            raise WorkflowError("--grant-at, --grant-until and --grant-merges need --grant ROW")
        return None
    if args.approver:
        raise WorkflowError("--approver is refused with --grant: a delegated approval is recorded as "
                            "delegated:<session>")
    if args.allow_skipped_packet_check:
        raise WorkflowError("--allow-skipped-packet-check is refused with --grant")
    if not GRANT_ROW_RE.fullmatch(args.grant):
        raise WorkflowError(f"--grant must be a decision-log row id, got {args.grant!r}")
    if not args.grant_at or not args.grant_until:
        raise WorkflowError("--grant needs --grant-at (the human's message) and --grant-until")
    at, until = parse_utc(args.grant_at, "--grant-at"), parse_utc(args.grant_until, "--grant-until")
    now = datetime.now(timezone.utc)
    if not at < until or (until - at).total_seconds() > GRANT_MAX_SECONDS:
        raise WorkflowError(f"grant {args.grant}: the window must end after it starts and last at most "
                            f"{GRANT_MAX_SECONDS // 3600} h")
    if at > now:
        raise WorkflowError(f"grant {args.grant}: --grant-at {iso(at)} is in the future")
    if now > until:
        raise WorkflowError(f"grant {args.grant}: delegation window closed at {iso(until)}")
    if "{approver}" not in (config["approval_status"] or ""):
        raise WorkflowError("a delegated approval needs an approval_status template that shows {approver}, so the "
                            "status reads delegated")
    if config["merge_mode"] == "bot" and not args.grant_merges:
        raise WorkflowError("under merge_mode: bot approving merges; pass --grant-merges only if the human's grant "
                            "said it includes merging")
    return {"row": args.grant, "at": iso(at), "until": iso(until), "merges": bool(args.grant_merges)}


def pin_grant(repo: Path, grant: dict[str, Any], write: bool) -> None:
    """Grants are pinned repo-wide on first use; every later use must match exactly (no extension)."""
    common = Path(run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    path = common / "feature-workflow" / "grants.json"
    with ledger_lock(path):
        grants = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        pinned = grants.get(grant["row"])
        if pinned is not None:
            if pinned != grant:
                raise WorkflowError(f"grant {grant['row']} is pinned to at {pinned['at']} until {pinned['until']} "
                                    f"merges {pinned['merges']}; a grant cannot change or be extended: log a new row")
            return
        if write:
            grants[grant["row"]] = grant
            path.write_text(json.dumps(grants, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def landing_plan(repo: Path, args: argparse.Namespace, report: dict[str, Any], approver: str,
                 keys: tuple[str, ...]) -> tuple[dict[str, str], dict[str, list[str]], dict[str, Any]] | None:
    """Validate config and the values its templates use, and render every command; --dry-run prints them."""
    if report["patch_id"] == "empty":
        raise WorkflowError("empty patch: nothing to approve")
    values = {"pr": args.pr, "sha": report["head_sha"], "patch_id": report["patch_id"], "approver": approver,
              "date": utc_now(), "head_ref": run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")}
    if run_git(repo, "diff", "--name-only", "--no-renames", report["base_sha"], values["sha"], "--", ".feature-workflow"):
        raise WorkflowError("this patch changes .feature-workflow/, whose rules and commands approve and carry trust; "
                            "land it on its own, approved with record --artifact approval")
    config = project_config(repo, args.project, report["base_sha"])
    if not config["pr_head"]:
        raise WorkflowError("project config switches pr_head off; approve and carry need the PR head")
    used = {name for key in ("pr_head", *keys) if config[key] for name in PLACEHOLDER_RE.findall(config[key])}
    bad = [f"{{{key}}}={values[key]!r}" for key in sorted(used) if not re.fullmatch(VALUE_RES[key], values[key])]
    if bad:
        raise WorkflowError(f"refusing to run commands with out-of-set values: {', '.join(bad)}")
    steps = {key: render(config[key], values) for key in ("pr_head", *keys) if config[key]}
    landing = {"project_config": config["path"], "merge_mode": config["merge_mode"],
               "required_checks": config["required_checks"]}
    if args.dry_run:
        emit({"dry_run": True, **landing, "would_run": steps})
        return None
    return values, steps, landing


def check_pr_head(repo: Path, argv: list[str], sha: str, after: str = "") -> None:
    head = run_command(repo, argv)["stdout"]
    if head != sha:
        raise WorkflowError(f"local HEAD {sha} is not the PR head {head or '(empty)'}"
                            + (f"; {after}" if after else "; push or pull first"))


def recheck(repo: Path, path: Path, artifact: str, values: dict[str, str],
            carry: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Under the lock: re-load and re-evaluate; the action must still be allowed, on the same head and patch."""
    state = load_state(path)
    refuse_closed(state)
    trial = copy.deepcopy(state)
    if carry:
        approval = trial["artifacts"].get("approval") or {}
        if approval.get("invalidated") or approval.get("revision") != carry["approval_revision"]:
            raise WorkflowError("the approval changed during carry; nothing recorded")
        trial["artifacts"]["carry"] = carry
    report = evaluate(trial, repo)
    require_current(report, trial, artifact)
    if (report["head_sha"], report["patch_id"]) != (values["sha"], values["patch_id"]):
        raise WorkflowError("HEAD or patch changed during landing; nothing recorded")
    return state, report


def cmd_approve(args: argparse.Namespace) -> int:
    """mark_ready, re-check the PR head, then approval_status and the record, under the ledger lock."""
    repo, path, state = open_run(args)
    refuse_closed(state)
    report = evaluate(state, repo)
    require_current(report, state, "approval")
    grant = grant_request(args, project_config(repo, args.project, report["base_sha"]))
    approver = delegated_approver() if grant else args.approver
    if not approver:
        raise WorkflowError("approve needs --approver NAME, or --grant for a delegated approval")
    check_approver(approver, delegated=bool(grant))
    if args.expect_patch is not None:
        if not re.fullmatch(r"[0-9a-f]{7,64}", args.expect_patch):
            raise WorkflowError("--expect-patch must be at least 7 lowercase hex characters of a patch id")
        if not report["patch_id"].startswith(args.expect_patch):
            raise WorkflowError(f"patch is {report['patch_id'][:12]}, not the approved {args.expect_patch}; re-ask")
    skipped = (state["artifacts"]["packet"].get("packet_check") or {}).get("skipped")
    if skipped and not args.allow_skipped_packet_check:
        raise WorkflowError(f"the packet was recorded with --skip-packet-check ({skipped}); re-record it, or pass "
                            "--allow-skipped-packet-check")
    if grant:
        pin_grant(repo, grant, write=not args.dry_run)
    plan = landing_plan(repo, args, report, approver, ("mark_ready", "approval_status"))
    if plan is None:
        return 0
    values, steps, landing = plan
    check_pr_head(repo, steps["pr_head"], values["sha"])
    ci, ci_note = check_problems(repo, project_config(repo, args.project, report["base_sha"]), values)
    if ci:
        raise WorkflowError("cannot approve before CI is green: " + "; ".join(ci))
    done = [run_command(repo, steps["mark_ready"])] if "mark_ready" in steps else []
    check_pr_head(repo, steps["pr_head"], values["sha"], "it moved after mark_ready; no approval status set")
    with ledger_lock(path):
        state, report = recheck(repo, path, "approval", values)
        try:
            done += [run_command(repo, steps["approval_status"])] if "approval_status" in steps else []
        except WorkflowError as exc:
            state.setdefault("approval_attempts", []).append(
                {"at": utc_now(), "pr": args.pr, "head_sha": values["sha"], "failed_step": "approval_status",
                 "error": str(exc)})
            write_state(path, state)
            raise WorkflowError(f"{exc}; no approval recorded") from exc
        note = path.parent / f"approval.{state['revision'] + 1}.md"
        lines = ["---", "workflow: feature-workflow/v2", f"run: {state['slug']}", "artifact: approval",
                 f"tier: {state['tier']}", f"source: {state['source']}"]
        lines += [f"{key}: {report[key]}" for key in ("base_sha", "head_sha", "patch_id")]
        lines += [f"generated_at: {values['date']}", "result: approved", "---",
                  f"Approved by {approver} on PR {args.pr}"
                  + (f" under grant {grant['row']} ({grant['at']} to {grant['until']}, merges: {grant['merges']})"
                     if grant else "")
                  + f"; evidence: {args.evidence_url or 'the commands below'}."]
        lines += [f"- `{shlex.join(item['argv'])}` exit 0 {item['stdout']}".rstrip() for item in done]
        note.write_text("\n".join(lines) + "\n", encoding="utf-8")
        extra = {"approver": approver, "grant": grant, "evidence_url": args.evidence_url, "pr": args.pr,
                 "landing": landing, "expect_patch": args.expect_patch,
                 "commands": done, "checks_note": ci_note or None,
                 "allow_skipped_packet_check": bool(args.allow_skipped_packet_check)}
        emit(store(state, path, "approval", report, str(note), extra))
    return 0


def file_hunks(repo: Path, base: str, head: str, entry: dict[str, Any] | None) -> bytes:
    """One file's patch without index, similarity and hunk-header lines: equal bytes mean the same hunks,
    wherever a rebase moved them."""
    if entry is None:
        return b""
    specs = [f":(literal){name}" for name in (entry["old_path"], entry["path"]) if name]
    diff = git_bytes(repo, "-c", "core.quotePath=false", "diff", *DIFF_FLAGS, "--no-color", base, head, "--", *specs)
    lines = [line for line in diff.split(b"\n")
             if not line.startswith((b"index ", b"similarity index ", b"dissimilarity index "))]
    return HUNK_HEADER_RE.sub(b"@@", b"\n".join(lines))


def carry_diff(repo: Path, approval: dict[str, Any], current: dict[str, Any],
               rules: dict[str, Any] | None) -> tuple[list[str], list[str], list[str]]:
    """Files whose hunks differ between the approved and current patch: (must-read, other, skip-read)."""
    before = {item["path"]: item for item in classify(repo, approval["base_sha"], approval["head_sha"], rules)["files"]}
    after = {item["path"]: item for item in classify(repo, current["base_sha"], current["head_sha"], rules)["files"]}
    must: list[str] = []
    other: list[str] = []
    skipped: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if file_hunks(repo, approval["base_sha"], approval["head_sha"], old) == \
                file_hunks(repo, current["base_sha"], current["head_sha"], new):
            continue
        entries = [item for item in (old, new) if item]
        if any(item["tier"] == "t2" and not item["skip_read"] for item in entries):
            must.append(name)
        else:
            (skipped if all(item["skip_read"] for item in entries) else other).append(name)
    return must, other, skipped


def cmd_carry(args: argparse.Namespace) -> int:
    """After a rebase, approval carries when the must-read hunks are byte-identical and every other changed file
    is skip-read. Verification must already be re-recorded on the new head."""
    repo, path, state = open_run(args)
    refuse_closed(state)
    approval = state["artifacts"].get("approval")
    if not approval or approval.get("invalidated"):
        raise WorkflowError("no approval to carry; run approve")
    if not approval.get("pr"):
        raise WorkflowError("the approval has no recorded PR; approve with --pr first")
    if approval["pr"] != args.pr:
        raise WorkflowError(f"the approval is for PR {approval['pr']}, not {args.pr}")
    grant = approval.get("grant")
    if grant and datetime.now(timezone.utc) > parse_utc(grant["until"], "grant until"):
        raise WorkflowError(f"re-approval needed: delegation window closed at {grant['until']} "
                            f"(grant {grant['row']})")
    for sha in (approval["base_sha"], approval["head_sha"]):
        if not resolve_commit(repo, sha):
            raise WorkflowError(f"approved commit {sha} is not in this repository; re-approval needed")
    current = run_snapshot(repo, state)
    rules, _ = load_rules(find_rules(repo, state.get("rules_path")))
    must, other, skipped = carry_diff(repo, approval, current, rules)
    if must:
        raise WorkflowError(f"re-approval needed: must-read changed in {', '.join(must)}")
    if other:
        raise WorkflowError(f"re-approval needed: {', '.join(other)} changed and not skip-read")
    entry = {"revision": state["revision"] + 1, "recorded_at": utc_now(), "approval_revision": approval["revision"],
             "from_patch_id": approval["patch_id"], "changed_files": skipped, "pr": args.pr, "invalidated": False,
             **{key: current[key] for key in ("base_sha", "head_sha", "patch_id")}}
    trial = copy.deepcopy(state)
    trial["artifacts"]["carry"] = entry
    report = evaluate(trial, repo, current)
    require_current(report, trial, "published")  # build and verification must be re-recorded on the new head
    plan = landing_plan(repo, args, report, approval["approver"], ("approval_status",))
    if plan is None:
        return 0
    values, steps, landing = plan
    check_pr_head(repo, steps["pr_head"], values["sha"])
    with ledger_lock(path):
        state, _ = recheck(repo, path, "published", values, entry)
        commands = [run_command(repo, steps["approval_status"])] if "approval_status" in steps else []
        state["revision"] += 1
        entry.update({"revision": state["revision"], "landing": landing, "commands": commands})
        state["artifacts"]["carry"] = entry
        state.setdefault("carries", []).append(entry)
        write_state(path, state)
    print(f"carried approval for PR {args.pr} to {current['head_sha']}: "
          + (f"only {', '.join(skipped)} changed" if skipped else "patch identical, no files changed")
          + ("; this will merge" if landing["merge_mode"] == "bot" else ""))
    return 0


PACKET_TITLE_RE = re.compile(r"## Review packet: (T[0-2]) · patch ([0-9a-f]{7,40}|empty) · head ([0-9a-f]{7,40})"
                             r"(?:\s.*)?", re.I)
PACKET_MARKER = "**Read these lines**"
PACKET_READ_RE = re.compile(r"\*\*Read these lines\*\* \((?:(\d+) marked of )?(\d+)\)")
CHECK_STATES = {"pass": "passed", "fail": "failing", "pending": "pending", "skipping": "skipped",
                "cancel": "cancelled"}


def packet_problems(text: str, state: dict[str, Any], report: dict[str, Any],
                    pending: dict[str, Any] | None = None) -> list[str]:
    """Compare the packet's title line and read marker (human-surfaces.md) with the ledger and the worktree.
    `pending` is a budget override being recorded with this packet."""
    problems = []
    lines = text.lstrip("\ufeff").splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    title = PACKET_TITLE_RE.fullmatch(first)
    if not title:
        problems.append("first line is not '## Review packet: <T0|T1|T2> · patch <id> · head <sha>'")
    else:
        tier, patch, head = title.group(1).lower(), title.group(2).lower(), title.group(3).lower()
        if tier != state["tier"]:
            problems.append(f"packet tier {tier.upper()} is not the run tier {state['tier'].upper()}")
        if not report["head_sha"].startswith(head):
            problems.append(f"packet head {head} is not the worktree HEAD {report['head_sha'][:12]}")
        if not report["patch_id"].startswith(patch):
            problems.append(f"packet patch {patch} is not the current patch-id {report['patch_id'][:12]}")
    statuses, required = report["artifacts"], REQUIRED[state["tier"]]
    for name in DEPENDENCIES["packet"]:
        status = statuses[name]["status"]
        if (name in required or status != "absent") and status != "current":
            problems.append(f"{name} is {status}: {'; '.join(statuses[name]['reasons']) or 'not recorded'}")
    markers, fenced = [], False
    for line in lines:  # a quoted, indented or fenced marker is not it
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and line.startswith(PACKET_MARKER):
            markers.append(line)
    read = PACKET_READ_RE.match(markers[0]) if markers else None
    counted = report["must_read_lines"]
    if read:
        marked, stated = (int(value) if value else None for value in read.groups())
        if stated != counted:
            problems.append(f"packet must-read {stated} is not the counted {counted}")
        overrides = [pending] if pending else [item for item in state.get("budget_overrides", [])
                                               if item.get("patch_id") == report["patch_id"]]
        if marked is not None and not any((item["marked_lines"], item["must_read_lines"]) == (marked, stated)
                                          for item in overrides):
            problems.append(f"override not recorded: no budget override for this patch marks {marked} of {stated}")
    elif markers:
        problems.append(f"malformed marker {markers[0][:60]!r}: use '**Read these lines** (N)' with a plain integer")
    elif state["tier"] == "t2":
        problems.append("no '**Read these lines** (N)' line (T2)")
    split = not read or read.group(1) is None
    problems += [f"{gate['gate']}: {gate['detail']}" for gate in report["gates"]
                 if "packet" in gate["blocks"] and (split or gate["gate"] != SPLIT_GATE)]
    if not report["worktree_clean"]:
        problems.append("worktree has uncommitted changes")
    return problems


def check_problems(repo: Path, config: dict[str, Any], values: dict[str, str]) -> tuple[list[str], str]:
    """Every required check passed (when none are named: no check pending, failing or cancelled). Returns
    (problems, note); `checks: null` in the project config means the project has no CI."""
    if not config["checks"]:
        return [], "no CI (project config sets checks to null)"
    used = set(PLACEHOLDER_RE.findall(config["checks"]))
    bad = sorted(key for key in used if key not in values or not re.fullmatch(VALUE_RES[key], values[key]))
    if bad:
        raise WorkflowError(f"refusing to run checks: placeholders {', '.join(bad)} are unavailable or out of set")
    argv = render(config["checks"], values)
    try:  # `gh pr checks` exits non-zero while checks are pending or failing; its JSON still says which
        proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"cannot run {shlex.join(argv)}: {exc}"], ""
    output = proc.stdout.lstrip("\ufeff").strip()
    try:
        rows = json.loads(output) if output else []
    except ValueError:
        if "no checks reported" not in (proc.stdout + proc.stderr).lower():
            return [f"cannot read checks from {shlex.join(argv)}: not JSON"], ""
        rows = []
    if not isinstance(rows, list) \
            or not all(isinstance(row, dict) and {"name", "bucket"} <= row.keys() for row in rows):
        return [f"cannot read checks from {shlex.join(argv)}: expected a list of {{name, bucket}}"], ""
    if not rows:
        return ["no checks reported; if the project has no CI, set checks to null in its config"], ""
    required, buckets = config["required_checks"], [(str(row["name"]), str(row["bucket"]).lower()) for row in rows]
    problems = [f"required check {name} has not reported" for name in required
                if name not in {row for row, _ in buckets}]
    for name, bucket in buckets:
        if bucket not in CHECK_STATES:
            problems.append(f"check {name} has an unknown state {bucket!r}")
        elif name in required and bucket != "pass":
            problems.append(f"required check {name} is {CHECK_STATES[bucket]}")
        elif not required and bucket in ("fail", "pending", "cancel"):
            problems.append(f"check {name} is {CHECK_STATES[bucket]}")
    return problems, ""


def pr_problems(repo: Path, project: str | None, pr: str, report: dict[str, Any]) -> tuple[list[str], str]:
    """The PR head must be the local HEAD and its checks green; read-only commands only."""
    config = project_config(repo, project, report["base_sha"])
    values = {"pr": pr, "sha": report["head_sha"], "patch_id": report["patch_id"],
              "head_ref": run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")}
    used = {name for key in ("pr_head", "checks") if config[key] for name in PLACEHOLDER_RE.findall(config[key])}
    bad = [f"{{{key}}}={values[key]!r}" for key in sorted(used & values.keys())
           if not re.fullmatch(VALUE_RES[key], values[key])]
    if bad or used - values.keys():
        raise WorkflowError(f"refusing to run pr_head or checks: out-of-set values {', '.join(bad) or 'none'}; "
                            f"unavailable placeholders {', '.join(sorted(used - values.keys())) or 'none'}")
    problems = []
    try:
        if not config["pr_head"]:
            raise WorkflowError("project config switches pr_head off; the PR head cannot be checked")
        check_pr_head(repo, render(config["pr_head"], values), values["sha"])
    except WorkflowError as exc:
        problems.append(str(exc))
    found, note = check_problems(repo, config, values)
    return problems + found, note


def read_packet(path: Path) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
        return data, data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkflowError(f"cannot read packet {path}: {exc}") from exc


def cmd_packet_check(args: argparse.Namespace) -> int:
    """Before posting a packet: its head, patch-id and must-read count must match the ledger and the worktree;
    with --pr, the PR head too, and no required check may be pending or failing. Never posts or records."""
    repo, _, state = open_run(args)
    report = evaluate(state, repo)
    problems, note = packet_problems(read_packet(Path(args.packet))[1], state, report), ""
    if args.pr:
        found, note = pr_problems(repo, args.project, args.pr, report)
        problems += found
    if problems:
        raise WorkflowError("packet-check refused, do not post:\n- " + "\n- ".join(problems))
    print(f"packet-check ok: head {report['head_sha'][:12]}, patch {report['patch_id'][:12]}, must-read "
          f"{report['must_read_lines']}" + (f", PR {args.pr} head and checks" if args.pr else ", PR not checked")
          + (f"; {note}" if note else ""))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    repo, _, state = open_run(args)
    report = evaluate(state, repo)
    approval = state["artifacts"].get("approval") or {}
    report["grant"] = {**approval["grant"], "approver": approval["approver"]} if approval.get("grant") else None
    if args.json:
        emit(report)
    else:
        def print(line: str) -> None:  # ledger text (sources, reasons, names) may hold control characters
            builtins.print(CONTROL_RE.sub(lambda match: f"\\x{ord(match.group()):02x}", line))
        print(f"run: {report['run']} (tier {report['tier']}); source: {report['source']}")
        if report["purpose"]:
            print(f"purpose: {report['purpose']}")
        print(f"base: {report['base_ref']} @ {report['base_sha']}")
        print(f"head: {report['head_sha']} (patch {report['patch_id']})"
              + (f"; merged into {report['base_ref']}" if report["merged"] else "")
              + ("; squash-merged, judged at the build snapshot" if report["squashed"] else ""))
        print(f"worktree: {'clean' if report['worktree_clean'] else 'dirty'}")
        print(f"rules: {report['rules_path'] or 'none'} (sha256 {report['rules_sha256'] or '-'})")
        budget, excluded = report["must_read_budget"], report["must_read_excluded"]
        print(f"path floor: {report['path_floor'] or 'n/a'}; budget: {budget if budget is not None else 'none'}")
        print(f"must-read: {report['must_read_lines']} counted (+{report['must_read_added']}/"
              f"-{report['must_read_deleted']}), {excluded['moved']} excluded (moved {excluded['moved']})"
              + (f"; {report['must_read_note']}" if report["must_read_note"] else ""))
        for gate in report["gates"]:
            print(f"GATE {gate['gate']}: {gate['detail']}")
        for name in ARTIFACT_ORDER:
            item = report["artifacts"][name]
            detail = "; ".join(item["reasons"] + item["notes"])
            label = "" if item["required"] else " [optional]"
            who = f" [recorded by {item['recorded_by'] or 'unnamed'} at {item['recorded_at']}]" \
                if item.get("recorded_at") else ""
            skipped = f" [packet-check skipped: {item['packet_check_skipped']}]" \
                if item.get("packet_check_skipped") else ""
            if name == "packet" and item.get("recorded_at") and not item.get("pr_checked"):
                skipped += " [PR/CI not checked]"
            print(f"{name}{label}: {item['status']}{who}{skipped}" + (f" ({detail})" if detail else ""))
        if report["grant"]:
            grant = report["grant"]
            print(f"grant: {grant['row']} ({grant['at']} to {grant['until']}, merges: {grant['merges']}) "
                  f"used by {grant['approver']}")
        for carry in report["carries"]:
            print(f"carry r{carry['revision']}: patch {carry['from_patch_id'][:12]} -> {carry['patch_id'][:12]} at "
                  f"{carry['head_sha'][:12]}; only {', '.join(carry['changed_files']) or 'no files'} changed")
        print(f"next: {report['next_artifact'] or 'none'}")
    return 0 if report["worktree_clean"] else 2


def cmd_set_tier(args: argparse.Namespace) -> int:
    repo, path, state = open_run(args)
    old, new = state["tier"], args.tier
    if new == old:
        raise WorkflowError(f"run is already {new}")
    lowering = TIERS.index(new) < TIERS.index(old)
    if lowering and not args.reason:
        raise WorkflowError(f"lowering the tier from {old} to {new} requires --reason")
    state["tier"] = new
    state["tier_changes"].append({"from": old, "to": new, "reason": args.reason, "at": utc_now()})
    if not lowering:
        invalidate_from(state, "build", f"tier raised {old}->{new}" + (f": {args.reason}" if args.reason else ""))
    write_state(path, state)
    emit(evaluate(state, repo))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    repo, _, state = open_run(args)
    current = run_snapshot(repo, state)
    classified, gates = ruled(repo, state, current)
    emit({"base_sha": current["base_sha"], "head_sha": current["head_sha"], "tier": state["tier"],
          **classified, "gates": gates})
    return 0


def cmd_set_rules(args: argparse.Namespace) -> int:
    repo, path, state = open_run(args)
    found = find_rules(repo, state.get("rules_path"))
    _, pin = load_rules(found)
    old = state.get("rules_pin")
    if pin == old:
        raise WorkflowError(f"rules match the pin ({found or 'no rules'}); nothing to re-pin")
    if found is None and old and old["path"]:
        raise WorkflowError(f"rules file {old['path']} is gone; restore it (a run cannot be re-pinned to no rules)")
    if old == NO_PIN and found == (repo / DEFAULT_RULES).resolve():
        raise WorkflowError("a run started without rules cannot adopt the in-tree fallback, which the branch "
                            "controls; pass --rules with --rules-override-reason or add the ancestor rules file")
    repin(state, pin, args.reason)
    write_state(path, state)
    emit(evaluate(state, repo))
    return 0


def cmd_invalidate(args: argparse.Namespace) -> int:
    _, path, state = open_run(args)
    affected = invalidate_from(state, args.from_artifact, args.reason)
    write_state(path, state)
    print(json.dumps({"affected": affected, "reason": args.reason}, sort_keys=True))
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    validate_slug(args.slug)
    print(state_path(repo_root(args.repo), args.slug, args.state_dir))
    return 0


def add_common(parser: argparse.ArgumentParser, rules: bool = False) -> None:
    parser.add_argument("--repo", default=".", help="repository or worktree path")
    parser.add_argument("--slug", required=True, help="stable lowercase run identifier")
    parser.add_argument("--state-dir", help="override the default worktree-local state directory")
    if rules:
        parser.add_argument("--rules", help="tier rules JSON, sticky per run (default: the first ancestor "
                            f".feature-workflow/<origin-name>.tiers.json, else <repo>/{DEFAULT_RULES})")
        parser.add_argument("--rules-override-reason", help="required to switch an existing run's --rules")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a run ledger")
    add_common(init, rules=True)
    init.add_argument("--source", required=True, help="issue URL, issue number, or concise idea")
    init.add_argument("--base-ref", default="origin/main")
    init.add_argument("--tier", choices=TIERS, default="t2", help="risk tier (default t2, the safest)")
    init.add_argument("--resume", action="store_true", help="show existing run instead of failing")
    init.add_argument("--allow-dirty", action="store_true")
    init.add_argument("--purpose", help="one line: the outcome this session delivers; status shows it")
    init.set_defaults(handler=locked(cmd_init))

    record = subparsers.add_parser("record", help="record a completed artifact")
    add_common(record, rules=True)
    record.add_argument("--artifact", required=True, choices=ARTIFACT_ORDER)
    record.add_argument("--path", help="artifact file path, required for Markdown artifacts")
    record.add_argument("--approver", help="approval: name of the human who approved")
    record.add_argument("--evidence-url", help="approval: commit status or PR comment URL")
    record.add_argument("--url", help="published: PR or branch URL")
    record.add_argument("--marked-lines", type=int, help="packet: must-read lines the packet marks, for the "
                        "budget when --budget-override-reason is given")
    record.add_argument("--budget-override-reason", help="packet: accept a split-required packet whose "
                        "--marked-lines fit the budget")
    record.add_argument("--recorded-by", help="who records it: the subagent or person that produced the artifact, "
                        "at the moment it finished (e.g. implementer, cold-reader)")
    record.add_argument("--pr", help="packet: also check the PR head and required checks, as packet-check --pr")
    record.add_argument("--project", help="packet: project config for --pr, as for approve")
    record.add_argument("--skip-packet-check", metavar="REASON", help="packet: record although packet-check "
                        "refuses; the reason and the refusals are stored and shown in status")
    record.add_argument("--remote-sha", help="published: pushed SHA (must equal HEAD), or the merge commit "
                        "once the branch is merged (its first-parent diff must match the approved patch)")
    record.set_defaults(handler=locked(cmd_record))

    for name, handler, text in (("approve", cmd_approve, "check the PR head, set the approval status, mark the PR "
                                 "ready and record the approval"),
                                ("carry", cmd_carry, "after a rebase, carry the approval when only skip-read files "
                                 "changed, and re-set the approval status on the new head")):
        land = subparsers.add_parser(name, help=text)
        add_common(land)  # no --rules: a re-pin would write state, even under --dry-run
        land.add_argument("--pr", required=True, help="PR number (digits only)")
        land.add_argument("--project", help="project config (default: ancestor .feature-workflow/<origin-name>"
                          ".project.json, else <repo>/.feature-workflow/project.json)")
        land.add_argument("--dry-run", action="store_true", help="run only the PR-head read; print the argv of "
                          "every other command and change nothing")
        if name == "approve":
            land.add_argument("--approver", help="name of the human who approved (ASCII; refused with --grant)")
            land.add_argument("--expect-patch", metavar="PREFIX", help="the patch id the human approved (>= 7 hex); "
                              "refuse when the current patch differs")
            land.add_argument("--grant", metavar="ROW", help="delegated approval under this decision-log grant row; "
                              "recorded as delegated:<session> (references/delegation.md)")
            land.add_argument("--grant-at", metavar="ISO_UTC", help="time of the human's grant message")
            land.add_argument("--grant-until", metavar="ISO_UTC", help="end of the window, at most 12 h after "
                              "--grant-at")
            land.add_argument("--grant-merges", action="store_true", help="the human's grant included merging "
                              "(required under merge_mode: bot)")
            land.add_argument("--evidence-url", help="the approval message or comment URL")
            land.add_argument("--allow-skipped-packet-check", action="store_true", help="approve a packet recorded "
                              "with --skip-packet-check; recorded in the approval")
        land.set_defaults(handler=handler)

    packet_check = subparsers.add_parser("packet-check", help="before posting: match the packet's head, patch-id, "
                                         "must-read count and (with --pr) PR head and checks to the ledger")
    add_common(packet_check)
    packet_check.add_argument("--packet", required=True, help="the packet file (grammar: human-surfaces.md)")
    packet_check.add_argument("--pr", help="PR number (digits only): also check its head and required checks")
    packet_check.add_argument("--project", help="project config, as for approve")
    packet_check.set_defaults(handler=cmd_packet_check)

    status = subparsers.add_parser("status", help="evaluate missing and stale artifacts")
    add_common(status, rules=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    set_tier = subparsers.add_parser("set-tier", help="change the run's risk tier")
    add_common(set_tier, rules=True)
    set_tier.add_argument("--tier", required=True, choices=TIERS)
    set_tier.add_argument("--reason", help="required when lowering the tier")
    set_tier.set_defaults(handler=locked(cmd_set_tier))

    classify_cmd = subparsers.add_parser("classify", help="print per-file tiers, path floor and must-read lines")
    add_common(classify_cmd, rules=True)
    classify_cmd.set_defaults(handler=cmd_classify)

    set_rules = subparsers.add_parser("set-rules", help="re-pin the run to the current rules file and hash")
    add_common(set_rules)
    set_rules.add_argument("--reason", required=True)
    set_rules.set_defaults(handler=locked(cmd_set_rules))

    invalidate = subparsers.add_parser("invalidate", help="mark an artifact and downstream records stale")
    add_common(invalidate)
    invalidate.add_argument("--from", dest="from_artifact", required=True, choices=ARTIFACT_ORDER)
    invalidate.add_argument("--reason", required=True)
    invalidate.set_defaults(handler=locked(cmd_invalidate))

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
