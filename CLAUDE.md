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
