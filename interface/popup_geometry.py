"""Единая геометрия HUD-попапов Octavia.

Источник правды: якорь в координатах ОКНА Blender (event.mouse_x / mouse_y).
CLIP_EDITOR / VIEW_3D только переводят якорь в локальные координаты для draw.

Hit-test и жесты — в оконных координатах. Политика закрытия (шаг 4):
ЛКМ мимо → dismiss; навигация VIEW_3D мимо окна → PASS_THROUGH без закрытия;
clamp якоря в AABB CLIP+VIEW_3D.

Якорь = ВЕРХНИЙ-левый угол попапа (как исторические _popup_x/_popup_y).
"""


DEFAULT_POPUP_W = 260
BPM_POPUP_W = 200
BPM_POPUP_H = 150
MIN_CHANNEL_SETTINGS_H = 200
BOTTOM_PAD = 12


def ensure_channel_data(scene, ch_idx):
    """Гарантирует ch_data + хотя бы один голос. Возвращает ch_data или None."""
    if ch_idx < 1:
        return None
    while len(scene.octavia_channels_data) < ch_idx:
        scene.octavia_channels_data.add()
    ch_data = scene.octavia_channels_data[ch_idx - 1]
    if len(ch_data.voices) == 0:
        v_def = ch_data.voices.add()
        v_def.name = "ГОЛОС 1"
        v_def.key_code = "K"
        v_def.hardware_id = 0
        v_def.punch = 0.5
        v_def.hold = 0.5
        v_def.echo = 0.5
    return ch_data


def _voice_tab_rows(num_voices, pw):
    """Сколько рядов займут табы голосов + кнопка [+]."""
    tx = 10
    rows = 1
    for _ in range(max(1, num_voices) + 1):
        if tx + 64 > pw - 15:
            tx = 10
            rows += 1
        tx += 68
    return rows


def calc_channel_settings_height(scene, ch_idx, pw=None):
    """Высота CHANNEL_SETTINGS — зеркало layout draw."""
    if pw is None:
        pw = DEFAULT_POPUP_W
    ch_data = ensure_channel_data(scene, ch_idx)
    n_voices = len(ch_data.voices) if ch_data else 1

    used = 22 + 14 + 8
    used += _voice_tab_rows(n_voices, pw) * 22
    used += 10
    used += 20

    all_macros = list(getattr(scene, "octavia_active_macros", []))
    hold_n = sum(1 for m in all_macros if m.category == 'HOLD')
    echo_n = sum(1 for m in all_macros if m.category == 'ECHO')
    global_n = sum(1 for m in all_macros if m.category == 'GLOBAL')

    for count in (hold_n, echo_n, global_n):
        used += 22
        used += 20 if count == 0 else count * 28

    used += 20
    used += BOTTOM_PAD
    return max(MIN_CHANNEL_SETTINGS_H, used)


# ─── Window ↔ Region ───────────────────────────────────────────────

def region_to_window(region, rx, ry):
    """Локальные координаты региона → оконные (как event.mouse_x/y)."""
    return float(region.x + rx), float(region.y + ry)


def window_to_region(region, wx, wy):
    """Оконные → локальные координаты региона."""
    return float(wx - region.x), float(wy - region.y)


def set_popup_anchor_window(handler, win_x, win_y):
    """Источник правды: верхний-левый угол попапа в оконных координатах."""
    handler._popup_win_x = float(win_x)
    handler._popup_win_y = float(win_y)


def set_popup_anchor_region(handler, region, rx, ry):
    """Задать якорь из локальных координат региона (клик/открытие в CLIP_EDITOR)."""
    wx, wy = region_to_window(region, rx, ry)
    set_popup_anchor_window(handler, wx, wy)
    # Легаси-кэш под старые читатели (регион, в котором задали)
    handler._popup_x = float(rx)
    handler._popup_y = float(ry)


def _bootstrap_win_from_legacy(handler, region=None):
    """Если win-якоря ещё нет — поднять из легаси _popup_x/_popup_y."""
    if getattr(handler, "_popup_win_x", None) is not None and getattr(handler, "_popup_win_y", None) is not None:
        return
    lx = float(getattr(handler, "_popup_x", 0) or 0)
    ly = float(getattr(handler, "_popup_y", 0) or 0)
    if region is not None:
        set_popup_anchor_region(handler, region, lx, ly)
    else:
        set_popup_anchor_window(handler, lx, ly)


def sync_popup_size(handler, scene=None):
    """Пишет актуальные pw/ph в handler под текущий _active_popup. Возвращает (pw, ph)."""
    active = getattr(handler, "_active_popup", None)
    pw = int(getattr(handler, "_popup_w", DEFAULT_POPUP_W) or DEFAULT_POPUP_W)
    ph = int(getattr(handler, "_popup_h", 300) or 300)

    if active == 'BPM':
        pw = BPM_POPUP_W
        ph = BPM_POPUP_H
    elif active == 'CHANNEL_SETTINGS' and scene is not None:
        ch_idx = int(getattr(handler, "_selected_channel_idx", 1) or 1)
        pw = pw if pw >= 200 else DEFAULT_POPUP_W
        ph = calc_channel_settings_height(scene, ch_idx, pw)
    elif active in {'ADD_CHANNEL', 'PRESETS'}:
        pw = pw if pw >= 200 else DEFAULT_POPUP_W
        ph = max(ph, 300)

    handler._popup_w = pw
    handler._popup_h = ph
    return pw, ph


def get_popup_rect_window(handler, scene=None):
    """(px, py, pw, ph) в оконных координатах. py = верх попапа."""
    _bootstrap_win_from_legacy(handler, region=None)
    pw, ph = sync_popup_size(handler, scene)
    px = float(handler._popup_win_x)
    py = float(handler._popup_win_y)
    return px, py, pw, ph


