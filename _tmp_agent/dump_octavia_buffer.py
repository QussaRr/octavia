import bpy
import sys

print("=== BLEND FILE ===", bpy.data.filepath)
print("=== OBJECTS with Octavia ===")
for o in bpy.data.objects:
    if "Octavia" in o.name or "Buffer" in o.name:
        print("OBJ", o.name, "type", o.type, "data", getattr(o.data, "name", None))

print("=== MESHES Octavia_Buffer* ===")
for m in bpy.data.meshes:
    if "Octavia_Buffer" in m.name or m.get("is_octavia_buffer"):
        act = None
        if m.animation_data and m.animation_data.action:
            act = m.animation_data.action.name
        print("MESH", m.name, "verts", len(m.vertices), "action", act)
        st = m.attributes.get("start_frame")
        en = m.attributes.get("end_frame")
        if st:
            dirty = []
            n = min(128, len(st.data))
            for i in range(n):
                sv = float(st.data[i].value)
                ev = float(en.data[i].value) if en else None
                if abs(sv + 1) > 1e-6 or (en and abs(ev + 1) > 1e-6 and ev >= 0):
                    dirty.append((i, sv, ev))
            print(" dirty note slots sample", dirty[:40], "count", len(dirty))
            salvo_dirty = []
            for i in range(160, min(2208, len(st.data))):
                if float(st.data[i].value) >= 1:
                    salvo_dirty.append((i, float(st.data[i].value)))
            print(" salvo start>=1 count", len(salvo_dirty), "sample", salvo_dirty[:20])
        else:
            print(" NO start_frame attr")

print("=== ACTIONS ===")
for a in bpy.data.actions:
    print("ACTION", a.name)

print("=== DONE ===")
