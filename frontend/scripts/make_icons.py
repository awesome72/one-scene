"""한 장면 앱 아이콘: 잉크색 바탕 위 서사 아크 곡선과 다섯 점 (정점 '의미'만 붉게).

외부 라이브러리 없이 PNG를 만든다 (4배 수퍼샘플링으로 가장자리를 부드럽게).
    cd frontend && python scripts/make_icons.py public   (약 2분)
"""

import math
import struct
import sys
import zlib
from pathlib import Path

INK = (0x16, 0x21, 0x3A)
CURVE = (0x8A, 0x93, 0xA8)
NODE = (0xF7, 0xF7, 0xF4)
MARK = (0xD0, 0x4A, 0x3C)


def bezier(p0, p1, p2, p3, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return out


# ArcCurve.tsx의 viewBox 300×92 좌표: M24 70 C 70 70, 95 24, 150 24 S 230 70, 276 70
PATH = bezier((24, 70), (70, 70), (95, 24), (150, 24)) + bezier((150, 24), (205, 24), (230, 70), (276, 70))[1:]
NODES = [(24, 70), (87, 40), (150, 24), (213, 40), (276, 70)]


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int, inset: float) -> bytes:
    """inset: 바깥 여백 비율 (마스크 아이콘은 안전 영역 안에 그린다)."""
    span = size * (1 - 2 * inset)
    scale = span / 252  # 곡선 가로 폭 24..276
    ox = size * inset - 24 * scale
    oy = size / 2 - 47 * scale  # 곡선 세로 가운데(24..70의 중간)
    pts = [(ox + x * scale, oy + y * scale) for x, y in PATH]
    nodes = [(ox + x * scale, oy + y * scale) for x, y in NODES]
    stroke = 5 * scale
    radius = 15 * scale
    segs = list(zip(pts, pts[1:]))
    ss = 4
    rows = []
    for y in range(size):
        row = bytearray([0])
        # 이 줄 근처의 곡선 조각만 본다 (속도)
        near = [s for s in segs if min(s[0][1], s[1][1]) - stroke - 2 <= y + 1 and max(s[0][1], s[1][1]) + stroke + 2 >= y]
        for x in range(size):
            acc = [0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    px = x + (sx + 0.5) / ss
                    py = y + (sy + 0.5) / ss
                    color = INK
                    if near and min(seg_dist(px, py, a, b) for a, b in near) <= stroke / 2:
                        color = CURVE
                    for i, (nx, ny) in enumerate(nodes):
                        d = math.hypot(px - nx, py - ny)
                        if d <= radius:
                            color = MARK if i == 2 else NODE
                    for c in range(3):
                        acc[c] += color[c]
            row += bytes(int(round(v / (ss * ss))) for v in acc)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def svg() -> str:
    d = "M24 70 C 70 70, 95 24, 150 24 S 230 70, 276 70"
    circles = "".join(
        f'<circle cx="{x}" cy="{y}" r="15" fill="#{"d04a3c" if i == 2 else "f7f7f4"}"/>'
        for i, (x, y) in enumerate(NODES)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300">'
        '<rect width="300" height="300" rx="66" fill="#16213a"/>'
        '<g transform="translate(0 103)">'
        f'<path d="{d}" fill="none" stroke="#8a93a8" stroke-width="5"/>{circles}</g></svg>\n'
    )


if __name__ == "__main__":
    out = Path(sys.argv[1])
    (out / "favicon.svg").write_text(svg(), encoding="utf-8")
    for name, size, inset in [("icon-192.png", 192, 0.12), ("icon-512.png", 512, 0.12),
                              ("icon-maskable-512.png", 512, 0.2), ("apple-touch-icon.png", 180, 0.14)]:
        (out / name).write_bytes(render(size, inset))
        print(name)
