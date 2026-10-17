from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from omniknow.api import create_app
from omniknow.api.app import client_ip
from omniknow.api.security import ApiKeyAuth, RateLimiter
from omniknow.api.settings import ApiSettings
from omniknow.config import Settings
from omniknow.llm import LLMError, MockProvider
from omniknow.models import Chunk

DEV = ApiSettings(dev_mode=True)
DEMO = ApiSettings()
SALARY_Q = "What is the salary band for a Staff Engineer?"
VENDOR_Q = "How long does vendor onboarding take and who approves new vendors?"


def client(settings: ApiSettings = DEV, base: Settings | None = None, **kw: Any) -> TestClient:
    return TestClient(create_app(settings, base or Settings(), **kw))


def ask(c: TestClient, question: str, principal: str, **extra: Any) -> Any:
    return c.post("/api/ask", json={"question": question, "principal": principal, **extra})


# ------------------------------------------------------------------ meta
def test_healthz_and_config_never_expose_keys() -> None:
    c = client(DEV, Settings(api_key="sk-test-secret-value"))
    health = c.get("/healthz").json()
    assert health["status"] == "ok" and health["documents"] == 9 and health["chunks"] > 9
    cfg = c.get("/api/config").json()
    assert cfg["access_mode"] == "dev" and cfg["provider"] == "mock"
    assert "hr-partner" in cfg["principals"] and cfg["default_principal"] == "employee"
    assert cfg["examples"] and cfg["simulated"] is False
    assert "sk-test-secret-value" not in str(cfg)


def test_public_demo_config_is_simulated_and_mock_only() -> None:
    cfg = client(DEMO, Settings(provider="openai")).get("/api/config").json()
    assert cfg["access_mode"] == "public-demo"
    assert cfg["simulated"] is True
    assert cfg["providers"] == ["mock"] and cfg["corpus"] == "packaged sample corpus"


def test_openapi_lists_routes() -> None:
    paths = client().get("/openapi.json").json()["paths"]
    for path in ("/api/ask", "/api/search", "/api/documents", "/api/principals", "/api/evals"):
        assert path in paths


# ------------------------------------------------------------------- ask
def test_ask_returns_cited_answer_with_sources() -> None:
    res = ask(client(), "How many days of paid time off do employees get?", "employee")
    assert res.status_code == 200
    body = res.json()
    assert body["answer"]["grounded"] and "25 days" in body["answer"]["answer"]
    assert body["sources"] and body["sources"][0]["doc_id"] == "benefits-overview"
    assert {s["chunk_id"] for s in body["sources"]} == {
        c["chunk_id"] for c in body["answer"]["citations"]
    }


def test_public_demo_answers_are_labelled_simulated() -> None:
    body = ask(client(DEMO), "What is the battery life of the X200 Courier?", "guest").json()
    assert body["simulated"] is True and body["access_mode"] == "public-demo"
    assert body["answer"]["provider"] == "mock" and "9 hours" in body["answer"]["answer"]


def test_acl_salary_band_denied_for_employee_allowed_for_hr() -> None:
    c = client()
    denied = ask(c, SALARY_Q, "employee").json()
    assert not denied["answer"]["grounded"] and not denied["sources"]
    assert "175000" not in str(denied)
    allowed = ask(c, SALARY_Q, "hr-partner").json()
    assert allowed["answer"]["grounded"] and "175000" in allowed["answer"]["answer"]
    assert allowed["sources"][0]["doc_id"] == "salary-bands"


def test_unknown_principal_is_rejected() -> None:
    res = ask(client(), SALARY_Q, "ceo")
    assert res.status_code == 422 and "unknown principal" in res.json()["detail"]


@pytest.mark.parametrize(
    "extra",
    [
        {"groups": ["hr"]},
        {"principal_groups": ["hr"]},
        {"acl": ["hr"]},
        {"corpus": "/etc"},
    ],
)
def test_caller_cannot_supply_groups_or_corpus(extra: dict[str, Any]) -> None:
    assert ask(client(), SALARY_Q, "employee", **extra).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"question": "", "principal": "employee"},
        {"question": "x" * 1001, "principal": "employee"},
        {"question": "hi", "principal": "Employee!"},
        {"question": "hi", "principal": "a" * 33},
        {"question": "hi"},
    ],
)
def test_ask_validation(body: dict[str, Any]) -> None:
    assert client().post("/api/ask", json=body).status_code == 422


