#!/usr/bin/env python3
"""Map master-video moments to the source clip that is visible there in the edit project.

  python3 resolve.py cutdown.json --align              # find master->sequence offset from the cut list
  python3 resolve.py cutdown.json --at 22.6 43.9 ...   # print sources + write a master|source sheet
  python3 resolve.py cutdown.json --fill               # fill file/src_in/speed/src_wh for shots with `mt` and no source
  python3 resolve.py cutdown.json --fill --refill      # ...and overwrite hand-tuned sources too

The visible clip is the highest enabled video track at that time, skipping names in
edit.skip (adjustment layers, light-leak overlays, graphics). Always look at the sheet:
the timeline's top clip is not always what was exported (blend modes, opacity, crops)."""
import argparse, json, os, subprocess, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutdown_lib import Config, FIX, ff, probe_wh  # noqa: E402


class Edit:
    def __init__(self, cfg):
        e = cfg["edit"]
        seqs = {s["name"]: s for s in json.load(open(cfg.local(e["sequences"])))}
        self.cfg, self.tracks = cfg, seqs[e["sequence"]]["video_tracks"]
        self.offset = float(e.get("offset", 0.0))
        self.skip = tuple(e.get("skip", []))

    def visible(self, mt, track=None):
        t = mt + self.offset
        best = None
        for ti, trk in enumerate(self.tracks):
            if track is not None and ti != track - 1:
                continue
            for it in trk:
                name = os.path.basename(it["source"] or "") or (it["name"] or "")
                if it["start"] is None or not (it["start"] <= t < it["end"]) or not it.get("enabled", True):
                    continue
                if name.startswith(self.skip):
                    continue
                if best is None or ti >= best[0]:
                    best = (ti, it, name)
        if best is None:
            return None
        ti, it, name = best
        return {"track": ti + 1, "file": name, "src_t": it["src_in"] + (t - it["start"]) * it["speed"],
                "speed": it["speed"], "item_start": it["start"] - self.offset, "item_end": it["end"] - self.offset}

    def starts(self):
        return np.array(sorted({round(i["start"], 3) for t in self.tracks for i in t if i["start"] is not None}))


def detect_cuts(master, threshold=0.25):
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", str(master), "-vf", f"select='gt(scene,{threshold})',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    return np.array([float(l.split("pts_time:")[1].split()[0]) for l in r.splitlines() if "pts_time:" in l])


def align(cfg, edit):
    cuts, starts = detect_cuts(cfg.local(cfg["master"])), edit.starts()
    best = (0, 0.0)
    for off in np.arange(-300, 300, 0.01):
        score = int(sum(np.min(np.abs(starts - off - c)) < 0.05 for c in cuts))
        if score > best[0]:
            best = (score, round(float(off), 2))
    print(f"{best[0]}/{len(cuts)} master cuts match item starts with sequence_time = master_time + {best[1]}s")
    print("set edit.offset to that value (flash frames and dissolves account for most misses)")


def sheet(cfg, edit, times, out):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in times:
        v = edit.visible(t)
        print(f"{t:7.2f}  " + (f"V{v['track']:<2} {v['file'][:50]:50s} src {v['src_t']:8.2f}s x{v['speed']}" if v else "(nothing)"))
        if not v:
            continue
        m, s = out / f"m_{t:06.2f}.png", out / f"s_{t:06.2f}.png"
        ff("-ss", t, "-i", cfg.local(cfg["master"]), "-frames:v", 1, "-vf", "scale=480:270", m)
        ff("-ss", f"{v['src_t']:.3f}", "-i", cfg.footage(v["file"]), "-frames:v", 1,
           "-vf", f"{FIX},scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:-1:-1", s)
        rows.append((m, s))
    for k in range(0, len(rows), 10):
        chunk, ins = rows[k:k + 10], []
        for m, s in chunk:
            ins += ["-i", m, "-i", s]
        n = len(chunk)
        fc = "".join(f"[{2*i}:v]format=rgb24,setsar=1[a{i}];[{2*i+1}:v]format=rgb24,setsar=1[b{i}];[a{i}][b{i}]hstack[r{i}];"
                     for i in range(n)) + "".join(f"[r{i}]" for i in range(n)) + f"vstack=inputs={n}[o]"
        ff(*ins, "-filter_complex", fc, "-map", "[o]", out.parent / f"{out.name}_{k // 10 + 1}.png")
    print(f"sheets: {out.parent}/{out.name}_*.png  (left = master, right = source)")


def fill(cfg, edit, refill=False):
    """Fill source fields for shots that have `mt` but no source yet; hand-tuned in points
    (e.g. a later src_in to keep a moving subject in frame) survive unless refill=True."""
    raw = cfg.raw
    for name, ver in raw["versions"].items():
        for s in ver["shots"]:
            if "mt" not in s or ("file" in s and "src_in" in s and not refill):
                continue
            v = edit.visible(s["mt"], s.get("track"))
            if v is None:
                sys.exit(f"{name}: nothing visible at master {s['mt']}")
            s.update(file=v["file"], src_in=round(v["src_t"], 3), speed=v["speed"],
                     src_wh=list(probe_wh(cfg.footage(v["file"]))))
            print(f"{name} {s['t']:6.2f}s  {v['file'][:48]:48s} src {s['src_in']:8.2f} x{s['speed']} {s['src_wh']}")
    cfg.path.write_text(json.dumps(raw, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--align", action="store_true")
    ap.add_argument("--at", nargs="*", type=float)
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--refill", action="store_true")
    a = ap.parse_args()
    cfg = Config(a.config)
    edit = Edit(cfg)
    if a.align:
        align(cfg, edit)
    if a.at:
        sheet(cfg, edit, a.at, cfg.out("evidence", "resolve", "pairs"))
    if a.fill or a.refill:
        fill(cfg, edit, a.refill)
