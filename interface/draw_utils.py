"""Примитивы GPU-отрисовки Octavia (+ pixel_scale для Offscreen/HiDPI)."""

import blf
import gpu
from gpu_extras.batch import batch_for_shader

_PIXEL_SCALE = 1.0
_blf_position_orig = None
_blf_size_orig = None


def pixel_scale_begin(scale=1.0):
    """Масштаб логических UI-пикселей → пиксели GPUOffScreen (Retina/4K)."""
    global _PIXEL_SCALE, _blf_position_orig, _blf_size_orig
    _PIXEL_SCALE = max(1.0, float(scale) or 1.0)
    if _blf_position_orig is None:
        _blf_position_orig = blf.position
        _blf_size_orig = blf.size

        def _pos(font_id, x, y, z=0.0):
            s = _PIXEL_SCALE
            _blf_position_orig(font_id, x * s, y * s, z)

        def _size(font_id, size):
            s = _PIXEL_SCALE
            _blf_size_orig(font_id, max(1, int(round(float(size) * s))))

        blf.position = _pos
        blf.size = _size


def pixel_scale_end():
    global _PIXEL_SCALE, _blf_position_orig, _blf_size_orig
    if _blf_position_orig is not None:
        blf.position = _blf_position_orig
        blf.size = _blf_size_orig
        _blf_position_orig = None
        _blf_size_orig = None
    _PIXEL_SCALE = 1.0


def draw_rect(x, y, width, height, color):
    s = _PIXEL_SCALE
    x1, y1 = x * s, y * s
    x2, y2 = (x + width) * s, (y + height) * s
    vertices = [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]
    indices = [(0, 1, 2), (2, 1, 3)]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": vertices}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    r, g, b = float(color[0]), float(color[1]), float(color[2])
    a = float(color[3]) if len(color) > 3 else 1.0
    shader.uniform_float("color", (r, g, b, a))
    batch.draw(shader)
