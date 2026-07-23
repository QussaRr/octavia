import bpy
import os
import re
import shutil
import time
from bpy.app.handlers import persistent


def _addon_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _graph_snapshot_dirs(scene):
    """Директории для слепков графа: всегда аддон + пользовательская сессия, если задана."""
    dirs = [os.path.join(_addon_dir(), "graph_snapshots")]
    export_dir = (getattr(scene, "octavia_authoring_export_dir", "") or "").strip()
    if export_dir and os.path.isdir(export_dir):
        dirs.append(os.path.join(export_dir, "graph_snapshots"))
    return dirs


def _copy_authoring_kit(dest_root):
    """Копирует файлы authoring_kit в корень dest_root (перезаписывает kit, чужие файлы не трогает)."""
    src_root = os.path.join(_addon_dir(), "authoring_kit")
    if not os.path.isdir(src_root):
        raise FileNotFoundError(f"authoring_kit не найден: {src_root}")

    copied = 0
    for root, _dirs, files in os.walk(src_root):
        rel = os.path.relpath(root, src_root)
        dest_dir = dest_root if rel == "." else os.path.join(dest_root, rel)
        os.makedirs(dest_dir, exist_ok=True)
        for name in files:
            shutil.copy2(os.path.join(root, name), os.path.join(dest_dir, name))
            copied += 1
    return copied


def _build_graph_report(group, mod_name):
    """Собирает архитектурный отчёт по графу Geometry Nodes в список строк."""
    link_indices = {link: i + 1 for i, link in enumerate(group.links)}

    TARGET_PROPERTIES = [
        "transform_space", "geometry_type", "data_type", "domain",
        "mode", "operation", "evaluation_type", "input_type",
        "string_sub_operation", "math_mode",
    ]

    lines = []
    lines.append(f"================== ARCHITECTURE ANALYSIS: [{mod_name}] ({group.name}) ==================")

    frames = {}
    orphans = []

    for node in group.nodes:
        if node.bl_idname == 'NodeFrame':
            f_label = node.label if node.label else node.name
            frames[node] = {"label": f_label, "nodes": []}

    for node in group.nodes:
        if node.bl_idname == 'NodeFrame':
            continue
        if node.parent and node.parent in frames:
            frames[node.parent]["nodes"].append(node)
        else:
            orphans.append(node)

    def dump_node_log(node):
        label = node.label if node.label else "NONE"
        node_dna = getattr(node, "octavia_dna", "").strip() or "Not documented."

        lines.append(f"\n  Node: [{node.name}] | LABEL: \"{label}\" (Type: {node.bl_idname})")
        lines.append(f"    DNA LOGIC: {node_dna}")

        node_settings = []
        for prop in TARGET_PROPERTIES:
            if hasattr(node, prop):
                node_settings.append(f"{prop.upper()}: {getattr(node, prop)}")

        for rna_prop in node.bl_rna.properties:
            prop_id = rna_prop.identifier
            if "clamp" in prop_id.lower():
                clamp_val = getattr(node, prop_id, None)
                if clamp_val is not None:
                    node_settings.append(f"{prop_id.upper()}: {clamp_val}")

        if node_settings:
            lines.append(f"    PARAMETERS: {', '.join(node_settings)}")

        visible_inputs = [
            (idx, inp) for idx, inp in enumerate(node.inputs)
            if not inp.hide and not getattr(inp, "is_unavailable", False)
        ]

        if visible_inputs:
            lines.append("    Inputs:")
            for idx, inp in visible_inputs:
                is_linked = inp.is_linked
                links_to_socket = [l for l in group.links if l.to_socket == inp]
                status = f"LINKED (Slot {idx})" if is_linked else "FREE"
                val_str = ""

                if not is_linked and hasattr(inp, "default_value"):
                    try:
                        val = inp.default_value
                        if hasattr(val, "__len__") and not isinstance(val, (str, bytes)):
                            coords = ["X", "Y", "Z", "W"]
                            vector_elements = [f"{coords[i]}={round(val[i], 3)}" for i in range(min(len(val), 4))]
                            val_str = f" [Value: {', '.join(vector_elements)}]"
                        elif hasattr(val, "name"):
                            val_str = f" [Value: {val.name}]"
                        else:
                            val_repr = repr(val)
                            val_str = " [Value: System Type/Vector/Color]" if "bpy.data." in val_repr else f" [Value: {val_repr}]"
                    except Exception:
                        val_str = " [Value: Hidden/Internal Type]"

                lines.append(f"        {idx}. \"{inp.name}\" -> {status}{val_str}")

                if is_linked:
                    for link in links_to_socket:
                        from_lbl = link.from_node.label if link.from_node.label else "NONE"
                        wire_id = link_indices.get(link, "?")
                        error_tag = " [INVALID TYPE MISMATCH]" if not link.is_valid else ""
                        lines.append(f"           <--- (Wire #{wire_id}{error_tag}) From: [{link.from_node.name}] (Label: \"{from_lbl}\") [Socket: \"{link.from_socket.name}\"]")

        visible_outputs = [
            outp for outp in node.outputs
            if not outp.hide and not getattr(outp, "is_unavailable", False)
        ]

        if visible_outputs:
            lines.append("    Outputs:")
            for idx, outp in enumerate(node.outputs):
                if outp.hide or getattr(outp, "is_unavailable", False):
                    continue

                is_linked = outp.is_linked
                links_from_socket = [l for l in group.links if l.from_socket == outp]

                if not is_linked:
                    lines.append(f"        {idx}. \"{outp.name}\" -> FREE")
                else:
                    lines.append(f"        {idx}. \"{outp.name}\" -> LINKED")
                    for link in links_from_socket:
                        to_lbl = link.to_node.label if link.to_node.label else "NONE"
                        wire_id = link_indices.get(link, "?")
                        error_tag = " [INVALID TYPE MISMATCH]" if not link.is_valid else ""
                        try:
                            to_idx = list(link.to_node.inputs).index(link.to_socket)
                        except ValueError:
                            to_idx = "?"
                        lines.append(f"           ---> (Wire #{wire_id}{error_tag}) To: [{link.to_node.name}] (Label: \"{to_lbl}\") [Slot {to_idx}: \"{link.to_socket.name}\"]")

    for f_obj, f_data in frames.items():
        lines.append(f"\nMODULE FRAME: ======= {f_data['label'].upper()} =======")
        if not f_data['nodes']:
            lines.append("  (Empty Frame)")
        for node in f_data['nodes']:
            dump_node_log(node)

    if orphans:
        lines.append("\nUNASSIGNED ORPHAN NODES: ==============================")
        for node in orphans:
            dump_node_log(node)

    lines.append("\n================================================================================")
    return lines


