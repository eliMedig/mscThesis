"""Tests for RAG ingest/retrieve (explicit knowledge channel)."""
from teaf.explicit_channels import rag


def test_chunking():
    assert rag.chunk("") == []
    assert rag.chunk("short") == ["short"]
    chunks = rag.chunk("x" * 2000, size=800, overlap=150)
    assert len(chunks) >= 3
    assert all(len(c) <= 800 for c in chunks)


def test_ingest_and_retrieve(tmp_env):
    coll = "test_collection"
    assert rag.count(coll) == 0
    rag.ingest_text(coll, "policy.txt", "Every application must have a named accountable owner.")
    rag.ingest_text(coll, "naming.txt", "Application IDs use the format APP-NNNN and are immutable.")
    assert rag.count(coll) > 0
    assert set(rag.list_documents(coll)) == {"policy.txt", "naming.txt"}

    hits = rag.retrieve(coll, "who is responsible for an application?", k=2)
    assert hits and all("text" in h and "source" in h for h in hits)
    # the owner document should be the most relevant hit
    assert hits[0]["source"] == "policy.txt"


def test_retrieve_empty_collection(tmp_env):
    assert rag.retrieve("nonexistent_collection", "anything", k=3) == []


def test_ingest_upload_is_visible_without_restart(tmp_env):
    coll = "live_refresh"
    # Prime the live retriever (builds + caches the Chroma client).
    rag.ingest_text(coll, "seed.txt", "Seed document about ownership policy.")
    assert rag.retrieve(coll, "ownership policy", k=3)
    primed_client = rag._client
    assert primed_client is not None

    # Upload a NEW doc through the same path the UI uses…
    rag.ingest_upload(coll, "fresh.md", b"Onboarding requires an intake review and a named owner.")
    # …it must be retrievable immediately, with no manual rebuild/restart.
    hits = rag.retrieve(coll, "onboarding intake review", k=5)
    assert any(h["source"] == "fresh.md" for h in hits)
    # The persistent client is reused, never torn down (tearing it down corrupts Chroma).
    assert rag._client is primed_client


def test_ingest_upload_text_and_skip_scanned(tmp_env):
    coll = "pdf_test"
    # text/markdown path is unchanged
    res = rag.ingest_upload(coll, "policy.md", b"Every application must have a named accountable owner.")
    assert res["skipped"] is False and res["chunks"] >= 1
    assert "policy.md" in rag.list_available_documents(coll)

    # a "PDF" with no extractable text (e.g. scanned/image) is skipped, not embedded
    fake_image_pdf = b"%PDF-1.4\n% scanned image, no text layer\n"
    res2 = rag.ingest_upload(coll, "scan.pdf", fake_image_pdf)
    assert res2["skipped"] is True and res2["chunks"] == 0
    assert "scan.pdf" not in rag.list_available_documents(coll)


def test_remove_document(tmp_env):
    coll = "test_removal"
    rag.ingest_text(coll, "keep.txt", "Application owners stay accountable.")
    rag.ingest_text(coll, "drop.txt", "Application IDs use the format APP-NNNN.")
    assert set(rag.list_available_documents(coll)) == {"keep.txt", "drop.txt"}

    rag.remove_document(coll, "drop.txt")

    # No longer listed and no longer retrievable.
    assert rag.list_available_documents(coll) == ["keep.txt"]
    assert set(rag.list_documents(coll)) == {"keep.txt"}
    hits = rag.retrieve(coll, "APP-NNNN format", k=5)
    assert all(h["source"] != "drop.txt" for h in hits)

    # Re-uploading the same name brings it back (tombstone lifted if it was a seed doc).
    rag.ingest_text(coll, "drop.txt", "Application IDs use the format APP-NNNN.")
    assert "drop.txt" in rag.list_available_documents(coll)
