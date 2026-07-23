import bpy
import bisect
from .draw_utils import draw_rect
from .echo_trail import echo_trail_context_for_channel, ghost_frames_for_voice


def draw_channel_blocks(layout):
    context = layout['context']
    scene = layout['scene']
    win_w = layout['win_w']
    track_x, track_y = layout['track_x'], layout['track_y']
    visible_workspace_w = layout['visible_workspace_w']
    right_margin = layout['right_margin']
    channel_h, channel_gap = layout['channel_h'], layout['channel_gap']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
    scroll_px = layout['scroll_px']

    active_channels = scene.octavia_channel_count

    if context.active_object:
        curr_layout_y = track_y
        for i in range(1, active_channels + 1):
            is_active_ch = (scene.octavia_active_channel == i)
            
            if is_active_ch and len(scene.octavia_channels_data) >= i:
                num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
                ch_h = num_voices * channel_h
            else:
                ch_h = channel_h
                num_voices = 1
                
            ch_y = curr_layout_y - (ch_h + channel_gap)
            curr_layout_y = ch_y
            
            # Находим скрытый дата-меш текущего канала
            buf_name = f"Octavia_Buffer_Ch_{i}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not (buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action):
                continue
                
            act = buf_obj.data.animation_data.action
            curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
            if hasattr(act, "layers"):
                for layer in act.layers:
                    for strip in getattr(layer, "strips", []):
                        for bag in getattr(strip, "channelbags", []):
                            curves.extend(getattr(bag, "fcurves", []))
                            
            # 🪐 БРОНЕБОЙНЫЙ КВАНТОВЫЙ СКАНЕР КРИВЫХ (QUOTE-AGNOSTIC + REGEX PARSER)
            import re
            start_curves = {}
            end_curves = {}
            voice_curves = {}
            
            for fc in curves:
                if not hasattr(fc, "data_path"): continue
                
                # Извлекаем индекс вершины снайперской регуляркой, полностью игнорируя тип кавычек Блендера
                match = re.search(r'\[(\d+)\]\s*\.\s*value$', fc.data_path)
                if not match: continue
                idx = int(match.group(1))
                
                if "start_frame" in fc.data_path:
                    start_curves[idx] = fc
                elif "end_frame" in fc.data_path:
                    end_curves[idx] = fc
                elif "octavia_voice_id" in fc.data_path:
                    voice_curves[idx] = fc

            try:
                # Хвост echo: KickFade (кадры) / DECAY (сек) / Offset÷ReturnSpeed (POLY_TEST)
                echo_ctx = echo_trail_context_for_channel(scene, i)
                ghost_group = decay_seconds_legacy = None
                echo_frame_nodes = echo_speed_nodes = hold_nodes = ()
                if echo_ctx:
                    ghost_group, decay_seconds_legacy, echo_frame_nodes, echo_speed_nodes, hold_nodes = echo_ctx

                def _ghost_frames_for_voice(hw_id):
                    return ghost_frames_for_voice(
                        hw_id, fps, ghost_group, i, scene,
                        decay_seconds_legacy, echo_frame_nodes, echo_speed_nodes, hold_nodes,
                    )
                            
                for idx in range(128):
                    st_fc = start_curves.get(idx)
                    end_fc = end_curves.get(idx)
                    if not st_fc: continue
                    
                    kps = st_fc.keyframe_points
                    for k_idx, kp in enumerate(kps):
                        hit_frame = kp.co[1]
                        if hit_frame < 1.0: continue 

                        next_hit_frame = kps[k_idx+1].co[1] if k_idx + 1 < len(kps) else float('inf')
                        end_frame = -1.0
                        if end_fc:
                            for ekp in end_fc.keyframe_points:
                                if hit_frame <= ekp.co[0] < next_hit_frame:
                                    if ekp.co[1] >= hit_frame:
                                        end_frame = ekp.co[1]

                        # Снайперское извлечение ID голоса из кривой на кадре удара
                        v_fc = voice_curves.get(idx)
                        if v_fc:
                            v_id = int(v_fc.evaluate(kp.co[0]))
                        else:
                            voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")
                            v_id = int(voice_id_attr.data[idx].value) if voice_id_attr else 0
                            
                        # 🛡️ ПРЕДОХРАНИТЕЛЬ СТАРЫХ БЛОКОВ
                        # Если блок пришел из старой миграции и равен -1, плавно переводим его на 0-й этаж
                        if v_id < 0:
                            v_id = 0
                            
                        # 🏛️ МАТРИЧНЫЙ UI-МАППИНГ: Переводим физический hardware_id в относительный этаж HUD-таба
                        ch_data = scene.octavia_channels_data[i - 1] if len(scene.octavia_channels_data) >= i else None
                        v_idx = next((idx_v for idx_v, v in enumerate(ch_data.voices) if v.hardware_id == v_id), 0) if ch_data else 0
                        
                        if is_active_ch:
                            voice_y = ch_y + (num_voices - 1 - v_idx) * channel_h + 3
                            voice_h = channel_h - 6
                        else:
                            voice_y = ch_y + 3
                            voice_h = channel_h - 6
                        
                        block_id = f"ch_{i}_idx_{idx}_f_{hit_frame:.1f}"
                        
                        import sys
                        if hasattr(sys, "_octavia_virtual_erased") and block_id in sys._octavia_virtual_erased:
                            continue
                            
                        is_block_selected = scene.octavia_selected_blocks.get(block_id) is not None
                        is_block_hovered = (
                            scene.get("octavia_hovered_block_ch", -1) == i and
                            scene.get("octavia_hovered_block_voice", -1) == idx and
                            abs(scene.get("octavia_hovered_block_frame", -1.0) - hit_frame) < 0.1
                        )
                        
                        is_drag_active = (scene.get("octavia_drag_ch", -1) != -1)
                        is_this_block_dragged = False
                        if is_drag_active:
                            if is_block_selected: 
                                is_this_block_dragged = True
                            elif (scene.get("octavia_drag_ch", -1) == i and 
                                scene.get("octavia_drag_voice", -1) == idx and 
                                abs(scene.get("octavia_drag_frame", -1.0) - hit_frame) < 0.1):
                                is_this_block_dragged = True
                                
                        is_this_block_resized = (
                            scene.get("octavia_resize_ch", -1) == i and
                            scene.get("octavia_resize_voice", -1) == idx and
                            abs(scene.get("octavia_resize_frame", -1.0) - hit_frame) < 0.1
                        )
                        
                        is_held = (end_frame == -1.0)
                        display_hit = hit_frame
                        display_end = scene.frame_current if is_held else end_frame
                        
                        if is_this_block_dragged:
                            drag_offset = scene.get("octavia_drag_offset_frames", 0.0)
                            display_hit += drag_offset
                            display_end += drag_offset
                            
                        if is_this_block_resized:
                            resize_offset = scene.get("octavia_resize_offset_frames", 0.0)
                            display_end += resize_offset
                
                        sec_start = (display_hit - 1) / fps
                        bx = track_x + (sec_start * pixels_per_second) - scroll_px
                        bw = ((display_end - display_hit) / fps) * pixels_per_second
                        decay_frames = _ghost_frames_for_voice(v_id)
                        gbw = (decay_frames / fps) * pixels_per_second if not is_held else 0.0
  
                        if bx + bw + gbw < track_x: continue
                        
                        draw_bx = bx
                        draw_bw = bw
                        if draw_bx < track_x:
                            draw_bw = bw - (track_x - draw_bx)
                            draw_bx = track_x
          
                        snap_bx = int(round(draw_bx))
                        snap_bw = int(round(draw_bw))
                        
                        if snap_bw > 0:
                            if is_block_selected:
                                draw_rect(snap_bx - 2, voice_y - 2, snap_bw + 4, voice_h + 4, (0.2, 0.7, 1.0, 1.0))
                            elif is_block_hovered:
                                draw_rect(snap_bx - 1, voice_y - 1, snap_bw + 2, voice_h + 2, (1.0, 1.0, 1.0, 0.6))
                                
                            voice_color = (0.85, 0.40, 0.15, 1.0)
                            draw_rect(snap_bx, voice_y, max(1, snap_bw - 1), voice_h, voice_color)

                        from ..operators.input_handlers.operator import OCTAVIA_OT_ui_handler
                        show_ghosts = getattr(OCTAVIA_OT_ui_handler, '_preview_ghost_active', True)
          
                        if not is_held and show_ghosts:
                            g_sec_start = (display_end - 1) / fps
                            gbx = track_x + (g_sec_start * pixels_per_second) - scroll_px
                            
                            if gbx + gbw > track_x:
                                draw_gbx = gbx
                                draw_gbw = gbw
                                if draw_gbx < track_x:
                                    draw_gbw = gbw - (track_x - draw_gbx)
                                    draw_gbx = track_x
                                
                                snap_gbx = int(round(draw_gbx))
                                snap_gbw = int(round(draw_gbw))
                                
                                if snap_gbw > 0:
                                    ghost_color = (0.85, 0.40, 0.15, 0.15)
                                    draw_rect(snap_gbx, voice_y, max(1, snap_gbw - 1), voice_h, ghost_color)
                                    draw_rect(snap_gbx, voice_y, max(1, snap_gbw - 1), 1, (0.85, 0.40, 0.15, 0.3))
                                    draw_rect(snap_gbx, voice_y + voice_h - 1, max(1, snap_gbw - 1), 1, (0.85, 0.40, 0.15, 0.3))
            except Exception as e:
                print(f"[Octavia UI Error] Ошибка отрисовки blocks: {e}")
                
    # БОКС-СЕЛЕКТ ВУАЛЬ
    if scene.get("octavia_box_select_active", False):
        bs_x, bs_y = scene.get("octavia_box_start_x", 0.0), scene.get("octavia_box_start_y", 0.0)
        bc_x, bc_y = scene.get("octavia_box_current_x", 0.0), scene.get("octavia_box_current_y", 0.0)
        bx_min, bx_max = int(round(min(bs_x, bc_x))), int(round(max(bs_x, bc_x)))
        by_min, by_max = int(round(min(bs_y, bc_y))), int(round(max(bs_y, bc_y)))
        bw, bh = bx_max - bx_min, by_max - by_min
        if bw > 0 and bh > 0:
            draw_rect(bx_min, by_min, bw, bh, (0.2, 0.7, 1.0, 0.12))
            draw_rect(bx_min, by_min, bw, 1, (0.2, 0.7, 1.0, 0.5))
            draw_rect(bx_min, by_max, bw, 1, (0.2, 0.7, 1.0, 0.5))
            draw_rect(bx_min, by_min, 1, bh, (0.2, 0.7, 1.0, 0.5))
            draw_rect(bx_max, by_min, 1, bh, (0.2, 0.7, 1.0, 0.5))

    # ЛИНИЯ ПЛЕЙХЕДА (субкадровый smooth_frame считается централизованно в draw_daw_canvas)
    if layout.get('has_track', False) and scene.frame_end > 1:
        smooth_frame = layout.get('smooth_frame', float(scene.frame_current))
        current_sec = (smooth_frame - 1.0) / fps
        playhead_x = int(round(track_x + (current_sec * pixels_per_second) - scroll_px))
        if track_x <= playhead_x < win_w - right_margin:
            draw_rect(playhead_x, 0, 2, track_y + layout.get('track_h', 45), (0.95, 0.95, 0.95, 1.0))

    # 🧽 ОТРЕНДЕРИТЬ БАГРОВЫЙ МАГНИТНЫЙ ВАЛИК ЦАРЬ-ЛАСТИКА
    if scene.get("octavia_eraser_active", False):
        e_ch = scene.get("octavia_eraser_ch", -1)
        e_frame = scene.get("octavia_eraser_frame", -1.0)
        e_width = scene.get("octavia_eraser_width", 0.0)
        
        if e_ch > 0 and e_frame >= 1.0 and e_width > 0.0:
            ch_y = track_y - (e_ch * (channel_h + channel_gap))
            
            # Конвертируем кадры Октавии в пиксели экрана
            f_start = e_frame - (e_width / 2.0)
            sec_start = (f_start - 1) / fps
            ex_start = track_x + (sec_start * pixels_per_second) - scroll_px
            ex_width = (e_width / fps) * pixels_per_second
            
            if ex_start + ex_width > track_x:
                draw_ex = ex_start
                draw_ew = ex_width
                if draw_ex < track_x:
                    draw_ew = ex_width - (track_x - draw_ex)
                    draw_ex = track_x
                    
                if draw_ex < win_w - right_margin:
                    snap_ex = int(round(draw_ex))
                    snap_ew = int(round(min(draw_ew, win_w - right_margin - draw_ex)))
                    
                    if snap_ew > 0:
                        # Полупрозрачное ядовито-багровое тело ластика внутри границ канала
                        draw_rect(snap_ex, ch_y, snap_ew, channel_h, (1.0, 0.1, 0.15, 0.18))
                        
                        # Плотные неоново-красные боковые лезвия ластика
                        draw_rect(snap_ex, ch_y, 1, channel_h, (1.0, 0.1, 0.15, 0.6))
                        draw_rect(snap_ex + snap_ew - 1, ch_y, 1, channel_h, (1.0, 0.1, 0.15, 0.6))
                        
                        # Верхняя и нижняя кромки зоны
                        draw_rect(snap_ex, ch_y, snap_ew, 1, (1.0, 0.1, 0.15, 0.4))
                        draw_rect(snap_ex, ch_y + channel_h - 1, snap_ew, 1, (1.0, 0.1, 0.15, 0.4))