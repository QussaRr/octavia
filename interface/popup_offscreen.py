"""GPUOffScreen-песочница HUD-попапа Octavia.

Шаг 1: интерфейс рисуется один раз в изолированный буфер (логические coords,
HiDPI через preferences.system.pixel_size). CLIP_EDITOR и VIEW_3D
только штампуют готовую текстуру в свои region-координаты.

Шаг 2: CLIP штампует as-is (эталон). VIEW_3D — GLSL sRGB→Linear под
Overlay sRGB-framebuffer. Dual scale lo/hi (fon× / UI×); авто-gain убран.

Шаг 3: window overlay из Python недоступен (FB = region; border поверх).
Dual-region blit + хамелеон; gutters нет. Настоящий overlay — форк/C.

Перерисовка буфера — только по content_dirty (мутация стейта).
Перетаскивание окна буфер не трогает.

Важно: OffScreen.bind() + смена projection ЛОМАЕТ матрицу текущего
region. После песочницы обязательно восстанавливаем POST_PIXEL ortho.
"""

from __future__ import annotations

import math

import bpy
import gpu
from gpu_extras.presets import draw_texture_2d
from mathutils import Matrix

_offscreen = None
_off_fb_w = 0
_off_fb_h = 0
_logical_w = 0
_logical_h = 0
_dirty = True
_decompensate_shader = None


def invalidate_popup_offscreen():
    """Пометить текстуру устаревшей (контент попапа изменился)."""
    global _dirty
    _dirty = True


def free_popup_offscreen():
    """Освободить GPU-ресурсы (unregister / закрытие попапа)."""
    global _offscreen, _off_fb_w, _off_fb_h, _logical_w, _logical_h, _dirty
    global _decompensate_shader
    if _offscreen is not None:
        try:
            _offscreen.free()
        except Exception:
            pass
    _offscreen = None
    _off_fb_w = 0
    _off_fb_h = 0
    _logical_w = 0
    _logical_h = 0
    _dirty = True
    # Шейдер пересоздаём при unload (смена fragment / uniforms)
    _decompensate_shader = None


def _pixel_size(context):
    sys = context.preferences.system
    ps = float(getattr(sys, "pixel_size", 1.0) or 1.0)
    return max(1.0, ps)


