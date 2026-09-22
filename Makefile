.PHONY: install test check demo run

install:
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest

check:
	ruff check app tests scripts
	python -m compileall -q app tests scripts
	python -m pytest

demo:
	python scripts/demo.py

run:
	uvicorn app.main:app --reload