def _resolve_mod_name(tree, context=None):
    mod_name = tree.name
    obj = getattr(context, "active_object", None) if context else None
    if obj:
        active_mod = next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group == tree), None)
        if active_mod:
            mod_name = active_mod.name
    return mod_name


def write_graph_snapshot(scene, group, mod_name=None, *, print_console=True, report_text=None):
    """Пишет слепок графа на диск (и опционально в консоль). Возвращает (paths, errors, report_text)."""
    if group is None:
        return [], ["нет графа"], ""

    if not mod_name:
        mod_name = group.name

    if report_text is None:
        lines = _build_graph_report(group, mod_name)
        report_text = "\n".join(lines)

    if print_console:
        print("\n" + report_text)

    safe_name = re.sub(r'[^A-Za-z0-9_.-]+', "_", group.name).strip("_") or "graph"
    filename = f"{safe_name}.txt"
    written = []
    errors = []

    for snapshots_dir in _graph_snapshot_dirs(scene):
        try:
            os.makedirs(snapshots_dir, exist_ok=True)
            file_path = os.path.join(snapshots_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            written.append(file_path)
        except Exception as e:
            errors.append(f"{snapshots_dir}: {e}")

    return written, errors, report_text


# ─── AUTO SNAPSHOT: debounce после правок Geometry Nodes ───
_AUTO_DEBOUNCE_SEC = 1.2
_auto_dirty_until = 0.0
_auto_last_hashes = {}  # node_group.name -> hash(report_text)


def _iter_open_geonode_trees():
    """Все Geometry NodeTree, открытые сейчас в Node Editor."""
    seen = set()
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        screen = getattr(window, "screen", None)
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'NODE_EDITOR':
                continue
            space = area.spaces.active
            if not space or space.tree_type != 'GeometryNodeTree':
                continue
            tree = space.edit_tree
            if not tree or tree.name in seen:
                continue
            seen.add(tree.name)
            yield tree


def _depsgraph_touched_geonodes(depsgraph):
    """True, если в апдейте есть Geometry NodeTree."""
    for update in depsgraph.updates:
        id_data = update.id
        orig = getattr(id_data, "original", id_data)
        if isinstance(orig, bpy.types.NodeTree) and getattr(orig, "type", "") == 'GEOMETRY':
            return True
    return False


def _flush_auto_graph_snapshots():
    """Таймер: ждём тишину после правок, потом тихо перезаписываем слепки."""
    global _auto_dirty_until

    remaining = _auto_dirty_until - time.time()
    if remaining > 0.05:
        return remaining

    scene = getattr(bpy.context, "scene", None)
    if not scene or not getattr(scene, "octavia_auto_graph_snapshot", True):
        return None

    # Не дёргать диск во время плейбэка анимации
    screen = getattr(bpy.context, "screen", None)
    if screen and getattr(screen, "is_animation_playing", False):
        return 0.5

    for tree in _iter_open_geonode_trees():
        try:
            mod_name = _resolve_mod_name(tree, bpy.context)
            lines = _build_graph_report(tree, mod_name)
            report_text = "\n".join(lines)
            text_hash = hash(report_text)
            if _auto_last_hashes.get(tree.name) == text_hash:
                continue

            written, errors, _ = write_graph_snapshot(
                scene, tree, mod_name, print_console=False, report_text=report_text,
            )
            _auto_last_hashes[tree.name] = text_hash
            if written:
                print(f"[Octavia] auto snapshot → {os.path.basename(written[0])}")
            elif errors:
                print(f"[Octavia] auto snapshot fail ({tree.name}): {'; '.join(errors)}")
        except Exception as e:
            print(f"[Octavia] auto snapshot error ({getattr(tree, 'name', '?')}): {e}")

    return None


@persistent
def _on_depsgraph_auto_snapshot(scene, depsgraph):
    if not getattr(scene, "octavia_auto_graph_snapshot", True):
        return
    if not _depsgraph_touched_geonodes(depsgraph):
        return
    # Есть ли вообще открытый редактор геонод — иначе нечего снимать
    if not any(True for _ in _iter_open_geonode_trees()):
        return

    global _auto_dirty_until
    _auto_dirty_until = time.time() + _AUTO_DEBOUNCE_SEC
    if not bpy.app.timers.is_registered(_flush_auto_graph_snapshots):
        bpy.app.timers.register(_flush_auto_graph_snapshots, first_interval=_AUTO_DEBOUNCE_SEC)


def register_auto_graph_snapshot():
    if _on_depsgraph_auto_snapshot not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_auto_snapshot)


