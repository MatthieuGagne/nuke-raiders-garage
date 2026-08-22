# Shared Document Conventions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `nuke-raiders-garage` to full convention parity with `gmb-nuke-raider` — the six document labels exist and are applied, every garage issue sits on the shared board with a `Type`, epic #1 owns its four child specs as native sub-issues, and a new root `CLAUDE.md` restates the operational musts and names the game repo's `CLAUDE.md` as canonical.

**Architecture:** Four of the five deliverables are **GitHub state**, not code: labels, project-3 membership and field values, and sub-issue edges. They are applied with `gh` and verified by re-reading the API — there is nothing to unit-test and nothing to commit. The fifth is the only tracked-file change: a new `CLAUDE.md` at the repo root, whose required content is pinned by a new `tests/test_docs_conventions.py` so the section cannot be silently deleted later. That test is the red/green vehicle for AC4 and rides the existing default `make test` target (no Qt, no game repo binding).

**Tech Stack:** `gh` CLI 2.96.0 (`gh label`, `gh project`, `gh api`), GitHub Projects v2 (project 3, "Nuke Raider — Documents", id `PVT_kwHOAv4a5M4BepB5`), Python 3.13 stdlib `unittest` via `make test`. No new dependency, no Qt.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/25 — "feat: adopt the shared document conventions — labels, board typing, CLAUDE.md pointer". R1–R4 and AC1–AC4 below are quoted from that issue body. The conventions it adopts are defined in the game repo's `CLAUDE.md`, "Workflow" section: https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md

---

## Global Constraints

- **No file in the game repository may be changed.** `C:/Code/nuke-raider` is read-only for this work — it is the source the conventions are copied *from*. Game-repo changes belong to the companion PRD `MatthieuGagne/gmb-nuke-raider#666`.
- **Only one tracked file in this repo changes on disk:** `CLAUDE.md` (new). Task 4 also adds `tests/test_docs_conventions.py`, which is this plan's own verification instrument for AC4.
- **No Qt import** in `tests/test_docs_conventions.py`. The default suite (`make test`) must pass with PySide6 absent — that is what `.github/workflows/test.yml` proves.
- **The new test must pass with no game repository bound.** CI checks this repository out alone; the test may read only files inside this repo.
- **Do not retitle any issue.** #6 and #18 are closed and carry a `PRD:` prefix that predates the convention. Out of Scope in the spec; history stays. They get the `prd` label and `Type = PRD`, nothing else.
- **Project id `PVT_kwHOAv4a5M4BepB5` is a stable literal. Field ids and single-select option ids are NOT** — they regenerate whenever an option set is edited. Always resolve them by name from `gh project field-list 3 --owner MatthieuGagne --format json` at the moment of use. Never paste an option id from this plan into a command.
- **Sub-issue wiring takes the child's numeric REST `id`**, not its `node_id` and not its issue number: `POST /repos/{owner}/{repo}/issues/{parent}/sub_issues` with `-F sub_issue_id=<id>`.
- Run tests with `python -m unittest ...` or `make test`. `python -m pytest` does not exist here.
- Never read `$LASTEXITCODE` after a piped command — the pipe masks it. Run the command bare and read its printed output.
- Never write `close`/`fix`/`resolve` next to `#25` in the PR body. This plan closes #25 by hand in Task 6, after all four acceptance criteria are verified — the PR carries only `CLAUDE.md` and cannot satisfy AC1–AC3 on its own.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` and reference `(#25)` in the subject.
- Work on a branch, not `main`. Suggested: `feat/shared-document-conventions`.
- Task 5 writes a file under `C:\Users\mathd\.claude\`, outside the repo. Per the user's standing rule, **draft it, show it, and wait for explicit approval before writing it.** Do not create it unprompted.

---

## Current state, verified 2026-08-21

Read this before starting. The board was partially typed after the spec was written, so several
R3 items are already satisfied and must not be redone.

**Labels in this repo** (`gh label list --repo MatthieuGagne/nuke-raiders-garage`):
`prd` already exists with the game repo's exact color and description. `epic`, `adr`, `log`,
`plan`, `idea` are **absent**. No garage issue carries any document label except #25 (`prd`).

**Garage issues** (18, all numbers below are `MatthieuGagne/nuke-raiders-garage`):
`#1` (open, epic) · `#2 #3 #6 #8 #9 #11 #13 #16 #18 #19 #21` (closed) · `#4 #5 #23 #25 #26 #28` (open).
The spec says "15 garage issues"; #26 and #28 were filed after it and are already on the board and
typed, which is why the count reads 18 today. AC1 is checked as *every* garage issue, not fifteen.

**On project 3 already, with `Type` set** — leave alone:

| Issue | Type | Status |
|---|---|---|
| #1 | Epic | Todo |
| #2 | PRD | Done |
| #3 | PRD | Done |
| #4 | PRD | Todo |
| #5 | PRD | Todo |
| #8 #9 #11 #13 #16 | Bug | Done |
| #25 | PRD | Todo |
| #26 #28 | Bug | Todo |

**Missing from the board entirely — this is Task 2's whole job:** #6, #18, #19, #21, #23.

**Sub-issues:** `#1`'s `sub_issues_summary.total` reads `0`. Nothing is wired.

**`CLAUDE.md` does not exist** in this repo — not tracked, not gitignored, not present. R1 says the
file "gains" a section; in practice Task 4 creates the file.

