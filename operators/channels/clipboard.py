import bpy
import sys
from ..vj_core import get_note_body_duration_frames

class OCTAVIA_OT_copy_pulses(bpy.types.Operator):
    """Копирует ритмический рисунок: смещения между ударами и длина hold (без echo)."""
    bl_idname = "octavia.copy_pulses"
    bl_label = "Копировать ритм Октавии"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        if not scene.octavia_selected_blocks:
            self.report({'WARNING'}, "Буфер пуст: сначала выделите блоки нот!")
            return {'CANCELLED'}
            
        selected_blocks = []
        for item in scene.octavia_selected_blocks:
            parts = item.name.split("_")
            ch = int(parts[1])
            slot_idx = int(parts[3])
            frame = float(parts[5])
            
            # Извлекаем честный физический v_id голоса из f-кривых
            buf_name = f"Octavia_Buffer_Ch_{ch}"
            buf_obj = scene.objects.get(buf_name)
            v_id = 0
            if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                from ..vj_core import get_note_timing_curve_maps
                _sc, _ec, voice_curves = get_note_timing_curve_maps(buf_obj.data)
                voice_fc = voice_curves.get(slot_idx)
                if voice_fc:
                    v_id = int(voice_fc.evaluate(frame))
                else:
                    attr = buf_obj.data.attributes.get("octavia_voice_id")
                    v_id = int(attr.data[slot_idx].value) if attr else 0
                    
            ch_data = scene.octavia_channels_data[ch - 1] if len(scene.octavia_channels_data) >= ch else None
            v_idx = next((idx_v for idx_v, v in enumerate(ch_data.voices) if v.hardware_id == v_id), 0) if ch_data else 0
            
            selected_blocks.append({
                'ch': ch,
                'slot_idx': slot_idx,
                'v_idx': v_idx,
                'frame': frame
            })
            
        min_frame = min(b['frame'] for b in selected_blocks)
        fps = scene.render.fps if scene.render.fps > 0 else 24
        max_frame_end = min_frame
        blocks_with_durations = []
        
        for b in selected_blocks:
            buf_name = f"Octavia_Buffer_Ch_{b['ch']}"
            buf_obj = scene.objects.get(buf_name)
            mesh = buf_obj.data if buf_obj else None
            duration_frames = get_note_body_duration_frames(mesh, b['slot_idx'], b['frame'], fps)
            
            b_end = b['frame'] + duration_frames
            if b_end > max_frame_end: max_frame_end = b_end
            blocks_with_durations.append((b, duration_frames))
            
        # Якорь штампа = начало самого левого удара (не середина паттерна)
        anchor_frame = float(min_frame)
        
        sys._octavia_clipboard = []
        sys._octavia_clipboard_source_ch = selected_blocks[0]['ch'] if selected_blocks else -1
        sys._octavia_clipboard_source_min_frame = float(min_frame)
        sys._octavia_clipboard_source_max_frame = float(max_frame_end)
        sys._octavia_clipboard_source_min_voice = min(b['v_idx'] for b in selected_blocks)
        
        for b, dur_frames in blocks_with_durations:
            hit_pos = (0.0, 0.0, 0.0)
            hit_nml = (0.0, 0.0, 0.0)
            salvo = []
            buf_name = f"Octavia_Buffer_Ch_{b['ch']}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data:
                from ..vj_core import read_hit_snapshot, read_salvo_block
                pos, nml = read_hit_snapshot(buf_obj.data, b['slot_idx'], frame=b['frame'])
                hit_pos = (float(pos[0]), float(pos[1]), float(pos[2]))
                hit_nml = (float(nml[0]), float(nml[1]), float(nml[2]))
                for sp, sn in read_salvo_block(buf_obj.data, b['slot_idx'], frame=b['frame']):
                    salvo.append((
                        (float(sp[0]), float(sp[1]), float(sp[2])),
                        (float(sn[0]), float(sn[1]), float(sn[2])),
                    ))
            sys._octavia_clipboard.append({
                'v_idx': b['v_idx'],
                'time_offset_frames': int(round(b['frame'] - anchor_frame)),
                'duration_frames': dur_frames,
                'hit_position': hit_pos,
                'hit_normal': hit_nml,
                'salvo': salvo,
            })
            
        self.report({'INFO'}, f"📋 Грув скопирован! Запечено импульсов: {len(sys._octavia_clipboard)}")
        return {'FINISHED'}


