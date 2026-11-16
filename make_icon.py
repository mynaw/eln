# -*- coding: utf-8 -*-
"""生成 assets/app.ico：苯环 → 反应箭头 → 实验记录卡。

    python make_icon.py

三块元素对应 ELN 的核心：化学结构、反应式绘制、电子记录。
只依赖 Pillow；图标文件已随项目带上，改完配色重跑一次即可。
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "app.ico")

S = 512
BLUE = (31, 78, 156, 255)
WHITE = (255, 255, 255, 255)
PALE = (206, 220, 240, 255)
INK_LIGHT = (198, 214, 236, 255)


def hexagon(cx, cy, r, rot=-90):
    return [(cx + r * math.cos(math.radians(rot + 60 * i)),
             cy + r * math.sin(math.radians(rot + 60 * i))) for i in range(6)]


def inner_edge(p, q, cx, cy, frac=0.22):
    """沿 p→q 朝环心内缩的平行线，用来画苯环的三条双键。"""
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    return ((p[0] + frac * (cx - mx), p[1] + frac * (cy - my)),
            (q[0] + frac * (cx - mx), q[1] + frac * (cy - my)))


def build() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 底板
    d.rounded_rectangle((16, 16, S - 16, S - 16), radius=104, fill=BLUE)
    d.rounded_rectangle((34, 34, S - 34, S - 34), radius=88,
                        outline=(255, 255, 255, 45), width=4)

    # 左：苯环
    cx, cy, r = 146, 202, 66
    pts = hexagon(cx, cy, r)
    d.line(pts + [pts[0]], fill=WHITE, width=14, joint="curve")
    for i in (0, 2, 4):
        a, b = inner_edge(pts[i], pts[(i + 1) % 6], cx, cy)
        d.line((a, b), fill=WHITE, width=9)
    for p in (pts[1], pts[3], pts[5]):
        d.ellipse((p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9), fill=PALE)

    # 中：反应箭头
    d.line((244, cy, 314, cy), fill=WHITE, width=16)
    d.polygon([(338, cy), (306, cy - 22), (306, cy + 22)], fill=WHITE)

    # 右：实验记录卡
    d.rounded_rectangle((356, 116, 472, 292), radius=18, fill=(255, 255, 255, 248))
    d.rounded_rectangle((374, 138, 454, 148), radius=5, fill=(120, 160, 215, 255))
    d.rounded_rectangle((374, 162, 428, 206), radius=8, fill=(214, 228, 246, 255))
    mini = hexagon(401, 184, 13)                 # 卡片里的结构缩略图
    d.line(mini + [mini[0]], fill=BLUE, width=3, joint="curve")
    for y, w in ((222, 80), (244, 80), (266, 52)):
        d.rounded_rectangle((374, y, 374 + w, y + 9), radius=4, fill=INK_LIGHT)

    # 下：三条长短不一的记录行，像台账列表
    for y, w in ((344, 392), (384, 330), (424, 366)):
        d.rounded_rectangle((60, y, 60 + w, y + 13), radius=6,
                            fill=(255, 255, 255, 70))
        d.ellipse((40, y - 1, 54, y + 13), fill=(255, 255, 255, 130))

    return im.resize((256, 256), Image.LANCZOS)


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    build().save(OUT, format="ICO",
                 sizes=[(16, 16), (32, 32), (48, 48), (64, 64),
                        (128, 128), (256, 256)])
    print("已生成", OUT)


if __name__ == "__main__":
    main()
