# CLAUDE.md

Garage — the Windows desktop tool for tuning Nuke Raider's parameters and managing its assets.
The application lives in `tools/garage/`; `garage/` holds the interactive prototype it was
designed from, published via GitHub Pages.

## Issues & documents

Issue, label, board and ADR conventions: use the **`file-an-issue`** skill. They are canonical in
the game repository's `CLAUDE.md` —
https://github.com/MatthieuGagne/gmb-nuke-raider/blob/master/CLAUDE.md, the "Workflow" section —
and govern **both** repositories. Where the two disagree, the game repository wins.

## Building, running & testing

Python 3.13, standard-library `unittest`, no build step. `pytest` is not used here and is not
installed. PySide6 is the only dependency, and it is what separates the two test targets.

| Command | Covers | Tests | Takes | Needs |
|---|---|---|---|---|
| `make test` | `tests/` — `tools/garage/core/`, the drift check, the docs guards | 339 | ~1 min | stdlib only |
| `make test-garage` | `tests/garage/` — the Qt panels | 225 | **3–13 min** | PySide6 |
| `make lint` | the `tunables.json` ↔ `src/config.h` drift check on its own | — | seconds | stdlib only |

**Pick the target by what you changed.** A change under `tools/garage/core/` is covered by
`make test`. A change under `tools/garage/panels/`, `tools/garage/theme/` or `app.py` is covered
only by `make test-garage` — `make test` goes green without having run a line of it. Changed both:
run both.

- `make test` **must keep passing with PySide6 absent.** No file under `tests/` may import Qt.
  Discovery never reaches `tests/garage/` because that directory has no `__init__.py`; the omission
  is load-bearing, not an oversight. `.github/workflows/test.yml` runs the suite on Windows and
  Linux with nothing installed, which is what proves it.
- `make test-garage` runs anywhere from 3 to 13 minutes: it spawns real subprocesses, so
  process-creation overhead (antivirus scanning above all) dominates, and the same suite on the
  same tree varies by machine and by day. Size any timeout to the high end. A quiet run is not a
  hung one.
- Without `make`, the two suites run directly — this is the form both workflows use:

```
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s tests/garage -p 'test_*.py'
```

Run the application from the repository root: `garage.bat`, or `python -m tools.garage`.

## Architecture

`tools/garage/` is layered so that everything worth testing can be tested without a display:

- **`core/`** holds the logic and **imports no Qt** — not one module. Everything here is pure: it
  shells out to `git` or `make`, parses files, returns data. This is the layer `make test` covers,
  and the reason that target can stay Qt-free. Behaviour that could live here belongs here.
- **`panels/`** holds the Qt widgets and stays thin — a panel wires a widget to `core/`, it does not
  reimplement it. Logic that lands here is reachable only by the slow suite.
- **`theme/`** is the single place a colour or a typeface may appear as a literal. Panels name a
  token (`TOKENS["accent"]`, `FONT_MONO`) or select on an object name or Qt dynamic property; no
  panel spells out a hex value or a font family, and none calls `setStyleSheet` to restyle itself.
  `theme.apply(app)` installs the stylesheet once, at startup.

Garage edits a **separate** checkout — the game repository is not this repository. It is resolved by
detection: a sibling `nuke-raider` directory, confirmed by its `origin` remote, with the choice
recorded in `garage.local.json` at this repository's root — gitignored, per-machine, never
committed. **No path into the game repository may be hardcoded.** Go through
`tools.garage.core.project`, whose `Binding` resolves them: `binding.config_h`, `binding.build_dir`,
`binding.resolve(...)`. A recorded binding that no longer resolves is reported as a failure, never
silently re-detected.

Anything that reads the game repository skips when none is bound. CI checks this repository out
alone, so a test that hard-fails on an unbound repository breaks the build.
