import bpy
import sys
import math
from .draw_utils import draw_rect
from .echo_trail import echo_trail_context_for_channel, ghost_frames_for_voice, hardware_id_for_voice_floor

def draw_laser_ghosts(layout):
    scene = layout['scene']
    context = layout['context']
    win_w = layout['win_w']
    track_x, track_y = layout['track_x'], layout['track_y']
    right_margin = layout['right_margin']
    pixels_per_second = layout['pixels_per_second']
    scroll_px = layout['scroll_px']
    fps = layout['fps']
    channel_h = layout['channel_h']

    if hasattr(sys, "_octavia_clipboard") and sys._octavia_clipboard and not scene.get("octavia_box_select_active", False):
        g_ch = scene.get("octavia_mouse_ch", -1)
        g_frame = scene.get("octavia_mouse_frame", -1.0)
        
        g_voice = scene.get("octavia_mouse_voice", 0)
        source_min_voice = getattr(sys, "_octavia_clipboard_source_min_voice", 0)
        voice_offset = g_voice - source_min_voice
        
        if g_ch > 0 and g_frame >= 1.0:
            existing_notes = {}
            ch_data = scene.octavia_channels_data[g_ch - 1] if len(scene.octavia_channels_data) >= g_ch else None
            num_voices = len(ch_data.voices) if ch_data else 1
            for v_idx in range(num_voices):
                existing_notes[v_idx] = []
                
            buf_name = f"Octavia_Buffer_Ch_{g_ch}"
            buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
            if buf_obj and buf_obj.data and buf_obj.data.animation_data and buf_obj.data.animation_data.action:
                from ..operators.vj_core import get_note_timing_curve_maps
                start_curves, end_curves, voice_curves = get_note_timing_curve_maps(buf_obj.data)

                for idx in start_curves:
                    st_fc = start_curves.get(idx)
                    en_fc = end_curves.get(idx)
                    if not st_fc: continue
                    
                    kps = st_fc.keyframe_points
                    for k_idx, kp in enumerate(kps):
                        hit_frame = kp.co[1]
                        if hit_frame < 1.0: continue
                        
                        next_hit_frame = kps[k_idx+1].co[1] if k_idx + 1 < len(kps) else float('inf')
                        end_frame = -1.0
                        if en_fc:
                            for ekp in en_fc.keyframe_points:
                                if hit_frame <= ekp.co[0] < next_hit_frame:
                                    if ekp.co[1] >= hit_frame:
                                        end_frame = ekp.co[1]

                        is_held = (end_frame == -1.0)
                        body_end_f = scene.frame_current if is_held else end_frame
                        
                        v_fc = voice_curves.get(idx)
                        if v_fc:
                            v_id = int(v_fc.evaluate(kp.co[0]))
                        else:
                            voice_id_attr = buf_obj.data.attributes.get("octavia_voice_id")
                            v_id = int(voice_id_attr.data[idx].value) if voice_id_attr else 0
                            
                        v_idx = next((idx_v for idx_v, v in enumerate(ch_data.voices) if v.hardware_id == v_id), 0) if ch_data else 0
                        if v_idx in existing_notes:
                            existing_notes[v_idx].append((hit_frame, body_end_f))

            has_collision = False
            for p in sys._octavia_clipboard:
                target_v_idx = p['v_idx'] + voice_offset
                target_frame = int(round(g_frame + p['time_offset_frames']))
                target_dur = p['duration_frames']
                
                if target_v_idx in existing_notes:
                    for f_start, f_end in existing_notes[target_v_idx]:
                        if max(target_frame, f_start) < min(target_frame + target_dur, f_end):
                            has_collision = True
                            break
                if has_collision: break

            if has_collision:
                ghost_color = (1.0, 0.2, 0.2, 0.15)
                outline_color = (1.0, 0.2, 0.2, 0.5)
                laser_color = (1.0, 0.2, 0.2)
            else:
                ghost_color = (0.2, 0.7, 1.0, 0.12)
                outline_color = (0.2, 0.7, 1.0, 0.35)
                laser_color = (0.2, 0.7, 1.0)

            # Вычисляем точный динамический ch_y для g_ch
            active_channels = scene.octavia_channel_count
            active_track_idx = getattr(scene, "octavia_active_channel", 1)
            channel_gap = layout.get('channel_gap', 8)
            channel_h = layout['channel_h']
            curr_layout_y = track_y
            g_ch_y = track_y
            g_num_voices = 1
            for i in range(1, active_channels + 1):
                is_active_ch = (active_track_idx == i)
                if is_active_ch and len(scene.octavia_channels_data) >= i:
                    num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
                    ch_h = num_voices * channel_h
                else:
                    ch_h = channel_h
                    num_voices = 1
                ch_y = curr_layout_y - (ch_h + channel_gap)
                curr_layout_y = ch_y
                if i == g_ch:
                    g_ch_y = ch_y
                    g_num_voices = num_voices

            paste_echo_ctx = echo_trail_context_for_channel(scene, g_ch)

            for p in sys._octavia_clipboard:
                t_frame = g_frame + p['time_offset_frames']
                target_v_idx = p['v_idx'] + voice_offset
                
                if 1.0 <= t_frame <= scene.frame_end:
                    if scene.octavia_active_channel == g_ch:
                        v_y = g_ch_y + (g_num_voices - 1 - target_v_idx) * channel_h + 4
                        v_h = channel_h - 8
                    else:
                        v_y = g_ch_y + 4
                        v_h = channel_h - 8
                    
                    p_sec = (t_frame - 1) / fps
                    gx = track_x + (p_sec * pixels_per_second) - scroll_px
                    gw = (p['duration_frames'] / fps) * pixels_per_second
                    if gx + gw > track_x:
                        draw_gx = gx
                        draw_gw = gw
                        if draw_gx < track_x:
                            draw_gw = gw - (track_x - draw_gx)
                            draw_gx = track_x
                            
                        if draw_gx < win_w - right_margin:
                            snap_gx = int(round(draw_gx))
                            snap_gw = int(round(min(draw_gw, win_w - right_margin - draw_gx)))
                            
                            if snap_gw > 0:
                                draw_rect(snap_gx, v_y, snap_gw, v_h, ghost_color)
                                draw_rect(snap_gx, v_y, snap_gw, 1, outline_color)
                                draw_rect(snap_gx, v_y + v_h - 1, snap_gw, 1, outline_color)
                                draw_rect(snap_gx, v_y, 1, v_h, outline_color)
                                draw_rect(snap_gx + snap_gw - 1, v_y, 1, v_h, outline_color)

                                # Echo-хвост — из пресета канала, куда вставляем (не из копии)
                                if paste_echo_ctx and not has_collision:
                                    ghost_group, decay, ef, es, hn = paste_echo_ctx
                                    hw_id = hardware_id_for_voice_floor(scene, g_ch, target_v_idx)
                                    echo_frames = ghost_frames_for_voice(
                                        hw_id, fps, ghost_group, g_ch, scene, decay, ef, es, hn,
                                    )
                                    if echo_frames > 0:
                                        echo_gw = (echo_frames / fps) * pixels_per_second
                                        ebx = snap_gx + snap_gw
                                        if ebx < win_w - right_margin:
                                            snap_ebw = int(round(min(echo_gw, win_w - right_margin - ebx)))
                                            if snap_ebw > 0:
                                                tail_fill = (
                                                    ghost_color[0], ghost_color[1], ghost_color[2],
                                                    ghost_color[3] * 0.65,
                                                )
                                                tail_line = (
                                                    outline_color[0], outline_color[1], outline_color[2],
                                                    outline_color[3] * 0.5,
                                                )
                                                draw_rect(ebx, v_y, snap_ebw, v_h, tail_fill)
                                                draw_rect(ebx, v_y, snap_ebw, 1, tail_line)
                                                draw_rect(ebx, v_y + v_h - 1, snap_ebw, 1, tail_line)

            # Тайминг исходного грува на целевом канале: мягкая полоса + скобки [ ]
            src_min_f = getattr(sys, "_octavia_clipboard_source_min_frame", -1.0)
            src_max_f = getattr(sys, "_octavia_clipboard_source_max_frame", -1.0)
            source_ch = getattr(sys, "_octavia_clipboard_source_ch", -1)

            if (
                src_min_f >= 1.0
                and src_max_f >= 1.0
                and source_ch != -1
                and g_ch != source_ch
            ):
                if scene.octavia_active_channel == g_ch:
                    mark_h = g_num_voices * channel_h
                else:
                    mark_h = channel_h

                def _frame_to_x(f_val):
                    return track_x + ((f_val - 1) / fps) * pixels_per_second - scroll_px

                x_lo = _frame_to_x(min(src_min_f, src_max_f))
                x_hi = _frame_to_x(max(src_min_f, src_max_f))
                clip_l = float(track_x)
                clip_r = float(win_w - right_margin)

                # Обрезка в видимую дорожку
                span_l = max(clip_l, x_lo)
                span_r = min(clip_r, x_hi)
                if span_r > span_l:
                    # Лёгкая заливка диапазона — читается как «окно тайминга»
                    draw_rect(
                        span_l, g_ch_y,
                        span_r - span_l, mark_h,
                        (*laser_color, 0.07),
                    )
                    # Тонкая верхняя кромка
                    draw_rect(
                        span_l, g_ch_y + mark_h - 1,
                        span_r - span_l, 1,
                        (*laser_color, 0.22),
                    )

                cap = 7  # ширина усов скобки
                for lx_raw, is_start in ((x_lo, True), (x_hi, False)):
                    if not (clip_l - 1 <= lx_raw <= clip_r + 1):
                        continue
                    lx = int(round(lx_raw))
                    # Вертикаль
                    draw_rect(lx, g_ch_y, 1, mark_h, (*laser_color, 0.75))
                    # Скобки: у старта усы вправо, у конца — влево
                    if is_start:
                        draw_rect(lx, g_ch_y + mark_h - 2, cap, 2, (*laser_color, 0.9))
                        draw_rect(lx, g_ch_y, cap, 2, (*laser_color, 0.9))
                    else:
                        draw_rect(lx - cap + 1, g_ch_y + mark_h - 2, cap, 2, (*laser_color, 0.9))
                        draw_rect(lx - cap + 1, g_ch_y, cap, 2, (*laser_color, 0.9))


