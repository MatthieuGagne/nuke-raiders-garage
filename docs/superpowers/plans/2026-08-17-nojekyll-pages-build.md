# `.nojekyll` — Unbreak the GitHub Pages Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `pages build and deployment` from failing on every commit to `main`, permanently, by taking Jekyll out of the loop.

**Architecture:** This repository publishes two hand-written static HTML pages and nothing else, but GitHub Pages runs it through Jekyll, which pre-processes *every* `.md` file in the repo with Liquid — including plan documents under `docs/` that contain `{`-brace pairs inside code fences. A single empty file, `.nojekyll`, at the root of the publishing source switches Pages to a plain static serve: the HTML is copied verbatim, no `.md` file is ever parsed, and this class of failure cannot recur. There is no code to write and no test suite to extend; the deliverable is the file plus **evidence from the live site** that the deploy actually happened.

**Tech Stack:** GitHub Pages (legacy branch build, `jekyll 3.10.0`), `gh` CLI, `git`, PowerShell 7 on Windows.

**Spec:** https://github.com/MatthieuGagne/nuke-raiders-garage/issues/16 (read it in full before Task 1 — the "alternatives, and why not" section is the reasoning behind the one-line change and pre-empts the obvious review question)

## Global Constraints

- **The file is exactly `.nojekyll`, at the repository root, and empty (0 bytes).** Not `.nojekyll.txt`, not in `docs/`, not in `garage/`. GitHub only honours it at the root of the publishing source, which the Pages API reports as `{branch: main, path: /}`.
- **No source file and no test changes.** The spec says so explicitly. Do not "while I'm here" edit `index.html`, `garage/index.html`, the two existing plan docs, the Makefile, or any test. Do not add `_config.yml`, do not add `{% raw %}` guards, do not add front matter.
- **Never commit a new `.md` file to `main` before `.nojekyll` is on `main`.** Any Markdown containing a `{`-brace pair inside a code fence — including *this* plan document — is a live grenade until Jekyll is off. Task 1 commits `.nojekyll` and this plan doc **together in one commit**, `.nojekyll` staged first.
- **Pages builds only from `main`.** A branch build never runs, so the green build in Task 2 is observable *only after the PR merges*. Do not attempt to verify the fix from a feature branch, and do not report the fix as working until Task 2's evidence is in hand.
- **PowerShell syntax throughout.** `2>$null` not `2>/dev/null`, `$env:VAR` not `export`, backtick for line continuation.
- **Repo convention: land through a PR.** Recent history is merge commits from short-lived `fix/*` branches (`fix/asset-panel-lifecycle`, `fix/one-make-target-per-rule`). Follow it.
- **Never read `$LASTEXITCODE` after a piped command** — the pipe masks it. Run the command bare, check the code on the next line.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `.nojekyll` | **Create** (empty, repo root) | The whole fix. Its presence tells GitHub Pages to skip the Jekyll build step and serve the branch contents as static files. |
| `docs/superpowers/plans/2026-08-17-nojekyll-pages-build.md` | **Create** (this file) | The plan record, committed alongside the fix — and itself an instance of the file class that broke the build, which is why its commit is ordered after `.nojekyll` in the same commit. |

Nothing else is touched. There is no `_config.yml` in this repository and none is being added.

---

### Task 1: Add `.nojekyll` and land it on `main`

