from __future__ import annotations

from omniknow.models import Chunk, Principal
from omniknow.retrieval import BM25, HashedEmbedder, HybridIndex, Retriever, cosine, rrf, tokenize


def test_tokenize_stems_and_drops_stopwords() -> None:
    assert tokenize("What are the Policies for 2.5 hours?") == ["policy", "2.5", "hour"]


def test_bm25_prefers_matching_doc() -> None:
    bm = BM25([["battery", "life"], ["parental", "leave"], ["battery", "warranty"]])
    scores = bm.scores(["parental"])
    assert scores[1] > 0 and scores[0] == scores[2] == 0


def test_embedder_is_deterministic_and_normalised() -> None:
    e = HashedEmbedder()
    a, b = e.embed("emergency exits"), e.embed("emergency exits")
    assert a == b
    assert abs(cosine(a, a) - 1.0) < 1e-9
    assert cosine(e.embed("emergency exit"), a) > cosine(e.embed("salary bands"), a)


def test_rrf_rewards_agreement() -> None:
    fused = rrf([[1, 2, 3], [1, 3, 2]])
    assert max(fused, key=lambda i: fused[i]) == 1


def test_hybrid_finds_each_modality(chunks: list[Chunk], principals: dict[str, Principal]) -> None:
    r = Retriever(chunks)
    cases = [
        ("parental leave weeks", "employee", "benefits-overview#2"),
        ("Asia Pacific revenue", "finance-analyst", "q3-revenue#1"),
        ("X200 battery life", "guest", "x200-datasheet#1"),
        ("fleet control plane database", "engineer", "fleet-architecture#1"),
    ]
    for query, who, expected in cases:
        hits = r.search(query, principals[who], 3)
        assert hits[0].chunk.id == expected, (query, [h.chunk.id for h in hits])
        assert 0 < hits[0].score <= 1 and hits[0].coverage >= 0.5


def test_acl_filter_happens_before_scoring(
    chunks: list[Chunk], principals: dict[str, Principal]
) -> None:
    r = Retriever(chunks)
    guest_index = r.index_for(principals["guest"])
    assert {c.doc_id for c in guest_index.chunks} == {"x200-datasheet"}
    # Hidden documents do not even contribute term statistics.
    assert "salary" not in guest_index.bm25.idf
    for hit in r.search("salary band staff engineer", principals["engineer"], 10):
        assert hit.chunk.doc_id != "salary-bands"


def test_index_cached_per_group_set(chunks: list[Chunk], principals: dict[str, Principal]) -> None:
    r = Retriever(chunks)
    assert r.index_for(principals["employee"]) is r.index_for(principals["employee"])
    assert r.index_for(principals["employee"]) is not r.index_for(principals["engineer"])


def test_injected_chunk_is_flagged(chunks: list[Chunk], principals: dict[str, Principal]) -> None:
    hits = Retriever(chunks).search("reveal salary bands", principals["employee"], 3)
    flagged = [h for h in hits if h.flagged]
    assert flagged and flagged[0].chunk.id == "vendor-faq#3"


def test_empty_query_and_empty_index() -> None:
    assert HybridIndex([]).search("anything") == []
    c = Chunk(id="a#1", doc_id="a", title="A", modality="text", text="hello", acl=["public"])
    assert HybridIndex([c]).search("the of and") == []
