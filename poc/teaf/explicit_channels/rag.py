# This component is documented and explained in the thesis. The comments here
# cover technical detail that may not be in the thesis.
from __future__ import annotations

from pathlib import Path

import config
from teaf import store

# One long-lived client per process; tearing it down on writes corrupts Chroma's system cache.
_client = None
_embed_fn = None


def _safe_doc_name(name: str) -> str:
    return Path(str(name or "document.txt").replace("\\", "/")).name or "document.txt"


def _source_path(collection: str, source: str) -> Path:
    return config.DATA_DIR / "rag_sources" / collection / _safe_doc_name(source)


def _removed_marker_path(collection: str) -> Path:
    # Committed seed docs cannot be deleted on disk, so removals are recorded here.
    return config.DATA_DIR / "rag_sources" / collection / ".removed"


def _removed_set(collection: str) -> set[str]:
    p = _removed_marker_path(collection)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}


def _write_removed_set(collection: str, names: set[str]) -> None:
    p = _removed_marker_path(collection)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(sorted(names)), encoding="utf-8")


def _get_embed_fn():
    global _embed_fn
    if _embed_fn is None:
        from chromadb.utils import embedding_functions

        _embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.LOCAL_EMBEDDING_MODEL
        )
    return _embed_fn


def _get_client():
    global _client
    if _client is None:
        import chromadb

        config.VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.VECTORSTORE_DIR))
    return _client


def get_collection(name: str):
    return _get_client().get_or_create_collection(name=name, embedding_function=_get_embed_fn())


def chunk(text: str, size: int = 800, overlap: int = 150) -> list[str]:
    # Character chunking with overlap, sufficient for a PoC.
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


def ingest_text(collection: str, doc_id: str, text: str) -> int:
    """Chunk + embed + add a single named document. Returns chunk count."""
    doc_id = _safe_doc_name(doc_id)
    col = get_collection(collection)
    chunks = chunk(text)
    if not chunks:
        return 0
    # Re-adding a previously removed name lifts its tombstone.
    removed = _removed_set(collection)
    if doc_id in removed:
        removed.discard(doc_id)
        _write_removed_set(collection, removed)
    raw_path = _source_path(collection, doc_id)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(text, encoding="utf-8")
    try:
        col.delete(where={"source": doc_id})
    except Exception:
        pass
    col.add(
        ids=[f"{doc_id}::{i}" for i in range(len(chunks))],
        documents=chunks,
        metadatas=[{"source": doc_id} for _ in chunks],
    )
    return len(chunks)


def ingest(collection: str, file_path: str) -> int:
    p = Path(file_path)
    return ingest_text(collection, p.name, p.read_text(encoding="utf-8"))


# Below this many extractable characters a PDF is treated as scanned and skipped.
_PDF_MIN_CHARS = 40


def extract_pdf_text(data: bytes) -> str:
    # No OCR: returns "" for an unparseable PDF or one with no text layer.
    from io import BytesIO

    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
        pages = reader.pages
    except Exception:
        return ""  # unparseable or corrupt, treat as no extractable text
    parts = []
    for page in pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts).strip()


def ingest_upload(collection: str, filename: str, data: bytes) -> dict:
    # Accepts .txt/.md/.pdf; a scanned PDF with no text layer is skipped, not OCR'd.
    name = _safe_doc_name(filename)
    if name.lower().endswith(".pdf"):
        text = extract_pdf_text(data)
        if len(text) < _PDF_MIN_CHARS:
            return {
                "chunks": 0,
                "skipped": True,
                "reason": "no extractable text, looks like a scanned/image PDF, so it was not embedded (no OCR).",
            }
    else:
        text = data.decode("utf-8", errors="ignore")
    chunks = ingest_text(collection, name, text)
    return {"chunks": chunks, "skipped": False, "reason": ""}


def retrieve(collection: str, query: str, k: int = 4) -> list[dict]:
    col = get_collection(collection)
    n = col.count()
    if n == 0:
        return []
    res = col.query(query_texts=[query], n_results=min(k, n))
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    return [{"text": d, "source": (m or {}).get("source", "?")} for d, m in zip(docs, metas)]


