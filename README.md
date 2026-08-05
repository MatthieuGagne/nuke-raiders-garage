# nuke-raider-prototypes

Interactive UI prototypes for [Nuke Raider](https://github.com/MatthieuGagne/gmb-nuke-raider)
developer tooling, published via GitHub Pages and linked from the PRD issues they belong to.

**Live:** https://matthieugagne.github.io/nuke-raider-prototypes/

They live outside the game repo on purpose: `gmb-nuke-raider` keeps design artifacts in GitHub
issues, not in the tree.

## Prototypes

| Path | Prototype | Covers |
|---|---|---|
| [`garage/`](garage/) | **Garage** — parameter tuning and asset management | P1 tuner / worktrees / doctor, P2 assets, P3 dialog |

## What these are

Static mockups. Controls demonstrate intended behaviour; nothing reads or writes a repository.
Values shown are real — parameters from `src/config.h`, checkouts from `git worktree list`,
budgets from a `tools/memory_check.py` run — so the screens can be judged against the real
project rather than invented data. Asset thumbnails are generated placeholders in the 4-shade
DMG palette, not the project's sprite art.

Each prototype is a single self-contained HTML file: no build step, no dependencies. Open it
locally or edit and push.