def test_blank_question_is_422_not_500() -> None:
    assert ask(client(), "    ", "employee").status_code == 422


def test_injection_is_flagged_and_never_cited() -> None:
    body = ask(client(), VENDOR_Q, "employee").json()
    kinds = {f["kind"] for f in body["answer"]["security_flags"]}
    assert {"instruction-override", "role-hijack"} <= kinds
    assert all(s["chunk_id"] != "vendor-faq#3" for s in body["sources"])


def test_public_demo_rejects_configured_provider() -> None:
    res = ask(
        client(DEMO, Settings(provider="openai")), SALARY_Q, "employee", provider="configured"
    )
    assert res.status_code == 403


class _Broken(MockProvider):
    name = "broken"

    def compose(self, question: str, chunks: list[Chunk]) -> str:
        raise LLMError("upstream down")


def test_configured_provider_used_in_dev_and_mock_on_request() -> None:
    c = client(DEV, Settings(provider="openai"), provider_factory=lambda _s: _Broken())
    assert c.get("/api/config").json()["provider"] == "broken"
    res = ask(c, "How many days of paid time off do employees get?", "employee")
    assert res.status_code == 502 and "upstream" not in res.text
    ok = ask(c, "How many days of paid time off do employees get?", "employee", provider="mock")
    assert ok.status_code == 200 and ok.json()["answer"]["provider"] == "mock"


def test_public_demo_ignores_configured_provider_and_corpus(tmp_path: Any) -> None:
    calls: list[str] = []

    def factory(_s: Settings) -> MockProvider:
        calls.append("built")
        return _Broken()

    c = client(
        DEMO, Settings(provider="openai", corpus_dir=str(tmp_path)), provider_factory=factory
    )
    assert ask(c, "What is the X200 payload capacity?", "guest").status_code == 200
    assert calls == []


# ------------------------------------------------------- search / documents
def test_search_is_acl_filtered_and_marks_quarantine() -> None:
    c = client()
    hits = c.post("/api/search", json={"query": "salary bands", "principal": "employee"}).json()
    assert all(h["doc_id"] != "salary-bands" for h in hits["hits"])
    assert any(h["flagged"] for h in hits["hits"])
    hr = c.post("/api/search", json={"query": "salary bands", "principal": "hr-partner"}).json()
    assert any(h["doc_id"] == "salary-bands" for h in hr["hits"])
    bad = c.post("/api/search", json={"query": "x", "principal": "employee", "k": 50})
    assert bad.status_code == 422


def test_documents_are_acl_filtered() -> None:
    c = client()
    guest = c.get("/api/documents", params={"as": "guest"}).json()
    assert [d["id"] for d in guest["documents"]] == ["x200-datasheet"]
    assert guest["total_documents"] == 9
    hr = {d["id"] for d in c.get("/api/documents?as=hr-partner").json()["documents"]}
    assert "salary-bands" in hr and "incident-runbook" not in hr
    eng = {d["id"] for d in c.get("/api/documents?as=engineer").json()["documents"]}
    assert {"incident-runbook", "fleet-architecture"} <= eng and "salary-bands" not in eng
    assert c.get("/api/documents?as=root").status_code == 422
    assert c.get("/api/documents?as=../etc").status_code == 422


def test_principals_list() -> None:
    data = client().get("/api/principals").json()["principals"]
    by_name = {p["name"]: p for p in data}
    assert by_name["guest"]["visible_documents"] == 1
    assert "hr" in by_name["hr-partner"]["groups"]


def test_evals_endpoint_passes_and_is_rate_limited() -> None:
    c = client(ApiSettings(dev_mode=True, eval_limit_per_minute=1))
    first = c.get("/api/evals")
    assert first.status_code == 200
    report = first.json()["report"]
    assert report["passed"] and report["acl_leaks"] == 0 and len(report["cases"]) >= 10
    second = c.get("/api/evals")
    assert second.status_code == 429 and int(second.headers["retry-after"]) >= 1


