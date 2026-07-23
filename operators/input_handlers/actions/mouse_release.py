import bpy
from ...vj_core import frame_to_time, quantize_time_to_playhead

def handle_mouse_release(self, context, event, layout, area):
    scene = context.scene
    fps = layout['fps']
    area.tag_redraw()

    # Финализация правого клика (Ластик или Луп)
    if event.type == 'RIGHTMOUSE':
        # Если мы выделяли луп
        if getattr(self, "_is_defining_loop", False):
            self._is_defining_loop = False
            self._loop_anchor_sec = None
            from ..operator import OCTAVIA_OT_ui_handler
            OCTAVIA_OT_ui_handler._defining_loop = False
            
            # Сброс только при чистом клике без драга; маленькие зоны больше не убиваем
            if abs(scene.octavia_loop_start - scene.octavia_loop_end) < 1e-6:
                scene.octavia_loop_active = False
                scene.use_preview_range = False
            else:
                # Контуры и плейхед живут на одной кадровой сетке
                start_sec, start_f = quantize_time_to_playhead(scene.octavia_loop_start, fps)
                end_sec, end_f = quantize_time_to_playhead(scene.octavia_loop_end, fps)
                if end_f <= start_f:
                    end_f = start_f + 1
                    end_sec = frame_to_time(end_f, fps)

                scene.octavia_loop_start = start_sec
                scene.octavia_loop_end = end_sec
                scene.frame_preview_start = start_f
                scene.frame_preview_end = end_f
                scene.use_preview_range = True
                scene.frame_current = start_f
                
            area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Если работал ластик
        if getattr(self, "_is_erasing", False):
            self._is_erasing = False
            scene["octavia_eraser_active"] = False
            bpy.ops.octavia.commit_eraser_transaction()
            area.tag_redraw()
            return {'RUNNING_MODAL'}

    if event.type == 'MIDDLEMOUSE':
        if getattr(self, "_is_panning", False):
            self._is_panning = False
            return {'RUNNING_MODAL'}

    if event.type == 'LEFTMOUSE':
        # Предохранитель перемещения попапа
        if getattr(self, "_is_dragging_popup", False):
            self._is_dragging_popup = False
            return {'RUNNING_MODAL'}

        # Предохранитель кастомных ползунков Октавии
        if getattr(self, "_is_dragging_macro", False):
            self._is_dragging_macro = False
            self._drag_macro_name = ""
            return {'RUNNING_MODAL'}
        # 🎯 ФИНАЛИЗАЦИЯ СКРАББИНГА ШКАЛЫ ВРЕМЕНИ
        if getattr(self, "_is_scrubbing", False):
            self._is_scrubbing = False
            return {'RUNNING_MODAL'}

        # 🔲 ФИНАЛИЗАЦИЯ МАССОВОГО ВЫДЕЛЕНИЯ РАМКОЙ
        if getattr(self, "_is_box_selecting", False):
            self._is_box_selecting = False
            scene["octavia_box_select_active"] = False
            self._selection_snapshot.clear()
            return {'RUNNING_MODAL'}

        if getattr(self, "_is_resizing", False):
            self._is_resizing = False
            offset_frames = int(round(scene.get("octavia_resize_offset_frames", 0.0)))
            ch = scene.get("octavia_resize_ch", -1)
            slot_idx = scene.get("octavia_resize_voice", -1)
            start_frame = scene.get("octavia_resize_frame", -1.0)
            
            if offset_frames != 0 and ch != -1:
                buf_name = f"Octavia_Buffer_Ch_{ch}"
                buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                    act = buf_obj.data.animation_data.action
                    curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
                    if hasattr(act, "layers"):
                        for layer in act.layers:
                            for strip in getattr(layer, "strips", []):
                                for bag in getattr(strip, "channelbags", []): curves.extend(getattr(bag, "fcurves", []))
                                
                    st_path = f'attributes["start_frame"].data[{slot_idx}].value'
                    fc_start = next((c for c in curves if hasattr(c, "data_path") and st_path in c.data_path), None)
                    next_hit_frame = float('inf')
                    if fc_start:
                        kps_st = sorted([k.co[1] for k in fc_start.keyframe_points if k.co[1] >= 1.0])
                        try:
                            f_idx = next(i for i, f in enumerate(kps_st) if abs(f - start_frame) < 0.1)
                            if f_idx < len(kps_st) - 1: next_hit_frame = kps_st[f_idx + 1]
                        except: pass
                        
                    end_path = f'attributes["end_frame"].data[{slot_idx}].value'
                    fc_end = next((c for c in curves if hasattr(c, "data_path") and end_path in c.data_path), None)
                    if fc_end:
                        kp = next((k for k in fc_end.keyframe_points if start_frame <= k.co[0] < next_hit_frame and k.co[1] >= start_frame), None)
                        if kp:
                            new_end = max(start_frame + 2.0, kp.co[1] + offset_frames)
                            kp.co[0] = new_end
                            kp.co[1] = new_end
                        fc_end.keyframe_points.sort()
                        fc_end.update()
            scene["octavia_resize_ch"] = -1
            scene["octavia_resize_offset_frames"] = 0.0
            return {'RUNNING_MODAL'}
       
        if getattr(self, "_is_dragging", False):
            offset_frames = int(round(scene.get("octavia_drag_offset_frames", 0.0)))
           
            if offset_frames != 0:
                items_to_move = []
                for item in scene.octavia_selected_blocks:
                    parts = item.name.split("_")
                    items_to_move.append({
                        'ch': int(parts[1]),
                        'slot_idx': int(parts[3]),
                        'frame': float(parts[5])
                    })
               
                if offset_frames > 0: items_to_move.sort(key=lambda x: x['frame'], reverse=True)
                else: items_to_move.sort(key=lambda x: x['frame'])
                   
                new_selected_ids = []
                
                for block in items_to_move:
                    ch = block['ch']
                    slot_idx = block['slot_idx']
                    start_frame = block['frame']
                    
                    buf_name = f"Octavia_Buffer_Ch_{ch}"
                    buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                    if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                        act = buf_obj.data.animation_data.action
                        curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
                        if hasattr(act, "layers"):
                            for layer in act.layers:
                                for strip in getattr(layer, "strips", []):
                                    for bag in getattr(strip, "channelbags", []): curves.extend(getattr(bag, "fcurves", []))
                                   
                        st_path = f'attributes["start_frame"].data[{slot_idx}].value'
                        end_path = f'attributes["end_frame"].data[{slot_idx}].value'
                        
                        fc_start = next((c for c in curves if hasattr(c, "data_path") and st_path in c.data_path), None)
                        fc_end = next((c for c in curves if hasattr(c, "data_path") and end_path in c.data_path), None)
                        
                        next_hit_frame = float('inf')
                        if fc_start:
                            kps_st = sorted([k.co[1] for k in fc_start.keyframe_points if k.co[1] >= 1.0])
                            try:
                                f_idx = next(i for i, f in enumerate(kps_st) if abs(f - start_frame) < 0.1)
                                if f_idx < len(kps_st) - 1: next_hit_frame = kps_st[f_idx + 1]
                            except: pass
                            
                        # Вытаскиваем кривую голоса
                        fc_voice = next((c for c in curves if hasattr(c, "data_path") and "octavia_voice_id" in c.data_path and f"[{slot_idx}]" in c.data_path), None)

                        if fc_start:
                            kp_st = next((k for k in fc_start.keyframe_points if abs(k.co[0] - start_frame) < 0.1), None)
                            if kp_st:
                                kp_st.co[0] += offset_frames
                                kp_st.co[1] += offset_frames
                            fc_start.keyframe_points.sort()
                            fc_start.update()
                            
                        if fc_end:
                            # Ключ удержания (-1) на старте — раньше оставался на старом кадре
                            kp_hold = next(
                                (k for k in fc_end.keyframe_points
                                 if abs(k.co[0] - start_frame) < 0.1 and k.co[1] < 0.0),
                                None,
                            )
                            if kp_hold:
                                kp_hold.co[0] += offset_frames
                            kp_en = next((k for k in fc_end.keyframe_points if start_frame <= k.co[0] < next_hit_frame and k.co[1] >= start_frame), None)
                            if kp_en:
                                kp_en.co[0] += offset_frames
                                kp_en.co[1] += offset_frames
                            fc_end.keyframe_points.sort()
                            fc_end.update()

                        # 🔥 СИНХРОННЫЙ ПЕРЕНОС КРИВОЙ ГОЛОСА: Двигаем маркер по шкале времени вместе с телом ноты!
                        if fc_voice:
                            kp_vc = next((k for k in fc_voice.keyframe_points if abs(k.co[0] - start_frame) < 0.1), None)
                            if kp_vc:
                                kp_vc.co[0] += offset_frames
                                # co[1] не трогаем, значение ID голоса должно остаться неизменным
                            fc_voice.keyframe_points.sort()
                            fc_voice.update()
                            
                        final_new_frame = int(round(start_frame + offset_frames))
                        new_selected_ids.append(f"ch_{ch}_idx_{slot_idx}_f_{final_new_frame:.1f}")
                        
                scene.octavia_selected_blocks.clear()
                for n_id in new_selected_ids: scene.octavia_selected_blocks.add().name = n_id
            
            self._is_dragging = False
            self._drag_ch = -1
            scene["octavia_drag_ch"] = -1
            scene["octavia_drag_offset_frames"] = 0.0
            return {'RUNNING_MODAL'}

    return {'PASS_THROUGH'}