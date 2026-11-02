"""Offline tests for video-editing's pure logic (no footage, no network).
Run: python3 -m unittest discover -s .claude/skills/video-editing/tests -v"""
import gzip, json, subprocess, sys, tempfile, unittest
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_audio  # noqa: E402
import prproj  # noqa: E402
from cutdown_lib import Config, crop_expr, match_lut, speech_groups, write_audio  # noqa: E402

TICKS = prproj.TICKS


def config(tmp, **over):
    raw = {"format": {"width": 1080, "height": 1920, "fps": "24000/1001", "frames": 360}, "versions": {}}
    raw.update(over)
    p = Path(tmp) / "cutdown.json"
    p.write_text(json.dumps(raw))
    return Config(p)


class Reframe(unittest.TestCase):
    def test_vertical_crop_from_landscape_is_full_height_and_clamped(self):
        f = crop_expr({"x": 0.5}, 3840, 2160, 1080, 1920, 1.0)
        self.assertTrue(f.startswith("crop=1214:2160:1313:0,scale=1080:1920"), f)
        edge = crop_expr({"x": 0.99}, 3840, 2160, 1080, 1920, 1.0)
        self.assertIn(":2626:0,", edge)  # clamped to iw - cw

    def test_zoom_tightens_and_pan_uses_time_expression(self):
        z = crop_expr({"x": 0.5, "zoom": 1.4}, 1920, 1080, 1080, 1920, 1.0)
        self.assertTrue(z.startswith("crop=432:770:"), z)
        pan = crop_expr({"x": 0.4, "x_end": 0.8}, 3200, 1800, 1080, 1920, 0.9)
        self.assertIn("*t/0.9000", pan)

    def test_square_and_fit_modes_pad_on_black(self):
        sq = crop_expr({"mode": "square"}, 1280, 720, 1080, 1920, 1.0)
        self.assertTrue(sq.startswith("crop=720:720:280:0,scale=1080:1080"), sq)
        self.assertIn("pad=1080:1920", crop_expr({"mode": "fit"}, 1920, 1080, 1080, 1920, 1.0))

    def test_portrait_source_into_square_crops_height(self):
        f = crop_expr({}, 1080, 1920, 1080, 1080, 1.0)
        self.assertTrue(f.startswith("crop=1080:1080:0:420"), f)


class Grade(unittest.TestCase):
    def test_identical_frames_give_identity_and_lut_is_monotonic(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, (90, 160, 3), dtype=np.uint8)
        lut = match_lut(img, img)
        self.assertLess(np.abs(lut - (np.arange(256) / 255)[:, None]).max(), 0.02)
        darker = (img * 0.6).astype(np.uint8)
        lut2 = match_lut(img, darker)
        self.assertTrue((np.diff(lut2, axis=0) >= -1e-9).all())
        self.assertLess(lut2[200, 0], 200 / 255)