**Files:**
- Create: `.nojekyll` (repository root, empty)
- Create: `docs/superpowers/plans/2026-08-17-nojekyll-pages-build.md` (this plan; already written — commit it, don't rewrite it)
- Test: none. This repository's suites (`tests/`) cover the Garage tooling; a Pages deploy has no unit-testable surface. The verification is Task 2, run against the live site.

**Interfaces:**
- Consumes: nothing.
- Produces: a merge commit on `main` whose tree contains a root-level `.nojekyll`. Task 2 verifies the Pages build for that commit. Task 2 needs the merge commit's short SHA — capture it in Step 9.

- [ ] **Step 1: Record the red baseline**

Before changing anything, capture the failure you are fixing, so the after-state has a before-state to be compared against.

```powershell
gh run list --repo MatthieuGagne/nuke-raiders-garage --workflow "pages-build-deployment" --limit 5
gh api repos/MatthieuGagne/nuke-raiders-garage/pages | ConvertFrom-Json | Select-Object status, build_type, source
```

Expected — the four most recent runs are `failure`, and the API reports:

```
status     : errored
build_type : legacy
source     : @{branch=main; path=/}
```

If `build_type` is **not** `legacy` (i.e. it says `workflow`), STOP and report: the site is built by GitHub Actions rather than the branch-Jekyll path, `.nojekyll` is not the right lever, and the spec's premise needs revisiting with the user.

- [ ] **Step 2: Read the exact Liquid error once**

```powershell
gh run view 32081291176 --repo MatthieuGagne/nuke-raiders-garage --log-failed
```

Expected: a `Liquid syntax error` naming `2026-08-12-garage-p2-assets.md` and an unterminated `Variable` around line 2976. This confirms the diagnosis is about Markdown pre-processing, not about the HTML pages. (If the run's logs have expired, the spec quotes the error verbatim; move on.)

- [ ] **Step 3: Create the branch**

```powershell
git checkout main
git pull --ff-only
git checkout -b fix/nojekyll-pages-build
```

- [ ] **Step 4: Create the empty `.nojekyll`**

```powershell
New-Item -ItemType File -Path .nojekyll
```

Do **not** use `New-Item -Force` and do not write any content into it — GitHub checks only for the file's existence, and an empty file is the documented form.

- [ ] **Step 5: Verify the file is exactly what it must be**

```powershell
Get-Item .nojekyll -Force | Select-Object Name, Length, DirectoryName
```

Expected: `Name` is exactly `.nojekyll`, `Length` is `0`, and `DirectoryName` is the repository root (`C:\Code\nuke-raider-garage`). PowerShell hides dotfiles without `-Force`; that is why the flag is there. If `Length` is not 0 or the name picked up an extension, delete it (`Remove-Item .nojekyll -Force`) and redo Step 4.

- [ ] **Step 6: Stage `.nojekyll` first, then the plan doc**

Dotfiles are easy to miss with globs, so name the file explicitly. The order matters for the reason in Global Constraints: the Markdown must never reach `main` in a commit that does not already carry `.nojekyll`.

```powershell
git add .nojekyll
git add docs/superpowers/plans/2026-08-17-nojekyll-pages-build.md
git status --short
```

Expected: two lines, both `A` (added):

```
A  .nojekyll
A  docs/superpowers/plans/2026-08-17-nojekyll-pages-build.md
```

If `.nojekyll` is absent from that list, `git add` silently skipped it — check you are at the repository root and that no `.gitignore` rule matches (there is none today: `.gitignore` lists `garage.local.json`, `__pycache__/`, `*.pyc`, `.superpowers/`).

- [ ] **Step 7: Commit**

```powershell
git commit -m @'
fix: serve Pages statically so a doc's braces cannot break the build

GitHub Pages ran Jekyll over the whole repository, and Liquid parses
every .md file before Markdown does -- so an f-string inside a Python
code fence in the P2 plan doc read as an unterminated variable and
failed the build. Every commit to main has carried a red X since.

.nojekyll turns the site into a plain static serve. The two published
pages are hand-written HTML with no front matter and use no Jekyll
feature, so nothing is lost, and no future doc or README code block
can break a deploy again.

Closes #16
'@
```

The closing `'@` must sit at column 0 with no leading whitespace, or PowerShell throws a parse error.

- [ ] **Step 8: Push and open the PR**

```powershell
git push -u origin fix/nojekyll-pages-build
gh pr create --repo MatthieuGagne/nuke-raiders-garage --base main --title "fix: serve Pages statically so a doc's braces cannot break the build" --body-file docs/superpowers/plans/.pr-body.md
```

Write the body to `docs/superpowers/plans/.pr-body.md` first — PowerShell flattens multi-line strings passed inline to `gh` into a single line. Body content:

```markdown
`pages build and deployment` has failed on every commit to `main` since
2026-08-16. Jekyll pre-processes every `.md` file in the repo with Liquid,
and a Python f-string in `docs/superpowers/plans/2026-08-12-garage-p2-assets.md`
reads as an unterminated Liquid variable.

`.nojekyll` makes Pages serve the branch statically. Both published pages are
hand-written HTML without front matter, so Jekyll was doing nothing for this
repository except scanning documents it was never meant to publish.

Verification is post-merge (Pages only builds `main`): the build goes green and
both pages still serve. See #16 for the alternatives considered.

Closes #16
```

Delete the body file after the PR is created (`Remove-Item docs/superpowers/plans/.pr-body.md`) — it is scratch, not a plan artifact. Do not commit it.

- [ ] **Step 9: Merge, and capture the merge SHA**

Merging is the user's call — ask before running this if you do not have standing approval to merge.

```powershell
gh pr merge --repo MatthieuGagne/nuke-raiders-garage --merge
git checkout main
git pull --ff-only
git log -1 --format="%h %s"
```

Record the short SHA from the last line. Task 2 checks that *this* commit is the one Pages built.

---

### Task 2: Verify the live site, not just the build

**Files:** none created or modified. This task produces evidence.

**Interfaces:**
- Consumes: the merge commit SHA from Task 1, Step 9.
- Produces: a pass/fail verdict backed by command output. Nothing downstream depends on it.

The spec is pointed about this: *"A change visible in the prototype, deployed and seen live, is the real check — the build going green only proves the build."* `.nojekyll` is invisible by design, so the substitute for a visible change is proving the **deployed commit SHA** matches the merge commit — that is what rules out "green build, stale deploy".

- [ ] **Step 1: Wait for the run, then check it went green**

```powershell
gh run list --repo MatthieuGagne/nuke-raiders-garage --workflow "pages-build-deployment" --limit 3
```

Expected: the newest run is `completed  success` on `main`, timestamped after the merge. Historical runs take 25–55s; if it is still `in_progress`, wait ~30s and re-run the command. If it is still queued after ~5 minutes, report that rather than re-running in a loop.

Expected failure mode if `.nojekyll` did not land at the root: an identical `Liquid syntax error`. That means the file is misplaced or was not committed — go back to Task 1, Step 5.

- [ ] **Step 2: Confirm Pages itself reports built, and for the right commit**

```powershell
gh api repos/MatthieuGagne/nuke-raiders-garage/pages/builds/latest | ConvertFrom-Json | Select-Object status, @{n='sha';e={$_.commit.Substring(0,7)}}, created_at, @{n='error';e={$_.error.message}} | Format-List
```

Expected: `status : built`, `error` empty, and `sha` equal to the merge SHA recorded in Task 1, Step 9. A `built` status with an older SHA means the deploy did not pick up the merge — do not report success; re-check Step 1 for a newer run.

- [ ] **Step 3: Confirm both pages still serve, with real content**

```powershell
$root = Invoke-WebRequest -Uri "https://matthieugagne.github.io/nuke-raiders-garage/" -UseBasicParsing
$garage = Invoke-WebRequest -Uri "https://matthieugagne.github.io/nuke-raiders-garage/garage/" -UseBasicParsing
"root:   $($root.StatusCode)  $($root.RawContentLength) bytes"
"garage: $($garage.StatusCode)  $($garage.RawContentLength) bytes"
```

Expected: both `200`. `garage/index.html` is 58,507 bytes in the working tree and `index.html` is 5,525 — the served sizes should be in that neighbourhood. A 200 with a few hundred bytes is GitHub's 404 page and is a **failure**, not a pass.

Append a cache-buster (`?v=1`) if you suspect a stale CDN copy; do not conclude "deployed" from a cached response.

- [ ] **Step 4: Confirm the served HTML is the file, byte-identical**

This is the check that proves static serving actually happened — under Jekyll the HTML could have been rewritten; under `.nojekyll` it must be copied verbatim.

```powershell
$local = (Get-FileHash garage/index.html -Algorithm SHA256).Hash
$tmp = Join-Path $env:TEMP "garage-live.html"
Invoke-WebRequest -Uri "https://matthieugagne.github.io/nuke-raiders-garage/garage/index.html" -OutFile $tmp -UseBasicParsing
$live = (Get-FileHash $tmp -Algorithm SHA256).Hash
"local: $local"
"live:  $live"
"match: $($local -eq $live)"
Remove-Item $tmp
```

Expected: `match: True`. If it is `False`, compare byte counts — a difference of a few bytes is a line-ending artifact of the download and is acceptable to note; a large difference means the deployed page is not the current file, which is a failure to report.

- [ ] **Step 5: Confirm the issue closed and report**

```powershell
gh issue view 16 --repo MatthieuGagne/nuke-raiders-garage --json state,stateReason
```

Expected: `CLOSED` / `COMPLETED`, auto-closed by the `Closes #16` in the commit and PR body. If it is still `OPEN`, close it manually with a comment linking the merge commit.

Report to the user with the evidence pasted, not summarised: the green run line, the `built` status with matching SHA, both status codes, and the hash match. State plainly that `.nojekyll` itself is not visually observable and that the SHA + hash match is what stands in for "seen live"; the next real content change to the prototype will be the first end-to-end visual confirmation.

- [ ] **Step 6: Clean up the branch**

```powershell
git checkout main
git pull --ff-only
git branch -d fix/nojekyll-pages-build
git push origin --delete fix/nojekyll-pages-build
```

Run this from the repository root. If a delete fails because a file is locked, find the holding process and report the exact command for the user rather than retrying blindly.

---

## Notes for the reviewer

- **Why not `_config.yml` with `exclude: [docs]`?** It fixes today's file and leaves the trap armed for the next Markdown file outside `docs/` — a README code block, for instance.
- **Why not `{% raw %}` around the offending block?** It edits a record of work already done to satisfy a template engine this repository does not use, and has to be repeated in every future document.
- **Why not `render_with_liquid: false`?** Jekyll 4.0+ only; GitHub Pages pins jekyll 3.10.0.
- **What is given up:** Markdown under `docs/` will no longer be served as HTML pages by the site. Nothing links to those files and they are read on GitHub, which renders them anyway.