class OctaviaOrbitPreset:
    def __init__(self, id_name, label):
        self.id_name = id_name
        self.label = label

    def get_position(self, t):
        return (0.0, 0.0, 0.0)


OCTAVIA_PRESET_REGISTRY = {
    'ORBITS': [
        OctaviaOrbitPreset("SPIRAL", "🌌 NEON SPIRAL"),
        OctaviaOrbitPreset("FIGURE_EIGHT", "♾️ INFINITY LOOP"),
        OctaviaOrbitPreset("RING", "⭕ LASER RING"),
        OctaviaOrbitPreset("SINUSOID", "🌊 WAVE SINUSOID")
    ],
    'GEONODES': [
        OctaviaOrbitPreset("SHAKE", "🧪 QUANTUM SHAKE"),
        OctaviaOrbitPreset("PULSE", "❤️ HEARTBEAT PULSE"),
        OctaviaOrbitPreset("CRYSTAL_MOD", "💎 CRYSTALLIZE")
    ],
    'SHADERS': [
        OctaviaOrbitPreset("HOLOGRAM", "🔮 GLITCH HOLOGRAM"),
        OctaviaOrbitPreset("LIQUID_NEON", "🧪 LIQUID NEON"),
        OctaviaOrbitPreset("CHROME_REFLECT", "💎 MIRROR CHROME")
    ]
}

import os

def get_preset_labels(category):
    addon_dir = os.path.dirname(os.path.dirname(__file__))
    folder_path = os.path.join(addon_dir, "presets", category.lower())
    
    if not os.path.exists(folder_path):
        return []
        
    preset_names = []
    try:
        for f in os.listdir(folder_path):
            if f.endswith(".blend"):
                name_without_ext = f[:-6].upper()
                preset_names.append(name_without_ext)
    except Exception as e:
        print(f"❌ [Octavia Scan] Ошибка сканирования пресетов на диске: {e}")
        
    preset_names.sort()
    
    if not preset_names:
        return ["НЕТ СОХРАНЕННЫХ ПРЕСЕТОВ"]
        
    return preset_names

def get_preset_id_by_idx(category, idx):
    presets = get_preset_labels(category)
    if 0 <= idx < len(presets):
        if presets[idx] == "НЕТ СОХРАНЕННЫХ ПРЕСЕТОВ":
            return None
        return presets[idx]
    return None