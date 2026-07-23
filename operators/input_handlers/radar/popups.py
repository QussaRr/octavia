import bpy
import os

def handle_popup_and_macros(self, context, mx, my, area):
    from octavia.operators.input_handlers.operator import OCTAVIA_OT_ui_handler
    scene = context.scene
    
    # 🔥 ОБСЛУЖИВАНИЕ ДИНАМИЧЕСКОГО ПЕРЕМЕЩЕНИЯ ОКНА
    if getattr(self, "_is_dragging_popup", False):
        delta_x = mx - self._popup_drag_start_mx
        delta_y = my - self._popup_drag_start_my
        OCTAVIA_OT_ui_handler._popup_x = self._popup_drag_start_px + delta_x
        OCTAVIA_OT_ui_handler._popup_y = self._popup_drag_start_py + delta_y
        area.tag_redraw()
        return True
        
    active_popup = getattr(OCTAVIA_OT_ui_handler, '_active_popup', None)
    
    px = OCTAVIA_OT_ui_handler._popup_x
    py = OCTAVIA_OT_ui_handler._popup_y
    pw = OCTAVIA_OT_ui_handler._popup_w
    ph = OCTAVIA_OT_ui_handler._popup_h
    
    if active_popup == 'CHANNEL_SETTINGS':
        ph = 440

    # 1. АВТОМАТИЗАЦИЯ HUD МАКРО-РУЧЕК ПРИ ЗАЖАТОЙ МЫШИ (МНОГОГОЛОСАЯ ИЗОЛЯЦИЯ)
    if getattr(self, "_is_dragging_macro", False):
        macro_name = getattr(self, "_drag_macro_name", "")
        m = next((x for x in scene.octavia_active_macros if x.node_name == macro_name), None)
        if m:
            ch_idx = scene.octavia_active_channel
            ch_data = scene.octavia_channels_data[ch_idx - 1] if len(scene.octavia_channels_data) >= ch_idx else None
            active_voice = ch_data.voices[ch_data.active_voice_idx] if (ch_data and len(ch_data.voices) > ch_data.active_voice_idx) else None
            
            # Кастомные макросы → ui_value → oc_m_<node> (не voice.echo/punch/hold)
            current_value = m.ui_value
            val_range = m.max_value - m.min_value
            
            if getattr(self, "_shift_held", False):
                # Режим микро-тюнинга при зажатом Shift
                prev_mx = getattr(self, "_last_macro_mx", mx)
                delta_px = mx - prev_mx
                pct_delta = (delta_px / (pw - 30)) / 5.0
                new_val = current_value + pct_delta * val_range
            else:
                # Стандартный режим абсолютной привязки ЛКМ-курсора
                pct = (mx - (px + 15)) / (pw - 30)
                new_val = m.min_value + (max(0.0, min(1.0, pct)) * val_range)
                
            # Зажимаем значение в рамки авторских лимитов графа
            new_val = max(m.min_value, min(m.max_value, new_val))
            m.ui_value = new_val
                
            self._last_macro_mx = mx
            
        area.tag_redraw()
        return True

    # 2. СКАНИРОВАНИЕ ХОВЕРОВ ВНУТРИ АКТИВНОГО ПОПАПА
    if active_popup in {'ADD_CHANNEL', 'PRESETS', 'CHANNEL_SETTINGS'}:
        scene.octavia_hovered_ch = 0
        scene.octavia_hovered_part = "NONE"
        scene["octavia_hovered_block_ch"] = -1
        
        if active_popup == 'ADD_CHANNEL':
            meshes = [
                o for o in context.scene.objects
                if o.type == 'MESH'
                and not o.data.get("is_octavia_buffer", 0)
                and not (o.data and "octavia_voice_id" in o.data.attributes)
            ]
            old_hover = getattr(OCTAVIA_OT_ui_handler, '_hovered_mesh_name', None)
            OCTAVIA_OT_ui_handler._hovered_mesh_name = None
            
            list_top_y = py - 40
            if px <= mx <= px + pw and my <= list_top_y:
                row_idx = int((list_top_y - my) // 22)
                if 0 <= row_idx < len(meshes):
                    OCTAVIA_OT_ui_handler._hovered_mesh_name = meshes[row_idx].name
                    
            if OCTAVIA_OT_ui_handler._hovered_mesh_name != old_hover:
                for o in meshes: o.select_set(False)
                if OCTAVIA_OT_ui_handler._hovered_mesh_name:
                    target_obj = context.scene.objects.get(OCTAVIA_OT_ui_handler._hovered_mesh_name)
                    if target_obj: target_obj.select_set(True)
                else:
                    for o_name in getattr(OCTAVIA_OT_ui_handler, '_original_selection', []):
                        o = context.scene.objects.get(o_name)
                        if o: o.select_set(True)
                for a in context.screen.areas:
                    if a.type == 'VIEW_3D': a.tag_redraw()
                
        elif active_popup == 'PRESETS':
            OCTAVIA_OT_ui_handler._back_btn_hovered = (px + 10 <= mx <= px + pw - 10 and py - 46 <= my <= py - 26)
            
            from octavia.interface.ghosts import get_preset_labels
            active_tab = getattr(OCTAVIA_OT_ui_handler, '_active_tab', 'ORBITS')
            current_items = get_preset_labels(active_tab)
            
            OCTAVIA_OT_ui_handler._hovered_preset_idx = -1
            list_top_y = py - 110
            if px <= mx <= px + pw and my <= list_top_y:
                row_idx = int((list_top_y - my) // 22)
                if 0 <= row_idx < len(current_items):
                    OCTAVIA_OT_ui_handler._hovered_preset_idx = row_idx
                    
        elif active_popup == 'CHANNEL_SETTINGS':
            pass
                    
        area.tag_redraw()
        return True

    return False