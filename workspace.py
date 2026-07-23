import bpy
import sys
from bpy.app.handlers import persistent

# 📸 СИСТЕМНОЕ ХРАНИЛИЩЕ ПЕСОЧНИЦЫ ОКТАВИИ (SURVIVES F3 RELOADS)
if not hasattr(sys, "_octavia_system_backup"):
    sys._octavia_system_backup = {}
if not hasattr(sys, "_octavia_was_active"):
    sys._octavia_was_active = False


def on_enter_octavia(context):
    """Триггер Входа: срабатывает ровно один раз при переключении на воркспейс DAW"""
    scene = context.scene
    prefs = context.preferences.system
    
    # Делаем снимок настроек ТОЛЬКО если буфер пуст (защита от перезатирания при релоадах)
    if not sys._octavia_system_backup:
        sys._octavia_system_backup['fps'] = scene.render.fps
        sys._octavia_system_backup['sync_mode'] = scene.sync_mode
        sys._octavia_system_backup['mixing_buffer'] = prefs.audio_mixing_buffer
        sys._octavia_system_backup['sample_rate'] = prefs.audio_sample_rate
    
    # 🔥 АКТИВИРУЕМ СВЕРХЗВУКОВОЙ АУДИО-БУСТ (ОДИН РАЗ!)
    scene.render.fps = 60
    scene.sync_mode = 'FRAME_DROP'
    if prefs.audio_mixing_buffer != 'SAMPLES_512':
        prefs.audio_mixing_buffer = 'SAMPLES_512'
    if prefs.audio_sample_rate != 'RATE_44100':
        prefs.audio_sample_rate = 'RATE_44100'


def on_leave_octavia(context):
    """Триггер Выхода: возвращает Блендер в исходное состояние без следов аддона"""
    if sys._octavia_system_backup:
        scene = context.scene
        prefs = context.preferences.system
        
        # Возвращаем родные лимиты и частоты продюсера
        scene.render.fps = sys._octavia_system_backup.get('fps', 24)
        scene.sync_mode = sys._octavia_system_backup.get('sync_mode', 'NONE')
        
        # Защита от сбоя, если преференции заблокированы операционной системой
        try:
            prefs.audio_mixing_buffer = sys._octavia_system_backup.get('mixing_buffer', 'SAMPLES_2048')
            prefs.audio_sample_rate = sys._octavia_system_backup.get('sample_rate', 'RATE_44100')
        except Exception as e:
            print(f"[Octavia Warning] Не удалось вернуть аудио-буфер преференций: {e}")
            
        sys._octavia_system_backup.clear()


def octavia_workspace_policer():
    
    """Фоновый полицейский планировки: легкий и стерильный"""
    context = bpy.context
    if not context or not hasattr(context, "workspace") or not context.workspace:
        return 0.1
        
    # БЕЗОПАСНЫЙ ФИКС ТАЙМЛАЙНА
    if hasattr(context, "screen") and context.screen:
        for area in context.screen.areas:
            if area.type in {'DOPESHEET_EDITOR', 'TIMELINE'}:
                for space in area.spaces:
                    if hasattr(space, "show_only_selected"):
                        space.show_only_selected = False

    # Машина состояний жизненного цикла Октавии
    ws_name = context.workspace.name
    is_now_in_octavia = (ws_name == "Octavia DAW")
    
    if is_now_in_octavia and not sys._octavia_was_active:
        # Бах! Поймали переход границы воркспейса внутрь
        on_enter_octavia(context)
        sys._octavia_was_active = True
        
    elif not is_now_in_octavia and sys._octavia_was_active:
        # Бах! Поймали выход из Октавии наружу
        on_leave_octavia(context)
        sys._octavia_was_active = False

    # Отрисовка рабочей области DAW (выполняется только внутри Октавии)
    if is_now_in_octavia and hasattr(context, "screen") and context.screen:
        for area in context.screen.areas:
            if area.type in {'TIMELINE', 'DOPESHEET_EDITOR'}:
                area.type = 'CLIP_EDITOR'
                for space in area.spaces:
                    if space.type == 'CLIP_EDITOR':
                        space.show_region_header = False
                        space.show_region_toolbar = False
                        space.show_region_ui = False
                area.tag_redraw()
                break
        
        try:
            from .operators.input_handlers import OCTAVIA_OT_ui_handler
            if not OCTAVIA_OT_ui_handler._running:
                bpy.ops.octavia.ui_handler('INVOKE_DEFAULT')
        except Exception:
            pass
            
    return 0.1

