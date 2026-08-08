import base64
import hashlib
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_BATCH_BYTES = 30 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
MAX_IMAGE_COUNT = 10
MAX_COMBINED_OCR_CHARS = 100_000
ALLOWED_FORMATS = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
TEMP_ROOT = Path(tempfile.gettempdir()) / "nerva-image-jobs"


class ImageValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TemporaryImage:
    sequence: int
    path: Path
    media_type: str
    size_bytes: int
    sha256: str


def create_job_directory() -> Path:
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="job_", dir=TEMP_ROOT))


def cleanup_job_directory(path: Path) -> None:
    try:
        resolved = path.resolve()
        root = TEMP_ROOT.resolve()
        if resolved != root and root in resolved.parents:
            shutil.rmtree(resolved, ignore_errors=True)
    except OSError:
        return


def cleanup_stale_directories(max_age_seconds: int = 3600) -> int:
    if not TEMP_ROOT.exists():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for candidate in TEMP_ROOT.iterdir():
        try:
            if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                cleanup_job_directory(candidate)
                removed += 1
        except OSError:
            continue
    return removed


def validate_image(path: Path) -> tuple[str, int, int]:
    try:
        with Image.open(path) as image:
            image_format = image.format or ""
            if image_format not in ALLOWED_FORMATS:
                raise ImageValidationError("IMAGE_UNSUPPORTED_FORMAT", "仅支持 JPG、PNG 和 WebP 图片")
            if getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1:
                raise ImageValidationError("IMAGE_ANIMATION_UNSUPPORTED", "暂不支持动画图片")
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ImageValidationError("IMAGE_PIXEL_LIMIT_EXCEEDED", "图片像素不能超过 3000 万")
            image.verify()
            return ALLOWED_FORMATS[image_format], width, height
    except ImageValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageValidationError("IMAGE_INVALID", "图片已损坏或内容格式无效") from exc


async def save_uploads(files: list[UploadFile]) -> tuple[Path, list[TemporaryImage]]:
    if not 1 <= len(files) <= MAX_IMAGE_COUNT:
        raise ImageValidationError("IMAGE_COUNT_INVALID", "一次请选择 1 到 10 张图片")

    job_directory = create_job_directory()
    saved: list[TemporaryImage] = []
    hashes: set[str] = set()
    batch_size = 0
    try:
        for sequence, upload in enumerate(files, start=1):
            path = job_directory / f"{uuid.uuid4().hex}.image"
            digest = hashlib.sha256()
            size = 0
            with path.open("wb") as target:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    batch_size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ImageValidationError("IMAGE_TOO_LARGE", "单张图片不能超过 6 MB")
                    if batch_size > MAX_BATCH_BYTES:
                        raise ImageValidationError("IMAGE_BATCH_TOO_LARGE", "一批图片总大小不能超过 30 MB")
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise ImageValidationError("IMAGE_EMPTY", "不能上传空文件")
            checksum = digest.hexdigest()
            if checksum in hashes:
                raise ImageValidationError("IMAGE_DUPLICATE", "同一批次不能包含重复图片")
            hashes.add(checksum)
            media_type, _, _ = validate_image(path)
            saved.append(TemporaryImage(sequence, path, media_type, size, checksum))
        return job_directory, saved
    except Exception:
        cleanup_job_directory(job_directory)
        raise
    finally:
        for upload in files:
            await upload.close()


def image_data_url(image: TemporaryImage) -> str:
    encoded = base64.b64encode(image.path.read_bytes()).decode("ascii")
    return f"data:{image.media_type};base64,{encoded}"


def combine_ocr_text(note: str | None, results: list[str]) -> str:
    sections: list[str] = []
    normalized_note = (note or "").strip()
    if normalized_note:
        sections.append(f"# 用户补充说明\n\n{normalized_note}")
    for sequence, result in enumerate(results, start=1):
        sections.append(f"# 图片 {sequence} OCR\n\n{result.strip()}")
    combined = "\n\n".join(sections).strip()
    if not combined:
        raise ImageValidationError("OCR_EMPTY_BATCH", "图片中没有识别到可用文字")
    if len(combined) > MAX_COMBINED_OCR_CHARS:
        raise ImageValidationError("OCR_OUTPUT_TOO_LARGE", "识别文字超过 100,000 字，请减少图片数量")
    return combined


def split_ocr_text(content: str, total_inputs: int) -> tuple[str | None, list[tuple[int, str]]]:
    """Recover ordered OCR inputs from persisted Markdown, including existing 0006 sources."""
    matches = list(re.finditer(r"(?m)^# 图片 (\d+) OCR\s*$", content))
    if len(matches) != total_inputs:
        raise ImageValidationError("SOURCE_INPUTS_INVALID", "已保存的图片文字分段不完整")
    context = content[:matches[0].start()].strip() if matches else ""
    if context.startswith("# 用户补充说明"):
        context = context[len("# 用户补充说明"):].strip()
    inputs: list[tuple[int, str]] = []
    for position, match in enumerate(matches):
        index = int(match.group(1))
        end = matches[position + 1].start() if position + 1 < len(matches) else len(content)
        text = content[match.end():end].strip()
        if index != position + 1 or not text:
            raise ImageValidationError("SOURCE_INPUTS_INVALID", "已保存的图片文字顺序或内容无效")
        inputs.append((index, text))
    return context or None, inputs
