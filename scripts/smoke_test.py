#!/usr/bin/env python3
"""End-to-end smoke test against a running server (stdlib only).

Usage: python3 scripts/smoke_test.py [BASE_URL] [--api-key KEY]

Checks health, the dashboard and its security headers, a cited multi-part answer, ACL
enforcement (an employee cannot see salary bands, HR can), quarantined injection text, and -
when the server requires API keys and none is given - that /api calls are rejected with 401.
Exits non-zero on the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SALARY_Q = "What is the salary band for a Staff Engineer?"
MULTI_Q = "How many days of paid time off do employees get and what is the X200 battery life?"
VENDOR_Q = "How long does vendor onboarding take and who approves new vendors?"


class Client:
    def __init__(self, base: str, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any, Any]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read().decode()
                status, headers = res.status, res.headers
        except urllib.error.HTTPError as err:
            raw, status, headers = err.read().decode(), err.code, err.headers
        ctype = headers.get("content-type", "")
        return status, (json.loads(raw) if "json" in ctype else raw), headers

    def ask(self, question: str, principal: str) -> dict[str, Any]:
        status, body, _ = self.request(
            "POST", "/api/ask", {"question": question, "principal": principal}
        )
        check(status == 200, f"ask as {principal} returned {status}: {body}")
        answer: dict[str, Any] = body["answer"]
        return answer


def check(cond: bool, message: str) -> None:
    if not cond:
        print(f"FAIL {message}")
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()
    c = Client(args.base, args.api_key)
    passed = 0

    status, health, _ = c.request("GET", "/healthz")
    check(status == 200 and health.get("status") == "ok", f"healthz returned {status}")
    check(health.get("documents", 0) >= 9, f"corpus not loaded: {health}")
    status, page, headers = c.request("GET", "/")
    check(status == 200 and "OmniKnow" in page, "dashboard did not render")
    csp = headers.get("content-security-policy", "")
    check("script-src 'self'" in csp and "frame-ancestors 'none'" in csp, f"CSP missing: {csp}")
    check(headers.get("x-frame-options") == "DENY", "X-Frame-Options missing")
    check(headers.get("x-content-type-options") == "nosniff", "nosniff missing")
    print(f"PASS health + dashboard + security headers (version {health['version']})")
    passed += 1

    _, cfg, _ = c.request("GET", "/api/config")
    check(not {"api_key", "api_keys"} & set(cfg), "config exposes key material")
    if cfg.get("auth_required") and not args.api_key:
        status, _, _ = c.request("POST", "/api/ask", {"question": MULTI_Q, "principal": "employee"})
        check(status == 401, f"expected 401 without API key, got {status}")
        status, _, _ = c.request("GET", "/api/documents?as=hr-partner")
        check(status == 401, f"expected 401 on documents without API key, got {status}")
        print("PASS API-key mode rejects unauthenticated calls")
        return 0

    status, _, headers = c.request("GET", "/api/principals")
    check(status == 200 and headers.get("cache-control") == "no-store", "no-store missing on /api")

    answer = c.ask(MULTI_Q, "employee")
    cited = {cit["doc_id"] for cit in answer["citations"]}
    check(answer["grounded"], f"multi-part answer not grounded: {answer['answer']}")
    check({"benefits-overview", "x200-datasheet"} <= cited, f"missing citations: {cited}")
    check("25 days" in answer["answer"] and "9 hours" in answer["answer"], "wrong facts")
    check(len(answer["sub_queries"]) == 2, f"expected 2 sub-queries: {answer['sub_queries']}")
    print(f"PASS cited multi-part answer ({', '.join(sorted(cited))})")
    passed += 1

    denied = c.ask(SALARY_Q, "employee")
    check(not denied["grounded"] and not denied["citations"], "employee saw salary bands")
    check("175000" not in json.dumps(denied), "salary figure leaked to employee")
    allowed = c.ask(SALARY_Q, "hr-partner")
    check(allowed["grounded"] and "175000" in allowed["answer"], "hr-partner denied salary band")
    _, docs, _ = c.request("GET", "/api/documents?as=employee")
    check("salary-bands" not in {d["id"] for d in docs["documents"]}, "salary doc listed")
    _, docs, _ = c.request("GET", "/api/documents?as=hr-partner")
    check("salary-bands" in {d["id"] for d in docs["documents"]}, "salary doc hidden from HR")
    _, hits, _ = c.request("POST", "/api/search", {"query": "salary band", "principal": "employee"})
    check(all(h["doc_id"] != "salary-bands" for h in hits["hits"]), "search leaked salary bands")
    print("PASS ACL: employee cannot see salary-bands, hr-partner can")
    passed += 1

    status, _, _ = c.request("POST", "/api/ask", {"question": SALARY_Q, "principal": "ceo"})
    check(status == 422, f"unknown principal accepted ({status})")
    status, _, _ = c.request(
        "POST", "/api/ask", {"question": SALARY_Q, "principal": "employee", "groups": ["hr"]}
    )
    check(status == 422, f"caller-supplied groups accepted ({status})")
    print("PASS principals restricted to principals.json; groups cannot be injected")
    passed += 1

    vendor = c.ask(VENDOR_Q, "employee")
    kinds = {f["kind"] for f in vendor["security_flags"]}
    check(vendor["grounded"], "vendor answer not grounded")
    check("instruction-override" in kinds, f"injection not flagged: {kinds}")
    check(all(cit["chunk_id"] != "vendor-faq#3" for cit in vendor["citations"]), "quarantined")
    print(f"PASS injection quarantined ({', '.join(sorted(kinds))})")
    passed += 1

    status, evals, _ = c.request("GET", "/api/evals")
    check(status == 200 and evals["report"]["passed"], f"evals failed: {status}")
    check(evals["report"]["acl_leaks"] == 0, "eval reports ACL leaks")
    print(f"PASS eval suite ({len(evals['report']['cases'])} cases, 0 ACL leaks)")
    passed += 1

    query = urllib.parse.urlencode({"as": "guest"})
    _, docs, _ = c.request("GET", f"/api/documents?{query}")
    check([d["id"] for d in docs["documents"]] == ["x200-datasheet"], "guest sees too much")
    print(f"ALL PASS ({passed})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
