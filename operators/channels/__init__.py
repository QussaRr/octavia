from .properties import OctaviaMacroOverride, OctaviaMacroSettings, OctaviaExposedMacro, OctaviaVoiceSettings, OctaviaChannelSettings
from .diagnostics import (
    OCTAVIA_OT_rescan_macros,
    OCTAVIA_OT_snapshot_graph,
    OCTAVIA_OT_export_authoring_kit,
)
from .buffer_snapshot import OCTAVIA_OT_snapshot_buffer
from .management import OCTAVIA_OT_rename_channel_popup, OCTAVIA_OT_add_channel, OCTAVIA_OT_delete_channel, OCTAVIA_OT_delete_voice
from .clipboard import OCTAVIA_OT_copy_pulses, OCTAVIA_OT_paste_pulses, OCTAVIA_OT_commit_eraser_transaction

classes = (
    OctaviaMacroOverride,
    OctaviaMacroSettings,
    OctaviaExposedMacro,
    OctaviaVoiceSettings,
    OctaviaChannelSettings,
    OCTAVIA_OT_rescan_macros,
    OCTAVIA_OT_snapshot_graph,
    OCTAVIA_OT_snapshot_buffer,
    OCTAVIA_OT_export_authoring_kit,
    OCTAVIA_OT_rename_channel_popup,
    OCTAVIA_OT_add_channel,
    OCTAVIA_OT_delete_channel,
    OCTAVIA_OT_delete_voice,
    OCTAVIA_OT_copy_pulses,
    OCTAVIA_OT_paste_pulses,
    OCTAVIA_OT_commit_eraser_transaction,
)
