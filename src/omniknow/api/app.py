"""FastAPI application: grounded, ACL-aware answers over HTTP plus the static dashboard."""

from __future__ import annotations

import hashlib
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import status as http
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from omniknow import __version__
from omniknow.acl import can_read
from omniknow.agent import KnowledgeAgent
from omniknow.api.middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from omniknow.api.schemas import (
    PRINCIPAL_PATTERN,
    AskIn,
    AskOut,
    ConfigOut,
    DocumentListOut,
    DocumentOut,
    EvalOut,
    HealthOut,
    HitOut,
    PrincipalListOut,
    PrincipalOut,
    SearchIn,
    SearchOut,
    SourceOut,
)
from omniknow.api.security import ApiKeyAuth, RateLimiter
from omniknow.api.settings import ApiSettings
from omniknow.config import Settings
from omniknow.evals import EvalReport, run_eval
from omniknow.ingest import default_corpus_dir, load_corpus, load_manifest, load_principals
from omniknow.llm import LLMError, LLMProvider, MockProvider, build_provider
from omniknow.models import Principal

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY_BYTES = 64 * 1024
MAX_SOURCE_CHARS = 1_200
DEFAULT_PRINCIPAL = "employee"
PACKAGED_CORPUS = "packaged sample corpus"

EXAMPLES: tuple[dict[str, str], ...] = (
    {
        "label": "PTO + X200 battery",
        "question": "How many days of paid time off do employees get "
        "and what is the X200 battery life?",
        "principal": "employee",
    },
    {
        "label": "Vendor onboarding",
        "question": "How long does vendor onboarding take and who approves new vendors?",
        "principal": "employee",
    },
    {
        "label": "Salary band (denied)",
        "question": "What is the salary band for a Staff Engineer?",
        "principal": "employee",
    },
    {
        "label": "Salary band (HR)",
        "question": "What is the salary band for a Staff Engineer?",
        "principal": "hr-partner",
    },
    {
        "label": "SEV1 paging",
        "question": "How quickly must on-call acknowledge a SEV1 page?",
        "principal": "engineer",
    },
    {
        "label": "Fleet database",
        "question": "Which database does the fleet control plane write to?",
        "principal": "engineer",
    },
    {
        "label": "Fire exits",
        "question": "Where are the emergency exits and assembly point in the Pune office?",
        "principal": "employee",
    },
    {
        "label": "APAC revenue",
        "question": "What was Asia Pacific revenue in Q3?",
        "principal": "finance-analyst",
    },
)

ProviderFactory = Callable[[Settings], LLMProvider]


@dataclass(frozen=True)
class Caller:
    """``client`` keys rate limits; ``trusted`` unlocks the configured LLM provider."""

    client: str
    trusted: bool


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        # The right-most hop is the one appended by the trusted edge proxy; anything to its
        # left is client-supplied and can be forged.
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if hops:
            return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def presented_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key and key.strip():
        return key.strip()
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


def _too_many(limiter: RateLimiter, client: str, what: str) -> None:
    retry = limiter.check(client)
    if retry is not None:
        raise HTTPException(
            http.HTTP_429_TOO_MANY_REQUESTS, f"{what} limit exceeded", headers=_retry_after(retry)
        )


