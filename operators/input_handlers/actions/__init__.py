from .keyboard import handle_keyboard_press
from .mouse_press import handle_mouse_press
from .mouse_release import handle_mouse_release
import bpy

def handle_actions(self, context, event, layout, area):
    scene = context.scene
    fps = layout['fps']

    # Колесо над BPM (линейка или попап TEMPO): ±1
    if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and event.value == 'PRESS':
        from ..operator import OCTAVIA_OT_ui_handler
        mx, my = layout['mx'], layout['my']
        left_margin = layout['left_margin']
        ruler_y = layout['track_y'] + 45 + 4
        over_ruler_bpm = (
            getattr(scene, "octavia_hovered_ruler", "NONE") == "BPM"
            or ((left_margin + 8 <= mx <= left_margin + 88) and (ruler_y <= my <= ruler_y + 20))
        )
        over_popup_bpm = False
        if getattr(OCTAVIA_OT_ui_handler, '_active_popup', None) == 'BPM':
            from octavia.interface.popup_geometry import point_in_popup
            wx = float(layout.get('mouse_win_x', mx))
            wy = float(layout.get('mouse_win_y', my))
            over_popup_bpm = point_in_popup(wx, wy, OCTAVIA_OT_ui_handler, scene)
        if over_ruler_bpm or over_popup_bpm:
            delta = 1 if event.type == 'WHEELUPMOUSE' else -1
            scene.octavia_bpm = max(30, min(300, int(scene.octavia_bpm) + delta))
            from octavia.interface.popup_draw import tag_octavia_popup_areas
            tag_octavia_popup_areas(context)
            return {'RUNNING_MODAL'}
    
    # 🔥 ПЕРЕХВАТ КОЛЕСИКА МЫШИ ДЛЯ УВЕЛИЧЕНИЯ/УМЕНЬШЕНИЯ ЗОНЫ ЛАСТИКА
    if getattr(self, "_is_erasing", False):
        if event.type == 'WHEELUPMOUSE':
            # Расширяем ластик на 4 кадра вверх
            self._eraser_width_frames = min(fps * 15.0, self._eraser_width_frames + 4.0)
            scene["octavia_eraser_width"] = self._eraser_width_frames
            area.tag_redraw()
            return {'RUNNING_MODAL'}
            
        elif event.type == 'WHEELDOWNMOUSE':
            # Сжимаем ластик до минимума в 2 кадра
            self._eraser_width_frames = max(2.0, self._eraser_width_frames - 4.0)
            scene["octavia_eraser_width"] = self._eraser_width_frames
            area.tag_redraw()
            return {'RUNNING_MODAL'}

    # ⚡ СУПЕР-ХОТКЕЙ ОКТАВИИ: Нажатие Alt мгновенно запекает выделение в кисть штампа!
    if event.type in {'LEFT_ALT', 'RIGHT_ALT'} and event.value == 'PRESS':
        if scene.octavia_selected_blocks:
            bpy.ops.octavia.copy_pulses()
            area.tag_redraw()
            return {'RUNNING_MODAL'}

    # Стандартный каскад распределения событий
    if event.value == 'PRESS':
        res = handle_keyboard_press(self, context, event, layout, area)
        if res is not None: return res
        
        res = handle_mouse_press(self, context, event, layout, area)
        if res is not None: return res
            
    elif event.value == 'RELEASE':
        res = handle_mouse_release(self, context, event, layout, area)
        if res is not None: return res
            
    return {'PASS_THROUGH'}