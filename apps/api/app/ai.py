import re
from dataclasses import dataclass


def _clean_title(value: str) -> str:
    value = re.sub(r"^[#\s]+", "", value).strip()
    value = re.sub(r"[。！？!?：:].*$", "", value).strip()
    return value[:80] or "未命名知识"


def _keywords(text: str) -> set[str]:
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_.+-]{2,}", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    return set(latin + chinese)


@dataclass
class MergeProposal:
    operation: str
    target_document_id: str | None
    target_title: str
    reason: str
    before: str | None
    after: str
    evidence: str
    confidence: float


class LocalDemoAI:
    """Deterministic adapter used until a cloud model is configured."""

    def propose(self, content: str, requested_title: str | None, documents: list[dict]) -> MergeProposal:
        first_line = next((line for line in content.splitlines() if line.strip()), "未命名知识")
        title = _clean_title(requested_title or first_line)
        incoming = _keywords(title + "\n" + content)

        best = None
        best_score = 0.0
        for document in documents:
            existing = _keywords(document["title"] + "\n" + document["markdown"])
            if not incoming or not existing:
                continue
            score = len(incoming & existing) / max(1, len(incoming | existing))
            if title.lower() == document["title"].lower():
                score = max(score, 0.95)
            if score > best_score:
                best, best_score = document, score

        normalized = content.strip()
        if best and best_score >= 0.18:
            return MergeProposal(
                operation="ADD_BLOCK",
                target_document_id=best["id"],
                target_title=best["title"],
                reason=f"新资料与《{best['title']}》主题相关，建议作为新章节补充。",
                before=best["markdown"],
                after=f"## 新增资料\n\n{normalized}",
                evidence=normalized[:280],
                confidence=min(0.96, 0.72 + best_score / 4),
            )

        markdown = normalized if normalized.startswith("#") else f"# {title}\n\n{normalized}"
        return MergeProposal(
            operation="CREATE_DOCUMENT",
            target_document_id=None,
            target_title=title,
            reason="现有知识库中没有足够相关的文档，建议创建新文档。",
            before=None,
            after=markdown,
            evidence=normalized[:280],
            confidence=0.86,
        )


def get_ai_adapter() -> LocalDemoAI:
    # The provider seam is intentional: Bailian will implement the same contract.
    return LocalDemoAI()

