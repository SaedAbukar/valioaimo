.PHONY: run test build index mcp setup agent bench
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

run: build
	AIMO_DB=data/gateway.db $(PY) -m gateway

test:
	$(PY) -m pytest -q tests

build:
	$(PY) scripts/record_replays.py && $(PY) ui/build.py

index:
	$(PY) scripts/build_aimo_index.py

mcp:  # stdio proxy to the running gateway (make run); unset AIMO_GATEWAY_URL for an in-process gateway
	AIMO_GATEWAY_URL=http://127.0.0.1:8000 $(PY) -m gateway.mcp_server

setup:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

agent:
	$(PY) scripts/agent_demo.py && $(PY) scripts/agent_demo.py --over-limit

bench:  # needs `make run` in another terminal; writes docs/BENCH.md
	$(PY) scripts/agent_bench.py --agents 10
