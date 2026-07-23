"""Super Node — шаблон контракта Octavia для VSD (Geometry Nodes N-panel).

Файл: presets/geonodes/SUPER_NODE.blend (внутри пакуется как Octavia_Graph).
Загрузка вешает копию шаблона на Geometry Nodes модификатор активного объекта
(иначе NODE_EDITOR, привязанный к объекту, снова показывает пустой New-граф).
"""

from __future__ import annotations

import os

import bpy


SUPER_NODE_PRESET_ID = "SUPER_NODE"
SUPER_NODE_PACKED_NAME = "Octavia_Graph"
SUPER_NODE_RUNTIME_NAME = "Graph_SUPER_NODE"
SUPER_NODE_TEMPLATE_NAME = "_Octavia_Super_Node_Template"


def _addon_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def super_node_blend_path():
    return os.path.join(_addon_dir(), "presets", "geonodes", f"{SUPER_NODE_PRESET_ID}.blend")


def find_super_node_group():
    for name in (
        SUPER_NODE_TEMPLATE_NAME,
        SUPER_NODE_RUNTIME_NAME,
        SUPER_NODE_PACKED_NAME,
        SUPER_NODE_PRESET_ID,
    ):
        g = bpy.data.node_groups.get(name)
        if g is not None and getattr(g, "type", None) == "GEOMETRY":
            return g
    for g in bpy.data.node_groups:
        if "SUPER_NODE" in g.name.upper() and getattr(g, "type", None) == "GEOMETRY":
            return g
    return None


def append_super_node_from_blend(filepath):
    if not os.path.isfile(filepath):
        return None, f"файл не найден: {filepath}"

    before = set(bpy.data.node_groups.keys())
    try:
        with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
            names = list(data_from.node_groups or [])
            pick = None
            for candidate in (SUPER_NODE_PACKED_NAME, SUPER_NODE_RUNTIME_NAME, SUPER_NODE_PRESET_ID):
                if candidate in names:
                    pick = candidate
                    break
            if pick is None and names:
                pick = names[0]
            if pick is None:
                return None, "в .blend нет node groups"
            data_to.node_groups = [pick]

        imported = None
        if getattr(data_to, "node_groups", None):
            imported = data_to.node_groups[0] if data_to.node_groups else None
        if imported is None:
            after = set(bpy.data.node_groups.keys()) - before
            if after:
                imported = bpy.data.node_groups.get(sorted(after)[0])
        if imported is None:
            return None, "не удалось импортировать node group"

        try:
            imported.is_modifier = True
        except Exception:
            pass
        # Каноническое имя шаблона (не трогаем пользовательский Graph_SUPER_NODE)
        try:
            imported.name = SUPER_NODE_TEMPLATE_NAME
        except Exception:
            pass
        return imported, None
    except Exception as e:
        return None, str(e)


def _resolve_nodes_modifier(obj):
    """Активный GN-модификатор объекта, либо первый, либо новый."""
    if obj is None:
        return None
    mod = obj.modifiers.active
    if mod is not None and mod.type == "NODES":
        return mod
    for m in obj.modifiers:
        if m.type == "NODES":
            return m
    return obj.modifiers.new(name="GeometryNodes", type="NODES")


def _bind_editor_to_group(context, group):
    space = context.space_data
    if space and space.type == "NODE_EDITOR":
        try:
            space.node_tree = group
            return True
        except Exception:
            pass
    for win in context.window_manager.windows:
        screen = win.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type != "NODE_EDITOR":
                continue
            for sp in area.spaces:
                if sp.type == "NODE_EDITOR" and getattr(sp, "tree_type", "") == "GeometryNodeTree":
                    try:
                        sp.node_tree = group
                        area.tag_redraw()
                        return True
                    except Exception:
                        continue
    return False


def _rebind_buffer_object_info(group, context):
    """Если есть буфер активного канала — привязать Object Info (как у пресетов)."""
    try:
        from ...nodes import _rebind_object_info
    except Exception:
        return
    scene = context.scene
    ch = int(getattr(scene, "octavia_active_channel", 1) or 1)
    buf = scene.objects.get(f"Octavia_Buffer_Ch_{ch}") or bpy.data.objects.get(
        f"Octavia_Buffer_Ch_{ch}"
    )
    if buf and group:
        _rebind_object_info(group, buf)


