import blf
from .draw_utils import draw_rect


def draw_time_ruler(layout):
    scene = layout['scene']
    win_w, win_h = layout['win_w'], layout['win_h']
    track_x, track_y = layout['track_x'], layout['track_y']
    visible_workspace_w = layout['visible_workspace_w']
    left_margin, right_margin = layout['left_margin'], layout['right_margin']
    header_w = layout['header_w']
    pixels_per_second = layout['pixels_per_second']
    scroll_px = layout['scroll_px']
    fps = layout['fps']
    font_id = layout['font_id']


    # --- АУДИОДОРОЖКА ---
    track_title = "Нет загруженного трека"
    track_color = (0.15, 0.42, 0.32, 1.0)
    has_track = False
   
    if scene.sequence_editor and scene.sequence_editor.strips:
        track = next((s for s in scene.sequence_editor.strips if s.name.startswith("Octavia")), None)
        if track and hasattr(track, "sound"):
            filename = track.sound.filepath.split("\\")[-1].split("/")[-1]
            track_title = f"TRACK: {filename}"
            has_track = True


    total_seconds = int(scene.frame_end / fps) if scene.frame_end > 1 else 10
    clip_w = total_seconds * pixels_per_second
    track_h = 45
   
    draw_rect(track_x, track_y, visible_workspace_w, track_h, (0.14, 0.14, 0.15, 1.0))
                
    if has_track:
        ax = track_x + (0.0 * pixels_per_second) - scroll_px
        aw = clip_w
        if ax < track_x:
            aw = clip_w - (track_x - ax)
            ax = track_x
        if ax < win_w - right_margin:
            final_aw = min(aw, win_w - right_margin - ax)
            if final_aw > 0:
                draw_rect(ax, track_y, final_aw, track_h, track_color)
               
        draw_rect(left_margin, track_y, header_w, track_h, (0.17, 0.18, 0.20, 1.0))


    blf.size(font_id, 10)
    blf.color(font_id, 0.85, 0.85, 0.88, 1.0)
    blf.position(font_id, left_margin + 12, track_y + 17, 0)
    short_title = track_title if len(track_title) < 16 else track_title[:13] + "..."
    blf.draw(font_id, short_title)
   
    blf.size(font_id, 11)
    if getattr(scene, "octavia_mute", False):
        blf.color(font_id, 0.85, 0.25, 0.25, 1.0)
    else:
        blf.color(font_id, 0.4, 0.4, 0.45, 1.0)    
    blf.position(font_id, left_margin + header_w - 25, track_y + 17, 0)
    blf.draw(font_id, "[M]")


    # --- ШКАЛА ВРЕМЕНИ И БЛОК КВАНТИЗАЦИИ ---
    ruler_y = track_y + track_h + 4
    ruler_h = 20
   
    draw_rect(track_x, ruler_y, visible_workspace_w, ruler_h, (0.09, 0.09, 0.10, 1.0))

    # Заливка лупа — под засечками, чтобы цифры времени читались поверх
    loop_x1 = loop_x2 = None
    if getattr(scene, "octavia_loop_active", False):
        from ..operators.input_handlers.operator import OCTAVIA_OT_ui_handler
        from ..operators.vj_core import quantize_time_to_playhead

        # Во время драга — плавные секунды мыши; после отпускания — кадровая сетка
        if getattr(OCTAVIA_OT_ui_handler, "_defining_loop", False):
            start_sec = scene.octavia_loop_start
            end_sec = scene.octavia_loop_end
        else:
            start_sec, _ = quantize_time_to_playhead(scene.octavia_loop_start, fps)
            end_sec, _ = quantize_time_to_playhead(scene.octavia_loop_end, fps)

        loop_x1 = int(round(track_x + (start_sec * pixels_per_second) - scroll_px))
        loop_x2 = int(round(track_x + (end_sec * pixels_per_second) - scroll_px))
        draw_x = max(track_x, loop_x1)
        draw_end_x = min(win_w - right_margin, loop_x2)
        draw_w = draw_end_x - draw_x
        if draw_w > 0:
            draw_rect(draw_x, ruler_y, draw_w, ruler_h, (0.2, 0.5, 0.8, 0.15))

    draw_rect(left_margin, ruler_y, header_w, ruler_h, (0.14, 0.14, 0.16, 1.0))
   
    blf.size(font_id, 10)
    # BPM кликабелен — подсветка при наведении
    bpm_hovered = (
        getattr(scene, "octavia_hovered_ruler", "NONE") == "BPM"
    )
    if bpm_hovered:
        blf.color(font_id, 1.0, 0.75, 0.35, 1.0)
        blf.position(font_id, left_margin + 12, ruler_y + 5, 0)
        blf.draw(font_id, f"BPM: {scene.octavia_bpm} ✎")
    else:
        blf.color(font_id, 0.85, 0.45, 0.15, 1.0)
        blf.position(font_id, left_margin + 12, ruler_y + 5, 0)
        blf.draw(font_id, f"BPM: {scene.octavia_bpm}")
   
    if getattr(scene, "octavia_snap", True):
        blf.color(font_id, 0.2, 0.7, 1.0, 1.0)
        snap_str = "● SNAP"
    else:
        blf.color(font_id, 0.4, 0.4, 0.42, 1.0)
        snap_str = "○ SNAP"
    blf.position(font_id, left_margin + 95, ruler_y + 5, 0)
    blf.draw(font_id, snap_str)

    # LIVE — запись импульсов с клавиш голосов (клик / L)
    live_on = bool(getattr(scene, "vj_record_mode", False))
    live_hovered = getattr(scene, "octavia_hovered_ruler", "NONE") == "LIVE"
    if live_on:
        blf.color(font_id, 1.0, 0.25, 0.28, 1.0)
        live_str = "● LIVE"
    elif live_hovered:
        blf.color(font_id, 1.0, 0.55, 0.45, 1.0)
        live_str = "○ LIVE"
    else:
        blf.color(font_id, 0.4, 0.4, 0.42, 1.0)
        live_str = "○ LIVE"
    blf.position(font_id, left_margin + 155, ruler_y + 5, 0)
    blf.draw(font_id, live_str)

    # 🪐 ДВИЖОК АДАПТИВНОГО КВАНТОВАНИЯ ТАЙМЛАЙНА (ИДЕЯ №4)
    import math
    MIN_TICK_WIDTH = 90  # Минимальный комфортный шаг между текстовыми метками в пикселях
   
    # Сетка разрешенных временных интервалов (включая микросекунды для экстремального зума)
    TIME_STEPS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0]
   
    # На лету выбираем самый мелкий шаг, который при текущем зуме не слипнется в кашу
    step = TIME_STEPS[-1]
    for ts in TIME_STEPS:
        if ts * pixels_per_second >= MIN_TICK_WIDTH:
            step = ts
            break
           
    # Определяем видимый диапазон времени на экране на основе координат монитора
    start_sec = scroll_px / pixels_per_second
    end_sec = (scroll_px + visible_workspace_w) / pixels_per_second
   
    # Вычисляем индексы начального и конечного деления, чтобы замостить 100% экрана
    start_tick = math.floor(start_sec / step)
    end_tick = math.ceil(end_sec / step)
   
    # Определяем шаг для промежуточных (минорных) полосочек без цифр
    minor_subdivisions = 5 if step in [5.0, 10.0, 30.0, 60.0, 300.0, 600.0] else 2
    minor_step = step / minor_subdivisions


    # Чертим бесконечную сетку слева направо
    for tick_idx in range(start_tick, end_tick + 1):
        sec = tick_idx * step
        if sec < 0: continue
       
        # 1. Отрисовка МИНОРНЫХ (промежуточных) делений линейки
        if tick_idx < end_tick:
            for m_idx in range(1, minor_subdivisions):
                m_sec = sec + (m_idx * minor_step)
                m_sec_x = int(round(track_x + (m_sec * pixels_per_second) - scroll_px))
                if track_x <= m_sec_x < win_w - right_margin:
                    draw_rect(m_sec_x, ruler_y, 1, 4, (0.20, 0.20, 0.22, 1.0))


        # 2. Отрисовка МАЖОРНЫХ делений
        sec_x = int(round(track_x + (sec * pixels_per_second) - scroll_px))
        if not (track_x <= sec_x < win_w - right_margin): continue
       
        # Высокая плотная засечка для основных секунд
        draw_rect(sec_x, ruler_y, 1, 8, (0.42, 0.42, 0.45, 1.0))
       
        # Форматируем текст: динамически выводим миллисекунды в зависимости от глубины зума
        if step < 1.0:
            # Высчитываем остаток миллисекунд с точностью до 2 знаков для ультра-шагов
            ms = int(round((sec - int(sec)) * 100))
            time_str = f"{int(sec) // 60}:{int(sec) % 60:02d}.{ms:02d}"
        else:
            time_str = f"{int(sec) // 60}:{int(sec) % 60:02d}"
           
        # 🎯 АБСОЛЮТНЫЙ МОНОЛИТНЫЙ РАЗДЕЛЬНЫЙ РЕНДЕРИНГ С ГЕОМЕТРИЧЕСКОЙ КОРРЕКЦИЕЙ СДВИГА
        blf.size(font_id, 10)
        blf.color(font_id, 0.55, 0.55, 0.58, 1.0)
       
        # Высота цифр над полоской
        text_y = ruler_y + 12
       
        if ":" in time_str:
            minutes_part, seconds_part = time_str.split(":")
           
            # Замеряем ширину элементов строки и эталонного символа для компенсации полуапрошей шрифта Blender
            w_min, _ = blf.dimensions(font_id, minutes_part)
            w_colon, _ = blf.dimensions(font_id, ":")
            w_char, _ = blf.dimensions(font_id, "0")  # Ширина стандартного цифрового шага
           
            # 🔥 ВЫРАВНИВАНИЕ ЦЕНТРА: Двоеточие встает мертвым хватом по центру пиксельной оси линии
            font_padding_offset = (w_char - w_colon) / 4.0
            colon_x = int(round(sec_x - (w_colon / 2.0) + font_padding_offset))
           
            # Рисуем двоеточие
            blf.position(font_id, colon_x, text_y, 0)
            blf.draw(font_id, ":")
           
            # Минуты рисуем строго слева от двоеточия
            min_x = int(round(colon_x - w_min))
            blf.position(font_id, min_x, text_y, 0)
            blf.draw(font_id, minutes_part)
           
            # Секунды (с миллисекундами) рисуем строго справа от двоеточия
            sec_part_x = int(round(colon_x + w_colon))
            blf.position(font_id, sec_part_x, text_y, 0)
            blf.draw(font_id, seconds_part)
        else:
            # Фолбэк на случай непредвиденного формата строки
            text_w, _ = blf.dimensions(font_id, time_str)
            blf.position(font_id, int(round(sec_x - (text_w / 2.0))), text_y, 0)
            blf.draw(font_id, time_str)

    # Границы лупа — поверх засечек, иначе засечка «откусывает» низ полосы
    if loop_x1 is not None and loop_x2 is not None and loop_x2 > loop_x1:
        if track_x <= loop_x1 < win_w - right_margin:
            draw_rect(loop_x1, ruler_y, 2, ruler_h, (0.3, 0.7, 1.0, 0.8))
        if track_x <= loop_x2 < win_w - right_margin and loop_x2 != loop_x1:
            draw_rect(loop_x2, ruler_y, 2, ruler_h, (0.3, 0.7, 1.0, 0.8))
       
    layout['has_track'] = has_track
    layout['track_h'] = track_h