import bpy
import sys

# ─── ЕДИНЫЙ КВАНТОВЫЙ ХРОНОМЕТР OCTAVIA ───
def frame_to_time(frame, fps):
    return (frame - 1) / fps

def time_to_frame(sec, fps):
    return sec * fps + 1

def quantize_time_to_playhead(sec, fps):
    """Секунды мыши → ближайший кадр и секунды, на которых реально стоит плейхед."""
    frame = max(1, int(round(time_to_frame(sec, fps))))
    return frame_to_time(frame, fps), frame

def adaptive_snap_seconds(sec, bpm, pixels_per_second):
    """Музыкальный SNAP с шагом, зависящим от зума — без гигантских прыжков на близком зуме."""
    seconds_per_beat = 60.0 / max(1, bpm)
    seconds_per_step = seconds_per_beat / 4.0
    step_px = seconds_per_step * pixels_per_second
    if step_px >= 14:
        music_step_sec = seconds_per_step
    elif (step_px * 4) >= 8:
        music_step_sec = seconds_per_beat
    else:
        music_step_sec = seconds_per_beat * 4
    if music_step_sec <= 0:
        return max(0.0, sec)
    step_idx = round(sec / music_step_sec)
    return max(0.0, step_idx * music_step_sec)


def iter_action_fcurves(action):
    """Все fcurves экшена, включая раскладку Blender 5.1 (layers/strips/channelbags)."""
    curves = list(getattr(action, "curves", getattr(action, "fcurves", [])))
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in getattr(layer, "strips", []):
                for bag in getattr(strip, "channelbags", []):
                    curves.extend(getattr(bag, "fcurves", []))
    return curves


def slot_latest_key_time(mesh, slot_idx):
    """Последний кадр (co[0]) любого ключа start/end/voice на этом слоте."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return -1.0
    needle = f"[{slot_idx}]"
    latest = -1.0
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if not hasattr(fc, "data_path") or needle not in fc.data_path:
            continue
        if "attributes[" not in fc.data_path:
            continue
        for kp in fc.keyframe_points:
            latest = max(latest, kp.co[0])
    return latest


def slot_is_free_before(mesh, slot_idx, target_frame):
    """Слот можно переиспользовать, если все его ключи строго ДО нового удара."""
    return slot_latest_key_time(mesh, slot_idx) < float(target_frame) - 0.1


def fcurve_slot_value(mesh, slot_idx, attr_name, frame):
    """Значение атрибута слота на кадре frame (из f-кривой, не сырой вершины)."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return None
    data_path = f'attributes["{attr_name}"].data[{slot_idx}].value'
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if hasattr(fc, "data_path") and data_path in fc.data_path:
            return fc.evaluate(frame)
    return None

# 🛰️ СВЕРХТОЧНЫЙ ТЕЛЕМЕТРИЧЕСКИЙ ЗОНД СТЕКА ИСТОРИИ ОКТАВИИ

