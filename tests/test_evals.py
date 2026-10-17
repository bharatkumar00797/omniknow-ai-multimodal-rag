from __future__ import annotations

from omniknow.agent import KnowledgeAgent
from omniknow.evals import EvalCase, load_cases, run_eval


def test_packaged_eval_passes_with_mock(agent: KnowledgeAgent) -> None:
    report = run_eval(agent)
    assert report.passed, [c for c in report.cases if not c.passed]
    assert report.retrieval_hit_rate == 1.0
    assert report.citation_accuracy == 1.0
    assert report.abstain_accuracy == 1.0
    assert report.acl_leaks == 0
    assert len(report.cases) == len(load_cases()) >= 10


def test_eval_detects_a_wrong_expectation(agent: KnowledgeAgent) -> None:
    case = EvalCase(
        id="wrong",
        question="What is the X200 battery life?",
        principal="guest",
        expected_docs=["benefits-overview"],
        must_contain=["42 hours"],
    )
    report = run_eval(agent, [case])
    assert not report.passed and not report.cases[0].passed
