"""Repository binding, active worktree resolution and path helpers.

No Qt import belongs in this module or anywhere under tools/garage/core/.
Everything here is pure and testable with no display: it shells out to
`git` and reads/writes a small JSON settings file, nothing else.

R17 / AC17: Garage resolves the game repository without an argument, by
detecting a sibling `nuke-raider` checkout and confirming it by its
`origin` remote. The choice is recorded in a gitignored `garage.local.json`
at the Garage repo root. A recorded binding that no longer resolves is
reported as a failure, never silently re-detected.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

GAME_REPO_DIRNAME = "nuke-raider"
GAME_REPO_REMOTE_MARKER = "gmb-nuke-raider"
SETTINGS_FILENAME = "garage.local.json"
WORKTREE_ROOT_DIRNAME = "worktrees"


class BindingError(Exception):
    """Raised when the game repository (or an active worktree) cannot be
    resolved. `key` names the garage.local.json key to fix; the exception
    message says what the failure prevents.
    """

    def __init__(self, key: str, message: str):
        self.key = key
        self.message = message
        super().__init__(message)


@dataclass
class Worktree:
    path: Path
    branch: Optional[str]
    head: str
    detached: bool = False
    is_bare: bool = False


@dataclass
class Binding:
    game_repo: Path
    game_repo_source: str  # "recorded" or "detected"
    worktree_root: Path
    worktrees: List[Worktree]
    active_worktree: Worktree
    active_source: str  # "recorded" or "main-fallback"
    settings_path: Path

    def resolve(self, *parts: str) -> Path:
        """Join a path against the active worktree root. Later iterations
        must go through this (or config_h / build_dir below) instead of
        joining paths themselves.
        """
        return self.active_worktree.path.joinpath(*parts)

    @property
    def config_h(self) -> Path:
        return self.resolve("src", "config.h")

    @property
    def build_dir(self) -> Path:
        return self.resolve("build")


def _run_git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True,
        text=True,
    )


def get_git_remote_url(repo_path: Path, remote: str = "origin") -> Optional[str]:
    """Return the URL of `remote` for the repo at `repo_path`, or None if
    the path is not a git repository or has no such remote.
    """
    try:
        result = _run_git(["remote", "get-url", remote], repo_path)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def _looks_like_game_repo(path: Path) -> Optional[str]:
    """Return the origin remote URL if `path` is a checkout of the game
    repository, else None.
    """
    remote = get_git_remote_url(path)
    if remote and GAME_REPO_REMOTE_MARKER in remote:
        return remote
    return None


def find_default_game_repo(garage_root: Path) -> Path:
    """Detect the game repository as a sibling `nuke-raider` directory
    beside `garage_root`, confirmed by its origin remote. Raises
    BindingError (key "game_repo") when the sibling is missing or does
    not hold the expected checkout.
    """
    candidate = garage_root.parent / GAME_REPO_DIRNAME
    if not candidate.is_dir():
        raise BindingError(
            "game_repo",
            f"No sibling '{GAME_REPO_DIRNAME}' directory was found beside "
            f"'{garage_root}' (expected '{candidate}'). Garage cannot "
            f"resolve any path in the game repository until 'game_repo' "
            f"is set in {garage_root / SETTINGS_FILENAME}.",
        )
    remote = get_git_remote_url(candidate)
    if not remote or GAME_REPO_REMOTE_MARKER not in remote:
        raise BindingError(
            "game_repo",
            f"'{candidate}' does not hold a {GAME_REPO_REMOTE_MARKER} "
            f"checkout (origin remote: {remote!r}). Garage cannot resolve "
            f"any path in the game repository until 'game_repo' is set "
            f"in {garage_root / SETTINGS_FILENAME}.",
        )
    return candidate


def _validate_recorded_game_repo(candidate: Path, settings_path: Path) -> None:
    """Raise BindingError (key "game_repo") if the recorded path no longer
    resolves or no longer holds a game repository checkout.
    """
    if not candidate.is_dir():
        raise BindingError(
            "game_repo",
            f"The recorded game repository path '{candidate}' no longer "
            f"exists. Fix 'game_repo' in {settings_path}. Garage cannot "
            f"resolve any path in the game repository until this is fixed.",
        )
    remote = get_git_remote_url(candidate)
    if not remote or GAME_REPO_REMOTE_MARKER not in remote:
        raise BindingError(
            "game_repo",
            f"The recorded game repository path '{candidate}' does not "
            f"hold a {GAME_REPO_REMOTE_MARKER} checkout (origin remote: "
            f"{remote!r}). Fix 'game_repo' in {settings_path}. Garage "
            f"cannot resolve any path in the game repository until this "
            f"is fixed.",
        )


def settings_path_for(garage_root: Path) -> Path:
    return garage_root / SETTINGS_FILENAME


def load_settings(garage_root: Path) -> Optional[dict]:
    """Return the parsed garage.local.json, or None when it does not
    exist yet (first run).
    """
    path = settings_path_for(garage_root)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_settings(garage_root: Path, settings: dict) -> None:
    path = settings_path_for(garage_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def list_worktrees(game_repo: Path) -> List[Worktree]:
    """Parse `git worktree list --porcelain` for `game_repo`. Handles a
    detached HEAD and a bare entry without crashing.
    """
    result = _run_git(["worktree", "list", "--porcelain"], game_repo)
    if result.returncode != 0:
        raise BindingError(
            "game_repo",
            f"'git worktree list' failed in '{game_repo}': "
            f"{result.stderr.strip()}. Garage cannot list worktrees of "
            f"the game repository until this is fixed.",
        )

    worktrees: List[Worktree] = []
    record: dict = {}

    def flush():
        if record:
            worktrees.append(_worktree_from_record(dict(record)))

    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip("\n")
        if line == "":
            flush()
            record.clear()
            continue
        if " " in line:
            key, _, value = line.partition(" ")
        else:
            key, value = line, ""
        if key == "worktree":
            flush()
            record.clear()
            record["worktree"] = value
        else:
            record[key] = value
    flush()

    return worktrees


def _worktree_from_record(record: dict) -> Worktree:
    path = Path(record["worktree"])
    is_bare = "bare" in record
    detached = "detached" in record
    head = record.get("HEAD", "")
    branch_ref = record.get("branch")
    branch = None
    if branch_ref:
        prefix = "refs/heads/"
        branch = branch_ref[len(prefix):] if branch_ref.startswith(prefix) else branch_ref
    return Worktree(path=path, branch=branch, head=head, detached=detached, is_bare=is_bare)


def _same_path(a: Path, b: Path) -> bool:
    import os

    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def resolve_active_worktree(
    worktrees: List[Worktree], recorded_active: Optional[str]
) -> "tuple[Worktree, str]":
    """Resolve the active worktree: the recorded `active` path when it
    still names a current worktree, otherwise the main worktree (the
    first entry `git worktree list` reports). Returns (worktree, source)
    where source is "recorded" or "main-fallback".
    """
    if not worktrees:
        raise BindingError(
            "game_repo",
            "The game repository reports no worktrees at all. Garage "
            "cannot resolve an active worktree until this is fixed.",
        )
    main = worktrees[0]
    if recorded_active:
        recorded_path = Path(recorded_active)
        for wt in worktrees:
            if not wt.is_bare and _same_path(wt.path, recorded_path):
                return wt, "recorded"
    return main, "main-fallback"


def default_garage_root() -> Path:
    """The Garage repository root, derived from this file's location:
    tools/garage/core/project.py -> repo root is three levels up.
    """
    return Path(__file__).resolve().parents[3]


def bind(garage_root: Optional[Path] = None) -> Binding:
    """Resolve the full binding: game repository, worktree root and
    active worktree. Raises BindingError on any failure -- callers (the
    Qt layer) must catch it and display the failure; this function never
    silently falls back on a bad recorded game_repo.
    """
    if garage_root is None:
        garage_root = default_garage_root()
    garage_root = Path(garage_root)
    settings_path = settings_path_for(garage_root)

    settings = load_settings(garage_root)
    first_run = settings is None
    if settings is None:
        settings = {}

    recorded_game_repo = settings.get("game_repo")
    if recorded_game_repo:
        game_repo = Path(recorded_game_repo)
        _validate_recorded_game_repo(game_repo, settings_path)
        game_repo_source = "recorded"
    else:
        game_repo = find_default_game_repo(garage_root)
        game_repo_source = "detected"

    recorded_worktree_root = settings.get("worktree_root")
    if recorded_worktree_root:
        worktree_root = Path(recorded_worktree_root)
    else:
        worktree_root = game_repo.parent / WORKTREE_ROOT_DIRNAME

    if first_run:
        save_settings(
            garage_root,
            {
                "game_repo": game_repo.as_posix(),
                "worktree_root": worktree_root.as_posix(),
                "active": None,
            },
        )

    worktrees = list_worktrees(game_repo)
    recorded_active = settings.get("active")
    active_worktree, active_source = resolve_active_worktree(worktrees, recorded_active)

    return Binding(
        game_repo=game_repo,
        game_repo_source=game_repo_source,
        worktree_root=worktree_root,
        worktrees=worktrees,
        active_worktree=active_worktree,
        active_source=active_source,
        settings_path=settings_path,
    )