def capture_daw_snapshot(context, target_channels):
    import sys
    scene = context.scene

    snapshot = {
        'channels': {},
        'selected_blocks': [item.name for item in scene.octavia_selected_blocks],
        'virtual_erased': list(getattr(sys, "_octavia_virtual_erased", set()))
    }

    # 🪐 ЗОНД ИСТОРИИ: Запекаем текущее положение ползунков всех голосов в слепок
    snapshot['voices_props'] = {}
    if hasattr(scene, "octavia_channels_data"):
        for c_idx, ch_data in enumerate(scene.octavia_channels_data, start=1):
            ch_v_list = []
            for v in ch_data.voices:
                ch_v_list.append({
                    'punch': v.punch, 'hold': v.hold, 'echo': v.echo,
                    'macro_overrides': [{"macro_id": mo.macro_id, "value": mo.value} for mo in v.macro_overrides],
                    'key_code': v.key_code, 'name': v.name
                })
            snapshot['voices_props'][c_idx] = ch_v_list
   
    for ch in target_channels:
        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if not buf_obj:
            continue
            
        if not (buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action):
            continue
           
        act = buf_obj.data.animation_data.action
        curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
        
        # Сканируем 5.1+ слои
        layers_count = 0
        strips_count = 0
        bags_count = 0
        if hasattr(act, "layers"):
            for layer in act.layers:
                layers_count += 1
                for strip in getattr(layer, "strips", []):
                    strips_count += 1
                    for bag in getattr(strip, "channelbags", []):
                        bags_count += 1
                        curves.extend(getattr(bag, "fcurves", []))
                        
        ch_curves_backup = {}
        captured_kps_total = 0
        for fc in curves:
            if hasattr(fc, "data_path") and "attributes[" in fc.data_path:
                kps_data = [(kp.co[0], kp.co[1], kp.interpolation) for kp in fc.keyframe_points]
                ch_curves_backup[fc.data_path] = kps_data
                captured_kps_total += len(kps_data)
                
        snapshot['channels'][ch] = ch_curves_backup
       
    return snapshot

def push_undo_step(context, target_channels):
    import sys
    if not target_channels:
        return
       
    snapshot = capture_daw_snapshot(context, target_channels)
    if snapshot:
        if not hasattr(sys, "_octavia_undo_stack"): sys._octavia_undo_stack = []
        if not hasattr(sys, "_octavia_redo_stack"): sys._octavia_redo_stack = []
           
        sys._octavia_undo_stack.append(snapshot)
        sys._octavia_redo_stack.clear()
       
        if len(sys._octavia_undo_stack) > 100:
            sys._octavia_undo_stack.pop(0)


def apply_daw_snapshot(context, snapshot):
    import sys
    scene = context.scene
    if not snapshot:
        return

    # Взводим щит: гасим колбэки, чтобы Блендер не улетел в бесконечный цикл пересчета
    from .input_handlers.operator import OCTAVIA_OT_ui_handler
    OCTAVIA_OT_ui_handler._block_sync_callbacks = True
    
    try:
        # Реставрируем положение крутилок каждого голоса из RAM-памяти истории
        if 'voices_props' in snapshot and hasattr(scene, "octavia_channels_data"):
            for c_idx, ch_v_list in snapshot['voices_props'].items():
                if c_idx <= len(scene.octavia_channels_data):
                    ch_data = scene.octavia_channels_data[c_idx - 1]
                    for v_idx, saved_v in enumerate(ch_v_list):
                        if v_idx < len(ch_data.voices):
                            v = ch_data.voices[v_idx]
                            v.punch = saved_v['punch']
                            v.hold = saved_v['hold']
                            v.echo = saved_v['echo']
                            v.key_code = saved_v['key_code']
                            v.name = saved_v['name']

                            # 🪐 РЕСТАВРАЦИЯ КАСТОМНЫХ МАКРОСОВ СЛОЯ ИСТОРИИ
                            v.macro_overrides.clear()
                            for mo_data in saved_v.get('macro_overrides', []):
                                mo = v.macro_overrides.add()
                                mo.name = mo_data['macro_id']
                                mo.macro_id = mo_data['macro_id']
                                mo.value = mo_data['value']
    except Exception as e:
        print(f"  ⚠️ Ошибка восстановления параметров голосов: {e}")

    for ch, curves_data in snapshot['channels'].items():
        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if not buf_obj:
            print(f"    ❌ Критическая ошибка отмены: Меш {buf_name} испарился!")
            continue
           
        act = buf_obj.data.animation_data.action
        curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
        if hasattr(act, "layers"):
            for layer in act.layers:
                for strip in getattr(layer, "strips", []):
                    for bag in getattr(strip, "channelbags", []): curves.extend(getattr(bag, "fcurves", []))
                       
        restored_paths = 0
        restored_kps = 0
        for fc in curves:
            if hasattr(fc, "data_path") and fc.data_path in curves_data:
                saved_kps = curves_data[fc.data_path]
                restored_paths += 1
                
                try:
                    for kp in reversed(list(fc.keyframe_points)):
                        fc.keyframe_points.remove(kp)
                except Exception as e_clean:
                    print(f"    ⚠️ Ошибка очистки точек на пути {fc.data_path}: {e_clean}")
                    
                for f_frame, val, interp in saved_kps:
                    try:
                        kp = fc.keyframe_points.insert(f_frame, val)
                        kp.interpolation = interp
                        restored_kps += 1
                    except Exception as e_ins:
                        print(f"    💥 Ошибка C++ ядра при вставке ключа ({f_frame}, {val}) на {fc.data_path}: {e_ins}")
                       
                fc.update()
                
        try:
            buf_obj.update_tag()
            if buf_obj.data: buf_obj.data.update()
        except Exception as e_tag:
            print(f"    ⚠️ Не удалось пнуть update_tag меша: {e_tag}")
               
    scene.octavia_selected_blocks.clear()
    for b_name in snapshot['selected_blocks']:
        scene.octavia_selected_blocks.add().name = b_name

    sys._octavia_virtual_erased = set()

    try:
        if context.active_object and context.active_object.animation_data and context.active_object.animation_data.action:
            context.active_object.animation_data.action.update_tag()
        
        current_f = scene.frame_current
        scene.frame_set(current_f)
        context.view_layer.update()
    except Exception as e_scene:
        print(f"  ⚠️ Ошибка обновления слоёв ViewLayer сцены: {e_scene}")
    finally:
        # Наглухо опускаем щит, возвращая ручкам интерактивность
        OCTAVIA_OT_ui_handler._block_sync_callbacks = False

