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

    # ─── СВЕРХЗВУКОВОЙ КОМПОНЕНТНЫЙ ДВИЖОК ПОПАПА ───
    from ..operators.input_handlers.operator import OCTAVIA_OT_ui_handler
    active_popup = getattr(OCTAVIA_OT_ui_handler, '_active_popup', None)
   
    if active_popup in {'ADD_CHANNEL', 'PRESETS', 'CHANNEL_SETTINGS'}:
        px = getattr(OCTAVIA_OT_ui_handler, '_popup_x', 0)
        py = getattr(OCTAVIA_OT_ui_handler, '_popup_y', 0)
        pw = getattr(OCTAVIA_OT_ui_handler, '_popup_w', 260)
        ph = getattr(OCTAVIA_OT_ui_handler, '_popup_h', 300)
        
        # ✂️--- ЗАМЕНИТЬ АБСОЛЮТНО ВСЁ ОТСЮДА ДО КОНЦА ФУНКЦИИ DRAW_DAW_CANVAS ---
        
        # ─── ДИНАМИЧЕСКИЙ РАСЧЕТ РАЗМЕРОВ ХУДА (Y-SHIFT ENGINE) ───
        if active_popup == 'CHANNEL_SETTINGS':
            ch_idx = getattr(OCTAVIA_OT_ui_handler, '_selected_channel_idx', 1)
            # 💡 САМОЛЕЧЕНИЕ СЦЕНЫ: Генерируем структуры на лету, если открыли старый проект
            while len(scene.octavia_channels_data) < ch_idx:
                scene.octavia_channels_data.add()
            ch_data = scene.octavia_channels_data[ch_idx - 1]
            if len(ch_data.voices) == 0:
                v_def = ch_data.voices.add()
                v_def.name = "ГОЛОС 1"
                v_def.key_code = "K"
                v_def.hardware_id = 0
                v_def.punch = 0.5
                v_def.hold = 0.5
                v_def.echo = 0.5

            # Окно ВСЕГДА сохраняет честную высоту под структуру ползунков автора
            calc_h = 130 
            if ch_data:
                tx = 10
                t_rows = 1
                for _ in range(len(ch_data.voices) + 1):
                    if tx + 64 > pw - 15:
                        tx = 10
                        t_rows += 1
                    tx += 68
                calc_h += t_rows * 22
            
            all_macros = list(scene.octavia_active_macros)
            calc_h += len(all_macros) * 28
            if any(m.category == 'GLOBAL' for m in all_macros): calc_h += 22
            if any(m.category == 'HOLD' for m in all_macros): calc_h += 22
            if any(m.category == 'ECHO' for m in all_macros): calc_h += 22
            ph = max(300, calc_h)
            OCTAVIA_OT_ui_handler._popup_h = ph

        # Железный стабильный бэкграунд попапа
        draw_rect(px - 1, py - ph - 1, pw + 2, ph + 2, (0.0, 0.9, 1.0, 1.0))
        draw_rect(px, py - ph, pw, ph, (0.07, 0.07, 0.08, 0.98))
       
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
                        blf.color(layout['font_id'], 1.0, 0.3, 0.3, 1.0) # Сигнальный красный
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
                import math
                overlay_y = curr_y - 10
                overlay_h = ph - (py - overlay_y)
                
                # Мягко глушим нижнюю конфигурационную зону
                draw_rect(px + 4, py - ph + 4, pw - 8, overlay_h - 8, (0.04, 0.04, 0.05, 0.95))
                
                # Заставляем рамку всего попапа дорого пульсировать неоном
                import time
                pulse = math.sin(time.time() * 12) * 0.3 + 0.7
                draw_rect(px - 1, py - ph - 1, pw + 2, ph + 2, (0.0, 1.0, 0.5, pulse * 0.5))
                draw_rect(px, py - ph, pw, ph, (0.0, 0.0, 0.0, 0.0))
                
                blf.size(layout['font_id'], 11)
                blf.color(layout['font_id'], 0.0, 1.0, 0.5, pulse)
                blf.position(layout['font_id'], px + 22, py - ph + (overlay_h // 2) + 6, 0)
                blf.draw(layout['font_id'], "[ НАЖМИТЕ КЛАВИШУ ДЛЯ БИНДА ]")
                
                blf.size(layout['font_id'], 9)
                blf.color(layout['font_id'], 0.5, 0.5, 0.55, 1.0)
                blf.position(layout['font_id'], px + 52, py - ph + (overlay_h // 2) - 14, 0)
                blf.draw(layout['font_id'], "( Нажмите ESC или кликните мимо )")
                return # Тормозим рендер ручек, вуаль наглухо закрыла управление!
            
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

def register():
    global _draw_handle
    _draw_handle = bpy.types.SpaceClipEditor.draw_handler_add(draw_daw_canvas, (), 'WINDOW', 'POST_PIXEL')

def unregister():
    global _draw_handle
    if _draw_handle is not None:
        bpy.types.SpaceClipEditor.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None