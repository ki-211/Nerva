"""Read-only knowledge chat retrieval and SSE helpers."""

from __future__ import annotations

import json
import re

from .ai import retrieve_candidates


GROUNDINGS = {"knowledge", "knowledge_plus_general", "general", "insufficient"}
MEMORY_TRIGGER = re.compile(r"记住|以后|长期|从现在起|今后|每次都|一直使用")
KNOWLEDGE_FACT_TRIGGER = re.compile(
    r"端口|配置值|接口地址|URL|版本号|业务流程|操作步骤|部署地址|密码|令牌|token",
    re.IGNORECASE,
)


def build_retrieval_query(messages: list[dict]) -> str:
    user_messages = [item["content"] for item in messages if item["role"] == "user" and item["content"]]
    return "\n".join(user_messages[-4:])[-8000:]


def build_chat_history(messages: list[dict]) -> list[dict]:
    completed = [
        {"role": item["role"], "content": item["content"]}
        for item in messages
        if item["status"] == "completed" and item["content"]
    ]
    return completed[-20:]


def _excerpt(markdown: str, query: str, max_length: int = 1200) -> str:
    compact = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    if len(compact) <= max_length:
        return compact
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}|[\u4e00-\u9fff]{2,8}", query)
    lowered = compact.casefold()
    positions = [lowered.find(term.casefold()) for term in terms]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - max_length // 4)
    end = min(len(compact), start + max_length)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end].strip() + suffix


def retrieve_chat_sources(query: str, documents: list[dict], limit: int = 5) -> list[dict]:
    ranked = retrieve_candidates(query, None, documents, limit=limit)
    return [{
        "ref": f"S{index}",
        "document_id": document["id"],
        "title": document["title"],
        "excerpt": _excerpt(document["markdown"], query),
    } for index, document in enumerate(ranked, start=1)]


def sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


class ChatStreamParser:
    """Hide the model control line while forwarding answer deltas."""

    def __init__(self, has_sources: bool):
        self.has_sources = has_sources
        self.header_buffer = ""
        self.header_parsed = False
        self.grounding: str | None = None
        self.answer_parts: list[str] = []

    def feed(self, chunk: str) -> list[str]:
        if self.header_parsed:
            self.answer_parts.append(chunk)
            return [chunk] if chunk else []
        self.header_buffer += chunk
        if "\n" not in self.header_buffer:
            return []
        header, remainder = self.header_buffer.split("\n", 1)
        self._parse_header(header)
        self.header_parsed = True
        self.header_buffer = ""
        if remainder:
            self.answer_parts.append(remainder)
            return [remainder]
        return []

    def finish(self) -> list[str]:
        if not self.header_parsed:
            buffered = self.header_buffer
            self.header_buffer = ""
            self.header_parsed = True
            self.grounding = "knowledge" if self.has_sources else "general"
            if buffered:
                self.answer_parts.append(buffered)
                return [buffered]
        return []

    def _parse_header(self, header: str) -> None:
        match = re.fullmatch(r"\s*GROUNDING:\s*([a-z_]+)\s*", header)
        grounding = match.group(1) if match and match.group(1) in GROUNDINGS else None
        if not self.has_sources and grounding in {"knowledge", "knowledge_plus_general"}:
            grounding = "general"
        self.grounding = grounding or ("knowledge" if self.has_sources else "general")

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts).strip()


def validated_citations(answer: str, sources: list[dict]) -> list[dict]:
    referenced = set(re.findall(r"\[(S\d+)\]", answer))
    return [source for source in sources if source["ref"] in referenced]


def should_infer_memory(content: str) -> bool:
    return bool(MEMORY_TRIGGER.search(content)) and not bool(KNOWLEDGE_FACT_TRIGGER.search(content))
