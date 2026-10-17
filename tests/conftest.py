"""Shared fixtures for OmniKnow tests."""

from __future__ import annotations

import pytest

from omniknow.agent import KnowledgeAgent
from omniknow.chunking import chunk_corpus
from omniknow.ingest import load_corpus, load_principals
from omniknow.models import Chunk, Document, Principal


@pytest.fixture(scope="session")
def docs() -> list[Document]:
    return load_corpus()


@pytest.fixture(scope="session")
def chunks(docs: list[Document]) -> list[Chunk]:
    return chunk_corpus(docs)


@pytest.fixture(scope="session")
def principals() -> dict[str, Principal]:
    return load_principals()


@pytest.fixture(scope="session")
def agent(docs: list[Document]) -> KnowledgeAgent:
    return KnowledgeAgent(docs)
