import bpy

def check_cursor_boundaries(self, context, event, mx, my, area):
    is_inside_daw = (0 <= mx <= area.width and 0 <= my <= area.height)
    if event.type == 'MOUSEMOVE':
        if is_inside_daw and getattr(self, "_was_outside", False):
            context.window.cursor_set('DEFAULT')
            self._was_outside = False
        elif not is_inside_daw:
            self._was_outside = True