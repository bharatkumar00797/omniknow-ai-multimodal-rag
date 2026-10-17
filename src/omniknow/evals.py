"""Small packaged evaluation set: retrieval hit-rate, citation accuracy, abstention, ACL leaks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from omniknow.acl import can_read
from omniknow.agent import KnowledgeAgent
from omniknow.ingest import load_principals, packaged_data_dir


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    question: str
    principal: str
    expected_docs: list[str] = Field(default_factory=list)
    must_contain: list[str] = Field(default_factory=list)
    expect_abstain: bool = False


class CaseResult(BaseModel):
    id: str
    passed: bool
    retrieval_hit: bool
    citation_accuracy: float
    contains_ok: bool
    abstain_ok: bool
    acl_leaks: int
    answer: str


class EvalReport(BaseModel):
    cases: list[CaseResult]
    retrieval_hit_rate: float
    citation_accuracy: float
    answer_accuracy: float
    abstain_accuracy: float
    acl_leaks: int
    passed: bool


THRESHOLDS = {"retrieval_hit_rate": 0.9, "citation_accuracy": 0.9, "answer_accuracy": 0.9}


def load_cases(path: Path | None = None) -> list[EvalCase]:
    data: Any = json.loads((path or packaged_data_dir() / "evals.json").read_text("utf-8"))
    return [EvalCase.model_validate(c) for c in data["cases"]]


def run_eval(agent: KnowledgeAgent, cases: list[EvalCase] | None = None) -> EvalReport:
    principals = load_principals()
    cases = cases if cases is not None else load_cases()
    results: list[CaseResult] = []
    for case in cases:
        principal = principals[case.principal]
        answer = agent.ask(case.question, principal)
        retrieved: set[str] = set()
        for sub in answer.sub_queries:
            retrieved.update(h.chunk.doc_id for h in agent.search(sub, principal))
        cited = [c.doc_id for c in answer.citations]
        leaks = sum(
            1 for c in answer.citations if not can_read(agent.by_id[c.chunk_id].acl, principal)
        )
        if case.expect_abstain:
            hit = True
            accuracy = 1.0 if not cited else 0.0
            abstain_ok = not answer.grounded
        else:
            hit = set(case.expected_docs) <= retrieved
            accuracy = (
                sum(1 for d in cited if d in case.expected_docs) / len(cited) if cited else 0.0
            )
            abstain_ok = answer.grounded
        contains_ok = all(s.lower() in answer.answer.lower() for s in case.must_contain)
        passed = hit and accuracy >= 1.0 and contains_ok and abstain_ok and leaks == 0
        results.append(
            CaseResult(
                id=case.id,
                passed=passed,
                retrieval_hit=hit,
                citation_accuracy=round(accuracy, 3),
                contains_ok=contains_ok,
                abstain_ok=abstain_ok,
                acl_leaks=leaks,
                answer=answer.answer,
            )
        )
    answerable = [r for r, c in zip(results, cases, strict=True) if not c.expect_abstain]
    n = max(len(results), 1)
    na = max(len(answerable), 1)
    hit_rate = sum(r.retrieval_hit for r in answerable) / na
    cit_acc = sum(r.citation_accuracy for r in answerable) / na
    ans_acc = sum(r.contains_ok and r.abstain_ok for r in results) / n
    abstain = sum(r.abstain_ok for r in results) / n
    leaks = sum(r.acl_leaks for r in results)
    passed = (
        hit_rate >= THRESHOLDS["retrieval_hit_rate"]
        and cit_acc >= THRESHOLDS["citation_accuracy"]
        and ans_acc >= THRESHOLDS["answer_accuracy"]
        and leaks == 0
    )
    return EvalReport(
        cases=results,
        retrieval_hit_rate=round(hit_rate, 3),
        citation_accuracy=round(cit_acc, 3),
        answer_accuracy=round(ans_acc, 3),
        abstain_accuracy=round(abstain, 3),
        acl_leaks=leaks,
        passed=passed,
    )
