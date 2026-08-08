import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable


MACHINE_SCHEMA_VERSION = "nerva-export-v1"
HUMAN_SCHEMA_VERSION = "nerva-human-markdown-v1"


@dataclass(frozen=True)
class ExportArchive:
    path: Path
    filename: str
    counts: dict[str, int]


_FIELDS = {
    "documents": ("id", "title", "markdown", "version", "created_at", "updated_at"),
    "document_versions": (
        "id", "document_id", "version", "title", "markdown", "reason", "created_at",
    ),
    "sources": (
        "id", "kind", "title", "content", "processing_status", "processing_stage",
        "total_inputs", "processed_inputs", "ai_provider", "ai_model", "prompt_version",
        "ocr_model", "ocr_prompt_version", "processed_at", "created_at", "error_code",
    ),
    "knowledge_units": (
        "id", "source_id", "type", "subject", "content", "source_span", "confidence",
        "created_at",
    ),
    "change_sets": ("id", "source_id", "origin", "status", "summary", "created_at"),
    "change_items": (
        "id", "change_set_id", "operation", "target_document_id", "target_title",
        "before_title", "reason", "before_text", "after_text", "evidence", "confidence",
        "accepted",
    ),
    "knowledge_events": (
        "id", "change_set_id", "created_at", "title", "summary", "affected_documents",
        "accepted_count", "rejected_count", "origin",
    ),
}


def safe_filename(value: str, *, fallback: str = "knowledge", max_length: int = 80) -> str:
    value = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "-", value).strip(" .-")
    value = re.sub(r"\.{2,}", ".", value)
    value = re.sub(r"\s+", " ", value)
    return value[:max_length].rstrip(" .-") or fallback


def dated_filename(prefix: str, extension: str) -> str:
    return f"{safe_filename(prefix)}-{date.today().isoformat()}.{extension}"


def single_markdown_filename(document: dict) -> str:
    title = safe_filename(document["title"])
    return f"{title}-v{document['version']}.md"


def render_single_markdown(document: dict) -> str:
    return document["markdown"].strip() + "\n"


