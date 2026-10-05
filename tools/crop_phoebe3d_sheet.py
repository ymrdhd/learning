# -*- coding: utf-8 -*-
"""从「6 情绪 × 3 视角」宫格图裁出 18 张透明 PNG 立牌素材。

输入：frontend/assets/phoebe3d/source.png（1536×1024 宫格图）
      左列为情绪标签（开心/难过/点赞/加油/可爱/鼓励），右侧三列为 正面/侧面/背面
输出：frontend/assets/phoebe3d/{mood}_{view}.png  （统一画布、底对齐、背景透明）
      frontend/assets/phoebe3d/manifest.json      （素材清单）

整体思路（先抠图、再按内容分格，不依赖网格切割精度）：
  1. 用 32×32 分块、块内中位数迭代的二维背景场估计背景色
     （背景是浅色渐变，逐行单色模型会留下 L1 系统偏差，实测会把白帽子啃掉 21%）；
  1b. 先把 18 个「正面 / 侧面 / 背面」文字标签按已知几何矩形 + 低饱和判据抹成背景色
     （标签与发丝只隔 1~2px，闭运算后并进公仔连通域，只能靠几何位置清除）；
  2. 「到背景色的 L1 距离」+「局部梯度」双判据得到可通行区域，从图像四边泛洪，
     得到与画布边缘连通的背景域 —— 公仔内部的浅色区域（白帽子高光等）
     因为被轮廓梯度阻断而不会被误判成背景；
  3b. 另外追加一条平滑亮区通道（低梯度 + 比背景亮 + 不暗）：
     行间白色分隔带与公仔脚下亮面都是「亮且极平」，不放行会把同列 6 个公仔
     连成一个 1024px 高的连通域；
  3c. 背景域整体置为全透明（不是「按距离半透明」，否则浅色渐变背景会留下灰色矩形底），
     前景域闭运算填缝 + 0.7px 高斯羽化做抗锯齿；
  4. 对羽化边缘做去背景混色（unpremultiply），避免深色页面上出现浅色光晕；
  5. 连通域分析：丢掉噪声碎片与细划痕，把剩下的组件
     （面积最大者为主组件，其余按 bbox 最近距离归并）按所在行列归到 18 个格子里，
     取并集 bbox 裁切。
"""

import json
import os
import sys
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "frontend", "assets", "phoebe3d")
SHEET = os.path.join(ASSETS, "source.png")

MOODS = ["happy", "sad", "like", "cheer", "cute", "encourage"]
MOOD_LABELS = ["开心", "难过", "点赞", "加油", "可爱", "鼓励"]
VIEWS = ["front", "side", "back"]
VIEW_LABELS = ["正面", "侧面", "背面"]

LABEL_W = 192                 # 左侧情绪标签列宽，抠图时整列忽略
ROW_H = 1024.0 / 6.0          # 每行内容高度
COL_CUTS = [640, 1088]        # 内容三列的分界（仅用于把组件归类到格子）

BG_TOL = 26                   # 到局部背景色的 L1 距离 ≤ 此值，视为「背景候选」
GRAD_BLOCK = 30               # 梯度 > 此值的像素阻断背景泛洪（保护白帽/发丝等浅色主体）
# 行间的白色分隔带、以及公仔脚下的亮面，比背景亮 45~190 且几乎无梯度（grad 中位 4~7），
# 用 BG_TOL 判不出来 —— 它们会把同一列的 6 个公仔连成一条 1024px 高的连通域。
# 追加一条「比背景亮 + 极低梯度」的通行通道：分隔带被吞成背景，公仔轮廓因梯度高仍被阻断。
FLAT_BRIGHT_GRAD = 20         # 平滑亮区的梯度上限
FLAT_BRIGHT_TOL = 240         # 平滑亮区到背景色的 L1 距离上限
FLAT_BRIGHT_MIN = 4           # 至少要比背景亮这么多，避免吞掉公仔的浅色暗部
FLAT_BRIGHT_DARK = 2          # 允许的「比背景暗」总量上限
BG_BLOCK = 32                 # 二维背景场的分块尺寸
BG_KEEP = 0.30                # 每块取「离粗背景最近」的 30% 像素做迭代修剪
FEATHER_RADIUS = 0.7
ALPHA_CUTOFF = 0.22           # 羽化后的极弱边缘直接丢弃
MIN_COMPONENT_AREA = 100      # 小于此面积的连通域视为噪点（水印文字另行判定）
PAD = 8
UNMIX_MIN_ALPHA = 0.25        # 低于此覆盖率不再解混（避免放大噪声）

