import bpy
m = bpy.data.meshes["Octavia_Buffer_Ch_1"]
act = m.animation_data.action if m.animation_data else None
print("ACTION", getattr(act, "name", None), "type", type(act))
# Blender 5 layered actions
for attr in ("fcurves", "layers", "slots", "curves", "groups"):
    print(" has", attr, hasattr(act, attr))
if hasattr(act, "layers"):
    print(" layers", len(act.layers))
    for layer in act.layers:
        print("  layer", layer.name, "strips", len(getattr(layer, "strips", [])))
        for strip in getattr(layer, "strips", []):
            ch = getattr(strip, "channelbag", None) or getattr(strip, "channelbags", None)
            print("   strip", strip, "channelbag", ch)
            if ch is None and hasattr(strip, "channelbags"):
                for cb in strip.channelbags:
                    fcs = getattr(cb, "fcurves", [])
                    print("    bag fcurves", len(fcs))
                    for fc in list(fcs)[:8]:
                        print("     ", fc.data_path, fc.array_index, "keys", len(fc.keyframe_points))
            elif hasattr(ch, "fcurves"):
                print("    fcurves", len(ch.fcurves))
# slots
if hasattr(act, "slots"):
    print(" slots", len(act.slots), [s.name_display if hasattr(s,"name_display") else s.name for s in act.slots])
# fallback: dir
print("dir sample", [x for x in dir(act) if not x.startswith("_")][:40])
st, en, vid = m.attributes["start_frame"], m.attributes["end_frame"], m.attributes.get("octavia_voice_id")
dirty = [(i, float(st.data[i].value), float(en.data[i].value), float(vid.data[i].value) if vid else None) for i in range(128) if abs(float(st.data[i].value)+1)>1e-6 or (abs(float(en.data[i].value)+1)>1e-6 and float(en.data[i].value)>=0)]
print("DIRTY count", len(dirty))
print(dirty)
