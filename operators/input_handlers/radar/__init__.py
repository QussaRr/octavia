import bpy
from .utils import check_cursor_boundaries
from .popups import handle_popup_and_macros
from .grid_tracker import track_mouse_grid
from .states import process_interactive_states
from .scanners import scan_interface_hovers

def handle_mousemove(self, context, event, layout, area):
    scene = context.scene
    mx, my = layout['mx'], layout['my']
    fps, pixels_per_second = layout['fps'], layout['pixels_per_second']
    scroll_px = (scene.octavia_scroll / fps) * pixels_per_second

    # 1. Проверяем интерфейсный щит попапов и автоматизацию ручек
    if handle_popup_and_macros(self, context, mx, my, area, layout=layout):
        return {'RUNNING_MODAL'}

    # 📸 СЛУШАТЕЛЬ СТАРЫХ СОСТОЯНИЙ ДЛЯ ОПТИМИЗАЦИИ ПЕРЕРИСОВКИ ЭКРАНА
    old_ch = scene.octavia_hovered_ch
    old_part = scene.octavia_hovered_part
    old_ruler = getattr(scene, "octavia_hovered_ruler", "NONE")
    old_b_ch = scene.get("octavia_hovered_block_ch", -1)
    old_b_voice = scene.get("octavia_hovered_block_voice", -1)
    old_b_frame = scene.get("octavia_hovered_block_frame", -1.0)
    old_mouse_ch = scene.get("octavia_mouse_ch", -1)
    old_mouse_frame = scene.get("octavia_mouse_frame", -1.0)
    old_mouse_voice = scene.get("octavia_mouse_voice", 1)

    # 2. Обсчитываем точные координаты сетки Кроноса под курсором
    current_mouse_frame, current_mouse_ch, current_mouse_voice = track_mouse_grid(context, layout, mx, scroll_px)

    # 3. Обсчитываем интерактивные стейты (Драг, Ресайз, Бокс-селект, Ластик)
    if process_interactive_states(self, context, event, layout, mx, my, current_mouse_frame, current_mouse_ch, current_mouse_voice, scroll_px, area):
        return {'RUNNING_MODAL'}

    # 4. Обсчитываем финальные ховер-коллизии элементов DAW и блоков
    scan_interface_hovers(context, layout, mx, my, scroll_px)

    # Умный триггер перерисовки экрана только при реальной смене стейтов
    if (scene.octavia_hovered_ch != old_ch or scene.octavia_hovered_part != old_part or
        getattr(scene, "octavia_hovered_ruler", "NONE") != old_ruler or
        scene.get("octavia_hovered_block_ch", -1) != old_b_ch or scene.get("octavia_hovered_block_voice", -1) != old_b_voice or
        abs(scene.get("octavia_hovered_block_frame", -1.0) - old_b_frame) > 0.01 or
        scene.get("octavia_mouse_ch", -1) != old_mouse_ch or abs(scene.get("octavia_mouse_frame", -1.0) - old_mouse_frame) > 0.01 or
        scene.get("octavia_mouse_voice", 1) != old_mouse_voice):
        area.tag_redraw()
       
    return {'RUNNING_MODAL'}