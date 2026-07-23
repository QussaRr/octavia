import bpy
from ..vj_core import frame_to_time, time_to_frame
from .navigation import handle_timer, handle_zoom, handle_scroll
from .radar import handle_mousemove, check_cursor_boundaries
from .actions import handle_actions

class OCTAVIA_OT_daw_zoom(bpy.types.Operator):
    bl_idname = "octavia.daw_zoom"
    bl_label = "Octavia DAW Zoom"
    direction: bpy.props.EnumProperty(items=[('IN', "In", ""), ('OUT', "Out", "")])
    def execute(self, context): return {'FINISHED'}

class OCTAVIA_OT_ui_handler(bpy.types.Operator):
    bl_idname = "octavia.ui_handler"
    bl_label = "Octavia UI Modal Handler"
    _running = False
    _defining_loop = False

    @classmethod
    def poll(cls, context):
        return context.workspace and context.workspace.name == "Octavia DAW"

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        OCTAVIA_OT_ui_handler._running = True
        OCTAVIA_OT_ui_handler._defining_loop = False
        
        # Инициализация бессмертных стеков истории Октавии
        import sys
        if not hasattr(sys, "_octavia_undo_stack"):
            sys._octavia_undo_stack = []
        if not hasattr(sys, "_octavia_redo_stack"):
            sys._octavia_redo_stack = []
        
        # 🔥 КЛАССНЫЕ ПЕРЕМЕННЫЕ ПОПАПА (СТАТИЧЕСКИЙ ГЛОБАЛЬНЫЙ КЭШ)
        OCTAVIA_OT_ui_handler._active_popup = None 
        OCTAVIA_OT_ui_handler._hovered_mesh_name = None
        OCTAVIA_OT_ui_handler._waiting_for_voice_key = False
        OCTAVIA_OT_ui_handler._binding_voice_idx = 0
        OCTAVIA_OT_ui_handler._selected_mesh_name = None # None, 'ADD_CHANNEL', 'PRESETS'
        OCTAVIA_OT_ui_handler._active_tab = 'ORBITS' # Могут быть: 'ORBITS', 'GEONODES', 'SHADERS'
        OCTAVIA_OT_ui_handler._popup_x = 0          
        OCTAVIA_OT_ui_handler._popup_y = 0          
        OCTAVIA_OT_ui_handler._popup_w = 260        # Чуть расширим под списки объектов
        OCTAVIA_OT_ui_handler._popup_h = 300        
        
        # Свойства перетаскивания (Drag)
        self._is_dragging = False
        self._drag_ch = -1
        self._drag_voice = -1
        self._drag_start_frame = -1.0
        self._drag_start_mx = 0
        
        # Свойства скраббинга и панорамирования
        self._is_scrubbing = False
        self._is_panning = False
        self._pan_start_mx = 0
        self._pan_start_scroll = 0.0
        
        # Флаги режима изменения длины (Resize Edge)
        self._is_resizing = False
        self._resize_start_frame = -1.0
        self._resize_start_mx = 0

        # Статические стены для борьбы с коллизиями блоков
        self._collision_left_wall = 1.0
        self._collision_right_wall = 100000.0
        
        # Квантовые лимиты хода для массового перемещения (Bulk Drag)
        self._pack_min_delta = -100000.0
        self._pack_max_delta = 100000.0
  
        # Переменные массового бокс-СЕЛЕКТА
        self._is_box_selecting = False
        self._box_start_mx = 0
        self._box_start_my = 0
        self._selection_snapshot = set()
        
        # Системные трекеры Блендера
        self._was_outside = False  
        self._last_frame = -1  
        self._timer = context.window_manager.event_timer_add(1.0 / 60.0, window=context.window)
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        
        self._shift_held = event.shift

        # Железный гейткипер автономного леджера Октавии
        if event.type == 'Z' and event.ctrl and event.value == 'PRESS':
            from ..vj_core import execute_octavia_undo, execute_octavia_redo
            area = next((a for a in context.screen.areas if a.type == 'CLIP_EDITOR'), None)
            if event.shift:
                execute_octavia_redo(context)
            else:
                execute_octavia_undo(context)
            if area:
                area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Предохранитель выхода из рабочей области DAW
        if not context.workspace or context.workspace.name != "Octavia DAW":
            if hasattr(self, "_timer") and self._timer:
                context.window_manager.event_timer_remove(self._timer)
            OCTAVIA_OT_ui_handler._running = False
            OCTAVIA_OT_ui_handler._defining_loop = False
            return {'FINISHED'}
            
        area = next((a for a in context.screen.areas if a.type == 'CLIP_EDITOR'), None)
        if not area:
            return {'PASS_THROUGH'}

        # 🔥 БРОНИРОВАННЫЙ ХВАТ РЕГИОНА: Извлекаем стабильное окно WINDOW напрямую из CLIP_EDITOR
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if not region:
            return {'PASS_THROUGH'} # Если регион на долю секунды пропал — мягко уходим на следующий кадр

        # Точнейшие координаты мыши относительно нижнего левого угла холста рисования
        mx = event.mouse_x - region.x
        my = event.mouse_y - region.y

        # 🛡️ ОБНОВЛЕННЫЙ ЩИТ КВАНТОВОГО БИНДА КЛАВИШ ОКТАВИИ (ФИЛЬТР МЫШИ + АВТО-КЛИНАП МУСОРА)
        if getattr(OCTAVIA_OT_ui_handler, '_waiting_for_voice_key', False):
            if event.value == 'PRESS':
                # Сценарий 1: Продюсер нажал ESC — отменяем операцию
                if event.type == 'ESC':
                    OCTAVIA_OT_ui_handler._waiting_for_voice_key = False
                    ch_idx = context.scene.octavia_active_channel
                    if len(context.scene.octavia_channels_data) >= ch_idx:
                        ch_data = context.scene.octavia_channels_data[ch_idx - 1]
                        v_idx = getattr(OCTAVIA_OT_ui_handler, '_binding_voice_idx', 0)
                        if len(ch_data.voices) > v_idx:
                            ch_data.voices.remove(len(ch_data.voices) - 1)
                            ch_data.active_voice_idx = max(0, v_idx - 1)
                    if area: area.tag_redraw()
                    return {'RUNNING_MODAL'}
                
                # Сценарий 2: Защита от случайных кликов мыши
                if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                    px = OCTAVIA_OT_ui_handler._popup_x
                    py = OCTAVIA_OT_ui_handler._popup_y
                    pw = OCTAVIA_OT_ui_handler._popup_w
                    ph = OCTAVIA_OT_ui_handler._popup_h
                    
                    # Если кликнули МИМО окна попапа — это жест отмены! Сносим пустой голос
                    if not (px <= mx <= px + pw and py - ph <= my <= py):
                        OCTAVIA_OT_ui_handler._waiting_for_voice_key = False
                        ch_idx = context.scene.octavia_active_channel
                        if len(context.scene.octavia_channels_data) >= ch_idx:
                            ch_data = context.scene.octavia_channels_data[ch_idx - 1]
                            v_idx = getattr(OCTAVIA_OT_ui_handler, '_binding_voice_idx', 0)
                            if len(ch_data.voices) > v_idx:
                                ch_data.voices.remove(len(ch_data.voices) - 1)
                                ch_data.active_voice_idx = max(0, v_idx - 1)
                        if area: area.tag_redraw()
                    return {'RUNNING_MODAL'} # Сжираем клики внутри окна, не давая привязать LEFTMOUSE к нотам
                
                # Пропускаем служебный мусор движения курсора
                if event.type in {'MOUSEMOVE', 'TIMER', 'INBETWEEN_MOUSEMOVE'}:
                    return {'RUNNING_MODAL'}
                
                # Сценарий 3: Поймана настоящая музыкальная клавиша клавиатуры!
                ch_idx = context.scene.octavia_active_channel
                if len(context.scene.octavia_channels_data) >= ch_idx:
                    ch_data = context.scene.octavia_channels_data[ch_idx - 1]
                    v_idx = getattr(OCTAVIA_OT_ui_handler, '_binding_voice_idx', 0)
                    if len(ch_data.voices) > v_idx:
                        ch_data.voices[v_idx].key_code = event.type
                        ch_data.voices[v_idx].name = f"ГОЛОС {v_idx + 1} [{event.type}]"
                        ch_data.active_voice_idx = v_idx # Автоматически переносим фокус интерфейса на него
                
                OCTAVIA_OT_ui_handler._waiting_for_voice_key = False
                if area: area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}
        
        # Щит активного попапа: Перехват кликов мимо окна
        if OCTAVIA_OT_ui_handler._active_popup:
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'} and event.value == 'PRESS':
                px = OCTAVIA_OT_ui_handler._popup_x
                py = OCTAVIA_OT_ui_handler._popup_y
                pw = OCTAVIA_OT_ui_handler._popup_w
                ph = OCTAVIA_OT_ui_handler._popup_h
                
                if OCTAVIA_OT_ui_handler._active_popup == 'CHANNEL_SETTINGS':
                    ph = 440
                    
                if not (px <= mx <= px + pw and py - ph <= my <= py):
                    for o in context.scene.objects: o.select_set(False)
                    for o_name in getattr(OCTAVIA_OT_ui_handler, '_original_selection', []):
                        o = context.scene.objects.get(o_name)
                        if o: o.select_set(True)
                    orig_act = getattr(OCTAVIA_OT_ui_handler, '_original_active', None)
                    if orig_act and orig_act in context.scene.objects:
                        context.view_layer.objects.active = context.scene.objects[orig_act]
                    OCTAVIA_OT_ui_handler._active_popup = None
                    for a in context.screen.areas:
                        if a.type in {'CLIP_EDITOR', 'VIEW_3D'}: a.tag_redraw()
                    return {'RUNNING_MODAL'}

        # Проверка и моментальный сброс курсорных стрелок ресайза
        check_cursor_boundaries(self, context, event, mx, my, area)

        # Во время жестов не отдаём события наружу — иначе Blender срывает ПКМ-луп
        if not getattr(self, "_is_dragging", False) and not getattr(self, "_is_scrubbing", False) and not getattr(self, "_is_panning", False) and not getattr(self, "_is_resizing", False) and not getattr(self, "_is_box_selecting", False) and not getattr(self, "_is_defining_loop", False) and not getattr(self, "_is_erasing", False) and not OCTAVIA_OT_ui_handler._active_popup:
            if event.type != 'TIMER':
                if not (0 <= mx <= region.width and 0 <= my <= region.height):
                    return {'PASS_THROUGH'}

        scene = context.scene
        fps = scene.render.fps if scene.render.fps > 0 else 24
        pixels_per_second = 50 * scene.octavia_zoom
        
        # Вычисляем scroll_px на основе текущего скролла сцены, как это сделано в интерфейсе
        scroll_px = (scene.octavia_scroll / fps) * pixels_per_second

        # Данные берутся из гарантированно существующего region
        layout = {
          'mx': mx, 'my': my,
          'win_w': region.width, 
          'win_h': region.height,
          'fps': fps, 'pixels_per_second': pixels_per_second,
          'scroll_px': scroll_px,  # <--- ВОТ ЭТА СУКА ТУТ ДОЛЖНА БЫТЬ!
          'left_margin': 15, 'right_margin': 15, 'header_w': 160, 'gap': 8,
          'channel_h': 30, 'channel_gap': 8,
          'region': region,
          'area': area,
        }
        layout['track_x'] = layout['left_margin'] + layout['header_w'] + layout['gap']
        layout['track_y'] = layout['win_h'] - 85
        layout['visible_workspace_w'] = layout['win_w'] - layout['track_x'] - layout['right_margin']
        layout['visible_frames'] = (layout['visible_workspace_w'] / pixels_per_second) * fps

        if event.type == 'TIMER':
            return handle_timer(self, context, event, layout, area)
            
        if event.ctrl and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if OCTAVIA_OT_ui_handler._active_popup: return {'RUNNING_MODAL'}
            return handle_zoom(self, context, event, layout, area)
            
        if event.shift and event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if OCTAVIA_OT_ui_handler._active_popup: return {'RUNNING_MODAL'}
            return handle_scroll(self, context, event, layout, area)
            
        if event.type == 'MOUSEMOVE':
            return handle_mousemove(self, context, event, layout, area)
            
        if event.value in {'PRESS', 'RELEASE'}:
            return handle_actions(self, context, event, layout, area)

        return {'PASS_THROUGH'}