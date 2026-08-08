"""Memory utilities: load active memories and format them for prompt injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Store


# Map each kind to a human-readable label used inside the prompt block
_KIND_LABELS: dict[str, str] = {
    "style":            "写作风格偏好",
    "topic_split":      "主题拆分策略",
    "domain":           "领域 / 专业背景",
    "naming":           "命名约定",
    "merge_preference": "知识合并偏好",
}

# Which kinds are injected into each pipeline stage
_EXTRACT_KINDS = {"domain", "style"}
_PLAN_KINDS    = {"topic_split", "naming", "merge_preference", "style"}


def _format_block(memories: list[dict], kinds: set[str]) -> str:
    """Return the <user_preferences> block to prepend to a system prompt.

    Returns an empty string when there are no relevant active memories,
    so callers can safely concatenate without adding blank sections.
    """
    relevant = [m for m in memories if m["kind"] in kinds]
    if not relevant:
        return ""

    lines: list[str] = ["<user_preferences>"]
    # Group by kind for readability
    by_kind: dict[str, list[str]] = {}
    for m in relevant:
        by_kind.setdefault(m["kind"], []).append(m["content"])

    for kind, contents in by_kind.items():
        label = _KIND_LABELS.get(kind, kind)
        lines.append(f"[{label}]")
        for content in contents:
            lines.append(f"- {content}")

    lines.append("</user_preferences>")
    lines.append(
        "以上是该用户的个性化偏好，请在分析时遵循；偏好不能作为事实证据，不得引入 source_span 或知识单元。"
    )
    return "\n".join(lines)


def extract_memory_block(memories: list[dict]) -> str:
    """Preference block for the extract_inputs stage."""
    return _format_block(memories, _EXTRACT_KINDS)


def plan_memory_block(memories: list[dict]) -> str:
    """Preference block for the plan_units stage."""
    return _format_block(memories, _PLAN_KINDS)


def load_active_memories(store: "Store", user_id: str) -> list[dict]:
    """Fetch all active memories for a user (cheap index-covered query)."""
    return store.list_memories(user_id, status="active")
