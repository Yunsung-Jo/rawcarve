#!/usr/bin/env python3
"""비교 몽타주 생성기.

보고서(docs/reports/)의 대표 그림인 **격자형 before/after 몽타주**를 표준 형식으로 만든다.
변하는 것(표본 수·조건 수·라벨 텍스트·이미지·블러 여부)은 스펙으로 받고,
고정된 것(레이아웃·맑은 고딕·크기·WebP 출력)은 이 파일에 박아 둔다.

스펙(JSON):
{
  "title": "<작업명> — <맥락(커밋/수정)>",
  "columns": ["기존 (carve 조기종료)", "신규 (EOI 검증 + budget 0)"],
  "rows": [
    {"label": "0x9906A000.jpg", "sub": "회색 0.918 → 0.002",
     "cells": ["a.png", "b.png"]},
    {"label": "0x96B61000.jpg", "sub": "회색 0.999 → 0.032",
     "cells": ["c.png", "d.png"]}
  ],
  "blur": 3,            # 전체 기본 블러 반지름(0=블러 없음). 생략 시 0.
  "out": "docs/reports/assets/2026-06-29-carve-eoi-comparison.webp"
}

- 각 row의 "cells" 길이는 "columns" 길이와 같아야 한다.
- row에 "blur"를 넣으면 그 행만 전체 기본값을 덮어쓴다.
- row의 "sub"는 선택(핵심 지표 before→after를 작게·회색으로).
- 셀 이미지는 미리 디코딩된 PNG 등을 넘긴다(이 스크립트는 조립만 한다).

사용:
    python tools/montage.py spec.json
    python tools/montage.py spec.json --out other.webp
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# --- 고정 스타일 (보고서 몽타주 표준) ---------------------------------------
WIDTH = 1800            # 전체 폭(px). 높이는 행 수에 비례해 자동.
MARGIN = 28             # 바깥 여백
LABEL_W = 250           # 행 라벨(파일명) 칸 너비. 오프셋 파일명(~230px) + 여백 기준.
GAP = 16               # 셀 사이 가로 간격
ROW_GAP = 22            # 행 사이 세로 간격
TITLE_FS = 40           # 제목
TITLE_GAP = 54          # 제목 아래 ~ 열 머리글 사이 여백
HEAD_FS = 30            # 열 머리글
LABEL_FS = 30           # 파일명
SUB_FS = 22             # 지표(회색)
BG = (255, 255, 255)
INK = (33, 33, 33)      # 제목·머리글·파일명
SUB_INK = (130, 130, 130)  # 지표
PLACEHOLDER = (150, 150, 150)  # 셀 이미지 누락 시 회색 박스

_FONT_DIRS = [r"C:\Windows\Fonts", "/usr/share/fonts/truetype/malgun", ""]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ["malgunbd.ttf", "malgun.ttf"] if bold else ["malgun.ttf"]
    for name in names:
        for base in _FONT_DIRS:
            path = os.path.join(base, name) if base else name
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_cell(path: str, cell_w: int, blur: float):
    """셀 이미지를 열어 cell_w 폭으로 맞추고(가로 기준) 블러를 적용한다."""
    if path and os.path.isfile(path):
        img = Image.open(path).convert("RGB")
    else:
        if path:
            print(f"  [warn] 셀 이미지 없음 → 회색 박스: {path}", file=sys.stderr)
        img = Image.new("RGB", (4, 3), PLACEHOLDER)  # 4:3 회색
    w, h = img.size
    new_h = max(1, round(cell_w * h / w))
    img = img.resize((cell_w, new_h), Image.LANCZOS)
    if blur and blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=blur))
    return img


def build(spec: dict) -> Image.Image:
    cols = spec["columns"]
    rows = spec["rows"]
    ncol = len(cols)
    if ncol < 1:
        raise ValueError("columns가 비어 있다.")
    default_blur = float(spec.get("blur", 0) or 0)
    width = int(spec.get("width", WIDTH))

    avail = width - 2 * MARGIN - LABEL_W
    cell_w = int((avail - GAP * (ncol - 1)) / ncol)
    if cell_w < 1:
        raise ValueError("폭이 너무 작거나 열이 너무 많다.")

    f_title = _font(TITLE_FS, bold=True)
    f_head = _font(HEAD_FS)
    f_label = _font(LABEL_FS, bold=True)
    f_sub = _font(SUB_FS)

    # 행별로 셀을 로드·스케일해 행 높이를 정한다.
    row_imgs: list[list[Image.Image]] = []
    row_h: list[int] = []
    for r in rows:
        cells = r.get("cells", [])
        if len(cells) != ncol:
            raise ValueError(
                f"행 '{r.get('label','?')}'의 cells({len(cells)})가 columns({ncol})와 다르다."
            )
        blur = float(r.get("blur", default_blur) or 0)
        imgs = [_load_cell(p, cell_w, blur) for p in cells]
        row_imgs.append(imgs)
        row_h.append(max(im.height for im in imgs))

    title_top = MARGIN
    header_y = title_top + TITLE_FS + TITLE_GAP
    grid_y0 = header_y + HEAD_FS + 14
    total_h = grid_y0 + sum(row_h) + ROW_GAP * (len(rows) - 1) + MARGIN

    canvas = Image.new("RGB", (width, total_h), BG)
    draw = ImageDraw.Draw(canvas)

    # 제목(좌측 정렬)
    draw.text((MARGIN, title_top), spec.get("title", ""), font=f_title, fill=INK)

    # 열 x 좌표
    x_cell0 = MARGIN + LABEL_W
    col_x = [x_cell0 + i * (cell_w + GAP) for i in range(ncol)]

    # 열 머리글(각 열 중앙 정렬)
    for i, head in enumerate(cols):
        tw = draw.textlength(head, font=f_head)
        cx = col_x[i] + (cell_w - tw) / 2
        draw.text((cx, header_y), head, font=f_head, fill=INK)

    # 행: 라벨 + 셀
    y = grid_y0
    for ridx, r in enumerate(rows):
        h = row_h[ridx]
        # 라벨 블록(파일명 + 지표)을 행 높이에 세로 중앙 정렬
        label = r.get("label", "")
        sub = r.get("sub", "")
        block_h = LABEL_FS + (SUB_FS + 8 if sub else 0)
        ly = y + max(0, (h - block_h) // 2)
        draw.text((MARGIN, ly), label, font=f_label, fill=INK)
        if sub:
            draw.text((MARGIN, ly + LABEL_FS + 8), sub, font=f_sub, fill=SUB_INK)
        # 셀(상단 정렬)
        for i, im in enumerate(row_imgs[ridx]):
            canvas.paste(im, (col_x[i], y))
        y += h + ROW_GAP

    return canvas


def main(argv=None):
    ap = argparse.ArgumentParser(description="보고서 비교 몽타주 생성기")
    ap.add_argument("spec", help="스펙 JSON 경로")
    ap.add_argument("--out", help="출력 경로 덮어쓰기(스펙의 out 대신)")
    args = ap.parse_args(argv)

    with open(args.spec, encoding="utf-8") as fp:
        spec = json.load(fp)

    out = args.out or spec.get("out")
    if not out:
        ap.error("출력 경로가 없다(--out 또는 스펙의 out).")

    canvas = build(spec)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    canvas.save(out, "WEBP", quality=88, method=6)
    print(f"몽타주 저장: {out}  ({canvas.width}x{canvas.height})")


if __name__ == "__main__":
    main()
