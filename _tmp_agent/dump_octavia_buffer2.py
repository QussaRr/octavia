import bpy
m = bpy.data.meshes.get("Octavia_Buffer_Ch_1")
print("MESH", m.name if m else None, "verts", len(m.vertices) if m else None)
ad = m.animation_data if m else None
act = ad.action if ad else None
print("ACTION", act.name if act else None)
if act:
    print(" fcurves", len(act.fcurves))
    for fc in list(act.fcurves)[:12]:
        kps = len(fc.keyframe_points)
        print(f"  {fc.data_path}[{fc.array_index}] keys={kps}")
    # count keys mentioning start_frame / end_frame
    sf = [fc for fc in act.fcurves if "start_frame" in fc.data_path]
    ef = [fc for fc in act.fcurves if "end_frame" in fc.data_path]
    print(" start_frame fcurves", len(sf), "end_frame fcurves", len(ef))
st = m.attributes.get("start_frame")
en = m.attributes.get("end_frame")
vid = m.attributes.get("octavia_voice_id")
dirty = []
for i in range(min(128, len(st.data))):
    sv = float(st.data[i].value)
    ev = float(en.data[i].value) if en else None
    vv = float(vid.data[i].value) if vid else None
    if abs(sv + 1) > 1e-6 or (en and abs(ev + 1) > 1e-6 and ev >= 0):
        dirty.append((i, sv, ev, vv))
print("DIRTY_ALL count", len(dirty))
print("DIRTY_ALL", dirty)
# pattern: start equals slot%16 style
weird = [t for t in dirty if t[1] < 32 and t[2] == -1.0]
print("held_with_start_lt32", len(weird), "sample", weird[:30])
