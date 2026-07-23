import bpy
from .popups import handle_active_popup
from .timeline import handle_timeline_clicks
from .blocks import handle_block_clicks
from .right_click import handle_right_clicks

def handle_mouse_press(self, context, event, layout, area):
    import sys
    scene = context.scene
    mx, my = layout['mx'], layout['my']
    win_w, win_h = layout['win_w'], layout['win_h']
    track_x, track_y = layout['track_x'], layout['track_y']
    left_margin, right_margin = layout['left_margin'], layout['right_margin']
    header_w, channel_h = layout['header_w'], layout['channel_h']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
    visible_frames = layout['visible_frames']

    from ...operator import OCTAVIA_OT_ui_handler
    active_popup = getattr(OCTAVIA_OT_ui_handler, '_active_popup', None)

    # 1. ЩИТ АКТИВНОГО ПОПАПА
    if active_popup:
        popup_res = handle_active_popup(self, context, event, layout, mx, my, active_popup, area)
        if popup_res is not None:
            return popup_res

    # 2. ПАНОРАМИРОВАНИЕ ХОЛСТА (СКМ) — НА ПЕРВОМ ОГНЕВОМ РУБЕЖЕ
    if event.type == 'MIDDLEMOUSE':
        scene.octavia_auto_scroll_active = False
        self._is_panning = True
        self._pan_start_mx = mx
        self._pan_start_scroll = scene.octavia_scroll
        return {'RUNNING_MODAL'}

    # 3. КЛИКИ ПО ТАЙМЛАЙНУ / ЛИНЕЙКЕ (И ЛКМ-СКРАББИНГ, И ПКМ-ВЫДЕЛЕНИЕ ЛУПА)
    # Вынесено наверх, чтобы ловить RIGHTMOUSE до того, как его перехватит ластик
    timeline_res = handle_timeline_clicks(self, context, event, layout, mx, my, area)
    if timeline_res is not None:
        return timeline_res

    # 4. КЛИКИ ЛЕВОЙ КНОПКИ МЫШИ (ЛКМ)
    if event.type == 'LEFTMOUSE':
        # Лазерный штамп, выделения блоков, Драг/Ресайз, Бокс-селект
        block_res = handle_block_clicks(self, context, event, layout, mx, my, area)
        if block_res is not None:
            return block_res

    # 5. КЛИКИ ПРАВОЙ КНОПКИ МЫШИ (ПКМ) — ЦАРЬ-ЛАСТИК
    # Сюда ПКМ долетит только в том случае, если кликнули МИМО таймлайна
    if event.type == 'RIGHTMOUSE':
        right_res = handle_right_clicks(self, context, event, layout, mx, my, area)
        if right_res is not None:
            return right_res

    return None