import blf
from .draw_utils import draw_rect


def draw_channels_grid(layout):
    scene = layout['scene']
    win_w = layout['win_w']
    track_x, track_y = layout['track_x'], layout['track_y']
    visible_workspace_w = layout['visible_workspace_w']
    left_margin, right_margin = layout['left_margin'], layout['right_margin']
    header_w, channel_h = layout['header_w'], layout['channel_h']
    channel_gap = layout['channel_gap']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
    scroll_px = layout['scroll_px']
    font_id = layout['font_id']


    active_channels = scene.octavia_channel_count
    active_track_idx = getattr(scene, "octavia_active_channel", 1)
   
    # 🔥 ЖЕЛЕЗНЫЙ ИНИЦИАЛИЗАТОР НАВИГАЦИИ: Задаем стартовую координату сетки
    curr_layout_y = track_y
    
    for i in range(1, active_channels + 1):
        is_active_ch = (active_track_idx == i)
       
        # Вычисляем динамическую высоту текущего канала
        if is_active_ch and len(scene.octavia_channels_data) >= i:
            num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
            ch_h = num_voices * channel_h
        else:
            ch_h = channel_h
            num_voices = 1
           
        ch_y = curr_layout_y - (ch_h + channel_gap)
        curr_layout_y = ch_y # Запоминаем опорную точку для следующего соседа
       
        # ВИЗУАЛЬНЫЙ НЕОН АКТИВНОГО ТРЕКА
        if is_active_ch:
            draw_rect(left_margin - 2, ch_y - 2, header_w + 4, ch_h + 4, (0.85, 0.45, 0.15, 1.0))
           
        # ЛЕВАЯ ЧАСТЬ: Плашка хедера канала
        draw_rect(left_margin, ch_y, header_w, ch_h, (0.18, 0.19, 0.22, 1.0) if is_active_ch else (0.14, 0.14, 0.15, 1.0))
       
        ch_custom_name = getattr(scene, f"octavia_ch{i}_name", f"Канал {i}")
        ch_preset = getattr(scene, f"octavia_ch{i}_preset", "NONE")
       
        is_name_hovered = (getattr(scene, "octavia_hovered_ch", 0) == i and getattr(scene, "octavia_hovered_part", "NONE") == "NAME")
       
        # Строка 1: Имя канала (привязываем к верхней кромке расширенного канала)
        blf.size(font_id, 11)
        if is_name_hovered:
            blf.color(font_id, 1.0, 0.73, 0.2, 1.0)
            display_name = f"✏️ {ch_custom_name.upper()}"
        else:
            blf.color(font_id, 0.95, 0.95, 0.98, 1.0) if is_active_ch else blf.color(font_id, 0.8, 0.8, 0.82, 1.0)
            display_name = ch_custom_name.upper()
           
        blf.position(font_id, left_margin + 12, ch_y + ch_h - 16, 0)
        short_name = display_name if len(display_name) < 16 else display_name[:14] + "..."
        blf.draw(font_id, short_name)
       
        # Строка 2: Название пресета
        is_preset_hovered = (getattr(scene, "octavia_hovered_ch", 0) == i and getattr(scene, "octavia_hovered_part", "NONE") == "PRESET")
        blf.size(font_id, 9)
        if is_preset_hovered:
            blf.color(font_id, 0.2, 0.7, 1.0, 1.0)
            display_preset = f"📁 ПРЕСЕТ: {ch_preset.replace('_', ' ').upper()}"
        else:
            blf.color(font_id, 0.5, 0.5, 0.55, 1.0) if is_active_ch else blf.color(font_id, 0.38, 0.38, 0.4, 1.0)
            display_preset = f"Пресет: {ch_preset}"
        blf.position(font_id, left_margin + 12, ch_y + ch_h - 26, 0)
        blf.draw(font_id, display_preset)
       
        # ПРАВАЯ ЧАСТЬ: Дорожка таймлайна
        draw_rect(track_x, ch_y, visible_workspace_w, ch_h, (0.15, 0.15, 0.17, 1.0))
       
        # Нарезаем активный канал изнутри на тонкие слои под каждый голос
        if is_active_ch and num_voices > 1:
            for v_line in range(1, num_voices):
                draw_rect(track_x, ch_y + (v_line * channel_h), visible_workspace_w, 1, (0.2, 0.2, 0.22, 0.4))
       
        # Сетка: ровные музыкальные X (без frame-round → без «кривой» сетки).
        # SNAP использует тот же шаг (16th/beat/bar по зуму) через vj_core.music_step_seconds.
        seconds_per_beat = 60.0 / max(1.0, float(scene.octavia_bpm))
        seconds_per_step = seconds_per_beat / 4.0
       
        step_px = seconds_per_step * pixels_per_second
        show_steps = step_px >= 14.0
        show_beats = (step_px * 4.0) >= 8.0
       
        max_sec = scene.frame_end / fps
        total_steps = int(max_sec / seconds_per_step) + 1
       
        start_step = max(0, int(scroll_px / max(step_px, 1e-6)) - 1)
        end_step = min(total_steps, int((scroll_px + visible_workspace_w) / max(step_px, 1e-6)) + 2)
       
        for step_idx in range(start_step, end_step):
            exact_step_sec = step_idx * seconds_per_step
            lx = int(round(track_x + (exact_step_sec * pixels_per_second) - scroll_px))
           
            if lx > win_w - right_margin: break
            if lx < track_x: continue
               
            is_bar = (step_idx % 16 == 0)  
            is_beat = (step_idx % 4 == 0)  
           
            if is_bar:
                draw_rect(lx, ch_y, 1, ch_h, (0.24, 0.24, 0.26, 1.0))
            elif is_beat and show_beats:
                draw_rect(lx, ch_y, 1, ch_h, (0.19, 0.19, 0.21, 1.0))
            elif show_steps:
                draw_rect(lx, ch_y, 1, ch_h, (0.16, 0.16, 0.18, 1.0))