@persistent
def octavia_global_frame_handler(scene, *args):
    """ Бессмертный инжектор: транслирует автоматизацию ручек всех каналов в C++ меш-буферы и крутит орбиты кривых """
    fps = scene.render.fps if scene.render.fps > 0 else 24
    bpm = getattr(scene, "octavia_bpm", 120)
    
    # ─── ЧАСТЬ А: ТОТАЛЬНЫЙ СТРИМИНГ МАКРОСОВ ДЛЯ ВСЕХ КАНАЛОВ В СЦЕНЕ ───
    if hasattr(scene, "octavia_channels_data"):
        for ch_idx, ch_data in enumerate(scene.octavia_channels_data, start=1):
            buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            
            if buf_obj and buf_obj.data:
                # 🩺 САМОИСЦЕЛЕНИЕ ВИДИМОСТИ: hide_viewport выкидывает буфер из depsgraph,
                # и граф (Object Info) читает пустую геометрию. Держим буфер вычисляемым
                # (hide_viewport=False), но прячем «глазом» — тогда во вьюпорте нет точек.
                if buf_obj.hide_viewport:
                    buf_obj.hide_viewport = False
                try:
                    if not buf_obj.hide_get():
                        buf_obj.hide_set(True)
                except Exception:
                    pass

                # 🔗 АВТО-РЕБАЙНД OBJECT INFO + СБОР ДЕФОЛТОВ МАКРОСОВ.
                # Object Info: граф канала обязан читать СВОЙ буфер
                # (Octavia_Buffer_Ch_{ch_idx}). Указатель рвётся при импорте пресета
                # (обнуляется) и при удалении/перенумерации каналов (смотрит на чужой/
                # удалённый буфер). Чиним, если цель пуста ИЛИ это буфер Октавии с чужим
                # индексом. Не-буферные Object Info (орбиты и т.п.) НЕ трогаем.
                # Заодно собираем дефолты нод-макросов графа: если у голоса нет явного
                # оверрайда, в буфер должен литься дефолт ноды — то же значение, что
                # показывает ползунок в попапе (фолбэк get_ui_value). Иначе UI показывает
                # N, а буфер держит 0, и объект не движется (классический баг после
                # пересоздания канала: нода помнит дефолт, а оверрайда уже нет).
                macro_defaults = {}
                for graph_obj in scene.objects:
                    gmod = graph_obj.modifiers.get(f"Octavia Channel {ch_idx}")
                    if gmod and gmod.node_group:
                        for node in gmod.node_group.nodes:
                            if node.bl_idname == 'GeometryNodeObjectInfo' and node.inputs:
                                tgt = node.inputs[0].default_value
                                tgt_name = getattr(tgt, "name", "") if tgt else ""
                                wrong_buffer = tgt_name.startswith("Octavia_Buffer_Ch_") and tgt_name != buf_name
                                if tgt is None or wrong_buffer:
                                    node.inputs[0].default_value = buf_obj
                            elif node.bl_idname == 'ShaderNodeValue':
                                macro = getattr(node, "octavia_macro", None)
                                if macro and getattr(macro, "is_macro", False):
                                    try:
                                        macro_defaults[node.name] = node.outputs[0].default_value
                                    except Exception:
                                        pass

                mesh = buf_obj.data
                punch_attr = mesh.attributes.get("octavia_macro_punch")
                hold_attr = mesh.attributes.get("octavia_macro_hold")
                echo_attr = mesh.attributes.get("octavia_macro_echo")
                
                # Потоковый инжекционный конвейер параметров каждого голоса
                for voice in ch_data.voices:
                    vert_idx = 128 + voice.hardware_id
                    if vert_idx >= len(mesh.vertices):
                        continue
                        
                    # 1. Стриминг стандартных системных параметров
                    if punch_attr: punch_attr.data[vert_idx].value = voice.punch
                    if hold_attr: hold_attr.data[vert_idx].value = voice.hold
                    if echo_attr: echo_attr.data[vert_idx].value = voice.echo
                    
                    # 2. 🪐 ЭФФЕКТИВНОЕ ЗНАЧЕНИЕ МАКРОСА: оверрайд голоса, иначе дефолт
                    # ноды графа. Так буфер всегда совпадает с ползунком — даже сразу
                    # после применения пресета, без ручного «покрути ручку».
                    voice_overrides = {o.macro_id: o.value for o in voice.macro_overrides}
                    for node_name, default_val in macro_defaults.items():
                        attr = mesh.attributes.get(f"oc_m_{node_name}")
                        if attr and vert_idx < len(attr.data):
                            attr.data[vert_idx].value = voice_overrides.get(node_name, default_val)
                    
                    # Легаси-подстраховка: оверрайды без соответствующей ноды-макроса
                    # (например после ручного удаления макроса из графа) всё равно льём.
                    for mid, val in voice_overrides.items():
                        if mid not in macro_defaults:
                            attr = mesh.attributes.get(f"oc_m_{mid}")
                            if attr and vert_idx < len(attr.data):
                                attr.data[vert_idx].value = val
               
                # Передаем обновленный массив вершин напрямую в Geometry Nodes
                mesh.update()
                buf_obj.update_tag()

    # ─── ЧАСТЬ Б: МАТЕМАТИЧЕСКАЯ СИНХРОНИЗАЦИЯ КРИВЫХ ТРАЕКТОРИЙ ОКТАВИИ ───
    frames_per_bar = (240.0 * fps) / bpm
    if frames_per_bar <= 0: return
    
    custom_speed = 1.0
    for obj in scene.objects:
        if obj.constraints and any(c.name.startswith("Octavia_Follow_") for c in obj.constraints):
            for mod in obj.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    speed_node = mod.node_group.nodes.get("Speed")
                    if speed_node and speed_node.type == 'VALUE':
                        custom_speed = speed_node.outputs[0].default_value
                        break

    current_offset = (((scene.frame_current - 1) * custom_speed) / frames_per_bar) % 1.0
    
    for obj in scene.objects:
        if obj.constraints:
           for con in obj.constraints:
                if con.type == 'FOLLOW_PATH' and con.name.startswith("Octavia_Follow_"):
                    if abs(con.offset_factor - current_offset) > 0.00001:
                        con.offset_factor = current_offset

    # ─── ЧАСТЬ В: ПРИНУДИТЕЛЬНЫЙ КВАНТОВЫЙ ЗАМУРОВАЛЬЩИК ПЛЕЙХЕДА В ВЫДЕЛЕННЫЙ ЛУП ───
    if getattr(scene, "octavia_loop_active", False):
        from .operators.vj_core import quantize_time_to_playhead
        _, loop_start_frame = quantize_time_to_playhead(scene.octavia_loop_start, fps)
        _, loop_end_frame = quantize_time_to_playhead(scene.octavia_loop_end, fps)
        
        # Защита от дурака: если луп выделили нормально (не в одну точку)
        if loop_end_frame > loop_start_frame:
            # Если плейхед перешагнул конец лупа ИЛИ оказался левее начала
            if scene.frame_current > loop_end_frame or scene.frame_current < loop_start_frame:
                # Насильно швыряем плейхед в НАЧАЛО ВЫДЕЛЕННОГО УЧАСТКА, а не в 1-й кадр!
                scene.frame_current = loop_start_frame

