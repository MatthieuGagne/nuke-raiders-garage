.PHONY: test test-garage

# Default suite: covers tools/garage/core/. Must pass with PySide6 absent
# (AC15) -- tests/garage/ has no __init__.py, so discovery never reaches it.
test:
	python -m unittest discover -s tests -p 'test_*.py'

# Panel coverage. Needs PySide6 (AC16).
test-garage:
	python -m unittest discover -s tests/garage -p 'test_*.py'
