import bpy
import sys

# ─── ЕДИНЫЙ КВАНТОВЫЙ ХРОНОМЕТР OCTAVIA ───
def frame_to_time(frame, fps):
    return (frame - 1) / fps

def time_to_frame(sec, fps):
    return sec * fps + 1

def quantize_time_to_playhead(sec, fps):
    """Секунды мыши → ближайший кадр и секунды, на которых реально стоит плейхед."""
    frame = max(1, int(round(time_to_frame(sec, fps))))
    return frame_to_time(frame, fps), frame


def music_step_seconds(bpm, pixels_per_second):
    """Шаг SNAP = видимый шаг сетки канала (16th / beat / bar по зуму).

    Пороги совпадают с interface/grid.py (show_steps / show_beats).
    """
    seconds_per_beat = 60.0 / max(1.0, float(bpm))
    seconds_per_16th = seconds_per_beat / 4.0
    step_px = seconds_per_16th * max(1e-6, float(pixels_per_second))
    if step_px >= 14.0:
        return seconds_per_16th
    if (step_px * 4.0) >= 8.0:
        return seconds_per_beat
    return seconds_per_beat * 4.0


def adaptive_snap_seconds(sec, bpm, pixels_per_second):
    """Секунды → ближайшая видимая линия музыкальной сетки (ровный шаг, без frame-jitter)."""
    step = music_step_seconds(bpm, pixels_per_second)
    if step <= 0.0:
        return max(0.0, float(sec))
    step_idx = int(round(float(sec) / step))
    return max(0.0, step_idx * step)


def snap_frame_to_grid(raw_frame, bpm, fps, pixels_per_second):
    """Кадр → ближайшая линия сетки (та же, что рисует channel grid)."""
    fps = max(1e-6, float(fps))
    sec = frame_to_time(raw_frame, fps)
    snapped_sec = adaptive_snap_seconds(sec, bpm, pixels_per_second)
    return max(1, int(round(time_to_frame(snapped_sec, fps))))


def snap_frame_for_daw_mouse(raw_frame, scene, fps, pixels_per_second, target_ch=-1):
    """SNAP мыши + магнит к началу зоны тайминга исходного грува (кросс-канал paste)."""
    fps = max(1e-6, float(fps))
    pps = max(1e-6, float(pixels_per_second))
    raw = float(raw_frame)

    if not getattr(scene, "octavia_snap", True):
        return max(1, int(round(raw)))

    src_min = float(getattr(sys, "_octavia_clipboard_source_min_frame", -1.0) or -1.0)
    source_ch = int(getattr(sys, "_octavia_clipboard_source_ch", -1) or -1)
    has_clip = bool(getattr(sys, "_octavia_clipboard", None))
    cross = (
        has_clip
        and source_ch >= 1
        and int(target_ch) >= 1
        and int(target_ch) != source_ch
        and src_min >= 1.0
    )

    if cross:
        # Начало зоны = доп. линия сетки (~12 UI-px магнит)
        magnet_frames = max(1.0, (12.0 / pps) * fps)
        if abs(raw - src_min) <= magnet_frames:
            return max(1, int(round(src_min)))

    return snap_frame_to_grid(raw, scene.octavia_bpm, fps, pps)


def daw_pixels_per_second(scene):
    return 50.0 * float(getattr(scene, "octavia_zoom", 1.0))


def iter_action_fcurves(action):
    """Все fcurves экшена, включая раскладку Blender 5.1 (layers/strips/channelbags)."""
    return [fc for fc, _owner in iter_action_fcurves_with_owners(action)]


def iter_action_fcurves_with_owners(action):
    """(fcurve, owner_collection) — owner нужен, чтобы удалять кривые целиком."""
    pairs = []
    if action is None:
        return pairs
    top = getattr(action, "fcurves", None) or getattr(action, "curves", None)
    if top is not None:
        for fc in top:
            pairs.append((fc, top))
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in getattr(layer, "strips", []):
                for bag in getattr(strip, "channelbags", []):
                    bag_fcs = getattr(bag, "fcurves", None)
                    if bag_fcs is None:
                        continue
                    for fc in bag_fcs:
                        pairs.append((fc, bag_fcs))
    return pairs


import re as _re_attr

# attributes["name"].data[N] — quote-agnostic, точный индекс (не substring data[1]⊂data[10])
_ATTR_DATA_PATH_RE = _re_attr.compile(
    r'attributes\[[\'"]([^\'"]+)[\'"]\]\.data\[(\d+)\]'
)

# Лёгкий кэш карт кривых для DAW draw / radar (инвалидация по len(fcurves))
_note_timing_maps_cache = {}


def safe_fcurve_data_path(fc):
    """data_path fcurve или None, если RNA/байты битые (после OOM/порчи Action)."""
    if fc is None:
        return None
    try:
        dp = getattr(fc, "data_path", None)
    except (UnicodeDecodeError, UnicodeError, RuntimeError, ReferenceError, TypeError):
        return None
    if dp is None:
        return None
    try:
        # иногда приходит bytes / битая str
        if isinstance(dp, bytes):
            dp = dp.decode("utf-8", errors="replace")
        else:
            dp = str(dp)
    except Exception:
        return None
    return dp


def parse_attribute_data_path(data_path):
    """(attr_name, vert_index) или (None, None)."""
    try:
        m = _ATTR_DATA_PATH_RE.search(data_path or "")
    except (UnicodeDecodeError, TypeError):
        return None, None
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def path_vert_index(data_path):
    _, idx = parse_attribute_data_path(data_path)
    return idx


def clear_note_timing_maps_cache():
    _note_timing_maps_cache.clear()


def get_note_timing_curve_maps(mesh=None, action=None, use_cache=True):
    """
    Один проход по Action → (start_curves, end_curves, voice_curves).
    Только зона нот 0–127 (залп 160+ не попадает в DAW/radar как «ноты»).
    """
    act = action
    if act is None and mesh is not None:
        if not (mesh.animation_data and mesh.animation_data.action):
            return {}, {}, {}
        act = mesh.animation_data.action
    if act is None:
        return {}, {}, {}

    fcs = iter_action_fcurves(act)
    cache_key = None
    if use_cache and mesh is not None:
        try:
            cache_key = (mesh.as_pointer(), act.as_pointer(), len(fcs))
            hit = _note_timing_maps_cache.get(cache_key)
            if hit is not None:
                return hit
        except Exception:
            cache_key = None

    start_curves, end_curves, voice_curves = {}, {}, {}
    for fc in fcs:
        name, idx = parse_attribute_data_path(safe_fcurve_data_path(fc))
        if name is None or not is_note_slot_index(idx):
            continue
        if name == "start_frame":
            start_curves[idx] = fc
        elif name == "end_frame":
            end_curves[idx] = fc
        elif name == "octavia_voice_id":
            voice_curves[idx] = fc

    maps = (start_curves, end_curves, voice_curves)
    if cache_key is not None:
        if len(_note_timing_maps_cache) > 48:
            _note_timing_maps_cache.clear()
        _note_timing_maps_cache[cache_key] = maps
    return maps


def slot_latest_key_time(mesh, slot_idx):
    """Последний кадр (co[0]) любого ключа start/end/voice на этом слоте."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return -1.0
    slot_idx = int(slot_idx)
    latest = -1.0
    for fc in iter_action_fcurves(mesh.animation_data.action):
        name, idx = parse_attribute_data_path(getattr(fc, "data_path", None))
        if idx != slot_idx or name not in ("start_frame", "end_frame", "octavia_voice_id"):
            continue
        for kp in fc.keyframe_points:
            latest = max(latest, kp.co[0])
    return latest


def slot_is_free_before(mesh, slot_idx, target_frame):
    """Слот можно переиспользовать, если все его ключи строго ДО нового удара."""
    return slot_latest_key_time(mesh, slot_idx) < float(target_frame) - 0.1


def get_note_body_duration_frames(mesh, slot_idx, start_frame, fps=24):
    """Длина тела ноты (hold): start → release. Echo в буфер не входит."""
    fallback = max(2, int(round(0.5 * fps)))
    if not mesh or not mesh.animation_data or not mesh.animation_data.action:
        return fallback

    start_curves, end_curves, _voice = get_note_timing_curve_maps(mesh, use_cache=False)
    fc_start = start_curves.get(int(slot_idx))
    fc_end = end_curves.get(int(slot_idx))

    next_hit_frame = float("inf")
    if fc_start and fc_start.keyframe_points:
        kps_st = sorted(k.co[1] for k in fc_start.keyframe_points if k.co[1] >= 1.0)
        try:
            f_idx = next(i for i, f in enumerate(kps_st) if abs(f - float(start_frame)) < 0.1)
            if f_idx + 1 < len(kps_st):
                next_hit_frame = kps_st[f_idx + 1]
        except StopIteration:
            pass

    if fc_end:
        start_f = float(start_frame)
        kp_end = next(
            (
                k for k in fc_end.keyframe_points
                if start_f <= k.co[0] < next_hit_frame and k.co[1] >= start_f
            ),
            None,
        )
        if kp_end:
            return max(2, int(round(kp_end.co[1] - start_f)))

    return fallback


def fcurve_slot_value(mesh, slot_idx, attr_name, frame):
    """Значение атрибута слота на кадре frame (из f-кривой, не сырой вершины)."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return None
    data_path = f'attributes["{attr_name}"].data[{int(slot_idx)}].value'
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if getattr(fc, "data_path", None) == data_path:
            return fc.evaluate(frame)
    # Blender иногда пишет одинарные кавычки — fallback через парсер
    for fc in iter_action_fcurves(mesh.animation_data.action):
        name, idx = parse_attribute_data_path(getattr(fc, "data_path", None))
        if name == attr_name and idx == int(slot_idx):
            return fc.evaluate(frame)
    return None


def _index_note_timing_fcurves(mesh):
    """Один проход → {slot: {start_frame/end_frame/octavia_voice_id: fc}}. Зона А."""
    start_c, end_c, voice_c = get_note_timing_curve_maps(mesh, use_cache=True)
    out = {}
    for idx, fc in start_c.items():
        out.setdefault(idx, {})["start_frame"] = fc
    for idx, fc in end_c.items():
        out.setdefault(idx, {})["end_frame"] = fc
    for idx, fc in voice_c.items():
        out.setdefault(idx, {})["octavia_voice_id"] = fc
    return out

def quantize_time_to_playhead(sec, fps):
    """Секунды мыши → ближайший кадр и секунды, на которых реально стоит плейхед."""
    frame = max(1, int(round(time_to_frame(sec, fps))))
    return frame_to_time(frame, fps), frame


def music_step_seconds(bpm, pixels_per_second):
    """Шаг SNAP = видимый шаг сетки канала (16th / beat / bar по зуму).

    Пороги совпадают с interface/grid.py (show_steps / show_beats).
    """
    seconds_per_beat = 60.0 / max(1.0, float(bpm))
    seconds_per_16th = seconds_per_beat / 4.0
    step_px = seconds_per_16th * max(1e-6, float(pixels_per_second))
    if step_px >= 14.0:
        return seconds_per_16th
    if (step_px * 4.0) >= 8.0:
        return seconds_per_beat
    return seconds_per_beat * 4.0


def adaptive_snap_seconds(sec, bpm, pixels_per_second):
    """Секунды → ближайшая видимая линия музыкальной сетки (ровный шаг, без frame-jitter)."""
    step = music_step_seconds(bpm, pixels_per_second)
    if step <= 0.0:
        return max(0.0, float(sec))
    step_idx = int(round(float(sec) / step))
    return max(0.0, step_idx * step)


def snap_frame_to_grid(raw_frame, bpm, fps, pixels_per_second):
    """Кадр → ближайшая линия сетки (та же, что рисует channel grid)."""
    fps = max(1e-6, float(fps))
    sec = frame_to_time(raw_frame, fps)
    snapped_sec = adaptive_snap_seconds(sec, bpm, pixels_per_second)
    return max(1, int(round(time_to_frame(snapped_sec, fps))))


def daw_pixels_per_second(scene):
    return 50.0 * float(getattr(scene, "octavia_zoom", 1.0))


def iter_action_fcurves(action):
    """Все fcurves экшена, включая раскладку Blender 5.1 (layers/strips/channelbags)."""
    return [fc for fc, _owner in iter_action_fcurves_with_owners(action)]


def iter_action_fcurves_with_owners(action):
    """(fcurve, owner_collection) — owner нужен, чтобы удалять кривые целиком."""
    pairs = []
    if action is None:
        return pairs
    top = getattr(action, "fcurves", None) or getattr(action, "curves", None)
    if top is not None:
        for fc in top:
            pairs.append((fc, top))
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in getattr(layer, "strips", []):
                for bag in getattr(strip, "channelbags", []):
                    bag_fcs = getattr(bag, "fcurves", None)
                    if bag_fcs is None:
                        continue
                    for fc in bag_fcs:
                        pairs.append((fc, bag_fcs))
    return pairs


