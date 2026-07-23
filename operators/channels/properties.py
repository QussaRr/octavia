import bpy

class OctaviaMacroOverride(bpy.types.PropertyGroup):
    """Индивидуальное переопределение значения макроса для конкретного голоса"""
    macro_id: bpy.props.StringProperty()  # Хранит уникальное имя ноды (node.name)
    value: bpy.props.FloatProperty()

class OctaviaMacroSettings(bpy.types.PropertyGroup):
    """Официальная структура метаданных макроса Октавии внутри ноды Value"""
    is_macro: bpy.props.BoolProperty(
        name="Экспортировать в Октавию",
        description="Включает отображение этой ручки в интерфейсе продюсера",
        default=False
    )
    friendly_name: bpy.props.StringProperty(
        name="Имя ручки",
        description="Понятное музыкальное название для продюсера (например: Резкость Кика)",
        default=""
    )
    category: bpy.props.EnumProperty(
        name="Сектор UI",
        items=[
            ('GLOBAL', "Глобальные настройки (Global)", "Общие системные ручки управления (Speed, Size...)"),
            ('HOLD', "Удержание ноты (Hold / Punch)", "Параметры атаки, скорости и дальности импульса"),
            ('ECHO', "Возврат ноты (Echo / Return)",
             "Хвост после ноты на таймлайне. Одна ручка (макс. >2) = длина в кадрах; "
             "скорость возврата (макс. ≤2) вместе с ручкой HOLD = дистанция/скорость"),
        ],
        default='HOLD'
    )
    min_value: bpy.props.FloatProperty(
        name="Минимум",
        description="Минимальное безопасное значение ползунка",
        default=0.0
    )
    max_value: bpy.props.FloatProperty(
        name="Максимум",
        description="Максимальное безопасное значение ползунка",
        default=1.0
    )
    description: bpy.props.StringProperty(
        name="Описание",
        description="Шпаргалка для продюсера, которая появится при наведении на ручку",
        default=""
    )

class OctaviaExposedMacro(bpy.types.PropertyGroup):
    """Плоский слепок макро-ручки, хранящийся на уровне сцены для мгновенного доступа DAW"""
    node_name: bpy.props.StringProperty()      
    friendly_name: bpy.props.StringProperty()  
    category: bpy.props.StringProperty()      
    min_value: bpy.props.FloatProperty()
    max_value: bpy.props.FloatProperty()
    description: bpy.props.StringProperty()    

    def get_ui_value(self):
        scene = bpy.context.scene
        ch_idx = scene.octavia_active_channel
        
        # 🪐 МАТРИЧНЫЙ ПЕРЕХВАТ: Пытаемся забрать значение из оверрайда АКТИВНОГО голоса
        active_voice = None
        if hasattr(scene, "octavia_channels_data") and len(scene.octavia_channels_data) >= ch_idx:
            ch_data = scene.octavia_channels_data[ch_idx - 1]
            if len(ch_data.voices) > ch_data.active_voice_idx:
                active_voice = ch_data.voices[ch_data.active_voice_idx]
                override = active_voice.macro_overrides.get(self.node_name)
                if override:
                    return override.value

        # ФОЛБЭК 1: значение уже зашито в буфер на вершине голоса (128+hw)
        if active_voice is not None:
            buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data:
                attr = buf_obj.data.attributes.get(f"oc_m_{self.node_name}")
                vert_idx = 128 + int(active_voice.hardware_id)
                if attr and vert_idx < len(attr.data):
                    return float(attr.data[vert_idx].value)

        # ФОЛБЭК 2: дефолт из ноды графа
        obj_name = scene.get("octavia_selected_mesh_name")
        obj = scene.objects.get(obj_name) if obj_name else None
            
        if obj:
            mod = obj.modifiers.get(f"Octavia Channel {ch_idx}")
            if mod and mod.node_group:
                node = mod.node_group.nodes.get(self.node_name)
                if node and node.outputs:
                    return node.outputs[0].default_value
        return 0.0

    def set_ui_value(self, value):
        scene = bpy.context.scene
        ch_idx = scene.octavia_active_channel
        from ..vj_core import clamp_macro_buffer_value
        clamped_val = max(self.min_value, min(self.max_value, value))
        clamped_val = clamp_macro_buffer_value(self.node_name, clamped_val)
        
        # 🪐 МАТРИЧНЫЙ ПОТОК: Записываем значение в оверрайд активного голоса
        ch_data = None
        if hasattr(scene, "octavia_channels_data") and len(scene.octavia_channels_data) >= ch_idx:
            ch_data = scene.octavia_channels_data[ch_idx - 1]
            if len(ch_data.voices) > ch_data.active_voice_idx:
                active_voice = ch_data.voices[ch_data.active_voice_idx]
                override = active_voice.macro_overrides.get(self.node_name)
                if not override:
                    override = active_voice.macro_overrides.add()
                    override.name = self.node_name
                    override.macro_id = self.node_name
                override.value = clamped_val

        # 🔥 ЩИТ ДЕПГРАФА: Синхронизируем ТОЛЬКО на паузе (для мгновенного фидбека автора)
        if not bpy.context.screen.is_animation_playing:
            # 1. Дублируем в физическую ноду графа (ползунок прыгает в Node Editor)
            obj_name = scene.get("octavia_selected_mesh_name")
            obj = scene.objects.get(obj_name) if obj_name else None
                
            if obj:
                mod = obj.modifiers.get(f"Octavia Channel {ch_idx}")
                if mod and mod.node_group:
                    node = mod.node_group.nodes.get(self.node_name)
                    if node and node.outputs:
                        node.outputs[0].default_value = clamped_val
            
            # 2. Мгновенно шьем в кастомный C++ слой меш-буфера под Named Attribute
            if ch_data and len(ch_data.voices) > ch_data.active_voice_idx:
                buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
                buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                if buf_obj and buf_obj.data:
                    mesh = buf_obj.data
                    attr_name = f"oc_m_{self.node_name}"
                    attr = mesh.attributes.get(attr_name)
                    if attr:
                        vert_idx = 128 + active_voice.hardware_id
                        if vert_idx < len(mesh.vertices):
                            attr.data[vert_idx].value = clamped_val
                            mesh.update()
                            buf_obj.update_tag()

    ui_value: bpy.props.FloatProperty(
        name="Значение",
        get=get_ui_value,
        set=set_ui_value
    )