# ------------------------------------------------------------- security
def test_api_key_mode_requires_key_via_header_or_bearer() -> None:
    c = client(ApiSettings(api_keys=("k1", "k2")))
    assert c.get("/healthz").status_code == 200
    assert c.get("/api/config").json()["auth_required"] is True
    assert ask(c, SALARY_Q, "employee").status_code == 401
    assert c.get("/api/documents?as=guest").status_code == 401
    assert c.get("/api/principals", headers={"X-API-Key": "nope"}).status_code == 401
    assert c.get("/api/principals", headers={"X-API-Key": "k2"}).status_code == 200
    bearer = c.get("/api/principals", headers={"Authorization": "Bearer k1"})
    assert bearer.status_code == 200
    cfg = c.get("/api/config", headers={"X-API-Key": "k1"}).json()
    assert cfg["authenticated"] is True and cfg["access_mode"] == "api-key"


def test_ask_limit_counts_only_valid_requests() -> None:
    c = client(ApiSettings(dev_mode=True, ask_limit_per_minute=1))
    for _ in range(3):
        assert ask(c, SALARY_Q, "nobody").status_code == 422
    assert ask(c, SALARY_Q, "employee").status_code == 200
    limited = ask(c, SALARY_Q, "employee")
    assert limited.status_code == 429 and "retry-after" in limited.headers


def test_general_rate_limit() -> None:
    c = client(ApiSettings(dev_mode=True, rate_limit_per_minute=2))
    assert c.get("/api/principals").status_code == 200
    assert c.get("/api/principals").status_code == 200
    assert c.get("/api/principals").status_code == 429


def test_body_size_cap() -> None:
    c = client()
    big = '{"question": "' + "x" * 70_000 + '", "principal": "employee"}'
    res = c.post("/api/ask", content=big, headers={"Content-Type": "application/json"})
    assert res.status_code == 413

    def chunks() -> Any:
        for _ in range(80):
            yield b"x" * 1024

    streamed = c.post("/api/ask", content=chunks(), headers={"Content-Type": "application/json"})
    assert streamed.status_code == 413


def test_security_headers_and_csp() -> None:
    c = client()
    page = c.get("/")
    assert page.status_code == 200 and "OmniKnow" in page.text
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["x-content-type-options"] == "nosniff"
    api = c.get("/api/principals")
    assert api.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in c.get("/docs").headers
    assert c.get("/static/app.js").status_code == 200


def test_dashboard_uses_no_html_sinks() -> None:
    from omniknow.api.app import STATIC_DIR

    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in js
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "style=" not in html and "onclick" not in html


def test_cors_only_when_configured() -> None:
    headers = {"Origin": "https://example.com", "Access-Control-Request-Method": "POST"}
    assert (
        "access-control-allow-origin" not in client().options("/api/ask", headers=headers).headers
    )
    c = client(ApiSettings(dev_mode=True, cors_origins=("https://example.com",)))
    res = c.options("/api/ask", headers=headers)
    assert res.headers["access-control-allow-origin"] == "https://example.com"


def test_api_key_auth_and_rate_limiter_units() -> None:
    auth = ApiKeyAuth(("alpha", "beta"))
    assert auth.enabled and auth.verify("beta") and auth.verify("gamma") is None
    assert auth.verify(None) is None and not ApiKeyAuth(()).enabled
    now = [0.0]
    limiter = RateLimiter(2, 10.0, clock=lambda: now[0])
    assert limiter.check("a") is None and limiter.check("a") is None
    retry = limiter.check("a")
    assert retry is not None and retry > 0
    now[0] = 10.5
    assert limiter.check("a") is None
    assert RateLimiter(0).check("a") is None


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OMNIKNOW_API_KEYS", " a , b ,")
    monkeypatch.setenv("OMNIKNOW_ASK_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("OMNIKNOW_TRUST_PROXY", "yes")
    s = ApiSettings.from_env()
    assert s.api_keys == ("a", "b") and s.ask_limit_per_minute == 7 and s.trust_proxy
    assert s.access_mode == "api-key"
    monkeypatch.setenv("OMNIKNOW_DEV_MODE", "maybe")
    with pytest.raises(ValueError):
        ApiSettings.from_env()


def test_client_ip_uses_rightmost_forwarded_hop_only_when_trusted() -> None:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"6.6.6.6, 10.0.0.9")],
        "client": ("127.0.0.1", 1234),
    }
    request = Request(scope)
    assert client_ip(request, trust_proxy=False) == "127.0.0.1"
    assert client_ip(request, trust_proxy=True) == "10.0.0.9"
