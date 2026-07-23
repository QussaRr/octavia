import bpy

class OCTAVIA_OT_rename_channel_popup(bpy.types.Operator):
    """Красивое всплывающее окошко для изменения имени канала"""
    bl_idname = "octavia.rename_channel_popup"
    bl_label = "Переименовать канал"
    bl_options = {'UNDO', 'INTERNAL'}

    channel_idx: bpy.props.IntProperty()
    new_name: bpy.props.StringProperty(name="Название канала")

    def invoke(self, context, event):
        scene = context.scene
        self.new_name = getattr(scene, f"octavia_ch{self.channel_idx}_name", f"Канал {self.channel_idx}")
        return context.window_manager.invoke_props_dialog(self, width=350)

    def draw(self, context):
        self.layout.label(text=f"Введите новое имя для Канала {self.channel_idx}:", icon='FONT_DATA')
        self.layout.prop(self, "new_name", text="")

    def execute(self, context):
        setattr(context.scene, f"octavia_ch{self.channel_idx}_name", self.new_name)
        context.area.tag_redraw()
        return {'FINISHED'}


class OCTAVIA_OT_add_channel(bpy.types.Operator):
    bl_idname = "octavia.add_channel"
    bl_label = "Добавить канал"
    def execute(self, context):
        if context.scene.octavia_channel_count < 20:
            new_idx = context.scene.octavia_channel_count + 1

            # 🔥 СВЕРХЗВУКОВОЙ РЕСЕТ КЭША: Выжигаем старые призраки Блендера под этим индексом
            setattr(context.scene, f"octavia_ch{new_idx}_name", f"Канал {new_idx}")
            setattr(context.scene, f"octavia_ch{new_idx}_preset", "NONE")
            if f"octavia_ch{new_idx}_mesh_name" in context.scene:
                del context.scene[f"octavia_ch{new_idx}_mesh_name"]
                
            # 🪐 ГЕНЕРАЦИЯ ДАТА-МЕША ДЛЯ КОЛЬЦЕВОГО БУФЕРА ГОЛОСОВ
            mesh_name = f"Octavia_Buffer_Ch_{new_idx}"
            mesh_data = bpy.data.meshes.new(mesh_name)
            mesh_data["is_octavia_buffer"] = 1
            
            # Спавним 160 вершин (0-127 ноты, 128-159 конфигурация голосов)
            verts = [(0.0, 0.0, float(i)) for i in range(160)]
            mesh_data.from_pydata(verts, [], [])
            mesh_data.update()
            
            # Создаем C++ слои атрибутов на уровне точек (POINT)
            start_attr = mesh_data.attributes.new(name="start_frame", type='FLOAT', domain='POINT')
            end_attr = mesh_data.attributes.new(name="end_frame", type='FLOAT', domain='POINT')
            voice_id_attr = mesh_data.attributes.new(name="octavia_voice_id", type='FLOAT', domain='POINT')
            punch_attr = mesh_data.attributes.new(name="octavia_macro_punch", type='FLOAT', domain='POINT')
            hold_attr = mesh_data.attributes.new(name="octavia_macro_hold", type='FLOAT', domain='POINT')
            echo_attr = mesh_data.attributes.new(name="octavia_macro_echo", type='FLOAT', domain='POINT')
            
            # 1. Зануляем Зону Нот (0 - 127) безопасным стейтом сна (-1.0)
            for i in range(128):
                start_attr.data[i].value = -1.0
                end_attr.data[i].value = -1.0
                voice_id_attr.data[i].value = -1.0
                
            # 2. Инициализируем Зону Конфигурации параметров (128 - 159) дефолтом 0.5
            for i in range(128, 160):
                punch_attr.data[i].value = 0.5
                hold_attr.data[i].value = 0.5
                echo_attr.data[i].value = 0.5

            # 3. Обратная совместимость: Рождаем "Голос 1 [K]" с аппаратным адресом 0
            ch_data = context.scene.octavia_channels_data.add()
            v_default = ch_data.voices.add()
            v_default.name = "ГОЛОС 1"
            v_default.key_code = "K"
            v_default.hardware_id = 0
            v_default.punch = 0.5
            v_default.hold = 0.5
            v_default.echo = 0.5
                
            obj_buffer = bpy.data.objects.new(mesh_name, mesh_data)
            context.scene.collection.objects.link(obj_buffer)
            
            # Прячем контейнер данных от глаз продюсера, но НЕ через hide_viewport:
            # «Disable in Viewports» выкидывает объект из depsgraph, и тогда Object Info
            # в графе получает пустую геометрию (и Spreadsheet пуст). Прячем «глазом»
            # (hide_set) — объект невидим, но продолжает вычисляться и читаться графом.
            obj_buffer.hide_render = True
            obj_buffer.hide_select = True
            try:
                obj_buffer.hide_set(True)
            except Exception:
                pass
            
            context.scene.octavia_channel_count += 1
        return {'FINISHED'}