class OCTAVIA_OT_paste_pulses(bpy.types.Operator):
    """Штампует ритм из буфера: hold из копии, echo рисует пресет канала назначения."""
    bl_idname = "octavia.paste_pulses"
    bl_label = "Вставить ритм Октавии"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        fps = scene.render.fps if scene.render.fps > 0 else 24
        
        if not hasattr(sys, "_octavia_clipboard") or not sys._octavia_clipboard:
            self.report({'WARNING'}, "Буфер обмена пуст! Нечего вставлять.")
            return {'CANCELLED'}
            
        hovered_ch = scene.get("octavia_mouse_ch", -1)
        if hovered_ch <= 0: hovered_ch = scene.octavia_active_channel
            
        from ..vj_core import push_undo_step, slot_is_free_before
        push_undo_step(context, [hovered_ch])

        anchor_frame = scene.get("octavia_mouse_frame", -1.0)
        if anchor_frame < 1.0: anchor_frame = float(scene.frame_current)
        anchor_frame = max(1.0, min(float(scene.frame_end), anchor_frame))
        
        new_selected_ids = []
        last_buf_obj = None
        
        for p in sys._octavia_clipboard:
            target_frame = int(round(anchor_frame + p['time_offset_frames']))
            if target_frame < 1 or target_frame > scene.frame_end: continue
            target_end_frame = target_frame + max(2, int(p['duration_frames']))
            
            buf_name = f"Octavia_Buffer_Ch_{hovered_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not buf_obj or not buf_obj.data: continue
            last_buf_obj = buf_obj
            
            mesh = buf_obj.data
            start_attr = mesh.attributes.get("start_frame")
            end_attr = mesh.attributes.get("end_frame")
            if not start_attr or not end_attr: continue
            
            held_indices = []
            free_indices = []
            max_safe_slots = min(128, len(start_attr.data))
            
            for i in range(max_safe_slots):
                s_val = start_attr.data[i].value
                e_val = end_attr.data[i].value
                if e_val == -1.0 and s_val != -1.0:
                    held_indices.append((i, s_val))
                elif slot_is_free_before(mesh, i, target_frame):
                    free_indices.append((i, e_val))
                    
            chosen_idx = -1
            if free_indices:
                free_indices.sort(key=lambda x: x[1])
                chosen_idx = free_indices[0][0]
            else:
                safe_held = [(i, s) for i, s in held_indices if slot_is_free_before(mesh, i, target_frame)]
                if safe_held:
                    safe_held.sort(key=lambda x: x[1])
                    chosen_idx = safe_held[0][0]
                elif held_indices:
                    held_indices.sort(key=lambda x: x[1])
                    chosen_idx = held_indices[0][0]
                else:
                    chosen_idx = 0
                
            mouse_voice_floor = scene.get("octavia_mouse_voice", 0)
            source_min_voice = getattr(sys, "_octavia_clipboard_source_min_voice", 0)
            voice_offset = mouse_voice_floor - source_min_voice
            
            ch_data = scene.octavia_channels_data[hovered_ch - 1] if len(scene.octavia_channels_data) >= hovered_ch else None
            target_v_idx = p['v_idx'] + voice_offset
            
            if ch_data and 0 <= target_v_idx < len(ch_data.voices):
                active_v_idx = ch_data.voices[target_v_idx].hardware_id
            else:
                active_v_idx = ch_data.voices[ch_data.active_voice_idx].hardware_id if ch_data else 0
                
            voice_id_attr = mesh.attributes.get("octavia_voice_id")

            start_attr.data[chosen_idx].value = float(target_frame)
            end_attr.data[chosen_idx].value = float(target_end_frame)
            if voice_id_attr:
                voice_id_attr.data[chosen_idx].value = float(active_v_idx)
            
            start_path = f'attributes["start_frame"].data[{chosen_idx}].value'
            end_path = f'attributes["end_frame"].data[{chosen_idx}].value'
            voice_id_path = f'attributes["octavia_voice_id"].data[{chosen_idx}].value'

            mesh.keyframe_insert(data_path=start_path, frame=target_frame)
            # Hold-ключ на ударе (-1), потом release — как при живой записи
            end_attr.data[chosen_idx].value = -1.0
            mesh.keyframe_insert(data_path=end_path, frame=target_frame)
            end_attr.data[chosen_idx].value = float(target_end_frame)
            mesh.keyframe_insert(data_path=end_path, frame=target_end_frame)
            if voice_id_attr:
                mesh.keyframe_insert(data_path=voice_id_path, frame=target_frame)

            # Снимок удара: копируем из клипборда (или нули для старых записей)
            from mathutils import Vector
            from ..vj_core import write_hit_snapshot, write_salvo_block, ensure_buffer_topology
            ensure_buffer_topology(mesh)
            hit_pos = Vector(p.get('hit_position', (0.0, 0.0, 0.0)))
            hit_nml = Vector(p.get('hit_normal', (0.0, 0.0, 0.0)))
            write_hit_snapshot(mesh, chosen_idx, hit_pos, hit_nml, target_frame)
            salvo_raw = p.get('salvo') or []
            samples = [(Vector(sp), Vector(sn)) for sp, sn in salvo_raw]
            write_salvo_block(
                mesh, chosen_idx, samples, target_frame,
                end_hold=-1.0, voice_id=float(active_v_idx),
            )
            # end_frame тела ноты уже проставлен ниже по времени — синхронизируем залп
            from ..vj_core import sync_salvo_end_frame
            sync_salvo_end_frame(mesh, chosen_idx, target_end_frame)
            
            if mesh.animation_data and mesh.animation_data.action:
                act = mesh.animation_data.action
                curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
                if hasattr(act, "layers"):
                    for layer in act.layers:
                        for strip in getattr(layer, "strips", []):
                            for bag in getattr(strip, "channelbags", []): curves.extend(getattr(bag, "fcurves", []))
                for fc in curves:
                    if hasattr(fc, "data_path") and (
                        "start_frame" in fc.data_path
                        or "end_frame" in fc.data_path
                        or "hit_position" in fc.data_path
                        or "hit_normal" in fc.data_path
                        or "burst_position" in fc.data_path
                        or "burst_normal" in fc.data_path
                        or "burst_sub_index" in fc.data_path
                    ):
                        for kp in fc.keyframe_points: kp.interpolation = 'CONSTANT'
                        fc.update()
            new_selected_ids.append(f"ch_{hovered_ch}_idx_{chosen_idx}_f_{target_frame:.1f}")
            
        scene.octavia_selected_blocks.clear()
        for n_id in new_selected_ids: scene.octavia_selected_blocks.add().name = n_id
            
        bpy.ops.octavia.rescan_macros()
        if last_buf_obj:
            last_buf_obj.update_tag()
        context.view_layer.update()
        
        return {'FINISHED'}