**One spec note did not reproduce.** The spec's Notes say `gh issue view` needs `--json` fields to
avoid a `projectCards` GraphQL error. On gh 2.96.0, `gh issue view 25 --repo MatthieuGagne/nuke-raiders-garage`
with no flags succeeds and prints the project row. Do **not** write that claim into `CLAUDE.md`;
Task 5's memory draft records it as version-dependent and unreproduced instead.

**Numeric REST ids of the four children** (Task 3 re-reads them rather than trusting this table,
but they are recorded so a mismatch is visible):
`#2 = 5075964400` · `#3 = 5075964484` · `#4 = 5075964568` · `#5 = 5075964654`. Epic `#1 = 5075963768`.

---

## Acceptance Criteria (from the issue)

- **AC1.** All garage issues appear on project 3 with a non-blank `Type`. (Spec says "all 15"; see the count note above.)
- **AC2.** `sub_issues_summary.total` on #1 reads 4.
- **AC3.** Labels `prd`, `epic`, `adr`, `log`, `plan`, `idea` exist, mirroring the game repo's colors and descriptions; `epic` + `prd` on #1, `prd` on #2 #3 #4 #5 #6 #18.
- **AC4.** `CLAUDE.md` carries the "Issues & documents" section per R1.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `CLAUDE.md` | **create** | Repo-root session instructions. In this plan it holds exactly one section, "Issues & documents": a pointer to the game repo's `CLAUDE.md` as canonical, plus the operational musts restated so a session working here can file an issue correctly without fetching that file. Build/test/architecture sections are deliberately **not** added — out of scope for #25, and a later issue can grow the file. |
| `tests/test_docs_conventions.py` | **create** | Pins the required content of that section: the heading exists, the canonical URL is present, and every must R1 enumerates appears. Runs under the default `make test` target — no Qt, no game repo binding, no network. |
| `<scratchpad>/add_and_type.py` | **create, untracked** | Throwaway helper for Task 2: adds one issue to project 3 and sets `Type` and `Status`, resolving field and option ids by name. Lives in the session scratchpad, never in the repo — there is no second use for it. |
| `C:\Users\mathd\.claude\projects\C--Code-nuke-raider-garage\memory\project-shared-board-conventions.md` | **create, outside the repo, approval-gated** | Machine-local memory so a future garage session knows both repos share board 3 before it files anything. |

---

## Task 1: The six document labels (R2, AC3)

**Files:** none — GitHub state only. Nothing to commit.

**Interfaces:**
- Consumes: nothing.
- Produces: labels `epic`, `adr`, `log`, `plan`, `idea` in `MatthieuGagne/nuke-raiders-garage`, with colors and descriptions identical to the game repo's. Task 6's AC3 check reads them.

- [ ] **Step 1: Write the failing check — the label set, side by side**

Run this from anywhere. It prints one line per document label with the game repo's value and
this repo's value, and a verdict.

```sh
python - <<'PY'
import json, subprocess
DOC = ["prd", "epic", "adr", "log", "plan", "idea"]
def labels(repo):
    out = subprocess.run(["gh", "label", "list", "--repo", repo, "--limit", "100",
                          "--json", "name,color,description"],
                         capture_output=True, text=True, check=True).stdout
    return {l["name"]: (l["color"].lower(), l["description"]) for l in json.loads(out)}
game = labels("MatthieuGagne/gmb-nuke-raider")
here = labels("MatthieuGagne/nuke-raiders-garage")
ok = True
for name in DOC:
    g, h = game.get(name), here.get(name)
    verdict = "OK" if g == h else "MISMATCH" if h else "MISSING"
    ok &= verdict == "OK"
    print(f"{name:6} game={g}  here={h}  -> {verdict}")
print("ALL LABELS MATCH" if ok else "LABELS DO NOT MATCH")
PY
```

Expected right now: `prd` reads `OK`; `epic`, `adr`, `log`, `plan`, `idea` read `MISSING`; last
line is `LABELS DO NOT MATCH`.

- [ ] **Step 2: Create the five missing labels**

Colors and descriptions are copied verbatim from `gh label list --repo MatthieuGagne/gmb-nuke-raider`
as read on 2026-08-21. If Step 1 printed a different game-repo value for any of these, use what
Step 1 printed — the game repo is the source of truth, not this plan.

```sh
gh label create epic --repo MatthieuGagne/nuke-raiders-garage \
  --color 3E4B9E --description "Master issue owning child specs"
gh label create adr  --repo MatthieuGagne/nuke-raiders-garage \
  --color 6f42c1 --description "Architecture decision record (accepted decision)"
gh label create log  --repo MatthieuGagne/nuke-raiders-garage \
  --color 5319E7 --description "Factory run dashboard issue"
gh label create plan --repo MatthieuGagne/nuke-raiders-garage \
  --color 1D76DB --description "Factory execution plan for one run"
gh label create idea --repo MatthieuGagne/nuke-raiders-garage \
  --color C2E0C6 --description "Uncommitted proposal; not yet a PRD"
```

If one already exists, `gh label create` fails with "label already exists" — that is not an error
to route around; re-run Step 1, and if it says `MISMATCH`, fix that one label with
`gh label edit <name> --repo MatthieuGagne/nuke-raiders-garage --color <c> --description "<d>"`.