class OCTAVIA_OT_delete_channel(bpy.types.Operator):
    """Удаляет канал мгновенно, зачищая физический мусор и перестраивая стек модификаторов"""
    bl_idname = "octavia.delete_channel"
    bl_label = "Удалить этот канал"
    bl_options = {'UNDO'}
    channel_idx: bpy.props.IntProperty()
   
    def execute(self, context):
        scene = context.scene
        count = scene.octavia_channel_count
        del_idx = self.channel_idx
        
        if count <= 1:
            self.report({'WARNING'}, "Нельзя удалить единственный канал")
            return {'CANCELLED'}

        # 🟢 1. ФИЗИЧЕСКАЯ УТИЛИЗАЦИЯ СЛОЕВ УДАЛЯЕМОГО КАНАЛА
        for obj in list(scene.objects):
            # Сносим модификатор Geometry Nodes именно этого канала
            mod = obj.modifiers.get(f"Octavia Channel {del_idx}")
            if mod: obj.modifiers.remove(mod)
           
            # Сносим Follow Path констрейнт именно этого канала
            con = obj.constraints.get(f"Octavia_Follow_{del_idx}")
            if con: obj.constraints.remove(con)

        # 🟢 2. БЕЗОПАСНОЕ УДАЛЕНИЕ ИЗ КОЛЛЕКЦИИ ДАННЫХ ДВИЖКА
        if hasattr(scene, "octavia_channels_data") and len(scene.octavia_channels_data) >= del_idx:
            scene.octavia_channels_data.remove(del_idx - 1)

        # 🟢 3. СИНХРОННОЕ ПЕРЕИМЕНОВАНИЕ ПОСЛЕДУЮЩИХ СЛОЕВ (РЕХЕШИНГ СТЕКА МОДИФИКАТОРОВ)
        for i in range(del_idx, count):
            next_idx = i + 1
            for obj in scene.objects:
                mod = obj.modifiers.get(f"Octavia Channel {next_idx}")
                if mod: mod.name = f"Octavia Channel {i}"
               
                con = obj.constraints.get(f"Octavia_Follow_{next_idx}")
                if con: con.name = f"Octavia_Follow_{i}"

        # 🟢 4. ВИРТУАЛЬНОЕ СМЕЩЕНИЕ СВОЙСТВ ПИТОНА (ЖЕСТКИЙ СДВИГ С ПЕРЕИНДЕКСАЦИЕЙ)
        for i in range(del_idx, count):
            next_ch = i + 1
            old_name = getattr(scene, f"octavia_ch{next_ch}_name", f"Канал {next_ch}")
            
            # Если имя канала дефолтное (например, "Канал 4"), динамически обновляем цифру под новый индекс
            if old_name.strip().lower() == f"канал {next_ch}":
                new_name = f"Канал {i}"
            else:
                new_name = old_name  # Если юзер переименовал канал вручную, бережно сохраняем имя
                
            setattr(scene, f"octavia_ch{i}_name", new_name)
            setattr(scene, f"octavia_ch{i}_preset", getattr(scene, f"octavia_ch{next_ch}_preset", "NONE"))
            
            if f"octavia_ch{next_ch}_mesh_name" in scene:
                scene[f"octavia_ch{i}_mesh_name"] = scene[f"octavia_ch{next_ch}_mesh_name"]
            elif f"octavia_ch{i}_mesh_name" in scene:
                del scene[f"octavia_ch{i}_mesh_name"]
           
        scene.octavia_channel_count -= 1
       
        # Умная коррекция активного выбора
        if scene.octavia_active_channel > scene.octavia_channel_count:
            scene.octavia_active_channel = max(1, scene.octavia_channel_count)
           
        # 🟢 5. СКАНИРОВАНИЕ И ПУРГ ОСИРОТЕВШИХ КРИВЫХ (АНТИ-МУСОРНЫЙ ФИЛЬТР)
        active_orbit_targets = set()
        for obj in scene.objects:
            for con in obj.constraints:
                if con.type == 'FOLLOW_PATH' and con.name.startswith("Octavia_Follow_") and con.target:
                    active_orbit_targets.add(con.target)
                   
        for obj in list(scene.objects):
            if obj.name.startswith("Orbit_") and obj.type == 'CURVE':
                if obj not in active_orbit_targets:
                    bpy.data.objects.remove(obj, do_unlink=True)
           
        # 🟢 6. ИЗОЛИРОВАННЫЕ ОПЕРАЦИИ НАД ДАТА-БУФЕРАМИ ОКТАВИИ (ФИНАЛ)
        buf_name = f"Octavia_Buffer_Ch_{del_idx}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if buf_obj:
            buf_mesh = buf_obj.data
            bpy.data.objects.remove(buf_obj, do_unlink=True)
            if buf_mesh:
                bpy.data.meshes.remove(buf_mesh)

        # Безопасно смещаем имена дата-буферов последующих каналов на индекс вниз
        for i in range(del_idx, count):
            next_idx = i + 1
            old_buf_name = f"Octavia_Buffer_Ch_{next_idx}"
            new_buf_name = f"Octavia_Buffer_Ch_{i}"
            sub_buf_obj = scene.objects.get(old_buf_name) or bpy.data.objects.get(old_buf_name)
            if sub_buf_obj:
                sub_buf_obj.name = new_buf_name
                if sub_buf_obj.data:
                    sub_buf_obj.data.name = new_buf_name

        # 🔗 ЖЁСТКИЙ РЕБАЙНД OBJECT INFO ПОСЛЕ ПЕРЕНУМЕРАЦИИ
        # Инвариант Октавии: граф "Octavia Channel i" обязан читать "Octavia_Buffer_Ch_i".
        # После сдвига индексов Object Info выжившего графа продолжает смотреть на
        # старый/удалённый буфер (или на буфер соседнего канала) — и куб замирает.
        # Пересобираем связь детерминированно, трогая только буферные цели (не орбиты).
        for i in range(1, scene.octavia_channel_count + 1):
            buf_i = scene.objects.get(f"Octavia_Buffer_Ch_{i}") or bpy.data.objects.get(f"Octavia_Buffer_Ch_{i}")
            if not buf_i:
                continue
            for gobj in scene.objects:
                gmod = gobj.modifiers.get(f"Octavia Channel {i}")
                if gmod and gmod.node_group:
                    for node in gmod.node_group.nodes:
                        if node.bl_idname == 'GeometryNodeObjectInfo' and node.inputs:
                            tgt = node.inputs[0].default_value
                            tgt_name = getattr(tgt, "name", "") if tgt else ""
                            if tgt is None or tgt_name.startswith("Octavia_Buffer_Ch_"):
                                node.inputs[0].default_value = buf_i

        # Насильно заставляем Blender пересчитать зависимости сцены
        context.view_layer.update()

        # Сканируем макросы и полностью перерисовываем интерфейс
        bpy.ops.octavia.rescan_macros()
       
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in {'CLIP_EDITOR', 'VIEW_3D'}:
                    area.tag_redraw()
                   
        return {'FINISHED'}
       
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    
class OCTAVIA_OT_delete_voice(bpy.types.Operator):
    """Хирургическое удаление голоса с занулением вершины и переиндексацией UI"""
    bl_idname = "octavia.delete_voice"
    bl_label = "Delete Octavia Voice"
    
    channel_idx: bpy.props.IntProperty(default=1)
    voice_idx: bpy.props.IntProperty(default=0)

    def execute(self, context):
        scene = context.scene
        if len(scene.octavia_channels_data) < self.channel_idx: return {'CANCELLED'}
        ch_data = scene.octavia_channels_data[self.channel_idx - 1]
        if len(ch_data.voices) <= self.voice_idx: return {'CANCELLED'}
        
        voice_to_del = ch_data.voices[self.voice_idx]
        target_hw_id = voice_to_del.hardware_id
        
        # ⚡ ХАК «НЕМЫХ ПРИЗРАКОВ»: Зануляем физическую вершину в C++ меше
        buf_name = f"Octavia_Buffer_Ch_{self.channel_idx}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if buf_obj and buf_obj.data:
            mesh = buf_obj.data
            p_attr = mesh.attributes.get("octavia_macro_punch")
            h_attr = mesh.attributes.get("octavia_macro_hold")
            e_attr = mesh.attributes.get("octavia_macro_echo")
            vert_idx = 128 + target_hw_id
            if vert_idx < len(mesh.vertices):
                if p_attr: p_attr.data[vert_idx].value = 0.0
                if h_attr: h_attr.data[vert_idx].value = 0.0
                if e_attr: e_attr.data[vert_idx].value = 0.0
                mesh.update()
                buf_obj.update_tag()

        # Удаляем элемент из коллекции Питона (0% нагрузки на таймлайн кривых Блендера!)
        ch_data.voices.remove(self.voice_idx)
        
        # Корректируем фокус активного таба, чтобы интерфейс не улетел в пустоту
        ch_data.active_voice_idx = max(0, min(ch_data.active_voice_idx, len(ch_data.voices) - 1))
        
        # Косметическая динамическая переиндексация имен оставшихся в HUD вкладок
        for i, v in enumerate(ch_data.voices):
            suffix = f" [{v.key_code}]" if v.key_code else ""
            v.name = f"ГОЛОС {i + 1}{suffix}"
            
        # 🛡️ БРОНЕБОЙНЫЙ ЩИТ КОНТЕКСТА: Шьем предохранитель от NoneType крашей Blender API
        if context.area:
            context.area.tag_redraw()
            
        return {'FINISHED'}