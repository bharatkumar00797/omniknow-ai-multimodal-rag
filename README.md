# OmniKnow

**Multimodal enterprise knowledge agent** — an AI retrieval-augmented generation
(RAG) system that answers questions over a mixed company corpus (Markdown docs,
CSV tables, PDFs and images) with grounded, cited answers and document-level
access control.

> Status: core engine, CLI, HTTP API, dashboard and deploy configs are in place.
> The full documentation (architecture diagrams, security model, deploy guides)
> lands with the 1.0.0 release.

## Quick start (offline)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
omniknow docs --as engineer
omniknow search "on-call paging" --as engineer
omniknow ask "How many PTO days do employees get and what is the X200 battery life?" --as employee
omniknow eval
```

The default provider is a deterministic offline mock — no API keys required.

## HTTP API & dashboard

```bash
omniknow serve --dev            # http://127.0.0.1:8000  (dashboard at /, OpenAPI at /docs)
docker compose up --build       # hardened container on http://localhost:8000
```

| Endpoint | Purpose |
|----------|---------|
| `POST /api/ask` | `{"question": "...", "principal": "employee"}` → grounded answer, citations, cited source text, sub-queries, confidence, security flags, trace |
| `POST /api/search` | Hybrid search hits visible to the principal (quarantined chunks marked `flagged`) |
| `GET /api/documents?as=<principal>` | Documents that principal may read |
| `GET /api/principals` | Demo personas from the packaged `principals.json` and their groups |
| `GET /api/evals` | Packaged evaluation suite (retrieval, citations, abstention, ACL leaks) |
| `GET /api/config` · `GET /healthz` | Access mode, provider, version · liveness |

Access modes: set `OMNIKNOW_API_KEYS` to require `X-API-Key` / `Authorization: Bearer`;
`OMNIKNOW_DEV_MODE=true` (or `--dev`) for local use without auth; with neither, the
service is a **public demo** — packaged corpus and offline mock provider only, every
response marked `simulated`. Principals can only be chosen from `principals.json`, and
the ACL filter always runs on the server before retrieval. All `OMNIKNOW_*` settings are
listed in [`.env.example`](.env.example); deploy configs are included for Docker,
Render, Fly.io, Railway and Vercel.

The dashboard (no build step) offers a principal picker, example questions, answers
with clickable citations, a sources panel with modality badges, quarantined chunks,
the documents each principal can see, and the eval report. Deep links:
`/#q=<question>&as=<principal>&tab=ask|docs|evals`.

## Design principles

- **Access control before retrieval.** Each document carries ACL groups; chunks a
  caller cannot read are removed before any scoring happens.
- **Hybrid retrieval.** BM25 keyword search and a local hashed n-gram embedding
  are fused with reciprocal rank fusion.
- **Untrusted context.** Retrieved text is scanned for prompt injection and
  wrapped in `<untrusted-context>` tags with delimiter look-alikes neutralized.
- **Grounded or silent.** Answers cite `[doc#chunk]` ids; every citation is
  verified, and weak evidence produces "I don't know" instead of a guess.
- **Pluggable LLM.** `mock` (default) | `openai` | `groq` | `ollama` via
  `OMNIKNOW_*` env vars.

## License

MIT — see [LICENSE](LICENSE).
