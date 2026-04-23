#!/usr/bin/env python3
"""Qualia Journal OGP image generator.

生成物: ~/Desktop/Qualia-work/ogp/default.png (1200x630)

コンセプト:
  拡張されたフィボナッチ螺旋 (1,1,2,3,5,8,13,21) を画面いっぱいに展開。
  各矩形にフィボナッチ数を注記し、螺旋そのものを設計図として提示する。
  「Qualia Journal」の文字は 21×21 の最大矩形の中に組まれ、
  螺旋の分割レイアウト = 誌面のグリッドという入れ子構造を作る。
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "default.png"

W, H = 1200, 630

# ブランドパレット
CREAM = (250, 248, 243)
BLACK = (26, 18, 8)
DARK = (61, 48, 32)
RED = (139, 26, 26)
GRID_LINE = (238, 230, 213)   # 極薄
RECT_LINE = (180, 165, 140)   # 薄タン
LABEL_COLOR = (150, 135, 110) # 注記用くすみ
WHITE = (255, 255, 255)
# Q の差し色(飽和したゴールド / 赤との類似色・歴史的配色)
ACCENT_Q = (212, 160, 40)   # #d4a028

# フォント
FONT_TITLE = "/System/Library/Fonts/Supplemental/Didot.ttc"
FONT_LABEL = "/System/Library/Fonts/Supplemental/Didot.ttc"

# フィボナッチ螺旋(n=8 まで): 1,1,2,3,5,8,13,21 → 全体 34u x 21u
U = 28
SPIRAL_W = 34 * U    # 952
SPIRAL_H = 21 * U    # 588
SPIRAL_X = (W - SPIRAL_W) // 2   # 124
SPIRAL_Y = (H - SPIRAL_H) // 2   # 21


def main():
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # ── 1. 背景グリッド ──
    for x in range(0, W + 1, U):
        d.line([(x, 0), (x, H)], fill=GRID_LINE, width=1)
    for y in range(0, H + 1, U):
        d.line([(0, y), (W, y)], fill=GRID_LINE, width=1)

    # ── 2. 21×21(最大矩形)を赤で塗りつぶし = 色反転パネル ──
    sq21_x = SPIRAL_X + 13 * U
    sq21_y = SPIRAL_Y
    sq21_w = 21 * U
    sq21_h = 21 * U
    d.rectangle([sq21_x, sq21_y, sq21_x + sq21_w, sq21_y + sq21_h], fill=RED)

    # ── 3. 他のフィボナッチ矩形(枠線のみ、21×21 は除く) ──
    squares = [
        (0, 0, 8),       # S6
        (8, 0, 5),       # S5
        (10, 5, 3),      # S4
        (8, 6, 2),       # S3
        (8, 5, 1),       # S2
        (9, 5, 1),       # S1
        (0, 8, 13),      # S7
    ]
    for (x, y, s) in squares:
        x1 = SPIRAL_X + x * U
        y1 = SPIRAL_Y + y * U
        x2 = x1 + s * U
        y2 = y1 + s * U
        d.rectangle([x1, y1, x2, y2], outline=RECT_LINE, width=1)

    # ── 4. 最小1×1を赤で塗る(螺旋の種) ──
    sx1 = SPIRAL_X + 9 * U
    sy1 = SPIRAL_Y + 5 * U
    d.rectangle([sx1, sy1, sx1 + U, sy1 + U], fill=RED)

    # ── 5. フィボナッチ弧 ──
    # 21×21 内の S8 弧だけ、赤→クリームに反転。
    arcs = [
        (8, 8, 8, 180, 270, RED),      # S6
        (8, 5, 5, 270, 360, RED),      # S5
        (10, 5, 3, 0, 90, RED),        # S4
        (10, 6, 2, 90, 180, RED),      # S3
        (9, 6, 1, 180, 270, RED),      # S2
        (9, 6, 1, 270, 360, RED),      # S1
        (13, 8, 13, 90, 180, RED),     # S7
        (13, 0, 21, 0, 90, CREAM),     # S8: 反転パネル内なのでクリーム
    ]
    for (cx_u, cy_u, r_u, a_start, a_end, color) in arcs:
        cx = SPIRAL_X + cx_u * U
        cy = SPIRAL_Y + cy_u * U
        r = r_u * U
        bbox = [cx - r, cy - r, cx + r, cy + r]
        d.arc(bbox, a_start, a_end, fill=color, width=3)

    # ── 5. フィボナッチ数の注記(各矩形の左上) ──
    try:
        font_label = ImageFont.truetype(FONT_LABEL, 14, index=0)
    except (OSError, IndexError):
        font_label = ImageFont.load_default()

    # 注記位置: 各矩形の左上内側に小さく
    # 21×21(反転パネル)のラベルだけクリームにして可読性を保つ
    label_positions = [
        (0, 0, "8", LABEL_COLOR),
        (8, 0, "5", LABEL_COLOR),
        (10, 5, "3", LABEL_COLOR),
        (8, 6, "2", LABEL_COLOR),
        (9, 5, "1", LABEL_COLOR),
        (0, 8, "13", LABEL_COLOR),
        (13, 0, "21", CREAM),
    ]
    for (x_u, y_u, label, color) in label_positions:
        lx = SPIRAL_X + x_u * U + 6
        ly = SPIRAL_Y + y_u * U + 4
        d.text((lx, ly), label, font=font_label, fill=color)

    # ── 6. タイトル「Qualia / Journal」(21×21 矩形の中に2行組) ──
    # 21×21 を誌面のレイアウト・グリッドとして使い、
    # 左端に寄せた大きな2行タイポで重量感を出す。
    try:
        font_title = ImageFont.truetype(FONT_TITLE, 140, index=1)  # Italic
    except (OSError, IndexError):
        font_title = ImageFont.truetype(FONT_TITLE, 140, index=0)

    ascent, descent = font_title.getmetrics()
    line_height = ascent + descent
    line_gap = int(line_height * 0.02)

    # 左端寄せ
    text_x = sq21_x + 34

    # 垂直位置: Journal の下端を 21×21 の底辺から 60px 上に
    text_bottom = sq21_y + sq21_h - 60
    text2_y = text_bottom - line_height
    text1_y = text2_y - line_height - line_gap

    # 全文字に 1px 縁取り。黒よりさらに薄い茶(DARK #3d3020)で主張を弱める。
    stroke_kwargs = dict(stroke_width=1, stroke_fill=DARK)

    # 1行目: Q をアクセント色 + "ualia" をクリーム
    q_width = font_title.getlength("Q")
    d.text((text_x, text1_y), "Q", font=font_title, fill=ACCENT_Q, **stroke_kwargs)
    d.text((text_x + q_width, text1_y), "ualia", font=font_title, fill=CREAM, **stroke_kwargs)

    # 2行目: Journal を右に1文字分(J幅)スライド
    j_shift = font_title.getlength("J")
    d.text((text_x + j_shift, text2_y), "Journal", font=font_title, fill=CREAM, **stroke_kwargs)

    img.save(OUT, "PNG", optimize=True)
    print(f"saved: {OUT}  ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
