# -*- coding: utf-8 -*-
"""从 18 张表情素材生成文档预览图 `docs/images/phoebe3d_views.png`。

用法（Windows 下用带 Pillow 的 Python）：

    python tools/make_phoebe3d_doc_preview.py

行为：
- 读 `frontend/assets/phoebe3d/{情绪}_{视角}.png` 共 18 张，按「6 情绪（行）× 3 视角（列）」
  拼成一张浅底联系表，直接覆盖 `docs/images/phoebe3d_views.png`；
- 只读素材、只写这一张 doc 图，不碰立牌素材本身；
- 素材缺失时打印缺哪张并退出（退出码 1），不会写出半张图。

素材被 `tools/crop_phoebe3d_sheet.py` 重裁后，跑一次本脚本即可刷新文档图。
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "frontend", "assets", "phoebe3d")
OUT_PATH = os.path.join(ROOT, "docs", "images", "phoebe3d_views.png")

# 与 phoebe3d.js 的 MOODS / MOOD_VIEWS 顺序保持一致
MOODS = [
    ("happy", "开心"),
    ("sad", "难过"),
    ("like", "点赞"),
    ("cheer", "加油"),
    ("cute", "可爱"),
    ("encourage", "鼓励"),
]
VIEWS = [("front", "正面"), ("side", "侧面"), ("back", "背面")]

CANVAS = (338, 210)          # 素材统一画布，见 manifest.json
SCALE = 0.8                  # 文档图上的缩放
TILE_W = int(CANVAS[0] * SCALE)
TILE_H = int(CANVAS[1] * SCALE)
GAP = 16
MARGIN = 18
LABEL_W = 96                 # 左侧中文标签列
BACKGROUND = (245, 246, 250)
LABEL_COLOR = (70, 74, 90)
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size), True
            except OSError:
                continue
    return ImageFont.load_default(), False


def main():
    missing = []
    for mood, _label in MOODS:
        for view, _vlabel in VIEWS:
            path = os.path.join(ASSETS, mood + "_" + view + ".png")
            if not os.path.exists(path):
                missing.append(mood + "_" + view + ".png")
    if missing:
        print("缺素材，未生成：" + "、".join(missing))
        return 1

    rows, cols = len(MOODS), len(VIEWS)
    width = MARGIN * 2 + LABEL_W + cols * TILE_W + (cols - 1) * GAP
    height = MARGIN * 2 + rows * TILE_H + (rows - 1) * GAP
    sheet = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font, has_label = load_font(26)

    for row, (mood, label) in enumerate(MOODS):
        top = MARGIN + row * (TILE_H + GAP)
        if has_label:
            text_w = draw.textlength(label, font=font)
            draw.text(
                (MARGIN + LABEL_W - 12 - text_w, top + TILE_H // 2 - 15),
                label,
                fill=LABEL_COLOR,
                font=font,
            )
        for col, (view, _vlabel) in enumerate(VIEWS):
            left = MARGIN + LABEL_W + col * (TILE_W + GAP)
            with Image.open(os.path.join(ASSETS, mood + "_" + view + ".png")) as raw:
                sprite = raw.convert("RGBA")
            if sprite.size != (TILE_W, TILE_H):
                sprite = sprite.resize((TILE_W, TILE_H), Image.LANCZOS)
            sheet.paste(sprite, (left, top), sprite)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    sheet.save(OUT_PATH)
    print("wrote %s %dx%d" % (OUT_PATH, sheet.size[0], sheet.size[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
