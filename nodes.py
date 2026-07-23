import bpy
import os


def _preset_filepath(category, preset_id):
    """Путь к .blend пресета в табличной раскладке presets/{category}/{id}.blend."""
    addon_dir = os.path.dirname(__file__)
    return os.path.join(addon_dir, "presets", category.lower(), f"{preset_id}.blend")


def _rebind_object_info(group, buf_obj):
    """Привязывает Object Info графа к буферу СВОЕГО канала.

    Нода-группа переиспользуется по имени из памяти, поэтому её Object Info
    может указывать на старый/переименованный буфер после удаления канала.
    Проверка «== None» недостаточна — перебиваем цель, если она пуста ИЛИ
    смотрит на любой буфер Октавии. Не-буферные Object Info (орбиты и т.п.)
    не трогаем.
    """
    if not buf_obj:
        return
    for node in group.nodes:
        if node.bl_idname == 'GeometryNodeObjectInfo' and node.inputs:
            tgt = node.inputs[0].default_value
            tgt_name = getattr(tgt, "name", "") if tgt else ""
            if tgt is None or tgt_name.startswith("Octavia_Buffer_Ch_"):
                node.inputs[0].default_value = buf_obj


def apply_channel_preset(context, target_obj, ch_idx, category, preset_id):
    """ЕДИНАЯ точка входа применения пресета графа к каналу Октавии.

    Обслуживает все вкладки (ORBITS / GEONODES / SHADERS). Грузит граф (и кривую
    орбиты для ORBITS) из presets/{category}/{preset_id}.blend, вешает модификатор
    Geometry Nodes «Octavia Channel {ch_idx}», для орбит — Follow Path констрейнт,
    переносит старый action, ребайндит Object Info на буфер канала и пишет
    свойства сцены (preset / mesh_name).

    Возвращает (ok: bool, message: str). Ошибки НЕ роняют вызывающий обработчик.
    """
    category = (category or "GEONODES").upper()
    filepath = _preset_filepath(category, preset_id)
    preset_filename = f"{preset_id}.blend"

    if not os.path.exists(filepath):
        return False, f"файл пресета не найден ({preset_filename})"

    graph_name = f"Graph_{preset_id}"

    try:
        imported_curve = None
        imported_group = bpy.data.node_groups.get(graph_name)

        if category == 'ORBITS':
            curve_name = f"Orbit_{preset_id}"
            imported_curve = context.scene.objects.get(curve_name) or bpy.data.objects.get(curve_name)

            if not imported_curve or not imported_group:
                with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                    if not imported_curve and "Octavia_Orbit_Obj" in data_from.objects:
                        data_to.objects = ["Octavia_Orbit_Obj"]
                    if not imported_group:
                        # Предпочитаем точное имя, иначе берём первую группу
                        # (защита от коллизии Octavia_Graph.001 при сохранении)
                        if "Octavia_Graph" in data_from.node_groups:
                            data_to.node_groups = ["Octavia_Graph"]
                        elif data_from.node_groups:
                            data_to.node_groups = [data_from.node_groups[0]]

                if data_to.objects and data_to.objects[0]:
                    imported_curve = data_to.objects[0]
                    imported_curve.name = curve_name
                    try: imported_curve.make_local()
                    except: pass

                if imported_curve and imported_curve.type == 'CURVE':
                    imported_curve.data.use_path = True

                if data_to.node_groups and data_to.node_groups[0]:
                    imported_group = data_to.node_groups[0]
                    imported_group.name = graph_name
        else:
            if not imported_group:
                with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to):
                    if "Octavia_Graph" in data_from.node_groups:
                        data_to.node_groups = ["Octavia_Graph"]
                    elif data_from.node_groups:
                        data_to.node_groups = [data_from.node_groups[0]]
                if data_to.node_groups and data_to.node_groups[0]:
                    imported_group = data_to.node_groups[0]
                    imported_group.name = graph_name

        if imported_group:
            try: imported_group.make_local()
            except: pass
            imported_group.is_modifier = True
            imported_group.use_fake_user = True
            context.scene[f"octavia_fake_anchor_{preset_id}"] = imported_group

        mod_name = f"Octavia Channel {ch_idx}"

        if category == 'ORBITS':
            if imported_curve and curve_name not in context.scene.collection.objects:
                context.scene.collection.objects.link(imported_curve)

            if imported_curve and target_obj:
                imported_curve.location = target_obj.location.copy()
                for m in list(imported_curve.modifiers):
                    imported_curve.modifiers.remove(m)

            if imported_group and target_obj:
                for mod in list(target_obj.modifiers):
                    if mod.name == mod_name: target_obj.modifiers.remove(mod)

                new_mod = target_obj.modifiers.new(name=mod_name, type='NODES')
                new_mod.node_group = imported_group

                con_name = f"Octavia_Follow_{ch_idx}"
                old_con = target_obj.constraints.get(con_name)
                if old_con: target_obj.constraints.remove(old_con)

                con = target_obj.constraints.new(type='FOLLOW_PATH')
                con.name = con_name
                con.target = imported_curve
                con.use_fixed_location = True
                con.use_curve_follow = True
                target_obj.location = (0.0, 0.0, 0.0)
        else:
            if imported_group and target_obj:
                old_mod = target_obj.modifiers.get(mod_name)
                old_action = None
                if old_mod and old_mod.node_group and old_mod.node_group.animation_data:
                    old_action = old_mod.node_group.animation_data.action

                if old_mod:
                    old_mod.node_group = imported_group
                else:
                    new_mod = target_obj.modifiers.new(name=mod_name, type='NODES')
                    new_mod.node_group = imported_group

                if old_action:
                    if not imported_group.animation_data: imported_group.animation_data_create()
                    imported_group.animation_data.action = old_action

                buf = context.scene.objects.get(f"Octavia_Buffer_Ch_{ch_idx}") or bpy.data.objects.get(f"Octavia_Buffer_Ch_{ch_idx}")
                _rebind_object_info(imported_group, buf)

        setattr(context.scene, f"octavia_ch{ch_idx}_preset", preset_id)
        if target_obj:
            context.scene[f"octavia_ch{ch_idx}_mesh_name"] = target_obj.name

        return True, f"Пресет {preset_id} применён к каналу {ch_idx}"

    except Exception as e:
        return False, f"не удалось загрузить пресет — {e}"
