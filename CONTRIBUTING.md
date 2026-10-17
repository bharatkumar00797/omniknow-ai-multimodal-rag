# Contributing to OmniKnow

Thanks for your interest in improving this multimodal enterprise knowledge agent.
Bug reports, new parsers, retrieval improvements, evaluation cases, documentation
fixes and pull requests are all welcome.

## Development setup

Requirements: Python 3.11 to 3.13 and `git`. Docker is optional (only for the
container checks).

```bash
git clone https://github.com/bharatkumar00797/omniknow-ai-multimodal-rag.git
cd omniknow-ai-multimodal-rag
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline with the default `mock` provider, so no API key is needed
for development or tests. To try a real model, copy `.env.example` to `.env` and set
`OMNIKNOW_PROVIDER` / `OMNIKNOW_BASE_URL` / `OMNIKNOW_API_KEY` / `OMNIKNOW_MODEL`.
Never commit `.env` or any key.

## Checks

Run these before opening a pull request; CI runs the same commands on Python 3.11,
3.12 and 3.13.

```bash
ruff check .            # lint
ruff format .           # format (CI uses: ruff format --check .)
mypy                    # strict type checking of src/omniknow
pytest                  # full test suite, offline
omniknow eval           # must print EVAL PASS with 0 ACL leaks
```

Optional end-to-end checks:

```bash
omniknow serve --dev                                  # dashboard on http://127.0.0.1:8000
python scripts/smoke_test.py http://127.0.0.1:8000
docker compose up --build --wait                      # hardened container
```

## Guidelines

- Keep the mock provider the default: every feature must work without network
  access or keys.
- New code is fully typed (`mypy --strict` must pass) and comes with tests.
- Access control runs before retrieval. Never build an index, compute statistics or
  pass text to a provider from chunks the principal cannot read.
- Retrieved text is data: it stays wrapped in `<untrusted-context>`, and injection
  hits become `security_flags` and are kept out of the evidence.
- Every citation must survive `verify.py`; do not return source text without a
  `can_read` check.
- Adding a document: put it under `src/omniknow/data/corpus/`, register it in
  `manifest.json` with ACL groups, and add an eval case to `data/evals.json`.
- Anything touching auth, access modes, rate limiting or the body cap needs a test
  proving the control holds (see `tests/test_api.py`).

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(ingest): parse DOCX sections
fix(retrieval): keep phrase queries together during decomposition
docs: document custom corpus manifests
test: cover ACL re-check on search hits
ci: smoke-test the Docker image in API-key mode
```

Keep commits small and focused, write the subject in the imperative mood, and
update `CHANGELOG.md` under **Unreleased** for user-visible changes.

## Reporting security issues

Please do not open public issues for vulnerabilities; see [SECURITY.md](SECURITY.md).
