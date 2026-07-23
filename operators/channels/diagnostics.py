import bpy
import os
import re
import shutil


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

        mod_name = group.name
        obj = context.active_object
        if obj:
            active_mod = next((m for m in obj.modifiers if m.type == 'NODES' and m.node_group == group), None)
            if active_mod:
                mod_name = active_mod.name

        lines = _build_graph_report(group, mod_name)
        report_text = "\n".join(lines)

        print("\n" + report_text)

        safe_name = re.sub(r'[^A-Za-z0-9_.-]+', "_", group.name).strip("_") or "graph"
        filename = f"{safe_name}.txt"
        written = []
        errors = []

        for snapshots_dir in _graph_snapshot_dirs(context.scene):
            try:
                os.makedirs(snapshots_dir, exist_ok=True)
                file_path = os.path.join(snapshots_dir, filename)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(report_text)
                written.append(file_path)
            except Exception as e:
                errors.append(f"{snapshots_dir}: {e}")

        if not written:
            self.report({'WARNING'}, f"Слепок в консоли, но файл не записан: {'; '.join(errors)}")
            return {'FINISHED'}

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


class OCTAVIA_OT_snapshot_buffer(bpy.types.Operator):
    """Снимает слепок меш-буфера активного канала (сырые + вычисленные данные) в файл для ИИ"""
    bl_idname = "octavia.snapshot_buffer"
    bl_label = "Снять слепок буфера"
    bl_options = {'REGISTER', 'INTERNAL'}

    def _attr_val(self, m, name, idx):
        a = m.attributes.get(name)
        if not a or idx >= len(a.data):
            return None
        return a.data[idx].value

    def execute(self, context):
        scene = context.scene
        ch_idx = scene.octavia_active_channel
        buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)

        lines = []
        lines.append(f"================== OCTAVIA BUFFER SNAPSHOT (Channel {ch_idx}) ==================")
        lines.append(f"Scene frame_current: {scene.frame_current} | fps: {scene.render.fps}")

        if not buf_obj or not buf_obj.data:
            lines.append(f"!!! Буфер '{buf_name}' не найден в сцене.")
            self._write(ch_idx, lines)
            self.report({'WARNING'}, f"Буфер канала {ch_idx} не найден")
            return {'FINISHED'}

        mesh = buf_obj.data
        attr_names = [a.name for a in mesh.attributes]
        lines.append(f"Buffer object: {buf_obj.name} | mesh: {mesh.name} | verts(raw): {len(mesh.vertices)}")
        lines.append(f"  hide_viewport={buf_obj.hide_viewport} hide_render={buf_obj.hide_render} hide_eye={buf_obj.hide_get()}")
        lines.append(f"  Attributes: {attr_names}")

        # Проверяем, сколько объектов с таким именем существует (дубликаты .001 — частый источник багов)
        dup_objs = [o.name for o in bpy.data.objects if o.name.startswith(buf_name)]
        lines.append(f"  Объекты с похожим именем в .blend: {dup_objs}")

        # --- ГРАФ КАНАЛА И ЦЕЛИ OBJECT INFO ---
        lines.append("\n--- ГРАФ КАНАЛА И ЦЕЛИ OBJECT INFO (главный подозреваемый) ---")
        found_graph = False
        for obj in scene.objects:
            mod = obj.modifiers.get(f"Octavia Channel {ch_idx}")
            if mod and mod.node_group:
                found_graph = True
                lines.append(f"  Объект '{obj.name}': модификатор '{mod.name}' -> граф '{mod.node_group.name}' (show_viewport={mod.show_viewport})")
                for node in mod.node_group.nodes:
                    if node.bl_idname == 'GeometryNodeObjectInfo':
                        tgt = node.inputs[0].default_value if node.inputs else None
                        tgt_name = tgt.name if tgt else "None"
                        match = "OK" if tgt_name == buf_name else "!!! НЕ СОВПАДАЕТ С БУФЕРОМ КАНАЛА !!!"
                        lines.append(f"      Object Info '{node.name}' -> target: '{tgt_name}'  [{match}]")
        if not found_graph:
            lines.append(f"  (На канале {ch_idx} не найдено объекта с графом 'Octavia Channel {ch_idx}')")

        # --- ГОЛОСА ---
        lines.append("\n--- КОНФИГУРАЦИЯ ГОЛОСОВ ---")
        if len(scene.octavia_channels_data) >= ch_idx:
            ch_data = scene.octavia_channels_data[ch_idx - 1]
            for i, v in enumerate(ch_data.voices):
                ov = ", ".join(f"{o.macro_id}={round(o.value, 3)}" for o in v.macro_overrides) or "нет"
                lines.append(f"  Voice {i}: key='{v.key_code}' hw_id={v.hardware_id} punch={round(v.punch, 3)} hold={round(v.hold, 3)} echo={round(v.echo, 3)} | overrides: {ov}")

        macro_attrs = [n for n in attr_names if n.startswith("oc_m_")] + ["octavia_macro_punch", "octavia_macro_hold", "octavia_macro_echo"]

        def dump_region(m, tag):
            lines.append(f"\n--- {tag}: КОНФИГ-ВЕРШИНЫ (128-159), непустые ---")
            for idx in range(128, min(160, len(m.vertices))):
                vals = []
                for mn in macro_attrs:
                    val = self._attr_val(m, mn, idx)
                    if val is None:
                        continue
                    # Пользовательские макросы (oc_m_*) показываем ВСЕГДА, даже нулевые:
                    # нулевой oc_m_* — частая причина «граф есть, привязка ОК, а движения нет».
                    if mn.startswith("oc_m_") or abs(val) > 1e-9:
                        vals.append(f"{mn}={round(val, 4)}")
                if vals:
                    lines.append(f"  Vertex {idx} (hw {idx - 128}): {', '.join(vals)}")
            lines.append(f"--- {tag}: СЛОТЫ НОТ (0-127), активные (start>=1) ---")
            any_slot = False
            for idx in range(min(128, len(m.vertices))):
                st = self._attr_val(m, "start_frame", idx)
                en = self._attr_val(m, "end_frame", idx)
                vid = self._attr_val(m, "octavia_voice_id", idx)
                if st is not None and st >= 1.0:
                    any_slot = True
                    lines.append(f"  Slot {idx}: start={st} end={en} voice_id={vid}")
            if not any_slot:
                lines.append("  (нет активных слотов)")

        dump_region(mesh, "СЫРЫЕ ДАННЫЕ (original mesh)")

        # Вычисленные данные — то, что реально читает Object Info графа
        try:
            depsgraph = context.evaluated_depsgraph_get()
            buf_eval = buf_obj.evaluated_get(depsgraph)
            mesh_eval = buf_eval.data
            lines.append(f"\n=== ВЫЧИСЛЕННЫЕ ДАННЫЕ @ frame {scene.frame_current} (это видит граф) ===")
            lines.append(f"  eval verts: {len(mesh_eval.vertices)} | eval attrs: {[a.name for a in mesh_eval.attributes]}")
            dump_region(mesh_eval, "ВЫЧИСЛЕННЫЕ")
        except Exception as e:
            lines.append(f"\n[Ошибка чтения вычисленных данных: {e}]")

        # --- АНИМАЦИЯ ---
        lines.append("\n--- АНИМАЦИОННЫЕ КРИВЫЕ БУФЕРА ---")
        if mesh.animation_data and mesh.animation_data.action:
            act = mesh.animation_data.action
            curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
            if hasattr(act, "layers"):
                for layer in act.layers:
                    for strip in getattr(layer, "strips", []):
                        for bag in getattr(strip, "channelbags", []):
                            curves.extend(getattr(bag, "fcurves", []))
            lines.append(f"  Action: {act.name} | кривых: {len(curves)}")
            for fc in curves:
                if not hasattr(fc, "data_path"):
                    continue
                keys = [(round(k.co[0], 1), round(k.co[1], 3), k.interpolation) for k in fc.keyframe_points]
                lines.append(f"  {fc.data_path}: {keys}")
        else:
            lines.append("  (Нет анимации на буфере)")

        lines.append("\n================================================================================")
        self._write(ch_idx, lines)
        self.report({'INFO'}, f"Слепок буфера канала {ch_idx} записан")
        return {'FINISHED'}

    def _write(self, ch_idx, lines):
        report_text = "\n".join(lines)
        print("\n" + report_text)
        addon_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        snapshots_dir = os.path.join(addon_dir, "buffer_snapshots")
        try:
            os.makedirs(snapshots_dir, exist_ok=True)
            file_path = os.path.join(snapshots_dir, f"Buffer_Ch_{ch_idx}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_text)
        except Exception as e:
            print(f"[Octavia] Не удалось записать слепок буфера: {e}")


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
                active_start_slots = set()
                active_end_slots = set()
               
                if buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                    from ..vj_core import iter_action_fcurves
                    import re
                    for fc in iter_action_fcurves(buf_obj.data.animation_data.action):
                        if not hasattr(fc, "data_path") or not fc.keyframe_points:
                            continue
                        m = re.search(r"data\[(\d+)\]", fc.data_path)
                        if not m:
                            continue
                        idx = int(m.group(1))
                        if "start_frame" in fc.data_path:
                            active_start_slots.add(idx)
                        elif "end_frame" in fc.data_path:
                            active_end_slots.add(idx)
               
                # Сбрасываем только полностью пустые слоты (без f-кривых).
                # Нельзя трогать end на слотах с ключами — иначе RELEASE режет все блоки.
                for idx in range(min(128, len(start_attr.data))):
                    if idx not in active_start_slots and idx not in active_end_slots:
                        start_attr.data[idx].value = -1.0
                        end_attr.data[idx].value = -1.0
                       
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