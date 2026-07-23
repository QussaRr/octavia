import bpy
from ....vj_core import time_to_frame

def handle_timeline_clicks(self, context, event, layout, mx, my, area):
    scene = context.scene
    track_x, track_y = layout['track_x'], layout['track_y']
    left_margin, header_w = layout['left_margin'], layout['header_w']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
    ruler_y = track_y + 45 + 4
   
    # FOLLOW — только поведение (play/scrub сами включают автоскролл), бейджа на линейке нет

    # Б: Заглушка аудио-дорожки [M]
    if (left_margin + header_w - 35 <= mx <= left_margin + header_w) and (track_y <= my <= track_y + 45):
        scene.octavia_mute = not getattr(scene, "octavia_mute", False)
        if scene.sequence_editor and scene.sequence_editor.strips:
            for strip in scene.sequence_editor.strips:
                if strip.name.startswith("Octavia"):
                    strip.mute = scene.octavia_mute
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # Б2: BPM — кастомный попап DAW (не диалог Blender)
    if (left_margin + 8 <= mx <= left_margin + 88) and (ruler_y <= my <= ruler_y + 20):
        from ...operator import OCTAVIA_OT_ui_handler
        from octavia.interface.popup_geometry import prepare_bpm_popup
        region = layout.get('region')
        if region is not None:
            prepare_bpm_popup(OCTAVIA_OT_ui_handler, region, left_margin + 8, ruler_y - 8)
        else:
            OCTAVIA_OT_ui_handler._active_popup = 'BPM'
            OCTAVIA_OT_ui_handler._popup_w = 200
            OCTAVIA_OT_ui_handler._popup_h = 150
            OCTAVIA_OT_ui_handler._popup_x = left_margin + 8
            OCTAVIA_OT_ui_handler._popup_y = ruler_y - 8
            OCTAVIA_OT_ui_handler._hovered_bpm_btn = "NONE"
        from octavia.interface.popup_draw import tag_octavia_popup_areas
        tag_octavia_popup_areas(context)
        return {'RUNNING_MODAL'}

    # В: Тумблер музыкального магнита сетки SNAP
    if (left_margin + 90 <= mx <= left_margin + 150) and (ruler_y <= my <= ruler_y + 20):
        scene.octavia_snap = not getattr(scene, "octavia_snap", True)
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # В2: LIVE — запись импульсов (клик по линейке)
    if (left_margin + 150 <= mx <= left_margin + 210) and (ruler_y <= my <= ruler_y + 20):
        bpy.ops.octavia.toggle_mode()
        area.tag_redraw()
        return {'RUNNING_MODAL'}
   
    # Г: Скраббинг шкалы времени (Перемещение плейхеда мыжкой — ТОЛЬКО ЛКМ)
    if event.type == 'LEFTMOUSE' and (mx >= track_x) and (ruler_y <= my <= ruler_y + 20):
        self._is_scrubbing = True
        click_scroll_px = (scene.octavia_scroll / fps) * pixels_per_second
        delta_x = mx - track_x + click_scroll_px
        current_sec = delta_x / pixels_per_second
        target_frame = int(round(time_to_frame(current_sec, fps)))
        scene.frame_current = max(1, min(scene.frame_end, target_frame))
        area.tag_redraw()
        scene.octavia_auto_scroll_active = True
        return {'RUNNING_MODAL'}
        
    # Д: ГИБРИДНЫЙ АДАПТИВНЫЙ ПРО-МОСТ ЛУПА (Выделение зоны лупа — ТОЛЬКО ПКМ)
    if event.type == 'RIGHTMOUSE' and (mx >= track_x) and (ruler_y <= my <= ruler_y + 20):
        # Якорь строго под курсором: SNAP не должен утаскивать старт при близком зуме
        click_sec = max(0.0, (mx - track_x + layout['scroll_px']) / pixels_per_second)
            
        scene.octavia_loop_start = click_sec
        scene.octavia_loop_end = click_sec
        scene.octavia_loop_active = True
        scene.use_preview_range = False  
        
        # Якорь клика: от него loop растягивается в обе стороны
        self._loop_anchor_sec = click_sec
        self._is_defining_loop = True
        from ...operator import OCTAVIA_OT_ui_handler
        OCTAVIA_OT_ui_handler._defining_loop = True
        area.tag_redraw()
        return {'RUNNING_MODAL'}
       
    return None