# Security Policy

OmniKnow answers questions over company documents with per-document access
control, so any way to read, infer or cite content outside a caller's permissions
is treated as a vulnerability. The design is described in the
[security model](README.md#security-model) section of the README.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |
| < 1.0 | no |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Use GitHub's private vulnerability reporting:
  **Security -> Report a vulnerability** on
  <https://github.com/bharatkumar00797/omniknow-ai-multimodal-rag/security>.
- Include the affected version or commit, a description of the impact, and steps or
  a proof of concept to reproduce it.

You can expect an acknowledgement within 3 working days and a status update within
10 working days. Once a fix is released we are happy to credit you in the changelog
unless you prefer to stay anonymous.

## Scope

In scope:

- Text, citations, scores or document metadata from a document the selected
  principal cannot read reaching an answer, search hit, source or document list.
- Requests that widen a principal's groups or swap the corpus (for example extra
  fields, crafted principal names, or the public demo reaching
  `OMNIKNOW_CORPUS_DIR`).
- Retrieved content that makes the agent follow embedded instructions, escapes the
  `<untrusted-context>` wrapper, or gets a quarantined chunk used as evidence.
- Citations that survive verification while pointing at evidence that was never
  retrieved.
- Path traversal or resource exhaustion through `manifest.json` or corpus files.
- Authentication bypass, a real provider reachable in public-demo mode, rate-limit
  or body-cap bypass, XSS or CSP bypass in the dashboard.
- Secrets exposed in API responses, logs or the published Docker image.

Out of scope:

- Choosing any demo principal from `principals.json` - personas are selectable by
  design in this demo (see residual risks in the README).
- Injection phrasings the pattern guard does not catch, as long as ACLs and citation
  verification still hold (report them anyway as hardening suggestions).
- Shared client identity when `OMNIKNOW_TRUST_PROXY` is unset behind a reverse proxy,
  and in-memory rate-limit state across restarts or serverless instances.
- Vulnerabilities in third-party platforms or dependencies without a demonstrated
  impact on OmniKnow.
