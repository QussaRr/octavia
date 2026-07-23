import bpy
import sys

def handle_block_clicks(self, context, event, layout, mx, my, area):
    scene = context.scene
    track_x, track_y = layout['track_x'], layout['track_y']
    left_margin, header_w = layout['left_margin'], layout['header_w']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
   
    # 1. СНАЙПЕРСКИЙ ЛАЗЕРНЫЙ ШТАМП ГРУВА ИЗ БУФЕРА ОБМЕНА (Только если кликаем по ПУСТОМУ месту!)
    if hasattr(sys, "_octavia_clipboard") and sys._octavia_clipboard and scene.get("octavia_hovered_block_ch", -1) == -1:
        m_ch = scene.get("octavia_mouse_ch", -1)
        m_frame = scene.get("octavia_mouse_frame", -1.0)
       
        if m_ch > 0 and m_frame >= 1.0:
            hovered_voice = scene.get("octavia_mouse_voice", 0)
            source_min_voice = getattr(sys, "_octavia_clipboard_source_min_voice", 0)
            voice_offset = hovered_voice - source_min_voice
           
            existing_notes = {}
            ch_data = scene.octavia_channels_data[m_ch - 1] if len(scene.octavia_channels_data) >= m_ch else None
            num_voices = len(ch_data.voices) if ch_data else 1
            for v_idx in range(num_voices):
                existing_notes[v_idx] = []
               
            obj = next((o for o in context.scene.objects if o.type == 'MESH' and o.modifiers.get(f"Octavia Channel {m_ch}")), None)
            if obj:
                buf_name = f"Octavia_Buffer_Ch_{m_ch}"
                buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                    from ....vj_core import get_note_timing_curve_maps
                    start_curves, end_curves, voice_curves = get_note_timing_curve_maps(buf_obj.data)
                                 
                    for idx in start_curves:
                        st_fc = start_curves.get(idx)
                        end_fc = end_curves.get(idx)
                        if not st_fc: continue
                        for sk_i, skp in enumerate(st_fc.keyframe_points):
                            f_start = skp.co[1]
                            if f_start < 1.0: continue
                            f_end = f_start + int(round(0.5 * fps))
                            nxt_f = st_fc.keyframe_points[sk_i+1].co[1] if sk_i + 1 < len(st_fc.keyframe_points) else float('inf')
                            if end_fc:
                                for ekp in end_fc.keyframe_points:
                                    if skp.co[0] <= ekp.co[0] < nxt_f and ekp.co[1] >= skp.co[1]:
                                        f_end = ekp.co[1]
                                        break
                                        
                            v_fc = voice_curves.get(idx)
                            if v_fc:
                                v_id = int(v_fc.evaluate(skp.co[0] + 0.1))
                            else:
                                voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")
                                v_id = int(voice_id_attr.data[idx].value) if voice_id_attr else 0
                                
                            v_idx = next((idx_v for idx_v, v in enumerate(ch_data.voices) if v.hardware_id == v_id), 0) if ch_data else 0
                            if v_idx in existing_notes:
                                existing_notes[v_idx].append((f_start, f_end))

            has_collision = False
            for p in sys._octavia_clipboard:
                target_v_idx = p['v_idx'] + voice_offset
                target_frame = int(round(m_frame + p['time_offset_frames']))
                target_dur = p['duration_frames']
               
                if target_v_idx in existing_notes:
                    for f_start, f_end in existing_notes[target_v_idx]:
                        if max(target_frame, f_start) < min(target_frame + target_dur, f_end):
                            has_collision = True
                            break
                if has_collision: break

            if has_collision:
                return {'RUNNING_MODAL'}

            if obj:
                context.view_layer.objects.active = obj
                if not obj.hide_get():
                    obj.select_set(True)
           
            bpy.ops.octavia.paste_pulses()

            if not event.shift and hasattr(sys, "_octavia_clipboard"):
                sys._octavia_clipboard.clear()
               
            area.tag_redraw()
            return {'RUNNING_MODAL'}

    # 2. МАТРИЦА ИНТЕРАКТИВНОГО КЛИКА И ВЫДЕЛЕНИЯ БЛОКОВ НА ДАТА-МЕШЕ
    hovered_ch = scene.get("octavia_hovered_block_ch", -1)
    if hovered_ch != -1:
        scene.octavia_auto_scroll_active = False
        voice = scene["octavia_hovered_block_voice"]
        hit_frame = scene["octavia_hovered_block_frame"]
        block_id = f"ch_{hovered_ch}_idx_{voice}_f_{hit_frame:.1f}"
       
        if event.ctrl:
            if scene.octavia_selected_blocks.get(block_id):
                d_idx = next(idx for idx, x in enumerate(scene.octavia_selected_blocks) if x.name == block_id)
                scene.octavia_selected_blocks.remove(d_idx)
            else:
                scene.octavia_selected_blocks.add().name = block_id
        else:
            if block_id not in scene.octavia_selected_blocks:
                scene.octavia_selected_blocks.clear()
                scene.octavia_selected_blocks.add().name = block_id

        if scene.octavia_hovered_part == "EDGE":
            from ....vj_core import push_undo_step
            push_undo_step(context, [hovered_ch])

            obj = next((o for o in context.scene.objects if o.type == 'MESH' and o.modifiers.get(f"Octavia Channel {hovered_ch}")), None)
           
            self._is_resizing = True
            self._resize_start_mx = mx
            self._resize_start_frame = hit_frame
           
            scene["octavia_resize_ch"] = hovered_ch
            scene["octavia_resize_voice"] = voice  
            scene["octavia_resize_frame"] = hit_frame
            scene["octavia_resize_offset_frames"] = 0.0
           
            left_wall = hit_frame + 2.0
            right_wall = float(scene.frame_end + 1000)
           
            buf_name = f"Octavia_Buffer_Ch_{hovered_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                from ....vj_core import get_note_timing_curve_maps
                start_curves, _end_c, _voice_c = get_note_timing_curve_maps(buf_obj.data)
                all_frames = []
                for st_fc in start_curves.values():
                    for kp in st_fc.keyframe_points:
                        if kp.co[1] >= 1.0:
                            all_frames.append(kp.co[1])
                all_frames = sorted(list(set(all_frames)))
                try:
                    idx_f = next(i for i, f in enumerate(all_frames) if abs(f - hit_frame) < 0.1)
                    if idx_f < len(all_frames) - 1: right_wall = all_frames[idx_f + 1]
                except: pass
           
            self._collision_left_wall = float(left_wall)
            self._collision_right_wall = float(right_wall)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
           
        else:
            from ....vj_core import push_undo_step
            target_chs = {int(item.name.split("_")[1]) for item in scene.octavia_selected_blocks}
            if hovered_ch not in target_chs:
                target_chs.add(hovered_ch)
            push_undo_step(context, list(target_chs))
           
            self._is_dragging = True
            self._drag_ch = hovered_ch
            self._drag_voice = voice
            self._drag_start_frame = hit_frame
            self._drag_start_mx = mx
           
            scene["octavia_drag_ch"] = hovered_ch
            scene["octavia_drag_voice"] = voice
            scene["octavia_drag_frame"] = hit_frame
            scene["octavia_drag_offset_frames"] = 0.0
           
            pack_min_delta = -100000.0  
            pack_max_delta = 100000.0  
            selected_ids = {item.name for item in scene.octavia_selected_blocks}
           
            for item in scene.octavia_selected_blocks:
                parts = item.name.split("_")
                b_ch = int(parts[1])
                b_idx = int(parts[3])  
                b_frame = float(parts[5])
               
                b_end_frame = b_frame + int(round(0.5 * fps))
                left_wall = 1.0
                right_wall = float(scene.frame_end + 1000)
               
                buf_name = f"Octavia_Buffer_Ch_{b_ch}"
                buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
               
                if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                    from ....vj_core import get_note_timing_curve_maps
                    start_curves, end_curves, voice_curves = get_note_timing_curve_maps(buf_obj.data)

                    def note_voice_id(slot, key_time):
                        v_fc = voice_curves.get(slot)
                        if v_fc:
                            return int(v_fc.evaluate(key_time + 0.1))
                        voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")
                        if voice_id_attr and slot < len(voice_id_attr.data):
                            return int(voice_id_attr.data[slot].value)
                        return 0
                           
                    st_fc = start_curves.get(b_idx)
                    en_fc = end_curves.get(b_idx)
                    drag_voice_id = 0
                    if st_fc:
                        for k_i, kp in enumerate(st_fc.keyframe_points):
                            if abs(kp.co[1] - b_frame) < 0.1:
                                drag_voice_id = note_voice_id(b_idx, kp.co[0])
                                nxt_f = st_fc.keyframe_points[k_i+1].co[1] if k_i + 1 < len(st_fc.keyframe_points) else float('inf')
                                if en_fc:
                                    for ekp in en_fc.keyframe_points:
                                        if kp.co[0] <= ekp.co[0] < nxt_f and ekp.co[1] >= kp.co[1]:
                                            b_end_frame = ekp.co[1]
                                            break
                   
                    # Стены только внутри того же голоса — иначе ноты V1 блокируют V2+
                    all_notes = []
                    for slot in start_curves:
                        s_c = start_curves.get(slot)
                        e_c = end_curves.get(slot)
                        if not s_c: continue
                        for sk_i, skp in enumerate(s_c.keyframe_points):
                            f_start = skp.co[1]
                            if f_start < 1.0: continue
                            if f"ch_{b_ch}_idx_{slot}_f_{f_start:.1f}" in selected_ids: continue
                            if note_voice_id(slot, skp.co[0]) != drag_voice_id: continue
                           
                            f_end = f_start + int(round(0.5 * fps))
                            nxt_f = s_c.keyframe_points[sk_i+1].co[1] if sk_i + 1 < len(s_c.keyframe_points) else float('inf')
                            if e_c:
                                for ekp in e_c.keyframe_points:
                                    if skp.co[0] <= ekp.co[0] < nxt_f and ekp.co[1] >= skp.co[1]:
                                        f_end = ekp.co[1]
                                        break
                            all_notes.append((f_start, f_end))
                           
                    for f_start, f_end in all_notes:
                        if f_end <= b_frame: left_wall = max(left_wall, f_end)
                        elif f_start >= b_end_frame: right_wall = min(right_wall, f_start)
                           
                min_delta_for_block = left_wall - b_frame
                max_delta_for_block = right_wall - b_end_frame
                pack_min_delta = max(pack_min_delta, min_delta_for_block)
                pack_max_delta = min(pack_max_delta, max_delta_for_block)
               
            if pack_min_delta > pack_max_delta:
                pack_min_delta = pack_max_delta = 0.0
            self._pack_min_delta = float(pack_min_delta)
            self._pack_max_delta = float(pack_max_delta)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
   
    # 1. Служебная кнопка [+] добавления нового канала с кумулятивным отступом
    curr_layout_y = layout['win_h'] - 85
    for i in range(1, scene.octavia_channel_count + 1):
        is_active = (scene.octavia_active_channel == i)
        if is_active and len(scene.octavia_channels_data) >= i:
            num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
            ch_h = num_voices * 30
        else:
            ch_h = 30
        curr_layout_y -= (ch_h + layout['channel_gap'])
    btn_y = curr_layout_y - (30 + layout['channel_gap'])
    
    if (15 <= mx <= 175) and (btn_y <= my <= btn_y + 30):
        bpy.ops.octavia.add_channel()
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # 2. Клики переключения каналов и вызова иерархических HUD-попапов (доверяем радару)
    if scene.octavia_hovered_ch > 0:
        ch_idx = scene.octavia_hovered_ch
        if scene.octavia_active_channel != ch_idx:
            scene.octavia_active_channel = ch_idx
            bpy.ops.octavia.rescan_macros()
            area.tag_redraw()
           
        existing_preset = getattr(scene, f"octavia_ch{ch_idx}_preset", "NONE")
       
        if scene.octavia_hovered_part == "PRESET" or (scene.octavia_hovered_part == "NAME" and existing_preset != "NONE"):
            from ...operator import OCTAVIA_OT_ui_handler
       
            if existing_preset != "NONE":
                OCTAVIA_OT_ui_handler._active_voice_tab = 1
               
                ch_obj = next((o for o in context.scene.objects if o.type == 'MESH' and o.modifiers.get(f"Octavia Channel {ch_idx}")), None)
                obj_name = ch_obj.name if ch_obj else 'UNKNOWN'
                
                context.scene["octavia_selected_mesh_name"] = obj_name
                OCTAVIA_OT_ui_handler._selected_mesh_name = obj_name  
               
                bpy.ops.octavia.rescan_macros()
                from octavia.interface.popup_geometry import prepare_channel_settings_popup
                region = layout.get('region')
                prepare_channel_settings_popup(
                    OCTAVIA_OT_ui_handler, scene, ch_idx,
                    region=region, mx=mx, my=my,
                )
            else:
                from octavia.interface.popup_geometry import set_popup_anchor_region, DEFAULT_POPUP_W
                region = layout.get('region')
                OCTAVIA_OT_ui_handler._selected_channel_idx = ch_idx
                OCTAVIA_OT_ui_handler._active_popup = 'ADD_CHANNEL'
                OCTAVIA_OT_ui_handler._popup_w = DEFAULT_POPUP_W
                OCTAVIA_OT_ui_handler._popup_h = 300
                if region is not None:
                    set_popup_anchor_region(OCTAVIA_OT_ui_handler, region, mx, my)
                else:
                    OCTAVIA_OT_ui_handler._popup_x = mx
                    OCTAVIA_OT_ui_handler._popup_y = my
               
            OCTAVIA_OT_ui_handler._hovered_mesh_name = None
            OCTAVIA_OT_ui_handler._original_selection = [o.name for o in context.selected_objects]
           
            act_obj = context.active_object
            OCTAVIA_OT_ui_handler._original_active = act_obj.name if act_obj else None
            from octavia.interface.popup_draw import tag_octavia_popup_areas, apply_popup_seam_chrome
            apply_popup_seam_chrome()
            tag_octavia_popup_areas(context)
            return {'RUNNING_MODAL'}
           
        elif scene.octavia_hovered_part == "NAME" and existing_preset == "NONE":
            bpy.ops.octavia.rename_channel_popup('INVOKE_DEFAULT', channel_idx=ch_idx)
            return {'RUNNING_MODAL'}

    # Триггер запуска выделения рамкой (Box Select) мимо нот
    if hovered_ch == -1 and mx >= track_x and my < track_y + 45:
        self._is_box_selecting = True
        self._box_start_mx = mx
        self._box_start_my = my
        if not event.ctrl:
            scene.octavia_selected_blocks.clear()
        self._selection_snapshot = {item.name for item in scene.octavia_selected_blocks}
       
        scene["octavia_box_select_active"] = True
        scene["octavia_box_start_x"] = float(mx)
        scene["octavia_box_start_y"] = float(my)
        scene["octavia_box_current_x"] = float(mx)
        scene["octavia_box_current_y"] = float(my)
       
        area.tag_redraw()
        return {'RUNNING_MODAL'}
      
    return None