class OCTAVIA_OT_load_super_node(bpy.types.Operator):
    """Копия SUPER_NODE → GN-модификатор активного объекта + открыть в редакторе."""
    bl_idname = "octavia.load_super_node"
    bl_label = "Загрузить Super Node"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == "NODE_EDITOR" and space.tree_type == "GeometryNodeTree"

    def execute(self, context):
        obj = context.object or context.active_object
        if obj is None:
            self.report({"ERROR"}, "Нет активного объекта — выдели куб/меш во вьюпорте")
            return {"CANCELLED"}

        blend_path = super_node_blend_path()
        template = None

        # Предпочитаем файл на диске (актуальный шаблон)
        if os.path.isfile(blend_path):
            template, err = append_super_node_from_blend(blend_path)
            if template is None:
                print(f"[Octavia] load_super_node blend fail: {err}")

        if template is None:
            template = find_super_node_group()

        if template is None:
            self.report(
                {"ERROR"},
                "Super Node не найден. Открой полный Graph_SUPER_NODE и нажми «СОХРАНИТЬ», "
                f"файл должен появиться: presets/geonodes/{SUPER_NODE_PRESET_ID}.blend",
            )
            return {"CANCELLED"}

        # Пустой New-граф не шаблон: если в шаблоне только IO — ругаемся
        real_nodes = [
            n for n in template.nodes
            if n.bl_idname not in {"NodeGroupInput", "NodeGroupOutput", "NodeReroute"}
        ]
        if len(real_nodes) < 1:
            self.report(
                {"ERROR"},
                f"«{template.name}» пустой (только IO). Сохрани нормальный Super Node кнопкой «СОХРАНИТЬ».",
            )
            return {"CANCELLED"}

        mod = _resolve_nodes_modifier(obj)
        if mod is None:
            self.report({"ERROR"}, "Не удалось создать Geometry Nodes модификатор")
            return {"CANCELLED"}

        # Копия на объект — имя простое, автор переименует сам
        instance = template.copy()
        try:
            instance.is_modifier = True
        except Exception:
            pass
        try:
            instance.name = "Geometry Nodes"
        except Exception:
            pass

        old_group = mod.node_group
        mod.node_group = instance
        _rebind_buffer_object_info(instance, context)
        _bind_editor_to_group(context, instance)

        # Убрать осиротевший пустой New, если юзер только что нажал New
        if old_group is not None and old_group != template and old_group != instance:
            old_real = [
                n for n in old_group.nodes
                if n.bl_idname not in {"NodeGroupInput", "NodeGroupOutput", "NodeReroute"}
            ]
            if len(old_real) < 1 and old_group.users == 0:
                try:
                    bpy.data.node_groups.remove(old_group)
                except Exception:
                    pass

        obj.update_tag()
        for area in context.screen.areas if context.screen else []:
            if area.type in {"NODE_EDITOR", "VIEW_3D"}:
                area.tag_redraw()

        self.report({"INFO"}, f"Super Node на «{obj.name}»: {instance.name} ({len(real_nodes)} нод)")
        return {"FINISHED"}


class OCTAVIA_OT_save_super_node(bpy.types.Operator):
    """Пакует активный граф GN как presets/geonodes/SUPER_NODE.blend."""
    bl_idname = "octavia.save_super_node"
    bl_label = "Сохранить Super Node"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return (
            space
            and space.type == "NODE_EDITOR"
            and space.tree_type == "GeometryNodeTree"
            and space.edit_tree is not None
        )

    def execute(self, context):
        group = context.space_data.edit_tree
        if group is None:
            self.report({"ERROR"}, "Нет открытого графа")
            return {"CANCELLED"}

        real_nodes = [
            n for n in group.nodes
            if n.bl_idname not in {"NodeGroupInput", "NodeGroupOutput", "NodeReroute"}
        ]
        if len(real_nodes) < 1:
            self.report({"ERROR"}, "Граф пустой (только IO) — нечего сохранять как Super Node")
            return {"CANCELLED"}

        out_dir = os.path.join(_addon_dir(), "presets", "geonodes")
        os.makedirs(out_dir, exist_ok=True)
        filepath = super_node_blend_path()

        original_name = group.name
        try:
            try:
                group.is_modifier = True
            except Exception:
                pass
            group.name = SUPER_NODE_PACKED_NAME
            bpy.data.libraries.write(filepath, {group}, fake_user=True)
        except Exception as e:
            self.report({"ERROR"}, f"Не удалось сохранить: {e}")
            return {"CANCELLED"}
        finally:
            # Вернуть рабочее имя; шаблон в data обновим копией имени
            try:
                group.name = original_name
            except Exception:
                pass

        # Держим эталон в bpy.data под стабильным именем шаблона
        existing = bpy.data.node_groups.get(SUPER_NODE_TEMPLATE_NAME)
        if existing is not None and existing != group:
            try:
                bpy.data.node_groups.remove(existing)
            except Exception:
                pass
        # Подтянуть с диска в data как шаблон (свежий append)
        tmpl, err = append_super_node_from_blend(filepath)
        if tmpl is None and err:
            print(f"[Octavia] save_super_node re-append: {err}")

        self.report(
            {"INFO"},
            f"Super Node сохранён ({len(real_nodes)} нод) → presets/geonodes/{SUPER_NODE_PRESET_ID}.blend",
        )
        return {"FINISHED"}