def _ortho_pixel(width, height):
    """Ортография: (0,0) низ-лево → (width, height) верх-право."""
    width = max(1.0, float(width))
    height = max(1.0, float(height))
    return Matrix((
        (2.0 / width, 0.0, 0.0, -1.0),
        (0.0, 2.0 / height, 0.0, -1.0),
        (0.0, 0.0, -1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))


def restore_region_pixel_matrix(region):
    """Вернуть POST_PIXEL ortho текущего region после OffScreen.bind()."""
    if region is None:
        return
    gpu.matrix.load_matrix(Matrix.Identity(4))
    gpu.matrix.load_projection_matrix(
        _ortho_pixel(region.width, region.height)
    )


def _ensure_offscreen(fb_w, fb_h):
    global _offscreen, _off_fb_w, _off_fb_h
    fb_w = max(1, int(fb_w))
    fb_h = max(1, int(fb_h))
    if _offscreen is not None and _off_fb_w == fb_w and _off_fb_h == fb_h:
        return _offscreen
    if _offscreen is not None:
        try:
            _offscreen.free()
        except Exception:
            pass
    _offscreen = gpu.types.GPUOffScreen(fb_w, fb_h, format='RGBA8')
    _off_fb_w = fb_w
    _off_fb_h = fb_h
    return _offscreen


def ensure_popup_texture(context, handler, scene, paint_fn):
    """Пересобрать оффскрин при dirty; вернуть (texture, logical_w, logical_h) или None.

    paint_fn(context, handler, active_popup, pw, ph) — рисует в локальных
    координатах: верхний-левый угол попапа = (0, ph), низ = y=0.

    HiDPI: FB = pw*scale × ph*scale, а projection — логическая (pw × ph).
    Тогда один логический пиксель = scale физических, без monkeypatch blf.
    """
    global _dirty, _logical_w, _logical_h

    active = getattr(handler, "_active_popup", None)
    if active not in {'ADD_CHANNEL', 'PRESETS', 'CHANNEL_SETTINGS', 'BPM'}:
        return None

    from .popup_geometry import sync_popup_size
    pw, ph = sync_popup_size(handler, scene)
    pw = max(1, int(pw))
    ph = max(1, int(ph))

    # Пульс бинда клавиши — анимация, буфер надо обновлять каждый кадр
    if getattr(handler, "_waiting_for_voice_key", False):
        _dirty = True

    scale = _pixel_size(context)
    fb_w = max(1, int(math.ceil(pw * scale)))
    fb_h = max(1, int(math.ceil(ph * scale)))

    size_changed = (pw != _logical_w or ph != _logical_h)
    if size_changed:
        _dirty = True
        _logical_w = pw
        _logical_h = ph

    off = _ensure_offscreen(fb_w, fb_h)

    if _dirty:
        # Сохраняем стек матриц region ДО bind — push_pop внутри bind
        # восстанавливает только внутренний уровень; сам bind всё равно
        # оставляет region в плохом состоянии → restore снаружи обязателен.
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop():
                gpu.matrix.load_matrix(Matrix.Identity(4))
                # Логическая ortho на HiDPI FB — без pixel_scale / патча blf
                gpu.matrix.load_projection_matrix(_ortho_pixel(pw, ph))
                paint_fn(context, handler, active, pw, ph)
        _dirty = False

    return off.texture_color, pw, ph


# Дефолты с замера на шве: фон 0.5, UI/ручки 1.3
VIEW3D_POPUP_SCALE_LO = 0.5
VIEW3D_POPUP_SCALE_HI = 1.3


def _ensure_decompensate_shader():
    """VIEW_3D blit: sRGB→Linear, затем dual-scale по luma текстуры.

    Одна ручка не работает: тёмный фон и яркий UI требуют разный множитель.
    scale = mix(lo, hi, smoothstep(luma)).
    """
    global _decompensate_shader
    if _decompensate_shader is not None:
        return _decompensate_shader

    vert_out = gpu.types.GPUStageInterfaceInfo("octavia_popup_blit")
    vert_out.smooth('VEC2', "uvInterp")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('MAT4', "ModelViewProjectionMatrix")
    info.push_constant('FLOAT', "u_scale_lo")
    info.push_constant('FLOAT', "u_scale_hi")
    info.sampler(0, 'FLOAT_2D', "image")
    info.vertex_in(0, 'VEC2', "pos")
    info.vertex_in(1, 'VEC2', "texCoord")
    info.vertex_out(vert_out)
    info.fragment_out(0, 'VEC4', "fragColor")
    info.vertex_source(
        "void main()\n"
        "{\n"
        "  uvInterp = texCoord;\n"
        "  gl_Position = ModelViewProjectionMatrix * vec4(pos.xy, 0.0, 1.0);\n"
        "}\n"
    )
    info.fragment_source(
        "float srgb_to_linearrgb(float c)\n"
        "{\n"
        "  if (c < 0.04045) {\n"
        "    return (c < 0.0) ? 0.0 : c * (1.0 / 12.92);\n"
        "  }\n"
        "  return pow((c + 0.055) * (1.0 / 1.055), 2.4);\n"
        "}\n"
        "void main()\n"
        "{\n"
        "  vec4 t = texture(image, uvInterp);\n"
        "  // Luma исходного UI-цвета (заливка ~0.07, ручки/текст выше)\n"
        "  float lum = dot(t.rgb, vec3(0.2126, 0.7152, 0.0722));\n"
        "  float w = smoothstep(0.05, 0.28, lum);\n"
        "  float s = mix(u_scale_lo, u_scale_hi, w);\n"
        "  vec3 lin = vec3(\n"
        "    srgb_to_linearrgb(t.r),\n"
        "    srgb_to_linearrgb(t.g),\n"
        "    srgb_to_linearrgb(t.b)\n"
        "  );\n"
        "  fragColor = vec4(lin * s, t.a);\n"
        "}\n"
    )
    _decompensate_shader = gpu.shader.create_from_info(info)
    return _decompensate_shader


def _blit_view3d_decompensated(texture, draw_x, draw_y, pw, ph, scale_lo=0.5, scale_hi=1.3):
    """Штамп VIEW_3D: linearize + dual-scale (фон / UI)."""
    from gpu_extras.batch import batch_for_shader

    shader = _ensure_decompensate_shader()
    x1, y1 = float(draw_x), float(draw_y)
    x2, y2 = x1 + float(pw), y1 + float(ph)
    pos = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    indices = ((0, 1, 2), (0, 2, 3))
    batch = batch_for_shader(
        shader, 'TRIS', {"pos": pos, "texCoord": uvs}, indices=indices,
    )
    shader.bind()
    mvp = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
    shader.uniform_float("ModelViewProjectionMatrix", mvp)
    shader.uniform_float("u_scale_lo", float(scale_lo))
    shader.uniform_float("u_scale_hi", float(scale_hi))
    shader.uniform_sampler("image", texture)
    gpu.state.blend_set('ALPHA')
    batch.draw(shader)


def blit_popup_texture(
    texture, region, handler, scene, logical_w, logical_h, *, decompensate=False,
):
    """Штамп текстуры в текущий region (координаты region / POST_PIXEL).

    decompensate=True — VIEW_3D (sRGB→Linear × dual lo/hi).
    decompensate=False — CLIP / эталон (as-is).
    """
    if texture is None or region is None:
        return
    restore_region_pixel_matrix(region)

    from .popup_geometry import get_popup_rect_region

    px, py, pw, ph = get_popup_rect_region(handler, region, scene)
    draw_x = px
    draw_y = py - ph
    gpu.state.blend_set('ALPHA')
    if decompensate:
        lo = float(getattr(scene, "octavia_popup_v3d_scale_lo", VIEW3D_POPUP_SCALE_LO))
        hi = float(getattr(scene, "octavia_popup_v3d_scale_hi", VIEW3D_POPUP_SCALE_HI))
        _blit_view3d_decompensated(texture, draw_x, draw_y, pw, ph, scale_lo=lo, scale_hi=hi)
    else:
        draw_texture_2d(texture, (draw_x, draw_y), float(pw), float(ph))