- [ ] **Step 3: Re-run the check**

Run the Step 1 script again.
Expected: all six lines read `OK`, last line reads `ALL LABELS MATCH`.

- [ ] **Step 4: Apply the labels to the issues R2 names**

`epic` **in addition to** `prd` on the epic; `prd` on the six specs. `#25` already has `prd` and is
not in R2's list; leave it.

```sh
gh issue edit 1 --repo MatthieuGagne/nuke-raiders-garage --add-label epic --add-label prd
for n in 2 3 4 5 6 18; do
  gh issue edit $n --repo MatthieuGagne/nuke-raiders-garage --add-label prd
done
```

`#2 #3 #6 #18` are closed. `gh issue edit` labels a closed issue without reopening it — confirm in
Step 5 that all four are still `CLOSED`.

- [ ] **Step 5: Verify the application, and that nothing reopened**

```sh
gh issue list --repo MatthieuGagne/nuke-raiders-garage --state all --limit 100 \
  --json number,state,labels \
  --jq '.[] | select(.number | IN(1,2,3,4,5,6,18)) | "#\(.number) \(.state) [\([.labels[].name] | join(","))]"'
```

Expected, in some order:

```
#1 OPEN [epic,prd]
#2 CLOSED [prd]
#3 CLOSED [prd]
#4 OPEN [prd]
#5 OPEN [prd]
#6 CLOSED [prd]
#18 CLOSED [prd]
```

Label order within the brackets may differ. Any `OPEN` on #2 #3 #6 #18 means an edit reopened an
issue — close it again with `gh issue close <n> --repo MatthieuGagne/nuke-raiders-garage` and say
so in the task report.

- [ ] **Step 6: Nothing to commit — record the result**

This task changed no file. Do not create a commit. Report the Step 3 and Step 5 output verbatim.

---

## Task 2: Board membership and `Type` for the five missing issues (R3, AC1)

**Files:**
- Create (untracked, scratchpad only): `<scratchpad>/add_and_type.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: project-3 items for #6 #18 #19 #21 #23, each with `Type` and `Status` set. Task 6's AC1 check reads them, and Task 6 Step 5 re-runs the helper this task writes.

**What `Type` each issue gets, and why** — from the game repo's title-prefix table. `#6` and `#18`
are `PRD:`-titled, which predates the convention; they are specs, so `PRD`. The rest follow their
prefix directly.

| Issue | Title prefix | Type | State | Status |
|---|---|---|---|---|
| #6 | `PRD:` (legacy) | PRD | CLOSED | Done |
| #18 | `PRD:` (legacy) | PRD | CLOSED | Done |
| #19 | `fix:` | Bug | CLOSED | Done |
| #21 | `fix:` | Bug | CLOSED | Done |
| #23 | `chore:` | Chore | OPEN | Todo |

`Status` is not named by R3, which asks only for `Type`. It is set anyway because the convention
this issue adopts says every board item carries an explicit `Status` — `Type` says what a document
is, `Status` says where it is — and an item added with a blank `Status` lands in the board's
"No Status" lane, which is exactly the untidiness #25 exists to remove.

- [ ] **Step 1: Write the failing check — every garage issue, on the board, typed**

```sh
python - <<'PY'
import json, subprocess
def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True, check=True).stdout
issues = {i["number"]: i["state"] for i in json.loads(gh(
    "issue", "list", "--repo", "MatthieuGagne/nuke-raiders-garage",
    "--state", "all", "--limit", "100", "--json", "number,state"))}
board = {}
for it in json.loads(gh("project", "item-list", "3", "--owner", "MatthieuGagne",
                        "--limit", "300", "--format", "json"))["items"]:
    c = it.get("content", {})
    if "nuke-raiders-garage" in (c.get("repository") or ""):
        board[c["number"]] = (it.get("type", ""), it.get("status", ""))
bad = []
for n in sorted(issues):
    t, s = board.get(n, (None, None))
    if t is None:
        bad.append(f"#{n}: NOT ON BOARD")
    elif not t:
        bad.append(f"#{n}: BLANK TYPE")
    else:
        print(f"#{n:>3} {issues[n]:6} Type={t:5} Status={s}")
for line in bad:
    print(line)
print(f"{len(issues)} issues, {len(bad)} failing")
PY
```

Expected right now: `#6 #18 #19 #21 #23` print `NOT ON BOARD`, last line reads `18 issues, 5 failing`.
(18 is today's count; a garage issue filed since only raises it. Any *other* number failing is new
information — report it and stop rather than adding an issue this plan never scoped.)

- [ ] **Step 2: Write the helper**

Save as `<scratchpad>/add_and_type.py`. It resolves the field and option ids by name every call —
never hardcode them.

