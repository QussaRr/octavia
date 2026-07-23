import bpy

def handle_keyboard_press(self, context, event, layout, area):
    scene = context.scene
    visible_frames = layout['visible_frames']
    fps = layout['fps']

    # 🛑 ПРЕДОХРАНИТЕЛЬ: Сброс лазерного штампа по кнопке ESC
    if event.type == 'ESC':
        import sys
        if hasattr(sys, "_octavia_clipboard") and sys._octavia_clipboard:
            sys._octavia_clipboard.clear()
            area.tag_redraw()
            return {'RUNNING_MODAL'}

    # 📋 ЛОВИМ ХОТКЕЙ КОПИРОВАНИЯ РИТМА (CTRL + C)
    if event.ctrl and event.type == 'C':
        bpy.ops.octavia.copy_pulses()
        return {'RUNNING_MODAL'}

    # 📋 ЛОВИМ ХОТКЕЙ СНАЙПЕРСКОЙ ВСТАВКИ РИТМА (CTRL + V)
    elif event.ctrl and event.type == 'V':
        bpy.ops.octavia.paste_pulses()
        
        if not event.shift:
            import sys
            if hasattr(sys, "_octavia_clipboard"):
                sys._octavia_clipboard.clear()
               
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    # 🔥 МАССОВОЕ УНИЧТОЖЕНИЕ ПАЧКИ ВЫДЕЛЕННЫХ БЛОКОВ (С ПОДДЕРЖКОЙ НАДЁЖНОГО CTRL+Z)
    elif event.type in {'DEL', 'BACKSPACE'} and scene.octavia_selected_blocks:
        import sys
        if not hasattr(sys, "_octavia_virtual_erased"):
            sys._octavia_virtual_erased = set()
            
        # Сгружаем всё текущее лазурное выделение в бак ластика
        for item in scene.octavia_selected_blocks:
            sys._octavia_virtual_erased.add(item.name)
            
        # Запекаем операцию в один красивый шаг истории Блендера!
        bpy.ops.octavia.commit_eraser_transaction()
        
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    elif event.type == 'SPACE':
        if not context.screen.is_animation_playing:
            scene.octavia_auto_scroll_active = True
            scene.octavia_scroll = max(0.0, scene.frame_current - (visible_frames * 0.75))
            
    return None