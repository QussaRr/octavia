"""Квантовый ластик Octavia: хит по телу ноты, только locked channel+voice."""
import sys

import bpy


def resolve_eraser_hardware_id(scene, ch_idx, voice_lane):
    """voice_lane (этаж HUD) → hardware_id голоса канала."""
    if ch_idx < 1 or len(scene.octavia_channels_data) < ch_idx:
        return 0
    voices = scene.octavia_channels_data[ch_idx - 1].voices
    if not voices:
        return 0
    lane = max(0, min(len(voices) - 1, int(voice_lane)))
    return int(voices[lane].hardware_id)


def apply_quantum_eraser(self, context, center_frame):
    """Помечает блоки под ластиком: только канал/голос зажима, пересечение с ТЕЛОМ ноты."""
    scene = context.scene
    ch = getattr(self, "_eraser_ch", -1)
    if ch < 1 or center_frame < 1.0:
        return

    width = float(getattr(self, "_eraser_width_frames", 2.0))
    f_start = center_frame - (width / 2.0)
    f_end = center_frame + (width / 2.0)
    target_hw = int(getattr(self, "_eraser_hw_id", 0))

    buf_name = f"Octavia_Buffer_Ch_{ch}"
    buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
    if not (buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action):
        return

    act = buf_obj.data.animation_data.action
    from ...vj_core import get_note_timing_curve_maps
    start_curves, end_curves, voice_curves = get_note_timing_curve_maps(buf_obj.data)

    if not hasattr(sys, "_octavia_virtual_erased"):
        sys._octavia_virtual_erased = set()

    voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")

    for idx in start_curves:
        st_fc = start_curves.get(idx)
        if not st_fc:
            continue
        en_fc = end_curves.get(idx)
        v_fc = voice_curves.get(idx)

        kps = st_fc.keyframe_points
        for k_idx, kp in enumerate(kps):
            hit_frame = kp.co[1]
            if hit_frame < 1.0:
                continue

            if v_fc:
                v_id = int(v_fc.evaluate(kp.co[0] + 0.1))
            elif voice_id_attr and idx < len(voice_id_attr.data):
                v_id = int(voice_id_attr.data[idx].value)
            else:
                v_id = 0
            if v_id < 0:
                v_id = 0
            if v_id != target_hw:
                continue

            next_hit = kps[k_idx + 1].co[1] if k_idx + 1 < len(kps) else float("inf")
            end_frame = -1.0
            if en_fc:
                for ekp in en_fc.keyframe_points:
                    if hit_frame <= ekp.co[0] < next_hit and ekp.co[1] >= hit_frame:
                        end_frame = ekp.co[1]
                        break

            body_end = float(scene.frame_current) if end_frame < 0.0 else float(end_frame)
            # Пересечение ластика с телом ноты [hit_frame, body_end], не только со start
            if hit_frame <= f_end and body_end >= f_start:
                block_id = f"ch_{ch}_idx_{idx}_f_{hit_frame:.1f}"
                sys._octavia_virtual_erased.add(block_id)
