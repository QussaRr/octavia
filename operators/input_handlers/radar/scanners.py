import bpy

def scan_interface_hovers(context, layout, mx, my, scroll_px):
    scene = context.scene
    fps = layout['fps']
    pixels_per_second = layout['pixels_per_second']
    track_x, track_y = layout['track_x'], layout['track_y']
    win_w, win_h = layout['win_w'], layout['win_h']
    right_margin, left_margin = layout['right_margin'], layout['left_margin']
    header_w, channel_h, channel_gap = layout['header_w'], layout['channel_h'], layout['channel_gap']

    current_hover_ch = 0
    current_hover_part = "NONE"
    hovered_block_ch = -1
    hovered_block_voice = -1
    hovered_block_frame = -1.0
    hovered_ruler = "NONE"

    # Линейка: BPM / SNAP / LIVE
    ruler_y = track_y + 45 + 4
    if ruler_y <= my <= ruler_y + 20:
        if left_margin + 8 <= mx <= left_margin + 88:
            hovered_ruler = "BPM"
        elif left_margin + 90 <= mx <= left_margin + 150:
            hovered_ruler = "SNAP"
        elif left_margin + 150 <= mx <= left_margin + 210:
            hovered_ruler = "LIVE"

    curr_layout_y = track_y
    for i in range(1, scene.octavia_channel_count + 1):
        is_active_ch = (scene.octavia_active_channel == i)
        
        if is_active_ch and len(scene.octavia_channels_data) >= i:
            num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
            ch_h = num_voices * channel_h
        else:
            ch_h = channel_h
            num_voices = 1
            
        ch_y = curr_layout_y - (ch_h + channel_gap)
        curr_layout_y = ch_y
       
        # Проверяем, находится ли курсор внутри высоты этого канала
        if ch_y <= my <= ch_y + ch_h:
            if (left_margin <= mx <= left_margin + header_w):
                current_hover_ch = i
                # Привязываем зоны к верхней кромке расширенного канала
                if ch_y + ch_h - 15 <= my <= ch_y + ch_h and (left_margin <= mx <= left_margin + 100):
                    current_hover_part = "NAME"
                elif ch_y + ch_h - 30 <= my <= ch_y + ch_h - 15 and (left_margin <= mx <= left_margin + 140):
                    current_hover_part = "PRESET"
                else:
                    current_hover_part = "NONE"
            
            elif track_x <= mx <= win_w - right_margin and context.active_object:
                buf_name = f"Octavia_Buffer_Ch_{i}"
                buf_obj = context.scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                    from ...vj_core import get_note_timing_curve_maps
                    start_curves, end_curves, voice_curves = get_note_timing_curve_maps(buf_obj.data)

                    for idx in start_curves:
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
                                        if ekp.co[1] >= hit_frame: end_frame = ekp.co[1]

                            is_held = (end_frame == -1.0)
                            body_end_f = context.scene.frame_current if is_held else end_frame
                           
                            v_fc = voice_curves.get(idx)
                            if v_fc:
                                v_id = int(v_fc.evaluate(kp.co[0] + 0.1))
                            else:
                                voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")
                                v_id = int(voice_id_attr.data[idx].value) if voice_id_attr else 0
                                
                            # 🏛️ РАДАРНЫЙ UI-МАППИНГ: Синхронно транслируем hw_id в хитбокс ховера мыши
                            ch_data = scene.octavia_channels_data[i - 1] if len(scene.octavia_channels_data) >= i else None
                            v_idx = next((idx_v for idx_v, v in enumerate(ch_data.voices) if v.hardware_id == v_id), 0) if ch_data else 0
                            
                            if is_active_ch:
                                bx_y = ch_y + (num_voices - 1 - v_idx) * channel_h
                            else:
                                bx_y = ch_y
                           
                            sec_start = (hit_frame - 1) / fps
                            bx = track_x + (sec_start * pixels_per_second) - scroll_px
                            bw = ((body_end_f - hit_frame) / fps) * pixels_per_second
                           
                            if bx < win_w - right_margin and bx_y <= my <= bx_y + channel_h:
                                draw_w = min(bw, win_w - right_margin - bx)
                                if max(track_x, bx) <= mx <= bx + draw_w:
                                    hovered_block_ch = i
                                    hovered_block_voice = idx 
                                    hovered_block_frame = hit_frame
                                   
                                    if bw > 16 and (bx + bw - 6) <= mx <= (bx + bw): current_hover_part = "EDGE"
                                    else: current_hover_part = "BLOCK"
                                    break
                        if hovered_block_ch != -1: break
            break
        if hovered_block_ch != -1: break

    scene.octavia_hovered_ch = current_hover_ch
    scene.octavia_hovered_part = current_hover_part
    scene.octavia_hovered_ruler = hovered_ruler
    scene["octavia_hovered_block_ch"] = hovered_block_ch
    scene["octavia_hovered_block_voice"] = hovered_block_voice
    scene["octavia_hovered_block_frame"] = hovered_block_frame
   
    if current_hover_part == "EDGE": context.window.cursor_set('MOVE_X')
    elif hovered_ruler == "BPM": context.window.cursor_set('DEFAULT')
    elif current_hover_part in {"NONE", "NAME", "PRESET", "BLOCK"}: context.window.cursor_set('DEFAULT')