def slot_latest_key_time(mesh, slot_idx):
    """Последний кадр (co[0]) любого ключа start/end/voice на этом слоте."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return -1.0
    needle = f"[{slot_idx}]"
    latest = -1.0
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if not hasattr(fc, "data_path") or needle not in fc.data_path:
            continue
        if "attributes[" not in fc.data_path:
            continue
        for kp in fc.keyframe_points:
            latest = max(latest, kp.co[0])
    return latest


def slot_is_free_before(mesh, slot_idx, target_frame):
    """Слот можно переиспользовать, если все его ключи строго ДО нового удара."""
    return slot_latest_key_time(mesh, slot_idx) < float(target_frame) - 0.1


def get_note_body_duration_frames(mesh, slot_idx, start_frame, fps=24):
    """Длина тела ноты (hold): start → release. Echo в буфер не входит."""
    fallback = max(2, int(round(0.5 * fps)))
    if not mesh or not mesh.animation_data or not mesh.animation_data.action:
        return fallback

    st_path = f'attributes["start_frame"].data[{slot_idx}].value'
    end_path = f'attributes["end_frame"].data[{slot_idx}].value'
    fc_start = fc_end = None
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if not hasattr(fc, "data_path"):
            continue
        if st_path in fc.data_path:
            fc_start = fc
        elif end_path in fc.data_path:
            fc_end = fc

    next_hit_frame = float("inf")
    if fc_start and fc_start.keyframe_points:
        kps_st = sorted(k.co[1] for k in fc_start.keyframe_points if k.co[1] >= 1.0)
        try:
            f_idx = next(i for i, f in enumerate(kps_st) if abs(f - float(start_frame)) < 0.1)
            if f_idx + 1 < len(kps_st):
                next_hit_frame = kps_st[f_idx + 1]
        except StopIteration:
            pass

    if fc_end:
        start_f = float(start_frame)
        kp_end = next(
            (
                k for k in fc_end.keyframe_points
                if start_f <= k.co[0] < next_hit_frame and k.co[1] >= start_f
            ),
            None,
        )
        if kp_end:
            return max(2, int(round(kp_end.co[1] - start_f)))

    return fallback


def fcurve_slot_value(mesh, slot_idx, attr_name, frame):
    """Значение атрибута слота на кадре frame (из f-кривой, не сырой вершины)."""
    if not mesh.animation_data or not mesh.animation_data.action:
        return None
    data_path = f'attributes["{attr_name}"].data[{slot_idx}].value'
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if hasattr(fc, "data_path") and data_path in fc.data_path:
            return fc.evaluate(frame)
    return None

# 🛰️ СВЕРХТОЧНЫЙ ТЕЛЕМЕТРИЧЕСКИЙ ЗОНД СТЕКА ИСТОРИИ ОКТАВИИ

def capture_daw_snapshot(context, target_channels):
    import sys
    scene = context.scene

    snapshot = {
        'channels': {},
        'selected_blocks': [item.name for item in scene.octavia_selected_blocks],
        'virtual_erased': list(getattr(sys, "_octavia_virtual_erased", set()))
    }

    # 🪐 ЗОНД ИСТОРИИ: Запекаем текущее положение ползунков всех голосов в слепок
    snapshot['voices_props'] = {}
    if hasattr(scene, "octavia_channels_data"):
        for c_idx, ch_data in enumerate(scene.octavia_channels_data, start=1):
            ch_v_list = []
            for v in ch_data.voices:
                ch_v_list.append({
                    'punch': v.punch, 'hold': v.hold, 'echo': v.echo,
                    'macro_overrides': [{"macro_id": mo.macro_id, "value": mo.value} for mo in v.macro_overrides],
                    'key_code': v.key_code, 'name': v.name
                })
            snapshot['voices_props'][c_idx] = ch_v_list
   
    for ch in target_channels:
        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if not buf_obj or not buf_obj.data:
            snapshot['channels'][ch] = {}
            continue
            
        if not (buf_obj.data.animation_data and buf_obj.data.animation_data.action):
            # Пустой канал тоже фиксируем — иначе undo после paste на пустой дорожке
            # не сотрёт вставленные ноты.
            snapshot['channels'][ch] = {}
            continue
           
        act = buf_obj.data.animation_data.action
        curves = list(iter_action_fcurves(act))
                        
        ch_curves_backup = {}
        for fc in curves:
            if hasattr(fc, "data_path") and _is_note_attr_path(fc.data_path):
                kps_data = [(kp.co[0], kp.co[1], kp.interpolation) for kp in fc.keyframe_points]
                # array_index обязателен для FLOAT_VECTOR (3 fcurve на один path)
                key = _curve_snapshot_key(fc.data_path, getattr(fc, "array_index", 0) or 0)
                ch_curves_backup[key] = kps_data
                
        snapshot['channels'][ch] = ch_curves_backup
       
    return snapshot

_NOTE_ATTR_MARKERS = (
    "start_frame",
    "end_frame",
    "octavia_voice_id",
    "hit_position",
    "hit_normal",
    "burst_position",
    "burst_normal",
    "burst_sub_index",
)
_HIT_VECTOR_ATTRS = frozenset({"hit_position", "hit_normal"})
_BURST_VECTOR_ATTRS = frozenset({"burst_position", "burst_normal"})
_VECTOR_NOTE_ATTRS = _HIT_VECTOR_ATTRS | _BURST_VECTOR_ATTRS
_SCALAR_NOTE_ATTRS = frozenset({
    "start_frame", "end_frame", "octavia_voice_id", "burst_sub_index",
})

# Детерминированная Сальво-Матрица: 0–127 ноты, 128–159 голоса, 160–2207 залпы
NOTE_SLOT_COUNT = 128
VOICE_ZONE_START = 128
VOICE_ZONE_COUNT = 32
SALVO_BASE = 160
SALVO_STRIDE = 16  # частиц на нотный слот
SALVO_SLOT_COUNT = NOTE_SLOT_COUNT
BUFFER_VERT_COUNT = SALVO_BASE + SALVO_SLOT_COUNT * SALVO_STRIDE  # 2208
BURST_COUNT_ATTR = "oc_m_burst_count"
BURST_COUNT_MAX = SALVO_STRIDE


def clamp_macro_buffer_value(node_or_attr_name, value):
    """Потолок только там, где упираемся в топологию буфера (залп ≤16).

    KickColCount / Count НЕ режем здесь: автор хочет десятки/сотни пластинок.
    Стоимость GN (DUP × сетка × Realize) — зона графа, не молчаливый clamp UI.
    """
    raw = float(value)
    key = (node_or_attr_name or "").strip()
    if key.startswith("oc_m_"):
        key = key[5:]
    low = key.lower().replace(" ", "")
    if low in ("burst_count", "burstcount"):
        return max(0.0, min(float(BURST_COUNT_MAX), raw))
    return raw


def salvo_vert_index(slot_idx, particle_idx):
    return SALVO_BASE + int(slot_idx) * SALVO_STRIDE + int(particle_idx)


def is_note_slot_index(idx):
    """Зона А: только 0–127. Зона В (залп) пишет start_frame, но это не нотные слоты UI."""
    return 0 <= int(idx) < NOTE_SLOT_COUNT


def _is_note_attr_path(data_path):
    try:
        if not data_path or "attributes[" not in data_path:
            return False
        return any(m in data_path for m in _NOTE_ATTR_MARKERS)
    except (UnicodeDecodeError, TypeError):
        return False


def _parse_note_attr_path(data_path):
    """attributes["name"].data[i].value|.vector → (name, i)."""
    import re
    m = re.search(r'attributes\[[\'"]([^\'"]+)[\'"]\]\.data\[(\d+)\]', data_path or "")
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def _curve_snapshot_key(data_path, array_index):
    """Ключ слепка Undo: путь + array_index (нужно для FLOAT_VECTOR)."""
    return f"{data_path}@@{int(array_index)}"


def _split_curve_snapshot_key(key):
    if "@@" in key:
        path, idx_s = key.rsplit("@@", 1)
        try:
            return path, int(idx_s)
        except ValueError:
            return key, 0
    return key, 0


def ensure_hit_snapshot_attrs(mesh):
    """Создаёт hit_position / hit_normal (FLOAT_VECTOR) если их нет. Возвращает True если создал."""
    created = False
    for attr_name in _HIT_VECTOR_ATTRS:
        attr = mesh.attributes.get(attr_name)
        if attr is None:
            attr = mesh.attributes.new(name=attr_name, type='FLOAT_VECTOR', domain='POINT')
            for d in attr.data:
                d.vector = (0.0, 0.0, 0.0)
            created = True
            continue
        # Старый/битый слой неверного типа — пересоздаём
        data_type = getattr(attr, "data_type", None) or getattr(attr, "type", None)
        if data_type and data_type != 'FLOAT_VECTOR':
            try:
                mesh.attributes.remove(attr)
            except Exception:
                pass
            attr = mesh.attributes.new(name=attr_name, type='FLOAT_VECTOR', domain='POINT')
            for d in attr.data:
                d.vector = (0.0, 0.0, 0.0)
            created = True
    return created


def ensure_burst_attrs(mesh):
    """Слои Сальво-Матрицы: burst_position / burst_normal / burst_sub_index."""
    created = False
    for attr_name in _BURST_VECTOR_ATTRS:
        attr = mesh.attributes.get(attr_name)
        if attr is None:
            attr = mesh.attributes.new(name=attr_name, type='FLOAT_VECTOR', domain='POINT')
            for d in attr.data:
                d.vector = (0.0, 0.0, 0.0)
            created = True
        else:
            data_type = getattr(attr, "data_type", None) or getattr(attr, "type", None)
            if data_type and data_type != 'FLOAT_VECTOR':
                try:
                    mesh.attributes.remove(attr)
                except Exception:
                    pass
                attr = mesh.attributes.new(name=attr_name, type='FLOAT_VECTOR', domain='POINT')
                for d in attr.data:
                    d.vector = (0.0, 0.0, 0.0)
                created = True
    sub = mesh.attributes.get("burst_sub_index")
    if sub is None:
        sub = mesh.attributes.new(name="burst_sub_index", type='FLOAT', domain='POINT')
        for d in sub.data:
            d.value = -1.0
        created = True
    return created


def ensure_buffer_topology(mesh):
    """Расширяет буфер до 2208 вершин и гарантирует hit_/burst_ атрибуты. True если менял."""
    changed = False
    n = len(mesh.vertices)
    if n < BUFFER_VERT_COUNT:
        mesh.vertices.add(BUFFER_VERT_COUNT - n)
        for i in range(n, BUFFER_VERT_COUNT):
            try:
                mesh.vertices[i].co = (0.0, 0.0, float(i))
            except Exception:
                pass
        changed = True

    # Базовые FLOAT-слои на всех точках (в т.ч. новые)
    for attr_name, default in (
        ("start_frame", -1.0),
        ("end_frame", -1.0),
        ("octavia_voice_id", -1.0),
    ):
        if attr_name not in mesh.attributes:
            mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
            for d in mesh.attributes[attr_name].data:
                d.value = default
            changed = True
        else:
            attr = mesh.attributes[attr_name]
            # Новые вершины после add() — зануляем только хвост зоны C, если ещё нули «как попало»
            if changed and len(attr.data) >= BUFFER_VERT_COUNT:
                for i in range(max(n, SALVO_BASE), BUFFER_VERT_COUNT):
                    attr.data[i].value = -1.0

    if ensure_hit_snapshot_attrs(mesh):
        changed = True
    if ensure_burst_attrs(mesh):
        changed = True

    if changed:
        # Инициализация burst_sub_index и нулей в зоне C
        sub = mesh.attributes.get("burst_sub_index")
        bpos = mesh.attributes.get("burst_position")
        bnml = mesh.attributes.get("burst_normal")
        start_attr = mesh.attributes.get("start_frame")
        end_attr = mesh.attributes.get("end_frame")
        for slot in range(NOTE_SLOT_COUNT):
            for p in range(SALVO_STRIDE):
                idx = salvo_vert_index(slot, p)
                if sub and idx < len(sub.data):
                    if sub.data[idx].value < 0.0:
                        sub.data[idx].value = float(p)
                if bpos and idx < len(bpos.data):
                    pass  # уже нули
                if bnml and idx < len(bnml.data):
                    pass
                if start_attr and idx < len(start_attr.data) and n <= idx:
                    start_attr.data[idx].value = -1.0
                if end_attr and idx < len(end_attr.data) and n <= idx:
                    end_attr.data[idx].value = -1.0
        try:
            mesh.update()
        except Exception:
            pass
    return changed


def read_burst_count(mesh, voice_id, default=1):
    """Плотность залпа с вершины голоса 128+hw_id.

    Ищем по приоритету: oc_m_burst_count → любой oc_m_*Burst* (напр. KickBurst).
    """
    vert_idx = VOICE_ZONE_START + int(voice_id)

    def _from_attr(attr_name):
        attr = mesh.attributes.get(attr_name)
        if attr is None or vert_idx < 0 or vert_idx >= len(attr.data):
            return None
        try:
            return int(round(float(attr.data[vert_idx].value)))
        except Exception:
            return None

    n = _from_attr(BURST_COUNT_ATTR)
    if n is None:
        # Совместимость с графами вроде KickBurst
        for attr in mesh.attributes:
            name = getattr(attr, "name", "") or ""
            if not name.startswith("oc_m_"):
                continue
            low = name.lower()
            if "burst" in low and "collapse" not in low:
                n = _from_attr(name)
                if n is not None:
                    break
    if n is None:
        n = int(default)
    return max(0, min(BURST_COUNT_MAX, n))


def sample_salvo_faces(context, emitter, count, seed):
    """N world (pos, normal) с фейсов СЫРОГО mesh.data эмиттера.

    Не evaluated_get: иначе Kick/тяжёлый GN Join+Realize заливает меш своими
    колоннами, и onset пересэмплит старый выстрел вместо поверхности куба.
    context оставлен в сигнатуре (PRESS/onset callers).
    """
    from mathutils import Vector
    import random

    count = max(0, min(BURST_COUNT_MAX, int(count)))
    if count <= 0:
        return []

    pivot_pos, pivot_nml = sample_emitter_basis(emitter)
    if emitter is None:
        return [(pivot_pos.copy(), pivot_nml.copy()) for _ in range(count)]

    mesh = getattr(emitter, "data", None)
    if getattr(emitter, "type", None) != 'MESH' or mesh is None:
        return [(pivot_pos.copy(), pivot_nml.copy()) for _ in range(count)]

    polys = getattr(mesh, "polygons", None)
    if not polys or len(polys) == 0:
        return [(pivot_pos.copy(), pivot_nml.copy()) for _ in range(count)]

    rng = random.Random(int(seed))
    M = emitter.matrix_world.copy()
    n_poly = len(polys)
    order = list(range(n_poly))
    rng.shuffle(order)
    results = []
    verts_co = mesh.vertices
    for i in range(count):
        poly = polys[order[i % n_poly]]
        center = Vector((0.0, 0.0, 0.0))
        vert_ids = poly.vertices
        if not vert_ids:
            results.append((pivot_pos.copy(), pivot_nml.copy()))
            continue
        for vi in vert_ids:
            center += verts_co[vi].co
        center /= float(len(vert_ids))
        nml_local = Vector(poly.normal)
        if nml_local.length_squared > 1e-12:
            nml_local.normalize()
        else:
            nml_local = Vector((0.0, 0.0, 1.0))
        p_world = M @ center
        n_world = M.to_3x3() @ nml_local
        if n_world.length_squared > 1e-12:
            n_world.normalize()
        else:
            n_world = pivot_nml.copy()
        results.append((p_world, n_world))
    return results


def _remove_fcurve_keys_at_frame(mesh, data_path, frame, array_index=None):
    """Сносит все ключи на кадре (и дубли) для data_path — до свежего keyframe_insert.

    Иначе PRESS + каждый onset-resolve копят 2+ ключа на одном кадре →
    scrub туда-сюда чередует «вариацию A / вариацию B» (часто зеркальные фейсы).
    """
    if not (mesh.animation_data and mesh.animation_data.action):
        return
    t = float(int(round(float(frame))))
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if getattr(fc, "data_path", "") != data_path:
            continue
        if array_index is not None and int(getattr(fc, "array_index", 0) or 0) != int(array_index):
            continue
        changed = False
        for kp in reversed(list(fc.keyframe_points)):
            if abs(float(kp.co[0]) - t) < 0.1:
                fc.keyframe_points.remove(kp)
                changed = True
        if changed:
            try:
                fc.keyframe_points.sort()
                fc.update()
            except Exception:
                pass


def _keyframe_scalar(mesh, attr_name, vert_idx, value, frame):
    attr = mesh.attributes.get(attr_name)
    if not attr or vert_idx >= len(attr.data):
        return
    attr.data[vert_idx].value = float(value)
    path = f'attributes["{attr_name}"].data[{vert_idx}].value'
    frame_i = int(round(float(frame)))
    _remove_fcurve_keys_at_frame(mesh, path, frame_i)
    try:
        mesh.keyframe_insert(data_path=path, frame=frame_i)
    except Exception as e:
        print(f"[Octavia] keyframe {attr_name}[{vert_idx}] @ {frame_i}: {e}")


def _keyframe_vector(mesh, attr_name, vert_idx, vec, frame):
    attr = mesh.attributes.get(attr_name)
    if not attr or vert_idx >= len(attr.data):
        return
    attr.data[vert_idx].vector = vec
    path = f'attributes["{attr_name}"].data[{vert_idx}].vector'
    frame_i = int(round(float(frame)))
    for axis in range(3):
        _remove_fcurve_keys_at_frame(mesh, path, frame_i, array_index=axis)
        try:
            mesh.keyframe_insert(data_path=path, index=axis, frame=frame_i)
        except Exception as e:
            print(f"[Octavia] keyframe {attr_name}[{vert_idx}].{axis} @ {frame_i}: {e}")


def write_salvo_spatial_only(mesh, slot_idx, samples, frame):
    """Только burst_position / burst_normal на кадре start.

    Не трогает start/end/voice — иначе после сдвига эмиттера onset-resolve
    ломает hold (collapse / обратный взрыв), хотя партитура та же.
    """
    ensure_buffer_topology(mesh)
    n_active = max(0, min(SALVO_STRIDE, len(samples)))
    frame_i = int(round(float(frame)))
    for p in range(n_active):
        idx = salvo_vert_index(slot_idx, p)
        pos, nml = samples[p]
        _keyframe_vector(mesh, "burst_position", idx, pos, frame_i)
        _keyframe_vector(mesh, "burst_normal", idx, nml, frame_i)


def write_salvo_block(mesh, slot_idx, samples, frame, end_hold=-1.0, voice_id=0.0):
    """Пишет блок 16 вершин залпа для нотного слота.

    Активные (0..N-1): start/end/burst_*/voice_id + keyframes.
    Хвост: только attr start=-1 БЕЗ keyframe (не раздуваем Action и не шумим в графе).
    """
    ensure_buffer_topology(mesh)
    n_active = max(0, min(SALVO_STRIDE, len(samples)))
    start_attr = mesh.attributes.get("start_frame")
    end_attr = mesh.attributes.get("end_frame")
    voice_attr = mesh.attributes.get("octavia_voice_id")
    for p in range(SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        sub = mesh.attributes.get("burst_sub_index")
        if sub and idx < len(sub.data):
            sub.data[idx].value = float(p)

        if p < n_active:
            pos, nml = samples[p]
            _keyframe_vector(mesh, "burst_position", idx, pos, frame)
            _keyframe_vector(mesh, "burst_normal", idx, nml, frame)
            _keyframe_scalar(mesh, "burst_sub_index", idx, float(p), frame)
            _keyframe_scalar(mesh, "start_frame", idx, float(frame), frame)
            _keyframe_scalar(mesh, "end_frame", idx, float(end_hold), frame)
            if voice_attr and idx < len(voice_attr.data):
                _keyframe_scalar(mesh, "octavia_voice_id", idx, float(voice_id), frame)
        else:
            # Неактивный хвост: гасим без keyframe — Action не раздувается
            bpos = mesh.attributes.get("burst_position")
            bnml = mesh.attributes.get("burst_normal")
            if bpos and idx < len(bpos.data):
                bpos.data[idx].vector = (0.0, 0.0, 0.0)
            if bnml and idx < len(bnml.data):
                bnml.data[idx].vector = (0.0, 0.0, 0.0)
            if start_attr and idx < len(start_attr.data):
                start_attr.data[idx].value = -1.0
            if end_attr and idx < len(end_attr.data):
                end_attr.data[idx].value = -1.0
            if voice_attr and idx < len(voice_attr.data):
                voice_attr.data[idx].value = -1.0


def sync_salvo_end_frame(mesh, slot_idx, end_frame):
    """RELEASE: end_frame только у активных частиц залпа (start>=1), снимок не трогает."""
    ensure_buffer_topology(mesh)
    start_attr = mesh.attributes.get("start_frame")
    for p in range(SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        if start_attr and idx < len(start_attr.data) and float(start_attr.data[idx].value) < 1.0:
            continue
        _keyframe_scalar(mesh, "end_frame", idx, float(end_frame), end_frame)


def _find_note_release_frame(mesh, slot_idx, start_frame, next_hit_frame=None):
    """Ключ end_frame нотного слота в теле ноты с value>=1 → кадр RELEASE, иначе None."""
    if not (mesh.animation_data and mesh.animation_data.action):
        return None
    t0 = float(start_frame)
    t1 = float("inf") if next_hit_frame is None else float(next_hit_frame)
    path = f'attributes["end_frame"].data[{int(slot_idx)}].value'
    best = None
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if getattr(fc, "data_path", "") != path:
            continue
        for kp in fc.keyframe_points:
            t = float(kp.co[0])
            v = float(kp.co[1])
            if v < 1.0:
                continue
            if (t0 - 0.5) < t < (t1 - 0.5):
                if best is None or t < best:
                    best = v if v >= 1.0 else t
        break
    return best


def _purge_stray_salvo_end_keys(mesh, slot_idx, start_frame, n_active, next_hit_frame=None):
    """Оставляет end=-1 на PRESS; сносит мусорные end в теле; возвращает легитимный RELEASE.

    Мусорный end mid-hold (value>0) → WAS_RELEASED/collapse во время hold =
    «исчезновение + обратный взрыв осколков».
    """
    ensure_buffer_topology(mesh)
    if not (mesh.animation_data and mesh.animation_data.action):
        return None
    t0 = float(start_frame)
    t1 = float("inf") if next_hit_frame is None else float(next_hit_frame)
    n_active = max(0, min(SALVO_STRIDE, int(n_active)))
    release = _find_note_release_frame(mesh, slot_idx, start_frame, next_hit_frame)

    for p in range(n_active):
        idx = salvo_vert_index(slot_idx, p)
        path = f'attributes["end_frame"].data[{idx}].value'
        for fc in iter_action_fcurves(mesh.animation_data.action):
            if getattr(fc, "data_path", "") != path:
                continue
            changed = False
            for kp in reversed(list(fc.keyframe_points)):
                t = float(kp.co[0])
                at_press = abs(t - t0) < 0.1
                in_body = (t0 + 0.1) < t < (t1 - 0.5)
                # На PRESS оставляем; всё остальное в теле (в т.ч. старый RELEASE) снимем —
                # легитимный RELEASE вернём sync'ом ниже.
                if at_press:
                    kp.co[1] = -1.0
                    changed = True
                    continue
                if in_body:
                    fc.keyframe_points.remove(kp)
                    changed = True
            if changed:
                try:
                    fc.keyframe_points.sort()
                    fc.update()
                except Exception:
                    pass
            break

    if release is not None and float(release) >= 1.0:
        sync_salvo_end_frame(mesh, slot_idx, float(release))
    return release


def shift_salvo_keyframes(mesh, slot_idx, start_frame, offset_frames, curves=None, next_hit_frame=None):
    """Drag: сдвигает ключи всех атрибутов залпа слота (PRESS + end в теле ноты)."""
    if abs(offset_frames) < 1e-9:
        return
    if curves is None:
        if not (mesh.animation_data and mesh.animation_data.action):
            return
        curves = list(iter_action_fcurves(mesh.animation_data.action))

    if next_hit_frame is None:
        next_hit_frame = float("inf")

    markers = (
        "start_frame", "end_frame", "burst_position", "burst_normal", "burst_sub_index",
        "octavia_voice_id",
    )
    for p in range(SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        for attr_name in markers:
            for fc in curves:
                dp = getattr(fc, "data_path", "") or ""
                name, vi = parse_attribute_data_path(dp)
                if name != attr_name or vi != idx:
                    continue
                for kp in fc.keyframe_points:
                    t = kp.co[0]
                    at_press = abs(t - start_frame) < 0.1
                    in_body = (attr_name == "end_frame"
                               and start_frame - 0.5 <= t < next_hit_frame - 0.5)
                    if not (at_press or in_body):
                        continue
                    kp.co[0] += offset_frames
                    if attr_name == "start_frame" and kp.co[1] >= 1.0:
                        kp.co[1] += offset_frames
                    elif attr_name == "end_frame" and kp.co[1] >= 1.0:
                        kp.co[1] += offset_frames
                    # voice_id / burst_* values — только время ключа
                fc.keyframe_points.sort()
                fc.update()


def shift_salvo_end_keyframes(mesh, slot_idx, start_frame, offset_frames, curves=None, next_hit_frame=None):
    """Resize: двигает только end_frame залпа (RELEASE в теле ноты). burst_* / start не трогает."""
    if abs(offset_frames) < 1e-9:
        return
    if curves is None:
        if not (mesh.animation_data and mesh.animation_data.action):
            return
        curves = list(iter_action_fcurves(mesh.animation_data.action))

    if next_hit_frame is None:
        next_hit_frame = float("inf")

    t0 = float(start_frame)
    t1 = float(next_hit_frame)
    for p in range(SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        for fc in curves:
            dp = getattr(fc, "data_path", "") or ""
            name, vi = parse_attribute_data_path(dp)
            if name != "end_frame" or vi != idx:
                continue
            changed = False
            for kp in fc.keyframe_points:
                t = float(kp.co[0])
                v = float(kp.co[1])
                # RELEASE в теле: value >= start; hold-ключ (-1) на PRESS не двигаем
                if v < 1.0:
                    continue
                if not (t0 - 0.5 <= t < t1 - 0.5):
                    continue
                kp.co[0] += offset_frames
                kp.co[1] += offset_frames
                changed = True
            if changed:
                try:
                    fc.keyframe_points.sort()
                    fc.update()
                except Exception:
                    pass


def remount_onset_freeze_after_note_move(ch_idx, slot_idx, old_start, new_start, emitter=None):
    """После drag блока: freeze живёт под новым start, без пересэмпла.

    Иначе onset видит новый start → spatial_only → другой seed → другие фейсы,
    хотя партитуру только сдвинули по времени.
    """
    old_key = (int(ch_idx), int(slot_idx), int(round(float(old_start))))
    new_key = (int(ch_idx), int(slot_idx), int(round(float(new_start))))
    x = _onset_freeze_xform.pop(old_key, None)
    if x is None:
        x = _emitter_xform_key(emitter)
    if x is not None:
        _onset_freeze_xform[new_key] = x
    _onset_latch[(int(ch_idx), int(slot_idx))] = float(new_start)


def clear_salvo_block_keys(mesh, slot_idx, start_frame, curves_with_owners=None,
                           from_particle=0, next_hit_frame=None):
    """Снимает ключи залпа для ноты и гасит attr.

    from_particle=0 — полный блок (ластик).
    from_particle=N — только хвост после N активных (onset rewrite).

    Важно: end_frame залпа ключуется и на PRESS (-1), и на RELEASE (кадр отпускания).
    Ластик должен сносить оба — иначе spreadsheet/GN видят осиротевшие записи.
    """
    ensure_buffer_topology(mesh)
    if curves_with_owners is None and mesh.animation_data and mesh.animation_data.action:
        act = mesh.animation_data.action
        curves_with_owners = []
        for fc, owner in iter_action_fcurves_with_owners(act):
            curves_with_owners.append((fc, owner))

    markers = (
        "start_frame", "end_frame", "burst_position", "burst_normal",
        "burst_sub_index", "octavia_voice_id",
    )
    start_p = max(0, int(from_particle))
    t0 = float(start_frame)
    t_next = float("inf") if next_hit_frame is None else float(next_hit_frame)

    for p in range(start_p, SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        for attr_name in ("start_frame", "end_frame", "octavia_voice_id"):
            attr = mesh.attributes.get(attr_name)
            if attr and idx < len(attr.data):
                attr.data[idx].value = -1.0
        for attr_name in ("burst_position", "burst_normal"):
            attr = mesh.attributes.get(attr_name)
            if attr and idx < len(attr.data):
                attr.data[idx].vector = (0.0, 0.0, 0.0)
        sub = mesh.attributes.get("burst_sub_index")
        if sub and idx < len(sub.data):
            sub.data[idx].value = float(p)

        if not curves_with_owners:
            continue
        for fc, owner in list(curves_with_owners):
            try:
                dp = safe_fcurve_data_path(fc)
            except Exception:
                continue
            if not dp:
                continue
            name, vi = parse_attribute_data_path(dp)
            if vi != idx or name not in markers:
                continue
            changed = False
            try:
                for kp in reversed(list(fc.keyframe_points)):
                    t = float(kp.co[0])
                    at_press = abs(t - t0) < 0.1
                    # end на RELEASE и любые end в теле ноты до следующей
                    in_body_end = (
                        name == "end_frame"
                        and (t0 - 0.5) <= t < (t_next - 0.5)
                    )
                    if not (at_press or in_body_end):
                        continue
                    fc.keyframe_points.remove(kp)
                    changed = True
            except Exception:
                continue
            if changed:
                try:
                    fc.keyframe_points.sort()
                except Exception:
                    pass
                try:
                    fc.update()
                except Exception:
                    pass
            if len(getattr(fc, "keyframe_points", []) or []) == 0 and owner is not None:
                try:
                    owner.remove(fc)
                except Exception:
                    pass


def buffer_has_active_note_keys(mesh):
    """Есть ли в зоне А (0–127) ключ start_frame со значением >= 1.

    Только fcurves — НЕ сырой attr. Иначе после ластика грязный attr
    блокирует sanitize и spreadsheet вечно показывает мусор.
    """
    start_c, _, _ = get_note_timing_curve_maps(mesh, use_cache=False)
    for idx, fc in start_c.items():
        if not is_note_slot_index(idx):
            continue
        for kp in fc.keyframe_points:
            if float(kp.co[1]) >= 1.0:
                return True
    return False


def _live_note_slots(mesh):
    """Слоты зоны А, у которых есть start_frame key со значением >= 1."""
    live = set()
    start_c, _, _ = get_note_timing_curve_maps(mesh, use_cache=False)
    for idx, fc in start_c.items():
        if not is_note_slot_index(idx):
            continue
        for kp in fc.keyframe_points:
            if float(kp.co[1]) >= 1.0:
                live.add(int(idx))
                break
    return live


def _reset_note_attr_vert(mesh, i):
    """Гасит note/salvo attr на вершине i (safe defaults)."""
    for attr_name in _NOTE_ATTR_MARKERS:
        attr = mesh.attributes.get(attr_name)
        if not attr or i >= len(attr.data):
            continue
        if attr_name in _VECTOR_NOTE_ATTRS:
            attr.data[i].vector = (0.0, 0.0, 0.0)
        elif attr_name == "burst_sub_index":
            if i >= SALVO_BASE:
                attr.data[i].value = float((i - SALVO_BASE) % SALVO_STRIDE)
            else:
                attr.data[i].value = -1.0
        else:
            attr.data[i].value = -1.0


def wipe_salvo_slot_residue(mesh, slot_idx):
    """Сносит ВСЕ ключи/attr залпа слота (любой кадр) — не только ключи @ start_frame."""
    ensure_buffer_topology(mesh)
    markers = (
        "start_frame", "end_frame", "burst_position", "burst_normal",
        "burst_sub_index", "octavia_voice_id",
        "hit_position", "hit_normal",
    )
    vert_ids = {salvo_vert_index(slot_idx, p) for p in range(SALVO_STRIDE)}
    for idx in vert_ids:
        _reset_note_attr_vert(mesh, idx)

    if not (mesh.animation_data and mesh.animation_data.action):
        return
    act = mesh.animation_data.action
    for fc, owner in list(iter_action_fcurves_with_owners(act)):
        name, vi = parse_attribute_data_path(getattr(fc, "data_path", None))
        if vi not in vert_ids or name not in markers:
            continue
        try:
            for kp in reversed(list(fc.keyframe_points)):
                fc.keyframe_points.remove(kp)
        except Exception:
            pass
        if owner is not None:
            try:
                owner.remove(fc)
            except Exception:
                try:
                    fc.update()
                except Exception:
                    pass


def wipe_note_slot_residue(mesh, slot_idx):
    """Полностью гасит нотный слот зоны А + его залп (осиротевший voice_id/hit и т.д.)."""
    ensure_buffer_topology(mesh)
    slot_idx = int(slot_idx)
    if not is_note_slot_index(slot_idx):
        return
    _reset_note_attr_vert(mesh, slot_idx)

    markers = (
        "start_frame", "end_frame", "octavia_voice_id",
        "hit_position", "hit_normal",
        "burst_position", "burst_normal", "burst_sub_index",
    )
    if mesh.animation_data and mesh.animation_data.action:
        act = mesh.animation_data.action
        for fc, owner in list(iter_action_fcurves_with_owners(act)):
            name, vi = parse_attribute_data_path(getattr(fc, "data_path", None))
            if vi != slot_idx or name not in markers:
                continue
            try:
                for kp in reversed(list(fc.keyframe_points)):
                    fc.keyframe_points.remove(kp)
            except Exception:
                pass
            if owner is not None:
                try:
                    owner.remove(fc)
                except Exception:
                    try:
                        fc.update()
                    except Exception:
                        pass

    wipe_salvo_slot_residue(mesh, slot_idx)


def _buffer_has_dirty_note_timing_attrs(mesh):
    """Сырой spreadsheet-мусор: start/end/voice не в дефолте при пустом Action."""
    start = mesh.attributes.get("start_frame")
    end = mesh.attributes.get("end_frame")
    voice = mesh.attributes.get("octavia_voice_id")
    n = min(NOTE_SLOT_COUNT, len(mesh.vertices) if mesh.vertices else 0)

    def _dirty_scalar(attr, i, empty=-1.0):
        if attr is None or i >= len(attr.data):
            return False
        try:
            return abs(float(attr.data[i].value) - empty) > 1e-6
        except Exception:
            return False

    for i in range(n):
        if _dirty_scalar(start, i) or _dirty_scalar(end, i) or _dirty_scalar(voice, i):
            return True
        for name in ("hit_position", "hit_normal"):
            attr = mesh.attributes.get(name)
            if not attr or i >= len(attr.data):
                continue
            try:
                v = attr.data[i].vector
                if abs(v[0]) + abs(v[1]) + abs(v[2]) > 1e-6:
                    return True
            except Exception:
                pass
    # залп: любой start>=1
    if start is not None:
        for i in range(SALVO_BASE, min(BUFFER_VERT_COUNT, len(start.data))):
            try:
                if float(start.data[i].value) >= 1.0:
                    return True
            except Exception:
                pass
    return False


def sanitize_buffer_after_erase(mesh):
    """
    После ластика:
    - нет ключей start>=1 → полный wipe attr+curves (spreadsheet чистый);
    - есть живые слоты → сносим только мёртвые слоты (keys+attr+залп).
    """
    ensure_buffer_topology(mesh)
    clear_note_timing_maps_cache()
    live = _live_note_slots(mesh)
    if not live:
        _clear_note_attribute_curves(mesh)
        return
    for slot in range(NOTE_SLOT_COUNT):
        if slot not in live:
            wipe_note_slot_residue(mesh, slot)
    scrub_phantom_buffer_attrs(mesh)
    clear_note_timing_maps_cache()


def scrub_phantom_buffer_attrs(mesh):
    """
    Фантомы OOM: start/end в attr без настоящих ключей.
    Типичный мусор: start=1..15 (== burst_sub_index), end=-1 → GN hold на сотнях точек.
    BurstCount тут ни при чём — раздувается числом фантомных частиц.
    """
    ensure_buffer_topology(mesh)
    live = _live_note_slots(mesh)
    starts_fc, _ends_fc = _watch_index_timing_fcurves(mesh)
    wiped_notes = 0
    wiped_salvo = 0

    for slot in range(NOTE_SLOT_COUNT):
        if slot in live:
            continue
        st = _watch_attr_float(mesh, "start_frame", slot, 0.0)
        en = _watch_attr_float(mesh, "end_frame", slot, -1.0)
        vid = _watch_attr_float(mesh, "octavia_voice_id", slot, -1.0)
        if st < 1.0 and en < 1.0 and vid < 0.0:
            continue
        wipe_note_slot_residue(mesh, slot)
        wiped_notes += 1

    for slot in range(NOTE_SLOT_COUNT):
        for p in range(SALVO_STRIDE):
            idx = salvo_vert_index(slot, p)
            st = _watch_attr_float(mesh, "start_frame", idx, 0.0)
            if st < 1.0:
                continue
            fc = starts_fc.get(idx)
            key_vals = []
            if fc is not None:
                try:
                    key_vals = [float(kp.co[1]) for kp in fc.keyframe_points if float(kp.co[1]) >= 1.0]
                except Exception:
                    key_vals = []
            sub = _watch_attr_float(mesh, "burst_sub_index", idx, float(p))
            if key_vals:
                # ключи только вида 1..15 ≈ sub_index → мусор; иначе живой залп (в т.ч. кадр 5)
                if any(v >= 16.0 or abs(v - sub) > 0.1 for v in key_vals):
                    continue
            # нет нормальных ключей → снести attr (+ мусорные keys 1..15)
            for attr_name in ("start_frame", "end_frame", "octavia_voice_id"):
                attr = mesh.attributes.get(attr_name)
                if attr and idx < len(attr.data):
                    attr.data[idx].value = -1.0
            for attr_name in ("burst_position", "burst_normal"):
                attr = mesh.attributes.get(attr_name)
                if attr and idx < len(attr.data):
                    attr.data[idx].vector = (0.0, 0.0, 0.0)
            if fc is not None and key_vals:
                try:
                    for kp in reversed(list(fc.keyframe_points)):
                        if float(kp.co[1]) < 16.0 and abs(float(kp.co[1]) - sub) < 0.1:
                            fc.keyframe_points.remove(kp)
                    if len(fc.keyframe_points) == 0 and mesh.animation_data and mesh.animation_data.action:
                        for _fc, owner in list(iter_action_fcurves_with_owners(mesh.animation_data.action)):
                            if _fc == fc and owner is not None:
                                try:
                                    owner.remove(fc)
                                except Exception:
                                    pass
                                break
                except Exception:
                    pass
            wiped_salvo += 1

    if wiped_notes or wiped_salvo:
        clear_note_timing_maps_cache()
        try:
            mesh.update()
        except Exception:
            pass
        print(
            f"[Octavia] phantom scrub: notes={wiped_notes} salvo_particles={wiped_salvo} "
            f"(фантомный hold start=1..15 — причина OOM при BurstCount>=1)"
        )
    return wiped_notes + wiped_salvo


_phantom_scrub_sign = {}


def scrub_phantom_buffers_on_scene(scene):
    """frame_change: raw start>>keyed notes → снести фантомы (не трогая живые ключи)."""
    try:
        max_ch = int(getattr(scene, "octavia_channel_count", 8) or 8)
    except Exception:
        max_ch = 8
    for ch in range(1, max_ch + 1):
        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if not buf or buf.type != "MESH" or not buf.data:
            continue
        mesh = buf.data
        live_n = len(_live_note_slots(mesh))
        start = mesh.attributes.get("start_frame")
        if start is None:
            continue
        raw_on = 0
        for i in range(min(NOTE_SLOT_COUNT, len(start.data))):
            try:
                if float(start.data[i].value) >= 1.0:
                    raw_on += 1
            except Exception:
                pass
        sign = (live_n, raw_on)
        if raw_on <= live_n + 2:
            _phantom_scrub_sign[ch] = sign
            continue
        if _phantom_scrub_sign.get(ch) == sign:
            continue
        n = scrub_phantom_buffer_attrs(mesh)
        if n:
            try:
                buf.update_tag()
            except Exception:
                pass
        _phantom_scrub_sign[ch] = (len(_live_note_slots(mesh)), raw_on)


_orphan_attr_purge_done = set()


def purge_orphan_note_attrs_if_canvas_empty(scene):
    """
    Canvas пуст (нет start>=1 keys), а spreadsheet грязный → один wipe.
    Безопасно: смотрит только ключи, не attr (иначе вечный deadlock).
    """
    global _orphan_attr_purge_done
    try:
        max_ch = int(getattr(scene, "octavia_channel_count", 8) or 8)
    except Exception:
        max_ch = 8
    for ch in range(1, max_ch + 1):
        buf_name = f"Octavia_Buffer_Ch_{ch}"
        buf = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
        if not buf or buf.type != "MESH" or not buf.data:
            continue
        mesh = buf.data
        try:
            key = mesh.as_pointer()
        except Exception:
            key = id(mesh)
        if buffer_has_active_note_keys(mesh):
            _orphan_attr_purge_done.discard(key)
            continue
        if key in _orphan_attr_purge_done:
            continue
        if not _buffer_has_dirty_note_timing_attrs(mesh):
            _orphan_attr_purge_done.add(key)
            continue
        try:
            _clear_note_attribute_curves(mesh)
            mesh.update()
            buf.update_tag()
            _orphan_attr_purge_done.add(key)
            print(f"[Octavia] eraser purge Ch{ch}: canvas empty → wiped orphan start/end attrs")
        except Exception as e:
            print(f"[Octavia] eraser purge Ch{ch}: {e}")


def mark_buffer_attrs_need_purge(mesh):
    """Сброс throttle: следующий frame_change снова проверит orphan attrs."""
    try:
        _orphan_attr_purge_done.discard(mesh.as_pointer())
    except Exception:
        pass


def _buffer_has_orphan_voice_attrs(mesh):
    """Ноты на таймлайне пусты, а octavia_voice_id/start всё ещё светятся в spreadsheet."""
    return _buffer_has_dirty_note_timing_attrs(mesh)


# Авто-sanitize на frame_change ОТКЛЮЧЁН как wipe-всех-нот; вместо него — purge_orphan.
_auto_sanitize_done = set()


def auto_sanitize_dirty_empty_buffers(scene):
    """Deprecated → purge_orphan_note_attrs_if_canvas_empty."""
    purge_orphan_note_attrs_if_canvas_empty(scene)


def read_salvo_block(mesh, slot_idx, frame=None):
    """Читает активные (start>=1) частицы залпа → list of (pos, nml)."""
    from mathutils import Vector
    ensure_buffer_topology(mesh)
    out = []
    for p in range(SALVO_STRIDE):
        idx = salvo_vert_index(slot_idx, p)
        st = -1.0
        if frame is not None and mesh.animation_data and mesh.animation_data.action:
            path = f'attributes["start_frame"].data[{idx}].value'
            for fc in iter_action_fcurves(mesh.animation_data.action):
                if getattr(fc, "data_path", "") == path:
                    st = float(fc.evaluate(float(frame)))
                    break
        if st < 0.0:
            attr = mesh.attributes.get("start_frame")
            if attr and idx < len(attr.data):
                st = float(attr.data[idx].value)
        if st < 1.0:
            continue
        pos = Vector((0.0, 0.0, 0.0))
        nml = Vector((0.0, 0.0, 1.0))
        bpos = mesh.attributes.get("burst_position")
        bnml = mesh.attributes.get("burst_normal")
        if bpos and idx < len(bpos.data):
            v = bpos.data[idx].vector
            pos = Vector((float(v[0]), float(v[1]), float(v[2])))
        if bnml and idx < len(bnml.data):
            v = bnml.data[idx].vector
            nml = Vector((float(v[0]), float(v[1]), float(v[2])))
        out.append((pos, nml))
    return out


def resolve_channel_emitter(context, ch_idx):
    """Объект-донор импульса: любой с модификатором Octavia Channel {ch} (mesh/curve/empty)."""
    mod_name = f"Octavia Channel {ch_idx}"
    obj = getattr(context, "active_object", None)
    if obj is not None and obj.modifiers.get(mod_name):
        return obj
    scene = context.scene
    for o in scene.objects:
        if o.modifiers.get(mod_name):
            return o
    return None


def sample_emitter_basis(obj):
    """World hit_position + hit_normal из matrix_world (локальная +Z без scale). Без evaluated_get."""
    from mathutils import Vector
    if obj is None:
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0))
    M = obj.matrix_world
    pos = M.translation.copy()
    nml = M.to_3x3() @ Vector((0.0, 0.0, 1.0))
    if nml.length_squared > 1e-12:
        nml.normalize()
    else:
        nml = Vector((0.0, 0.0, 1.0))
    return pos, nml


def write_hit_snapshot(mesh, slot_idx, position, normal, frame):
    """Пишет hit_* в слот и ставит CONSTANT-compatible keyframes (3 компоненты)."""
    ensure_hit_snapshot_attrs(mesh)
    pairs = (
        ("hit_position", position),
        ("hit_normal", normal),
    )
    frame_i = int(round(float(frame)))
    for attr_name, vec in pairs:
        attr = mesh.attributes.get(attr_name)
        if not attr or slot_idx >= len(attr.data):
            continue
        attr.data[slot_idx].vector = vec
        path = f'attributes["{attr_name}"].data[{slot_idx}].vector'
        for axis in range(3):
            _remove_fcurve_keys_at_frame(mesh, path, frame_i, array_index=axis)
            try:
                mesh.keyframe_insert(data_path=path, index=axis, frame=frame_i)
            except Exception as e:
                print(f"[Octavia] hit keyframe_insert {attr_name}[{slot_idx}].{axis} @ {frame_i}: {e}")


def read_hit_snapshot(mesh, slot_idx, frame=None):
    """Читает hit_position/hit_normal слота (из fcurves @ frame или из attr.data)."""
    from mathutils import Vector
    ensure_hit_snapshot_attrs(mesh)
    pos = [0.0, 0.0, 0.0]
    nml = [0.0, 0.0, 0.0]
    got_from_curves = False
    if frame is not None and mesh.animation_data and mesh.animation_data.action:
        for attr_name, out in (("hit_position", pos), ("hit_normal", nml)):
            path = f'attributes["{attr_name}"].data[{slot_idx}].vector'
            for fc in iter_action_fcurves(mesh.animation_data.action):
                if getattr(fc, "data_path", "") != path:
                    continue
                ai = int(getattr(fc, "array_index", 0) or 0)
                if 0 <= ai < 3:
                    out[ai] = float(fc.evaluate(float(frame)))
                    got_from_curves = True
    if not got_from_curves:
        for attr_name, out in (("hit_position", pos), ("hit_normal", nml)):
            attr = mesh.attributes.get(attr_name)
            if attr and slot_idx < len(attr.data):
                v = attr.data[slot_idx].vector
                out[0], out[1], out[2] = float(v[0]), float(v[1]), float(v[2])
    return Vector(pos), Vector(nml)


# ─── Idea 1: resolve-at-onset (не resolve-at-record) ───
# Партитура = когда; эмиттер = откуда сейчас. World hit_/burst_ замораживаются
# при входе playhead в ноту; mid-note эмиттер можно крутить — снимок не едет.
_onset_latch = {}  # (ch_idx, slot_idx) -> start_frame
_onset_prev_frame = {}  # scene-as-id → previous frame_current
# (ch, slot, start_i) -> matrix_world fingerprint на момент freeze
_onset_freeze_xform = {}


def clear_onset_latch():
    _onset_latch.clear()
    _onset_prev_frame.clear()
    _onset_freeze_xform.clear()


def _clear_onset_freeze_for_slot(ch_idx, slot_idx):
    dead = [
        k for k in _onset_freeze_xform
        if k[0] == int(ch_idx) and k[1] == int(slot_idx)
    ]
    for k in dead:
        _onset_freeze_xform.pop(k, None)


def _emitter_xform_key(obj):
    """Отпечаток matrix_world — сдвиг куба после freeze должен дать новый resolve."""
    if obj is None:
        return ()
    try:
        M = obj.matrix_world
        return tuple(round(float(M[i][j]), 5) for i in range(4) for j in range(4))
    except Exception:
        return ()


def _note_contributing_at(frame, start, end):
    """start<=F и (end<0 или F<=end). Та же эвристика, что в BRIEF-слепке."""
    if start is None or start < 1.0:
        return False
    if frame < start:
        return False
    if end is None or end < 0.0:
        return True
    return frame <= end


def _salvo_has_snapshot_at(mesh, slot_idx, start_frame):
    """Есть ли уже ключ burst_position на кадре start у первой частицы залпа.

    Если да — партитура spatially заморожена: scrub/reload/echo НЕ должны
    пересэмплить эмиттер (иначе телепорты и «пропал/появился»).
    """
    if not (mesh.animation_data and mesh.animation_data.action):
        return False
    idx0 = salvo_vert_index(int(slot_idx), 0)
    path = f'attributes["burst_position"].data[{idx0}].vector'
    t0 = float(start_frame)
    for fc in iter_action_fcurves(mesh.animation_data.action):
        if getattr(fc, "data_path", "") != path:
            continue
        if int(getattr(fc, "array_index", 0) or 0) != 0:
            continue
        for kp in fc.keyframe_points:
            if abs(float(kp.co[0]) - t0) < 0.1:
                return True
    return False


def resolve_note_emitter_snapshot(context, ch_idx, mesh, slot_idx, start_frame, voice_id, end_frame=None,
                                  spatial_only=False):
    """Семпл эмиттера → hit_/burst_ на кадре start.

    spatial_only=True: только позиции/нормали (после сдвига куба). Timing-ключи не трогаем.
    """
    ensure_buffer_topology(mesh)
    emitter = resolve_channel_emitter(context, ch_idx)
    hit_pos, hit_nml = sample_emitter_basis(emitter)
    frame_i = int(round(float(start_frame)))
    write_hit_snapshot(mesh, slot_idx, hit_pos, hit_nml, frame_i)

    vid = int(voice_id) if voice_id is not None else 0
    burst_n = max(1, read_burst_count(mesh, vid, default=1))
    seed = frame_i + int(slot_idx) + vid
    samples = sample_salvo_faces(context, emitter, burst_n, seed)
    if not samples:
        samples = [sample_emitter_basis(emitter)]

    if spatial_only:
        write_salvo_spatial_only(mesh, slot_idx, samples, frame_i)
    else:
        write_salvo_block(
            mesh, slot_idx, samples, frame_i,
            end_hold=-1.0, voice_id=float(vid),
        )
        clear_salvo_block_keys(
            mesh, slot_idx, float(start_frame), from_particle=len(samples),
        )

    # CONSTANT только на hit/burst этого слота и его залпа
    if mesh.animation_data and mesh.animation_data.action:
        import re
        wanted = {int(slot_idx)}
        wanted.update(salvo_vert_index(slot_idx, p) for p in range(SALVO_STRIDE))
        for fc in iter_action_fcurves(mesh.animation_data.action):
            dp = getattr(fc, "data_path", "") or ""
            if "hit_" not in dp and "burst_" not in dp:
                continue
            m = re.search(r"\.data\[(\d+)\]", dp)
            if not m or int(m.group(1)) not in wanted:
                continue
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'
            try:
                fc.update()
            except Exception:
                pass


def process_emitter_onset_resolves(scene):
    """frame_change_post: freeze эмиттера только при ВХОДЕ в ноту (дешёвый idle)."""
    context = bpy.context
    if context is None or scene is None:
        return

    frame = float(scene.frame_current)
    scene_key = scene.as_pointer() if hasattr(scene, "as_pointer") else id(scene)
    prev_frame = _onset_prev_frame.get(scene_key, frame)
    _onset_prev_frame[scene_key] = frame

    # Сколько каналов реально есть — не сканируем 1..20 вхолостую
    n_ch = int(getattr(scene, "octavia_channel_count", 0) or 0)
    if n_ch < 1 and hasattr(scene, "octavia_channels_data"):
        n_ch = len(scene.octavia_channels_data)
    if n_ch < 1:
        return

    any_dirty = False
    for ch_idx in range(1, n_ch + 1):
        buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
        buf_obj = scene.objects.get(buf_name)
        if buf_obj is None:
            buf_obj = bpy.data.objects.get(buf_name)
        if not buf_obj or not buf_obj.data:
            continue
        mesh = buf_obj.data
        if not (mesh.animation_data and mesh.animation_data.action):
            continue

        # Один проход по Action → только слоты с ключами start/end/voice
        timing = _index_note_timing_fcurves(mesh)
        if not timing:
            continue

        start_attr = mesh.attributes.get("start_frame")
        end_attr = mesh.attributes.get("end_frame")
        voice_attr = mesh.attributes.get("octavia_voice_id")
        ch_dirty = False

        for slot, fcs in timing.items():
            fc_start = fcs.get("start_frame")
            if fc_start is None:
                continue
            start = float(fc_start.evaluate(frame))
            fc_end = fcs.get("end_frame")
            if fc_end is not None:
                end = float(fc_end.evaluate(frame))
            elif end_attr and slot < len(end_attr.data):
                end = float(end_attr.data[slot].value)
            else:
                end = -1.0
            fc_voice = fcs.get("octavia_voice_id")
            if fc_voice is not None:
                voice = float(fc_voice.evaluate(frame))
            elif voice_attr and slot < len(voice_attr.data):
                voice = float(voice_attr.data[slot].value)
            else:
                voice = 0.0

            key = (ch_idx, slot)
            contributing = _note_contributing_at(frame, start, end)
            if not contributing:
                # Latch НЕ снимаем — иначе scrub hold↔echo снова орёт resolve/телепорты.
                continue

            start_f = float(start)
            prev_latched = _onset_latch.get(key)
            entered = (prev_frame < start_f - 1e-6) and (frame + 1e-6 >= start_f)
            jumped_inside = (not entered) and (prev_latched is None)
            # Луп: playhead прыгнул на ноту (200→100), crossed_start=False, но нужен onset.
            loop_reentry = (
                (not entered)
                and abs(frame - prev_frame) > 1.5
                and (frame + 1e-6 >= start_f)
                and prev_latched is not None
                and abs(prev_latched - start_f) < 0.1
            )

            emitter = resolve_channel_emitter(context, ch_idx)
            xform = _emitter_xform_key(emitter)
            freeze_key = (ch_idx, int(slot), int(round(start_f)))
            prev_x = _onset_freeze_xform.get(freeze_key)
            same_freeze = (
                prev_x is not None
                and prev_x == xform
                and _salvo_has_snapshot_at(mesh, slot, start_f)
            )

            # Scrub внутри ноты — idle (как в рабочем TEST).
            if (
                prev_latched is not None
                and abs(prev_latched - start_f) < 0.1
                and not entered
                and not loop_reentry
            ):
                continue

            if not (entered or jumped_inside or loop_reentry):
                continue

            # Тот же эмиттер — не пересэмплить (анти A/B). Без purge на каждом заходе.
            if same_freeze:
                _onset_latch[key] = start_f
                continue

            try:
                # Уже есть timing+salvo с PRESS → после сдвига куба только XYZ/normal.
                # Полный rewrite start/end давал collapse/дыры в hold.
                has_snap = _salvo_has_snapshot_at(mesh, slot, start_f)
                resolve_note_emitter_snapshot(
                    context, ch_idx, mesh, slot, start_f, voice,
                    end_frame=None,
                    spatial_only=has_snap,
                )
                _onset_freeze_xform[freeze_key] = xform
                _onset_latch[key] = start_f
                ch_dirty = True
            except Exception as e:
                print(f"[Octavia] onset resolve Ch{ch_idx} slot{slot}: {e}")

        if ch_dirty:
            try:
                mesh.update()
                buf_obj.update_tag()
            except Exception:
                pass
            any_dirty = True

    # view_layer.update() специально НЕ зовём — убивает FPS; tag достаточно
    if any_dirty:
        pass


# ─── Watchdog: давление Kick-геометрии (консоль Blender до OOM/TDR) ───
# Пороги консервативные: BUILD_GRID ≈128 ячеек на активную частицу залпа в hold.
_KICK_GRID_CELLS_EST = 128
_WATCH_WARN_SALVO = 24
_WATCH_CRIT_SALVO = 64
_WATCH_WARN_NOTES = 8
_WATCH_CRIT_NOTES = 16
_WATCH_WARN_CELLS = 2500
_WATCH_CRIT_CELLS = 8000
_watch_last_sig = {}  # ch -> (level, notes, salvo, ghosts)
_watch_last_print_frame = {}


def clear_kick_pressure_watch():
    _watch_last_sig.clear()
    _watch_last_print_frame.clear()
    _auto_sanitize_done.clear()
    _orphan_attr_purge_done.clear()
    _phantom_scrub_sign.clear()


def _watch_attr_float(mesh, name, idx, default=0.0):
    attr = mesh.attributes.get(name)
    if not attr or idx < 0 or idx >= len(attr.data):
        return default
    try:
        return float(attr.data[idx].value)
    except Exception:
        return default


def _watch_attr_vec_len(mesh, name, idx):
    attr = mesh.attributes.get(name)
    if not attr or idx < 0 or idx >= len(attr.data):
        return 0.0
    try:
        v = attr.data[idx].vector
        return abs(v[0]) + abs(v[1]) + abs(v[2])
    except Exception:
        return 0.0


def _watch_index_timing_fcurves(mesh):
    """Один проход по action → start/end fcurves по индексу вершины."""
    starts, ends = {}, {}
    if not mesh.animation_data or not mesh.animation_data.action:
        return starts, ends
    for fc in iter_action_fcurves(mesh.animation_data.action):
        name, idx = parse_attribute_data_path(safe_fcurve_data_path(fc))
        if idx is None:
            continue
        if name == "start_frame":
            starts[idx] = fc
        elif name == "end_frame":
            ends[idx] = fc
    return starts, ends


def _watch_slot_timing(starts, ends, mesh, idx, frame_f):
    """(start, end) на кадре: fcurve → иначе сырой attr."""
    st = None
    en = None
    fc_s = starts.get(idx)
    fc_e = ends.get(idx)
    if fc_s is not None:
        try:
            st = float(fc_s.evaluate(frame_f))
        except Exception:
            st = None
    if fc_e is not None:
        try:
            en = float(fc_e.evaluate(frame_f))
        except Exception:
            en = None
    if st is None:
        st = _watch_attr_float(mesh, "start_frame", idx, 0.0)
    if en is None:
        en = _watch_attr_float(mesh, "end_frame", idx, -1.0)
    return st, en


def scan_channel_kick_pressure(scene, ch_idx, frame_f=None):
    """Снимок давления буфера канала (fcurves @ frame, без depsgraph)."""
    if frame_f is None:
        frame_f = float(scene.frame_current)
    buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
    buf = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
    if not buf or buf.type != "MESH" or not buf.data:
        return None
    mesh = buf.data
    ensure_buffer_topology(mesh)
    starts, ends = _watch_index_timing_fcurves(mesh)

    notes_attr_on = 0
    notes_live = 0
    notes_held = 0
    ghosts = 0
    ghost_slots = []
    for i in range(NOTE_SLOT_COUNT):
        st, en = _watch_slot_timing(starts, ends, mesh, i, frame_f)
        if st < 1.0:
            continue
        notes_attr_on += 1
        # hold: end=-1 — это НЕ призрак, нота жива
        if en < 0.0:
            notes_held += 1
            notes_live += 1
        elif en > st and st <= frame_f <= en:
            notes_live += 1
        elif en >= 1.0 and en < st:
            ghosts += 1
            if len(ghost_slots) < 12:
                ghost_slots.append(i)

    voice_id = 0
    try:
        if hasattr(scene, "octavia_channels_data") and len(scene.octavia_channels_data) >= ch_idx:
            ch_data = scene.octavia_channels_data[ch_idx - 1]
            vi = int(getattr(ch_data, "active_voice_idx", 0) or 0)
            if 0 <= vi < len(ch_data.voices):
                voice_id = int(getattr(ch_data.voices[vi], "hardware_id", vi) or 0)
            elif len(ch_data.voices) > 0:
                voice_id = int(getattr(ch_data.voices[0], "hardware_id", 0) or 0)
    except Exception:
        voice_id = 0

    burst = max(1, int(read_burst_count(mesh, voice_id, default=1) or 1))
    count = _watch_attr_float(mesh, "oc_m_KickColCount", VOICE_ZONE_START + voice_id, 1.0)
    if count <= 0.0:
        count = 1.0
    fade = _watch_attr_float(mesh, "oc_m_KickFade", VOICE_ZONE_START + voice_id, 25.0)
    kick_burst_factor = _watch_attr_float(mesh, "oc_m_KickBurst", VOICE_ZONE_START + voice_id, 0.0)

    salvo_active = 0
    salvo_attr_on = 0
    salvo_geo_alive = 0  # hold + тело + echo (как COL_VISIBLE в графе)
    salvo_candidates = set()
    for idx in starts:
        if idx >= SALVO_BASE:
            salvo_candidates.add(idx)
    if not salvo_candidates:
        for i in range(SALVO_BASE, min(BUFFER_VERT_COUNT, len(mesh.vertices))):
            if _watch_attr_float(mesh, "start_frame", i, 0.0) >= 1.0:
                salvo_candidates.add(i)

    for i in salvo_candidates:
        st, en = _watch_slot_timing(starts, ends, mesh, i, frame_f)
        if st < 1.0:
            continue
        salvo_attr_on += 1
        if st > frame_f:
            continue
        if en < 0.0:
            # hold
            salvo_active += 1
            salvo_geo_alive += 1
        elif en > st and st <= frame_f <= en:
            salvo_active += 1
            salvo_geo_alive += 1
        elif en >= 1.0 and frame_f <= (en + max(0.0, fade)):
            # echo / collapse ещё рисует колонну (BUILD_GRID до COL_FLY)
            salvo_geo_alive += 1

    # hold/echo: ~128 ячеек на частицу; fly + Count≥1: × floor(Count)
    hold_cells = salvo_geo_alive * _KICK_GRID_CELLS_EST
    fly_mult = max(1, int(count)) if count >= 1.0 else 1
    est_cells = hold_cells * fly_mult
    # пик «если все keyed-ноты одновременно в echo» — для диагностики накопления
    est_peak_if_stacked = notes_attr_on * burst * _KICK_GRID_CELLS_EST * fly_mult

    level = 0
    reasons = []
    if burst >= 8:
        level = max(level, 2)
        reasons.append(f"BurstCount={burst} (не Count!)")
    elif burst >= 4:
        level = max(level, 1)
        reasons.append(f"BurstCount={burst}")
    if ghosts > 0:
        level = max(level, 1)
        reasons.append(f"ghosts={ghosts}")
    if notes_live >= _WATCH_WARN_NOTES or notes_attr_on >= _WATCH_WARN_NOTES:
        level = max(level, 1)
        reasons.append(f"notes_live={notes_live}/attr_on={notes_attr_on}")
    if notes_live >= _WATCH_CRIT_NOTES or notes_attr_on >= _WATCH_CRIT_NOTES:
        level = max(level, 2)
    if salvo_geo_alive >= _WATCH_WARN_SALVO:
        level = max(level, 1)
        reasons.append(f"salvo_geo_alive={salvo_geo_alive}")
    if salvo_geo_alive >= _WATCH_CRIT_SALVO:
        level = max(level, 2)
    if est_cells >= _WATCH_WARN_CELLS:
        level = max(level, 1)
        reasons.append(f"est_cells≈{est_cells}")
    if est_cells >= _WATCH_CRIT_CELLS or est_peak_if_stacked >= _WATCH_CRIT_CELLS:
        level = max(level, 2)
        if est_peak_if_stacked >= _WATCH_CRIT_CELLS:
            reasons.append(f"stacked_peak≈{est_peak_if_stacked}")

    return {
        "ch": ch_idx,
        "frame": int(frame_f),
        "buf": buf.name,
        "notes_attr_on": notes_attr_on,
        "notes_live": notes_live,
        "notes_held": notes_held,
        "ghosts": ghosts,
        "ghost_slots": ghost_slots,
        "salvo_attr_on": salvo_attr_on,
        "salvo_active": salvo_active,
        "salvo_geo_alive": salvo_geo_alive,
        "burst": burst,
        "kick_burst_factor": kick_burst_factor,
        "count": count,
        "fade": fade,
        "hold_cells": hold_cells,
        "est_cells": est_cells,
        "est_peak_if_stacked": est_peak_if_stacked,
        "level": level,
        "reasons": reasons,
    }


def watch_kick_buffer_pressure(scene):
    """
    frame_change_post: если давление Kick близко к OOM — печатает в консоль Blender.
    Не спамит: только при смене уровня/ключевых метрик или раз в ~45 кадров на WARN+.
    """
    try:
        scrub_phantom_buffers_on_scene(scene)
        purge_orphan_note_attrs_if_canvas_empty(scene)
    except Exception as e:
        print(f"[Octavia] orphan/phantom scrub: {e}")
    try:
        max_ch = int(getattr(scene, "octavia_channel_count", 8) or 8)
    except Exception:
        max_ch = 8
    frame = int(scene.frame_current)
    for ch in range(1, max_ch + 1):
        snap = scan_channel_kick_pressure(scene, ch, float(frame))
        if not snap:
            continue
        level = snap["level"]
        sig = (
            level,
            snap["notes_attr_on"],
            snap["notes_live"],
            snap.get("salvo_geo_alive", snap["salvo_active"]),
            snap["ghosts"],
            int(snap["count"]),
            snap["burst"],
        )
        prev = _watch_last_sig.get(ch)
        last_pf = _watch_last_print_frame.get(ch, -9999)
        changed = prev != sig
        heartbeat = level >= 1 and (frame - last_pf) >= 45
        if level <= 0:
            if prev and prev[0] > 0:
                print(
                    f"[Octavia WATCH] Ch{ch} OK f={frame} "
                    f"notes_live={snap['notes_live']} "
                    f"salvo_geo={snap.get('salvo_geo_alive', 0)} ghosts={snap['ghosts']}"
                )
                _watch_last_print_frame[ch] = frame
            _watch_last_sig[ch] = sig
            continue
        if not (changed or heartbeat):
            _watch_last_sig[ch] = sig
            continue

        tag = "CRITICAL" if level >= 2 else "WARN"
        why = ", ".join(snap["reasons"]) if snap["reasons"] else "threshold"
        print(
            f"[Octavia WATCH {tag}] Ch{ch} f={frame} buf={snap['buf']}\n"
            f"  notes: live={snap['notes_live']} held={snap.get('notes_held', 0)} "
            f"attr_on={snap['notes_attr_on']} ghosts={snap['ghosts']} slots={snap['ghost_slots']}\n"
            f"  salvo: geo_alive={snap.get('salvo_geo_alive', 0)} "
            f"in_body={snap['salvo_active']} keyed={snap['salvo_attr_on']}\n"
            f"  macros: BurstCount(N particles)={snap['burst']}  "
            f"KickColCount/Count={snap['count']:.3f}  "
            f"KickBurst(factor)={snap.get('kick_burst_factor', 0):.3f}  "
            f"Fade={snap.get('fade', 0):.1f}\n"
            f"  est: geo_alive×{_KICK_GRID_CELLS_EST} → ~{snap['est_cells']}  "
            f"stacked_peak(notes×burst×grid)≈{snap.get('est_peak_if_stacked', 0)}\n"
            f"  why: {why}\n"
            f"  hint: Count≠BurstCount. Взрыв при Count=1 почти всегда из BurstCount "
            f"(oc_m_burst_count, дефолт графа ~13) × BUILD_GRID×Realize на hold/echo."
        )
        _watch_last_sig[ch] = sig
        _watch_last_print_frame[ch] = frame


def _ensure_mesh_action(mesh, action_name="Octavia_BufferAction"):
    if not mesh.animation_data:
        mesh.animation_data_create()
    if not mesh.animation_data.action:
        mesh.animation_data.action = bpy.data.actions.new(name=action_name)
    return mesh.animation_data.action


def _clear_note_attribute_curves(mesh):
    """Сносит note/salvo-кривые и обнуляет зону А (0–127) + зону В залпов (160–2207)."""
    ensure_buffer_topology(mesh)
    if mesh.animation_data and mesh.animation_data.action:
        act = mesh.animation_data.action
        for fc, owner in list(iter_action_fcurves_with_owners(act)):
            if not _is_note_attr_path(safe_fcurve_data_path(fc)):
                continue
            try:
                for kp in reversed(list(fc.keyframe_points)):
                    fc.keyframe_points.remove(kp)
            except Exception:
                pass
            if owner is not None:
                try:
                    owner.remove(fc)
                except Exception:
                    try:
                        # некоторые коллекции не умеют remove — оставляем пустую кривую
                        fc.update()
                    except Exception:
                        pass

        # Если нот не осталось — отвязываем action (как ластик)
        remaining = 0
        if mesh.animation_data.action:
            for fc in iter_action_fcurves(mesh.animation_data.action):
                remaining += len(fc.keyframe_points)
            if remaining == 0:
                mesh.animation_data.action = None

    for i in range(min(NOTE_SLOT_COUNT, len(mesh.vertices))):
        _reset_note_attr_vert(mesh, i)
    for i in range(SALVO_BASE, min(BUFFER_VERT_COUNT, len(mesh.vertices))):
        _reset_note_attr_vert(mesh, i)
    # Зона голоса 128–159: voice_id тоже не должен светиться в spreadsheet
    for i in range(VOICE_ZONE_START, min(VOICE_ZONE_START + VOICE_ZONE_COUNT, len(mesh.vertices))):
        attr = mesh.attributes.get("octavia_voice_id")
        if attr and i < len(attr.data):
            attr.data[i].value = -1.0
    clear_note_timing_maps_cache()


def _restore_note_curves_via_keyframes(mesh, curves_data):
    """Восстанавливает ноты через keyframe_insert — совместимо с Blender 5.1 layers."""
    if not curves_data:
        # Уже должно быть чисто после _clear_note_attribute_curves
        return

    ensure_buffer_topology(mesh)
    _ensure_mesh_action(mesh, action_name=f"{mesh.name}_Action")
    for snap_key, kps_data in curves_data.items():
        data_path, array_index = _split_curve_snapshot_key(snap_key)
        if not _is_note_attr_path(data_path):
            continue
        attr_name, slot_idx = _parse_note_attr_path(data_path)
        if attr_name is None:
            print(f"    ⚠️ Undo: не разобрал data_path: {data_path}")
            continue
        attr = mesh.attributes.get(attr_name)
        if not attr or slot_idx >= len(attr.data):
            continue

        is_vec = attr_name in _VECTOR_NOTE_ATTRS
        if is_vec:
            canon_path = f'attributes["{attr_name}"].data[{slot_idx}].vector'
        else:
            canon_path = f'attributes["{attr_name}"].data[{slot_idx}].value'

        for f_frame, val, _interp in sorted(kps_data, key=lambda x: x[0]):
            try:
                if is_vec:
                    from mathutils import Vector
                    vec = Vector(attr.data[slot_idx].vector)
                    ai = int(array_index)
                    if 0 <= ai < 3:
                        vec[ai] = float(val)
                    attr.data[slot_idx].vector = vec
                    mesh.keyframe_insert(
                        data_path=canon_path,
                        index=ai,
                        frame=int(round(f_frame)),
                    )
                else:
                    attr.data[slot_idx].value = float(val)
                    mesh.keyframe_insert(data_path=canon_path, frame=int(round(f_frame)))
            except Exception as e_ins:
                print(f"    💥 Undo keyframe_insert ({f_frame}, {val}) на {canon_path}: {e_ins}")

    if mesh.animation_data and mesh.animation_data.action:
        for fc in iter_action_fcurves(mesh.animation_data.action):
            if _is_note_attr_path(getattr(fc, "data_path", "")):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'
                fc.update()


def push_undo_step(context, target_channels):
    import sys
    if not target_channels:
        return
       
    snapshot = capture_daw_snapshot(context, target_channels)
    if snapshot:
        if not hasattr(sys, "_octavia_undo_stack"):
            sys._octavia_undo_stack = []
        if not hasattr(sys, "_octavia_redo_stack"):
            sys._octavia_redo_stack = []
           
        sys._octavia_undo_stack.append(snapshot)
        sys._octavia_redo_stack.clear()
        print(f"[Octavia Undo] push channels={list(target_channels)} stack={len(sys._octavia_undo_stack)}")
       
        if len(sys._octavia_undo_stack) > 100:
            sys._octavia_undo_stack.pop(0)


def apply_daw_snapshot(context, snapshot):
    """Полный откат канала: снос текущих нот + восстановление из слепка."""
    import sys
    scene = context.scene
    if not snapshot:
        return

    from .input_handlers.operator import OCTAVIA_OT_ui_handler
    OCTAVIA_OT_ui_handler._block_sync_callbacks = True
    
    try:
        if 'voices_props' in snapshot and hasattr(scene, "octavia_channels_data"):
            for c_idx, ch_v_list in snapshot['voices_props'].items():
                if c_idx <= len(scene.octavia_channels_data):
                    ch_data = scene.octavia_channels_data[c_idx - 1]
                    for v_idx, saved_v in enumerate(ch_v_list):
                        if v_idx < len(ch_data.voices):
                            v = ch_data.voices[v_idx]
                            v.punch = saved_v['punch']
                            v.hold = saved_v['hold']
                            v.echo = saved_v['echo']
                            v.key_code = saved_v['key_code']
                            v.name = saved_v['name']
                            v.macro_overrides.clear()
                            for mo_data in saved_v.get('macro_overrides', []):
                                mo = v.macro_overrides.add()
                                mo.name = mo_data['macro_id']
                                mo.macro_id = mo_data['macro_id']
                                mo.value = mo_data['value']

        for ch, curves_data in snapshot['channels'].items():
            buf_name = f"Octavia_Buffer_Ch_{ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not buf_obj or not buf_obj.data:
                print(f"    ❌ Undo: буфер {buf_name} не найден")
                continue

            mesh = buf_obj.data
            n_paths = len(curves_data) if curves_data else 0
            print(f"[Octavia Undo] apply ch={ch} restore_paths={n_paths}")
            try:
                _clear_note_attribute_curves(mesh)
                _restore_note_curves_via_keyframes(mesh, curves_data)
                mesh.update()
                buf_obj.update_tag()
            except Exception as e_ch:
                print(f"    ❌ Undo канала {ch}: {e_ch}")

        scene.octavia_selected_blocks.clear()
        for b_name in snapshot.get('selected_blocks', []):
            scene.octavia_selected_blocks.add().name = b_name

        # После полного restore кривых «виртуальное удаление» не нужно.
        # Раньше слепок ластика сохранял ID уже стёртых блоков → undo возвращал
        # данные, а UI продолжал их прятать (невидимый барьер).
        sys._octavia_virtual_erased = set()

        try:
            current_f = scene.frame_current
            scene.frame_set(current_f)
            context.view_layer.update()
        except Exception as e_scene:
            print(f"  ⚠️ Undo view_layer: {e_scene}")
    finally:
        OCTAVIA_OT_ui_handler._block_sync_callbacks = False


def execute_octavia_undo(context):
    import sys
    if not hasattr(sys, "_octavia_undo_stack") or not sys._octavia_undo_stack:
        print("[Octavia Undo] стек пуст — нечего откатывать")
        return False
       
    snapshot_to_restore = sys._octavia_undo_stack.pop()
    target_channels = list(snapshot_to_restore['channels'].keys())
    print(f"[Octavia Undo] UNDO channels={target_channels} remaining={len(sys._octavia_undo_stack)}")
    
    redo_snapshot = capture_daw_snapshot(context, target_channels)
    if redo_snapshot:
        if not hasattr(sys, "_octavia_redo_stack"):
            sys._octavia_redo_stack = []
        sys._octavia_redo_stack.append(redo_snapshot)
       
    apply_daw_snapshot(context, snapshot_to_restore)
   
    if context.active_object:
        try:
            context.active_object.update_tag()
        except Exception:
            pass
    try:
        bpy.ops.octavia.rescan_macros()
    except Exception:
        pass
    return True


def execute_octavia_redo(context):
    import sys
    if not hasattr(sys, "_octavia_redo_stack") or not sys._octavia_redo_stack:
        print("[Octavia Undo] redo-стек пуст")
        return False
       
    snapshot_to_restore = sys._octavia_redo_stack.pop()
    target_channels = list(snapshot_to_restore['channels'].keys())
    print(f"[Octavia Undo] REDO channels={target_channels}")
    
    undo_snapshot = capture_daw_snapshot(context, target_channels)
    if undo_snapshot:
        if not hasattr(sys, "_octavia_undo_stack"):
            sys._octavia_undo_stack = []
        sys._octavia_undo_stack.append(undo_snapshot)
       
    apply_daw_snapshot(context, snapshot_to_restore)
   
    if context.active_object:
        try:
            context.active_object.update_tag()
        except Exception:
            pass
    try:
        bpy.ops.octavia.rescan_macros()
    except Exception:
        pass
    return True

class OCTAVIA_OT_vj_listener(bpy.types.Operator):
    bl_idname = "octavia.vj_listener"
    bl_label = "Octavia Listener"

    # Модалка не сериализуется в .blend — после load/restart флаг LIVE может быть True,
    # а слушатель мёртв. Этот маркер живёт только в рантайме.
    _running = False
   
    def modal(self, context, event):
        if not context.scene.vj_record_mode:
            OCTAVIA_OT_vj_listener._running = False
            return {'FINISHED'}
           
        if event.type == 'TIMER':
            return {'PASS_THROUGH'}
           
        triggered = False
        ch_idx = context.scene.octavia_active_channel
        if len(context.scene.octavia_channels_data) >= ch_idx:
            ch_data = context.scene.octavia_channels_data[ch_idx - 1]
           
            # 🛸 САМОЛЕЧЕНИЕ ИНДЕКСОВ СТАРЫХ ГОЛОСОВ (VOICE ID ANTI-COLLISION)
            # Если Блендер занулил hardware_id у старых вкладок, принудительно разводим их по уникальным этажам
            hw_ids = [v.hardware_id for v in ch_data.voices]
            if len(hw_ids) != len(set(hw_ids)):
                for i, v in enumerate(ch_data.voices):
                    v.hardware_id = i

            # 🛡️ БРОНЕБОЙНЫЙ ЩИТ ПОВТОРОВ: Тушим автоповтор ОС для всей спарки разом
            if event.value == 'PRESS' and event.is_repeat:
                if any(event.type == voice.key_code for voice in ch_data.voices):
                    return {'RUNNING_MODAL'}
           
            # Прокатываемся по всей коллекции, передавая физический hardware_id
            for idx, voice in enumerate(ch_data.voices):
                if voice.key_code and event.type == voice.key_code:
                    if event.value == 'PRESS':
                        bpy.ops.octavia.kick_trigger(action='PRESS', voice_id=voice.hardware_id)
                        triggered = True
                    elif event.value == 'RELEASE':
                        bpy.ops.octavia.kick_trigger(action='RELEASE', voice_id=voice.hardware_id)
                        triggered = True
       
        # Если хотя бы один голос сработал — поглощаем клавишу в Октавию
        if triggered:
            return {'RUNNING_MODAL'}
            
        return {'PASS_THROUGH'}
       
    def invoke(self, context, event):
        if OCTAVIA_OT_vj_listener._running:
            return {'CANCELLED'}
        OCTAVIA_OT_vj_listener._running = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        OCTAVIA_OT_vj_listener._running = False


def ensure_vj_listener(context=None):
    """Поднимает LIVE-слушатель клавиш, если флаг включён, а модалка мертва.

    Modal-операторы не переживают закрытие Blender / File→Open / reload аддона.
    Свойство scene.vj_record_mode — переживает. Без этого моста LIVE «горит»,
    а клавиши молчат, пока не тумблернёшь режим вручную.
    """
    ctx = context or bpy.context
    scene = getattr(ctx, "scene", None)
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene or not getattr(scene, "vj_record_mode", False):
        return False
    if OCTAVIA_OT_vj_listener._running:
        return True

    wm = getattr(ctx, "window_manager", None) or getattr(bpy.context, "window_manager", None)
    window = getattr(ctx, "window", None)
    if window is None and wm and wm.windows:
        window = wm.windows[0]
    if window is None:
        return False

    try:
        with bpy.context.temp_override(window=window):
            bpy.ops.octavia.vj_listener('INVOKE_DEFAULT')
    except Exception as e:
        print(f"[Octavia] LIVE listener revive failed: {e}")
        OCTAVIA_OT_vj_listener._running = False
        return False

    return bool(OCTAVIA_OT_vj_listener._running)


def _timer_ensure_vj_listener():
    ensure_vj_listener()
    return None


class OCTAVIA_OT_kick_trigger(bpy.types.Operator):
    bl_idname = "octavia.kick_trigger"
    bl_label = "Trigger Octavia Kick"
   
    # 🔥 ЖЕЛЕЗНЫЙ ФИКС RNA-РЕГИСТРАЦИИ: Переводим свойства на аннотации типов Блендера
    action: bpy.props.EnumProperty(
        items=[('PRESS', "Press", ""), ('RELEASE', "Release", "")],
        default='PRESS'
    )
    voice_id: bpy.props.IntProperty(default=0, description="Индекс голоса в коллекции канала")

    def execute(self, context):
        scene = context.scene
        active_ch = scene.octavia_active_channel
        fps = scene.render.fps if scene.render.fps > 0 else 24

        # 🪐 ФАЗА 1: НАЖАТИЕ КНОПКИ (ВЫДЕЛЕНИЕ АНАЛИТИЧЕСКОГО СЛОТА)
        if self.action == 'PRESS':
            raw_frame = scene.frame_current
           
            if getattr(scene, "octavia_snap", True):
                target_frame = snap_frame_to_grid(
                    raw_frame, scene.octavia_bpm, fps, daw_pixels_per_second(scene),
                )
                target_frame = max(1, min(scene.frame_end, target_frame))
            else:
                target_frame = raw_frame

            buf_name = f"Octavia_Buffer_Ch_{active_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if not buf_obj or not buf_obj.data:
                return {'CANCELLED'}
               
            mesh = buf_obj.data
            
            # =========================================================================
            # 🛸 СУВЕРЕННЫЙ ДВИГАТЕЛЬ МИГРАЦИИ ОКТАВИИ (ВСТАВЛЯТЬ СТРОГО СЮДА)
            # =========================================================================
            required_attrs = {
                "start_frame": -1.0,
                "end_frame": -1.0,
                "octavia_voice_id": -1.0,
                "octavia_macro_punch": 0.5,
                "octavia_macro_hold": 0.5,
                "octavia_macro_echo": 0.5
            }
            mesh_was_outdated = False
            for attr_name, default_val in required_attrs.items():
                if attr_name not in mesh.attributes:
                    mesh.attributes.new(name=attr_name, type='FLOAT', domain='POINT')
                    # Инициализируем новые ячейки безопасными значениями
                    for d in mesh.attributes[attr_name].data:
                        d.value = default_val
                    mesh_was_outdated = True

            if ensure_buffer_topology(mesh):
                mesh_was_outdated = True
            
            if mesh_was_outdated:
                mesh.update()
                buf_obj.update_tag()
            # =========================================================================

            start_attr = mesh.attributes.get("start_frame")
            end_attr = mesh.attributes.get("end_frame")
            voice_id_attr = mesh.attributes.get("octavia_voice_id")
            if not start_attr or not end_attr:
                return {'CANCELLED'}

            # 🛡️ ЧИТАЕМ СТЕЙТЫ НАПРЯМУЮ ИЗ АНИМАЦИОННЫХ КРИВЫХ БЛЕНДЕРА
            active_slots = {}  # slot_idx -> last_start_frame
            held_slots = set() # слоты, у которых нота сейчас зажата (end_frame == -1)
            
            if mesh.animation_data and mesh.animation_data.action:
                act = mesh.animation_data.action
                curves = list(getattr(act, "curves", getattr(act, "fcurves", [])))
                if hasattr(act, "layers"):
                    for layer in act.layers:
                        for strip in getattr(layer, "strips", []):
                            for bag in getattr(strip, "channelbags", []): 
                                curves.extend(getattr(bag, "fcurves", []))
                                
                import re
                for fc in curves:
                    if not fc.data_path: continue
                    match = re.search(r'data\[(\d+)\]', fc.data_path)
                    if not match: continue
                    idx = int(match.group(1))
                    # Зона В (залп) тоже пишет start_frame — не путать с нотными слотами UI
                    if not is_note_slot_index(idx):
                        continue
                    
                    if "start_frame" in fc.data_path and fc.keyframe_points:
                        # Берем кадр последнего удара в этом слоте
                        active_slots[idx] = fc.keyframe_points[-1].co[1]
                    if "end_frame" in fc.data_path and fc.keyframe_points:
                        # Если последнее значение -1.0, значит нота еще удерживается
                        if fc.keyframe_points[-1].co[1] == -1.0:
                            held_slots.add(idx)

            # =========================================================================
            # 🛡️ ЗАЩИТА СТАРЫХ СОХРАНЕНИЙ: Динамический лимит слотов вместо хардкода 128
            # =========================================================================
            max_slots = 128 if len(start_attr.data) >= 128 else len(start_attr.data)
            # =========================================================================

            # Ищем идеальный пустой или освободившийся слот
            chosen_idx = -1
            
            # 1. Абсолютно чистый слот
            for i in range(max_slots):
                if i not in active_slots and i not in held_slots:
                    chosen_idx = i
                    break
            
            # 2. Переиспользование — только если ВСЕ ключи слота раньше нового удара
            if chosen_idx == -1:
                released_slots = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                    and slot_is_free_before(mesh, idx, target_frame)
                }
                if released_slots:
                    chosen_idx = min(released_slots, key=released_slots.get)
            
            # 3. Крайний случай: незажатый слот, но только без пересечения по времени
            if chosen_idx == -1:
                released_any = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                    and slot_is_free_before(mesh, idx, target_frame)
                }
                if released_any:
                    chosen_idx = min(released_any, key=released_any.get)
            
            # 4. Паника: любой незажатый (может пересечься — крайний случай)
            if chosen_idx == -1:
                released_overlap = {
                    idx: f for idx, f in active_slots.items()
                    if idx not in held_slots and idx < max_slots
                }
                if released_overlap:
                    chosen_idx = min(released_overlap, key=released_overlap.get)
            
            # 5. Всё зажато — сбиваем самый старый активный
            if chosen_idx == -1:
                valid_active = {idx: f for idx, f in active_slots.items() if idx < max_slots}
                chosen_idx = min(valid_active, key=valid_active.get) if valid_active else 0

            # Записываем физические данные в меш и сразу жестко запекаем ключевой кадр
            start_attr.data[chosen_idx].value = float(target_frame)
            end_attr.data[chosen_idx].value = -1.0
            if voice_id_attr:
                voice_id_attr.data[chosen_idx].value = float(self.voice_id)
           
            start_path = f'attributes["start_frame"].data[{chosen_idx}].value'
            end_path = f'attributes["end_frame"].data[{chosen_idx}].value'
            voice_id_path = f'attributes["octavia_voice_id"].data[{chosen_idx}].value'
           
            mesh.keyframe_insert(data_path=start_path, frame=target_frame)
            mesh.keyframe_insert(data_path=end_path, frame=target_frame)
            if voice_id_attr:
                mesh.keyframe_insert(data_path=voice_id_path, frame=target_frame)

            # Live-черновик hit/burst на PRESS (сразу видно во вьюпорте).
            # Истина при проигрывании — resolve-at-onset: при входе playhead в ноту
            # process_emitter_onset_resolves пересемплит эмиттер и перезапишет freeze.
            emitter = resolve_channel_emitter(context, active_ch)
            hit_pos, hit_nml = sample_emitter_basis(emitter)
            write_hit_snapshot(mesh, chosen_idx, hit_pos, hit_nml, target_frame)

            # Сальво-Матрица: N фейсов (или pivot-fallback) → зона 160+
            burst_n = max(1, read_burst_count(mesh, self.voice_id, default=1))
            seed = int(target_frame) + int(chosen_idx) + int(self.voice_id)
            samples = sample_salvo_faces(context, emitter, burst_n, seed)
            if not samples:
                samples = [sample_emitter_basis(emitter)]
            write_salvo_block(
                mesh, chosen_idx, samples, target_frame,
                end_hold=-1.0, voice_id=float(self.voice_id),
            )
            # Сброс latch+freeze — следующий play-вход пересемплит (после сдвига куба тоже).
            _onset_latch.pop((active_ch, chosen_idx), None)
            _clear_onset_freeze_for_slot(active_ch, chosen_idx)
            clear_note_timing_maps_cache()

            # Выпрямление f-кривых (Бронебойный сканер Blender 5.1+)
            if mesh.animation_data and mesh.animation_data.action:
                for fc in iter_action_fcurves(mesh.animation_data.action):
                    if hasattr(fc, "data_path") and "attributes" in fc.data_path:
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'CONSTANT'
                        fc.update()

        # 🪐 ФАЗА 2: ОТПУСКАНИЕ КНОПКИ (ЗАКРЫТИЕ ВСЕХ АКТИВНЫХ ГОЛОСОВ ТРЕКА)
        elif self.action == 'RELEASE':
            raw_release_frame = scene.frame_current
           
            if getattr(scene, "octavia_snap", True):
                target_release_frame = snap_frame_to_grid(
                    raw_release_frame, scene.octavia_bpm, fps, daw_pixels_per_second(scene),
                )
            else:
                target_release_frame = raw_release_frame

            buf_name = f"Octavia_Buffer_Ch_{active_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data:
                mesh = buf_obj.data
                ensure_buffer_topology(mesh)
                start_attr = mesh.attributes.get("start_frame")
                end_attr = mesh.attributes.get("end_frame")
               
                if start_attr and end_attr:
                    voice_id_attr = mesh.attributes.get("octavia_voice_id")
                   
                    # Закрываем только ноты, реально удерживаемые НА КАДРЕ отпускания.
                    # Сырой end_attr.data[i] нельзя — rescan/старые данные дают -1 на всех слотах.
                    for i in range(min(128, len(end_attr.data))):
                        v_id_on_vertex = voice_id_attr.data[i].value if voice_id_attr else 0.0
                        if float(self.voice_id) != v_id_on_vertex:
                            continue
                        start_at_rel = fcurve_slot_value(mesh, i, "start_frame", target_release_frame)
                        end_at_rel = fcurve_slot_value(mesh, i, "end_frame", target_release_frame)
                        if start_at_rel is None or end_at_rel is None:
                            continue
                        if start_at_rel < 1.0 or start_at_rel > float(target_release_frame):
                            continue
                        if end_at_rel >= 0.0:
                            continue
                        final_release = max(start_at_rel + 2.0, float(target_release_frame))
                        end_attr.data[i].value = final_release
                        end_path = f'attributes["end_frame"].data[{i}].value'
                        mesh.keyframe_insert(data_path=end_path, frame=final_release)
                        sync_salvo_end_frame(mesh, i, final_release)

                    if mesh.animation_data and mesh.animation_data.action:
                        for fc in iter_action_fcurves(mesh.animation_data.action):
                            if hasattr(fc, "data_path") and "end_frame" in fc.data_path:
                                for kp in fc.keyframe_points:
                                    kp.interpolation = 'CONSTANT'
                                fc.update()

        buf_name = f"Octavia_Buffer_Ch_{active_ch}"
        buf_obj = scene.objects.get(buf_name)
        if buf_obj:
            buf_obj.update_tag()
           
        context.view_layer.update()
        return {'FINISHED'}
    
class OCTAVIA_OT_toggle_mode(bpy.types.Operator):
    bl_idname = "octavia.toggle_mode"
    bl_label = "Toggle Octavia Mode"
   
    def execute(self, context):
        scene = context.scene
        scene.vj_record_mode = not scene.vj_record_mode

        if scene.vj_record_mode:
            ensure_vj_listener(context)
        else:
            # Модалка сама завершится на следующем событии; маркер сбрасываем сразу,
            # чтобы самолечение не считало её живой.
            OCTAVIA_OT_vj_listener._running = False

        obj = context.active_object
        if obj:
            obj.update_tag()
            context.view_layer.update()
        return {'FINISHED'}