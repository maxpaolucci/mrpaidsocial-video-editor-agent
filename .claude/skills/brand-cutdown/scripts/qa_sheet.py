#!/usr/bin/env python3
"""Frame-evidence for a rendered cut-down: one strip per version with a frame from every shot,
the first frame after each cut (leak tails), and the end card's build and hold.

  python3 qa_sheet.py cutdown.json [version ...]

Also asserts the deliverable contract: exact frame count, WxH, audio length == video length,
loudness within 0.5 LU of target. Look at the strips -- this is where lost subjects, letterbox
bars and heavy leak tints show up."""
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutdown_lib import Config, ff, integrated_lufs  # noqa: E402


def probe(path):
    r = json.loads(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                   "stream=codec_type,width,height,nb_read_frames,duration", "-of", "json", str(path)],
                                  capture_output=True, text=True, check=True).stdout)["streams"]
    return {s["codec_type"]: s for s in r}


def main():
    cfg = Config(sys.argv[1])
    o = cfg.get("output", {})
    ok = True
    for name in sys.argv[2:] or cfg["versions"]:
        ver = cfg["versions"][name]
        out = cfg.local(f"renders/{o.get('prefix', '')}{name}_{cfg.width}x{cfg.height}_{o.get('revision', 'v01')}.mp4")
        s = probe(out)
        v, a = s["video"], s.get("audio", {})
        lufs, peak = integrated_lufs(out)
        checks = {
            "frames": int(v["nb_read_frames"]) == cfg.frames,
            "size": (int(v["width"]), int(v["height"])) == (cfg.width, cfg.height),
            "audio_len": abs(float(a.get("duration", 0)) - cfg.frames / cfg.fps) < 0.03,
            "loudness": abs(lufs - float(cfg.get("audio", {}).get("lufs", -14))) <= 0.5,
        }
        ok &= all(checks.values())
        print(f"{name}: {v['nb_read_frames']} frames {v['width']}x{v['height']}, {lufs:.1f} LUFS / {peak:.1f} dBFS  "
              + " ".join(f"{k}={'ok' if c else 'FAIL'}" for k, c in checks.items()))
        fr = lambda t: int(round(t * cfg.fps))
        ts = [s_["t"] for s_ in ver["shots"]] + [ver["end_start"], cfg.duration]
        picks = [fr(1.0)]
        for t0, t1 in zip(ts, ts[1:]):
            picks += [fr(t0) + 1, (fr(t0) + fr(t1)) // 2]
        picks += [cfg.frames - 1]
        picks = sorted({min(max(p, 0), cfg.frames - 1) for p in picks})
        sel = "+".join(f"eq(n\\,{p})" for p in picks)
        dst = cfg.out("_qa", f"{name}_sheet.png")
        ff("-i", out, "-vf", f"select='{sel}',scale=240:-2,tile={len(picks)}x1", "-fps_mode", "vfr", "-frames:v", 1, dst)
        print(f"   sheet: {dst.relative_to(cfg.dir)}  frames {picks}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
