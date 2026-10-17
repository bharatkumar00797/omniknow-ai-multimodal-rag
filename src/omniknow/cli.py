"""omniknow command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace

from omniknow import __version__
from omniknow.agent import KnowledgeAgent
from omniknow.config import Settings
from omniknow.evals import run_eval
from omniknow.ingest import CorpusError, get_principal, load_principals
from omniknow.models import Answer


def _agent(args: argparse.Namespace) -> KnowledgeAgent:
    settings = Settings.from_env()
    if getattr(args, "provider", None):
        settings = replace(settings, provider=args.provider)
    if getattr(args, "corpus", None):
        settings = replace(settings, corpus_dir=args.corpus)
    return KnowledgeAgent.from_settings(settings)


def _render_answer(answer: Answer) -> str:
    lines = [
        f"Q: {answer.question}",
        f"As: {answer.principal}   provider: {answer.provider}   confidence: {answer.confidence}",
        "",
        answer.answer,
    ]
    if len(answer.sub_queries) > 1:
        lines += ["", "Sub-queries:"] + [f"  - {q}" for q in answer.sub_queries]
    if answer.citations:
        lines += ["", "Sources:"]
        for c in answer.citations:
            lines.append(f"  [{c.chunk_id}] {c.title} ({c.modality}, {c.locator})")
    if answer.security_flags:
        lines += ["", "Security flags (quarantined retrieved text):"]
        for f in answer.security_flags:
            lines.append(f"  {f.chunk_id}: {f.kind}")
    if answer.dropped_citations:
        lines += ["", "Dropped citations: " + ", ".join(answer.dropped_citations)]
    return "\n".join(lines)


def cmd_principals(args: argparse.Namespace) -> int:
    for name, p in load_principals().items():
        print(f"{name:16} {', '.join(p.groups)}")
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    agent = _agent(args)
    principal = get_principal(args.as_)
    docs = agent.visible(principal)
    if args.json:
        print(json.dumps([d.spec.model_dump() for d in docs], indent=2))
        return 0
    print(f"{len(docs)} documents visible to {principal.name}:")
    for d in docs:
        chunks = sum(1 for c in agent.chunks if c.doc_id == d.id)
        print(f"  {d.id:22} {d.spec.modality:6} {chunks:2} chunks  {d.spec.title}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    agent = _agent(args)
    hits = agent.search(args.query, get_principal(args.as_), args.k)
    if args.json:
        print(json.dumps([h.model_dump() for h in hits], indent=2))
        return 0
    if not hits:
        print("no results")
    for h in hits:
        flag = "  [QUARANTINED: injection pattern]" if h.flagged else ""
        snippet = " ".join(h.chunk.text.split())[:110]
        print(f"{h.score:.3f} cov={h.coverage:.2f} [{h.chunk.id}] {h.chunk.locator}{flag}")
        print(f"      {snippet}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    agent = _agent(args)
    answer = agent.ask(args.question, get_principal(args.as_))
    if args.json:
        print(answer.model_dump_json(indent=2))
    else:
        print(_render_answer(answer))
        if args.trace:
            print("\nTrace:")
            for t in answer.trace:
                print(f"  {t.step:10} {t.detail}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    report = run_eval(_agent(args))
    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        for r in report.cases:
            print(f"{'PASS' if r.passed else 'FAIL'}  {r.id}")
        print(
            f"\nretrieval hit-rate {report.retrieval_hit_rate:.2f} | "
            f"citation accuracy {report.citation_accuracy:.2f} | "
            f"answer accuracy {report.answer_accuracy:.2f} | "
            f"abstain accuracy {report.abstain_accuracy:.2f} | ACL leaks {report.acl_leaks}"
        )
        print("EVAL PASS" if report.passed else "EVAL FAIL")
    return 0 if report.passed else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from omniknow.api import create_app
    from omniknow.api.settings import ApiSettings

    raw_port = os.getenv("PORT") or "8000"
    if args.port is None and not raw_port.isdigit():
        raise ValueError(f"PORT must be an integer, got {raw_port!r}")
    port = args.port or int(raw_port)
    settings = ApiSettings.from_env()
    if args.dev:
        settings = replace(settings, dev_mode=True)
    if settings.access_mode == "dev" and args.host not in {"127.0.0.1", "::1", "localhost"}:
        print("warning: dev mode without API keys is exposed beyond localhost", file=sys.stderr)
    mode = {
        "api-key": "API-key auth",
        "dev": "dev mode (no auth)",
        "public-demo": "public demo (packaged corpus + mock provider)",
    }[settings.access_mode]
    print(f"OmniKnow {__version__} on http://{args.host}:{port} | {mode}", flush=True)
    uvicorn.run(create_app(settings), host=args.host, port=port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omniknow",
        description="Multimodal enterprise knowledge agent: grounded, cited, ACL-aware RAG.",
    )
    parser.add_argument("--version", action="version", version=f"omniknow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, principal: bool = True) -> None:
        if principal:
            p.add_argument(
                "--as", dest="as_", default="employee", help="principal (see `principals`)"
            )
        p.add_argument("--corpus", help="corpus directory with manifest.json")
        p.add_argument("--json", action="store_true", help="machine-readable output")

    p = sub.add_parser("principals", help="List demo principals and their groups")
    p.set_defaults(func=cmd_principals)

    p = sub.add_parser("docs", help="List documents visible to a principal")
    common(p)
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("search", help="Hybrid search (BM25 + local embeddings, RRF)")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5, choices=range(1, 21), metavar="K")
    common(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("ask", help="Ask a question and get a grounded, cited answer")
    p.add_argument("question")
    p.add_argument("--provider", choices=["mock", "openai", "groq", "ollama"])
    p.add_argument("--trace", action="store_true", help="print the agent trace")
    common(p)
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("eval", help="Run the packaged evaluation set")
    p.add_argument("--provider", choices=["mock", "openai", "groq", "ollama"])
    common(p, principal=False)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("serve", help="Start the REST API and web dashboard")
    p.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
        help="bind address (default: $HOST or 127.0.0.1)",
    )
    p.add_argument("--port", type=int, default=None, help="port (default: $PORT or 8000)")
    p.add_argument("--dev", action="store_true", help="dev mode: no API key required")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except (KeyError, ValueError, CorpusError) as exc:
        message = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {message}", file=sys.stderr)
        return 2
    return code
