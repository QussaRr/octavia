"""Длина echo-хвоста на таймлайне из секторов UI макросов (ECHO / HOLD)."""


def macro_looks_like_return_speed(macro_settings):
    """ECHO-ручка «скорость» (POLY_TEST), а не длительность в кадрах."""
    if not macro_settings:
        return False
    return float(getattr(macro_settings, "max_value", 1.0)) <= 2.0


def scan_graph_echo_macros(node_group):
    """Секторы UI графа: ECHO / HOLD + legacy DECAY по имени ноды."""
    decay_seconds = None
    echo_frame_nodes = []
    echo_speed_nodes = []
    hold_nodes = []

    if not node_group:
        return decay_seconds, echo_frame_nodes, echo_speed_nodes, hold_nodes

    for n in node_group.nodes:
        if n.bl_idname != 'ShaderNodeValue':
            continue
        macro = getattr(n, "octavia_macro", None)
        friendly = (getattr(macro, "friendly_name", "") or "").upper() if macro else ""
        name_u = n.name.upper()
        label_u = (n.label or "").upper()
        if "DECAY" in name_u or "DECAY" in label_u or "DECAY" in friendly:
            try:
                decay_seconds = n.outputs[0].default_value
            except Exception:
                pass
        if not macro or not getattr(macro, "is_macro", False):
            continue
        cat = getattr(macro, "category", "")
        if cat == 'ECHO':
            if macro_looks_like_return_speed(macro):
                echo_speed_nodes.append(n.name)
            else:
                echo_frame_nodes.append(n.name)
        elif cat == 'HOLD':
            hold_nodes.append(n.name)

    if not echo_speed_nodes and not echo_frame_nodes:
        if node_group.nodes.get("ReturnSpeed"):
            rs = node_group.nodes["ReturnSpeed"]
            rs_macro = getattr(rs, "octavia_macro", None)
            if rs_macro and getattr(rs_macro, "is_macro", False):
                echo_speed_nodes.append("ReturnSpeed")
        if node_group.nodes.get("Offset"):
            off = node_group.nodes["Offset"]
            off_macro = getattr(off, "octavia_macro", None)
            if off_macro and getattr(off_macro, "is_macro", False):
                hold_nodes.append("Offset")

    return decay_seconds, echo_frame_nodes, echo_speed_nodes, hold_nodes


def ghost_frames_for_voice(
    hw_id, fps, ghost_group, ch_idx, scene,
    decay_seconds, echo_frame_nodes, echo_speed_nodes, hold_nodes,
):
    """Сколько кадров echo рисовать после конца тела ноты."""
    if decay_seconds is not None:
        return max(0.0, decay_seconds * fps)

    def voice_macro(node_name, fallback=0.0):
        if not node_name:
            return fallback
        ch_data_g = scene.octavia_channels_data[ch_idx - 1] if len(scene.octavia_channels_data) >= ch_idx else None
        if ch_data_g:
            voice = next((v for v in ch_data_g.voices if v.hardware_id == hw_id), None)
            if voice:
                ov = voice.macro_overrides.get(node_name)
                if ov:
                    return ov.value
        if ghost_group:
            node = ghost_group.nodes.get(node_name)
            if node and node.outputs:
                try:
                    return node.outputs[0].default_value
                except Exception:
                    pass
        return fallback

    if echo_frame_nodes:
        return max(0.0, voice_macro(echo_frame_nodes[0], 0.0))

    if echo_speed_nodes and hold_nodes:
        dist = abs(voice_macro(hold_nodes[0], 0.0))
        speed = max(0.01, voice_macro(echo_speed_nodes[0], 0.01))
        return (dist / speed) * fps

    if len(echo_speed_nodes) == 1:
        return max(0.0, voice_macro(echo_speed_nodes[0], 0.0))

    return 0.0


def echo_trail_context_for_channel(scene, ch_idx):
    """Кэш макросов echo для канала (для отрисовки превью вставки)."""
    ch_mesh = next(
        (o for o in scene.objects if o.type == 'MESH' and o.modifiers.get(f"Octavia Channel {ch_idx}")),
        None,
    )
    if not ch_mesh:
        return None
    mod = ch_mesh.modifiers.get(f"Octavia Channel {ch_idx}")
    if not mod or not mod.node_group:
        return None
    decay, ef, es, hn = scan_graph_echo_macros(mod.node_group)
    return mod.node_group, decay, ef, es, hn


def hardware_id_for_voice_floor(scene, ch_idx, voice_floor_idx):
    ch_data = scene.octavia_channels_data[ch_idx - 1] if len(scene.octavia_channels_data) >= ch_idx else None
    if ch_data and 0 <= voice_floor_idx < len(ch_data.voices):
        return ch_data.voices[voice_floor_idx].hardware_id
    return 0