@persistent
def on_file_load(dummy1=None, dummy2=None):
    """Вызывается строго ПОСЛЕ загрузки или создания нового проекта"""
    try:
        from .operators.input_handlers import OCTAVIA_OT_ui_handler
        OCTAVIA_OT_ui_handler._running = False

        # 🛡️ ГЕЙТКИПЕР САМОЛЕЧЕНИЯ: Вшиваем паспорт старым буферам, если открыт древний проект
        for mesh in bpy.data.meshes:
            if "is_octavia_buffer" not in mesh:
                if mesh.attributes and "octavia_voice_id" in mesh.attributes:
                    mesh["is_octavia_buffer"] = 1
    except Exception as e:
        print(f"[Octavia Load Error] Ошибка при санации мешей: {e}")

    # 🔥 БРОНЕБОЙНЫЙ СБРОС СТЕКОВ ОКТАВИИ: вычищаем историю, чтобы она не перетекала между треками
    if hasattr(sys, "_octavia_undo_stack"):
        sys._octavia_undo_stack.clear()
    if hasattr(sys, "_octavia_redo_stack"):
        sys._octavia_redo_stack.clear()

    # Принудительно сбрасываем флаги активности для свежего файла
    sys._octavia_was_active = False
    sys._octavia_system_backup.clear()

    try:
        bpy.app.timers.unregister(octavia_workspace_policer)
    except Exception:
        pass
    bpy.app.timers.register(octavia_workspace_policer)


