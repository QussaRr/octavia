import bpy
import os
from bpy_extras.io_utils import ImportHelper 

def get_octavia_presets(self, context):
    """Динамически сканирует подпапки орбит, геонод и шейдеров и собирает их в единый глобальный реестр UI"""
    addon_dir = os.path.dirname(os.path.dirname(__file__))
    presets_dir = os.path.join(addon_dir, "presets")
    
    # Базовая заглушка
    items = [("NONE", "НЕТ ПРЕСЕТА", "Пресет не выбран")]
    
    if not os.path.exists(presets_dir):
        return items
        
    # Сканируем все три суверенные папки Октавии
    subfolders = ['orbits', 'geonodes', 'shaders']
    seen_presets = set()
    
    for folder in subfolders:
        target_path = os.path.join(presets_dir, folder)
        if os.path.exists(target_path):
            try:
                for f in os.listdir(target_path):
                    if f.endswith(".blend"):
                        preset_id = os.path.splitext(f)[0].upper()
                        # Защита от дубликатов имён в разных папках
                        if preset_id not in seen_presets:
                            seen_presets.add(preset_id)
                            # Формат Блендера: (ключ, имя в меню, описание при наведении)
                            items.append((preset_id, preset_id.replace("_", " "), f"Загрузить [{preset_id}] из секции {folder.upper()}"))
            except Exception as e:
                print(f"❌ [Octavia UI Scan] Ошибка чтения подпапки {folder}: {e}")
                
    if len(items) == 1:
        return [("NONE", "НЕТ СОХРАНЕННЫХ ПРЕСЕТОВ", "Папки категорий пусты")]
        
    return items

class OCTAVIA_OT_load_audio(bpy.types.Operator, ImportHelper):
    bl_idname = "octavia.load_audio"
    bl_label = "Выбрать аудиофайл"
    filter_glob: bpy.props.StringProperty(default="*.mp3;*.wav;*.ogg;*.flac", options={'HIDDEN'}, maxlen=255)

    def execute(self, context):
        scene = context.scene 
        if not scene.sequence_editor:
            scene.sequence_editor_create()
            
        try:
            se = scene.sequence_editor
            container = getattr(se, "strips", getattr(se, "sequences", None))
            for strip in list(container):
                if strip.name.startswith("Octavia"):
                    container.remove(strip)

            audio_strip = container.new_sound(name="Octavia_Track", filepath=self.filepath, channel=1, frame_start=1)
            if audio_strip:
                audio_strip.show_waveform = True
                scene.frame_start = 1
                scene.frame_end = int(audio_strip.frame_duration)
            self.report({'INFO'}, f"Трек загружен! Длина таймлайна: {scene.frame_end} кадров.")
        except Exception as e:
            self.report({'ERROR'}, f"Ошибка: {e}")
            return {'CANCELLED'}
        return {'FINISHED'}