# 「正面 / 侧面 / 背面」标签块的实测位置（整图坐标，18 格规律完全一致）：
# 三列 x 区间固定，六行 y 区间固定。先按颜色判据把它们还原成行背景色，
# 否则标签与公仔头发只隔 1~2px，闭运算后会被并进同一条连通域，
# 裁切时把整块浅色标签带进素材（实测 cute_side 就发生了这件事）。
LABEL_COLS = [(498, 533), (915, 951), (1390, 1426)]
LABEL_ROWS = [(140, 158), (305, 323), (470, 489), (648, 667), (808, 826), (986, 1005)]
LABEL_ERASE_PAD = 3           # 标签矩形外扩，覆盖抗锯齿边缘
LABEL_ERASE_SAT = 34.0        # 标签整体低饱和（18 格里高饱和像素仅 29 个）
LABEL_ERASE_MIN_V = 40.0
NOISE_MIN_THICKNESS = 5       # 任一方向厚度不足此值的连通域视为划痕/背景漏网


def estimate_bg_map(tile, block=BG_BLOCK):
    """分块估计二维背景色场，再双线性上采样成逐像素背景图。

    背景是「行内横向渐变 + 行间过渡带」的二维平滑场。逐行单色模型会留下
    20~40 的 L1 系统偏差，而白色帽顶与背景的真实色差只有约 21 —— 于是帽顶
    被误判成背景、泛洪钻进去啃掉一大块（实测 21.5% 的帽顶像素）。
    分块估计把背景像素的 dist 压到接近 0，白色帽顶就重新凸显出来了（降到 2.7%）。
    """
    h, w, _ = tile.shape
    bh = (h + block - 1) // block
    bw = (w + block - 1) // block
    grid = np.empty((bh, bw, 3), np.float32)
    for by in range(bh):
        for bx in range(bw):
            b = tile[by * block:(by + 1) * block, bx * block:(bx + 1) * block].reshape(-1, 3)
            c = np.median(b, axis=0)
            for _ in range(4):
                d = np.abs(b - c).sum(axis=1)
                sel = b[d <= np.percentile(d, BG_KEEP * 100)]
                if len(sel) < 8:
                    break
                c = sel.mean(axis=0)
            grid[by, bx] = c
    up = Image.fromarray(np.rint(np.clip(grid, 0, 255)).astype(np.uint8), "RGB").resize(
        (w, h), Image.BILINEAR)
    return np.asarray(up).astype(np.float32)


