"""Run a disposable real OCR -> draft -> approval smoke test without printing content."""

import hashlib
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from apps.api.app.ai import AIProviderError, BailianAI, BailianOCR, retrieve_candidates
from apps.api.app.image_ingestion import TemporaryImage, combine_ocr_text, image_data_url, validate_image
from apps.api.app.logging_config import configure_logging
from apps.api.app.prompts import EXTRACT_PROMPT_VERSION, MERGE_PROMPT_VERSION, OCR_PROMPT_VERSION
from apps.api.app.store import Store


def main() -> None:
    configure_logging()
    ocr = BailianOCR()
    ai = BailianAI()
    with tempfile.TemporaryDirectory(prefix="nerva-real-image-smoke-") as tempdir:
        root = Path(tempdir)
        image_path = root / "input.png"
        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).multiline_text(
            (40, 45),
            "Nerva OCR smoke test\nKnowledge changes require approval.",
            fill="black",
            spacing=20,
        )
        image.save(image_path, format="PNG")
        media_type, _, _ = validate_image(image_path)
        raw = image_path.read_bytes()
        temporary_image = TemporaryImage(
            sequence=1,
            path=image_path,
            media_type=media_type,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )

        store = Store(f"sqlite+pysqlite:///{(root / 'smoke.db').as_posix()}")
        try:
            user = store.create_user("bailian-image-smoke@nerva.invalid", "Bailian Image Smoke")
            source = store.create_image_source(
                user["id"], title="Nerva OCR Smoke", total_inputs=1,
                ocr_model=ocr.model, ocr_prompt_version=OCR_PROMPT_VERSION,
            )
            store.start_image_ocr(user["id"], source["id"])
            recognized = ocr.recognize(
                image_data_url(temporary_image), source_id=source["id"], sequence=1,
            )
            image_path.unlink()
            combined = combine_ocr_text(None, [recognized.text])
            store.save_ocr_content(user["id"], source["id"], combined)
            extraction = ai.extract(combined, source["title"])
            store.save_extraction(user["id"], source["id"], extraction)
            candidates = retrieve_candidates(
                combined, source["title"], store.list_documents(user["id"]), limit=8,
            )
            proposals = ai.plan(extraction, candidates, source["title"])
            draft = store.create_change_set_for_source(user["id"], source["id"], proposals)
            applied = store.apply_change_set(user["id"], draft["id"], None)
            print({
                "ocr_model": ocr.model,
                "text_model": ai.model,
                "ocr_characters": len(recognized.text),
                "image_tokens": recognized.image_tokens,
                "knowledge_units": len(extraction.units),
                "changes": len(proposals),
                "applied_status": applied["status"],
                "documents": len(store.list_documents(user["id"])),
                "events": len(store.list_events(user["id"])),
            })
        except AIProviderError as exc:
            print({
                "error": exc.code,
                "upstream_status": exc.upstream_status,
                "upstream_code": exc.upstream_code,
                "request_id": exc.request_id,
            })
            raise SystemExit(1) from exc
        finally:
            if image_path.exists():
                image_path.unlink()
            store.close()


if __name__ == "__main__":
    main()