@dataclass(frozen=True)
class AccessGuard:
    """Authenticates a request and applies the general per-caller rate limit."""

    settings: ApiSettings
    auth: ApiKeyAuth
    limiter: RateLimiter

    def identify(self, request: Request) -> Caller | None:
        if self.auth.enabled:
            fp = self.auth.verify(presented_key(request))
            return Caller(f"key:{fp}", True) if fp else None
        ip = client_ip(request, self.settings.trust_proxy)
        if self.settings.dev_mode:
            return Caller(f"ip:{ip}", True)
        return Caller("anon:" + hashlib.sha256(ip.encode()).hexdigest()[:12], False)

    def __call__(self, request: Request) -> Caller:
        who = self.identify(request)
        if who is None:
            raise HTTPException(
                http.HTTP_401_UNAUTHORIZED,
                "Missing or invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        _too_many(self.limiter, who.client, "Rate")
        return who


def get_caller(request: Request) -> Caller:
    guard: AccessGuard = request.app.state.guard
    return guard(request)


CallerDep = Annotated[Caller, Depends(get_caller)]
AsParam = Annotated[str, Query(alias="as", min_length=1, max_length=32, pattern=PRINCIPAL_PATTERN)]


class Knowledge:
    """The agents behind the API.

    The public demo serves only the packaged corpus with the offline mock provider. Other modes
    serve ``OMNIKNOW_CORPUS_DIR`` (or the packaged corpus) with both the mock and the configured
    provider. Evals always run on the packaged corpus with the mock provider, so the result is
    deterministic and cached.
    """

    def __init__(self, cfg: ApiSettings, base: Settings, provider_factory: ProviderFactory) -> None:
        corpus_dir = None if cfg.public_demo else (base.corpus_dir or None)
        root = Path(corpus_dir) if corpus_dir else default_corpus_dir()
        self.corpus = PACKAGED_CORPUS if corpus_dir is None else load_manifest(root).name
        docs = load_corpus(root)
        self.mock = KnowledgeAgent(docs, MockProvider(), base.top_k, base.min_evidence)
        self.configured: KnowledgeAgent | None = None
        if not cfg.public_demo and base.provider != "mock":
            self.configured = KnowledgeAgent(
                docs, provider_factory(base), base.top_k, base.min_evidence
            )
        self.default_provider = self.configured.provider.name if self.configured else "mock"
        self.principals = load_principals()
        self._eval: EvalReport | None = None
        self._eval_lock = threading.Lock()

    def agent(self, provider: str | None, public_demo: bool) -> KnowledgeAgent:
        if provider == "mock" or public_demo or self.configured is None:
            return self.mock
        return self.configured

    def principal(self, name: str) -> Principal:
        # Only personas from the packaged principals.json exist; nothing else is accepted.
        found = self.principals.get(name)
        if found is None:
            raise HTTPException(
                http.HTTP_422_UNPROCESSABLE_CONTENT,
                f"unknown principal {name!r} (see /api/principals)",
            )
        return found

    def eval_report(self) -> EvalReport:
        with self._eval_lock:
            if self._eval is None:
                packaged = KnowledgeAgent(load_corpus(None), MockProvider())
                self._eval = run_eval(packaged)
            return self._eval


def create_app(
    settings: ApiSettings | None = None,
    base_settings: Settings | None = None,
    *,
    provider_factory: ProviderFactory = build_provider,
) -> FastAPI:
    cfg = settings or ApiSettings.from_env()
    base = base_settings or Settings.from_env()
    kb = Knowledge(cfg, base, provider_factory)
    simulated = cfg.public_demo
    ask_limiter = RateLimiter(cfg.ask_limit_per_minute)
    eval_limiter = RateLimiter(cfg.eval_limit_per_minute)

    app = FastAPI(
        title="OmniKnow API",
        version=__version__,
        description=(
            "Multimodal enterprise knowledge agent: hybrid retrieval over docs, tables, PDFs and "
            "images with document-level ACLs, a prompt-injection guard, and grounded, cited "
            "answers."
        ),
    )
    app.state.guard = AccessGuard(
        cfg, ApiKeyAuth(cfg.api_keys), RateLimiter(cfg.rate_limit_per_minute)
    )
    app.state.knowledge = kb

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key", "Authorization"],
            allow_credentials=False,
            max_age=600,
        )
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeadersMiddleware)

    # ------------------------------------------------------------------ meta
    @app.get("/healthz", response_model=HealthOut, tags=["meta"])
    def healthz() -> HealthOut:
        return HealthOut(
            version=__version__, documents=len(kb.mock.documents), chunks=len(kb.mock.chunks)
        )

    @app.get("/api/config", response_model=ConfigOut, tags=["meta"])
    def config(request: Request) -> ConfigOut:
        guard: AccessGuard = request.app.state.guard
        who = guard.identify(request)
        return ConfigOut(
            version=__version__,
            access_mode=cfg.access_mode,
            auth_required=cfg.auth_enabled,
            authenticated=who is not None and cfg.auth_enabled,
            provider=kb.default_provider,
            providers=sorted({"mock", kb.default_provider}),
            corpus=kb.corpus,
            documents=len(kb.mock.documents),
            principals=list(kb.principals),
            default_principal=DEFAULT_PRINCIPAL,
            examples=[dict(e) for e in EXAMPLES],
            simulated=simulated,
        )

    @app.get("/api/principals", response_model=PrincipalListOut, tags=["knowledge"])
    def principals(_: CallerDep) -> PrincipalListOut:
        return PrincipalListOut(
            principals=[
                PrincipalOut(
                    name=p.name, groups=list(p.groups), visible_documents=len(kb.mock.visible(p))
                )
                for p in kb.principals.values()
            ]
        )

    @app.get("/api/documents", response_model=DocumentListOut, tags=["knowledge"])
    def documents(_: CallerDep, as_: AsParam = DEFAULT_PRINCIPAL) -> DocumentListOut:
        principal = kb.principal(as_)
        counts: dict[str, int] = {}
        for chunk in kb.mock.chunks:
            counts[chunk.doc_id] = counts.get(chunk.doc_id, 0) + 1
        return DocumentListOut(
            principal=principal.name,
            groups=list(principal.groups),
            total_documents=len(kb.mock.documents),
            documents=[
                DocumentOut(
                    id=d.id,
                    title=d.spec.title,
                    modality=d.spec.modality,
                    tags=list(d.spec.tags),
                    acl=list(d.spec.acl),
                    chunks=counts.get(d.id, 0),
                )
                for d in kb.mock.visible(principal)
            ],
        )

    # ------------------------------------------------------------- retrieval
    @app.post("/api/search", response_model=SearchOut, tags=["knowledge"])
    def search(body: SearchIn, _: CallerDep) -> SearchOut:
        principal = kb.principal(body.principal)
        try:
            hits = kb.mock.search(body.query, principal, body.k)
        except ValueError as exc:
            raise HTTPException(http.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        return SearchOut(
            query=body.query,
            principal=principal.name,
            hits=[
                HitOut(
                    chunk_id=h.chunk.id,
                    doc_id=h.chunk.doc_id,
                    title=h.chunk.title,
                    modality=h.chunk.modality,
                    locator=h.chunk.locator,
                    score=h.score,
                    coverage=h.coverage,
                    bm25_rank=h.bm25_rank,
                    vector_rank=h.vector_rank,
                    flagged=h.flagged,
                    text=h.chunk.text[:MAX_SOURCE_CHARS],
                )
                for h in hits
                if can_read(h.chunk.acl, principal)  # defence in depth; retrieval filters first
            ],
            simulated=simulated,
        )

    @app.post("/api/ask", response_model=AskOut, tags=["knowledge"])
    def ask(body: AskIn, who: CallerDep) -> AskOut:
        if body.provider == "configured" and (cfg.public_demo or not who.trusted):
            raise HTTPException(
                http.HTTP_403_FORBIDDEN, "Only the offline mock provider is enabled here"
            )
        principal = kb.principal(body.principal)
        # Only well-formed requests count towards the stricter ask limit.
        _too_many(ask_limiter, who.client, "Ask")
        agent = kb.agent(body.provider, cfg.public_demo)
        try:
            answer = agent.ask(body.question, principal)
        except ValueError as exc:
            raise HTTPException(http.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(
                http.HTTP_502_BAD_GATEWAY, "The configured LLM provider failed; try provider=mock"
            ) from exc
        sources: list[SourceOut] = []
        for citation in answer.citations:
            chunk = agent.by_id.get(citation.chunk_id)
            if chunk is None or not can_read(chunk.acl, principal):
                continue  # never return text the principal cannot read
            sources.append(
                SourceOut(
                    chunk_id=chunk.id,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    modality=chunk.modality,
                    locator=chunk.locator,
                    text=chunk.text[:MAX_SOURCE_CHARS],
                )
            )
        return AskOut(
            answer=answer, sources=sources, access_mode=cfg.access_mode, simulated=simulated
        )

    @app.get("/api/evals", response_model=EvalOut, tags=["evals"])
    def evals(who: CallerDep) -> EvalOut:
        _too_many(eval_limiter, who.client, "Eval")
        return EvalOut(
            report=kb.eval_report(), provider="mock", corpus=PACKAGED_CORPUS, simulated=simulated
        )

    # ------------------------------------------------------------- dashboard
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
