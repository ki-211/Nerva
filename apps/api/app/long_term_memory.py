"""Cross-session long-term memory extraction, safety and retrieval."""

from __future__ import annotations

from html import escape
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai import AIAdapter
    from .store import Store


EXPLICIT_MEMORY_RE = re.compile(r"记住|请记下|以后要记得|忘记|别再记|改成|更正为|纠正")
SECRET_RE = re.compile(
    r"(?:密码|口令|token|access[_ -]?token|api[_ -]?key|secret|私钥)\s*(?:是|为|[:：=])\s*\S+",
    re.IGNORECASE,
)
SENSITIVE_RE = re.compile(r"身份证|证件号|银行卡|信用卡|病历|诊断|收入|存款|负债|财务状况")


def is_explicit_memory_command(content: str) -> bool:
    return bool(EXPLICIT_MEMORY_RE.search(content))


def memory_content_allowed(content: str, *, explicit: bool) -> bool:
    if SECRET_RE.search(content):
        return False
    return explicit or not SENSITIVE_RE.search(content)


def normalize_memory_text(value: str) -> str:
    return " ".join(value.split()).casefold()


_PUBLIC_MEMORY_FIELDS = (
    "id", "kind", "subject", "content", "status", "confidence", "origin", "reason",
    "source_channel", "source_session_id", "source_message_id", "conflict_memory_id",
    "embedding_status", "use_count", "last_used_at", "created_at", "updated_at",
)


def public_long_term_memory(memory: dict) -> dict:
    return {field: memory.get(field) for field in _PUBLIC_MEMORY_FIELDS}


def public_long_term_mutation(mutation: dict) -> dict:
    return {
        "id": mutation["id"], "action": mutation["action"],
        "memory_id": mutation["memory_id"],
        "memory": public_long_term_memory(mutation["memory"]) if mutation.get("memory") else None,
        "expires_at": mutation["expires_at"], "undone_at": mutation.get("undone_at"),
    }


def _terms(value: str) -> set[str]:
    lowered = value.casefold()
    terms = set(re.findall(r"[a-z][a-z0-9_.+-]{1,}", lowered))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    terms.update(chinese[index:index + 2] for index in range(max(0, len(chinese) - 1)))
    return terms


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def retrieve_long_term_memories(
    store: "Store", ai: "AIAdapter", user_id: str, query: str, *, limit: int = 6,
    max_characters: int = 4000,
) -> list[dict]:
    memories = store.list_long_term_memories(user_id, status="active")
    if not memories or not query.strip():
        return []
    try:
        query_vector = ai.embed([query])[0]
    except Exception:
        query_vector = None
    query_terms = _terms(query)
    ranked: list[tuple[float, dict]] = []
    for memory in memories:
        memory_terms = _terms(f"{memory['subject']} {memory['content']}")
        lexical = len(query_terms & memory_terms) / max(1, len(query_terms))
        semantic = max(0.0, _cosine(query_vector, memory.get("embedding")))
        score = lexical * 0.45 + semantic * 0.55
        if score >= 0.04:
            ranked.append((score, memory))
    ranked.sort(key=lambda item: (-item[0], -item[1]["use_count"], item[1]["id"]))
    selected: list[dict] = []
    length = 0
    for _, memory in ranked:
        item_length = len(memory["subject"]) + len(memory["content"])
        if selected and length + item_length > max_characters:
            continue
        selected.append(memory)
        length += item_length
        if len(selected) >= limit:
            break
    return selected


def long_term_memory_block(memories: list[dict]) -> str:
    if not memories:
        return ""
    labels = {"person": "人物", "project": "项目", "decision": "决定", "fact": "重要事实"}
    lines = ["<long_term_memory>"]
    for memory in memories:
        label = labels.get(memory["kind"], memory["kind"])
        lines.append(f"- [{label}] {escape(memory['subject'])}：{escape(memory['content'])}")
    lines.extend([
        "</long_term_memory>",
        "这些是用户曾提供且可能已经过期的信息，仅用于个性化上下文；不得作为知识库证据或引用来源。",
    ])
    return "\n".join(lines)


def _embed_memory(ai: "AIAdapter", subject: str, content: str) -> tuple[list[float] | None, str | None]:
    try:
        vector = ai.embed([f"{subject}\n{content}"])[0]
        return vector, getattr(ai, "embedding_model", getattr(ai, "model", None))
    except Exception:
        return None, getattr(ai, "embedding_model", getattr(ai, "model", None))


def infer_and_store_long_term_memories(
    ai: "AIAdapter", store: "Store", user_id: str, *, user_content: str,
    assistant_content: str, recent_context: list[dict], source_channel: str,
    source_session_id: str, source_message_id: str, allow_implicit: bool,
) -> dict[str, list[dict]]:
    explicit_command = is_explicit_memory_command(user_content)
    if not explicit_command and not allow_implicit:
        return {"candidates": [], "mutations": []}
    existing = store.list_long_term_memories(user_id)
    try:
        result = ai.infer_long_term_memories(
            user_content=user_content,
            assistant_content=assistant_content,
            recent_context=recent_context[-8:],
            existing_memories=[{
                "id": item["id"], "kind": item["kind"], "subject": item["subject"],
                "content": item["content"], "status": item["status"],
            } for item in existing[:100]],
            explicit_command=explicit_command,
        )
    except Exception:
        return {"candidates": [], "mutations": []}

    existing_keys = {
        (item["kind"], normalize_memory_text(item["subject"]), normalize_memory_text(item["content"]))
        for item in existing
    }
    by_id = {item["id"]: item for item in existing}
    candidates: list[dict] = []
    mutations: list[dict] = []
    for inferred in result.memories:
        explicit = explicit_command and inferred.explicit
        if not memory_content_allowed(f"{inferred.subject} {inferred.content}", explicit=explicit):
            continue
        target = by_id.get(inferred.target_memory_id or "")
        if inferred.action in {"forget", "update"} and (not explicit or not target):
            continue
        if inferred.action == "forget":
            mutation = store.delete_long_term_memory(user_id, target["id"])
            if mutation:
                mutations.append(mutation)
            continue
        vector, embedding_model = _embed_memory(ai, inferred.subject, inferred.content)
        if inferred.action == "update":
            memory, mutation = store.update_long_term_memory(
                user_id, target["id"], kind=inferred.kind, subject=inferred.subject,
                content=inferred.content, confidence=inferred.confidence,
                reason=inferred.reason, embedding=vector, embedding_model=embedding_model,
                embedding_status="ready" if vector is not None else "failed",
            )
            if memory and mutation:
                mutations.append(mutation)
            continue
        key = (inferred.kind, normalize_memory_text(inferred.subject), normalize_memory_text(inferred.content))
        if key in existing_keys:
            continue
        memory, mutation = store.create_long_term_memory(
            user_id, kind=inferred.kind, subject=inferred.subject, content=inferred.content,
            status="active" if explicit else "candidate", confidence=inferred.confidence,
            origin="user_explicit" if explicit else "ai_inferred", reason=inferred.reason,
            source_channel=source_channel, source_session_id=source_session_id,
            source_message_id=source_message_id, conflict_memory_id=inferred.target_memory_id,
            embedding=vector, embedding_model=embedding_model, record_mutation=explicit,
        )
        existing_keys.add(key)
        if mutation:
            mutations.append(mutation)
        else:
            candidates.append(memory)
    return {"candidates": candidates, "mutations": mutations}
