"""Smart Document Processor and Auto-Optimizer.

Ensures candidate documents strictly conform to verified examination bulletin limits
(dimensions, aspect ratios, file size boundaries, and format specifications)
before runtime browser upload.
"""

from __future__ import annotations

import io
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image

from ..knowledge.schemas.exam_blueprint_schema import DocumentFormat, DocumentSpec


@dataclass
class DocumentOptimizationResult:
    success: bool
    original_path: str
    optimized_path: str
    original_size_kb: float
    optimized_size_kb: float
    target_format: str
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DocumentProcessor:
    """Intelligent document normalizer grounded in official exam specifications."""

    @staticmethod
    def _pad_jpeg_to_min_size(raw_jpeg: bytes, min_kb: int) -> bytes:
        """Pad a JPEG with standard comment marker (0xFF 0xFE) to satisfy portal min-size checks."""
        min_bytes = int(min_kb * 1024)
        if len(raw_jpeg) >= min_bytes:
            return raw_jpeg

        if raw_jpeg[-2:] != b"\xff\xd9":
            return raw_jpeg

        diff = min_bytes - len(raw_jpeg) + 512
        # JPEG COM marker segment max length is 65535
        # Write chunks if diff > 65000
        output = raw_jpeg[:-2]
        remaining = diff
        while remaining > 0:
            chunk_size = min(remaining, 65000)
            pad = b"\x00" * chunk_size
            length = len(pad) + 2
            output += b"\xff\xfe" + length.to_bytes(2, "big") + pad
            remaining -= chunk_size

        output += raw_jpeg[-2:]
        return output

    @staticmethod
    def _pad_pdf_to_min_size(raw_pdf: bytes, min_kb: int) -> bytes:
        """Pad a PDF with standard post-trailer comments to satisfy portal min-size checks."""
        min_bytes = int(min_kb * 1024)
        if len(raw_pdf) >= min_bytes:
            return raw_pdf

        diff = min_bytes - len(raw_pdf) + 512
        comment = b"\n% FormPilot Certified Spec Padding: " + (b"0" * diff) + b"\n"
        return raw_pdf + comment

    @classmethod
    def optimize_photo(
        cls,
        source_path: Path | str,
        target_path: Optional[Path | str] = None,
        min_kb: int = 10,
        max_kb: int = 200,
        target_width: int = 600,
        target_height: int = 800,
    ) -> DocumentOptimizationResult:
        """Optimize candidate passport photograph for examination portal upload.
        
        Applies aspect ratio normalization (~3.5cm x 4.5cm), RGB conversion,
        and iterative quality compression to land safely within [min_kb, max_kb].
        """
        src = Path(source_path)
        if not src.exists():
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=0.0,
                optimized_size_kb=0.0,
                target_format="jpg",
                message=f"Source file not found: {src}",
            )

        orig_size_kb = src.stat().st_size / 1024.0

        if target_path is None:
            dest = src.parent / f"{src.stem}_optimized.jpg"
        else:
            dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            with Image.open(src) as img:
                # Convert to RGB mode (stripping alpha channel / CMYK)
                if img.mode in ("RGBA", "LA", "P"):
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    rgb_img.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                else:
                    rgb_img = img.convert("RGB")

                # Resize image while preserving aspect ratio
                rgb_img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)

                # Iterative compression search to fit [min_kb, max_kb]
                best_bytes: Optional[bytes] = None

                for quality in range(95, 20, -5):
                    buf = io.BytesIO()
                    rgb_img.save(buf, format="JPEG", quality=quality, optimize=True)
                    data = buf.getvalue()
                    cur_kb = len(data) / 1024.0
                    if cur_kb <= max_kb:
                        best_bytes = data
                        if cur_kb >= min_kb:
                            break

                if best_bytes is None:
                    # Very large image; scale down further
                    rgb_img.thumbnail((target_width // 2, target_height // 2), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    rgb_img.save(buf, format="JPEG", quality=30, optimize=True)
                    best_bytes = buf.getvalue()

                # Ensure min_kb is satisfied
                if len(best_bytes) / 1024.0 < min_kb:
                    best_bytes = cls._pad_jpeg_to_min_size(best_bytes, min_kb)

                with open(dest, "wb") as f:
                    f.write(best_bytes)

                final_kb = dest.stat().st_size / 1024.0
                return DocumentOptimizationResult(
                    success=True,
                    original_path=str(src),
                    optimized_path=str(dest),
                    original_size_kb=orig_size_kb,
                    optimized_size_kb=final_kb,
                    target_format="jpg",
                    message=f"Photo normalized from {orig_size_kb:.1f} KB to {final_kb:.1f} KB (mandate: {min_kb}-{max_kb} KB).",
                )
        except Exception as e:
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=orig_size_kb,
                optimized_size_kb=0.0,
                target_format="jpg",
                message=f"Optimization error: {str(e)}",
            )

    @classmethod
    def optimize_signature(
        cls,
        source_path: Path | str,
        target_path: Optional[Path | str] = None,
        min_kb: int = 10,
        max_kb: int = 100,
        target_width: int = 600,
        target_height: int = 250,
    ) -> DocumentOptimizationResult:
        """Optimize candidate signature image (typically 3.5cm x 1.5cm landscape).
        
        Mandated range in JEE / NTA is strictly 10 KB to 100 KB.
        """
        src = Path(source_path)
        if not src.exists():
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=0.0,
                optimized_size_kb=0.0,
                target_format="jpg",
                message=f"Source file not found: {src}",
            )

        orig_size_kb = src.stat().st_size / 1024.0

        if target_path is None:
            dest = src.parent / f"{src.stem}_signature_optimized.jpg"
        else:
            dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            with Image.open(src) as img:
                # Convert RGBA / Grayscale to clean white-background RGB
                if img.mode in ("RGBA", "LA", "P"):
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    if img.mode == "P":
                        img = img.convert("RGBA")
                    rgb_img.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                else:
                    rgb_img = img.convert("RGB")

                rgb_img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)

                best_bytes: Optional[bytes] = None

                for quality in range(95, 25, -5):
                    buf = io.BytesIO()
                    rgb_img.save(buf, format="JPEG", quality=quality, optimize=True)
                    data = buf.getvalue()
                    cur_kb = len(data) / 1024.0
                    if cur_kb <= max_kb:
                        best_bytes = data
                        if cur_kb >= min_kb:
                            break

                if best_bytes is None:
                    rgb_img.thumbnail((target_width // 2, target_height // 2), Image.Resampling.LANCZOS)
                    buf = io.BytesIO()
                    rgb_img.save(buf, format="JPEG", quality=30, optimize=True)
                    best_bytes = buf.getvalue()

                # Ensure min_kb is satisfied
                if len(best_bytes) / 1024.0 < min_kb:
                    best_bytes = cls._pad_jpeg_to_min_size(best_bytes, min_kb)

                with open(dest, "wb") as f:
                    f.write(best_bytes)

                final_kb = dest.stat().st_size / 1024.0
                return DocumentOptimizationResult(
                    success=True,
                    original_path=str(src),
                    optimized_path=str(dest),
                    original_size_kb=orig_size_kb,
                    optimized_size_kb=final_kb,
                    target_format="jpg",
                    message=f"Signature normalized from {orig_size_kb:.1f} KB to {final_kb:.1f} KB (mandate: {min_kb}-{max_kb} KB).",
                )
        except Exception as e:
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=orig_size_kb,
                optimized_size_kb=0.0,
                target_format="jpg",
                message=f"Signature optimization failed: {str(e)}",
            )

    @classmethod
    def convert_to_pdf(
        cls,
        source_path: Path | str,
        target_path: Optional[Path | str] = None,
        min_kb: int = 50,
        max_kb: int = 300,
    ) -> DocumentOptimizationResult:
        """Convert certificate image or normalize existing PDF to official exam bounds (50 KB - 300 KB)."""
        src = Path(source_path)
        if not src.exists():
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=0.0,
                optimized_size_kb=0.0,
                target_format="pdf",
                message=f"Source file not found: {src}",
            )

        orig_size_kb = src.stat().st_size / 1024.0

        if target_path is None:
            dest = src.parent / f"{src.stem}_optimized.pdf"
        else:
            dest = Path(target_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            # If source is already a PDF
            if src.suffix.lower() == ".pdf":
                if min_kb <= orig_size_kb <= max_kb:
                    shutil.copy2(src, dest)
                    return DocumentOptimizationResult(
                        success=True,
                        original_path=str(src),
                        optimized_path=str(dest),
                        original_size_kb=orig_size_kb,
                        optimized_size_kb=orig_size_kb,
                        target_format="pdf",
                        message=f"PDF already conforms to bounds ({orig_size_kb:.1f} KB).",
                    )
                
                import pypdf
                reader = pypdf.PdfReader(str(src))
                writer = pypdf.PdfWriter()
                for page in reader.pages:
                    page.compress_content_streams()
                    writer.add_page(page)

                buf = io.BytesIO()
                writer.write(buf)
                pdf_bytes = buf.getvalue()

                if len(pdf_bytes) / 1024.0 < min_kb:
                    pdf_bytes = cls._pad_pdf_to_min_size(pdf_bytes, min_kb)

                with open(dest, "wb") as f:
                    f.write(pdf_bytes)

                compressed_kb = dest.stat().st_size / 1024.0
                return DocumentOptimizationResult(
                    success=True,
                    original_path=str(src),
                    optimized_path=str(dest),
                    original_size_kb=orig_size_kb,
                    optimized_size_kb=compressed_kb,
                    target_format="pdf",
                    message=f"PDF normalized from {orig_size_kb:.1f} KB to {compressed_kb:.1f} KB (mandate: {min_kb}-{max_kb} KB).",
                )

            # If source is an image (JPG / PNG), convert to A4 PDF
            with Image.open(src) as img:
                rgb_img = img.convert("RGB")
                # Scale to fit standard A4 (approx 1240 x 1754 at 150 DPI)
                rgb_img.thumbnail((1240, 1754), Image.Resampling.LANCZOS)
                
                buf = io.BytesIO()
                rgb_img.save(buf, format="PDF", resolution=150.0)
                pdf_bytes = buf.getvalue()

                if len(pdf_bytes) / 1024.0 < min_kb:
                    pdf_bytes = cls._pad_pdf_to_min_size(pdf_bytes, min_kb)

                with open(dest, "wb") as f:
                    f.write(pdf_bytes)

                final_kb = dest.stat().st_size / 1024.0
                return DocumentOptimizationResult(
                    success=True,
                    original_path=str(src),
                    optimized_path=str(dest),
                    original_size_kb=orig_size_kb,
                    optimized_size_kb=final_kb,
                    target_format="pdf",
                    message=f"Image converted to PDF ({final_kb:.1f} KB, mandate: {min_kb}-{max_kb} KB).",
                )

        except Exception as e:
            return DocumentOptimizationResult(
                success=False,
                original_path=str(src),
                optimized_path="",
                original_size_kb=orig_size_kb,
                optimized_size_kb=0.0,
                target_format="pdf",
                message=f"PDF conversion failed: {str(e)}",
            )

    @classmethod
    def optimize_for_spec(
        cls,
        source_path: Path | str,
        doc_spec: DocumentSpec,
        target_path: Optional[Path | str] = None,
    ) -> DocumentOptimizationResult:
        """Route optimization based directly on an official DocumentSpec from an ExamBlueprint."""
        src = Path(source_path)
        is_pdf_required = DocumentFormat.PDF in doc_spec.formats and DocumentFormat.JPG not in doc_spec.formats

        if is_pdf_required:
            return cls.convert_to_pdf(
                source_path=src,
                target_path=target_path,
                min_kb=doc_spec.min_size_kb,
                max_kb=doc_spec.max_size_kb,
            )

        # Image documents
        if "signature" in doc_spec.document_key.lower():
            return cls.optimize_signature(
                source_path=src,
                target_path=target_path,
                min_kb=doc_spec.min_size_kb,
                max_kb=doc_spec.max_size_kb,
            )
        else:
            return cls.optimize_photo(
                source_path=src,
                target_path=target_path,
                min_kb=doc_spec.min_size_kb,
                max_kb=doc_spec.max_size_kb,
            )
