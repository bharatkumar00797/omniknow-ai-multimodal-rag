"""Regenerate the binary sample assets (PDF datasheet + placeholder PNGs).

The corpus is committed, so this only needs to run when the samples change.
Uses the standard library only: a minimal text PDF and solid-colour PNGs.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

CORPUS = Path(__file__).resolve().parents[1] / "src" / "omniknow" / "data" / "corpus"

PAGES = [
    [
        "X200 Courier Datasheet",
        "The X200 Courier is an autonomous indoor delivery robot for warehouses and hospitals.",
        "Payload capacity: 12 kg. Top speed: 1.8 m/s.",
        "Battery life: 9 hours of continuous operation; full recharge takes 2.5 hours.",
    ],
    [
        "Safety and compliance",
        "The X200 carries ISO 3691-4 certification and stops within 0.5 m of an obstacle.",
        "Warranty: 3 years on the drive unit and 1 year on the battery pack.",
    ],
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[str]]) -> bytes:
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, lines in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        ops = ["BT", "/F1 12 Tf", "16 TL", "72 720 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode()
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    out += trailer.encode()
    return bytes(out)


def build_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    (CORPUS / "products").mkdir(parents=True, exist_ok=True)
    (CORPUS / "products" / "x200-datasheet.pdf").write_bytes(build_pdf(PAGES))
    (CORPUS / "facilities" / "office-floorplan.png").write_bytes(build_png(64, 40, (230, 236, 245)))
    (CORPUS / "engineering" / "fleet-architecture.png").write_bytes(build_png(64, 40, (20, 40, 70)))
    print("sample assets written to", CORPUS)


if __name__ == "__main__":
    main()
