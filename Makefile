run:
	python3 -m gateway

test:
	python3 -m pytest -q tests

build:
	python3 scripts/gen_catalog.py && python3 ui/build.py
