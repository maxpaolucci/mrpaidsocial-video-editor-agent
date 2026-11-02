#!/usr/bin/env python3
"""Render each version: per-shot reframe + grade match from camera originals, open/close plates,
light-leak transitions, alpha end card, and the mix from build_audio.py.

  python3 build_video.py cutdown.json [version ...] [--overwrite]

Segments are rendered to frame-exact ProRes intermediates (renders/segments/<v>/), concatenated,
then composited and encoded once to H.264. Delivered files are never replaced without --overwrite:
bump output.revision for a new round instead."""
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutdown_lib import FIX, Config, crop_expr, ff, frame_rgb, match_lut, probe_wh, write_cube  # noqa: E402

PRORES = ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
          "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]


def segment(cfg, path, src_in, speed, frames, vf, out, lut=None):
    """Reframe in YUV, then grade in 10-bit RGB and re-tag before returning to YUV."""
    dur = frames / cfg.fps * speed + 0.5
    grade = (f",format=gbrp10le,lut1d=file='{lut}':interp=linear,"
             "setparams=colorspace=gbr:color_primaries=bt709:color_trc=bt709:range=pc,"
             "scale=out_color_matrix=bt709:out_range=tv") if lut else ""
    ff("-ss", f"{src_in:.4f}", "-t", f"{dur:.3f}", "-i", path, "-an", "-vf",
       f"{FIX}:range=tv,setpts=(PTS-STARTPTS)/{speed},fps={cfg.fps_expr},{vf}{grade},"
       "format=yuv422p10le,setparams=colorspace=bt709:range=tv,setsar=1",
       "-frames:v", frames, *PRORES, out)


def shot_lut(cfg, edit, shot, out):
    g = shot.get("grade", "match" if "mt" in shot and edit else "none")
    if g == "none":
        return None
    if g != "match":
        return cfg.local(g)
    mid = edit.visible(shot["mt"], shot.get("track"))
    m = (mid["item_start"] + mid["item_end"]) / 2  # mid-item avoids the light-leak frames at cuts
    src_mid = edit.visible(m, shot.get("track"))["src_t"]
    lut = match_lut(frame_rgb(cfg.footage(shot["file"]), src_mid), frame_rgb(cfg.local(cfg["master"]), m),
                    strength=float(shot.get("grade_strength", cfg.get("grade_strength", 0.75))))
    return write_cube(lut, out)


def plate(cfg, spec, frames, out):
    p = cfg.footage(spec["file"])
    w, h = probe_wh(p)
    segment(cfg, p, float(spec.get("src", 0)), float(spec.get("speed", 1)), frames,
            crop_expr(spec, w, h, cfg.width, cfg.height, frames / cfg.fps), out)


def build(cfg, name, edit, overwrite):
    ver = cfg["versions"][name]
    o = cfg.get("output", {})
    out = cfg.out("renders", f"{o.get('prefix', '')}{name}_{cfg.width}x{cfg.height}_{o.get('revision', 'v01')}.mp4")
    if out.exists() and not overwrite:
        sys.exit(f"{out.name} exists -- bump output.revision for a new round, or pass --overwrite for an undelivered file")
    work = cfg.out("renders", "segments", name, "x").parent
    fr = lambda t: int(round(t * cfg.fps))
    shots = ver["shots"]
    cuts = [0] + [fr(s["t"]) for s in shots] + [fr(ver["end_start"]), cfg.frames]
    parts = [work / "00_open.mov"]
    plate(cfg, cfg["plates"]["open"], cuts[1], parts[0])
    for k, s in enumerate(shots):
        n, dur = cuts[k + 2] - cuts[k + 1], (cuts[k + 2] - cuts[k + 1]) / cfg.fps
        src = cfg.footage(s["file"])
        w, h = s.get("src_wh") or probe_wh(src)
        lut = shot_lut(cfg, edit, s, work / f"{k + 1:02d}.cube")
        p = work / f"{k + 1:02d}.mov"
        segment(cfg, src, float(s["src_in"]), float(s.get("speed", 1)), n, crop_expr(s, w, h, cfg.width, cfg.height, dur), p, lut)
        parts.append(p)
    parts.append(work / "99_close.mov")
    plate(cfg, cfg["plates"]["close"], cuts[-1] - cuts[-2], parts[-1])
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{q}'\n" for q in parts))
    base = work / "base.mov"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", base)

    W, H = cfg.width, cfg.height
    leaks, ec = cfg.get("leaks", {}), cfg["endcard"]
    op, ld = float(leaks.get("opacity", 0.7)), float(leaks.get("dur", 0.8))
    t_open = shots[0]["t"] - float(leaks.get("open", {}).get("lead", 0.27))
    t_close = ver["end_start"] - float(leaks.get("close", {}).get("lead", 0.25))
    ec_w, ec_h = probe_wh(cfg.local(ec["file"]))
    if W >= ec_w:  # card narrower than the frame: scale to width
        ec_fit, ec_h_out = f"scale={W}:-2", int(ec_h * W / ec_w)
    else:          # wider card (e.g. 16:9 card on 9:16): crop the centre, keep native size
        cx = int(float(ec.get("crop_x", 0.5)) * ec_w - W / 2)
        ec_fit, ec_h_out = f"crop={W}:{ec_h}:{max(0, min(cx, ec_w - W))}:0", ec_h
    y = int(ec.get("y", (H - ec_h_out) / 2))
    end_t = float(ver["end_start"])
    leak = lambda i, t0: (f"[{i}:v]trim=duration={ld},scale=-2:{H},crop={W}:{H},format=gbrp,setpts=PTS-STARTPTS,"
                          f"tpad=start_duration={t0:.3f}:color=black[l{i}];")
    fc = (f"[0:v]format=gbrp[b];" + leak(1, t_open) + leak(2, t_close) +
          f"[b][l1]blend=all_mode=screen:all_opacity={op}:shortest=0:repeatlast=0,format=gbrp[b1];"
          f"[b1][l2]blend=all_mode=screen:all_opacity={op}:shortest=0:repeatlast=0,format=rgba[b2];"
          f"[3:v]{FIX},format=rgba,setpts=PTS-STARTPTS,{ec_fit},"
          f"fade=t=in:st=0:d={float(ec.get('fade_in', 0.3))}:alpha=1,setpts=PTS+{end_t:.4f}/TB[ec];"
          f"[b2][ec]overlay=0:{y}:eof_action=pass,format=yuv420p[v]")
    ff("-i", base,
       "-stream_loop", "-1", "-i", cfg.footage(leaks["open"]["file"]),
       "-stream_loop", "-1", "-i", cfg.footage(leaks["close"]["file"]),
       "-ss", f"{float(ver.get('endcard_src', ec.get('src', 0))):.3f}", "-i", cfg.local(ec["file"]),
       "-i", cfg.local(f"renders/audio/{name}_mix.wav"),
       "-filter_complex", fc, "-map", "[v]", "-map", "4:a", "-frames:v", cfg.frames, "-r", cfg.fps_expr,
       "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-profile:v", "high", "-pix_fmt", "yuv420p",
       "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
       "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", "-shortest", out)
    print(f"{name}: {out.relative_to(cfg.dir)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("versions", nargs="*")
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    cfg = Config(a.config)
    edit = None
    if cfg.get("edit"):
        from resolve import Edit
        edit = Edit(cfg)
    for n in a.versions or cfg["versions"]:
        build(cfg, n, edit, a.overwrite)


if __name__ == "__main__":
    main()
