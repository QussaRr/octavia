import bpy

def handle_timer(self, context, event, layout, area):
    scene = context.scene
    current_frame = scene.frame_current
   
    frame_changed = (current_frame != getattr(self, "_last_frame", -1))
    
    # 🪐 МАТЕМАТИЧЕСКИЙ ДВИЖОК СИНХРОНИЗАЦИИ ОРБИТ С BPM СЕКВЕНСОРА
    fps = layout['fps']
    bpm = getattr(scene, "octavia_bpm", 120)
   
    # 1 полный круг по кривой = 4 битам (1 музыкальный бар трека)
    frames_per_bar = (240.0 * fps) / bpm
   
    # Вычисляем текущую фазу прогресса на кривой (от 0.0 до 1.0)
    progress = (current_frame - 1) / frames_per_bar
    current_offset = progress % 1.0  
   
    # Бежим по сцене и крутим абсолютно все объекты, посаженные на рельсы Октавии
    for obj in scene.objects:
        if hasattr(obj, "constraints") and obj.constraints:
            for con in obj.constraints:
                if con.type == 'FOLLOW_PATH' and con.name.startswith("Octavia_Follow_"):
                    # 🔥 ЖЕЛЕЗНЫЙ ПРЕДОХРАНИТЕЛЬ: Пишем в RNA только если значение реально сдвинулось!
                    # Спасает Блендер от бесконечного цикла пересчета сцены на паузе.
                    if abs(con.offset_factor - current_offset) > 0.00001:
                        con.offset_factor = current_offset
                        
    self._last_frame = current_frame
   
    if frame_changed:
        if scene.octavia_auto_scroll_active:
            # 1. Смарт-Ресет назад (Ловушка музыкального возврата)
            if current_frame < scene.octavia_scroll:
                quarter_screen = layout['visible_frames'] * 0.25
                if current_frame <= quarter_screen:
                    scene.octavia_scroll = 0.0
                else:
                    scene.octavia_scroll = max(0.0, current_frame - quarter_screen)
                   
            # 2. Шёлковый авто-скролл вперёд
            elif context.screen.is_animation_playing:
                scroll_threshold_frame = scene.octavia_scroll + (layout['visible_frames'] * 0.75)
                if current_frame > scroll_threshold_frame:
                    scene.octavia_scroll = current_frame - (layout['visible_frames'] * 0.75)
       
        area.tag_redraw()

    # 🎞️ НЕПРЕРЫВНАЯ ПЕРЕРИСОВКА ДЛЯ СУБКАДРОВОГО ПЛЕЙХЕДА
    # Во время проигрывания дёргаем redraw на каждом тике таймера (60 Гц), а не только
    # при смене целого кадра. Только так субкадровая интерполяция плейхеда в blocks.py
    # получает возможность пересчитать своё дробное положение между кадрами Блендера.
    elif context.screen.is_animation_playing:
        area.tag_redraw()
       
    return {'RUNNING_MODAL'}

def handle_zoom(self, context, event, layout, area):
    scene = context.scene
    fps = layout['fps']
    track_x = layout['track_x']
    mx = layout['mx']
    visible_workspace_w = layout['visible_workspace_w']
    
    scene.octavia_auto_scroll_active = False
    focus_x = max(track_x, mx)
    
    current_pps = 50 * scene.octavia_zoom
    old_scroll_px = (scene.octavia_scroll / fps) * current_pps
    absolute_mouse_px = (focus_x - track_x) + old_scroll_px
    time_anchor_sec = absolute_mouse_px / current_pps
    
    # 🪐 ДИНАМИЧЕСКИЙ ОГРАНИЧИТЕЛЬ МАКСИМАЛЬНОГО ОТДАЛЕНИЯ
    # Вычисляем минимальный зум, при котором длина трека займет ровно 85% видимого экрана
    track_len_sec = scene.frame_end / fps if scene.frame_end > 1 else 10.0
    
    # Формула: 50 * zoom * track_len_sec = visible_workspace_w * 0.85
    # Отсюда выражаем минимальный зум:
    min_adaptive_zoom = (visible_workspace_w * 0.85) / (50.0 * track_len_sec)
    
    # Ставим жесткий предохранитель, чтобы зум не ушел в микроскопические значения на пустых сценах
    min_adaptive_zoom = max(0.05, min_adaptive_zoom)

    if event.type == 'WHEELUPMOUSE':
        scene.octavia_zoom = min(10.0, scene.octavia_zoom * 1.1)
    elif event.type == 'WHEELDOWNMOUSE':
        scene.octavia_zoom = max(min_adaptive_zoom, scene.octavia_zoom / 1.1)
        
    new_pps = 50 * scene.octavia_zoom
    new_absolute_mouse_px = time_anchor_sec * new_pps
    
    new_scroll_px = new_absolute_mouse_px - (focus_x - track_x)
    new_scroll_frames = (new_scroll_px / new_pps) * fps
    
    track_len_px = (scene.frame_end / fps) * new_pps
    
    # Умная центровка пустого пространства
    if track_len_px < visible_workspace_w:
        scene.octavia_scroll = 0.0
    else:
        max_scroll_px = track_len_px - visible_workspace_w
        max_scroll_frames = (max_scroll_px / new_pps) * fps
        scene.octavia_scroll = max(0.0, min(new_scroll_frames, max_scroll_frames))
    
    area.tag_redraw()
    return {'RUNNING_MODAL'}

def handle_scroll(self, context, event, layout, area):
    scene = context.scene
    scene.octavia_auto_scroll_active = False
    
    frames_per_beat = (60.0 / scene.octavia_bpm) * layout['fps']
    
    if event.type == 'WHEELUPMOUSE':
        scene.octavia_scroll = max(0.0, scene.octavia_scroll - frames_per_beat)
    elif event.type == 'WHEELDOWNMOUSE':
        scene.octavia_scroll += frames_per_beat
        
    area.tag_redraw()
    return {'RUNNING_MODAL'}