"""Спартанский кастомный попап темпа Octavia (без диалогов Blender)."""
import blf
from .draw_utils import draw_rect

BPM_PRESETS = (90, 110, 120, 128, 140, 174)
BPM_MIN = 30
BPM_MAX = 300


def bpm_layout(px, py, pw, ph):
    """Геометрия зон попапа — одна карта для draw и hit-test."""
    title_y = py - 22
    value_y = py - 62
    btn_w, btn_h = 28, 26
    minus = (px + 14, value_y - 4, btn_w, btn_h)
    plus = (px + pw - 14 - btn_w, value_y - 4, btn_w, btn_h)
    slider_y = py - 100
    slider = (px + 15, slider_y, pw - 30, 8)
    presets_y = py - 130
    chip_w = (pw - 24 - 5 * 4) // 6
    chips = []
    cx = px + 12
    for i, bpm in enumerate(BPM_PRESETS):
        chips.append((bpm, cx, presets_y, chip_w, 18))
        cx += chip_w + 4
    return {
        "title_y": title_y,
        "value_y": value_y,
        "minus": minus,
        "plus": plus,
        "slider": slider,
        "chips": chips,
        "presets_y": presets_y,
    }


def hit_bpm_control(mx, my, px, py, pw, ph):
    """Вернёт 'MINUS' | 'PLUS' | 'SLIDER' | ('PRESET', bpm) | None."""
    L = bpm_layout(px, py, pw, ph)
    bx, by, bw, bh = L["minus"]
    if bx <= mx <= bx + bw and by <= my <= by + bh:
        return "MINUS"
    bx, by, bw, bh = L["plus"]
    if bx <= mx <= bx + bw and by <= my <= by + bh:
        return "PLUS"
    sx, sy, sw, sh = L["slider"]
    if sx <= mx <= sx + sw and sy - 4 <= my <= sy + sh + 4:
        return "SLIDER"
    for bpm, cx, cy, cw, ch in L["chips"]:
        if cx <= mx <= cx + cw and cy <= my <= cy + ch:
            return ("PRESET", bpm)
    return None


def apply_bpm_from_slider(scene, mx, px, pw):
    track_w = pw - 30
    pct = (mx - (px + 15)) / track_w if track_w > 0 else 0.0
    pct = max(0.0, min(1.0, pct))
    scene.octavia_bpm = int(round(BPM_MIN + pct * (BPM_MAX - BPM_MIN)))


def draw_bpm_popup(layout, px, py, pw, ph, hovered_btn="NONE"):
    scene = layout["scene"]
    font_id = layout["font_id"]
    bpm = int(getattr(scene, "octavia_bpm", 120))
    L = bpm_layout(px, py, pw, ph)

    draw_rect(px, py - ph, pw, ph, (0.85, 0.45, 0.15, 1.0))
    draw_rect(px + 1, py - ph + 1, pw - 2, ph - 2, (0.07, 0.07, 0.08, 1.0))

    blf.size(font_id, 11)
    blf.color(font_id, 0.85, 0.45, 0.15, 1.0)
    blf.position(font_id, px + 15, L["title_y"], 0)
    blf.draw(font_id, "TEMPO")

    blf.size(font_id, 9)
    blf.color(font_id, 0.45, 0.45, 0.48, 1.0)
    blf.position(font_id, px + pw - 55, L["title_y"], 0)
    blf.draw(font_id, "BPM")

    # − / значение / +
    mx_, my_, mw, mh = L["minus"]
    minus_hot = hovered_btn == "MINUS"
    draw_rect(mx_, my_, mw, mh, (0.0, 0.45, 0.5, 0.35) if minus_hot else (0.14, 0.14, 0.16, 1.0))
    blf.size(font_id, 14)
    if minus_hot:
        blf.color(font_id, 0.0, 0.9, 1.0, 1.0)
    else:
        blf.color(font_id, 0.75, 0.75, 0.78, 1.0)
    blf.position(font_id, mx_ + 8, my_ + 6, 0)
    blf.draw(font_id, "−")

    blf.size(font_id, 22)
    blf.color(font_id, 0.95, 0.95, 0.97, 1.0)
    label = str(bpm)
    # Грубое центрирование без measure (blf dimensions нестабильны в draw handler)
    blf.position(font_id, px + pw // 2 - (7 * len(label)), L["value_y"], 0)
    blf.draw(font_id, label)

    px_, py_, pw_, ph_ = L["plus"]
    plus_hot = hovered_btn == "PLUS"
    draw_rect(px_, py_, pw_, ph_, (0.0, 0.45, 0.5, 0.35) if plus_hot else (0.14, 0.14, 0.16, 1.0))
    blf.size(font_id, 14)
    if plus_hot:
        blf.color(font_id, 0.0, 0.9, 1.0, 1.0)
    else:
        blf.color(font_id, 0.75, 0.75, 0.78, 1.0)
    blf.position(font_id, px_ + 8, py_ + 5, 0)
    blf.draw(font_id, "+")

    # Слайдер
    sx, sy, sw, sh = L["slider"]
    draw_rect(sx, sy, sw, sh, (0.09, 0.10, 0.12, 1.0))
    pct = (bpm - BPM_MIN) / float(BPM_MAX - BPM_MIN)
    fill = int(sw * max(0.0, min(1.0, pct)))
    if fill > 0:
        draw_rect(sx, sy, fill, sh, (0.85, 0.45, 0.15, 1.0))
    knob_x = sx + fill - 3
    draw_rect(knob_x, sy - 3, 6, sh + 6, (0.95, 0.7, 0.35, 1.0))

    # Пресеты
    for preset, cx, cy, cw, ch in L["chips"]:
        is_active = preset == bpm
        is_hot = hovered_btn == f"PRESET_{preset}"
        if is_active:
            bg = (0.85, 0.45, 0.15, 0.35)
        elif is_hot:
            bg = (0.0, 0.45, 0.5, 0.30)
        else:
            bg = (0.12, 0.13, 0.15, 1.0)
        draw_rect(cx, cy, cw, ch, bg)
        blf.size(font_id, 9)
        if is_active:
            blf.color(font_id, 1.0, 0.75, 0.4, 1.0)
        elif is_hot:
            blf.color(font_id, 0.0, 0.9, 1.0, 1.0)
        else:
            blf.color(font_id, 0.55, 0.55, 0.58, 1.0)
        blf.position(font_id, cx + 4, cy + 4, 0)
        blf.draw(font_id, str(preset))