def erase_labels(tile, bgmap):
    """把 18 个「正面 / 侧面 / 背面」标签块就地还原成背景色，返回抹除的像素数。

    标签是「半透明浅色圆角底 + 深灰小字」，整体低饱和；公仔的黄色头发、
    蓝色蝴蝶结等彩色主体饱和度远高于阈值，所以判据只会命中标签本身。
    """
    h, w, _ = tile.shape
    hits = 0
    for ry0, ry1 in LABEL_ROWS:
        y0 = max(0, ry0 - LABEL_ERASE_PAD)
        y1 = min(h, ry1 + LABEL_ERASE_PAD + 1)
        for cx0, cx1 in LABEL_COLS:
            x0 = max(0, cx0 - LABEL_W - LABEL_ERASE_PAD)
            x1 = min(w, cx1 - LABEL_W + LABEL_ERASE_PAD + 1)
            if x0 >= x1 or y0 >= y1:
                continue
            patch = tile[y0:y1, x0:x1, :]
            sat = patch.max(axis=2) - patch.min(axis=2)
            v = patch.max(axis=2)
            m = (sat <= LABEL_ERASE_SAT) & (v >= LABEL_ERASE_MIN_V)
            hits += int(m.sum())
            patch[m] = bgmap[(y0 + y1) // 2, (x0 + x1) // 2][None, :]
    return hits


def flood_from_border(passable):
    """从四边开始、只在 passable 像素上扩散，返回可达区域。"""
    reach = np.zeros_like(passable)
    reach[0, :] = passable[0, :]
    reach[-1, :] = passable[-1, :]
    reach[:, 0] = passable[:, 0]
    reach[:, -1] = passable[:, -1]
    for _ in range(6000):
        grown = reach.copy()
        grown[1:, :] |= reach[:-1, :]
        grown[:-1, :] |= reach[1:, :]
        grown[:, 1:] |= reach[:, :-1]
        grown[:, :-1] |= reach[:, 1:]
        grown &= passable
        if np.array_equal(grown, reach):
            break
        reach = grown
    return reach


def label_components(mask):
    """8-连通标记，返回 (labels, [(area, x0, y0, x1, y1), ...])（下标 0 为空）。"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    comps = [None]
    cur = 0
    for sy in range(h):
        row = mask[sy]
        if not row.any():
            continue
        for sx in np.flatnonzero(row):
            sx = int(sx)
            if lab[sy, sx]:
                continue
            cur += 1
            lab[sy, sx] = cur
            q = deque([(sy, sx)])
            n = 0
            x0 = x1 = sx
            y0 = y1 = sy
            while q:
                cy, cx = q.popleft()
                n += 1
                if cx < x0:
                    x0 = cx
                if cx > x1:
                    x1 = cx
                if cy < y0:
                    y0 = cy
                if cy > y1:
                    y1 = cy
                for dy in (-1, 0, 1):
                    ny = cy + dy
                    if ny < 0 or ny >= h:
                        continue
                    for dx in (-1, 0, 1):
                        nx = cx + dx
                        if nx < 0 or nx >= w:
                            continue
                        if mask[ny, nx] and not lab[ny, nx]:
                            lab[ny, nx] = cur
                            q.append((ny, nx))
            comps.append((n, x0, y0, x1, y1))
    return lab, comps


def cut_region(tile):
    """返回 (rgba_uint8, hard_fg, bgmap)。tile 为 float32 RGB。"""
    h, w, _ = tile.shape
    bgmap = estimate_bg_map(tile)
    hits = erase_labels(tile, bgmap)
    print("  标签预处理：抹除低饱和像素 %d 个" % hits)
    dist = np.abs(tile - bgmap).sum(axis=2)

    gx = np.zeros((h, w), np.float32)
    gy = np.zeros((h, w), np.float32)
    gx[:, 1:-1] = np.abs(tile[:, 2:, :] - tile[:, :-2, :]).sum(axis=2)
    gy[1:-1, :] = np.abs(tile[2:, :, :] - tile[:-2, :, :]).sum(axis=2)
    grad = gx + gy

    passable = (dist <= BG_TOL) & (grad <= GRAD_BLOCK)
    d3 = tile - bgmap
    bright = np.clip(d3, 0, None).sum(axis=2)
    dark = np.clip(-d3, 0, None).sum(axis=2)
    passable |= ((grad <= FLAT_BRIGHT_GRAD) & (dist <= FLAT_BRIGHT_TOL)
                 & (bright >= FLAT_BRIGHT_MIN) & (dark <= FLAT_BRIGHT_DARK))
    bg_area = flood_from_border(passable)
    hard_fg = ~bg_area

    # 闭运算填 1px 缝隙，减少碎片
    m = Image.fromarray((hard_fg * 255).astype(np.uint8), "L")
    m = m.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    hard_fg = np.asarray(m) > 127

    cov = np.asarray(m.filter(ImageFilter.GaussianBlur(FEATHER_RADIUS))).astype(np.float32) / 255.0
    cov[cov < ALPHA_CUTOFF] = 0.0

    # 去背景混色：C = a*F + (1-a)*B  =>  F = (C - (1-a)*B) / a
    a = cov[:, :, None]
    safe = np.maximum(a, UNMIX_MIN_ALPHA)
    fg = (tile - (1.0 - safe) * bgmap) / safe
    rgb = np.where(a > 0, np.clip(fg, 0, 255), 0.0)

    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[:, :, :3] = np.rint(rgb).astype(np.uint8)
    rgba[:, :, 3] = np.rint(cov * 255.0).astype(np.uint8)
    return rgba, hard_fg, bgmap


def is_watermark(region, comp):
    """判断连通域是否为格子里的「正面 / 侧面 / 背面」标签。

    该标签是一块约 36×19px 的半透明浅色圆角底 + 深灰小字，18 个格子里
    尺寸与面积高度一致（面积 542–623，宽 36–37，高 18–20，饱和度 ≤14），
    与公仔主体的彩色装饰（饱和度 17–77、尺寸各异）区分明显。
    """
    n, x0, y0, x1, y1 = comp
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    if not (30 <= w <= 46 and 14 <= h <= 24 and 380 <= n <= 820):
        return False
    patch = region[y0:y1 + 1, x0:x1 + 1].reshape(-1, 3)
    med = np.median(patch, axis=0)
    return float(med.max() - med.min()) <= 32.0


def cell_of(comp):
    """组件所属的 (行, 列)：按 bbox 质心归位。"""
    n, x0, y0, x1, y1 = comp
    cx = (x0 + x1) * 0.5 + LABEL_W
    cy = (y0 + y1) * 0.5
    col = 0 if cx < COL_CUTS[0] else (1 if cx < COL_CUTS[1] else 2)
    row = min(5, max(0, int(cy // ROW_H)))
    return row, col


def bbox_gap(a, b):
    """两个 bbox 之间的最小间距（像素）。"""
    _, ax0, ay0, ax1, ay1 = a
    _, bx0, by0, bx1, by1 = b
    dx = max(0, ax0 - bx1, bx0 - ax1)
    dy = max(0, ay0 - by1, by0 - ay1)
    return float((dx * dx + dy * dy) ** 0.5)


def main():
    if not os.path.exists(SHEET):
        raise SystemExit("缺少源图：%s" % SHEET)
    sheet = np.array(Image.open(SHEET).convert("RGB")).astype(np.float32)
    sh, sw, _ = sheet.shape
    if (sw, sh) != (1536, 1024):
        print("警告：源图尺寸为 %dx%d，预期 1536x1024" % (sw, sh))
    region = np.ascontiguousarray(sheet[:, LABEL_W:, :])

    rgba, hard_fg, _bgmap = cut_region(region)
    _lab, comps = label_components(hard_fg)
    print("连通域总数：%d" % (len(comps) - 1))

    kept = []
    dropped_area = 0
    dropped_thin = 0
    dropped_text = []
    for c in comps[1:]:
        n, x0, y0, x1, y1 = c
        if n < MIN_COMPONENT_AREA:
            dropped_area += 1
            continue
        if min(x1 - x0 + 1, y1 - y0 + 1) <= NOISE_MIN_THICKNESS:
            dropped_thin += 1
            continue
        if is_watermark(region, c):
            dropped_text.append(c)
            continue
        kept.append(c)
    print("丢弃碎片 %d 个、细划痕 %d 个、标签 %d 个；保留 %d 个组件" % (
        dropped_area, dropped_thin, len(dropped_text), len(kept)))
    for c in sorted(dropped_text, key=lambda c: (c[2], c[1])):
        r, col = cell_of(c)
        print("  标签 @row%d col%d 面积%d 尺寸%dx%d" % (
            r, col, c[0], c[3] - c[1] + 1, c[4] - c[2] + 1))

    # 先按行列挑出主组件（面积最大者），其余小组件（星星/爱心/彩球等装饰）
    # 归给 bbox 距离最近的主组件，避免质心刚好压线时被分到隔壁格子。
    primaries = {}
    leftovers = []
    for c in sorted(kept, key=lambda c: -c[0]):
        pos = cell_of(c)
        if pos in primaries:
            leftovers.append(c)
        else:
            primaries[pos] = c
    cells = {k: [v] for k, v in primaries.items()}
    far = []
    for c in leftovers:
        best = None
        best_d = None
        for k, p in primaries.items():
            d = bbox_gap(c, p)
            if best_d is None or d < best_d:
                best_d, best = d, k
        if best_d > 260.0:
            far.append((c, best, best_d))
        cells[best].append(c)
    for c, k, d in far:
        print("  警告：组件 bbox(%d,%d,%d,%d) 距离最近主组件 row%d col%d 仍有 %.0fpx" % (
            c[1] + LABEL_W, c[2], c[3] + LABEL_W, c[4], k[0], k[1], d))

    missing = [(r, c) for r in range(6) for c in range(3) if (r, c) not in cells]
    if missing:
        print("警告：以下格子没有找到组件：%s" % missing)

    bboxes = {}
    for (row, col), cs in cells.items():
        x0 = min(c[1] for c in cs)
        y0 = min(c[2] for c in cs)
        x1 = max(c[3] for c in cs) + 1
        y1 = max(c[4] for c in cs) + 1
        bboxes[(row, col)] = (x0, y0, x1, y1)

    max_w = max(b[2] - b[0] for b in bboxes.values())
    max_h = max(b[3] - b[1] for b in bboxes.values())
    canvas_w = max_w + PAD * 2
    canvas_h = max_h + PAD * 2
    print("统一画布：%dx%d（最大内容 bbox %dx%d）" % (canvas_w, canvas_h, max_w, max_h))

    out_files = {}
    for row, mood in enumerate(MOODS):
        for col, view in enumerate(VIEWS):
            bx0, by0, bx1, by1 = bboxes[(row, col)]
            crop = rgba[by0:by1, bx0:bx1, :]
            canvas = np.zeros((canvas_h, canvas_w, 4), np.uint8)
            ch, cw = crop.shape[0], crop.shape[1]
            oy = canvas_h - PAD - ch          # 底对齐
            ox = (canvas_w - cw) // 2         # 水平居中
            canvas[oy:oy + ch, ox:ox + cw, :] = crop
            key = "%s_%s" % (mood, view)
            name = "%s.png" % key
            Image.fromarray(canvas, "RGBA").save(os.path.join(ASSETS, name), optimize=True)
            out_files[key] = name
            print("  %-16s 内容 %dx%d 位置 x[%d..%d] y[%d..%d]" % (
                key, cw, ch, bx0 + LABEL_W, bx1 + LABEL_W, by0, by1))

    manifest = {
        "source": "用户提供的「菲比 Phoebe」6 情绪 × 3 视角表情立牌宫格图",
        "source_image": "source.png",
        "generated_by": "tools/crop_phoebe3d_sheet.py（32×32 分块迭代估出的 2D 背景场 + 「到背景距离 / 局部梯度」双判据 + 从画布边缘泛洪，再补一条「平滑亮区」通道跨过行间白色分隔带与公仔脚下亮面；只把与画布边缘连通的背景域置为透明，白色帽子靠梯度阻断保护不被吃掉）",
        "canvas": [canvas_w, canvas_h],
        "bottom_aligned": True,
        "moods": [{"key": m, "label": MOOD_LABELS[i]} for i, m in enumerate(MOODS)],
        "views": [
            {"key": v, "label": VIEW_LABELS[i], "angle": [0, 90, 180][i], "mirror": False}
            for i, v in enumerate(VIEWS)
        ],
        "frames": [
            {"key": "front", "view": "front", "angle": 0, "mirror": False},
            {"key": "side", "view": "side", "angle": 90, "mirror": False},
            {"key": "back", "view": "back", "angle": 180, "mirror": False},
            {"key": "side-mirror", "view": "side", "angle": 270, "mirror": True},
        ],
        "files": out_files,
        "note": "真实视角只有三个（正面/侧面/背面），270° 由侧面水平镜像补足；"
                "每种情绪三张图共用同一画布且底对齐，切换情绪/旋转时脚底不会跳动。"
                "素材由 1536×1024 宫格图裁切而来，单格公仔主体高约 157px，故立牌按接近 1:1 像素显示。",
        "cell_size": [max_w, max_h],
    }
    with open(os.path.join(ASSETS, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("已写出 18 张素材 + manifest.json")

    # 预览图：深浅棋盘格背景，用于目视检查抠图边缘与白边
    scale = 2
    gap = 12
    pw = len(VIEWS) * (canvas_w * scale + gap) + gap
    ph = len(MOODS) * (canvas_h * scale + gap) + gap
    preview = np.zeros((ph, pw, 3), np.uint8)
    yy, xx = np.mgrid[0:ph, 0:pw]
    checker = (((yy // 10) + (xx // 10)) % 2).astype(np.uint8)
    preview[:, :, 0] = np.where(checker == 0, 40, 150)
    preview[:, :, 1] = np.where(checker == 0, 40, 150)
    preview[:, :, 2] = np.where(checker == 0, 44, 152)
    for mi, mood in enumerate(MOODS):
        for vi, view in enumerate(VIEWS):
            img = Image.open(os.path.join(ASSETS, "%s_%s.png" % (mood, view))).convert("RGBA")
            big = img.resize((canvas_w * scale, canvas_h * scale), Image.LANCZOS)
            arr = np.array(big)
            oy = gap + mi * (canvas_h * scale + gap)
            ox = gap + vi * (canvas_w * scale + gap)
            a = arr[:, :, 3:4].astype(np.float32) / 255.0
            base = preview[oy:oy + arr.shape[0], ox:ox + arr.shape[1], :].astype(np.float32)
            preview[oy:oy + arr.shape[0], ox:ox + arr.shape[1], :] = np.rint(
                arr[:, :, :3] * a + base * (1 - a)).astype(np.uint8)
    prev_path = os.path.join(ROOT, "tools", "_preview_phoebe3d_sheet.png")
    Image.fromarray(preview, "RGB").save(prev_path)
    print("预览图：%s" % prev_path)


if __name__ == "__main__":
    sys.exit(main())