def unregister_auto_graph_snapshot():
    if _on_depsgraph_auto_snapshot in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_auto_snapshot)
    if bpy.app.timers.is_registered(_flush_auto_graph_snapshots):
        bpy.app.timers.unregister(_flush_auto_graph_snapshots)
    _auto_last_hashes.clear()


class OCTAVIA_OT_snapshot_graph(bpy.types.Operator):
    """Снимает архитектурный слепок активного графа Geometry Nodes: печатает в консоль и пишет файл на диск"""
    bl_idname = "octavia.snapshot_graph"
    bl_label = "Снять слепок графа"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.tree_type == 'GeometryNodeTree'

    def execute(self, context):
        space = context.space_data
        group = space.edit_tree if space else None
        if not group:
            self.report({'WARNING'}, "Граф геонод не открыт!")
            return {'CANCELLED'}

        mod_name = _resolve_mod_name(group, context)
        written, errors, report_text = write_graph_snapshot(
            context.scene, group, mod_name, print_console=True,
        )
        _auto_last_hashes[group.name] = hash(report_text)

        if not written:
            self.report({'WARNING'}, f"Слепок в консоли, но файл не записан: {'; '.join(errors)}")
            return {'FINISHED'}

        filename = os.path.basename(written[0])
        msg = f"Слепок графа записан ({len(written)}): {filename}"
        if errors:
            msg += f" | ошибки: {'; '.join(errors)}"
            self.report({'WARNING'}, msg)
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


class OCTAVIA_OT_export_authoring_kit(bpy.types.Operator):
    """Копирует Authoring Kit в выбранную папку и запоминает путь для дубля слепков графа"""
    bl_idname = "octavia.export_authoring_kit"
    bl_label = "Папка для сессии с ИИ"
    bl_options = {'REGISTER', 'INTERNAL'}

    directory: bpy.props.StringProperty(
        name="Directory",
        subtype='DIR_PATH',
    )

    @classmethod
    def poll(cls, context):
        space = context.space_data
        return space and space.type == 'NODE_EDITOR' and space.tree_type == 'GeometryNodeTree'

    def invoke(self, context, event):
        current = (getattr(context.scene, "octavia_authoring_export_dir", "") or "").strip()
        if current and os.path.isdir(current):
            self.directory = current
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        dest = (self.directory or "").strip()
        if not dest:
            self.report({'WARNING'}, "Папка не выбрана")
            return {'CANCELLED'}

        try:
            os.makedirs(dest, exist_ok=True)
            copied = _copy_authoring_kit(dest)
        except Exception as e:
            self.report({'ERROR'}, f"Не удалось скопировать kit: {e}")
            return {'CANCELLED'}

        context.scene.octavia_authoring_export_dir = dest
        self.report({'INFO'}, f"Kit скопирован ({copied} файлов): {dest}")
        return {'FINISHED'}


