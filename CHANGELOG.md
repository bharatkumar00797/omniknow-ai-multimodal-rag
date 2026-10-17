# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-17

First stable release.

### Added

- Multimodal ingest from a validated `manifest.json`: Markdown (split by heading),
  CSV tables (row groups with headers), PDFs (per page) and images described by a
  sidecar `meta.json` (caption, alt text, OCR text). Path-traversal guard, 2 MB file
  cap, 500-document cap and control-character sanitising.
- Modality-aware chunks carrying document ACL groups and a locator (section, rows,
  page, image).
- Document-level access control applied before retrieval: each principal gets an
  index built only from chunks it can read (cached per group set).
- Hybrid retrieval: BM25 plus 512-dimension hashed n-gram embeddings fused with
  reciprocal rank fusion; idf-weighted coverage as the evidence signal.
- Deterministic question decomposition into up to 4 sub-queries.
- Prompt-injection guard with 5 pattern families; flagged chunks are quarantined as
  `security_flags` and never used as evidence; allowed chunks are wrapped in
  `<untrusted-context>` with look-alike delimiters defanged.
- Evidence gate ("I don't know" below `OMNIKNOW_MIN_EVIDENCE`) and citation
  verification (must exist, be in the evidence and be readable by the caller).
- Pluggable LLM providers: offline deterministic `mock` (default) and
  OpenAI-compatible `openai` / Groq / Ollama with retries and https-or-localhost
  base URLs.
- Northwind Robotics sample corpus (9 documents across 4 modalities, one with a
  planted injection), 5 demo principals and 11 evaluation cases measuring retrieval
  hit-rate, citation accuracy, answer accuracy, abstention accuracy and ACL leaks.
- CLI: `omniknow principals | docs | search | ask | eval | serve`.
- FastAPI service: `POST /api/ask`, `POST /api/search`, `GET /api/documents`,
  `/api/principals`, `/api/evals`, `/api/config`, `/healthz`, OpenAPI docs;
  api-key / dev / public-demo access modes, SHA-256 + constant-time key checks,
  sliding-window rate limits, 64 KB body cap, strict CSP and security headers, and
  an ACL re-check before any source text is returned.
- No-build dashboard: principal picker, example questions, clickable citations,
  modality badges, quarantined chunks, documents you can see, eval report, agent
  trace and `#q=&as=&tab=` deep links.
- Hardened multi-stage Docker image, docker compose, Render, Fly.io, Railway and
  Vercel configs, stdlib smoke test and a Docker smoke job in CI.
- Full documentation: architecture and request diagrams, security model with
  residual risks, deploy guides, configuration reference and screenshots.

[Unreleased]: https://github.com/bharatkumar00797/omniknow-ai-multimodal-rag/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bharatkumar00797/omniknow-ai-multimodal-rag/releases/tag/v1.0.0