def sync_voice_property_to_vertex(self, context):
    """Умный сенсор: ловит изменения ручек на паузе и пинает граф зависимостей Блендера"""
    scene = context.scene
    if not hasattr(scene, "octavia_channels_data"):
        return

    # 🛡️ ПРЕДОХРАНИТЕЛЬ ОТМЕНЫ: Не даем колбэкам засирать Dependency Graph во время Undo/Redo
    from ..input_handlers.operator import OCTAVIA_OT_ui_handler
    if getattr(OCTAVIA_OT_ui_handler, '_block_sync_callbacks', False):
        return

    for ch_idx, ch_data in enumerate(scene.octavia_channels_data, start=1):
        for voice in ch_data.voices:
            if voice == self:
                buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
                buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
                
                if buf_obj and buf_obj.data:
                    mesh = buf_obj.data
                    punch_attr = mesh.attributes.get("octavia_macro_punch")
                    hold_attr = mesh.attributes.get("octavia_macro_hold")
                    echo_attr = mesh.attributes.get("octavia_macro_echo")
                    
                    # 🔥 КВАНТОВЫЙ ВИРТУАЛЬНЫЙ ПАТЧИНГ: Целимся строго по аппаратному адресу hardware_id
                    vert_idx = 128 + self.hardware_id
                    if vert_idx < len(mesh.vertices):
                        if punch_attr: punch_attr.data[vert_idx].value = self.punch
                        if hold_attr: hold_attr.data[vert_idx].value = self.hold
                        if echo_attr: echo_attr.data[vert_idx].value = self.echo
                        
                        mesh.update()
                        buf_obj.update_tag()
                return

class OctaviaVoiceSettings(bpy.types.PropertyGroup):
    """Контейнер параметров конкретного голоса кнопки на канале"""
    name: bpy.props.StringProperty(default="ГОЛОС 1")
    key_code: bpy.props.StringProperty(default="K")
    
    # Скрытый физический суверенный адрес вершины в меш-матрице (0 - 31)
    hardware_id: bpy.props.IntProperty(default=0)
    
    punch: bpy.props.FloatProperty(min=-10000.0, max=10000.0, default=0.5, update=sync_voice_property_to_vertex)
    hold: bpy.props.FloatProperty(min=-10000.0, max=10000.0, default=0.5, update=sync_voice_property_to_vertex)
    echo: bpy.props.FloatProperty(min=-10000.0, max=10000.0, default=0.5, update=sync_voice_property_to_vertex)
    macro_overrides: bpy.props.CollectionProperty(type=OctaviaMacroOverride)

class OctaviaChannelSettings(bpy.types.PropertyGroup):
    """Многоголосая конфигурация конкретного канала DAW"""
    voices: bpy.props.CollectionProperty(type=OctaviaVoiceSettings)
    active_voice_idx: bpy.props.IntProperty(default=0)