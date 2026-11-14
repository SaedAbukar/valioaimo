PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

run: build
	$(PY) -m gateway

test:
	$(PY) -m pytest -q tests

build:
	$(PY) scripts/record_replays.py && $(PY) ui/build.py

index:
	$(PY) scripts/build_aimo_index.py

mcp:
	$(PY) -m gateway.mcp_server

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
