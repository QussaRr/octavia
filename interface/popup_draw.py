"""HUD-попап Octavia: отрисовка в CLIP_EDITOR и VIEW_3D."""

import math
import time

import blf
import bpy

from .draw_utils import draw_rect
from .ghosts import get_preset_labels
from .popup_geometry import (
    ensure_channel_data,
)

# Непрозрачный фон — иначе поверх DAW и VIEW_3D разный «просвет» фона.
POPUP_FILL = (0.07, 0.07, 0.08, 1.0)
POPUP_FILL_RGB = (0.07, 0.07, 0.08)
POPUP_EDGE = (0.0, 0.9, 1.0, 1.0)

# Бэкап theme.editor_border* на время открытого попапа (полоса сплита area).
_seam_chrome_backup = None


def tag_octavia_popup_areas(context, content_dirty=True):
    """Перерисовать CLIP_EDITOR и VIEW_3D в Octavia DAW.

    content_dirty=True  — контент попапа изменился → пересобрать Offscreen.
    content_dirty=False — только позиция (драг окна) → штамп той же текстуры.
    """
    if content_dirty:
        from .popup_offscreen import invalidate_popup_offscreen
        invalidate_popup_offscreen()
    wm = getattr(context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        workspace = getattr(window, "workspace", None)
        if workspace is None or workspace.name != "Octavia DAW":
            continue
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type in {'CLIP_EDITOR', 'VIEW_3D'}:
                area.tag_redraw()


def _theme_ui():
    try:
        return bpy.context.preferences.themes[0].user_interface
    except Exception:
        return None


def apply_popup_seam_chrome():
    """Хамелеон: полоса сплита = цвет заливки попапа, пока HUD открыт/тащится.

    Region POST_PIXEL не может закрасить editor_border (window composite).
    Один theme-цвет не идеален для CLIP+VIEW3D (разный CM) — максимум из theme.
    """
    global _seam_chrome_backup
    ui = _theme_ui()
    if ui is None:
        return
    if _seam_chrome_backup is None:
        _seam_chrome_backup = {
            'editor_border': tuple(ui.editor_border),
            'editor_outline': tuple(ui.editor_outline),
            'editor_outline_active': tuple(ui.editor_outline_active),
        }
    ui.editor_border = POPUP_FILL_RGB
    ui.editor_outline = (0.0, 0.0, 0.0, 0.0)
    ui.editor_outline_active = (0.0, 0.0, 0.0, 0.0)


def restore_popup_seam_chrome():
    """Вернуть theme border после закрытия попапа / unload аддона."""
    global _seam_chrome_backup
    if _seam_chrome_backup is None:
        return
    ui = _theme_ui()
    if ui is not None:
        try:
            ui.editor_border = _seam_chrome_backup['editor_border']
            ui.editor_outline = _seam_chrome_backup['editor_outline']
            ui.editor_outline_active = _seam_chrome_backup['editor_outline_active']
        except Exception:
            pass
    _seam_chrome_backup = None


def dismiss_octavia_popup(context, handler, restore_selection=True):
    """Закрыть HUD-попап и (опционально) вернуть прежнее выделение сцены."""
    if restore_selection:
        scene = getattr(context, "scene", None)
        if scene is not None:
            for o in scene.objects:
                o.select_set(False)
            for o_name in getattr(handler, '_original_selection', []) or []:
                o = scene.objects.get(o_name)
                if o:
                    o.select_set(True)
            orig_act = getattr(handler, '_original_active', None)
            if orig_act and orig_act in scene.objects:
                context.view_layer.objects.active = scene.objects[orig_act]
    handler._active_popup = None
    handler._hovered_mesh_name = None
    handler._hovered_bpm_btn = "NONE"
    handler._hovered_preset_idx = -1
    restore_popup_seam_chrome()
    from .popup_offscreen import free_popup_offscreen
    free_popup_offscreen()
    tag_octavia_popup_areas(context, content_dirty=False)


def draw_octavia_hud_popup(context):
    """Штамп HUD-попапа: Offscreen-фабрика → текстура в текущий region."""
    if not context or not getattr(context, "workspace", None):
        return
    if context.workspace.name != "Octavia DAW":
        return

    region = getattr(context, "region", None)
    if region is None:
        return

    from ..operators.input_handlers.operator import OCTAVIA_OT_ui_handler
    from .popup_offscreen import ensure_popup_texture, blit_popup_texture

    active_popup = getattr(OCTAVIA_OT_ui_handler, '_active_popup', None)
    if active_popup not in {'ADD_CHANNEL', 'PRESETS', 'CHANNEL_SETTINGS', 'BPM'}:
        return

    apply_popup_seam_chrome()

    result = ensure_popup_texture(
        context, OCTAVIA_OT_ui_handler, context.scene, _paint_popup_local,
    )
    if result is None:
        return
    texture, logical_w, logical_h = result
    # CLIP = эталон as-is; VIEW_3D = sRGB→Linear под Overlay FB
    area = getattr(context, "area", None)
    decompensate = bool(area is not None and area.type == 'VIEW_3D')
    blit_popup_texture(
        texture, region, OCTAVIA_OT_ui_handler, context.scene,
        logical_w, logical_h, decompensate=decompensate,
    )
    from .popup_offscreen import restore_region_pixel_matrix
    restore_region_pixel_matrix(region)


def _paint_popup_local(context, OCTAVIA_OT_ui_handler, active_popup, pw, ph):
    """Рисует попап в локальной сетке Offscreen: верх-лево = (0, ph)."""
    scene = context.scene
    layout = {'font_id': 0, 'scene': scene, 'context': context}
    px = 0
    py = ph

    if active_popup == 'BPM':
        from .bpm_popup import draw_bpm_popup
        hovered = getattr(OCTAVIA_OT_ui_handler, '_hovered_bpm_btn', 'NONE')
        draw_bpm_popup(layout, px, py, pw, ph, hovered)
        return

    # Железный стабильный бэкграунд попапа (alpha=1)
    # Рамка внутри буфера (без px-1), чтобы не клиповать Offscreen.
    draw_rect(0, 0, pw, ph, POPUP_EDGE)
    draw_rect(1, 1, pw - 2, ph - 2, POPUP_FILL)

    if active_popup == 'ADD_CHANNEL':
        blf.size(layout['font_id'], 11)
        blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
        blf.position(layout['font_id'], px + 15, py - 25, 0)
        blf.draw(layout['font_id'], "OCTAVIA: BIND MATTER")

        # Исключаем буферы по ID-флагу + анатомическая подстраховка от рантайм-глюков Blender
        meshes = [
            o for o in scene.objects
            if o.type == 'MESH'
            and not o.data.get("is_octavia_buffer", 0)
            and not (o.data and "octavia_voice_id" in o.data.attributes)
        ]
        list_top_y = py - 40
        hovered_mesh = getattr(OCTAVIA_OT_ui_handler, '_hovered_mesh_name', None)

        for idx, obj in enumerate(meshes):
            row_bottom_y = list_top_y - ((idx + 1) * 22)
            is_hovered = (obj.name == hovered_mesh)
            if is_hovered:
                draw_rect(px + 10, row_bottom_y + 2, pw - 20, 20, (0.0, 0.7, 0.8, 0.25))
                blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
            else:
                blf.color(layout['font_id'], 0.75, 0.75, 0.78, 1.0)

            blf.size(layout['font_id'], 12)
            blf.position(layout['font_id'], px + 20, row_bottom_y + 6, 0)
            prefix = "• [TARGET] " if is_hovered else "  [OBJ] "
            blf.draw(layout['font_id'], f"{prefix}{obj.name.upper()}")

    elif active_popup == 'PRESETS':
        target_obj = getattr(OCTAVIA_OT_ui_handler, '_selected_mesh_name', 'UNKNOWN')

        blf.size(layout['font_id'], 10)
        blf.color(layout['font_id'], 0.5, 0.5, 0.55, 1.0)
        blf.position(layout['font_id'], px + 15, py - 20, 0)
        blf.draw(layout['font_id'], f"MATERIA: {target_obj.upper()}")

        back_hovered = getattr(OCTAVIA_OT_ui_handler, '_back_btn_hovered', False)
        draw_rect(px + 10, py - 46, pw - 20, 20, (0.16, 0.17, 0.20, 1.0) if back_hovered else (0.11, 0.12, 0.14, 1.0))
        blf.size(layout['font_id'], 11)
        blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0) if back_hovered else blf.color(layout['font_id'], 0.8, 0.8, 0.82, 1.0)
        blf.position(layout['font_id'], px + 20, py - 42, 0)
        blf.draw(layout['font_id'], "⬅  RETURN TO MATTER")

        active_tab = getattr(OCTAVIA_OT_ui_handler, '_active_tab', 'ORBITS')
        tab_w = (pw - 20) // 3
        tabs_data = [('ORBITS', "🌌 ORB"), ('GEONODES', "🧪 GEO"), ('SHADERS', "💎 SHD")]

        for i, (tab_id, tab_text) in enumerate(tabs_data):
            tab_x = px + 10 + (i * tab_w)
            is_active = (tab_id == active_tab)
            if is_active:
                draw_rect(tab_x, py - 75, tab_w - 2, 22, (0.0, 0.5, 0.6, 0.3))
                draw_rect(tab_x, py - 77, tab_w - 2, 2, (0.0, 0.9, 1.0, 1.0))
                blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
            else:
                draw_rect(tab_x, py - 75, tab_w - 2, 22, (0.10, 0.10, 0.12, 1.0))
                blf.color(layout['font_id'], 0.6, 0.6, 0.62, 1.0)

            blf.size(layout['font_id'], 10)
            blf.position(layout['font_id'], tab_x + 12, py - 70, 0)
            blf.draw(layout['font_id'], tab_text)

        current_items = get_preset_labels(active_tab)
        list_top_y = py - 110
        hovered_item_idx = getattr(OCTAVIA_OT_ui_handler, '_hovered_preset_idx', -1)

        for idx, item_name in enumerate(current_items):
            row_bottom_y = list_top_y - ((idx + 1) * 22)
            is_row_hovered = (idx == hovered_item_idx)
            if is_row_hovered:
                draw_rect(px + 10, row_bottom_y + 2, pw - 20, 20, (0.0, 0.7, 0.8, 0.20))
                blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
            else:
                blf.color(layout['font_id'], 0.7, 0.7, 0.72, 1.0)

            blf.size(layout['font_id'], 11)
            blf.position(layout['font_id'], px + 25, row_bottom_y + 6, 0)
            prefix = "• " if is_row_hovered else "  "
            blf.draw(layout['font_id'], f"{prefix}{item_name}")

    elif active_popup == 'CHANNEL_SETTINGS':
        ch_idx = getattr(OCTAVIA_OT_ui_handler, '_selected_channel_idx', 1)
        target_obj = getattr(OCTAVIA_OT_ui_handler, '_selected_mesh_name', 'UNKNOWN')
        ch_preset = getattr(scene, f"octavia_ch{ch_idx}_preset", "NONE")
        ch_data = scene.octavia_channels_data[ch_idx - 1] if len(scene.octavia_channels_data) >= ch_idx else None

        curr_y = py - 22

        # 🏛️ ЗОНА А: ШАПКА КАНАЛА
        blf.size(layout['font_id'], 11)
        blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
        blf.position(layout['font_id'], px + 15, curr_y, 0)
        blf.draw(layout['font_id'], f"CHANNEL {ch_idx} CONFIG")

        curr_y -= 14
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.5, 0.5, 0.55, 1.0)
        blf.position(layout['font_id'], px + 15, curr_y, 0)
        blf.draw(layout['font_id'], f"OBJ: {target_obj.upper()}  | PRESET: {ch_preset.upper()}")

        curr_y -= 8
        draw_rect(px + 10, curr_y, pw - 20, 1, (0.16, 0.17, 0.20, 1.0))

        # 🎙️ ЗОНА Б: СЕТКА УЛЬТРАКОМПАКТНЫХ МНОГОСТРОЧНЫХ ТАБОВ С КРЕСТИКОМ УДАЛЕНИЯ ✕
        curr_y -= 22
        if ch_data:
            key_frequencies = {}
            for v in ch_data.voices:
                if v.key_code:
                    key_frequencies[v.key_code] = key_frequencies.get(v.key_code, 0) + 1

            tx = px + 10
            for idx, voice in enumerate(ch_data.voices):
                if tx + 64 > px + pw - 15:
                    tx = px + 10
                    curr_y -= 22

                is_active_v = (idx == ch_data.active_voice_idx)
                is_layered = voice.key_code and key_frequencies.get(voice.key_code, 0) > 1

                if is_active_v:
                    tab_bg = (0.0, 0.4, 0.5, 0.25)
                elif is_layered:
                    tab_bg = (0.16, 0.12, 0.18, 1.0)
                else:
                    tab_bg = (0.12, 0.13, 0.15, 1.0)

                draw_rect(tx, curr_y, 64, 18, tab_bg)

                if is_active_v:
                    draw_rect(tx, curr_y, 64, 1, (0.0, 0.9, 1.0, 1.0))
                elif is_layered:
                    draw_rect(tx, curr_y, 64, 1, (0.8, 0.3, 0.9, 0.6))

                blf.size(layout['font_id'], 9)
                if is_active_v:
                    blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
                elif is_layered:
                    blf.color(layout['font_id'], 0.9, 0.5, 1.0, 1.0)
                else:
                    blf.color(layout['font_id'], 0.7, 0.7, 0.72, 1.0)

                layer_dot = "•" if is_layered else ""
                blf.position(layout['font_id'], tx + 4, curr_y + 4, 0)
                blf.draw(layout['font_id'], f"V{idx+1} [{voice.key_code}]{layer_dot}")

                # 🔥 РЕНДЕР КРЕСТИКА УДАЛЕНИЯ ДЛЯ АКТИВНОГО ТАБА (если на канале > 1 голоса)
                if is_active_v and len(ch_data.voices) > 1:
                    blf.color(layout['font_id'], 1.0, 0.3, 0.3, 1.0)  # Сигнальный красный
                    blf.position(layout['font_id'], tx + 53, curr_y + 4, 0)
                    blf.draw(layout['font_id'], "✕")

                tx += 68

            # Кнопка спавна [+]
            if tx + 64 > px + pw - 15:
                tx = px + 10
                curr_y -= 22
            draw_rect(tx, curr_y, 64, 18, (0.16, 0.18, 0.22, 1.0))
            blf.size(layout['font_id'], 10)
            blf.color(layout['font_id'], 0.0, 1.0, 0.5, 1.0)
            blf.position(layout['font_id'], tx + 28, curr_y + 4, 0)
            blf.draw(layout['font_id'], "+")

        curr_y -= 10

        # 🔥 ИНТЕЛЛЕКТУАЛЬНАЯ ВУАЛЬ ОКТАВИИ: Затеняем только ручки, сохраняя окно стабильным!
        if getattr(OCTAVIA_OT_ui_handler, '_waiting_for_voice_key', False):
            overlay_y = curr_y - 10
            overlay_h = ph - (py - overlay_y)

            # Мягко глушим нижнюю конфигурационную зону
            draw_rect(px + 4, py - ph + 4, pw - 8, overlay_h - 8, (0.04, 0.04, 0.05, 1.0))

            # Заставляем рамку всего попапа дорого пульсировать неоном
            pulse = math.sin(time.time() * 12) * 0.3 + 0.7
            draw_rect(0, 0, pw, ph, (0.0, 1.0, 0.5, pulse * 0.5))
            draw_rect(1, 1, pw - 2, ph - 2, POPUP_FILL)

            blf.size(layout['font_id'], 11)
            blf.color(layout['font_id'], 0.0, 1.0, 0.5, pulse)
            blf.position(layout['font_id'], px + 22, py - ph + (overlay_h // 2) + 6, 0)
            blf.draw(layout['font_id'], "[ НАЖМИТЕ КЛАВИШУ ДЛЯ БИНДА ]")

            blf.size(layout['font_id'], 9)
            blf.color(layout['font_id'], 0.5, 0.5, 0.55, 1.0)
            blf.position(layout['font_id'], px + 52, py - ph + (overlay_h // 2) - 14, 0)
            blf.draw(layout['font_id'], "( Нажмите ESC или кликните мимо )")
            return  # Тормозим рендер ручек, вуаль наглухо закрыла управление!

        # Тумблер Neon Preview
        curr_y -= 20
        ghost_active = getattr(OCTAVIA_OT_ui_handler, '_preview_ghost_active', True)
        ghost_text = "👁️ NEON PREVIEW: ACTIVE" if ghost_active else "👁️ NEON PREVIEW: HIDDEN"
        draw_rect(px + 10, curr_y, pw - 20, 16, (0.0, 0.4, 0.5, 0.18) if ghost_active else (0.12, 0.12, 0.14, 1.0))
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0) if ghost_active else blf.color(layout['font_id'], 0.45, 0.45, 0.48, 1.0)
        blf.position(layout['font_id'], px + 20, curr_y + 4, 0)
        blf.draw(layout['font_id'], ghost_text)

        # ФИЛЬТРАЦИЯ МАКРОСОВ ИЗ КЭША
        all_macros = list(scene.octavia_active_macros)
        global_macros = [m for m in all_macros if m.category == 'GLOBAL']
        hold_macros = [m for m in all_macros if m.category == 'HOLD']
        echo_macros = [m for m in all_macros if m.category == 'ECHO']

        active_voice = ch_data.voices[ch_data.active_voice_idx] if (ch_data and len(ch_data.voices) > ch_data.active_voice_idx) else None

        # ─── [СЕКТОР 1] HOLD / PUNCH МАКРОСЫ ───
        curr_y -= 22
        draw_rect(px + 10, curr_y, pw - 20, 16, (0.12, 0.13, 0.15, 1.0))
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.85, 0.40, 0.15, 1.0)
        blf.position(layout['font_id'], px + 15, curr_y + 4, 0)
        blf.draw(layout['font_id'], "PUNCH / HOLD SETTINGS")

        if not hold_macros:
            curr_y -= 20
            blf.size(layout['font_id'], 10)
            blf.color(layout['font_id'], 0.35, 0.35, 0.38, 1.0)
            blf.position(layout['font_id'], px + 25, curr_y + 6, 0)
            blf.draw(layout['font_id'], "НЕТ РУЧЕК УДЕРЖАНИЯ В ГРАФЕ")
        else:
            for m in hold_macros:
                curr_y -= 28
                blf.size(layout['font_id'], 9)
                blf.color(layout['font_id'], 0.85, 0.85, 0.88, 1.0)
                blf.position(layout['font_id'], px + 15, curr_y + 10, 0)
                blf.draw(layout['font_id'], m.friendly_name.upper())

                current_val = m.ui_value

                blf.position(layout['font_id'], px + pw - 45, curr_y + 10, 0)
                blf.draw(layout['font_id'], f"{current_val:.2f}")

                track_w = pw - 30
                draw_rect(px + 15, curr_y, track_w, 6, (0.09, 0.10, 0.12, 1.0))
                val_range = m.max_value - m.min_value
                pct = (current_val - m.min_value) / val_range if val_range > 0 else 0.0
                fill_w = int(track_w * max(0.0, min(1.0, pct)))
                if fill_w > 0:
                    draw_rect(px + 15, curr_y, fill_w, 6, (0.85, 0.45, 0.15, 1.0))

        # ─── [СЕКТОР 2] ECHO / RETURN МАКРОСЫ ───
        curr_y -= 22
        draw_rect(px + 10, curr_y, pw - 20, 16, (0.12, 0.13, 0.15, 1.0))
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.15, 0.65, 0.85, 1.0)
        blf.position(layout['font_id'], px + 15, curr_y + 4, 0)
        blf.draw(layout['font_id'], "ECHO / RETURN SETTINGS")

        if not echo_macros:
            curr_y -= 20
            blf.size(layout['font_id'], 10)
            blf.color(layout['font_id'], 0.35, 0.35, 0.38, 1.0)
            blf.position(layout['font_id'], px + 25, curr_y + 6, 0)
            blf.draw(layout['font_id'], "НЕТ РУЧЕК ВОЗВРАТА В ГРАФЕ")
        else:
            for m in echo_macros:
                curr_y -= 28
                blf.size(layout['font_id'], 9)
                blf.color(layout['font_id'], 0.85, 0.85, 0.88, 1.0)
                blf.position(layout['font_id'], px + 15, curr_y + 10, 0)
                blf.draw(layout['font_id'], m.friendly_name.upper())

                current_val = m.ui_value

                blf.position(layout['font_id'], px + pw - 45, curr_y + 10, 0)
                blf.draw(layout['font_id'], f"{current_val:.2f}")

                track_w = pw - 30
                draw_rect(px + 15, curr_y, track_w, 6, (0.09, 0.10, 0.12, 1.0))
                val_range = m.max_value - m.min_value
                pct = (current_val - m.min_value) / val_range if val_range > 0 else 0.0
                fill_w = int(track_w * max(0.0, min(1.0, pct)))
                if fill_w > 0:
                    draw_rect(px + 15, curr_y, fill_w, 6, (0.15, 0.65, 0.85, 1.0))

        # ─── [СЕКТОР 3] GLOBAL МАКРОСЫ ───
        curr_y -= 22
        draw_rect(px + 10, curr_y, pw - 20, 16, (0.12, 0.13, 0.15, 1.0))
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.0, 0.9, 1.0, 1.0)
        blf.position(layout['font_id'], px + 15, curr_y + 4, 0)
        blf.draw(layout['font_id'], "GLOBAL SYSTEM SETTINGS (SPEED / SIZE)")

        if not global_macros:
            curr_y -= 20
            blf.size(layout['font_id'], 10)
            blf.color(layout['font_id'], 0.35, 0.35, 0.38, 1.0)
            blf.position(layout['font_id'], px + 25, curr_y + 6, 0)
            blf.draw(layout['font_id'], "НЕТ АКТИВНЫХ РУЧЕК ТРАЕКТОРИИ")
        else:
            for m in global_macros:
                curr_y -= 28
                blf.size(layout['font_id'], 9)
                blf.color(layout['font_id'], 0.85, 0.85, 0.88, 1.0)
                blf.position(layout['font_id'], px + 15, curr_y + 10, 0)
                m_name = m.friendly_name if m.friendly_name else m.node_name
                blf.draw(layout['font_id'], m_name.upper())

                blf.position(layout['font_id'], px + pw - 45, curr_y + 10, 0)
                blf.draw(layout['font_id'], f"{m.ui_value:.2f}")

                track_w = pw - 30
                draw_rect(px + 15, curr_y, track_w, 6, (0.09, 0.10, 0.12, 1.0))
                val_range = m.max_value - m.min_value
                pct = (m.ui_value - m.min_value) / val_range if val_range > 0 else 0.0
                fill_w = int(track_w * max(0.0, min(1.0, pct)))
                if fill_w > 0:
                    draw_rect(px + 15, curr_y, fill_w, 6, (0.0, 0.8, 0.9, 1.0))

        # Подвал
        curr_y -= 20
        blf.size(layout['font_id'], 9)
        blf.color(layout['font_id'], 0.4, 0.4, 0.42, 1.0)
        blf.position(layout['font_id'], px + 25, curr_y, 0)
        blf.draw(layout['font_id'], "Octavia Unified System 5+")
