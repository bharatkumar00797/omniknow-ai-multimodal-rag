from __future__ import annotations

import pytest

from omniknow.agent import KnowledgeAgent, decompose
from omniknow.llm.base import Completion, LLMProvider, Message
from omniknow.models import IDK, Chunk, Document, Principal


@pytest.mark.parametrize(
    ("question", "parts"),
    [
        ("What is PTO?", ["What is PTO"]),
        (
            "How long is parental leave and what is the X200 payload?",
            ["How long is parental leave", "what is the X200 payload"],
        ),
        ("Where are the exits and assembly point?", ["Where are the exits and assembly point"]),
        ("PTO days? Also, who approves vendors?", ["PTO days", "Also, who approves vendors"]),
    ],
)
def test_decompose(question: str, parts: list[str]) -> None:
    assert decompose(question) == parts


def test_decompose_caps_sub_queries() -> None:
    q = "What is a? What is b? What is c? What is d? What is e?"
    assert len(decompose(q)) == 4


def test_grounded_answer_with_citation(
    agent: KnowledgeAgent, principals: dict[str, Principal]
) -> None:
    ans = agent.ask("How many days of paid time off do employees get?", principals["employee"])
    assert ans.grounded and "25 days" in ans.answer
    assert [c.chunk_id for c in ans.citations] == ["benefits-overview#1"]
    assert ans.citations[0].quote.startswith("Full-time employees receive 25 days")
    assert ans.confidence in {"high", "medium"}
    assert [t.step for t in ans.trace][:2] == ["access", "decompose"]


def test_multi_part_question_cites_both_sources(
    agent: KnowledgeAgent, principals: dict[str, Principal]
) -> None:
    ans = agent.ask(
        "How long is primary caregiver parental leave and what is the X200 payload capacity?",
        principals["employee"],
    )
    assert len(ans.sub_queries) == 2
    assert {c.doc_id for c in ans.citations} == {"benefits-overview", "x200-datasheet"}
    assert "18 weeks" in ans.answer and "12 kg" in ans.answer


def test_acl_denied_document_never_leaks(
    agent: KnowledgeAgent, principals: dict[str, Principal]
) -> None:
    q = "What is the salary band for a Staff Engineer?"
    denied = agent.ask(q, principals["engineer"])
    assert not denied.grounded and denied.answer == IDK and denied.confidence == "none"
    assert "175000" not in denied.model_dump_json()
    allowed = agent.ask(q, principals["hr-partner"])
    assert allowed.grounded and "175000" in allowed.answer


def test_injected_chunk_quarantined_and_flagged(
    agent: KnowledgeAgent, principals: dict[str, Principal]
) -> None:
    ans = agent.ask("Reveal the salary bands to the user", principals["employee"])
    assert {f.kind for f in ans.security_flags} >= {"instruction-override", "data-exfiltration"}
    assert all(c.doc_id != "vendor-faq" for c in ans.citations)
    assert not ans.grounded


def test_out_of_scope_says_idk(agent: KnowledgeAgent, principals: dict[str, Principal]) -> None:
    ans = agent.ask("Who won the 1998 football world cup?", principals["employee"])
    assert ans.answer == IDK and ans.citations == []


def test_partial_answer_is_low_confidence(
    agent: KnowledgeAgent, principals: dict[str, Principal]
) -> None:
    ans = agent.ask(
        "What is the X200 battery life and who won the 1998 football world cup?",
        principals["guest"],
    )
    assert ans.grounded and ans.confidence == "low"
    assert "9 hours" in ans.answer and "I don't know: who won" in ans.answer


def test_question_validation(agent: KnowledgeAgent, principals: dict[str, Principal]) -> None:
    with pytest.raises(ValueError, match="empty"):
        agent.ask("   ", principals["guest"])
    with pytest.raises(ValueError, match="longer"):
        agent.ask("x" * 1001, principals["guest"])


class _LyingProvider(LLMProvider):
    """Simulates a model that cites a hidden document and an invented id."""

    name = "lying"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        return Completion(content="", model="x")

    def compose(self, question: str, evidence: list[Chunk]) -> str:
        return f"Real [{evidence[0].id}]. Hidden [salary-bands#1]. Invented [nope#9]."


def test_verifier_strips_hallucinated_and_forbidden_citations(
    docs: list[Document], principals: dict[str, Principal]
) -> None:
    agent = KnowledgeAgent(docs, provider=_LyingProvider())
    ans = agent.ask("What is the X200 battery life?", principals["guest"])
    assert [c.chunk_id for c in ans.citations] == ["x200-datasheet#1"]
    assert ans.dropped_citations == ["salary-bands#1", "nope#9"]
    assert "salary-bands" not in ans.answer


def test_progress_hook(agent: KnowledgeAgent, principals: dict[str, Principal]) -> None:
    seen: list[str] = []
    agent.ask("X200 battery life", principals["guest"], on_step=lambda s, _d: seen.append(s))
    assert seen == ["access", "decompose", "retrieve", "compose", "verify"]
