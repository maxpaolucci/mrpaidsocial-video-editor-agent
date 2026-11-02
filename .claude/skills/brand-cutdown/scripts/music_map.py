#!/usr/bin/env python3
"""Map a music track's structure so short edits can splice on bar lines.

  python3 music_map.py <full_mix.wav> [--stems drums.wav bass.wav ...] [--master master.mp4]

Prints: per-4s levels for the mix and each stem (sections show up as stems entering/leaving),
BPM and bar length from the drum (or mix) onsets, drum entry/exit points snapped to the bar
grid, and -- with --master -- where the long-form edit's music sits in the track
(spectral fingerprint per 3s window; a steady offset over consecutive windows is a real match)."""
import argparse, subprocess
from pathlib import Path

import numpy as np

SR, HOP = 8000, 80  # onset envelope at 10 ms


def mono(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                        "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(r, np.float32)


def onset(x):
    n = len(x) // HOP
    e = np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(1))
    return np.maximum(0, np.diff(np.log(e + 1e-5), prepend=0))


def tempo(o, lo=60, hi=200):
    seg = o - o.mean()
    ac = np.correlate(seg, seg, "full")[len(seg) - 1:]
    lags = np.arange(int(100 * 60 / hi), int(100 * 60 / lo))
    beat = lags[np.argmax(ac[lags])] / 100
    bpm0 = 60 / beat

    def fit(bpm):
        p = 60 / bpm
        t = np.arange(0, len(o) / 100 - 1, p)
        return max(o[np.clip(((t + ph) * 100).astype(int), 0, len(o) - 1)].sum() for ph in np.arange(0, p, 0.01))
    bpm = max(np.arange(bpm0 - 2, bpm0 + 2, 0.05), key=fit)
    p = 60 / bpm
    t = np.arange(0, len(o) / 100 - 1, p)
    phase = max(np.arange(0, p, 0.01), key=lambda ph: o[np.clip(((t + ph) * 100).astype(int), 0, len(o) - 1)].sum())
    return bpm, phase


def spec(x, hop=400, win=1024):
    n = (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(x[idx] * np.hanning(win), axis=1))
    f = np.fft.rfftfreq(win, 1 / SR)
    edges = np.geomspace(60, 3500, 49)
    B = np.log(np.stack([S[:, (f >= a) & (f < b)].sum(1) for a, b in zip(edges, edges[1:])], 1) + 1e-3)
    B -= B.mean(1, keepdims=True)
    return B / np.linalg.norm(B, axis=1, keepdims=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mix")
    ap.add_argument("--stems", nargs="*", default=[])
    ap.add_argument("--master")
    a = ap.parse_args()
    tracks = {"MIX": mono(a.mix)}
    for s in a.stems:
        tracks[Path(s).stem[-12:]] = mono(s)
    names = list(tracks)
    print("time  " + "  ".join(f"{n[:8]:>8}" for n in names))
    for t in range(0, int(len(tracks["MIX"]) / SR), 4):
        print(f"{t:4d}s " + "  ".join(f"{20*np.log10(np.sqrt((tracks[n][t*SR:(t+4)*SR]**2).mean())+1e-9):8.1f}" for n in names))

    drums = next((tracks[n] for n in names if "DRUM" in n.upper()), tracks["MIX"])
    o = onset(drums)
    bpm, phase = tempo(o)
    bar = 4 * 60 / bpm
    print(f"\ntempo {bpm:.2f} BPM, beat {60/bpm:.4f}s, bar {bar:.4f}s, first beat phase {phase:.2f}s")

    env = 20 * np.log10(np.sqrt(np.convolve(drums ** 2, np.ones(800) / 800, "same")[::80]) + 1e-9)
    on = env > env.max() - 30
    edges = np.flatnonzero(np.diff(on.astype(int)))
    print("drum/energy entries (+) and exits (-), with nearest bar line on this grid:")
    for i in edges:
        t = i / 100
        k = round((t - phase) / bar)
        if i + 50 < len(on) and on[i + 1:i + 50].mean() > 0.6 or i - 50 > 0 and on[i - 50:i].mean() > 0.6:
            print(f"  {'+' if on[i + 1] else '-'} {t:7.2f}s  -> bar {k:4d} at {phase + k * bar:7.2f}s")

    if a.master:
        T, Mx = spec(tracks["MIX"]), spec(mono(a.master))
        fps = SR / 400
        print("\nmaster window -> track position (steady offsets over consecutive windows = a real match):")
        for m in np.arange(0, len(Mx) / fps - 3, 3.0):
            q = Mx[int(m * fps):int((m + 3) * fps)]
            L = len(q)
            sc = np.array([(T[i:i + L] * q).sum() / L for i in range(0, len(T) - L)])
            i = int(sc.argmax())
            print(f"  master {m:6.1f}s -> track {i/fps:7.2f}s  offset {i/fps-m:+8.2f}  sim {sc[i]:.2f}")


if __name__ == "__main__":
    main()