class OCTAVIA_OT_commit_eraser_transaction(bpy.types.Operator):
    """Физически вырезает ключи нот из ДНК Блендера, полностью ликвидируя мусор"""
    bl_idname = "octavia.commit_eraser_transaction"
    bl_label = "Фиксация очистки Октавии"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        import sys
        scene = context.scene
     
        erased_set = getattr(sys, "_octavia_virtual_erased", set())
        if not erased_set:
            return {'FINISHED'}
            
        obj = context.active_object
        if not obj: return {'CANCELLED'}
            
        target_channels = set()
        for b_id in erased_set:
            parts = b_id.split("_")
            target_channels.add(int(parts[1]))
            
        from ..vj_core import push_undo_step
        # Слепок ДО удаления: без ID из текущего erased_set, иначе undo вернёт
        # ноты, а таймлайн будет считать их «стёртыми-призраками».
        erased_now = set(erased_set)
        sys._octavia_virtual_erased = set()
        push_undo_step(context, target_channels)
        sys._octavia_virtual_erased = erased_now
        erased_set = erased_now

        blocks_by_ch = {}
        for b_id in erased_set:
            parts = b_id.split("_")
            ch = int(parts[1])
            slot_idx = int(parts[3])
            frame = float(parts[5])
            if ch not in blocks_by_ch: blocks_by_ch[ch] = []
            blocks_by_ch[ch].append((slot_idx, frame))
            
        for ch, block_list in blocks_by_ch.items():
            buf_name = f"Octavia_Buffer_Ch_{ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not (buf_obj and buf_obj.data):
                continue
            mesh = buf_obj.data
            from ..vj_core import (
                clear_salvo_block_keys,
                wipe_note_slot_residue,
                iter_action_fcurves_with_owners,
            )

            has_action = bool(mesh.animation_data and mesh.animation_data.action)
            curves_with_owners = []
            start_curves = {}
            end_curves = {}
            voice_curves = {}
            hit_curves = {}

            if has_action:
                act = mesh.animation_data.action
                from ..vj_core import safe_fcurve_data_path, parse_attribute_data_path
                curves_with_owners = list(iter_action_fcurves_with_owners(act))
                for fc, owner in curves_with_owners:
                    dp = safe_fcurve_data_path(fc)
                    if not dp or "attributes[" not in dp:
                        continue
                    try:
                        name, s_idx = parse_attribute_data_path(dp)
                        if s_idx is None:
                            continue
                        if name == "start_frame":
                            start_curves[s_idx] = (fc, owner)
                        elif name == "end_frame":
                            end_curves[s_idx] = (fc, owner)
                        elif name == "octavia_voice_id":
                            voice_curves[s_idx] = (fc, owner)
                        elif name in ("hit_position", "hit_normal"):
                            hit_curves.setdefault(s_idx, []).append((fc, owner))
                    except Exception:
                        pass

            slots_to_clean = {}
            for slot_idx, frame in block_list:
                if slot_idx not in slots_to_clean:
                    slots_to_clean[slot_idx] = []
                slots_to_clean[slot_idx].append(frame)

            for slot_idx, block_frames in slots_to_clean.items():
                st_tuple = start_curves.get(slot_idx)
                en_tuple = end_curves.get(slot_idx)

                for start_frame in block_frames:
                    next_hit_frame = float('inf')
                    if st_tuple:
                        st_fc, st_owner = st_tuple
                        kps_st = sorted(
                            [k.co[1] for k in st_fc.keyframe_points if k.co[1] >= 1.0]
                        )
                        try:
                            f_idx = next(
                                i for i, f in enumerate(kps_st)
                                if abs(f - start_frame) < 0.1
                            )
                            if f_idx < len(kps_st) - 1:
                                next_hit_frame = kps_st[f_idx + 1]
                        except StopIteration:
                            pass

                        changed_st = False
                        for kp in reversed(list(st_fc.keyframe_points)):
                            if abs(kp.co[0] - start_frame) < 0.1:
                                st_fc.keyframe_points.remove(kp)
                                changed_st = True
                        if changed_st:
                            st_fc.keyframe_points.sort()
                        st_fc.update()

                    if en_tuple:
                        en_fc, en_owner = en_tuple
                        changed_en = False
                        for kp in reversed(list(en_fc.keyframe_points)):
                            if start_frame - 0.5 <= kp.co[0] < next_hit_frame - 0.5:
                                en_fc.keyframe_points.remove(kp)
                                changed_en = True
                        if changed_en:
                            en_fc.keyframe_points.sort()
                            en_fc.update()

                    v_tuple = voice_curves.get(slot_idx)
                    if v_tuple:
                        v_fc, v_owner = v_tuple
                        changed_v = False
                        for kp in reversed(list(v_fc.keyframe_points)):
                            if abs(kp.co[0] - start_frame) < 0.1:
                                v_fc.keyframe_points.remove(kp)
                                changed_v = True
                        if changed_v:
                            v_fc.keyframe_points.sort()
                        v_fc.update()

                    for h_fc, h_owner in hit_curves.get(slot_idx, []):
                        changed_h = False
                        for kp in reversed(list(h_fc.keyframe_points)):
                            if abs(kp.co[0] - start_frame) < 0.1:
                                h_fc.keyframe_points.remove(kp)
                                changed_h = True
                        if changed_h:
                            h_fc.keyframe_points.sort()
                        h_fc.update()

                    try:
                        clear_salvo_block_keys(
                            mesh,
                            slot_idx,
                            start_frame,
                            curves_with_owners=curves_with_owners or None,
                            next_hit_frame=next_hit_frame,
                        )
                    except Exception as e:
                        print(f"[Octavia] clear_salvo_block_keys slot{slot_idx}@{start_frame}: {e}")

                # Слот без оставшихся start>=1 → полный attr wipe (spreadsheet)
                still_live = False
                if st_tuple:
                    st_fc, st_owner = st_tuple
                    still_live = any(float(k.co[1]) >= 1.0 for k in st_fc.keyframe_points)
                    if len(st_fc.keyframe_points) == 0 and st_owner:
                        try:
                            st_owner.remove(st_fc)
                        except Exception:
                            pass
                if en_tuple:
                    en_fc, en_owner = en_tuple
                    if len(en_fc.keyframe_points) == 0 and en_owner:
                        try:
                            en_owner.remove(en_fc)
                        except Exception:
                            pass
                v_tuple = voice_curves.get(slot_idx)
                if v_tuple:
                    v_fc, v_owner = v_tuple
                    if len(v_fc.keyframe_points) == 0 and v_owner:
                        try:
                            v_owner.remove(v_fc)
                        except Exception:
                            pass
                for h_fc, h_owner in hit_curves.get(slot_idx, []):
                    if len(h_fc.keyframe_points) == 0 and h_owner:
                        try:
                            h_owner.remove(h_fc)
                        except Exception:
                            pass

                if not still_live:
                    wipe_note_slot_residue(mesh, slot_idx)

        from ..vj_core import (
            sanitize_buffer_after_erase,
            clear_note_timing_maps_cache,
            clear_onset_latch,
            mark_buffer_attrs_need_purge,
        )
        clear_note_timing_maps_cache()
        clear_onset_latch()

        # После ластика: мёртвые слоты + полный wipe если canvas пуст
        for ch in blocks_by_ch.keys():
            b_name = f"Octavia_Buffer_Ch_{ch}"
            b_obj = scene.objects.get(b_name) or bpy.data.objects.get(b_name)
            if not (b_obj and b_obj.data):
                continue
            try:
                mark_buffer_attrs_need_purge(b_obj.data)
                sanitize_buffer_after_erase(b_obj.data)
                b_obj.data.update()
                b_obj.update_tag()
            except Exception as e:
                print(f"[Octavia] sanitize after erase Ch{ch}: {e}")

        for b_id in list(erased_set):
            alt_id = b_id.replace("_idx_", "_v_") if "_idx_" in b_id else b_id.replace("_v_", "_idx_")
            for target_id in (b_id, alt_id):
                d_idx = next((idx for idx, x in enumerate(scene.octavia_selected_blocks) if x.name == target_id), None)
                if d_idx is not None:
                    scene.octavia_selected_blocks.remove(d_idx)
         
        erased_set.clear()
        bpy.ops.octavia.rescan_macros()
        obj.update_tag()
        context.view_layer.update()
        
        return {'FINISHED'}