```python
"""Add one garage issue to project 3 and set Type and Status.

Usage: python add_and_type.py <issue#> <Type> <Status>
Throwaway: lives in the session scratchpad, never in the repo.
"""
import json
import subprocess
import sys

OWNER = "MatthieuGagne"
REPO = "MatthieuGagne/nuke-raiders-garage"
PROJECT_NUMBER = "3"
PROJECT_ID = "PVT_kwHOAv4a5M4BepB5"  # stable literal; field/option ids are not


def gh(*args):
    done = subprocess.run(["gh", *args], capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def field(name):
    data = json.loads(gh("project", "field-list", PROJECT_NUMBER,
                         "--owner", OWNER, "--format", "json"))
    for f in data["fields"]:
        if f["name"] == name:
            return f
    sys.exit(f"project {PROJECT_NUMBER} has no field named {name!r}")


def option_id(f, name):
    for o in f.get("options", []):
        if o["name"] == name:
            return o["id"]
    sys.exit(f"field {f['name']!r} has no option {name!r}")


def main():
    number, type_name, status_name = sys.argv[1], sys.argv[2], sys.argv[3]
    url = f"https://github.com/{REPO}/issues/{number}"
    item = json.loads(gh("project", "item-add", PROJECT_NUMBER,
                         "--owner", OWNER, "--url", url, "--format", "json"))
    item_id = item["id"]
    for field_name, chosen in (("Type", type_name), ("Status", status_name)):
        f = field(field_name)
        gh("project", "item-edit", "--project-id", PROJECT_ID, "--id", item_id,
           "--field-id", f["id"],
           "--single-select-option-id", option_id(f, chosen))
    print(f"#{number}: item={item_id} Type={type_name} Status={status_name}")


main()
```

- [ ] **Step 3: Run it once, on the open issue, and eyeball the board**

```sh
python <scratchpad>/add_and_type.py 23 Chore Todo
```

Expected: one line, `#23: item=PVTI_... Type=Chore Status=Todo`. Open
https://github.com/users/MatthieuGagne/projects/3 and confirm #23 shows `Chore` / `Todo` before
running the other four — a wrong option name would otherwise be applied five times.

- [ ] **Step 4: Run it for the four closed issues**

```sh
python <scratchpad>/add_and_type.py 6  PRD Done
python <scratchpad>/add_and_type.py 18 PRD Done
python <scratchpad>/add_and_type.py 19 Bug Done
python <scratchpad>/add_and_type.py 21 Bug Done
```

- [ ] **Step 5: Re-run the check**

Run the Step 1 script again.
Expected: every issue prints a `Type=` line, no `NOT ON BOARD` and no `BLANK TYPE`, last line reads
`18 issues, 0 failing`.

- [ ] **Step 6: Confirm the four closed issues are still closed**

```sh
gh issue list --repo MatthieuGagne/nuke-raiders-garage --state all --limit 100 \
  --json number,state --jq '.[] | select(.number | IN(6,18,19,21,23)) | "#\(.number) \(.state)"'
```

Expected: `#6 CLOSED`, `#18 CLOSED`, `#19 CLOSED`, `#21 CLOSED`, `#23 OPEN`.

- [ ] **Step 7: Nothing to commit**

The helper stays in the scratchpad. Do not add it to the repo, and do not create a commit. Report
where you saved it — Task 6 Step 5 runs it again.

---

## Task 3: Wire #2 #3 #4 #5 as native sub-issues of epic #1 (R4, AC2)

**Files:** none — GitHub state only. Nothing to commit.

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: four sub-issue edges under #1, so the board's `Parent issue` field populates. Task 6's AC2 check reads `sub_issues_summary.total`.

A body reference such as "Child specs: #2" is **not** sufficient — the board groups on the
`Parent issue` field, and only native wiring populates it.

- [ ] **Step 1: Write the failing check**

```sh
gh api repos/MatthieuGagne/nuke-raiders-garage/issues/1 \
  --jq '{total: .sub_issues_summary.total, completed: .sub_issues_summary.completed}'
gh api repos/MatthieuGagne/nuke-raiders-garage/issues/1/sub_issues \
  --jq '[.[] | .number] | sort'
```

Expected right now: `{"total":0,"completed":0}` and `[]`.

- [ ] **Step 2: Read each child's numeric REST id**

The API wants the child's `id`, not its number and not its `node_id`. Read it from the child's own
repo; POST to the epic's repo.

```sh
for n in 2 3 4 5; do
  echo "#$n id=$(gh api repos/MatthieuGagne/nuke-raiders-garage/issues/$n --jq .id)"
done
```

Expected, as read on 2026-08-21: `#2 id=5075964400`, `#3 id=5075964484`, `#4 id=5075964568`,
`#5 id=5075964654`. A REST `id` never changes, so a different value means the wrong repo or the
wrong issue was read — stop and report rather than POSTing it.

- [ ] **Step 3: POST the four edges**

```sh
for n in 2 3 4 5; do
  child_id=$(gh api repos/MatthieuGagne/nuke-raiders-garage/issues/$n --jq .id)
  gh api -X POST repos/MatthieuGagne/nuke-raiders-garage/issues/1/sub_issues \
    -F sub_issue_id=$child_id --jq '"#\(.number) wired"'
done
```

Expected: four lines, `#2 wired` … `#5 wired`. A `422` means that child already has a parent — do
not force it; report which one and stop.

- [ ] **Step 4: Re-run the check**

Run both Step 1 commands again.
Expected: `{"total":4,"completed":2}` — #2 and #3 are closed, so `completed` reads 2; AC2 pins
`total`, not `completed` — and `[2,3,4,5]`.

- [ ] **Step 5: Confirm the board's `Parent issue` field populated**

```sh
gh issue view 2 --repo MatthieuGagne/nuke-raiders-garage --json number,parent \
  --jq '"#\(.number) parent=#\(.parent.number // "NONE")"'
```

