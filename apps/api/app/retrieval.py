"""Deterministic Markdown chunking and user-scoped hybrid retrieval."""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .ai import AIProviderError, _keywords
from .settings import settings
from .monitoring import metrics


logger = logging.getLogger("nerva.retrieval")


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]: ...


def _blocks(markdown: str) -> list[str]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    current: list[str] = []
    fenced = False
    table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            current.append(line)
            continue
        is_table = stripped.startswith("|") or bool(re.match(r"^\s*[-|:]+\s*$", line))
        if not fenced and table and not is_table:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            table = False
        if not fenced and not table and stripped.startswith("#") and current:
            blocks.append("\n".join(current).strip())
            current = []
        if not stripped and not fenced and not table:
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        if is_table and not fenced:
            table = True
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _safe_slices(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = max((rest.rfind("\n", 0, max_chars), rest.rfind(" ", 0, max_chars)))
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def _overlap_tail(text: str, overlap: int) -> str:
    if not overlap or "```" in text or "~~~" in text or any(
        line.lstrip().startswith("|") for line in text.splitlines()
    ):
        return ""
    tail = text[-overlap:]
    newline = tail.find("\n")
    return tail[newline + 1:].lstrip() if newline >= 0 else tail.lstrip()


def chunk_markdown(title: str | None, markdown: str, *, target_chars: int | None = None,
                   overlap_chars: int | None = None, max_chars: int | None = None) -> list[str]:
    target = target_chars or settings.chunk_target_chars
    overlap = overlap_chars if overlap_chars is not None else settings.chunk_overlap_chars
    maximum = max_chars or max(target * 2, target + overlap + 80)
    heading = f"# {(title or '').strip()}".strip()
    chunks: list[str] = []
    section_headings: list[str] = []

    def context_prefix(*, include_current: bool = True) -> str:
        sections = section_headings if include_current else section_headings[:-1]
        parts = ([heading] if heading != "#" else []) + sections
        return "\n\n".join(dict.fromkeys(parts)).strip()

    current = heading if heading != "#" else ""
    for block in _blocks(markdown):
        match = re.match(r"^(#{1,6})\s+.+$", block.splitlines()[0])
        if match:
            level = len(match.group(1))
            section_headings[:] = section_headings[:max(0, level - 1)]
            section_headings.append(block.splitlines()[0].strip())
        for piece in _safe_slices(block, maximum):
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if current and len(candidate) > target and current != heading:
                chunks.append(current.strip())
                tail = _overlap_tail(current, overlap)
                include_current = not (section_headings and piece.strip() == section_headings[-1])
                prefix = context_prefix(include_current=include_current)
                prefix = f"{prefix}\n\n{tail}".strip() if tail else prefix
                current = f"{prefix}\n\n{piece}".strip() if prefix else piece
            else:
                current = candidate
            if len(current) >= target and piece != block:
                chunks.append(current.strip())
                tail = _overlap_tail(current, overlap)
                prefix = context_prefix()
                current = f"{prefix}\n\n{tail}".strip() if tail else prefix
    if current.strip() and current.strip() != heading:
        chunks.append(current.strip())
    return chunks or ([heading] if heading != "#" else [])


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0


@dataclass
class RetrievalResult:
    results: list[dict]
    retrieval_mode: str
    fallback_reason: str | None = None


class HybridRetriever:
    def __init__(self, store, provider: EmbeddingProvider, *, max_per_document: int = 2):
        self.store = store
        self.provider = provider
        self.max_per_document = max_per_document

    def retrieve(self, user_id: str, query: str, recent_messages: list[str] | None = None,
                 *, candidate_count: int = 20, final_count: int = 8,
                 include_public: bool = False) -> RetrievalResult:
        started = time.perf_counter()
        query = "\n".join([*(recent_messages or [])[-4:], query]).strip()
        if not query:
            metrics.increment("nerva_retrieval_total", retrieval_mode="empty", fallback="none")
            return RetrievalResult([], "empty")
        chunks = self.store.list_search_chunks(user_id, include_public=include_public)
        if not chunks:
            metrics.increment("nerva_retrieval_total", retrieval_mode="empty", fallback="none")
            return RetrievalResult([], "empty")
        terms = _keywords(query)
        keyword_ranked = []
        for chunk in chunks:
            existing = _keywords(chunk["content"])
            score = len(terms & existing) / max(1, len(terms | existing)) if terms and existing else 0.0
            if score > 0:
                keyword_ranked.append((score, chunk))
        keyword_ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
        keyword_ids = [item["id"] for _, item in keyword_ranked]
        vector_ids: list[str] = []
        fallback_reason = None
        embedding_started = time.perf_counter()
        try:
            query_vector = self.provider.embed([query])[0]
            metrics.increment("nerva_model_calls_total", operation="embedding", status="success")
            if len(query_vector) != 1024:
                raise ValueError("embedding query vector must have 1024 dimensions")
            ready = [
                item for item in chunks
                if item.get("embedding_status") == "ready"
                and item.get("embedding") and len(item["embedding"]) == 1024
            ]
            scored = [(cosine_similarity(query_vector, list(item["embedding"])), item) for item in ready]
            scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
            vector_ids = [item["id"] for _, item in scored[:candidate_count]]
        except Exception as exc:  # embedding is explicitly best-effort
            metrics.increment("nerva_model_calls_total", operation="embedding", status="failed")
            fallback_reason = getattr(exc, "code", "EMBEDDING_UNAVAILABLE")
            logger.warning(
                "retrieval_embedding_fallback",
                extra={"event": "retrieval_embedding_fallback", "error_code": fallback_reason},
            )
        finally:
            metrics.observe("nerva_model_call_duration", time.perf_counter() - embedding_started, operation="embedding")

        by_id = {item["id"]: item for item in chunks}
        scores: dict[str, float] = {}
        for rank, item_id in enumerate(keyword_ids[:candidate_count], 1):
            scores[item_id] = scores.get(item_id, 0.0) + 1 / (60 + rank)
        for rank, item_id in enumerate(vector_ids, 1):
            scores[item_id] = scores.get(item_id, 0.0) + 1 / (60 + rank)
        fused_ids = sorted(scores, key=lambda item_id: (-scores[item_id], item_id))[:candidate_count]
        if not fused_ids:
            mode = "keyword" if fallback_reason else "empty"
            metrics.increment("nerva_retrieval_total", retrieval_mode=mode, fallback=fallback_reason or "none")
            logger.info("retrieval_completed", extra={
                "event": "retrieval_completed", "retrieval_mode": mode,
                "fallback_reason": fallback_reason, "candidate_count": 0,
                "keyword_candidate_count": len(keyword_ids), "vector_candidate_count": len(vector_ids),
                "rerank_elapsed_ms": 0, "elapsed_ms": int((time.perf_counter() - started) * 1000),
            })
            return RetrievalResult([], mode, fallback_reason)
        candidates = [{**by_id[item_id], "rrf_score": scores[item_id]} for item_id in fused_ids]
        mode = "hybrid" if vector_ids else "keyword"
        rerank_started = time.perf_counter()
        rerank_elapsed_ms = 0
        try:
            reranked = self.provider.rerank(query, candidates)
            candidate_ids = [item["id"] for item in candidates]
            reranked_ids = [item.get("id") for item in reranked]
            if len(reranked_ids) != len(candidate_ids) or set(reranked_ids) != set(candidate_ids):
                raise ValueError("rerank returned invalid candidate ids")
            metrics.increment("nerva_model_calls_total", operation="rerank", status="success")
            candidates = sorted(reranked, key=lambda item: (-float(item.get("rerank_score", 0)), -item["rrf_score"], item["id"]))
        except Exception as exc:
            metrics.increment("nerva_model_calls_total", operation="rerank", status="failed")
            fallback_reason = fallback_reason or getattr(exc, "code", "RERANK_UNAVAILABLE")
            logger.warning(
                "retrieval_rerank_fallback",
                extra={"event": "retrieval_rerank_fallback", "error_code": getattr(exc, "code", "RERANK_UNAVAILABLE")},
            )
        finally:
            rerank_seconds = time.perf_counter() - rerank_started
            rerank_elapsed_ms = int(rerank_seconds * 1000)
            metrics.observe("nerva_model_call_duration", rerank_seconds, operation="rerank")
        selected: list[dict] = []
        counts: dict[str, int] = {}
        for item in candidates:
            doc_id = item["document_id"]
            if counts.get(doc_id, 0) >= self.max_per_document:
                continue
            counts[doc_id] = counts.get(doc_id, 0) + 1
            selected.append(item)
            if len(selected) >= final_count:
                break
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        metrics.increment("nerva_retrieval_total", retrieval_mode=mode, fallback=fallback_reason or "none")
        logger.info(
            "retrieval_completed",
            extra={
                "event": "retrieval_completed", "retrieval_mode": mode,
                "fallback_reason": fallback_reason, "candidate_count": len(candidates),
                "keyword_candidate_count": len(keyword_ids),
                "vector_candidate_count": len(vector_ids),
                "rerank_elapsed_ms": rerank_elapsed_ms,
                "elapsed_ms": elapsed_ms,
            },
        )
        return RetrievalResult(selected, mode, fallback_reason)


def rebuild_document_index(store, user_id: str, document_id: str, provider: EmbeddingProvider) -> list[dict] | None:
    started = time.perf_counter()
    logger.info("document_index_started", extra={
        "event": "document_index_started", "document_id": document_id,
        "model": getattr(provider, "embedding_model", getattr(provider, "model", "unknown")),
    })
    document = store.get_document(user_id, document_id)
    if not document:
        return None
    chunks = chunk_markdown(document["title"], document["markdown"])
    existing_count = len(store.list_search_chunks(user_id, document_id))
    current_count = len(store.list_search_chunks(user_id)) - existing_count
    if current_count + len(chunks) > settings.max_indexed_chunks_per_user:
        payload = [{"content": item, "embedding_status": "failed"} for item in chunks]
        result = store.replace_document_chunks(user_id, document_id, document["version"], payload)
        metrics.increment("nerva_document_index_total", status="failed", error_code="INDEX_CHUNK_LIMIT")
        logger.warning(
            "document_index_failed",
            extra={
                "event": "document_index_failed", "error_code": "INDEX_CHUNK_LIMIT",
                "chunk_count": len(chunks), "document_id": document_id,
            },
        )
        return result
    failure_code: str | None = None
    try:
        vectors = []
        for start in range(0, len(chunks), settings.embedding_batch_size):
            call_started = time.perf_counter()
            try:
                vectors.extend(provider.embed(chunks[start:start + settings.embedding_batch_size]))
                metrics.increment("nerva_model_calls_total", operation="embedding", status="success")
            except Exception:
                metrics.increment("nerva_model_calls_total", operation="embedding", status="failed")
                raise
            finally:
                metrics.observe("nerva_model_call_duration", time.perf_counter() - call_started, operation="embedding")
        if len(vectors) != len(chunks) or any(len(vector) != 1024 for vector in vectors):
            raise ValueError("invalid embedding dimensions")
        payload = [{"content": item, "embedding": vector, "embedding_status": "ready"} for item, vector in zip(chunks, vectors)]
    except Exception as exc:
        payload = [{"content": item, "embedding_status": "failed"} for item in chunks]
        error_code = getattr(exc, "code", "EMBEDDING_UNAVAILABLE")
        failure_code = error_code
        logger.warning(
            "document_index_embedding_failed",
            extra={
                "event": "document_index_embedding_failed", "error_code": error_code,
                "chunk_count": len(chunks), "document_id": document_id,
            },
        )
    result = store.replace_document_chunks(
        user_id, document_id, document["version"], payload,
        embedding_model=getattr(provider, "embedding_model", getattr(provider, "model", None)),
    )
    status = "ready" if payload and payload[0].get("embedding_status") == "ready" else "failed"
    metrics.increment("nerva_document_index_total", status=status, error_code=failure_code or "none")
    logger.info(
        "document_index_completed",
        extra={
            "event": "document_index_completed", "chunk_count": len(result),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "model": getattr(provider, "embedding_model", getattr(provider, "model", "unknown")),
            "document_id": document_id,
        },
    )
    return result
