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
| `make test-garage` | `tests/garage/` — the Qt panels | 225 | **~12 min** | PySide6 |
| `make lint` | the `tunables.json` ↔ `src/config.h` drift check on its own | — | seconds | stdlib only |

**Pick the target by what you changed.** A change under `tools/garage/core/` is covered by
`make test`. A change under `tools/garage/panels/`, `tools/garage/theme/` or `app.py` is covered
only by `make test-garage` — `make test` goes green without having run a line of it. Changed both:
run both.

- `make test` **must keep passing with PySide6 absent.** No file under `tests/` may import Qt.
  Discovery never reaches `tests/garage/` because that directory has no `__init__.py`; the omission
  is load-bearing, not an oversight. `.github/workflows/test.yml` runs the suite on Windows and
  Linux with nothing installed, which is what proves it.
- `make test-garage` is silent for twelve minutes. Size any timeout to that figure, not to the
  ~2.5 minutes the same suite takes on CI. A quiet run is not a hung one.
- Without `make`, the two suites run directly — this is the form both workflows use:

```
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s tests/garage -p 'test_*.py'
```

Run the application from the repository root: `garage.bat`, or `python -m tools.garage`.
