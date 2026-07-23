import bpy

def handle_active_popup(self, context, event, layout, mx, my, active_popup, area):
    from octavia.operators.input_handlers.operator import OCTAVIA_OT_ui_handler
    scene = context.scene
    
    px = OCTAVIA_OT_ui_handler._popup_x
    py = OCTAVIA_OT_ui_handler._popup_y
    pw = OCTAVIA_OT_ui_handler._popup_w
    ph = OCTAVIA_OT_ui_handler._popup_h
   
    if active_popup == 'CHANNEL_SETTINGS':
        ph = 440
   
    # Полный гейткипер границ попапа
    if px <= mx <= px + pw and py - ph <= my <= py:
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
               
            if active_popup == 'ADD_CHANNEL':
                if OCTAVIA_OT_ui_handler._hovered_mesh_name:
                    OCTAVIA_OT_ui_handler._selected_mesh_name = OCTAVIA_OT_ui_handler._hovered_mesh_name
                    OCTAVIA_OT_ui_handler._active_popup = 'PRESETS'
                    OCTAVIA_OT_ui_handler._active_tab = 'ORBITS'
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}
                   
            elif active_popup == 'PRESETS':
                if getattr(OCTAVIA_OT_ui_handler, '_back_btn_hovered', False):
                    OCTAVIA_OT_ui_handler._active_popup = 'ADD_CHANNEL'
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}
                   
                if py - 75 <= my <= py - 53:
                    tab_w = (pw - 20) // 3
                    if px + 10 <= mx <= px + 10 + tab_w:
                        OCTAVIA_OT_ui_handler._active_tab = 'ORBITS'
                    elif px + 10 + tab_w <= mx <= px + 10 + (tab_w * 2):
                        OCTAVIA_OT_ui_handler._active_tab = 'GEONODES'
                    elif px + 10 + (tab_w * 2) <= mx <= px + pw - 10:
                        OCTAVIA_OT_ui_handler._active_tab = 'SHADERS'
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}
                   
                hovered_idx = getattr(OCTAVIA_OT_ui_handler, '_hovered_preset_idx', -1)
                if hovered_idx != -1:
                    from octavia.interface.ghosts import get_preset_id_by_idx
                    from octavia.nodes import apply_channel_preset
                    active_tab = OCTAVIA_OT_ui_handler._active_tab
                    chosen_preset_id = get_preset_id_by_idx(active_tab, hovered_idx)
                   
                    target_obj_name = OCTAVIA_OT_ui_handler._selected_mesh_name
                    target_obj = context.scene.objects.get(target_obj_name) if target_obj_name else None
                    ch_idx = context.scene.octavia_active_channel

                    # 🎯 ЕДИНАЯ ТОЧКА ВХОДА: вся логика загрузки/привязки пресета живёт
                    # в octavia.nodes.apply_channel_preset (граф, орбита, констрейнт,
                    # перенос action, ребайнд Object Info). Обработчик кликов лишь
                    # переключает UI и репортит ошибку.
                    ok, msg = apply_channel_preset(context, target_obj, ch_idx, active_tab, chosen_preset_id)
                    if not ok:
                        print(f"❌ [Octavia Bridge] {msg}")
                        try:
                            self.report({'ERROR'}, f"Octavia: {msg}")
                        except Exception:
                            pass
                   
                    for o in context.scene.objects: o.select_set(False)
                    for o_name in getattr(OCTAVIA_OT_ui_handler, '_original_selection', []):
                        o = context.scene.objects.get(o_name)
                        if o: o.select_set(True)
                       
                    bpy.ops.octavia.rescan_macros()
                       
                    OCTAVIA_OT_ui_handler._active_popup = 'CHANNEL_SETTINGS'
                    OCTAVIA_OT_ui_handler._selected_channel_idx = context.scene.octavia_active_channel
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}

            elif active_popup == 'CHANNEL_SETTINGS':
                ch_idx = getattr(OCTAVIA_OT_ui_handler, '_selected_channel_idx', 1)
                
                # 🩺 САМОЛЕЧЕНИЕ КОНТЕКСТА: Защита кликов мыши в старых файлах
                while len(context.scene.octavia_channels_data) < ch_idx:
                    context.scene.octavia_channels_data.add()
                ch_data = context.scene.octavia_channels_data[ch_idx - 1]
                if len(ch_data.voices) == 0:
                    v_def = ch_data.voices.add()
                    v_def.name = "ГОЛОС 1"
                    v_def.key_code = "K"
                    v_def.hardware_id = 0
                    v_def.punch = 0.5
                    v_def.hold = 0.5
                    v_def.echo = 0.5

                # 🌌 ЗЕРКАЛЬНЫЙ ТРАНСПОРТ КООРДИНАТ (ИДЕНТИЧНО ИНТЕРФЕЙСУ)
                curr_y = py - 22
                curr_y -= 14
                curr_y -= 8
                
                # 1. Проверяем ЛКМ-клики по сетке Голосов (снайперский детектор крестика удаления)
                curr_y -= 22
                tx = px + 10
                for idx, voice in enumerate(ch_data.voices):
                    if tx + 64 > px + pw - 15:
                        tx = px + 10
                        curr_y -= 22
                    
                    if tx <= mx <= tx + 64 and curr_y <= my <= curr_y + 18:
                        # ✕ ДЕТЕКТОР КРЕСТИКА: если кликнули в правые 14 пикселей активного таба
                        if idx == ch_data.active_voice_idx and len(ch_data.voices) > 1 and (tx + 50 <= mx <= tx + 64):
                            bpy.ops.octavia.delete_voice(channel_idx=ch_idx, voice_idx=idx)
                            area.tag_redraw()
                            return {'RUNNING_MODAL'}
                        
                        ch_data.active_voice_idx = idx
                        area.tag_redraw()
                        return {'RUNNING_MODAL'}
                    tx += 68
                    
                # 2. Проверяем клик по кнопке добавления голоса [+] (МЕНЕДЖЕР ПУЛА СЛОТОВ)
                if tx + 64 > px + pw - 15:
                    tx = px + 10
                    curr_y -= 22
                if tx <= mx <= tx + 64 and curr_y <= my <= curr_y + 18:
                    v_idx = len(ch_data.voices)
                    
                    # 🔥 УЛЬТРАКОМПАКТНЫЙ ПУЛ: Ищем первый свободный hardware_id в диапазоне 0-31
                    used_hw_ids = {v.hardware_id for v in ch_data.voices}
                    free_hw_ids = set(range(32)) - used_hw_ids
                    next_hardware_id = min(free_hw_ids) if free_hw_ids else v_idx
                    
                    v_prev = ch_data.voices[ch_data.active_voice_idx] if len(ch_data.voices) > 0 else None
                    
                    v_new = ch_data.voices.add()
                    v_new.name = f"ГОЛОС {v_idx + 1}"
                    v_new.key_code = ""
                    v_new.hardware_id = next_hardware_id # Запекаем свободный аппаратный слот
                    
                    if v_prev:
                        v_new.punch = v_prev.punch
                        v_new.hold = v_prev.hold
                        v_new.echo = v_prev.echo
                    
                    OCTAVIA_OT_ui_handler._waiting_for_voice_key = True
                    OCTAVIA_OT_ui_handler._binding_voice_idx = v_idx
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}
                    
                curr_y -= 10
                
                # 3. Клик по тумблеру Neon Preview
                curr_y -= 20
                if curr_y <= my <= curr_y + 16 and px + 10 <= mx <= px + pw - 10:
                    ghost_active = getattr(OCTAVIA_OT_ui_handler, '_preview_ghost_active', True)
                    OCTAVIA_OT_ui_handler._preview_ghost_active = not ghost_active
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}
                   
                all_macros = list(context.scene.octavia_active_macros)
                global_macros = [m for m in all_macros if m.category == 'GLOBAL']
                hold_macros = [m for m in all_macros if m.category == 'HOLD']
                echo_macros = [m for m in all_macros if m.category == 'ECHO']
                active_voice = ch_data.voices[ch_data.active_voice_idx]
               
                # Сектор 1: HOLD KNOBS CLICKS
                curr_y -= 22
                if hold_macros:
                    for m in hold_macros:
                        curr_y -= 28
                        if curr_y <= my <= curr_y + 24 and px + 15 <= mx <= px + pw - 15:
                            self._is_dragging_macro = True
                            self._drag_macro_name = m.node_name
                            self._last_macro_mx = mx
                            
                            # Кастомные макросы всегда через ui_value → oc_m_<node>.
                            # Не маппить по словам в имени на voice.punch/hold/echo —
                            # иначе «Скорость возврата» писала в echo, а граф читал 0.
                            val_range = m.max_value - m.min_value
                            pct = (mx - (px + 15)) / (pw - 30)
                            m.ui_value = m.min_value + (max(0.0, min(1.0, pct)) * val_range)
                            area.tag_redraw()
                            return {'RUNNING_MODAL'}
                           
                # Сектор 2: ECHO KNOBS CLICKS
                curr_y -= 22
                if echo_macros:
                    for m in echo_macros:
                        curr_y -= 28
                        if curr_y <= my <= curr_y + 24 and px + 15 <= mx <= px + pw - 15:
                            self._is_dragging_macro = True
                            self._drag_macro_name = m.node_name
                            self._last_macro_mx = mx
                            
                            val_range = m.max_value - m.min_value
                            pct = (mx - (px + 15)) / (pw - 30)
                            m.ui_value = m.min_value + (max(0.0, min(1.0, pct)) * val_range)
                            area.tag_redraw()
                            return {'RUNNING_MODAL'}
                           
                # Сектор 3: GLOBAL KNOBS CLICKS
                curr_y -= 22
                if global_macros:
                    for m in global_macros:
                        curr_y -= 28
                        if curr_y <= my <= curr_y + 24 and px + 15 <= mx <= px + pw - 15:
                            self._is_dragging_macro = True
                            self._drag_macro_name = m.node_name
                            self._last_macro_mx = mx
                            val_range = m.max_value - m.min_value
                            pct = (mx - (px + 15)) / (pw - 30)
                            m.ui_value = m.min_value + (max(0.0, min(1.0, pct)) * val_range)
                            area.tag_redraw()
                            return {'RUNNING_MODAL'}

            # 🛡️ ФИНАЛЬНЫЙ ПЕРЕХВАТ ПУСТОГО МЕСТА ДЛЯ ВСЕХ ОКЕН (Уровень отступа ЛКМ-пресса)
            # Если клик был внутри границ попапа, но ни один блок выше не выдал ранний ретурн —
            # значит, юзер попал по чистому фону. Включаем свободный драг!
            self._is_dragging_popup = True
            self._popup_drag_start_mx = mx
            self._popup_drag_start_my = my
            self._popup_drag_start_px = px
            self._popup_drag_start_py = py
            return {'RUNNING_MODAL'}
        
    # Клик мимо попапа (Закрытие)
    else:
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            OCTAVIA_OT_ui_handler._active_popup = None
            for o in context.scene.objects: o.select_set(False)
            for o_name in getattr(OCTAVIA_OT_ui_handler, '_original_selection', []):
                o = context.scene.objects.get(o_name)
                if o: o.select_set(True)
            area.tag_redraw()
            return {'RUNNING_MODAL'}
           
    return None