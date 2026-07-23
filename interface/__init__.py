import math
from time import time

import bpy
import blf
from .draw_utils import draw_rect
from .ruler import draw_time_ruler
from .grid import draw_channels_grid
from .blocks import draw_channel_blocks
# 🔥 ШАГ 4.1: ИМПОРТИРУЕМ ДИНАМИЧЕСКИЙ РЕЕСТР ПРЕСЕТОВ К РЯДУ С ТВОИМИ ПРИЗРАКАМИ
from .ghosts import draw_laser_ghosts, get_preset_labels

_draw_handle = None
_draw_handle_view3d = None

def draw_daw_canvas():
    context = bpy.context
    if context.workspace.name != "Octavia DAW":
        return

    win_w = context.region.width
    win_h = context.region.height
    scene = context.scene
   
    left_margin, right_margin, header_w, gap = 15, 15, 160, 8            
    track_x = left_margin + header_w + gap
    visible_workspace_w = win_w - track_x - right_margin
   
    fps = scene.render.fps if scene.render.fps > 0 else 24
    pixels_per_second = 50 * scene.octavia_zoom
    visible_frames = (visible_workspace_w / pixels_per_second) * fps
    current_frame = scene.frame_current

    # 🎞️ ЕДИНЫЙ СУБКАДРОВЫЙ ЧАСОВОЙ ОКТАВИИ
    # Считаем дробный кадр ОДИН раз и используем его согласованно и для скролла,
    # и для плейхеда. Это критично: если скролл привязать к целому кадру, а плейхед
    # к дробному — при авто-скролле плейхед начинает дрожать/двоиться (уползает между
    # кадрами и скачком возвращается на фикс-позицию). Единый smooth_frame убирает это.
    import sys
    import time as _time
    is_playing = context.screen.is_animation_playing
    if not hasattr(sys, "_octavia_playhead_time"):
        sys._octavia_playhead_time = _time.time()
    if not hasattr(sys, "_octavia_last_draw_frame"):
        sys._octavia_last_draw_frame = current_frame

    if is_playing:
        if current_frame != sys._octavia_last_draw_frame:
            sys._octavia_playhead_time = _time.time()
            sys._octavia_last_draw_frame = current_frame
        time_delta = min(_time.time() - sys._octavia_playhead_time, 1.0 / fps)
        smooth_frame = current_frame + (time_delta * fps)
        loop_end = scene.frame_preview_end if scene.use_preview_range else scene.frame_end
        smooth_frame = min(smooth_frame, float(loop_end))
    else:
        sys._octavia_last_draw_frame = current_frame
        smooth_frame = float(current_frame)

    visual_scroll = scene.octavia_scroll
    if scene.octavia_auto_scroll_active:
        if smooth_frame < visual_scroll:
            quarter_screen = visible_frames * 0.25
            visual_scroll = 0.0 if smooth_frame <= quarter_screen else max(0.0, smooth_frame - quarter_screen)
        elif is_playing:
            scroll_threshold_frame = visual_scroll + (visible_frames * 0.75)
            if smooth_frame > scroll_threshold_frame:
                visual_scroll = smooth_frame - (visible_frames * 0.75)

    scroll_px = (visual_scroll / fps) * pixels_per_second

    layout = {
        'context': context, 'scene': scene, 'win_w': win_w, 'win_h': win_h,
        'left_margin': left_margin, 'right_margin': right_margin,
        'header_w': header_w, 'gap': gap, 'track_x': track_x, 'track_y': win_h - 85,
        'visible_workspace_w': visible_workspace_w, 'visible_frames': visible_frames,
        'fps': fps, 'pixels_per_second': pixels_per_second, 'scroll_px': scroll_px,
        'smooth_frame': smooth_frame,
        'channel_h': 30, 'channel_gap': 8, 'font_id': 0
    }

    draw_rect(0, 0, win_w, win_h, (0.11, 0.11, 0.12, 1.0))

    draw_time_ruler(layout)

    draw_channels_grid(layout)
    draw_channel_blocks(layout)
    draw_laser_ghosts(layout)

    # Кнопка [+] с динамическим отступом под подвалом всех расширенных каналов
    active_channels = scene.octavia_channel_count
    curr_layout_y = layout['track_y']
    for i in range(1, active_channels + 1):
        is_active = (scene.octavia_active_channel == i)
        if is_active and len(scene.octavia_channels_data) >= i:
            num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
            ch_h = num_voices * 30
        else:
            ch_h = 30
        curr_layout_y -= (ch_h + layout['channel_gap'])
        
    btn_y = curr_layout_y - (30 + layout['channel_gap'])
    draw_rect(left_margin, btn_y, header_w, 30, (0.20, 0.21, 0.24, 1.0))
   
    blf.size(layout['font_id'], 14)
    blf.color(layout['font_id'], 0.9, 0.9, 0.92, 1.0)
    blf.position(layout['font_id'], left_margin + (header_w // 2) - 6, btn_y + 13, 0)
    blf.draw(layout['font_id'], "+")

    # ─── HUD-попап (CLIP_EDITOR + VIEW_3D через общий offscreen draw) ───
    from .popup_draw import draw_octavia_hud_popup
    draw_octavia_hud_popup(context)


def draw_viewport_popup_overlay():
    context = bpy.context
    if not context or not context.workspace or context.workspace.name != "Octavia DAW":
        return
    from .popup_draw import draw_octavia_hud_popup
    draw_octavia_hud_popup(context)


def register():
    global _draw_handle, _draw_handle_view3d
    _draw_handle = bpy.types.SpaceClipEditor.draw_handler_add(draw_daw_canvas, (), 'WINDOW', 'POST_PIXEL')
    _draw_handle_view3d = bpy.types.SpaceView3D.draw_handler_add(
        draw_viewport_popup_overlay, (), 'WINDOW', 'POST_PIXEL'
    )


def unregister():
    global _draw_handle, _draw_handle_view3d
    from .popup_draw import restore_popup_seam_chrome
    from .popup_offscreen import free_popup_offscreen
    restore_popup_seam_chrome()
    free_popup_offscreen()
    if _draw_handle is not None:
        bpy.types.SpaceClipEditor.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    if _draw_handle_view3d is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle_view3d, 'WINDOW')
        _draw_handle_view3d = None