def execute_octavia_undo(context):
    import sys
    if not hasattr(sys, "_octavia_undo_stack") or not sys._octavia_undo_stack:
        return
       
    snapshot_to_restore = sys._octavia_undo_stack.pop()
    target_channels = list(snapshot_to_restore['channels'].keys())
    
    redo_snapshot = capture_daw_snapshot(context, target_channels)
    if redo_snapshot:
        if not hasattr(sys, "_octavia_redo_stack"): sys._octavia_redo_stack = []
        sys._octavia_redo_stack.append(redo_snapshot)
       
    apply_daw_snapshot(context, snapshot_to_restore)
   
    if context.active_object:
        try: context.active_object.update_tag()
        except: pass
    bpy.ops.octavia.rescan_macros()


def execute_octavia_redo(context):
    import sys
    if not hasattr(sys, "_octavia_redo_stack") or not sys._octavia_redo_stack:
        return
       
    snapshot_to_restore = sys._octavia_redo_stack.pop()
    target_channels = list(snapshot_to_restore['channels'].keys())
    
    undo_snapshot = capture_daw_snapshot(context, target_channels)
    if undo_snapshot:
        sys._octavia_undo_stack.append(undo_snapshot)
       
    apply_daw_snapshot(context, snapshot_to_restore)
   
    if context.active_object:
        try: context.active_object.update_tag()
        except: pass
    bpy.ops.octavia.rescan_macros()

