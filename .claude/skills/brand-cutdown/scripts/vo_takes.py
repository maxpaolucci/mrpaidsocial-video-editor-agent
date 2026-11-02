#!/usr/bin/env python3
"""Find and verify voiceover takes in a raw record session.

  python3 vo_takes.py map <session.wav> [--from S --to E] > takes.txt
      Phrase islands (from silence detection, reliable bounds) labelled with whisper text
      (approximate: labels can drift by a word -- trust the bounds, not the label).
  python3 vo_takes.py extract <session.wav> <candidates.tsv> <outdir>
      candidates.tsv: name<TAB>start<TAB>end (session seconds). Cuts each select at 24-bit and
      re-transcribes it alone, so every pick is verified word for word before it is used.

Whisper model: $WHISPER_MODEL, else the first ggml-*.bin under ~/.cache/hyperframes/whisper/models."""
import argparse, json, os, re, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cutdown_lib import ff  # noqa: E402


def model():
    m = os.environ.get("WHISPER_MODEL")
    if m:
        return m
    found = sorted((Path.home() / ".cache/hyperframes/whisper/models").glob("ggml-*.bin"))
    if not found:
        sys.exit("No whisper model: set WHISPER_MODEL or run `npx hyperframes transcribe` once to fetch one")
    return str(found[-1])


def to16k(src, dst, start=None, end=None):
    args = (["-ss", start] if start is not None else []) + (["-to", end] if end is not None else [])
    ff(*args, "-i", src, "-ac", 1, "-ar", 16000, dst)


def words(wav):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["whisper-cli", "-m", model(), "-f", str(wav), "-ojf", "-of", f"{td}/w", "-np"],
                       capture_output=True, check=True)
        d = json.load(open(f"{td}/w.json"))
    out = []
    for s in d["transcription"]:
        for t in s["tokens"]:
            tx = t["text"]
            if tx.startswith("[_"):
                continue
            if tx.startswith(" ") or not out:
                out.append([tx.strip(), t["offsets"]["from"] / 1000])
            else:
                out[-1][0] += tx
    return out


def text_of(wav):
    return " ".join(w for w, _ in words(wav))


def gaps(wav, start, end, noise=-45, d=0.25):
    r = subprocess.run(["ffmpeg", "-nostdin", "-ss", str(start), "-to", str(end), "-i", str(wav), "-af",
                        f"silencedetect=noise={noise}dB:d={d}", "-f", "null", "-"], capture_output=True, text=True).stderr
    marks = [float(x) + start for x in re.findall(r"silence_(?:start|end): ([0-9.]+)", r)]
    return list(zip(marks[0::2], marks[1::2]))


def cmd_map(a):
    with tempfile.TemporaryDirectory() as td:
        w16 = Path(td) / "s.wav"
        to16k(a.session, w16, a.start, a.end)
        ws = words(w16)
    off = a.start or 0.0
    g = gaps(a.session, off, a.end or 1e9)
    islands = [(x[1], y[0]) for x, y in zip(g, g[1:]) if y[0] - x[1] > 0.15]
    for s, e in islands:
        txt = " ".join(w for w, t in ws if s - 0.4 <= t + off < e - 0.1)
        print(f"{s:8.2f}-{e:8.2f} ({e - s:5.2f}s) {txt}")


def cmd_extract(a):
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for line in Path(a.candidates).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, s, e = line.split("\t")[:3]
        dst = out / f"{name}.wav"
        ff("-ss", s, "-to", e, "-i", a.session, "-c:a", "pcm_s24le", dst)
        with tempfile.TemporaryDirectory() as td:
            w16 = Path(td) / "c.wav"
            to16k(dst, w16)
            print(f"{name:28s} {float(e) - float(s):5.2f}s | {text_of(w16)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map")
    m.add_argument("session")
    m.add_argument("--from", dest="start", type=float)
    m.add_argument("--to", dest="end", type=float)
    x = sub.add_parser("extract")
    x.add_argument("session")
    x.add_argument("candidates")
    x.add_argument("outdir")
    a = ap.parse_args()
    {"map": cmd_map, "extract": cmd_extract}[a.cmd](a)
