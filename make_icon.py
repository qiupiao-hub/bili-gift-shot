# -*- coding: utf-8 -*-
"""生成粉色小猫图标：app.ico + docs/logo.png"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
S = 1024


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def main() -> None:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top, bottom = (255, 214, 231), (255, 110, 158)
    for y in range(S):
        d.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    # 圆角遮罩
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=210, fill=255)
    img.putalpha(mask)

    d = ImageDraw.Draw(img)
    white = (255, 255, 255, 255)
    pink_line = (255, 190, 214, 255)
    # 耳朵
    d.polygon([(250, 470), (300, 250), (450, 380)], fill=white)
    d.polygon([(774, 470), (724, 250), (574, 380)], fill=white)
    d.polygon([(300, 430), (325, 320), (400, 385)], fill=(255, 205, 224, 255))
    d.polygon([(724, 430), (699, 320), (624, 385)], fill=(255, 205, 224, 255))
    # 脸
    d.ellipse([228, 350, 796, 860], fill=white)
    # 蝴蝶结
    d.polygon([(690, 300), (830, 360), (690, 420)], fill=(255, 131, 174, 255))
    d.polygon([(600, 320), (690, 360), (600, 400)], fill=(255, 131, 174, 255))
    d.ellipse([640, 330, 700, 390], fill=(255, 92, 141, 255))
    # 眼睛
    d.ellipse([380, 545, 440, 635], fill=(90, 58, 70, 255))
    d.ellipse([584, 545, 644, 635], fill=(90, 58, 70, 255))
    # 鼻子
    d.ellipse([492, 645, 532, 675], fill=(255, 92, 141, 255))
    # 胡须
    for dy in (-18, 12, 42):
        d.line([(230, 620 + dy), (350, 640 + dy)], fill=pink_line, width=10)
        d.line([(794, 620 + dy), (674, 640 + dy)], fill=pink_line, width=10)
    # 相机小标（右下角）
    d.ellipse([690, 690, 940, 940], fill=(255, 255, 255, 255))
    d.ellipse([690, 690, 940, 940], outline=(255, 131, 174, 255), width=14)
    d.rounded_rectangle([748, 770, 882, 862], radius=24, fill=(255, 92, 141, 255))
    d.ellipse([790, 786, 840, 836], fill=(255, 255, 255, 255))
    d.rectangle([772, 750, 858, 778], fill=(255, 92, 141, 255))

    big = img.resize((256, 256), Image.LANCZOS)
    big.save(ROOT / "app.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    big.save(ROOT / "docs" / "logo.png")
    print("ok", ROOT / "app.ico", big.size)


if __name__ == "__main__":
    main()
