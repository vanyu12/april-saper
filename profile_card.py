"""Карточка профиля: человечек в надетой одежде.

Если Pillow не установлен — render() вернёт None, и бот покажет старую картинку.
"""
from __future__ import annotations

import pathlib

try:
    from PIL import Image, ImageDraw
except Exception:  # Pillow нет на машине
    Image = None
    ImageDraw = None

W, H = 720, 960
BLACK = "#141414"
WHITE = "#ffffff"
OUT_DIR = pathlib.Path("data/profiles")

COLORS = {
    "cap_rag": "#6b6b6b",
    "cap_basic": "#2f7d32",
    "cap_brand": "#1b1b1b",
    "hat_panama": "#d9c27a",
    "hat_fedora": "#3a2a1a",
    "hat_gucci": "#1b1b1b",
    "top_rag": "#9e9e9e",
    "top_basic": "#4a7bd0",
    "top_shirt": "#f3f3f3",
    "top_gucci": "#3f7d3a",
    "legs_rag": "#8d8d8d",
    "legs_jeans": "#2f4f7a",
    "legs_suit": "#232323",
    "legs_gucci": "#1c1c1c",
    "feet_rag": "#8a8a8a",
    "feet_basic": "#f0f0f0",
    "feet_sneakers": "#ffffff",
    "feet_gucci": "#1c1c1c",
}


def _pick(worn: dict, slot: str) -> str:
    return (worn.get(slot) or "").strip()


def _leaf(d, x, y, size=14) -> None:
    d.polygon([(x, y - size), (x + size * 0.7, y), (x, y + size),
               (x - size * 0.7, y)], outline="#1d4d1a", width=3)


def _body(d, worn: dict) -> None:
    top = _pick(worn, "top")
    legs = _pick(worn, "legs")
    feet = _pick(worn, "feet")

    if legs:
        color = COLORS.get(legs, "#555555")
        d.rectangle((298, 690, 348, 852), fill=color, outline=BLACK, width=7)
        d.rectangle((372, 690, 422, 852), fill=color, outline=BLACK, width=7)
        if legs == "legs_gucci":
            for y in (720, 770, 820):
                for x in (312, 386):
                    _leaf(d, x, y, 9)
        if legs == "legs_rag":
            d.ellipse((310, 750, 336, 776), fill=WHITE, outline=BLACK, width=3)
            d.ellipse((384, 800, 404, 820), fill=WHITE, outline=BLACK, width=3)
    else:
        for x in (322, 398):
            d.line((x, 690, x, 852), fill=BLACK, width=9)

    if feet:
        color = COLORS.get(feet, "#dddddd")
        d.ellipse((286, 844, 356, 884), fill=color, outline=BLACK, width=7)
        d.ellipse((364, 844, 434, 884), fill=color, outline=BLACK, width=7)
        if feet == "feet_sneakers":
            d.line((296, 868, 346, 868), fill="#2f6fd0", width=5)
            d.line((374, 868, 424, 868), fill="#2f6fd0", width=5)
    else:
        for x in (320, 396):
            d.line((x - 26, 856, x + 18, 856), fill=BLACK, width=9)

    if top:
        color = COLORS.get(top, "#4a7bd0")
        d.polygon([(250, 414), (470, 414), (486, 700), (234, 700)],
                  fill=color, outline=BLACK, width=7)
        d.polygon([(250, 414), (196, 556), (238, 574), (264, 466)],
                  fill=color, outline=BLACK, width=7)
        d.polygon([(470, 414), (524, 556), (482, 574), (456, 466)],
                  fill=color, outline=BLACK, width=7)
        d.arc((314, 396, 406, 446), 0, 180, fill=BLACK, width=7)
        if top == "top_gucci":
            for y in (470, 530, 590, 650):
                for x in (290, 360, 430):
                    _leaf(d, x, y, 13)
        if top == "top_rag":
            d.ellipse((286, 560, 318, 592), fill=WHITE, outline=BLACK, width=3)
            d.ellipse((404, 520, 428, 544), fill=WHITE, outline=BLACK, width=3)
        if top == "top_shirt":
            d.line((360, 470, 360, 690), fill=BLACK, width=4)
            for y in (520, 580, 640):
                d.ellipse((352, y, 368, y + 16), fill=WHITE, outline=BLACK, width=3)
    else:
        d.line((300, 470, 420, 470), fill=BLACK, width=8)
        d.line((360, 470, 360, 690), fill=BLACK, width=8)

    d.line((252, 440, 204, 616), fill=BLACK, width=10)
    d.line((468, 440, 516, 616), fill=BLACK, width=10)
    for dx in (-14, 0, 14):
        d.line((204 + dx, 616, 204 + dx * 1.4, 650), fill=BLACK, width=7)
        d.line((516 + dx, 616, 516 + dx * 1.4, 650), fill=BLACK, width=7)


def _head(d, worn: dict) -> None:
    d.line((360, 344, 360, 414), fill=BLACK, width=9)
    d.ellipse((250, 124, 470, 344), fill=WHITE, outline=BLACK, width=9)

    if _pick(worn, "eyes"):
        d.ellipse((282, 206, 350, 264), fill=BLACK)
        d.ellipse((370, 206, 438, 264), fill=BLACK)
        d.line((350, 232, 370, 232), fill=BLACK, width=6)
        d.line((282, 226, 258, 214), fill=BLACK, width=6)
        d.line((438, 226, 462, 214), fill=BLACK, width=6)

    cap = _pick(worn, "cap")
    hat = _pick(worn, "hat")
    if cap:
        color = COLORS.get(cap, "#2f7d32")
        d.pieslice((252, 128, 468, 300), 180, 360, fill=color,
                   outline=BLACK, width=7)
        d.polygon([(252, 214), (196, 232), (198, 252), (268, 240)],
                  fill=color, outline=BLACK, width=7)
        if cap == "cap_brand":
            d.line((270, 210, 450, 210), fill="#d8b64a", width=7)
    elif hat:
        color = COLORS.get(hat, "#3a2a1a")
        d.polygon([(210, 216), (510, 216), (486, 240), (234, 240)],
                  fill=color, outline=BLACK, width=7)
        if hat == "hat_fedora":
            d.polygon([(272, 216), (280, 140), (440, 140), (448, 216)],
                      fill=color, outline=BLACK, width=7)
            d.line((280, 176, 440, 176), fill="#5a4230", width=6)
        else:
            d.arc((260, 140, 460, 260), 180, 360, fill=color, width=9)
            d.line((300, 160, 420, 160), fill="#b79a55", width=6)


def render(worn: dict, user_id: int | str) -> str | None:
    """Рисует карточку и возвращает путь к PNG (None, если Pillow нет)."""
    if Image is None or ImageDraw is None:
        return None
    import hashlib
    import json

    key = hashlib.md5(
        json.dumps({k: worn.get(k) or "" for k in sorted(worn)},
                   sort_keys=True).encode()).hexdigest()[:10]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"profile_{user_id}_{key}.png"
    if path.exists():
        return str(path)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    _body(d, worn)
    _head(d, worn)
    img.save(path, "PNG")
    return str(path)