class OCTAVIA_OT_switch_workspace(bpy.types.Operator):
    bl_idname = "octavia.switch_workspace"
    bl_label = "Открыть интерфейс DAW"
    
    def execute(self, context):
        ws = bpy.data.workspaces.get("Octavia DAW")
        if not ws:
            old_workspaces = {w.name for w in bpy.data.workspaces}
            bpy.ops.workspace.duplicate()
            ws = next((w for w in bpy.data.workspaces if w.name not in old_workspaces), None)
            if ws: ws.name = "Octavia DAW"
            
        context.window.workspace = ws
        return {'FINISHED'}


def register():
    bpy.utils.register_class(OCTAVIA_OT_switch_workspace)
    if not bpy.app.timers.is_registered(octavia_workspace_policer):
        bpy.app.timers.register(octavia_workspace_policer)
    if on_file_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(on_file_load)
        
    # 🔥 ИНЪЕКЦИЯ В ЯДРО БЛЕНДЕРА: Вешаем постоянный следильщик за кадрами (СТРОГО ДО ОЦЕНКИ ГРАФА!)
    if octavia_global_frame_handler not in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.append(octavia_global_frame_handler)


def unregister():
    if sys._octavia_was_active:
        ctx = bpy.context
        if ctx and hasattr(ctx, "scene") and ctx.scene:
            scene = ctx.scene
            prefs = ctx.preferences.system
            if sys._octavia_system_backup:
                scene.render.fps = sys._octavia_system_backup.get('fps', 24)
                scene.sync_mode = sys._octavia_system_backup.get('sync_mode', 'NONE')
                try:
                    prefs.audio_mixing_buffer = sys._octavia_system_backup.get('mixing_buffer', 'SAMPLES_2048')
                    prefs.audio_sample_rate = sys._octavia_system_backup.get('sample_rate', 'RATE_44100')
                except Exception:
                    pass
        sys._octavia_was_active = False
        sys._octavia_system_backup.clear()

    bpy.utils.unregister_class(OCTAVIA_OT_switch_workspace)
    if bpy.app.timers.is_registered(octavia_workspace_policer):
        bpy.app.timers.unregister(octavia_workspace_policer)
    if on_file_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(on_file_load)
        
    # Чистим за собой при выгрузке аддона
    if octavia_global_frame_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(octavia_global_frame_handler)