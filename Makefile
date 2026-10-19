GITLEAKS ?= gitleaks
REQ_FILE ?= $(or $(TMPDIR),/tmp)/meridian-gate-req.txt

.PHONY: gate tools run

gate:
	uv sync --frozen
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run pytest -q
	$(GITLEAKS) git --no-banner --redact --exit-code 1 .
	uv export --frozen --no-emit-project --format requirements-txt -o $(REQ_FILE) >/dev/null
	uv run pip-audit --strict --disable-pip -r $(REQ_FILE)

tools:
	GOBIN=$$HOME/.local/bin go install github.com/zricethezav/gitleaks/v8@v8.30.1

run:
	uv run python -m app
