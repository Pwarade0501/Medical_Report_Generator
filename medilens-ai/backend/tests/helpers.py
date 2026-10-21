"""Synthetic test files. No real medical data."""
import struct
import zlib
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def text_pdf_bytes(*page_texts: str) -> bytes:
    """Build small text PDFs for extraction tests without external fixtures."""
    writer = PdfWriter()
    from pypdf.generic import DictionaryObject
    for text in page_texts:
        page = writer.add_blank_page(width=612, height=792)
        font = writer._add_object(  # pypdf's writer object registry is needed for test fixtures
            DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        )
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        stream = DecodedStreamObject()
        safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def raster_text_image_bytes(text: str) -> bytes:
    image = Image.new("RGB", (400, 100), "white")
    ImageDraw.Draw(image).text((12, 30), text, fill="black", font=ImageFont.load_default())
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def scanned_pdf_bytes(*page_texts: str) -> bytes:
    images = []
    for text in page_texts:
        image = Image.new("RGB", (400, 100), "white")
        ImageDraw.Draw(image).text((12, 30), text, fill="black", font=ImageFont.load_default())
        images.append(image)
    output = BytesIO()
    images[0].save(output, format="PDF", save_all=True, append_images=images[1:])
    return output.getvalue()


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


# Valid 1x1 RGB PNG
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    + _png_chunk(b"IEND", b"")
)

# Synthetic JPEG: real SOI/APP0 header and EOI marker. Our validation only checks
# the signature, so this is enough without needing an imaging library.
JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    + b"\x00" * 32
    + b"\xff\xd9"
)
