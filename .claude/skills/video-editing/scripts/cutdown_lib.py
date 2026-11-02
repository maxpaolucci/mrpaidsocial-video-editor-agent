"""Shared helpers for video-editing: config, ffmpeg wrappers, timing and colour utilities.

Every script takes the project's cutdown.json; relative paths in it resolve against the
config file's directory, and `footage_root` is joined onto shot/plate/leak file names."""
import json, subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np

# Camera originals (ARRI ProRes, some mirrorless/drone files) can decode with bogus per-frame
# colour tags (csp:gbr, prim:reserved) that make swscale and encoders fail. Pin them first.
FIX = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709"
SR = 48000


class Config:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.dir = self.path.parent
        self.raw = json.loads(self.path.read_text())
        fmt = self.raw.get("format", {})
        self.width = int(fmt.get("width", 1080))
        self.height = int(fmt.get("height", 1920))
        self.fps_expr = str(fmt.get("fps", "24000/1001"))
        self.fps = float(Fraction(self.fps_expr))
        self.frames = int(fmt.get("frames", round(15 * self.fps)))
        self.duration = self.frames / self.fps
        root = self.raw.get("footage_root")
        self.footage_root = (self.dir / root).resolve() if root else self.dir

    def __getitem__(self, k):
        return self.raw[k]

    def get(self, k, default=None):
        return self.raw.get(k, default)

    def local(self, p):
        """A path that belongs to the project folder (audio, master, end card...)."""
        p = Path(p).expanduser()
        return p if p.is_absolute() else (self.dir / p)

    def footage(self, name):
        """A shot/plate/leak file: absolute, project-relative, or under footage_root."""
        p = Path(name).expanduser()
        if p.is_absolute():
            return p
        return (self.dir / p) if (self.dir / p).exists() else (self.footage_root / p)

    def out(self, *parts):
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *map(str, args)], check=True)


def probe_wh(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    nums = [int(x) for x in out.replace("\n", ",").split(",") if x.strip().isdigit()]
    return nums[0], nums[1]


def load_audio(path, start=None, end=None, mono=False, sr=SR):
    args = ["ffmpeg", "-nostdin", "-loglevel", "error"]
    if start is not None:
        args += ["-ss", f"{start:.4f}"]
    if end is not None:
        args += ["-to", f"{end:.4f}"]
    args += ["-i", str(path), "-ac", "1" if mono else "2", "-ar", str(sr), "-f", "f32le", "-"]
    x = np.frombuffer(subprocess.run(args, capture_output=True, check=True).stdout, np.float32)
    return x.reshape(-1, 1 if mono else 2).copy()


def write_audio(arr, path, codec="pcm_s24le"):
    ch = 1 if arr.ndim == 1 or arr.shape[1] == 1 else 2
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", str(ch),
                    "-i", "-", "-c:a", codec, str(path)], input=arr.astype(np.float32).tobytes(), check=True)


def fade(x, n_in=0, n_out=0):
    if n_in:
        x[:n_in] *= np.linspace(0, 1, n_in)[:, None]
    if n_out:
        x[-n_out:] *= np.linspace(1, 0, n_out)[:, None]
    return x


def integrated_lufs(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    lines = [l.split() for l in r.splitlines() if l.strip().startswith(("I:", "Peak:"))]
    vals = {l[0]: float(l[1]) for l in lines}
    return vals.get("I:"), vals.get("Peak:")


def speech_groups(path, threshold_db=-34.0, bridge=0.125, min_len=0.12, hop=0.025):
    """Spoken phrase spans [(start, end), ...] from an energy envelope; gaps < `bridge` are joined.
    Whisper puts a take's leading room tone inside the first word, so cut on these, not on its times."""
    x = load_audio(path, mono=True, sr=8000)[:, 0]
    h = int(hop * 8000)
    e = 20 * np.log10(np.sqrt((x[:len(x) // h * h].reshape(-1, h) ** 2).mean(1)) + 1e-9)
    on, gap = e > threshold_db, int(round(bridge / hop))
    groups, i = [], 0
    while i < len(on):
        if not on[i]:
            i += 1
            continue
        j = i
        while j < len(on) and (on[j] or on[j:j + gap].any()):
            j += 1
        if (j - i) * hop > min_len:
            groups.append((round(i * hop, 3), round(j * hop, 3)))
        i = j
    return groups


def frame_rgb(path, t, size=(480, 270)):
    w, h = size
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                        "-vf", f"{FIX},scale={w}:{h},format=rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(r, np.uint8).reshape(h, w, 3)


def match_lut(source_rgb, target_rgb, strength=0.75, margin=0.15):
    """Per-channel histogram match of source -> target over the central region, as a 256x3 table in 0-1.
    `strength` blends toward identity so one noisy frame cannot wreck a shot."""
    h, w = source_rgb.shape[:2]
    ys, xs = slice(int(h * margin), int(h * (1 - margin))), slice(int(w * margin), int(w * (1 - margin)))
    q = np.linspace(0, 1, 256)
    ident = np.arange(256) / 255
    lut = []
    for c in range(3):
        sq = np.quantile(source_rgb[ys, xs, c], q) + np.arange(256) * 1e-6
        tq = np.quantile(target_rgb[ys, xs, c], q)
        lut.append(np.clip(np.interp(np.arange(256), np.maximum.accumulate(sq), tq), 0, 255) / 255)
    return (1 - strength) * ident[:, None] + strength * np.stack(lut, 1)


def write_cube(lut, path):
    Path(path).write_text("LUT_1D_SIZE 256\n" + "".join(f"{r:.6f} {g:.6f} {b:.6f}\n" for r, g, b in lut))
    return path


def crop_expr(shot, src_w, src_h, out_w, out_h, dur):
    """ffmpeg filter that reframes a source to out_w x out_h.
    modes: crop (default; x = centre 0-1, optional x_end to pan, zoom > 1 to tighten, y = centre),
           fit (whole frame on black), square (centred square gate on black)."""
    mode = shot.get("mode", "crop")
    if mode == "fit":
        return f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
    if mode == "square":
        side = min(src_w, src_h) // 2 * 2
        x = int(np.clip(shot.get("x", 0.5) * src_w - side / 2, 0, src_w - side))
        y = int(np.clip(shot.get("y", 0.5) * src_h - side / 2, 0, src_h - side))
        s = min(out_w, out_h)
        return f"crop={side}:{side}:{x}:{y},scale={s}:{s}:flags=lanczos,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black"
    target = out_w / out_h
    zoom = float(shot.get("zoom", 1.0))
    if src_w / src_h > target:  # source wider: full height, crop width
        ch = int(src_h / zoom) // 2 * 2
        cw = int(ch * target) // 2 * 2
    else:
        cw = int(src_w / zoom) // 2 * 2
        ch = int(cw / target) // 2 * 2
    y = int(np.clip(shot.get("y", 0.5) * src_h - ch / 2, 0, src_h - ch))
    x0 = shot.get("x", 0.5) * src_w - cw / 2
    if "x_end" in shot:
        x1 = shot["x_end"] * src_w - cw / 2
        x = f"'clip({x0:.1f}+({x1 - x0:.1f})*t/{dur:.4f},0,{src_w - cw})'"
    else:
        x = int(np.clip(x0, 0, src_w - cw))
    return f"crop={cw}:{ch}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos"
