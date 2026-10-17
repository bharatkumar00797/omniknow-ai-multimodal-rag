"""Hybrid retrieval: BM25 + hashed n-gram embeddings fused with reciprocal rank fusion.

Access control runs first: the index used for a query is built only from the
chunks the caller may read, so hidden documents never influence scores, term
statistics, or results. Indexes are cached per distinct group set.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from omniknow.acl import visible_chunks
from omniknow.guard import scan
from omniknow.models import Chunk, Principal, SearchHit

RRF_K = 60
EMBED_DIM = 512

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOPWORD_TEXT = (
    "a an and are as at be by can do does for from has have how i in is it its of on or our "
    "that the their there this to was we were what when where which who why will with you your "
    "much many any"
)
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


class BM25:
    def __init__(self, docs: Sequence[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avgdl = (sum(self.lengths) / len(docs)) if docs else 0.0
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out: list[float] = []
        for doc, length in zip(self.docs, self.lengths, strict=True):
            s = 0.0
            for term in set(query):
                tf = doc.get(term, 0)
                if not tf:
                    continue
                norm = tf + self.k1 * (1 - self.b + self.b * length / (self.avgdl or 1.0))
                s += self.idf[term] * tf * (self.k1 + 1) / norm
            out.append(s)
        return out


class HashedEmbedder:
    """Deterministic local embedding: signed feature hashing of words and char trigrams.

    No model download, no network, identical vectors on every machine - good
    enough to add fuzzy matching (plurals, compounds, typos) on top of BM25.
    """

    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim

    def _features(self, text: str) -> Counter[str]:
        feats: Counter[str] = Counter()
        for token in tokenize(text):
            feats[f"w:{token}"] += 2
            padded = f"#{token}#"
            for i in range(len(padded) - 2):
                feats[f"c:{padded[i : i + 3]}"] += 1
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in self._features(text).items():
            digest = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            sign = 1.0 if value & 1 else -1.0
            vec[(value >> 1) % self.dim] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def rrf(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


@dataclass
class HybridIndex:
    chunks: list[Chunk]
    embedder: HashedEmbedder = field(default_factory=HashedEmbedder)

    def __post_init__(self) -> None:
        self.tokens = [tokenize(c.searchable) for c in self.chunks]
        self.token_sets = [set(t) for t in self.tokens]
        self.bm25 = BM25(self.tokens)
        self.vectors = [self.embedder.embed(c.searchable) for c in self.chunks]
        self.flagged = [bool(scan(c)) for c in self.chunks]

    def coverage(self, query_terms: list[str], idx: int) -> float:
        terms = set(query_terms)
        if not terms:
            return 0.0
        weights = {t: self.bm25.idf.get(t, math.log(1 + len(self.chunks) + 0.5)) for t in terms}
        total = sum(weights.values())
        found = sum(w for t, w in weights.items() if t in self.token_sets[idx])
        return found / total if total else 0.0

    def search(self, query: str, k: int = 5, *, min_cosine: float = 0.08) -> list[SearchHit]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        bm = self.bm25.scores(terms)
        bm_rank = [i for i in sorted(range(len(bm)), key=lambda i: (-bm[i], i)) if bm[i] > 0]
        qv = self.embedder.embed(query)
        cos = [cosine(qv, v) for v in self.vectors]
        vec_rank = [
            i for i in sorted(range(len(cos)), key=lambda i: (-cos[i], i)) if cos[i] >= min_cosine
        ]
        fused = rrf([bm_rank, vec_rank])
        best = 2.0 / (RRF_K + 1)
        order = sorted(fused, key=lambda i: (-fused[i], i))[:k]
        bm_pos = {idx: r for r, idx in enumerate(bm_rank, start=1)}
        vec_pos = {idx: r for r, idx in enumerate(vec_rank, start=1)}
        return [
            SearchHit(
                chunk=self.chunks[i],
                score=round(fused[i] / best, 4),
                coverage=round(self.coverage(terms, i), 4),
                bm25_rank=bm_pos.get(i),
                vector_rank=vec_pos.get(i),
                flagged=self.flagged[i],
            )
            for i in order
        ]


class Retriever:
    """ACL-aware front door: filter by principal, then search that principal's index."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._cache: dict[frozenset[str], HybridIndex] = {}

    def index_for(self, principal: Principal) -> HybridIndex:
        key = frozenset(principal.groups)
        if key not in self._cache:
            self._cache[key] = HybridIndex(visible_chunks(self.chunks, principal))
        return self._cache[key]

    def search(self, query: str, principal: Principal, k: int = 5) -> list[SearchHit]:
        return self.index_for(principal).search(query, k)