class OCTAVIA_OT_vj_listener(bpy.types.Operator):
    bl_idname = "octavia.vj_listener"
    bl_label = "Octavia Listener"
   
    def modal(self, context, event):
        if not context.scene.vj_record_mode:
            return {'FINISHED'}
           
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}
           
        triggered = False
        ch_idx = context.scene.octavia_active_channel
        if len(context.scene.octavia_channels_data) >= ch_idx:
            ch_data = context.scene.octavia_channels_data[ch_idx - 1]
           
            # 🛸 САМОЛЕЧЕНИЕ ИНДЕКСОВ СТАРЫХ ГОЛОСОВ (VOICE ID ANTI-COLLISION)
            # Если Блендер занулил hardware_id у старых вкладок, принудительно разводим их по уникальным этажам
            hw_ids = [v.hardware_id for v in ch_data.voices]
            if len(hw_ids) != len(set(hw_ids)):
                for i, v in enumerate(ch_data.voices):
                    v.hardware_id = i

            # 🛡️ БРОНЕБОЙНЫЙ ЩИТ ПОВТОРОВ: Тушим автоповтор ОС для всей спарки разом
            if event.value == 'PRESS' and event.is_repeat:
                if any(event.type == voice.key_code for voice in ch_data.voices):
                    return {'RUNNING_MODAL'}
           
            # Прокатываемся по всей коллекции, передавая физический hardware_id
            for idx, voice in enumerate(ch_data.voices):
                if voice.key_code and event.type == voice.key_code:
                    if event.value == 'PRESS':
                        bpy.ops.octavia.kick_trigger(action='PRESS', voice_id=voice.hardware_id)
                        triggered = True
                    elif event.value == 'RELEASE':
                        bpy.ops.octavia.kick_trigger(action='RELEASE', voice_id=voice.hardware_id)
                        triggered = True
       
        # Если хотя бы один голос сработал — поглощаем клавишу в Октавию
        if triggered:
            return {'RUNNING_MODAL'}
            
        return {'PASS_THROUGH'}
       
    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