def retrieve_for_agent(agent_id: int, query: str, k: int = 4) -> tuple[list[dict], list[str]]:
    # Collections come from the agent_rag links, not the caller, so channel isolation
    # is enforced in code. Per-collection failures are returned, not swallowed.
    hits: list[dict] = []
    errors: list[str] = []
    for row in store.list_agent_rag(agent_id):
        collection = row["collection_name"]
        try:
            ensure_seeded(collection)
            hits.extend(retrieve(collection, query, k=k))
        except Exception as e:
            errors.append(f"{collection}: {e}")
    return hits, errors


def list_documents(collection: str) -> list[str]:
    col = get_collection(collection)
    if col.count() == 0:
        return []
    metas = col.get(include=["metadatas"]).get("metadatas") or []
    return sorted({(m or {}).get("source", "?") for m in metas})


def list_available_documents(collection: str) -> list[str]:
    # Reads filenames from disk to avoid opening Chroma or loading embeddings.
    docs: set[str] = set()
    source_dir = config.DATA_DIR / "rag_sources" / collection
    if source_dir.is_dir():
        docs.update(p.name for p in source_dir.iterdir() if p.is_file() and p.name != ".removed")
    subdir = config.COLLECTION_DOCS_SUBDIR.get(collection)
    if subdir:
        seed_dir = config.DOCS_DIR / subdir
        if seed_dir.is_dir():
            docs.update(p.name for p in seed_dir.glob("*.txt"))
    return sorted(docs - _removed_set(collection))


def remove_document(collection: str, source: str) -> None:
    # A removed seed doc is tombstoned so seeding cannot bring it back.
    name = _safe_doc_name(source)
    try:
        get_collection(collection).delete(where={"source": name})
    except Exception:
        pass
    raw_path = _source_path(collection, name)
    if raw_path.exists():
        raw_path.unlink()
    subdir = config.COLLECTION_DOCS_SUBDIR.get(collection)
    if subdir and (config.DOCS_DIR / subdir / name).exists():
        removed = _removed_set(collection)
        removed.add(name)
        _write_removed_set(collection, removed)


def read_document(collection: str, source: str) -> str:
    raw_path = _source_path(collection, source)
    if raw_path.exists():
        return raw_path.read_text(encoding="utf-8")

    subdir = config.COLLECTION_DOCS_SUBDIR.get(collection)
    if subdir:
        seed_path = config.DOCS_DIR / subdir / _safe_doc_name(source)
        if seed_path.exists():
            return seed_path.read_text(encoding="utf-8")

    col = get_collection(collection)
    if col.count() == 0:
        return ""
    res = col.get(where={"source": source}, include=["documents"])
    docs = res.get("documents") or []
    ids = res.get("ids") or []

    def chunk_index(item) -> int:
        doc_id = item[0]
        try:
            return int(str(doc_id).rsplit("::", 1)[1])
        except (IndexError, ValueError):
            return 0

    ordered = [doc for _, doc in sorted(zip(ids, docs), key=chunk_index)]
    return "\n\n".join(ordered)


def count(collection: str) -> int:
    return get_collection(collection).count()


def clear_store() -> None:
    # Danger-zone reset; collections re-seed lazily on next use.
    import shutil

    global _client
    _client = None
    if config.VECTORSTORE_DIR.exists():
        shutil.rmtree(config.VECTORSTORE_DIR, ignore_errors=True)
    source_dir = config.DATA_DIR / "rag_sources"
    if source_dir.exists():
        shutil.rmtree(source_dir, ignore_errors=True)
    config.VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_seeded(collection: str) -> int:
    # Seeds only .txt files, and only when the collection is empty (idempotent).
    if count(collection) > 0:
        return 0
    subdir = config.COLLECTION_DOCS_SUBDIR.get(collection)
    if not subdir:
        return 0
    folder = config.DOCS_DIR / subdir
    if not folder.is_dir():
        return 0
    removed = _removed_set(collection)
    ingested = 0
    for f in sorted(folder.glob("*.txt")):
        if f.name in removed:
            continue  # user removed this seed doc, do not re-seed it
        if ingest(collection, str(f)) > 0:
            ingested += 1
    return ingested