class Music(unittest.TestCase):
    def test_timeline_bars_and_cue_references(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = config(td, music={"file": "x.wav", "bpm": 120, "segments": [
                {"name": "open", "src": 10, "bars": 2}, {"name": "drop", "src": 40, "bars": 1}, {"name": "outro", "src": 90}]})
            tl = build_audio.music_timeline(cfg)
            self.assertEqual([s["t"] for s in tl], [0.0, 4.0, 6.0])
            self.assertAlmostEqual(tl[-1]["dur"], cfg.duration - 6.0)
            cues = {s["name"]: s["t"] for s in tl}
            self.assertAlmostEqual(build_audio.resolve_at("drop-0.5", cues), 3.5)
            self.assertAlmostEqual(build_audio.resolve_at(" outro + 1.05", cues), 7.05)
            self.assertEqual(build_audio.resolve_at(2.5, cues), 2.5)
            with self.assertRaises(SystemExit):
                build_audio.resolve_at("chorus", cues)


class Speech(unittest.TestCase):
    def test_groups_bridge_short_gaps_and_split_long_ones(self):
        sr = 48000
        t = np.arange(int(4 * sr)) / sr
        tone = 0.3 * np.sin(2 * np.pi * 220 * t)
        gate = ((t > 0.5) & (t < 1.0)) | ((t > 1.06) & (t < 1.5)) | ((t > 2.5) & (t < 3.0))
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "vo.wav"
            write_audio(np.stack([tone * gate] * 2, 1), p)
            g = speech_groups(p)
        self.assertEqual(len(g), 2, g)
        self.assertAlmostEqual(g[0][0], 0.5, delta=0.05)
        self.assertAlmostEqual(g[1][0], 2.5, delta=0.05)


class Project(unittest.TestCase):
    def test_parses_items_sources_speed_and_disabled_flag(self):
        xml = f"""<PremiereData>
<Sequence ObjectUID="s1"><Name>LF</Name><TrackGroups><TrackGroup><Second ObjectRef="2"/></TrackGroup></TrackGroups></Sequence>
<VideoTrackGroup ObjectID="2"><Tracks><Track ObjectURef="t1"/></Tracks></VideoTrackGroup>
<VideoClipTrack ObjectUID="t1"><ClipItems><TrackItems><TrackItem ObjectRef="10"/><TrackItem ObjectRef="11"/></TrackItems></ClipItems></VideoClipTrack>
<VideoClipTrackItem ObjectID="10"><ClipTrackItem><TrackItem><Start>{2*TICKS}</Start><End>{4*TICKS}</End></TrackItem>
  <SubClip ObjectRef="20"/></ClipTrackItem></VideoClipTrackItem>
<VideoClipTrackItem ObjectID="11"><ClipTrackItem><TrackItem><Start>{4*TICKS}</Start><End>{5*TICKS}</End></TrackItem>
  <SubClip ObjectRef="20"/><IsMuted>true</IsMuted></ClipTrackItem></VideoClipTrackItem>
<SubClip ObjectID="20"><Name>A001C002.mov</Name><Clip ObjectRef="30"/></SubClip>
<VideoClip ObjectID="30"><Clip><InPoint>{10*TICKS}</InPoint><OutPoint>{12*TICKS}</OutPoint><PlaybackSpeed>1.25</PlaybackSpeed>
  <Source ObjectRef="40"/></Clip></VideoClip>
<VideoMediaSource ObjectID="40"><MediaSource><Media ObjectURef="m1"/></MediaSource></VideoMediaSource>
<Media ObjectUID="m1"><ActualMediaFilePath>media/A001C002.mov</ActualMediaFilePath></Media>
</PremiereData>"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "edit.prproj"
            p.write_bytes(gzip.compress(xml.encode()))
            seqs = prproj.parse(p)
        items = seqs[0]["video_tracks"][0]
        self.assertEqual(seqs[0]["name"], "LF")
        self.assertEqual([(i["start"], i["end"], i["enabled"]) for i in items], [(2.0, 4.0, True), (4.0, 5.0, False)])
        self.assertEqual(items[0]["source"], "media/A001C002.mov")
        self.assertEqual((items[0]["src_in"], items[0]["speed"]), (10.0, 1.25))


class Example(unittest.TestCase):
    def test_example_config_loads_and_resolves_its_cues(self):
        ex = Path(__file__).resolve().parents[1] / "assets" / "cutdown.example.json"
        cfg = Config(ex)
        self.assertEqual((cfg.width, cfg.height, cfg.frames), (1080, 1920, 360))
        cues = {s["name"]: s["t"] for s in build_audio.music_timeline(cfg)}
        for ver in cfg["versions"].values():
            for line in ver["vo"]:
                build_audio.resolve_at(line["at"], cues)
            ts = [s["t"] for s in ver["shots"]]
            self.assertEqual(ts, sorted(ts))
            self.assertGreater(ver["end_start"], ts[-1])


@unittest.skipUnless(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0, "ffmpeg missing")
class Toolchain(unittest.TestCase):
    def test_scripts_print_usage(self):
        for s in ("prproj.py", "resolve.py", "music_map.py", "vo_takes.py", "build_audio.py", "build_video.py", "qa_sheet.py", "publish_api.py"):
            r = subprocess.run([sys.executable, "-c", f"import ast;ast.parse(open('{SCRIPTS / s}').read())"])
            self.assertEqual(r.returncode, 0, s)


if __name__ == "__main__":
    unittest.main()
