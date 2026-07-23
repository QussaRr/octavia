import bpy
from .channels import classes as channels_classes
from .channels.panels import OCTAVIA_PT_main_panel, OCTAVIA_PT_vsd_inspector
from .audio import OCTAVIA_OT_load_audio, OCTAVIA_OT_export_preset
from .vj_core import OCTAVIA_OT_vj_listener, OCTAVIA_OT_kick_trigger, OCTAVIA_OT_toggle_mode
from .input_handlers.operator import OCTAVIA_OT_daw_zoom, OCTAVIA_OT_ui_handler

classes = (
    *channels_classes,
    OCTAVIA_PT_main_panel,
    OCTAVIA_PT_vsd_inspector,
    OCTAVIA_OT_load_audio,
    OCTAVIA_OT_vj_listener,
    OCTAVIA_OT_kick_trigger,
    OCTAVIA_OT_toggle_mode,
    OCTAVIA_OT_export_preset,
    OCTAVIA_OT_daw_zoom,
    OCTAVIA_OT_ui_handler,
)

addon_keymaps = []

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)