"""Filing one GitHub issue for the work in the active worktree (#5). Pure
and Qt-free (R10): everything here composes text, parses recorded output,
or shells out through an injected runner, and none of it needs a display.

**Why this module exists at all.** `.github/workflows/pr-linked-issue.yml`
fails any pull request whose body holds no `Closes #N`, and tuning work
starts with no issue behind it. The alternative — an exemption keyed to a
branch prefix or a body marker — is asserted by whoever opens the pull
request, so it would be an opt-out available to everybody with a
Garage-flavoured name. Filing an issue costs one action and keeps the
property the workflow exists to protect.

**The issue is filed in the game repository**, whose worktree the work is
in and whose `master` the pull request will target. The slug comes from
that repository's `origin` remote; no path and no repository name is
spelled out here (R11).

**Nothing here pushes, opens a pull request, closes an issue or edits
one** (R9). The only write is `gh issue create`, plus the two field values
that put it on the board.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from tools.garage.core import config_io
from tools.garage.core.project import Binding, get_git_remote_url

MASTER_BRANCHES = ("master", "main")


@dataclass(frozen=True)
class ChangedDefine:
    """One `#define` whose value in the worktree differs from HEAD (R4).

    Both values are the text as written — `0xDF80U`, `4u`, `32` — not the
    parsed integer. The body is read by someone who will go and look the
    value up in `config.h`, and a radix change on the way there is a lie.
    """

    name: str
    head_text: str
    new_text: str


def changed_defines(binding: Binding) -> List[ChangedDefine]:
    """Every `#define` that differs between the worktree and HEAD, by name.

    Two `git`-backed reads, once each: `config_io.read_value_at_head` warns
    in its own docstring against being called per row, because it re-runs
    `git show` every time.

    A `#define` that has no value at HEAD is not a change — there is no
    "from" to state — and neither is one that has no value now. Returns an
    empty list when either side cannot be read; the caller reports that
    through `refuse_reason`, not through an exception it would have to
    catch around a button press.
    """
    try:
        current = config_io.read(binding)
        head = config_io.read_config_at_head(binding)
    except config_io.ConfigIOError:
        return []

    changes = []
    for name in sorted(current.defines):
        new = current.defines[name]
        old = head.defines.get(name)
        if old is None or not old.has_value or not new.has_value:
            continue
        if old.value == new.value and old.value_text == new.value_text:
            continue
        changes.append(
            ChangedDefine(
                name=name,
                head_text=old.value_text or str(old.value),
                new_text=new.value_text or str(new.value),
            )
        )
    return changes


def _git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )


def branch_commits(worktree: Path, count: int = 20) -> List[str]:
    """`<short sha> <subject>` for the commits this branch holds that its
    base does not, newest first. Empty when the branch is at its base, when
    no base is found, or when the worktree cannot be read.

    The base is whichever of `master` or `main` this repository actually
    has — the game repository uses `master`, but naming one branch here
    would be a second place to change if that ever moved.
    """
    for base in MASTER_BRANCHES:
        probe = _git(["rev-parse", "--verify", "--quiet", base], worktree)
        if probe.returncode != 0:
            continue
        result = _git(
            ["log", f"-{count}", "--format=%h %s", f"{base}..HEAD"], worktree
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]
    return []


def refuse_reason(
    binding: Optional[Binding],
    changes: Sequence[ChangedDefine],
    commits: Sequence[str],
) -> Optional[str]:
    """Why no work item may be filed, or None when one may (AC1).

    The binding is checked first, so a user with nothing bound is told the
    thing they cannot fix by editing a value.
    """
    if binding is None:
        return "No repository is bound; there is nothing to file a work item for."
    if not changes and not commits:
        return (
            "This worktree holds no changed value and no commit of its own, "
            "so there is nothing to file a work item about."
        )
    return None


TITLE_PREFIX = "chore:"

_PREFIX_RE = re.compile(r"^\s*chore\s*:\s*", re.IGNORECASE)


class WorkItemError(Exception):
    """A refusal Garage makes on its own, before any `gh` call."""


def title_for(raw: str) -> str:
    """`chore: <what the user typed>` (R3/AC4).

    The prefix is what gives the board `Type = Chore` when the conventions
    are read back by a human, so it is applied here rather than left to the
    user to remember. An existing prefix is normalised, not doubled — a
    user who types the convention correctly must not be punished with
    `chore: chore: …`.
    """
    stripped = (raw or "").strip()
    if not stripped:
        raise WorkItemError("A work item needs a title.")
    body = _PREFIX_RE.sub("", stripped).strip()
    if not body:
        raise WorkItemError("A work item needs a title beyond the `chore:` prefix.")
    return f"{TITLE_PREFIX} {body}"


def closes_line(number: int) -> str:
    """The reference `.github/workflows/pr-linked-issue.yml` greps for.

    Spelled here rather than at the call site because it is the one string
    in this module whose exact form another repository's CI depends on.
    """
    return f"Closes #{number}"


def compose_body(
    changes: Sequence[ChangedDefine],
    description: str,
    branch: Optional[str],
    commits: Sequence[str],
) -> str:
    """The issue body: what the user said, what changed, and where.

    The parameter table is the part R4 requires and the part a reviewer
    actually reads — an issue that says "tuned the handling" and nothing
    else cannot be checked against the diff six weeks later.
    """
    parts: List[str] = []

    text = (description or "").strip()
    if text:
        parts.append(text)

    if changes:
        rows = "\n".join(
            f"| `{c.name}` | `{c.head_text}` | `{c.new_text}` |" for c in changes
        )
        parts.append(
            "## Changed parameters\n\n"
            "| `#define` | At HEAD | New |\n"
            "|---|---|---|\n" + rows
        )
    else:
        parts.append(
            "## Changed parameters\n\n"
            "No `#define` differs from HEAD; this work item covers the "
            "commits below."
        )

    if commits:
        listed = "\n".join(f"- `{line}`" for line in commits)
        parts.append("## Commits\n\n" + listed)

    where = f"Filed by Garage from the `{branch}` worktree." if branch else "Filed by Garage."
    parts.append(where)

    return "\n\n".join(parts) + "\n"


# The shared board, from the `file-an-issue` skill. These three are stable
# literals; the field and option ids below them are not, and are resolved
# by name every time (R5).
PROJECT_NUMBER = "3"
PROJECT_OWNER = "MatthieuGagne"
PROJECT_ID = "PVT_kwHOAv4a5M4BepB5"

TYPE_FIELD = "Type"
TYPE_OPTION = "Chore"
STATUS_FIELD = "Status"
STATUS_OPTION = "Todo"

_SLUG_RE = re.compile(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$")
_ISSUE_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/issues/(\d+)")


@dataclass(frozen=True)
class CommandResult:
    argv: Sequence[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def message(self) -> str:
        """What the tool said, preferring stderr — which is where `gh` puts
        the reason a call was refused (R8 shows this verbatim).
        """
        return (self.stderr.strip() or self.stdout.strip()) or (
            f"`{' '.join(self.argv)}` failed with exit code {self.exit_code} "
            f"and said nothing."
        )


Runner = Callable[..., CommandResult]

EXIT_NOT_STARTED = 127


def run_capture(argv: Sequence[str], cwd: Optional[Path] = None) -> CommandResult:
    """Run `argv` and capture everything, without a shell.

    Never raises. A `gh` call happens behind a button, on a worker thread,
    and an exception crossing that boundary is a crash rather than a
    message in the window (R8).
    """
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return CommandResult(
            argv=tuple(argv), exit_code=EXIT_NOT_STARTED, stdout="", stderr=str(exc)
        )
    return CommandResult(
        argv=tuple(argv),
        exit_code=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def repo_slug(remote_url: Optional[str]) -> Optional[str]:
    """`owner/name` for a GitHub remote, or None when it is not one.

    Derived rather than spelled out: the game repository's name appears
    nowhere in Garage (R11), and a user working against a fork must not
    have their work item filed against somebody else's repository.
    """
    if not remote_url:
        return None
    match = _SLUG_RE.search(remote_url.strip())
    if not match:
        return None
    return f"{match.group(1)}/{match.group(2)}"


def issue_number(create_output: str) -> int:
    """The number in the issue URL `gh issue create` prints (AC7)."""
    match = _ISSUE_URL_RE.search(create_output or "")
    if not match:
        raise WorkItemError(
            "`gh issue create` did not print an issue URL, so Garage cannot "
            "say which issue it filed. Check the repository on GitHub before "
            "filing again — one may already exist."
        )
    return int(match.group(1))


def resolve_option(fields, field_name: str, option_name: str):
    """`(field_id, option_id)` for one single-select value, by name (R5).

    Option ids are regenerated whenever the option set is edited, so
    recording one would work until the day somebody renames a `Type` and
    then silently write the wrong value. Both halves are looked up every
    time, and a name that is gone is a refusal — never a guess.
    """
    for field in fields or ():
        if field.get("name") != field_name:
            continue
        options = field.get("options") or []
        if not options:
            raise WorkItemError(
                f"The board's `{field_name}` field carries no options, so "
                f"`{option_name}` cannot be resolved."
            )
        for option in options:
            if option.get("name") == option_name:
                return field["id"], option["id"]
        available = ", ".join(o.get("name", "?") for o in options)
        raise WorkItemError(
            f"The board's `{field_name}` field has no `{option_name}` "
            f"option. It offers: {available}."
        )
    raise WorkItemError(
        f"The board has no `{field_name}` field, so Garage cannot set it."
    )


STEP_FIELDS = "resolve the board's fields"
STEP_CREATE = "create the issue"
STEP_BOARD = "add the issue to the board"
STEP_TYPE = "set Type"
STEP_STATUS = "set Status"


@dataclass(frozen=True)
class WorkItem:
    """An issue Garage filed, and how far onto the board it got.

    The three booleans exist because the board is reached in three separate
    writes and R8 forbids leaving any of them silently undone. A caller
    that sees `complete is False` has something to tell the user.
    """

    number: int
    url: str
    on_board: bool = False
    type_set: bool = False
    status_set: bool = False

    @property
    def complete(self) -> bool:
        return self.on_board and self.type_set and self.status_set


@dataclass(frozen=True)
class WorkItemFailure:
    """A step that did not happen, in GitHub's own words (R8/AC10).

    `item` is None when nothing was created, and otherwise carries exactly
    what does exist — which is what the panel offers to finish.
    """

    step: str
    message: str
    item: Optional[WorkItem] = None

    @property
    def text(self) -> str:
        lead = f"Garage could not {self.step}: {self.message}"
        if self.item is None:
            return lead + "\nNo issue was created."
        missing = []
        if not self.item.on_board:
            missing.append("it is not on the board")
        else:
            if not self.item.type_set:
                missing.append("Type is unset")
            if not self.item.status_set:
                missing.append("Status is unset")
        return (
            f"{lead}\nIssue #{self.item.number} exists ({self.item.url}), but "
            f"{', and '.join(missing)}."
        )


def _gh_project(*args: str) -> List[str]:
    return ["gh", "project", *args]


def _field_list_argv() -> List[str]:
    return _gh_project(
        "field-list", PROJECT_NUMBER, "--owner", PROJECT_OWNER, "--format", "json"
    )


def _item_edit_argv(item_id: str, field_id: str, option_id: str) -> List[str]:
    return _gh_project(
        "item-edit",
        "--id",
        item_id,
        "--project-id",
        PROJECT_ID,
        "--field-id",
        field_id,
        "--single-select-option-id",
        option_id,
    )


def file_work_item(
    binding: Optional[Binding],
    title: str,
    description: str,
    *,
    changes: Optional[Sequence[ChangedDefine]] = None,
    commits: Optional[Sequence[str]] = None,
    existing: Optional[WorkItem] = None,
    run: Runner = run_capture,
):
    """File one issue for the active worktree and put it on the board.

    Returns a `WorkItem` when every step succeeded, and a
    `WorkItemFailure` otherwise. Nothing raises: this runs behind a button,
    on a worker thread.

    The order is deliberate (R8). `field-list` is a read, and it comes
    first, so a `Type` or `Status` option that has been renamed fails while
    nothing exists yet. After the issue is created there is no transaction
    to fall back on — GitHub sets one field per call — so a later failure
    is reported as a partial `WorkItem` and the caller may pass it back as
    `existing` to finish the remaining steps. Resuming files no second
    issue.
    """
    changes = list(changes or [])
    commits = list(commits or [])

    if existing is None:
        refusal = refuse_reason(binding, changes, commits)
        if refusal:
            return WorkItemFailure(step=STEP_CREATE, message=refusal)
        try:
            full_title = title_for(title)
        except WorkItemError as exc:
            return WorkItemFailure(step=STEP_CREATE, message=str(exc))
    else:
        full_title = title_for(title) if title.strip() else ""

    if binding is None:
        # Reachable only on the resume path, which skips refuse_reason: a
        # caller may hand back an `existing` WorkItem with no binding. This
        # is a refusal, not a crash — an AssertionError must never cross
        # the worker thread this runs on.
        return WorkItemFailure(
            step=STEP_CREATE,
            message="No repository is bound; there is nothing to file a work item for.",
        )

    # Step 1 — resolve both field/option pairs by name, before any write.
    listed = run(_field_list_argv())
    if not listed.ok:
        return WorkItemFailure(step=STEP_FIELDS, message=listed.message)
    try:
        fields = json.loads(listed.stdout or "{}").get("fields", [])
        type_field, type_option = resolve_option(fields, TYPE_FIELD, TYPE_OPTION)
        status_field, status_option = resolve_option(
            fields, STATUS_FIELD, STATUS_OPTION
        )
    except (ValueError, WorkItemError) as exc:
        return WorkItemFailure(step=STEP_FIELDS, message=str(exc))

    # Step 2 — the issue itself.
    item = existing
    if item is None:
        slug = repo_slug(get_git_remote_url(binding.game_repo))
        if slug is None:
            return WorkItemFailure(
                step=STEP_CREATE,
                message=(
                    "The bound repository has no GitHub `origin` remote, so "
                    "Garage cannot tell which repository to file in."
                ),
            )
        body = compose_body(
            changes, description, binding.active_worktree.branch, commits
        )
        created = _create_issue(run, slug, full_title, body, binding)
        if isinstance(created, WorkItemFailure):
            return created
        item = created

    # Step 3 — the board.
    if not item.on_board:
        added = run(
            _gh_project(
                "item-add",
                PROJECT_NUMBER,
                "--owner",
                PROJECT_OWNER,
                "--url",
                item.url,
                "--format",
                "json",
            )
        )
        if not added.ok:
            return WorkItemFailure(step=STEP_BOARD, message=added.message, item=item)
        try:
            item_id = json.loads(added.stdout or "{}")["id"]
        except (ValueError, KeyError):
            return WorkItemFailure(
                step=STEP_BOARD,
                message=(
                    "`gh project item-add` printed no item id, so Garage "
                    "cannot set Type or Status."
                ),
                item=item,
            )
        item = replace(item, on_board=True)
    else:
        found = _find_item_id(run, item.url)
        if isinstance(found, WorkItemFailure):
            return replace(found, item=item)
        item_id = found

    # Step 4 — the two fields, Type first: it is the one that decides how
    # the board groups the issue, so a failure between them leaves the more
    # useful half done.
    for step, field_id, option_id, attribute in (
        (STEP_TYPE, type_field, type_option, "type_set"),
        (STEP_STATUS, status_field, status_option, "status_set"),
    ):
        if getattr(item, attribute):
            continue
        edited = run(_item_edit_argv(item_id, field_id, option_id))
        if not edited.ok:
            return WorkItemFailure(step=step, message=edited.message, item=item)
        item = replace(item, **{attribute: True})

    return item


def _create_issue(run: Runner, slug: str, title: str, body: str, binding: Binding):
    """`gh issue create`, with the body in a file rather than an argument.

    The file is removed whatever happens: a body left in the temp directory
    is a copy of work-in-progress notes nobody asked to keep.
    """
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".md", encoding="utf-8", delete=False, newline="\n"
    )
    try:
        handle.write(body)
        handle.close()
        created = run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                slug,
                "--title",
                title,
                "--body-file",
                handle.name,
            ],
            binding.active_worktree.path,
        )
    finally:
        Path(handle.name).unlink(missing_ok=True)

    if not created.ok:
        return WorkItemFailure(step=STEP_CREATE, message=created.message)
    try:
        number = issue_number(created.stdout)
    except WorkItemError as exc:
        return WorkItemFailure(step=STEP_CREATE, message=str(exc))
    return WorkItem(number=number, url=_ISSUE_URL_RE.search(created.stdout).group(0))


def _find_item_id(run: Runner, url: str):
    """The board item id for an issue already on the board — needed only on
    the resume path, where the `item-add` that would have printed it has
    already succeeded in an earlier attempt.
    """
    listed = run(
        _gh_project(
            "item-list",
            PROJECT_NUMBER,
            "--owner",
            PROJECT_OWNER,
            "--limit",
            "500",
            "--format",
            "json",
        )
    )
    if not listed.ok:
        return WorkItemFailure(step=STEP_BOARD, message=listed.message)
    try:
        items = json.loads(listed.stdout or "{}").get("items", [])
    except ValueError:
        items = []
    for entry in items:
        if entry.get("content", {}).get("url") == url:
            return entry["id"]
    return WorkItemFailure(
        step=STEP_BOARD,
        message=f"{url} is not on the board, so its fields cannot be set.",
    )
