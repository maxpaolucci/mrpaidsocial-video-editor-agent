#!/usr/bin/env python3
"""Build each version's audio: a bar-aligned music edit + placed VO, ducked and mastered.

  python3 build_audio.py cutdown.json [version ...]

Writes renders/audio/<v>_{bed,vo,mix}.wav and cues.json (music segment times by name, VO
lines, and spoken phrase groups -- cut the picture to those groups, not to whisper word times).
Every mix is exactly format.frames long, at loudness.lufs integrated with a true-peak ceiling."""
import json, re, subprocess, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutdown_lib import SR, Config, fade, ff, integrated_lufs, load_audio, speech_groups, write_audio  # noqa: E402


def music_timeline(cfg):
    m = cfg["music"]
    bar = 4 * 60 / float(m["bpm"]) if m.get("bpm") else None
    t, out = 0.0, []
    for i, seg in enumerate(m["segments"]):
        if "bars" in seg:
            dur = seg["bars"] * bar
        elif "dur" in seg:
            dur = float(seg["dur"])
        else:
            dur = cfg.duration - t  # last segment runs to the end
        out.append({"name": seg.get("name", f"seg{i}"), "t": t, "src": float(seg["src"]), "dur": dur})
        t += dur
    return out


def resolve_at(at, cues):
    """`at` is seconds, or "<cue name>[+/-seconds]" referencing a music segment start."""
    if isinstance(at, (int, float)):
        return float(at)
    m = re.fullmatch(r"\s*([A-Za-z_][\w-]*)\s*([+-]\s*[\d.]+)?\s*", str(at))
    if not m or m.group(1) not in cues:
        raise SystemExit(f"bad cue reference {at!r}; known cues: {', '.join(cues)}")
    return cues[m.group(1)] + float((m.group(2) or "0").replace(" ", ""))


def music_bed(cfg, timeline):
    m = cfg["music"]
    path = cfg.local(m["file"])
    xf = int(float(m.get("crossfade", 0.02)) * SR)
    n = int(round(cfg.duration * SR))
    out = np.zeros((n + SR, 2), np.float32)
    for k, seg in enumerate(timeline):
        # later segments start `xf` early to crossfade -- and so does their source, keeping every
        # downbeat on the grid (otherwise each splice lands the incoming material 20 ms early)
        pre = xf / SR if k else 0.0
        a = load_audio(path, seg["src"] - pre, seg["src"] + seg["dur"] + xf / SR)
        a = fade(a, int(float(m.get("fade_in", 0.4)) * SR) if k == 0 else xf, xf if k < len(timeline) - 1 else 0)
        i = max(0, int(round(seg["t"] * SR)) - (xf if k else 0))
        out[i:i + len(a)] += a[:len(out) - i]
    out = out[:n]
    return fade(out, 0, int(float(m.get("fade_out", 1.6)) * SR))


def vo_track(cfg, lines, cues):
    n = int(round(cfg.duration * SR))
    out = np.zeros((n, 2), np.float32)
    placed = []
    for ln in lines:
        t = resolve_at(ln["at"], cues)
        v = load_audio(cfg.local(ln["file"]), ln.get("in"), ln.get("out"), mono=True)
        v = fade(v, int(0.01 * SR), int(0.04 * SR))
        i = int(round(t * SR))
        k = max(0, min(len(v), n - i))
        out[i:i + k] += v[:k]
        placed.append({"file": ln["file"], "start": round(t, 3), "end": round(t + len(v) / SR, 3)})
    return out, placed


def master(cfg, vo_path, bed_path, out_path):
    a = cfg.get("audio", {})
    vo_chain = a.get("vo_chain", "highpass=f=80,lowpass=f=16000,"
                     "acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=4,volume=2dB")
    graph = (f"[0:a]{vo_chain},asplit=2[vo][sc];"
             f"[1:a]volume={a.get('bed_gain_db', -3)}dB[bed];"
             f"[bed][sc]sidechaincompress=threshold={a.get('duck_threshold', 0.03)}:ratio={a.get('duck_ratio', 4)}"
             ":attack=40:release=400[duck];[vo][duck]amix=inputs=2:normalize=0[out]")
    pre = out_path.with_name(out_path.stem + "_premix.wav")
    ff("-i", vo_path, "-i", bed_path, "-filter_complex", graph, "-map", "[out]", "-c:a", "pcm_f32le", pre)
    lufs, _ = integrated_lufs(pre)
    target, tp = float(a.get("lufs", -14)), float(a.get("true_peak", -1))
    limit = 10 ** (tp / 20)
    # static gain + latency-compensated limiter: loudnorm trims ~85 ms off the tail and drifts timing
    x = load_audio(pre)
    pre.unlink()
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                        "-af", f"volume={target - lufs:.2f}dB,alimiter=limit={limit:.4f}:attack=5:release=50:latency=1:level=0",
                        "-f", "f32le", "-"], input=x.tobytes(), capture_output=True, check=True).stdout
    y = np.frombuffer(r, np.float32).reshape(-1, 2)
    n = int(round(cfg.duration * SR))
    y = np.pad(y, ((0, max(0, n - len(y))), (0, 0)))[:n]
    write_audio(y, out_path)
    return integrated_lufs(out_path)


def main():
    cfg = Config(sys.argv[1])
    names = sys.argv[2:] or list(cfg["versions"])
    timeline = music_timeline(cfg)
    cues = {s["name"]: s["t"] for s in timeline}
    out_dir = cfg.out("renders", "audio", "x").parent
    bed = music_bed(cfg, timeline)
    cue_file = cfg.out("cues.json")
    allcues = json.loads(cue_file.read_text()) if cue_file.exists() else {}
    allcues.update({"fps": cfg.fps, "frames": cfg.frames, "duration": cfg.duration, "music": timeline})
    allcues.setdefault("versions", {})
    for name in names:
        ver = cfg["versions"][name]
        vo, placed = vo_track(cfg, ver.get("vo", []), cues)
        vo_p, bed_p, mix_p = out_dir / f"{name}_vo.wav", out_dir / f"{name}_bed.wav", out_dir / f"{name}_mix.wav"
        write_audio(vo, vo_p)
        write_audio(bed, bed_p)
        lufs, peak = master(cfg, vo_p, bed_p, mix_p)
        groups = speech_groups(vo_p)
        allcues["versions"][name] = {"vo": placed, "speech": groups}
        print(f"{name}: {lufs:.1f} LUFS, peak {peak:.1f} dBFS | VO " +
              ", ".join(f"{p['start']:.2f}-{p['end']:.2f}" for p in placed) +
              " | phrases " + " ".join(f"{a:.2f}-{b:.2f}" for a, b in groups))
    cue_file.write_text(json.dumps(allcues, indent=1))
    print("music: " + "  ".join(f"{s['name']}@{s['t']:.2f}s" for s in timeline) + f"  | {cfg.duration:.3f}s")


if __name__ == "__main__":
    main()