class OCTAVIA_OT_rescan_macros(bpy.types.Operator):
    """Сканирует граф активного канала и запекает макросы в плоский кэш сцены"""
    bl_idname = "octavia.rescan_macros"
    bl_label = "Обновить макросы канала"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        scene = context.scene
        scene.octavia_active_macros.clear()
       
        ch_idx = scene.octavia_active_channel
       
        # 🪐 АВТОНОМНЫЙ ОПРЕДЕЛИТЕЛЬ МАТЕРИИ КАНАЛА
        obj = context.active_object
        if not (obj and obj.modifiers.get(f"Octavia Channel {ch_idx}")):
            obj = next((o for o in scene.objects if o.type == 'MESH' and o.modifiers.get(f"Octavia Channel {ch_idx}")), None)
           
        if not obj:
            return {'FINISHED'}
           
        mod = obj.modifiers.get(f"Octavia Channel {ch_idx}")
        if not mod or not mod.node_group:
            return {'FINISHED'}

        # 🧽 СВЕРХЗВУКОВАЯ АВТО-САНАЦИЯ ДАТА-МЕША (ИСПРАВЛЕННАЯ)
        buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if buf_obj and buf_obj.data:
            # 🩺 ИСЦЕЛЕНИЕ СТАРЫХ БУФЕРОВ: если буфер спрятан через hide_viewport,
            # он выпадает из depsgraph и Object Info в графе видит пустоту.
            # Возвращаем в вычисления и прячем «глазом».
            if buf_obj.hide_viewport:
                buf_obj.hide_viewport = False
                buf_obj.hide_render = True
                buf_obj.hide_select = True
                try:
                    buf_obj.hide_set(True)
                except Exception:
                    pass

            mesh = buf_obj.data
            start_attr = mesh.attributes.get("start_frame")
            end_attr = mesh.attributes.get("end_frame")
           
            if start_attr and end_attr:
                from ..vj_core import get_note_timing_curve_maps
                st_map, _, _ = get_note_timing_curve_maps(mesh, use_cache=False)
                voice_attr = mesh.attributes.get("octavia_voice_id")

                # Сбрасываем слоты без живого start>=1 (не по самому факту пустой fcurve).
                for idx in range(min(128, len(start_attr.data))):
                    st_fc = st_map.get(idx)
                    has_live_start = bool(
                        st_fc is not None
                        and any(float(k.co[1]) >= 1.0 for k in st_fc.keyframe_points)
                    )
                    if not has_live_start:
                        start_attr.data[idx].value = -1.0
                        end_attr.data[idx].value = -1.0
                        if voice_attr and idx < len(voice_attr.data):
                            voice_attr.data[idx].value = -1.0

                from ..vj_core import _clear_note_attribute_curves, buffer_has_active_note_keys
                if not buffer_has_active_note_keys(mesh):
                    _clear_note_attribute_curves(mesh)
                       
                mesh.update()
                buf_obj.update_tag()

            # 🪐 МАТРИЧНЫЙ АЛЛОКАТОР C++ СЛОЕВ МЕША (ПОТОКОВЫЙ ИНЖЕКТОР)
            expected_macro_attrs = set()
            for node in mod.node_group.nodes:
                if node.bl_idname == 'ShaderNodeValue' and node.octavia_macro.is_macro:
                    attr_name = f"oc_m_{node.name}"
                    expected_macro_attrs.add(attr_name)
                    
                    # Если C++ слоя под этот макрос ещё нет в меше — рождаем его на лету
                    if attr_name not in mesh.attributes:
                        mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')

            # 🧽 АНТИ-МУСОРНАЯ САНАЦИЯ: Безопасно стираем из VRAM слои удаленных макросов
            for attr in list(mesh.attributes):
                if attr.name.startswith("oc_m_") and attr.name not in expected_macro_attrs:
                    mesh.attributes.remove(attr)
            
            mesh.update()
            buf_obj.update_tag()

        # Физическое запекание макросов в кэш сцены
        for node in mod.node_group.nodes:

            if node.bl_idname == 'ShaderNodeValue':
                macro_settings = node.octavia_macro
                if macro_settings.is_macro:
                    item = scene.octavia_active_macros.add()
                    item.node_name = node.name
                    item.friendly_name = macro_settings.friendly_name if macro_settings.friendly_name else node.name
                    item.category = macro_settings.category
                    item.min_value = macro_settings.min_value
                    item.max_value = macro_settings.max_value
                    item.description = macro_settings.description
                   
        return {'FINISHED'}
