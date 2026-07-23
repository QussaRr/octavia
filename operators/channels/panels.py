import bpy
import os


class OCTAVIA_PT_main_panel(bpy.types.Panel):
    bl_label = "Octavia Control"
    bl_idname = "OCTAVIA_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Octavia'

    def draw(self, context):
        layout = self.layout
       
        # Постоянный блок медиа-стриминга для длинных сетов
        box_audio = layout.box()
        box_audio.label(text="МЕДИА СТРИМИНГ:", icon='FILE_SOUND')
        box_audio.operator("octavia.load_audio", text="Загрузить / Сменить аудио-трек", icon='IMPORT')
        layout.separator()
       
        # Инструменты навигации
        layout.column().operator("octavia.switch_workspace", text="ОТКРЫТЬ ИНТЕРФЕЙС DAW", icon='WINDOW')
        # LIVE — только на линейке DAW (● LIVE), не в N-панели
       
        # Инструменты разработки и экспорта (Панель полностью восстановлена)
        layout.separator()
        box_diag = layout.box()
        box_diag.label(text="ИНСТРУМЕНТЫ РАЗРАБОТКИ:", icon='PROPERTIES')
        box_diag.operator("octavia.snapshot_buffer", text="СНЯТЬ СЛЕПОК БУФЕРА", icon='MESH_DATA')
        box_diag.operator("octavia.export_preset", text="УПАКОВАТЬ ГРАФ В ПРЕСЕТ", icon='PRESET_NEW')


class OCTAVIA_PT_vsd_inspector(bpy.types.Panel):
    bl_label = "Octavia VSD Inspector"
    bl_idname = "OCTAVIA_PT_vsd_inspector"
    bl_space_type = 'NODE_EDITOR'  
    bl_region_type = 'UI'
    bl_category = "Octavia VSD"    

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.tree_type == 'GeometryNodeTree'

    def draw(self, context):
        layout = self.layout
        space = context.space_data
       
        if not space.edit_tree:
            layout.label(text="Октавия спит. Откройте граф геонод.", icon='INFO')
            return

        # Снимок всего графа для консоли и файла (для ИИ-сессий)
        box_snap = layout.box()
        box_snap.label(text="СЛЕПОК ГРАФА ДЛЯ ИИ:", icon='FILE_TEXT')
        box_snap.operator("octavia.snapshot_graph", text="СНЯТЬ СЛЕПОК ГРАФА", icon='NODETREE')
        box_snap.prop(context.scene, "octavia_auto_graph_snapshot", text="Авто после правок")
        box_snap.operator(
            "octavia.export_authoring_kit",
            text="ПАПКА ДЛЯ СЕССИИ С ИИ",
            icon='FILE_FOLDER',
        )
        export_dir = (getattr(context.scene, "octavia_authoring_export_dir", "") or "").strip()
        if export_dir:
            box_snap.label(text=os.path.basename(export_dir.rstrip("/\\")) or export_dir, icon='CHECKMARK')
        layout.separator()

        active_node = space.edit_tree.nodes.active
        if not active_node:
            layout.label(text="Выделите любую ноду для анализа.", icon='RESTRICT_SELECT_ON')
            return
           
        # 🧬 БЛОК ТОТАЛЬНОГО ДНК-ДОКУМЕНТИРОВАНИЯ ДЛЯ СЛЕДУЮЩИХ ИИ-СЕССИЙ
        box_dna = layout.box()
        box_dna.label(text=f"🧬 ДНК ЛОГИКИ: {active_node.name}", icon='TEXT')
        
        # Нативно и безопасно выводим свойство, без нелегальных записей в draw()
        box_dna.prop(active_node, "octavia_dna", text="")
        box_dna.label(text=" Опишите назначение ноды и её физику для ИИ", icon='INFO')
        layout.separator()
           
        # 🎛️ ПАСПОРТ МАКРОСА (Показывается ТОЛЬКО если выделена нода Value)
        if active_node.bl_idname == 'ShaderNodeValue':
            macro = active_node.octavia_macro
            box = layout.box()
            box.label(text="НАСТРОЙКИ МАКРО-РУЧКИ HUD:", icon='NODE_SEL')
            box.prop(macro, "is_macro", toggle=True, icon='EXPORT' if macro.is_macro else 'RADIOBUT_OFF')
           
            if macro.is_macro:
                col = box.column(align=False)
                col.separator()
                col.label(text="Паспорт ручки:", icon='SORTALPHA')
                col.prop(macro, "friendly_name", text="Имя в DAW")
                col.prop(macro, "category", text="Категория")
                col.separator()
                col.label(text="Диапазон значений:", icon='SETTINGS')
                row = col.row(align=True)
                row.prop(macro, "min_value", text="Мин")
                row.prop(macro, "max_value", text="Макс")
                col.separator()
                col.label(text="Инженерное описание (Tooltip):", icon='TEXT')
                col.prop(macro, "description", text="")
                col.separator()
                col.operator("octavia.rescan_macros", text="ОБНОВИТЬ РУЧКИ В DAW", icon='FILE_REFRESH')