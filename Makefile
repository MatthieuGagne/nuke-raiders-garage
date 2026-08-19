.PHONY: test test-garage lint

# Default suite: covers tools/garage/core/. Must pass with PySide6 absent
# (AC15) -- tests/garage/ has no __init__.py, so discovery never reaches it.
# The tests that read the game repository's src/config.h skip when no game
# repository is bound, which is the CI case; the drift check itself is part
# of this target (tests/test_garage_lint.py).
test:
	python -m unittest discover -s tests -p 'test_*.py'

# Panel coverage. Needs PySide6 (AC16).
test-garage:
	python -m unittest discover -s tests/garage -p 'test_*.py'

# The drift check on its own (R8/AC9 and #18 R3): is every #define in the
# game repository's src/config.h classified in tunables.json, does every
# tunables.json entry still exist in the header, and does every tunable
# the header range-guards with an #if declare that same range? `make test`
# fails on the same drift; this prints the names without running the
# suite, and exits 0 with an explanation when no game repository is bound.
lint:
	python tools/garage_lint.py