Expected: `#2 parent=#1`. This is the field the Epics view groups on; if it reads `NONE` the edge
did not take, whatever Step 4 said.

- [ ] **Step 6: Nothing to commit**

This task changed no file. Do not create a commit.

---

## Task 4: `CLAUDE.md` and the test that pins it (R1, AC4)

**Files:**
- Create: `CLAUDE.md`
- Create: `tests/test_docs_conventions.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–3 (it can be done first or last).
- Produces: the tracked-file half of #25, and the only commit and pull request this plan makes. Task 6's AC4 check runs its test.

- [ ] **Step 1: Branch**

From the repo root `C:\Code\nuke-raider-garage`, with a clean tree on `main`:

```sh
git checkout -b feat/shared-document-conventions
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_docs_conventions.py`:

```python
"""CLAUDE.md carries the shared-board conventions (#25 R1 / AC4).

No Qt import and no game-repo binding: this file runs under the default
`make test` target, which must pass with PySide6 absent.
"""
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

GAME_CLAUDE_MD_URL = (
    "https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md"
)

# One entry per operational must R1 enumerates. Each value is the shortest
# string that cannot land in the file by accident.
REQUIRED = {
    "title prefix feat": "`feat:`",
    "title prefix fix": "`fix:`",
    "title prefix bug": "`bug:`",
    "title prefix chore": "`chore:`",
    "title prefix docs": "`docs:`",
    "board field Type": "`Type`",
    "board field Status": "`Status`",
    "the shared board id": "PVT_kwHOAv4a5M4BepB5",
    "label prd": "`prd`",
    "label epic": "`epic`",
    "label adr": "`adr`",
    "label log": "`log`",
    "label plan": "`plan`",
    "label idea": "`idea`",
    "native sub-issue wiring": "sub_issues",
    "routing rule": "whose tracked files it changes",
}


