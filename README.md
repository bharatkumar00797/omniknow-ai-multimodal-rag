# OmniKnow

**Multimodal enterprise knowledge agent** — an AI retrieval-augmented generation
(RAG) system that answers questions over a mixed company corpus (Markdown docs,
CSV tables, PDFs and images) with grounded, cited answers and document-level
access control.

> Session 1 ships the core engine, CLI, offline mock provider and a packaged
> sample corpus. The FastAPI service, dashboard, deploy configs and the full docs
> land in later sessions.

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