def _json_value(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unsupported export value: {type(value).__name__}")


def _json_text(value, *, pretty: bool = False) -> str:
    return json.dumps(
        value, ensure_ascii=False, default=_json_value,
        indent=2 if pretty else None, separators=None if pretty else (",", ":"),
    ) + "\n"


def _jsonl(rows: Iterable[dict]) -> str:
    return "".join(_json_text(row) for row in rows)


def _temporary_zip() -> Path:
    descriptor, name = tempfile.mkstemp(prefix="nerva-export-", suffix=".zip")
    os.close(descriptor)
    return Path(name)


def _markdown_path(document: dict, index: int) -> str:
    title = safe_filename(document["title"])
    return f"markdown/{index:04d}-{title}-{document['id']}.md"


def _markdown_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def build_human_markdown_archive(documents: list[dict]) -> ExportArchive:
    path = _temporary_zip()
    counts = {"documents": len(documents)}
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            links: list[str] = []
            entries: list[dict] = []
            for index, document in enumerate(documents, start=1):
                internal_path = _markdown_path(document, index)
                archive.writestr(internal_path, render_single_markdown(document))
                links.append(f"- [{_markdown_label(document['title'])}]({internal_path}) · v{document['version']}")
                entries.append({
                    "id": document["id"], "title": document["title"],
                    "version": document["version"], "path": internal_path,
                    "updated_at": document["updated_at"],
                })
            index_text = "# Nerva 知识库\n\n" + ("\n".join(links) if links else "知识库当前为空。") + "\n"
            manifest = {
                "schema_version": HUMAN_SCHEMA_VERSION,
                "exported_at": datetime.now(timezone.utc),
                "scope": "library", "counts": counts, "documents": entries,
            }
            archive.writestr("index.md", index_text)
            archive.writestr("manifest.json", _json_text(manifest, pretty=True))
            archive.writestr(
                "README.md",
                "# Nerva 人类可读知识库导出\n\n"
                "`index.md` 是文档目录，`markdown/` 保存导出时每篇文档的最新正式版本。\n",
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return ExportArchive(path, dated_filename("nerva-library", "zip"), counts)


def _project_rows(snapshot: dict[str, list[dict]], *, scope: str) -> dict[str, list[dict]]:
    set_origins = {row["id"]: row["origin"] for row in snapshot["change_sets"]}
    version_titles = {row["title"] for row in snapshot["document_versions"]}
    version_titles.update(row["title"] for row in snapshot["documents"])
    projected: dict[str, list[dict]] = {}
    for name, rows in snapshot.items():
        allowed = _FIELDS[name]
        clean_rows: list[dict] = []
        for source_row in rows:
            row = dict(source_row)
            if name == "knowledge_events":
                row["origin"] = set_origins.get(row["change_set_id"], "ai_ingestion")
                if scope == "document":
                    row["affected_documents"] = [
                        title for title in row["affected_documents"] if title in version_titles
                    ]
            clean_rows.append({field: row.get(field) for field in allowed})
        projected[name] = clean_rows
    return projected


def _machine_readme() -> str:
    fields = "\n".join(
        f"- `{name}.jsonl`: " + ", ".join(f"`{field}`" for field in allowed)
        for name, allowed in _FIELDS.items()
    )
    return (
        "# Nerva AI 结构化知识包\n\n"
        f"格式版本：`{MACHINE_SCHEMA_VERSION}`。各 JSONL 文件每行是一个独立 JSON 对象。\n\n"
        "## 文件与字段\n\n"
        f"{fields}\n"
        "- `markdown/`: 导出时每篇文档的最新正式 Markdown。\n\n"
        "## 关联关系\n\n"
        "`document_versions.document_id -> documents.id`；"
        "`knowledge_units.source_id -> sources.id`；"
        "`change_sets.source_id -> sources.id`；"
        "`change_items.change_set_id -> change_sets.id`；"
        "`change_items.target_document_id -> documents.id`；"
        "`knowledge_events.change_set_id -> change_sets.id`。\n\n"
        "## 隐私\n\n"
        "包中不包含账号、`user_id`、验证码、会话、数据库连接信息、内部错误详情或原始图片。"
        "图片来源的 `content` 是处理后保存的 OCR 文本。\n"
    )


def build_knowledge_archive(
    snapshot: dict[str, list[dict]], *, scope: str, document_id: str | None,
) -> ExportArchive:
    projected = _project_rows(snapshot, scope=scope)
    counts = {name: len(rows) for name, rows in projected.items()}
    path = _temporary_zip()
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            markdown_files: list[dict] = []
            for index, document in enumerate(projected["documents"], start=1):
                internal_path = _markdown_path(document, index)
                archive.writestr(internal_path, render_single_markdown(document))
                markdown_files.append({"document_id": document["id"], "path": internal_path})
            for name, rows in projected.items():
                archive.writestr(f"{name}.jsonl", _jsonl(rows))
            manifest = {
                "schema_version": MACHINE_SCHEMA_VERSION,
                "exported_at": datetime.now(timezone.utc),
                "scope": scope,
                "document_id": document_id,
                "counts": counts,
                "markdown_files": markdown_files,
                "privacy": {
                    "contains_account_data": False,
                    "contains_sessions": False,
                    "contains_original_images": False,
                    "image_sources_contain_ocr_text_only": True,
                },
            }
            archive.writestr("manifest.json", _json_text(manifest, pretty=True))
            archive.writestr("README.md", _machine_readme())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    prefix = "nerva-knowledge-package"
    if scope == "document" and projected["documents"]:
        prefix = f"nerva-{safe_filename(projected['documents'][0]['title'])}-ai"
    return ExportArchive(path, dated_filename(prefix, "zip"), counts)