class OCTAVIA_OT_kick_trigger(bpy.types.Operator):
    bl_idname = "octavia.kick_trigger"
    bl_label = "Trigger Octavia Kick"
   
    # 🔥 ЖЕЛЕЗНЫЙ ФИКС RNA-РЕГИСТРАЦИИ: Переводим свойства на аннотации типов Блендера
    action: bpy.props.EnumProperty(
        items=[('PRESS', "Press", ""), ('RELEASE', "Release", "")],
        default='PRESS'
    )
    voice_id: bpy.props.IntProperty(default=0, description="Индекс голоса в коллекции канала")

    def execute(self, context):
        scene = context.scene
        active_ch = scene.octavia_active_channel
        fps = scene.render.fps if scene.render.fps > 0 else 24

        # 🪐 ФАЗА 1: НАЖАТИЕ КНОПКИ (ВЫДЕЛЕНИЕ АНАЛИТИЧЕСКОГО СЛОТА)
        if self.action == 'PRESS':
            raw_frame = scene.frame_current
           
            if getattr(scene, "octavia_snap", True):
                seconds_per_beat = 60.0 / scene.octavia_bpm
                seconds_per_step = seconds_per_beat / 4
                frames_per_step = seconds_per_step * fps
                step_idx = int(round((raw_frame - 1) / frames_per_step))
                target_frame = int(round(step_idx * frames_per_step + 1))
                target_frame = max(1, min(scene.frame_end, target_frame))
            else:
                target_frame = raw_frame

            buf_name = f"Octavia_Buffer_Ch_{active_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not buf_obj or not buf_obj.data:
                return {'CANCELLED'}
               
            mesh = buf_obj.data
            
            # =========================================================================
            # 🛸 СУВЕРЕННЫЙ ДВИГАТЕЛЬ МИГРАЦИИ ОКТАВИИ (ВСТАВЛЯТЬ СТРОГО СЮДА)
            # =========================================================================
            required_attrs = {
                "start_frame": -1.0,
                "end_frame": -1.0,
                "octavia_voice_id": -1.0,
                "octavia_macro_punch": 0.5,
                "octavia_macro_hold": 0.5,
                "octavia_macro_echo": 0.5
            }
            mesh_was_outdated = False
            for attr_name, default_val in required_attrs.items():
                if attr_name not in mesh.attributes:
                    mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
                    # Инициализируем новые ячейки безопасными значениями
                    for d in mesh.attributes[attr_name].data:
                        d.value = default_val
                    mesh_was_outdated = True
            
            if mesh_was_outdated:
                mesh.update()
                buf_obj.update_tag()
            # =========================================================================

            start_attr = mesh.attributes.get("start_frame")
            end_attr = mesh.attributes.get("end_frame")
            voice_id_attr = mesh.attributes.get("octavia_voice_id")
            if not start_attr or not end_attr:
                return {'CANCELLED'}

            # 🛡️ ЧИТАЕМ СТЕЙТЫ НАПРЯМУЮ ИЗ АНИМАЦИОННЫХ КРИВЫХ БЛЕНДЕРА
            active_slots = {}  # slot_idx -> last_start_frame
            held_slots = set() # слоты, у которых нота сейчас зажата (end_frame == -1)
            
            if mesh.animation_data and mesh.animation_data.action:
                act = mesh.animation_data.action
                curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
                if hasattr(act, "layers"):
                    for layer in act.layers:
                        for strip in getattr(layer, "strips", []):
                            for bag in getattr(strip, "channelbags", []): 
                                curves.extend(getattr(bag, "fcurves", []))
                                
                import re
                for fc in curves:
                    if not fc.data_path: continue
                    match = re.search(r'data\[(\d+)\]', fc.data_path)
                    if not match: continue
                    idx = int(match.group(1))
                    
                    if "start_frame" in fc.data_path and fc.keyframe_points:
                        # Берем кадр последнего удара в этом слоте
                        active_slots[idx] = fc.keyframe_points[-1].co[1]
                    if "end_frame" in fc.data_path and fc.keyframe_points:
                        # Если последнее значение -1.0, значит нота еще удерживается
                        if fc.keyframe_points[-1].co[1] == -1.0:
                            held_slots.add(idx)

            # =========================================================================
            # 🛡️ ЗАЩИТА СТАРЫХ СОХРАНЕНИЙ: Динамический лимит слотов вместо хардкода 128
            # =========================================================================
            max_slots = 128 if len(start_attr.data) >= 128 else len(start_attr.data)
            # =========================================================================

            # Ищем идеальный пустой или освободившийся слот
            chosen_idx = -1
            
            # 1. Абсолютно чистый слот
            for i in range(max_slots):
                if i not in active_slots and i not in held_slots:
                    chosen_idx = i
                    break
            
            # 2. Переиспользование — только если ВСЕ ключи слота раньше нового удара
            if chosen_idx == -1:
                released_slots = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                    and slot_is_free_before(mesh, idx, target_frame)
                }
                if released_slots:
                    chosen_idx = min(released_slots, key=released_slots.get)
            
            # 3. Крайний случай: незажатый слот, но только без пересечения по времени
            if chosen_idx == -1:
                released_any = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                    and slot_is_free_before(mesh, idx, target_frame)
                }
                if released_any:
                    chosen_idx = min(released_any, key=released_any.get)
            
            # 4. Паника: любой незажатый (может пересечься — крайний случай)
            if chosen_idx == -1:
                released_overlap = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                }
                if released_overlap:
                    chosen_idx = min(released_overlap, key=released_overlap.get)
            
            # 5. Всё зажато — сбиваем самый старый активный
            if chosen_idx == -1:
                valid_active = {idx: f for idx, f in active_slots.items() if idx < max_slots}
                chosen_idx = min(valid_active, key=valid_active.get) if valid_active else 0

            # Записываем физические данные в меш и сразу жестко запекаем ключевой кадр
            start_attr.data[chosen_idx].value = float(target_frame)
            end_attr.data[chosen_idx].value = -1.0
            if voice_id_attr:
                voice_id_attr.data[chosen_idx].value = float(self.voice_id)
           
            start_path = f'attributes["start_frame"].data[{chosen_idx}].value'
            end_path = f'attributes["end_frame"].data[{chosen_idx}].value'
            voice_id_path = f'attributes["octavia_voice_id"].data[{chosen_idx}].value'
           
            mesh.keyframe_insert(data_path=start_path, frame=target_frame)
            mesh.keyframe_insert(data_path=end_path, frame=target_frame)
            if voice_id_attr:
                mesh.keyframe_insert(data_path=voice_id_path, frame=target_frame)

            # Выпрямление f-кривых (Бронебойный сканер Blender 5.1+)
            if mesh.animation_data and mesh.animation_data.action:
                for fc in iter_action_fcurves(mesh.animation_data.action):
                    if hasattr(fc, "data_path") and "attributes" in fc.data_path:
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'CONSTANT'
                        fc.update()

        # 🪐 ФАЗА 2: ОТПУСКАНИЕ КНОПКИ (ЗАКРЫТИЕ ВСЕХ АКТИВНЫХ ГОЛОСОВ ТРЕКА)
        elif self.action == 'RELEASE':
            raw_release_frame = scene.frame_current
           
            if getattr(scene, "octavia_snap", True):
                seconds_per_beat = 60.0 / scene.octavia_bpm
                seconds_per_step = seconds_per_beat / 4
                frames_per_step = seconds_per_step * fps
                step_idx = int(round((raw_release_frame - 1) / frames_per_step))
                target_release_frame = int(round(step_idx * frames_per_step + 1))
            else:
                target_release_frame = raw_release_frame

            buf_name = f"Octavia_Buffer_Ch_{active_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data:
                mesh = buf_obj.data
                start_attr = mesh.attributes.get("start_frame")
                end_attr = mesh.attributes.get("end_frame")
               
                if start_attr and end_attr:
                    voice_id_attr = mesh.attributes.get("octavia_voice_id")
                   
                    # Закрываем только ноты, реально удерживаемые НА КАДРЕ отпускания.
                    # Сырой end_attr.data[i] нельзя — rescan/старые данные дают -1 на всех слотах.
                    for i in range(min(128, len(end_attr.data))):
                        v_id_on_vertex = voice_id_attr.data[i].value if voice_id_attr else 0.0
                        if float(self.voice_id) != v_id_on_vertex:
                            continue
                        start_at_rel = fcurve_slot_value(mesh, i, "start_frame", target_release_frame)
                        end_at_rel = fcurve_slot_value(mesh, i, "end_frame", target_release_frame)
                        if start_at_rel is None or end_at_rel is None:
                            continue
                        if start_at_rel < 1.0 or start_at_rel > float(target_release_frame):
                            continue
                        if end_at_rel >= 0.0:
                            continue
                        final_release = max(start_at_rel + 2.0, float(target_release_frame))
                        end_attr.data[i].value = final_release
                        end_path = f'attributes["end_frame"].data[{i}].value'
                        mesh.keyframe_insert(data_path=end_path, frame=final_release)

                    if mesh.animation_data and mesh.animation_data.action:
                        for fc in iter_action_fcurves(mesh.animation_data.action):
                            if hasattr(fc, "data_path") and "end_frame" in fc.data_path:
                                for kp in fc.keyframe_points:
                                    kp.interpolation = 'CONSTANT'
                                fc.update()

        buf_name = f"Octavia_Buffer_Ch_{active_ch}"
        buf_obj = scene.objects.get(buf_name)
        if buf_obj:
            buf_obj.update_tag()
           
        context.view_layer.update()
        return {'FINISHED'}
    
class OCTAVIA_OT_toggle_mode(bpy.types.Operator):
    bl_idname = "octavia.toggle_mode"
    bl_label = "Toggle Octavia Mode"
   
    def execute(self, context):
        scene = context.scene
        scene.vj_record_mode = not scene.vj_record_mode
        obj = context.active_object
       
        if not obj:
            return {'CANCELLED'}

        if scene.vj_record_mode:
            bpy.ops.octavia.vj_listener('INVOKE_DEFAULT')
               
        obj.update_tag()
        context.view_layer.update()
        return {'FINISHED'}