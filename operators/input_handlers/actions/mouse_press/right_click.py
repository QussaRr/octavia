import bpy
import sys

from ...radar.eraser import apply_quantum_eraser, resolve_eraser_hardware_id


def handle_right_clicks(self, context, event, layout, mx, my, area):
    scene = context.scene
    left_margin, header_w = layout['left_margin'], layout['header_w']
    track_x, track_y = layout['track_x'], layout['track_y']
    fps = layout['fps']

    if getattr(self, "_is_dragging", False) or getattr(self, "_is_resizing", False) or getattr(self, "_is_box_selecting", False):
        return {'RUNNING_MODAL'}

    if hasattr(sys, "_octavia_clipboard"):
        sys._octavia_clipboard.clear()

    # А: Точечное физическое удаление оранжевого блока через ПКМ клик
    hovered_block_ch = scene.get("octavia_hovered_block_ch", -1)
    if hovered_block_ch != -1 and context.active_object:
        b_ch = hovered_block_ch
        b_voice = scene["octavia_hovered_block_voice"]
        b_frame = scene["octavia_hovered_block_frame"]
        dead_id = f"ch_{b_ch}_idx_{b_voice}_f_{b_frame:.1f}"
       
        if not hasattr(sys, "_octavia_virtual_erased"):
            sys._octavia_virtual_erased = set()
        sys._octavia_virtual_erased.add(dead_id)
       
        bpy.ops.octavia.commit_eraser_transaction()
       
        scene["octavia_hovered_block_ch"] = -1
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # Б: Инициализация багровой зоны зачистки (ПКМ драг) — lock на канал+голос зажима
    m_ch = scene.get("octavia_mouse_ch", -1)
    m_frame = scene.get("octavia_mouse_frame", -1.0)
    m_voice = int(scene.get("octavia_mouse_voice", 0))
   
    if m_ch > 0 and m_frame >= 1.0:
        self._is_erasing = True
        self._eraser_ch = m_ch
        self._eraser_voice_lane = m_voice
        self._eraser_hw_id = resolve_eraser_hardware_id(scene, m_ch, m_voice)
        self._eraser_width_frames = float(int(round(fps * 0.5)))
       
        scene["octavia_eraser_active"] = True
        scene["octavia_eraser_ch"] = m_ch
        scene["octavia_eraser_voice"] = m_voice
        scene["octavia_eraser_frame"] = m_frame
        scene["octavia_eraser_width"] = self._eraser_width_frames

        # Сразу задеть блоки под курсором (не ждать первого mousemove)
        apply_quantum_eraser(self, context, m_frame)
       
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # В: Физическая утилизация канала целиком через ПКМ по хедеру плашки
    for i in range(1, scene.octavia_channel_count + 1):
        ch_y = track_y - (i * 48)
        if (left_margin <= mx <= header_w + left_margin) and (ch_y <= my <= ch_y + 40):
            bpy.ops.octavia.delete_channel(channel_idx=i)
            return {'RUNNING_MODAL'}
           
    return None
