#!/usr/bin/env python3
"""Extract every sequence's video track items from a Premiere .prproj (gzipped XML).

  python3 prproj.py <edit.prproj> <sequences.json>

Each item: timeline start/end (s), source path, source in/out (s), speed, enabled, motion
(Scale/Position first values). Disabled clips (Premiere's IsMuted) are kept but flagged, so a
resolver can skip them -- a disabled clip on a higher track otherwise "wins" and is wrong."""
import gzip, json, sys
import xml.etree.ElementTree as ET

TICKS = 254016000000  # Premiere ticks per second


def parse(path):
    with open(path, "rb") as f:
        head = f.read(2)
    opener = gzip.open if head == b"\x1f\x8b" else open
    with opener(path, "rb") as f:
        root = ET.parse(f).getroot()
    by_id, by_uid = {}, {}
    for el in root:
        if "ObjectID" in el.attrib:
            by_id[el.attrib["ObjectID"]] = el
        if "ObjectUID" in el.attrib:
            by_uid[el.attrib["ObjectUID"]] = el

    def ref(el):
        if el is None:
            return None
        if "ObjectRef" in el.attrib:
            return by_id.get(el.attrib["ObjectRef"])
        if "ObjectURef" in el.attrib:
            return by_uid.get(el.attrib["ObjectURef"])
        return el

    def num(el, p):
        x = el.find(p) if el is not None else None
        return int(x.text) if x is not None and x.text and x.text.lstrip("-").isdigit() else None

    def text(el, p):
        x = el.find(p) if el is not None else None
        return x.text if x is not None else None

    def motion(item):
        out = {}
        comps = ref(item.find("ClipTrackItem/ComponentOwner/Components"))
        for c in (comps.iter("Component") if comps is not None else []):
            comp = ref(c)
            if comp is None or text(comp, "MatchName") != "AE.ADBE Motion":
                continue
            for p in comp.iter("Param"):
                prm = ref(p)
                name = text(prm, "Name")
                val = text(prm, "StartKeyframe") or text(prm, "CurrentValue")
                if name in ("Position", "Scale", "Rotation") and val:
                    out[name] = val.split(",", 1)[-1].split(",")[0]
                    if text(prm, "Keyframes"):
                        out[name + "_animated"] = True
        return out

    seqs = []
    for seq in root.iter("Sequence"):
        tg = seq.find("TrackGroups")
        if tg is None:
            continue
        tracks = []
        for g in tg.iter("TrackGroup"):
            grp = ref(g.find("Second")) if g.find("Second") is not None else None
            if grp is None or grp.tag != "VideoTrackGroup":
                continue
            for t in grp.iter("Track"):
                trk = ref(t)
                if trk is None or trk.tag != "VideoClipTrack":
                    continue
                items = []
                for ti in trk.iter("TrackItem"):
                    it = ref(ti)
                    if it is None or it.tag != "VideoClipTrackItem":
                        continue
                    s, e = num(it, "ClipTrackItem/TrackItem/Start"), num(it, "ClipTrackItem/TrackItem/End")
                    sub = ref(it.find("ClipTrackItem/SubClip"))
                    clip = ref(sub.find("Clip")) if sub is not None else None
                    src = ref(clip.find("Clip/Source")) if clip is not None else None
                    med = ref(src.find("MediaSource/Media")) if src is not None else None
                    cin, cout = num(clip, "Clip/InPoint"), num(clip, "Clip/OutPoint")
                    speed = text(clip, "Clip/PlaybackSpeed")
                    items.append({
                        "start": s / TICKS if s is not None else None,
                        "end": e / TICKS if e is not None else None,
                        "source": (text(med, "ActualMediaFilePath") or text(med, "FilePath")) if med is not None else None,
                        "name": text(sub, "Name"),
                        "src_in": cin / TICKS if cin is not None else None,
                        "src_out": cout / TICKS if cout is not None else None,
                        "speed": float(speed) if speed else 1.0,
                        "enabled": (text(it, "ClipTrackItem/IsMuted") or "false").lower() != "true",
                        "motion": motion(it),
                    })
                tracks.append(sorted(items, key=lambda x: x["start"] or 0))
        seqs.append({"name": text(seq, "Name"), "video_tracks": tracks})
    return seqs


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    seqs = parse(sys.argv[1])
    json.dump(seqs, open(sys.argv[2], "w"), indent=1)
    for s in seqs:
        items = [i for t in s["video_tracks"] for i in t]
        end = max((i["end"] or 0) for i in items) if items else 0
        off = sum(not i["enabled"] for i in items)
        print(f"{s['name']!r}: {len(s['video_tracks'])} video tracks, {len(items)} items "
              f"({off} disabled), ends {end:.2f}s")
