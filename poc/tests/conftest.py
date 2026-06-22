"""Shared test fixtures.

`tmp_env` repoints all data paths at a throwaway temp directory and re-initialises
the DB, so tests never touch the developer's real poc.db / vectorstore / patches.
"""
import pytest

import config
from teaf import store
from teaf.explicit_channels import rag


class FakeEmbeddingFunction:
    """Small deterministic embedding for offline RAG unit tests."""

    @staticmethod
    def name() -> str:
        return "default"

    @staticmethod
    def default_space() -> str:
        return "cosine"

    @staticmethod
    def supported_spaces() -> list[str]:
        return ["cosine"]

    @classmethod
    def build_from_config(cls, config):
        return cls()

    def is_legacy(self) -> bool:
        return False

    def get_config(self) -> dict:
        return {}

    def embed_documents(self, input):
        return self(input)

    def embed_query(self, input):
        return self(input)

    def __call__(self, input):
        vectors = []
        for text in input:
            t = str(text).lower()
            vectors.append([
                float(t.count("app") + t.count("application")),
                float(t.count("owner") + t.count("responsible") + t.count("accountable")),
                float(t.count("id") + t.count("format") + t.count("immutable") + t.count("naming")),
            ])
        return vectors


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "poc.db")
    monkeypatch.setattr(config, "VECTORSTORE_DIR", tmp_path / "vectorstore")
    monkeypatch.setattr(config, "PORTFOLIO_DIR", tmp_path / "portfolio")
    monkeypatch.setattr(config, "PATCHES_DIR", tmp_path / "patches")
    # Chroma client is cached at module level — force a fresh one for the temp path.
    monkeypatch.setattr(rag, "_client", None)
    monkeypatch.setattr(rag, "_embed_fn", FakeEmbeddingFunction())
    store.init_db()
    yield
    monkeypatch.setattr(rag, "_client", None)