class OCTAVIA_OT_export_preset(bpy.types.Operator):
    bl_idname = "octavia.export_preset"
    bl_label = "Упаковать граф в пресет"
    bl_options = {'UNDO', 'INTERNAL'}

    # ✏️ УНИВЕРСАЛЬНАЯ ПЛАШКА ДЛЯ ИМЕНИ ПРЕСЕТА
    preset_name: bpy.props.StringProperty(
        name="Название пресета",
        description="Введите имя для вашего нового пресета",
        default=""
    )

    # 📁 СЕЛЕКТОР НАПРАВЛЕНИЯ ПОДПАПОК
    preset_category: bpy.props.EnumProperty(
        name="Категория",
        items=[
            ('orbits', "🌌 Орбиты (Orbits)", "Сохранить пресет в подпапку орбит"),
            ('geonodes', "🧪 Геоноды (Geonodes)", "Сохранить пресет в подпапку геонод"),
            ('shaders', "💎 Шейдеры (Shaders)", "Сохранить пресет в подпапку шейдеров"),
        ],
        default='orbits'
    )

    def invoke(self, context, event):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "Нет активного объекта во вьюпорте!")
            return {'CANCELLED'}
            
        mod = next((m for m in obj.modifiers if m.type == 'NODES'), None)
        
        if mod and mod.node_group:
            self.preset_name = mod.node_group.name
        else:
            obj_clean_name = obj.name.replace(" ", "_")
            self.preset_name = f"{obj_clean_name}_Preset"
            
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="ПАРАМЕТРЫ ИНИЦИАЛИЗАЦИИ И СБОРКИ", icon='NODETREE')
        box.prop(self, "preset_name", text="Имя")
        box.prop(self, "preset_category", text="Папка")

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "Нет активного объекта!")
            return {'CANCELLED'}
        
        clean_name = self.preset_name.strip().replace(" ", "_")
        if not clean_name:
            clean_name = f"{obj.name.replace(' ', '_')}_Preset"
            
        ch_idx = context.scene.octavia_active_channel
        addon_dir = os.path.dirname(os.path.dirname(__file__))
        presets_dir = os.path.join(addon_dir, "presets", self.preset_category)
        os.makedirs(presets_dir, exist_ok=True)
        filepath = os.path.join(presets_dir, f"{clean_name}.blend")
        
        # 🔥 ДВУХРЕЖИМНЫЙ СНАЙПЕРСКИЙ ЭКСПОРТЁР ОКТАВИИ
        if self.preset_category == 'orbits':
            # Режим Орбит: Запекаем физический 3D-объект кривой
            original_obj_name = obj.name
            obj.name = "Octavia_Orbit_Obj"
            
            # Находим или создаем внутренний граф для этой орбиты, чтобы она была автономной
            mod = next((m for m in obj.modifiers if m.type == 'NODES'), None)
            if not mod:
                mod = obj.modifiers.new(name=f"Octavia Channel {ch_idx}", type='NODES')
            if not mod.node_group:
                group = bpy.data.node_groups.new(name=clean_name, type='GeometryNodeTree')
                group.is_modifier = True  # 🔥 ГАРАНТИЯ ВИДИМОСТИ ДЛЯ UI ПРИ ЭКСПОРТЕ
                mod.node_group = group
                in_node = group.nodes.new('NodeGroupInput')
                out_node = group.nodes.new('NodeGroupOutput')
                if hasattr(group, "interface"):
                    group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
                    group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
                try: group.links.new(in_node.outputs[0], out_node.inputs[0])
                except: pass
                
            group = mod.node_group
            original_group_name = group.name
            group.name = "Octavia_Graph"
            
            try:
                bpy.data.libraries.write(filepath, {obj, group}, fake_user=True)
                self.report({'INFO'}, f"🌌 Гибридный пресет ОРБИТЫ упакован: {clean_name}")
            except Exception as e:
                self.report({'ERROR'}, f"Ошибка запекания орбиты: {e}")
            finally:
                obj.name = original_obj_name
                group.name = original_group_name
        else:
            # 🔥 РЕЖИМ ГЕОНОД / ШЕЙДЕРОВ: Пакуем ноду-группу активного канала.
            # Если графа на канале ещё нет — берём активный (или первый) Geometry
            # Nodes модификатор объекта. Это снимает проблему «курицы и яйца»:
            # граф можно собрать в обычном модификаторе и упаковать в пресет,
            # ещё не привязав его к каналу Октавии.
            mod_name = f"Octavia Channel {ch_idx}"
            mod = obj.modifiers.get(mod_name)

            if not mod or not mod.node_group:
                active_mod = obj.modifiers.active
                if active_mod and active_mod.type == 'NODES' and active_mod.node_group:
                    mod = active_mod
                else:
                    mod = next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group), None)

            if not mod or not mod.node_group:
                self.report({'ERROR'}, "На объекте нет ни одного Geometry Nodes графа для упаковки!")
                return {'CANCELLED'}

            group = mod.node_group
            original_group_name = group.name
            group.name = "Octavia_Graph"
            
            try:
                bpy.data.libraries.write(filepath, {group}, fake_user=True)
                self.report({'INFO'}, f"🧪 Модульный граф [{clean_name}] упакован в паку {self.preset_category.upper()}!")
            except Exception as e:
                self.report({'ERROR'}, f"Ошибка запекания графа: {e}")
            finally:
                group.name = original_group_name
                
        return {'FINISHED'}