class TestIssuesAndDocumentsSection(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            CLAUDE_MD.is_file(), "CLAUDE.md is missing from the repository root"
        )
        self.text = CLAUDE_MD.read_text(encoding="utf-8")

    def test_has_the_issues_and_documents_heading(self):
        self.assertIn("## Issues & documents", self.text)

    def test_names_the_game_repos_claude_md_as_canonical(self):
        self.assertIn(GAME_CLAUDE_MD_URL, self.text)

    def test_restates_every_operational_must(self):
        for must, needle in REQUIRED.items():
            with self.subTest(must=must):
                self.assertIn(needle, self.text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it to verify it fails**

```sh
python -m unittest tests.test_docs_conventions -v
```

Expected: FAIL — three errors, each raised from `setUp`, reading
`AssertionError: False is not true : CLAUDE.md is missing from the repository root`.

- [ ] **Step 4: Write `CLAUDE.md`**

Create `CLAUDE.md` at the repo root with exactly this content. The em dashes and the `&` in the
heading are intentional; write the file as UTF-8.

````markdown
# CLAUDE.md

Garage — the Windows desktop tool for tuning Nuke Raider's parameters and managing its assets.
The application lives in `tools/garage/`; `garage/` holds the interactive prototype it was
designed from, published via GitHub Pages.

## Issues & documents

**The conventions for issues, labels, the board and ADRs are canonical in the game repository's
`CLAUDE.md`** — https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md, the
"Workflow" section. They govern **both** repositories: a convention written there is not a
game-repo convention, it is the convention. What follows restates the operational musts so a
session working here can file an issue correctly without fetching that file. Where the two
disagree, the game repository wins — fix this file rather than following it.

**Routing.** An issue is filed in the repo whose tracked files it changes — the game ROM, its
assets and its tooling in `gmb-nuke-raider`; the Garage desktop tool here. Work that spans both
becomes **one issue per repo**, cross-linked in each body, never one issue whose implementation
edits two repos. Both halves go on the board, because the board is what makes the pair legible.

**Specs live in GitHub issues, never in this tree.** No PRD, no design doc and no ADR is
versioned here. The implementation plans under `docs/superpowers/plans/` are the one exception,
and they are execution artifacts, not specs.

**Title prefixes.** `feat:` for a spec, `fix:` or `bug:` for a defect, `chore:` or `docs:` for
maintenance. The prefix is what decides `Type` on the board, so it is not decoration.

**Every issue joins the shared board when it is created, with `Type` and `Status` set** as two
explicit commands. Both repositories share one project — "Nuke Raider — Documents", project
number 3 under owner `MatthieuGagne`, id `PVT_kwHOAv4a5M4BepB5`. `Type` says what a document is;
`Status` says where it is: `Todo` at creation, `Done` when it closes.

| Title prefix | Type |
|---|---|
| `feat:` carrying the `epic` label | Epic |
| `feat:` | PRD |
| `fix:` / `bug:` | Bug |
| `docs:` / `chore:` / `refactor:` / `test:` | Chore |
| `ADR <work item#>:` | ADR |
| `run …` | Log |
| `plan: …` | Plan |
| `review:` | Review |
| `idea:` | Idea |

The project id above is a stable literal. **Field ids and single-select option ids are not** —
they are regenerated whenever an option set is edited. Resolve them by name, at the moment of
use, from `gh project field-list 3 --owner MatthieuGagne --format json`. Board *views* are
UI-only; there is no API that creates one.

**Labels mark document kinds.** `prd`, `epic`, `adr`, `log`, `plan` and `idea` exist here with
the same colors and descriptions as in the game repository. A `fix:`, `bug:`, `docs:` or
`chore:` issue carries no kind label — its kind is expressed on the board through `Type`. An
epic carries `epic` **in addition to** `prd`, and takes `Type = Epic`.

**An epic's children are wired as native sub-issues**, not by a line in the body. The board's
Epics view groups on the `Parent issue` field, and only native wiring populates it. The API
takes the child's numeric REST `id` — not its `node_id`, not its issue number — read from the
child's own repository, and POSTed to the epic's. It works cross-repo under one owner:

```sh
child_id=$(gh api repos/MatthieuGagne/nuke-raiders-garage/issues/<child> --jq .id)
gh api -X POST repos/MatthieuGagne/nuke-raiders-garage/issues/<parent>/sub_issues \
  -F sub_issue_id=$child_id
```

**Decisions are ADRs** filed as `adr`-labeled issues, keyed by the issue number of the work item
being worked when the decision was taken, one ADR per work item, each decision a `### Dn` inside
it. Key resolution, lifecycle and citation form are in the game repository's `CLAUDE.md`; do not
re-derive them here.
````

- [ ] **Step 5: Run the test to verify it passes**

```sh
python -m unittest tests.test_docs_conventions -v
```

Expected: PASS, 3 tests, `OK`.

- [ ] **Step 6: Run the full default suite**

```sh
make test
```

Expected: `OK`, with the test count three higher than before. `make test-garage` is **not** run —
this task touches no Qt code, and that suite takes about twelve minutes.

- [ ] **Step 7: Commit**

```sh
git add CLAUDE.md tests/test_docs_conventions.py
git commit -m "docs: adopt the shared document conventions in CLAUDE.md (#25)"
```

Write the body before the trailer, explaining that the file did not exist and now carries one
section — the pointer at the game repo's `CLAUDE.md` plus the musts a session here needs — and
that `tests/test_docs_conventions.py` pins its content so the section cannot be silently dropped.
End with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

- [ ] **Step 8: Push and open the pull request**

```sh
git push -u origin feat/shared-document-conventions
```

Write the PR body to `<scratchpad>/pr-body.md` — PowerShell flattens a multi-line `--body` to one
line — with exactly this content:

```markdown
Part of #25 (R1, AC4).

`CLAUDE.md` did not exist in this repository. It does now, carrying one section,
"Issues & documents": the game repository's `CLAUDE.md` named as canonical for both repos,
plus the operational musts restated so a session working only in this clone can file an issue
correctly without fetching that file — the routing rule, the title prefixes, the shared board
and its `Type`/`Status` table, the document label set, and native sub-issue wiring for an
epic's children.

`tests/test_docs_conventions.py` pins that content: the heading, the canonical URL, and one
assertion per must R1 enumerates. It runs under the default `make test` target — no Qt import,
no game-repo binding — so the section cannot be silently dropped later.

The issue's other three criteria are GitHub state, not a diff, and were applied outside this
pull request: the six document labels and their application (AC3), project-3 membership and
`Type` for #6 #18 #19 #21 #23 (AC1), and #2 #3 #4 #5 wired as native sub-issues of #1 (AC2).
#25 stays open until all four are verified together.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Note the deliberate absence of `close`/`fix`/`resolve` next to `#25`: GitHub's parser ignores
negation, and this PR cannot satisfy AC1–AC3 on its own. Task 6 closes the issue by hand.

```sh
gh pr create --repo MatthieuGagne/nuke-raiders-garage \
  --title "docs: adopt the shared document conventions in CLAUDE.md (#25)" \
  --body-file <scratchpad>/pr-body.md
```

---

## Task 5: Machine-local memory for garage sessions (spec Notes)

**Files:**
- Create, **outside the repository, after explicit approval**: `C:\Users\mathd\.claude\projects\C--Code-nuke-raider-garage\memory\project-shared-board-conventions.md`
- Modify, same directory: `MEMORY.md` — one index line.

**Interfaces:**
- Consumes: the facts established by Tasks 1–4.
- Produces: nothing any later task reads. No acceptance criterion depends on it.

**The path in the spec is wrong, and this is the "verified at execution" its Notes call for.**
The spec names `C--Code-nuke-raiders-garage` (with an `s`) and a filename
`project_shared_board_conventions.md`. The directory that actually exists on this machine is
`C:\Users\mathd\.claude\projects\C--Code-nuke-raider-garage\memory\` — it derives from the clone
path `C:\Code\nuke-raider-garage`, which has no `s`. It already holds `MEMORY.md` and three
memories, all named in kebab-case, so the new file is `project-shared-board-conventions.md` to
match its neighbours. Confirm before writing:

```sh
ls "C:/Users/mathd/.claude/projects/C--Code-nuke-raider-garage/memory/"
```

Expected: `MEMORY.md`, `commit-after-each-confirmed-iteration.md`,
`garage-panel-suite-runs-twelve-minutes.md`, `garage-specs-live-in-github-issues.md`.

- [ ] **Step 1: Check the memory is not already there**

```sh
grep -ril "board 3\|shared board\|documents" \
  "C:/Users/mathd/.claude/projects/C--Code-nuke-raider-garage/memory/"
```

Expected: at most `garage-specs-live-in-github-issues.md`. If a memory already covers the shared
board, **update that file instead of adding a second** and say so in the task report.

- [ ] **Step 2: Draft the memory and show it to the user — do not write it yet**

The user's standing rule is that memory files are drafted, shown, and written only after explicit
approval. Present this content in the response and stop for approval:

```markdown
---
name: project-shared-board-conventions
description: Where Nuke Raider issue conventions live, and that the garage repo shares one GitHub project board with the game repo — labels, Type/Status, sub-issues, project 3
metadata:
  type: project
---

`nuke-raiders-garage` and `gmb-nuke-raider` share one GitHub project — "Nuke Raider —
Documents", project number 3 under owner `MatthieuGagne`, id `PVT_kwHOAv4a5M4BepB5`. The
conventions for both are canonical in the **game** repo's `CLAUDE.md`
(https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md, "Workflow"), restated
for this repo in its own `CLAUDE.md`. Adopted here by
MatthieuGagne/nuke-raiders-garage#25 on 2026-08-21.

**Why:** a session working only in the garage clone sees no game repo, and would otherwise file
an untyped, unlabelled issue on no board — which is the mess #25 existed to clear.

**How to apply:** file an issue in the repo whose tracked files it changes, cross-linking a
one-issue-per-repo pair when the work spans both; add it to project 3 with `Type` (from the
title prefix) and `Status` set as explicit commands; label document kinds only (`prd`, `epic`,
`adr`, `log`, `plan`, `idea`) and leave `fix:`/`chore:` unlabelled; wire an epic's children as
native sub-issues by POSTing the child's numeric REST `id` to the parent's `/sub_issues`.
Resolve project field and option ids **by name** every time — they regenerate when an option set
is edited; only the project id is stable. Board views are UI-only and cannot be created through
the API. See [[garage-specs-live-in-github-issues]].

The spec's claim that `gh issue view` needs explicit `--json` fields to dodge a `projectCards`
GraphQL error did **not** reproduce on gh 2.96.0 (checked 2026-08-21): the bare command prints
the project row fine. Re-check if a future gh regresses it.
```

- [ ] **Step 3: After approval, write the file**

Write the approved content to
`C:\Users\mathd\.claude\projects\C--Code-nuke-raider-garage\memory\project-shared-board-conventions.md`.
If approval is withheld, skip Steps 3–4 and record that in the task report.

- [ ] **Step 4: Add the index line to `MEMORY.md`**

Append one line to
`C:\Users\mathd\.claude\projects\C--Code-nuke-raider-garage\memory\MEMORY.md`, matching the
existing format exactly:

```
- [Both repos share one document board](project-shared-board-conventions.md) — project 3, conventions canonical in the game repo's CLAUDE.md, and the field-ids-by-name rule
```

Verify with:

```sh
cat "C:/Users/mathd/.claude/projects/C--Code-nuke-raider-garage/memory/MEMORY.md"
```

Expected: four bullets, the new one last. A memory missing from `MEMORY.md` is unreviewable.

- [ ] **Step 5: Nothing to commit**

This file is outside the repository. Do not `git add` it, and do not create a commit.

---

## Task 6: Verify all four acceptance criteria and close #25

**Files:** none.

**Interfaces:**
- Consumes: everything Tasks 1–4 produced, and Task 2's `<scratchpad>/add_and_type.py`.
- Produces: the evidence that closes #25.

- [ ] **Step 1: Run the whole acceptance check in one pass**

Run from the repo root, on the branch (or on `main` after the PR merges) so `CLAUDE.md` exists.

```sh
python - <<'PY'
import json, subprocess, sys
from pathlib import Path

REPO = "MatthieuGagne/nuke-raiders-garage"
GAME = "MatthieuGagne/gmb-nuke-raider"
DOC = ["prd", "epic", "adr", "log", "plan", "idea"]

def gh(*a):
    return subprocess.run(["gh", *a], capture_output=True, text=True, check=True).stdout

fails = []

# AC1 -- every garage issue on project 3 with a non-blank Type
issues = {i["number"]: i for i in json.loads(gh(
    "issue", "list", "--repo", REPO, "--state", "all", "--limit", "100",
    "--json", "number,state,labels"))}
board = {}
for it in json.loads(gh("project", "item-list", "3", "--owner", "MatthieuGagne",
                        "--limit", "300", "--format", "json"))["items"]:
    c = it.get("content", {})
    if "nuke-raiders-garage" in (c.get("repository") or ""):
        board[c["number"]] = it.get("type", "")
missing = [n for n in issues if not board.get(n)]
print(f"AC1: {len(issues)} garage issues, {len(issues) - len(missing)} on board with a Type")
if missing:
    fails.append(f"AC1: untyped or off-board: {sorted(missing)}")

# AC2 -- the epic owns four native sub-issues
total = int(gh("api", f"repos/{REPO}/issues/1",
               "--jq", ".sub_issues_summary.total").strip())
print(f"AC2: #1 sub_issues_summary.total = {total}")
if total != 4:
    fails.append(f"AC2: total is {total}, expected 4")

# AC3 -- labels exist, mirror the game repo, and are applied
def labels(repo):
    return {l["name"]: (l["color"].lower(), l["description"])
            for l in json.loads(gh("label", "list", "--repo", repo, "--limit", "100",
                                   "--json", "name,color,description"))}
game, here = labels(GAME), labels(REPO)
for name in DOC:
    if here.get(name) != game.get(name):
        fails.append(f"AC3: label {name}: here={here.get(name)} game={game.get(name)}")
want = {1: {"epic", "prd"}, 2: {"prd"}, 3: {"prd"}, 4: {"prd"},
        5: {"prd"}, 6: {"prd"}, 18: {"prd"}}
for n, expected in want.items():
    got = {l["name"] for l in issues[n]["labels"]}
    if not expected <= got:
        fails.append(f"AC3: #{n} has {sorted(got)}, needs {sorted(expected)}")
print(f"AC3: {len(DOC)} labels compared, {len(want)} issues checked")

# AC4 -- CLAUDE.md carries the section
text = Path("CLAUDE.md").read_text(encoding="utf-8")
for needle in ("## Issues & documents",
               "https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md",
               "PVT_kwHOAv4a5M4BepB5", "sub_issues",
               "whose tracked files it changes"):
    if needle not in text:
        fails.append(f"AC4: CLAUDE.md is missing {needle!r}")
print(f"AC4: CLAUDE.md is {len(text)} characters")

print()
for f in fails:
    print("FAIL", f)
print("ALL FOUR ACCEPTANCE CRITERIA MET" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
PY
```

Expected: no `FAIL` lines, last line `ALL FOUR ACCEPTANCE CRITERIA MET`.

- [ ] **Step 2: Run the default suite on the merge result**

```sh
make test
```

Expected: `OK`.

- [ ] **Step 3: Merge the pull request and clean up**

Merge Task 4's PR once it is approved, then, from the main repo root:

```sh
git checkout main && git pull --ff-only
git branch -d feat/shared-document-conventions
```

- [ ] **Step 4: Close #25 with the evidence**

Only after Step 1 printed `ALL FOUR ACCEPTANCE CRITERIA MET`. Write the comment to
`<scratchpad>/close-25.md` and use `--body-file`; a multi-line body passed inline is flattened by
PowerShell. Fill the bracketed values from Step 1's actual output — do not copy the numbers below
without checking them.

```markdown
All four criteria verified against the API, not asserted.

**AC1** — [N] garage issues exist; every one is on project 3 with a non-blank `Type`.
#6 and #18 came in as `PRD`, #19 and #21 as `Bug`, #23 as `Chore`; the rest were already typed.
Each also carries an explicit `Status` (`Done` for the closed ones, `Todo` for #23), because a
blank `Status` lands an item in the board's No Status lane.

**AC2** — `sub_issues_summary.total` on #1 reads 4, with #2 #3 #4 #5 wired natively. #2's
`parent` field reads #1, so the Epics view groups them.

**AC3** — `prd`, `epic`, `adr`, `log`, `plan` and `idea` exist here with the same colors and
descriptions as in `gmb-nuke-raider`, compared field by field. Applied: `epic` + `prd` on #1,
`prd` on #2 #3 #4 #5 #6 #18. The four closed issues among them are still closed.

**AC4** — `CLAUDE.md` carries the "Issues & documents" section, added by PR #[PR]. The file did
not previously exist. `tests/test_docs_conventions.py` pins the heading, the canonical URL and
every must R1 enumerates, under the default `make test` target.

**Two places reality differed from this spec.** The issue count reads [N], not 15 — #26 and #28
were filed after this spec was written, and both were already on the board and typed, so the
check was run as "every garage issue" rather than a fixed fifteen. And the machine-local memory
directory is `C--Code-nuke-raider-garage`, not `C--Code-nuke-raiders-garage`: it derives from the
clone path `C:\Code\nuke-raider-garage`, which has no `s`. The Notes anticipated this by asking
for the path to be verified at execution.

**One Note did not reproduce.** `gh issue view` needing explicit `--json` fields to dodge a
`projectCards` GraphQL error does not happen on gh 2.96.0 — the bare command prints the project
row. That claim was therefore left out of `CLAUDE.md` and recorded as version-dependent in the
machine-local memory instead.
```

```sh
gh issue comment 25 --repo MatthieuGagne/nuke-raiders-garage \
  --body-file <scratchpad>/close-25.md
gh issue close 25 --repo MatthieuGagne/nuke-raiders-garage
```

- [ ] **Step 5: Set #25's board `Status` to `Done`**

Closing an issue does not move its board `Status`. Reuse Task 2's helper — `gh project item-add`
returns the existing item id when the issue is already on the board:

```sh
python <scratchpad>/add_and_type.py 25 PRD Done
```

Verify:

```sh
gh issue view 25 --repo MatthieuGagne/nuke-raiders-garage --json number,state \
  --jq '"#\(.number) \(.state)"'
```

Expected: `#25 CLOSED`, and the board shows `PRD` / `Done` for it.

---

## Notes for whoever executes this

- **Tasks 1, 2, 3 and 4 are independent of each other.** Only Task 6 depends on all of them. If
  they are dispatched in parallel, Task 2's helper script is the one shared artifact — Task 6
  Step 5 runs it again, so Task 2 must report where it saved it.
- **Tasks 1, 2, 3 and 5 create no commit.** Four of the five deliverables are GitHub state. A task
  report claiming a commit for one of those means something was written that should not have been.
- **The board is shared with the game repo's ~276 items.** Every command in this plan filters on
  `nuke-raiders-garage`. A command that does not is a command that can retype a game-repo issue.