def get_popup_rect_region(handler, region, scene=None, write_legacy=False):
    """(px, py, pw, ph) в координатах данного региона — для draw.

    write_legacy=False по умолчанию: иначе VIEW_3D и CLIP_EDITOR по очереди
    затирают _popup_x/_popup_y чужими локальными координатами.
    """
    _bootstrap_win_from_legacy(handler, region=region)
    pw, ph = sync_popup_size(handler, scene)
    px, py = window_to_region(region, handler._popup_win_x, handler._popup_win_y)
    if write_legacy:
        handler._popup_x = px
        handler._popup_y = py
    return px, py, pw, ph


def get_popup_rect(handler, scene=None, region=None):
    """Совместимость: с region → локальный rect, без → оконный."""
    if region is not None:
        return get_popup_rect_region(handler, region, scene)
    return get_popup_rect_window(handler, scene)


def point_in_popup(wx, wy, handler, scene=None):
    """Hit-test в ОКОННЫХ координатах (event.mouse_x / mouse_y)."""
    px, py, pw, ph = get_popup_rect_window(handler, scene)
    return px <= wx <= px + pw and py - ph <= wy <= py


def point_in_popup_region(rx, ry, handler, region, scene=None):
    """Hit-test в локальных координатах региона."""
    px, py, pw, ph = get_popup_rect_region(handler, region, scene)
    return px <= rx <= px + pw and py - ph <= ry <= py


def resolve_popup_hit(handler, scene, wx, wy):
    """Оконный hit-frame для input: (inside, px, py, pw, ph).

    px/py — верхний-левый угол в window-space; wx/wy сравнивать с ними напрямую.
    """
    px, py, pw, ph = get_popup_rect_window(handler, scene)
    inside = px <= wx <= px + pw and py - ph <= wy <= py
    return inside, px, py, pw, ph


def find_area_under_window_point(context, wx, wy):
    """Area экрана под оконной точкой, или None."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    for area in screen.areas:
        if area.x <= wx < area.x + area.width and area.y <= wy < area.y + area.height:
            return area
    return None


def octavia_workspace_bounds(context):
    """Объединяющий AABB областей CLIP_EDITOR + VIEW_3D в Octavia DAW.

    Возвращает (min_x, min_y, max_x, max_y) в оконных координатах или None.
    """
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    min_x = min_y = None
    max_x = max_y = None
    for area in screen.areas:
        if area.type not in {'CLIP_EDITOR', 'VIEW_3D'}:
            continue
        x0, y0 = area.x, area.y
        x1, y1 = area.x + area.width, area.y + area.height
        min_x = x0 if min_x is None else min(min_x, x0)
        min_y = y0 if min_y is None else min(min_y, y0)
        max_x = x1 if max_x is None else max(max_x, x1)
        max_y = y1 if max_y is None else max(max_y, y1)
    if min_x is None:
        return None
    return float(min_x), float(min_y), float(max_x), float(max_y)


def clamp_popup_anchor(handler, context, scene=None, margin=8, keep=48):
    """Не дать попапу полностью уехать за пределы CLIP+VIEW_3D.

    `keep` — сколько пикселей окна обязано остаться видимым с каждого края.
    """
    bounds = octavia_workspace_bounds(context)
    if bounds is None:
        return
    min_x, min_y, max_x, max_y = bounds
    px, py, pw, ph = get_popup_rect_window(handler, scene)
    keep = max(24, min(keep, int(pw), int(ph)))

    lo_x = min_x - pw + keep
    hi_x = max_x - keep
    lo_y = min_y + margin + ph  # низ окна не ниже workspace
    hi_y = max_y - margin       # верх окна не выше workspace
    if hi_x < lo_x:
        lo_x = hi_x = (min_x + max_x - pw) * 0.5
    if hi_y < lo_y:
        lo_y = hi_y = (min_y + max_y + ph) * 0.5

    set_popup_anchor_window(
        handler,
        max(lo_x, min(hi_x, px)),
        max(lo_y, min(hi_y, py)),
    )


def prepare_channel_settings_popup(handler, scene, ch_idx, region=None, mx=None, my=None):
    """Открытие CHANNEL_SETTINGS: размер + якорь (mx/my — coords региона, если region дан)."""
    handler._selected_channel_idx = ch_idx
    handler._active_popup = 'CHANNEL_SETTINGS'
    handler._popup_w = DEFAULT_POPUP_W
    handler._popup_h = calc_channel_settings_height(scene, ch_idx, DEFAULT_POPUP_W)

    if mx is not None and my is not None:
        if region is not None:
            set_popup_anchor_region(handler, region, mx, my)
            # Не уезжать ниже низа региона
            rx, ry = window_to_region(region, handler._popup_win_x, handler._popup_win_y)
            if ry - handler._popup_h < 8:
                ry = handler._popup_h + 8
                set_popup_anchor_region(handler, region, rx, ry)
        else:
            set_popup_anchor_window(handler, mx, my)
            if handler._popup_win_y - handler._popup_h < 8:
                handler._popup_win_y = handler._popup_h + 8

    try:
        from .popup_draw import apply_popup_seam_chrome
        apply_popup_seam_chrome()
    except Exception:
        pass


def prepare_bpm_popup(handler, region, rx, ry):
    """Открытие TEMPO-попапа из локальных координат CLIP_EDITOR."""
    handler._active_popup = 'BPM'
    handler._popup_w = BPM_POPUP_W
    handler._popup_h = BPM_POPUP_H
    handler._hovered_bpm_btn = "NONE"
    set_popup_anchor_region(handler, region, rx, ry)
    try:
        from .popup_draw import apply_popup_seam_chrome
        apply_popup_seam_chrome()
    except Exception:
        pass
