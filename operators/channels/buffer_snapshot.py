"""Octavia buffer snapshot — Idea 9: one file, BRIEF (auto) / FORENSIC (button)."""

from __future__ import annotations

import hashlib
import os
import re
import time

import bpy
from bpy.app.handlers import persistent


def _addon_dir():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _dedupe_dirs(dirs):
    seen = set()
    out = []
    for d in dirs:
        norm = os.path.normcase(os.path.abspath(d))
        if norm in seen:
            continue
        seen.add(norm)
        out.append(d)
    return out


def _buffer_snapshot_dirs(scene=None):
    addon = _addon_dir()
    dirs = [
        os.path.join(addon, "buffer_snapshots"),
        os.path.join(addon, "authoring_kit", "buffer_snapshots"),
    ]
    if scene is not None:
        export_dir = (getattr(scene, "octavia_authoring_export_dir", "") or "").strip()
        if export_dir and os.path.isdir(export_dir):
            dirs.append(os.path.join(export_dir, "buffer_snapshots"))
    return _dedupe_dirs(dirs)


def _content_hash(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _attr_val_mesh(m, name, idx):
    a = m.attributes.get(name)
    if not a or idx >= len(a.data):
        return None
    return a.data[idx].value


def _attr_vec_mesh(m, name, idx):
    a = m.attributes.get(name)
    if not a or idx >= len(a.data):
        return None
    try:
        v = a.data[idx].vector
        return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:
        return None


_BUFFER_NOISE_ATTRS = frozenset({
    "position", "sharp_face", "sharp_edge", "crease_edge", "crease_vert",
})
_BUFFER_RECENT_WINDOW = 96
_BUFFER_CURVES_DENSE_PER_NOTE = 24


def _fmt_vec3(v, digits=3):
    if v is None:
        return "None"
    return f"({v[0]:.{digits}f}, {v[1]:.{digits}f}, {v[2]:.{digits}f})"


def _vec_near_zero(v, eps=1e-5):
    if v is None:
        return True
    return abs(v[0]) <= eps and abs(v[1]) <= eps and abs(v[2]) <= eps


def _is_meaningful_attr(name):
    if not name or name.startswith("."):
        return False
    if name in _BUFFER_NOISE_ATTRS:
        return False
    return True


def _collect_buffer_fcurves(mesh):
    from ..vj_core import iter_action_fcurves

    if not mesh.animation_data or not mesh.animation_data.action:
        return None, []
    act = mesh.animation_data.action
    return act, list(iter_action_fcurves(act))


def _parse_attr_curve_path(data_path):
    m = re.search(r'attributes\["([^"]+)"\]\.data\[(\d+)\]', data_path or "")
    if not m:
        m = re.search(r"attributes\['([^']+)'\]\.data\[(\d+)\]", data_path or "")
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _first_key_frame(fc):
    if not fc.keyframe_points:
        return None
    return round(fc.keyframe_points[0].co[0], 1)


def _note_status(frame, start, end):
    if start is None or start < 1.0:
        return None
    if frame < start:
        return "future"
    end_open = end is None or end < 0.0
    if end_open:
        return "held"
    if frame < end:
        return "held"
    if abs(frame - end) < 1e-6:
        return "released"
    return "past"


def _is_contributing(frame, start, end):
    if start is None or start < 1.0:
        return False
    if frame < start:
        return False
    if end is None or end < 0.0:
        return True
    return frame <= end


def _hw_macro_vals(mesh, hw, macro_attrs):
    idx = 128 + int(hw)
    out = []
    if idx >= len(mesh.vertices):
        return out
    for mn in macro_attrs:
        val = _attr_val_mesh(mesh, mn, idx)
        if val is None:
            continue
        if mn.startswith("oc_m_") or abs(val) > 1e-9:
            out.append((mn, float(val)))
    return out


def _burst_count_from_macros(macro_pairs):
    by_name = {n: v for n, v in macro_pairs}
    if "oc_m_burst_count" in by_name:
        try:
            return max(0, int(round(by_name["oc_m_burst_count"])))
        except Exception:
            pass
    for n, v in macro_pairs:
        if "burst" in n.lower() and n.startswith("oc_m_"):
            try:
                return max(0, int(round(v)))
            except Exception:
                continue
    return None


def _salvo_active(mesh, slot_idx, stride, salvo_vert_index):
    bits = []
    for p in range(stride):
        sidx = salvo_vert_index(slot_idx, p)
        if sidx >= len(mesh.vertices):
            break
        sst = _attr_val_mesh(mesh, "start_frame", sidx)
        if sst is None or sst < 1.0:
            continue
        bp = _attr_vec_mesh(mesh, "burst_position", sidx)
        bn = _attr_vec_mesh(mesh, "burst_normal", sidx)
        bits.append((p, sidx, bp, bn, float(sst)))
    return bits


def _compress_hw_ranges(hw_ids):
    if not hw_ids:
        return "none"
    ids = sorted(hw_ids)
    ranges = []
    a = b = ids[0]
    for x in ids[1:]:
        if x == b + 1:
            b = x
        else:
            ranges.append(f"{a}-{b}" if a != b else str(a))
            a = b = x
    ranges.append(f"{a}-{b}" if a != b else str(a))
    return ",".join(ranges)


def _slot_eval_signature(mesh, slot_idx, stride, salvo_vert_index):
    st = _attr_val_mesh(mesh, "start_frame", slot_idx)
    en = _attr_val_mesh(mesh, "end_frame", slot_idx)
    vid = _attr_val_mesh(mesh, "octavia_voice_id", slot_idx)
    hp = _attr_vec_mesh(mesh, "hit_position", slot_idx)
    hn = _attr_vec_mesh(mesh, "hit_normal", slot_idx)
    salvo_n = len(_salvo_active(mesh, slot_idx, stride, salvo_vert_index))
    return (st, en, vid, hp, hn, salvo_n)


def _write_buffer_report_files(scene, ch_idx, lines, *, print_console=True):
    report_text = "\n".join(lines)
    if print_console:
        print("\n" + report_text)
    filename = f"Buffer_Ch_{ch_idx}.txt"
    written = []
    errors = []
    for snapshots_dir in _buffer_snapshot_dirs(scene):
        try:
            os.makedirs(snapshots_dir, exist_ok=True)
            file_path = os.path.join(snapshots_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            written.append(file_path)
        except Exception as e:
            errors.append(f"{snapshots_dir}: {e}")
            print(f"[Octavia] Не удалось записать слепок буфера в {snapshots_dir}: {e}")
    return written, errors, report_text


def build_buffer_snapshot_lines(scene, ch_idx, *, mode="BRIEF", context=None):
    """
    Idea 9: один каркас Buffer_Ch_N.txt.
    mode=BRIEF (auto) | FORENSIC (кнопка).
    Section order: HEADER, CONTRACT, WIRING, VOICES, NOTES@F,
    HIT/SALVO, ANOMALIES, CURVES, EVAL, [APPENDIX].
    """
    from ..vj_core import (
        ensure_buffer_topology,
        BUFFER_VERT_COUNT,
        NOTE_SLOT_COUNT,
        SALVO_BASE,
        SALVO_STRIDE,
        salvo_vert_index,
    )

    mode = (mode or "BRIEF").upper()
    if mode not in ("BRIEF", "FORENSIC"):
        mode = "BRIEF"
    forensic = mode == "FORENSIC"

    buf_name = f"Octavia_Buffer_Ch_{ch_idx}"
    buf_obj = scene.objects.get(buf_name) or bpy.data.objects.get(buf_name)
    frame = float(scene.frame_current)
    fps = scene.render.fps
    anomalies = []

    header = [
        "================== OCTAVIA BUFFER SNAPSHOT ==================",
        f"MODE: {mode}",
        f"channel: {ch_idx} | frame: {scene.frame_current} | fps: {fps}",
    ]

    if not buf_obj or not buf_obj.data:
        lines = list(header)
        lines.append(f"topology: FAIL — буфер '{buf_name}' не найден")
        anomalies.append(f"buffer object '{buf_name}' missing")
        lines.append("\n## ANOMALIES")
        for a in anomalies:
            lines.append(f"- {a}")
        lines.append("\n================================================================================")
        return lines

    if ensure_buffer_topology(buf_obj.data):
        try:
            buf_obj.data.update()
            buf_obj.update_tag()
        except Exception:
            pass

    mesh = buf_obj.data
    nverts = len(mesh.vertices)
    topo_ok = nverts >= BUFFER_VERT_COUNT
    if not topo_ok:
        anomalies.append(f"verts={nverts} expected>={BUFFER_VERT_COUNT}")

    attr_all = [a.name for a in mesh.attributes]
    attr_meaningful = [n for n in attr_all if _is_meaningful_attr(n)]
    header.append(
        f"topology: {'OK' if topo_ok else 'FAIL'} | object={buf_obj.name} | "
        f"mesh={mesh.name} | verts={nverts} (expect {BUFFER_VERT_COUNT})"
    )
    header.append(f"attrs: {', '.join(attr_meaningful) if attr_meaningful else '(none)'}")

    # CONTRACT
    contract = [
        "\n## CONTRACT",
        "Zones: A notes 0–127 | B voices 128–159 | C salvo 160–2207",
        f"Salvo index: {SALVO_BASE} + note×{SALVO_STRIDE} + p  (p=0..{SALVO_STRIDE - 1})",
        "hit_* / burst_* = world freeze at ONSET (playhead enters note); PRESS may write live draft",
        "Salvo: RAW emitter.data+matrix_world faces (not evaluated); pivot fallback Empty/Curve",
        "Onset: idle if same matrix fingerprint; else re-sample; spatial_only if salvo exists (no end rewrite)",
        "Full contract: authoring_kit → octavia-engine.mdc (this is an anchor only)",
    ]

    # WIRING
    wiring = ["\n## WIRING"]
    dup_objs = [o.name for o in bpy.data.objects if o.name.startswith(buf_name)]
    if len(dup_objs) > 1:
        anomalies.append(f"duplicate buffer-like objects: {dup_objs}")
    hide_vp = bool(buf_obj.hide_viewport)
    if hide_vp:
        anomalies.append("hide_viewport=True (Object Info may see empty eval)")
    wiring.append(
        f"buffer hide_viewport={hide_vp} hide_render={buf_obj.hide_render} "
        f"hide_eye={buf_obj.hide_get()} | dups={dup_objs}"
    )

    found_graph = False
    oi_ok = 0
    oi_fail = 0
    graph_names = []
    for obj in scene.objects:
        mod = obj.modifiers.get(f"Octavia Channel {ch_idx}")
        if not (mod and mod.node_group):
            continue
        found_graph = True
        gname = mod.node_group.name
        graph_names.append(gname)
        wiring.append(
            f"host '{obj.name}' mod '{mod.name}' → graph '{gname}' "
            f"(show_viewport={mod.show_viewport})"
        )
        for node in mod.node_group.nodes:
            if node.bl_idname != "GeometryNodeObjectInfo":
                continue
            tgt = node.inputs[0].default_value if node.inputs else None
            tgt_name = tgt.name if tgt else "None"
            ok = tgt_name == buf_name
            if ok:
                oi_ok += 1
            else:
                oi_fail += 1
                anomalies.append(
                    f"Object Info '{node.name}' → '{tgt_name}' (want '{buf_name}')"
                )
            wiring.append(
                f"  Object Info '{node.name}' → '{tgt_name}' [{('OK' if ok else 'FAIL')}]"
            )
    if not found_graph:
        wiring.append(f"(no object with modifier 'Octavia Channel {ch_idx}')")
        anomalies.append(f"no Octavia Channel {ch_idx} graph host")
    elif oi_ok == 0 and oi_fail == 0:
        wiring.append("  (no Object Info nodes in graph)")
        anomalies.append("graph has no Object Info nodes")
    else:
        wiring.append(f"Object Info summary: OK={oi_ok} FAIL={oi_fail}")
    if graph_names:
        wiring.append(
            f"graph snapshot hint: graph_snapshots/ → {', '.join(sorted(set(graph_names)))}"
        )

    # VOICES
    voices_sec = ["\n## VOICES (live)"]
    macro_attrs = [n for n in attr_meaningful if n.startswith("oc_m_")] + [
        "octavia_macro_punch", "octavia_macro_hold", "octavia_macro_echo",
    ]
    seen_m = set()
    macro_attrs = [n for n in macro_attrs if not (n in seen_m or seen_m.add(n))]

    voices = []
    if len(scene.octavia_channels_data) >= ch_idx:
        voices = list(scene.octavia_channels_data[ch_idx - 1].voices)
    voice_by_idx = {i: v for i, v in enumerate(voices)}
    live_hw = set()
    empty_hw = []

    for hw in range(32):
        v = None
        v_idx = None
        for i, cand in enumerate(voices):
            if int(getattr(cand, "hardware_id", -1)) == hw:
                v = cand
                v_idx = i
                break
        macros = _hw_macro_vals(mesh, hw, macro_attrs)
        overrides = []
        key = ""
        punch = hold = echo = 0.0
        if v is not None:
            key = (getattr(v, "key_code", "") or "").strip()
            punch = float(getattr(v, "punch", 0.0) or 0.0)
            hold = float(getattr(v, "hold", 0.0) or 0.0)
            echo = float(getattr(v, "echo", 0.0) or 0.0)
            overrides = [
                (o.macro_id, float(o.value))
                for o in getattr(v, "macro_overrides", [])
            ]

        has_key = bool(key)
        has_ov = bool(overrides)
        has_m = any(abs(val) > 1e-9 for _, val in macros)
        has_phe = abs(punch) > 1e-9 or abs(hold) > 1e-9 or abs(echo) > 1e-9
        live = has_key or has_ov or has_m or has_phe
        if not live:
            empty_hw.append(hw)
            continue

        live_hw.add(hw)
        ov_s = ", ".join(f"{k}={round(val, 3)}" for k, val in overrides) or "нет"
        mac_bits = []
        for mn, val in macros:
            if mn.startswith("oc_m_"):
                mac_bits.append(f"{mn}={round(val, 4)}")
            elif abs(val) > 1e-9:
                mac_bits.append(f"{mn}={round(val, 4)}")
        mac_s = ", ".join(mac_bits) or "—"
        voices_sec.append(
            f"hw{hw} voice[{v_idx if v_idx is not None else '?'}] "
            f"key='{key or '—'}' punch={round(punch, 3)} hold={round(hold, 3)} "
            f"echo={round(echo, 3)} | overrides: {ov_s}"
        )
        voices_sec.append(f"  buffer@{128 + hw}: {mac_s}")

        buf_map = {n: val for n, val in macros}
        for oid, oval in overrides:
            matched = None
            for c in (oid, f"oc_m_{oid}"):
                if c in buf_map:
                    matched = c
                    break
            if matched is None:
                for bn in buf_map:
                    if bn.replace("oc_m_", "") == oid or bn.endswith(oid):
                        matched = bn
                        break
            if matched is not None and abs(buf_map[matched] - oval) > 1e-3:
                anomalies.append(
                    f"hw{hw} override {oid}={oval} ≠ buffer {matched}={buf_map[matched]}"
                )

        if not has_key and (has_m or has_ov):
            anomalies.append(f"hw{hw} has macros/overrides but empty key")

    voices_sec.append(f"empty hw: {_compress_hw_ranges(empty_hw)}")

    # NOTES @ frame
    notes_sec = [
        f"\n## NOTES @ frame {scene.frame_current}",
        "heuristic: contributing = start<=F and (end<0 or F<=end); "
        "echo/fade in graph may outlive end",
    ]

    allocated = []
    for idx in range(min(NOTE_SLOT_COUNT, nverts)):
        st = _attr_val_mesh(mesh, "start_frame", idx)
        if st is None or st < 1.0:
            continue
        en = _attr_val_mesh(mesh, "end_frame", idx)
        vid = _attr_val_mesh(mesh, "octavia_voice_id", idx)
        allocated.append((idx, float(st), float(en) if en is not None else -1.0, vid))

    contributing = []
    recent = []
    for slot, st, en, vid in allocated:
        if _is_contributing(frame, st, en):
            contributing.append((slot, st, en, vid))
        elif en >= 0 and st <= frame and (frame - en) <= _BUFFER_RECENT_WINDOW:
            recent.append((slot, st, en, vid, "past"))
        elif st > frame and (st - frame) <= _BUFFER_RECENT_WINDOW:
            recent.append((slot, st, en, vid, "future"))

    notes_sec.append("### CONTRIBUTING")
    hit_nonzero = 0
    salvo_active_total = 0
    pivot_fallback_hints = 0

    if not contributing:
        notes_sec.append("  (none)")
    for slot, st, en, vid in contributing:
        status = _note_status(frame, st, en)
        dur = round(en - st, 1) if en >= 0 else None
        vid_i = int(vid) if vid is not None else -1
        v = voice_by_idx.get(vid_i)
        key = (getattr(v, "key_code", "") or "").strip() if v else ""
        hw = int(getattr(v, "hardware_id", -1)) if v else -1
        hp = _attr_vec_mesh(mesh, "hit_position", slot)
        hn = _attr_vec_mesh(mesh, "hit_normal", slot)
        if not _vec_near_zero(hp):
            hit_nonzero += 1
        else:
            anomalies.append(f"slot {slot} contributing but hit_position≈0")

        salvo = _salvo_active(mesh, slot, SALVO_STRIDE, salvo_vert_index)
        salvo_active_total += len(salvo)
        macros_hw = _hw_macro_vals(mesh, hw, macro_attrs) if hw >= 0 else []
        burst_n = _burst_count_from_macros(macros_hw)
        if burst_n is not None and 0 < len(salvo) < burst_n:
            anomalies.append(
                f"slot {slot} burst macro N={burst_n} but active particles={len(salvo)}"
            )

        if salvo and hp is not None:
            if all(
                bp is not None
                and abs(bp[0] - hp[0]) < 1e-4
                and abs(bp[1] - hp[1]) < 1e-4
                and abs(bp[2] - hp[2]) < 1e-4
                for _, _, bp, _, _ in salvo
            ):
                pivot_fallback_hints += 1

        dur_s = str(dur) if dur is not None else "open"
        voice_s = f"voice[{vid_i}]→key='{key or '—'}'/hw{hw}"
        salvo_s = f"salvo={len(salvo)}" + (
            f"/{burst_n}" if burst_n is not None else f"/{SALVO_STRIDE}"
        )
        p_bits = [
            f"p{p}@{sidx}:{_fmt_vec3(bp)}"
            for p, sidx, bp, bn, sst in salvo[:8]
        ]
        if len(salvo) > 8:
            p_bits.append("...")
        notes_sec.append(
            f"  slot {slot}: start={st:g} end={en:g} dur={dur_s} status={status} | {voice_s}"
        )
        notes_sec.append(
            f"    hit={_fmt_vec3(hp)} nml={_fmt_vec3(hn)} | {salvo_s}"
            + (f" | {'; '.join(p_bits)}" if p_bits else "")
        )

    notes_sec.append("### RECENT/PAST")
    if recent:
        for slot, st, en, vid, tag in recent[:16]:
            status = _note_status(frame, st, en)
            notes_sec.append(
                f"  slot {slot}: start={st:g} end={en:g} status={status} ({tag}) vid={vid}"
            )
        if len(recent) > 16:
            notes_sec.append(f"  ... +{len(recent) - 16} more")
    else:
        other = [
            (s, st, en, vid) for s, st, en, vid in allocated
            if not _is_contributing(frame, st, en)
        ]
        if not other:
            notes_sec.append("  (none)")
        else:
            bits = [f"s{s}:{st:g}→{en:g}" for s, st, en, vid in other[:12]]
            notes_sec.append(
                f"  other allocated ({len(other)}): " + ", ".join(bits)
                + (" ..." if len(other) > 12 else "")
            )

    # HIT / SALVO SUMMARY
    summary = [
        "\n## HIT / SALVO SUMMARY",
        f"contributing_notes={len(contributing)} | hit_nonzero={hit_nonzero} | "
        f"salvo_particles_active={salvo_active_total} | "
        f"pivot_fallback_suspect={pivot_fallback_hints}",
        f"allocated_note_slots={len(allocated)} | live_voices_hw={len(live_hw)}",
    ]

    # CURVES (index)
    curves_sec = ["\n## CURVES (index)"]
    act, curves = _collect_buffer_fcurves(mesh)
    by_slot = {}
    if act is None:
        curves_sec.append("  (no action on buffer mesh)")
    else:
        if ".001" in act.name:
            anomalies.append(f"action name looks duplicated: '{act.name}'")
        other_curves = 0
        for fc in curves:
            if not hasattr(fc, "data_path"):
                continue
            parsed = _parse_attr_curve_path(fc.data_path)
            if not parsed:
                other_curves += 1
                continue
            aname, idx = parsed
            fk = _first_key_frame(fc)
            if idx < NOTE_SLOT_COUNT:
                bucket = by_slot.setdefault(idx, {"start": None, "end": None, "salvo": []})
                if aname == "start_frame" and bucket["start"] is None:
                    bucket["start"] = fk
                elif aname == "end_frame" and bucket["end"] is None:
                    bucket["end"] = fk
            elif idx >= SALVO_BASE:
                note = (idx - SALVO_BASE) // SALVO_STRIDE
                p = (idx - SALVO_BASE) % SALVO_STRIDE
                if 0 <= note < NOTE_SLOT_COUNT:
                    bucket = by_slot.setdefault(note, {"start": None, "end": None, "salvo": []})
                    if aname == "start_frame":
                        bucket["salvo"].append((p, idx, fk))
            else:
                other_curves += 1

        n_notes_keyed = len(by_slot)
        dense = (
            n_notes_keyed > 0
            and len(curves) >= max(_BUFFER_CURVES_DENSE_PER_NOTE * n_notes_keyed, 80)
        )
        if dense:
            anomalies.append(
                f"dense curves: {len(curves)} fcurves for ~{n_notes_keyed} keyed notes"
            )
        curves_sec.append(
            f"  Action: {act.name} | curves_total={len(curves)}"
            + (" | warn: dense" if dense else "")
            + (f" | other={other_curves}" if other_curves else "")
        )
        priority = [s for s, _, _, _ in contributing] + [r[0] for r in recent]
        show_slots = [s for s in priority if s in by_slot]
        if not show_slots:
            show_slots = sorted(by_slot.keys())[:12]
        # unique preserve order
        seen_s = set()
        show_slots = [s for s in show_slots if not (s in seen_s or seen_s.add(s))]
        for slot in show_slots[:24]:
            b = by_slot[slot]
            salvo_bits = []
            seen_p = set()
            for p, vidx, fk in sorted(b["salvo"], key=lambda t: t[0]):
                if p in seen_p:
                    continue
                seen_p.add(p)
                salvo_bits.append(f"p{p}→v{vidx}" + (f"@{fk}" if fk is not None else ""))
            curves_sec.append(
                f"  slot {slot}: start@{b['start']} end@{b['end']}"
                + (f"; salvo {', '.join(salvo_bits[:8])}" if salvo_bits else "")
            )
        if len(by_slot) > len(show_slots[:24]):
            curves_sec.append(f"  ... +{len(by_slot) - len(show_slots[:24])} keyed slots")

    # EVAL
    eval_sec = ["\n## EVAL"]
    mesh_eval = None
    eval_err = None
    try:
        ctx = context or bpy.context
        depsgraph = ctx.evaluated_depsgraph_get()
        mesh_eval = buf_obj.evaluated_get(depsgraph).data
    except Exception as e:
        eval_err = str(e)

    if eval_err:
        eval_sec.append(f"raw vs eval: ERROR ({eval_err})")
        anomalies.append(f"eval read failed: {eval_err}")
    elif mesh_eval is None:
        eval_sec.append("raw vs eval: unavailable")
    else:
        slots_to_cmp = [s for s, _, _, _ in contributing] or [
            s for s, _, _, _ in allocated[:8]
        ]
        diffs = []
        for slot in slots_to_cmp:
            sig_r = _slot_eval_signature(mesh, slot, SALVO_STRIDE, salvo_vert_index)
            sig_e = _slot_eval_signature(mesh_eval, slot, SALVO_STRIDE, salvo_vert_index)
            if sig_r != sig_e:
                diffs.append(slot)
        if not diffs:
            eval_sec.append("raw vs eval: identical (checked contributing/allocated slots)")
        else:
            eval_sec.append(f"raw vs eval: DIFF on slots {diffs}")
            anomalies.append(f"raw≠eval on slots {diffs}")
            if forensic:
                for slot in diffs[:12]:
                    eval_sec.append(
                        f"  slot {slot} raw="
                        f"{_slot_eval_signature(mesh, slot, SALVO_STRIDE, salvo_vert_index)}"
                    )
                    eval_sec.append(
                        f"  slot {slot} eval="
                        f"{_slot_eval_signature(mesh_eval, slot, SALVO_STRIDE, salvo_vert_index)}"
                    )

    # ANOMALIES
    anom_sec = ["\n## ANOMALIES"]
    if anomalies:
        for a in anomalies:
            anom_sec.append(f"- {a}")
    else:
        anom_sec.append("none")

    lines = header + contract + wiring + voices_sec + notes_sec + summary
    lines += anom_sec + curves_sec + eval_sec

    if forensic:
        lines.append("\n--- FORENSIC APPENDIX ---")
        lines.append("### FULL CURVES")
        if act is None:
            lines.append("  (no action)")
        else:
            for fc in curves:
                if not hasattr(fc, "data_path"):
                    continue
                keys = [
                    (round(k.co[0], 1), round(k.co[1], 3), k.interpolation)
                    for k in fc.keyframe_points
                ]
                lines.append(f"  {fc.data_path}: {keys}")

        lines.append("### RAW ACTIVE / RECENT TABLES")
        dump_slots = sorted({
            *[s for s, _, _, _ in contributing],
            *[r[0] for r in recent],
            *[s for s, _, _, _ in allocated[:8]],
        })
        for slot in dump_slots:
            st = _attr_val_mesh(mesh, "start_frame", slot)
            en = _attr_val_mesh(mesh, "end_frame", slot)
            vid = _attr_val_mesh(mesh, "octavia_voice_id", slot)
            hp = _attr_vec_mesh(mesh, "hit_position", slot)
            hn = _attr_vec_mesh(mesh, "hit_normal", slot)
            lines.append(
                f"  slot {slot}: start={st} end={en} vid={vid} "
                f"hit={_fmt_vec3(hp, 4)} nml={_fmt_vec3(hn, 4)}"
            )
            for p, sidx, bp, bn, sst in _salvo_active(
                mesh, slot, SALVO_STRIDE, salvo_vert_index
            ):
                lines.append(
                    f"    p{p} v{sidx}: start={sst} pos={_fmt_vec3(bp, 4)} "
                    f"nml={_fmt_vec3(bn, 4)}"
                )

        lines.append("### CONFIG VERTS (128–159) non-empty")
        any_cfg = False
        for idx in range(128, min(160, nverts)):
            vals = []
            for mn in macro_attrs:
                val = _attr_val_mesh(mesh, mn, idx)
                if val is None:
                    continue
                if mn.startswith("oc_m_") or abs(val) > 1e-9:
                    vals.append(f"{mn}={round(val, 4)}")
            if vals:
                any_cfg = True
                lines.append(f"  v{idx} (hw{idx - 128}): {', '.join(vals)}")
        if not any_cfg:
            lines.append("  (none)")

    lines.append("\n================================================================================")
    return lines


def write_buffer_snapshot(
    scene, ch_idx, *, mode="FORENSIC", print_console=True, context=None, include_evaluated=None,
):
    """Пишет слепок в 3 места. include_evaluated: legacy True→FORENSIC, False→BRIEF."""
    if include_evaluated is False:
        mode = "BRIEF"
    elif include_evaluated is True:
        mode = "FORENSIC"
    lines = build_buffer_snapshot_lines(scene, ch_idx, mode=mode, context=context)
    return _write_buffer_report_files(scene, ch_idx, lines, print_console=print_console)


# ─── AUTO BRIEF ───
_AUTO_BUFFER_DEBOUNCE_SEC = 1.2
_auto_buffer_dirty_until = 0.0
_auto_buffer_last_hashes = {}
_auto_pending_buffers = set()


def _parse_buffer_channel(mesh_or_obj):
    name = getattr(mesh_or_obj, "name", "") or ""
    m = re.match(r"^Octavia_Buffer_Ch_(\d+)", name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _depsgraph_collect_buffers(depsgraph):
    found = False
    for update in depsgraph.updates:
        id_data = update.id
        orig = getattr(id_data, "original", id_data)
        ch = None
        if isinstance(orig, bpy.types.Mesh):
            if orig.get("is_octavia_buffer") or orig.name.startswith("Octavia_Buffer_Ch_"):
                ch = _parse_buffer_channel(orig)
        elif isinstance(orig, bpy.types.Object) and getattr(orig, "data", None):
            data = orig.data
            if isinstance(data, bpy.types.Mesh) and (
                data.get("is_octavia_buffer") or orig.name.startswith("Octavia_Buffer_Ch_")
            ):
                ch = _parse_buffer_channel(orig) or _parse_buffer_channel(data)
        elif isinstance(orig, bpy.types.Action):
            an = getattr(orig, "name", "") or ""
            m = re.search(r"Buffer_Ch_(\d+)", an)
            if m:
                try:
                    ch = int(m.group(1))
                except ValueError:
                    ch = None
        if ch is not None and ch >= 1:
            _auto_pending_buffers.add(ch)
            found = True
    return found


def _buffer_hash_text(report_text):
    """Хеш BRIEF без scrub-only полей шапки."""
    out = []
    for ln in report_text.splitlines():
        if ln.startswith("MODE:"):
            continue
        if ln.startswith("channel:") and "| frame:" in ln:
            m = re.match(r"(channel:\s*\d+)\s*\|", ln)
            if m and "fps:" in ln:
                out.append(m.group(1) + " | fps:" + ln.split("fps:")[-1])
            else:
                out.append(ln)
            continue
        if ln.startswith("## NOTES @ frame"):
            out.append("## NOTES @ frame")
            continue
        out.append(ln)
    return _content_hash("\n".join(out))


def _flush_auto_buffer_snapshots():
    global _auto_buffer_dirty_until

    remaining = _auto_buffer_dirty_until - time.time()
    if remaining > 0.05:
        return remaining

    scene = getattr(bpy.context, "scene", None)
    if not scene or not getattr(scene, "octavia_auto_buffer_snapshot", True):
        _auto_pending_buffers.clear()
        return None

    screen = getattr(bpy.context, "screen", None)
    if screen and getattr(screen, "is_animation_playing", False):
        return 0.5

    channels = set(_auto_pending_buffers)
    _auto_pending_buffers.clear()
    try:
        channels.add(int(getattr(scene, "octavia_active_channel", 1) or 1))
    except Exception:
        pass

    for ch_idx in sorted(channels):
        try:
            lines = build_buffer_snapshot_lines(
                scene, ch_idx, mode="BRIEF", context=bpy.context,
            )
            report_text = "\n".join(lines)
            text_hash = _buffer_hash_text(report_text)
            if _auto_buffer_last_hashes.get(ch_idx) == text_hash:
                continue

            written, errors, _ = _write_buffer_report_files(
                scene, ch_idx, lines, print_console=False,
            )
            _auto_buffer_last_hashes[ch_idx] = text_hash
            if written:
                print(
                    f"[Octavia] auto buffer BRIEF → {os.path.basename(written[0])} "
                    f"({len(written)} мест)"
                )
            elif errors:
                print(f"[Octavia] auto buffer fail (Ch{ch_idx}): {'; '.join(errors)}")
        except Exception as e:
            print(f"[Octavia] auto buffer snapshot error (Ch{ch_idx}): {e}")

    return None


@persistent
def _on_depsgraph_auto_buffer_snapshot(scene, depsgraph):
    if not getattr(scene, "octavia_auto_buffer_snapshot", True):
        return
    if not _depsgraph_collect_buffers(depsgraph):
        return

    global _auto_buffer_dirty_until
    _auto_buffer_dirty_until = time.time() + _AUTO_BUFFER_DEBOUNCE_SEC
    if not bpy.app.timers.is_registered(_flush_auto_buffer_snapshots):
        bpy.app.timers.register(
            _flush_auto_buffer_snapshots, first_interval=_AUTO_BUFFER_DEBOUNCE_SEC,
        )


def register_auto_buffer_snapshot():
    if _on_depsgraph_auto_buffer_snapshot not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_auto_buffer_snapshot)


def unregister_auto_buffer_snapshot():
    if _on_depsgraph_auto_buffer_snapshot in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_auto_buffer_snapshot)
    if bpy.app.timers.is_registered(_flush_auto_buffer_snapshots):
        bpy.app.timers.unregister(_flush_auto_buffer_snapshots)
    _auto_buffer_last_hashes.clear()
    _auto_pending_buffers.clear()


class OCTAVIA_OT_snapshot_buffer(bpy.types.Operator):
    """FORENSIC-слепок буфера активного канала (brief + appendix) для ИИ"""
    bl_idname = "octavia.snapshot_buffer"
    bl_label = "Снять слепок буфера"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        scene = context.scene
        ch_idx = scene.octavia_active_channel
        written, errors, _ = write_buffer_snapshot(
            scene, ch_idx, mode="FORENSIC", print_console=True, context=context,
        )
        if written:
            self.report({"INFO"}, f"FORENSIC буфера Ch{ch_idx} → {len(written)} мест(а)")
        else:
            self.report(
                {"WARNING"},
                f"Слепок буфера не записан: {'; '.join(errors) or 'нет путей'}",
            )
        return {"FINISHED"}
