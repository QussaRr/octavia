import bpy
import sys

from .eraser import apply_quantum_eraser


def process_interactive_states(self, context, event, layout, mx, my, current_mouse_frame, current_mouse_ch, current_mouse_voice, scroll_px, area):
    scene = context.scene
    fps = layout['fps']
    pixels_per_second = layout['pixels_per_second']
    track_x, track_y = layout['track_x'], layout['track_y']
    channel_h = layout['channel_h']
    win_w = layout['win_w']

    # 🪐 ТРЕКИНГ ПРОТАСКИВАНИЯ ГРАНИЦ ЛУПА С ПКМ (ИДЕЯ №3)
    if getattr(self, "_is_defining_loop", False):
        if getattr(scene, "octavia_loop_active", False):
            # Луп всегда плавный под курсором — SNAP сюда не лезет
            current_sec = max(0.0, (mx - track_x + scroll_px) / pixels_per_second)
            anchor = getattr(self, "_loop_anchor_sec", scene.octavia_loop_start)

            # Старт всегда левее конца — и влево, и вправо от точки клика
            scene.octavia_loop_start = min(anchor, current_sec)
            scene.octavia_loop_end = max(anchor, current_sec)
                
            area.tag_redraw()
            return True

    # 1. МАТРИЦА КВАНТОВОГО ВИРТУАЛЬНОГО ЛАСТИКА (канал+голос зафиксированы на зажиме)
    if getattr(self, "_is_erasing", False):
        if current_mouse_frame >= 1.0:
            scene["octavia_eraser_frame"] = current_mouse_frame
            apply_quantum_eraser(self, context, current_mouse_frame)
        area.tag_redraw()
        return True

    # 2. МАТРИЦА МАССОВОГО БОКС-СЕЛЕКТА
    if getattr(self, "_is_box_selecting", False):
        scene["octavia_box_current_x"] = float(mx)
        scene["octavia_box_current_y"] = float(my)
       
        min_x = min(self._box_start_mx, mx)
        max_x = max(self._box_start_mx, mx)
        min_y = min(self._box_start_my, my)
        max_y = max(self._box_start_my, my)
       
        scene.octavia_selected_blocks.clear()
        for b_id in self._selection_snapshot:
            scene.octavia_selected_blocks.add().name = b_id
           
        for i in range(1, scene.octavia_channel_count + 1):
            ch_y = track_y - (i * 48)
            buf_name = f"Octavia_Buffer_Ch_{i}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                from ...vj_core import get_note_timing_curve_maps
                start_curves, end_curves, _voice = get_note_timing_curve_maps(buf_obj.data)

                for idx in start_curves:
                    st_fc = start_curves.get(idx)
                    en_fc = end_curves.get(idx)
                    if not st_fc: continue
                   
                    voice_y = ch_y + 4
                    voice_h = channel_h - 8
                   
                    kps = st_fc.keyframe_points
                    for k_idx, kp in enumerate(kps):
                        hit_frame = kp.co[1]
                        if hit_frame < 1.0: continue
                       
                        next_hit_frame = kps[k_idx+1].co[1] if k_idx + 1 < len(kps) else float('inf')
                        end_frame = -1.0
                        if en_fc:
                            for ekp in en_fc.keyframe_points:
                                if hit_frame <= ekp.co[0] < next_hit_frame:
                                    if ekp.co[1] >= hit_frame:
                                        end_frame = ekp.co[1]

                        is_held = (end_frame == -1.0)
                        body_end_f = scene.frame_current if is_held else end_frame
                       
                        sec = (hit_frame - 1) / fps
                        bx = track_x + (sec * pixels_per_second) - scroll_px
                        bw = ((body_end_f - hit_frame) / fps) * pixels_per_second
                       
                        if (bx < max_x and bx + bw > min_x and voice_y < max_y and voice_y + voice_h > min_y):
                            block_id = f"ch_{i}_idx_{idx}_f_{hit_frame:.1f}"
                            if block_id not in scene.octavia_selected_blocks:
                                scene.octavia_selected_blocks.add().name = block_id
        area.tag_redraw()
        return True

    # 3. ПАНОРАМИРОВАНИЕ ХОЛСТА (СКМ)
    if getattr(self, "_is_panning", False):
        delta_px = mx - self._pan_start_mx
        delta_sec = delta_px / pixels_per_second
        delta_frames = delta_sec * fps
        scene.octavia_scroll = max(0.0, self._pan_start_scroll - delta_frames)
        area.tag_redraw()
        return True

    # 4. СКРАББИНГ ТАЙМЛАЙНА
    if getattr(self, "_is_scrubbing", False):
        delta_x = mx - track_x + scroll_px
        current_sec = delta_x / pixels_per_second
        from ..operator import time_to_frame
        target_frame = int(round(time_to_frame(current_sec, fps)))
        scene.frame_current = max(1, min(scene.frame_end, target_frame))
        area.tag_redraw()
        return True
   
    # 5. ИЗМЕНЕНИЕ ДЛИНЫ БЛОКА (RESIZE EDGE)
    if getattr(self, "_is_resizing", False):
        delta_px = mx - self._resize_start_mx
        delta_sec = delta_px / pixels_per_second
        raw_delta_frames = delta_sec * fps
        base_dur_frames = int(round(0.5 * fps))
        ch = scene.get("octavia_resize_ch", -1)
        voice = scene.get("octavia_resize_voice", -1)

        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
            act = buf_obj.data.animation_data.action
            curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
            if hasattr(act, "layers"):
                for layer in act.layers:
                    for strip in getattr(layer, "strips", []):
                        for bag in getattr(strip, "channelbags", []): curves.extend(getattr(bag, "fcurves", []))
            
            st_path = f'attributes["start_frame"].data[{voice}].value'
            fc_start = next((c for c in curves if hasattr(c, "data_path") and st_path in c.data_path), None)
            next_hit_frame = float('inf')
            if fc_start:
                kps_st = sorted([k.co[1] for k in fc_start.keyframe_points if k.co[1] >= 1.0])
                try:
                    f_idx = next(i for i, f in enumerate(kps_st) if abs(f - self._resize_start_frame) < 0.1)
                    if f_idx < len(kps_st) - 1: next_hit_frame = kps_st[f_idx + 1]
                except: pass
                
            end_path = f'attributes["end_frame"].data[{voice}].value'
            fc_end = next((c for c in curves if hasattr(c, "data_path") and end_path in c.data_path), None)
            if fc_end:
                kp_en = next((k for k in fc_end.keyframe_points if self._resize_start_frame <= k.co[0] < next_hit_frame and k.co[1] >= self._resize_start_frame), None)
                if kp_en: base_dur_frames = int(round(kp_en.co[1] - self._resize_start_frame))

        if getattr(scene, "octavia_snap", True):
            from ...vj_core import snap_frame_to_grid
            raw_end = self._resize_start_frame + base_dur_frames + raw_delta_frames
            snapped_end = snap_frame_to_grid(
                raw_end, scene.octavia_bpm, fps, pixels_per_second,
            )
            final_offset = float(snapped_end - self._resize_start_frame - base_dur_frames)
        else:
            final_offset = float(int(round(raw_delta_frames)))
           
        proposed_total_duration = base_dur_frames + final_offset
        max_allowed_duration = self._collision_right_wall - self._resize_start_frame
        min_allowed_duration = 2.0  
        clamped_duration = max(min_allowed_duration, min(max_allowed_duration, proposed_total_duration))
        final_offset = clamped_duration - base_dur_frames
       
        scene["octavia_resize_offset_frames"] = final_offset
        area.tag_redraw()
        return True

    # 6. РЕЖИМ ALT-ШТАНПА СИНХРОНИЗАЦИИ ПРОКСИ
    if event.alt and scene.octavia_selected_blocks and not getattr(self, "_is_dragging", False) and not getattr(self, "_is_resizing", False) and not getattr(self, "_is_box_selecting", False):
        scene["octavia_alt_preview_active"] = True
        clip_voices = []
        frames = []
        for item in scene.octavia_selected_blocks:
            parts = item.name.split("_")
            clip_voices.append(int(parts[3]))
            frames.append(float(parts[5]))
           
        if frames and clip_voices:
            min_f, max_f = min(frames), max(frames)
            min_v, max_v = min(clip_voices), max(clip_voices)
           
            m_ch = current_mouse_ch if current_mouse_ch > 0 else scene.get("octavia_alt_preview_ch", scene.octavia_active_channel)
            m_frame = current_mouse_frame
            m_voice = current_mouse_voice
       
            if m_frame >= 1.0:
                raw_v_offset = m_voice - min_v
                min_allowed_v_offset = 1 - min_v
                max_allowed_v_offset = 3 - max_v
                v_offset = max(min_allowed_v_offset, min(max_allowed_v_offset, raw_v_offset))
               
                scene["octavia_alt_preview_ch"] = int(m_ch)
                # Якорь = начало (левый удар), не середина выделения
                scene["octavia_alt_preview_offset_frames"] = float(m_frame - min_f)
                scene["octavia_alt_preview_offset_voice"] = int(v_offset)
    else:
        scene["octavia_alt_preview_active"] = False

    # 7. МАССОВОЕ ПЕРЕМЕЩЕНИЕ БЛОКОВ (DRAG)
    if getattr(self, "_is_dragging", False):
        delta_px = mx - self._drag_start_mx
        delta_sec = delta_px / pixels_per_second
        raw_delta_frames = delta_sec * fps
        if getattr(scene, "octavia_snap", True):
            from ...vj_core import snap_frame_to_grid
            raw_target_frame = self._drag_start_frame + raw_delta_frames
            snapped_target_frame = snap_frame_to_grid(
                raw_target_frame, scene.octavia_bpm, fps, pixels_per_second,
            )
            proposed_offset = snapped_target_frame - self._drag_start_frame
        else:
            proposed_offset = int(round(raw_delta_frames))
        clamped_offset = max(self._pack_min_delta, min(self._pack_max_delta, proposed_offset))
        scene["octavia_drag_offset_frames"] = float(clamped_offset)
        area.tag_redraw()
        return True

    return False
