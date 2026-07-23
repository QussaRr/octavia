import bpy

def track_mouse_grid(context, layout, mx, scroll_px):
    scene = context.scene
    fps = layout['fps']
    pixels_per_second = layout['pixels_per_second']
    track_x, track_y = layout['track_x'], layout['track_y']
    channel_h = layout['channel_h']
    channel_gap = layout['channel_gap']

    current_mouse_ch = -1
    current_mouse_frame = -1.0
    current_mouse_voice = 0

    if mx >= track_x and layout['my'] < track_y + 45:
        curr_layout_y = track_y
        for i in range(1, scene.octavia_channel_count + 1):
            is_active_ch = (scene.octavia_active_channel == i)
            
            if is_active_ch and len(scene.octavia_channels_data) >= i:
                num_voices = max(1, len(scene.octavia_channels_data[i - 1].voices))
                ch_h = num_voices * channel_h
            else:
                ch_h = channel_h
                num_voices = 1
                
            ch_y = curr_layout_y - (ch_h + channel_gap)
            curr_layout_y = ch_y
          
            if ch_y <= layout['my'] <= ch_y + ch_h:
                current_mouse_ch = i
                if is_active_ch:
                    # Вычисляем, по какому именно голосовому этажу кликнули (сверху вниз)
                    local_y_from_top = (ch_y + ch_h) - layout['my']
                    v_lane = int(local_y_from_top // channel_h)
                    current_mouse_voice = max(0, min(num_voices - 1, v_lane))
                else:
                    current_mouse_voice = 0
                break
               
        delta_x = mx - track_x + scroll_px
        c_sec = delta_x / pixels_per_second
        r_frame = c_sec * fps + 1
       
        if getattr(scene, "octavia_snap", True):
            from ...vj_core import snap_frame_for_daw_mouse
            current_mouse_frame = float(snap_frame_for_daw_mouse(
                r_frame, scene, fps, pixels_per_second, current_mouse_ch,
            ))
        else:
            current_mouse_frame = float(int(round(r_frame)))

    scene["octavia_mouse_ch"] = current_mouse_ch
    scene["octavia_mouse_frame"] = current_mouse_frame
    scene["octavia_mouse_voice"] = current_mouse_voice
    
    return current_mouse_frame, current_mouse_ch, current_mouse_voice
