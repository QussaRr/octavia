import bpy

from .operators.audio import get_octavia_presets
from .operators.channels.properties import (
    OctaviaChannelSettings,
    OctaviaExposedMacro,
    OctaviaMacroSettings,
)


SCENE_PROPERTY_NAMES = [
    "vj_record_mode",
    *(f"octavia_ch{i}_{suffix}" for i in range(1, 21) for suffix in ("preset", "name")),
    "octavia_channels_data",
    "octavia_zoom",
    "octavia_scroll",
    "octavia_channel_count",
    "octavia_mute",
    "octavia_bpm",
    "octavia_snap",
    "octavia_hovered_ch",
    "octavia_hovered_part",
    "octavia_hovered_ruler",
    "octavia_active_channel",
    "octavia_auto_scroll_active",
    "octavia_active_macros",
    "octavia_selected_blocks",
    "octavia_loop_start",
    "octavia_loop_end",
    "octavia_loop_active",
    "octavia_authoring_export_dir",
    "octavia_auto_graph_snapshot",
    "octavia_auto_buffer_snapshot",
]

NODE_PROPERTY_NAMES = [
    "octavia_macro",
    "octavia_dna",
]


def register():
    """Подключает все динамические свойства Octavia после регистрации классов."""
    bpy.types.Scene.vj_record_mode = bpy.props.BoolProperty(
        name="Octavia Live Mode",
        default=False,
    )

    for i in range(1, 21):
        setattr(
            bpy.types.Scene,
            f"octavia_ch{i}_preset",
            bpy.props.EnumProperty(name=f"Пресет К{i}", items=get_octavia_presets),
        )
        setattr(
            bpy.types.Scene,
            f"octavia_ch{i}_name",
            bpy.props.StringProperty(name=f"Имя К{i}", default=f"Канал {i}"),
        )

    bpy.types.Node.octavia_macro = bpy.props.PointerProperty(type=OctaviaMacroSettings)
    bpy.types.Node.octavia_dna = bpy.props.StringProperty(
        name="Octavia DNA",
        description="Архитектурное описание логики ноды для следующих ИИ-сессий",
        default="",
    )

    bpy.types.Scene.octavia_channels_data = bpy.props.CollectionProperty(
        type=OctaviaChannelSettings,
    )
    bpy.types.Scene.octavia_zoom = bpy.props.FloatProperty(default=1.0, min=0.1, max=10.0)
    bpy.types.Scene.octavia_scroll = bpy.props.FloatProperty(default=0.0, min=0.0)
    bpy.types.Scene.octavia_channel_count = bpy.props.IntProperty(default=0, min=0, max=20)
    bpy.types.Scene.octavia_mute = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.octavia_bpm = bpy.props.IntProperty(
        name="BPM",
        default=120,
        min=30,
        max=300,
    )
    bpy.types.Scene.octavia_snap = bpy.props.BoolProperty(
        name="Магнит сетки",
        default=True,
    )

    bpy.types.Scene.octavia_hovered_ch = bpy.props.IntProperty(default=0)
    bpy.types.Scene.octavia_hovered_part = bpy.props.StringProperty(default="NONE")
    bpy.types.Scene.octavia_hovered_ruler = bpy.props.StringProperty(default="NONE")
    bpy.types.Scene.octavia_active_channel = bpy.props.IntProperty(default=1, min=1, max=20)
    bpy.types.Scene.octavia_auto_scroll_active = bpy.props.BoolProperty(
        name="Octavia Auto Scroll Active",
        default=True,
    )

    bpy.types.Scene.octavia_active_macros = bpy.props.CollectionProperty(
        type=OctaviaExposedMacro,
    )
    bpy.types.Scene.octavia_selected_blocks = bpy.props.CollectionProperty(
        type=bpy.types.PropertyGroup,
    )

    bpy.types.Scene.octavia_loop_start = bpy.props.FloatProperty(default=0.0)
    bpy.types.Scene.octavia_loop_end = bpy.props.FloatProperty(default=0.0)
    bpy.types.Scene.octavia_loop_active = bpy.props.BoolProperty(default=False)

    bpy.types.Scene.octavia_authoring_export_dir = bpy.props.StringProperty(
        name="Папка сессии с ИИ",
        description="Куда копируется Authoring Kit и дублируются слепки графа",
        default="",
        subtype='DIR_PATH',
    )
    bpy.types.Scene.octavia_auto_graph_snapshot = bpy.props.BoolProperty(
        name="Авто-слепок графа",
        default=True,
    )
    bpy.types.Scene.octavia_auto_buffer_snapshot = bpy.props.BoolProperty(
        name="Авто-слепок буфера",
        default=True,
    )


def unregister():
    """Удаляет свойства до выгрузки классов, от которых они зависят."""
    for name in reversed(NODE_PROPERTY_NAMES):
        if hasattr(bpy.types.Node, name):
            delattr(bpy.types.Node, name)

    for name in reversed(SCENE_PROPERTY_NAMES):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
