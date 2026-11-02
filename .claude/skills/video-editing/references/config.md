# cutdown.json

One file per project, in the project's working folder. Relative paths resolve against the
file's folder; shot/plate/leak names resolve under `footage_root` (or as given if absolute).

```jsonc
{
  "footage_root": "footage/Collected_Project",   // camera originals, stock, overlays (absolute path to a drive is fine)
  "master": "source.mp4",                                // the long-form export (grade + timing reference)

  "edit": {
    "sequences": "edl/sequences.json",                   // output of prproj.py
    "sequence": "BRAND_Anthem_LF_v06",                   // the long form as exported
    "offset": 0.0,                                       // sequence_time = master_time + offset (resolve.py --align)
    "skip": ["Adjustment", "FilmBurn", "Tagline"]        // name prefixes that are never "the shot"
  },

  "format": {"width": 1080, "height": 1920, "fps": "24000/1001", "frames": 360},

  "music": {
    "file": "audio/track.wav",
    "bpm": 165.97,                                       // from music_map.py
    "segments": [                                        // laid end to end; the last runs to the end
      {"name": "open",  "src": 113.49, "bars": 2},
      {"name": "drop",  "src": 116.38, "bars": 4},       // "bars" needs bpm; or "dur": seconds
      {"name": "fill",  "src": 197.36, "bars": 1},
      {"name": "outro", "src": 198.81}
    ],
    "fade_in": 0.4, "fade_out": 1.6, "crossfade": 0.02
  },

  "audio": {"lufs": -14, "true_peak": -1, "bed_gain_db": -3},   // optional: vo_chain, duck_threshold, duck_ratio

  "plates": {                                            // opening and closing full-frame plates (bookends)
    "open":  {"file": "sky.mp4", "src": 0.0, "x": 0.5},
    "close": {"file": "sky.mp4", "src": 8.0, "x": 0.5}
  },
  "leaks": {"opacity": 0.7, "dur": 0.8,                 // screen-blended transitions
            "open":  {"file": "Leak 01.mp4", "lead": 0.27},   // starts `lead` s before the first shot
            "close": {"file": "Leak 15.mp4", "lead": 0.25}},  // starts `lead` s before end_start
  "endcard": {"file": "endcard.mov", "crop_x": 0.5, "y": 400, "fade_in": 0.3},
  "grade_strength": 0.75,

  "output": {"prefix": "Brand_", "revision": "v01"},    // renders/Brand_<v>_1080x1920_v01.mp4

  "versions": {
    "15-2": {
      "script": "Toward clarity. … Together, we lead on.",
      "vo": [ {"file": "audio/selects/15-2_t18.wav", "at": "drop-0.86"} ],   // seconds or "<segment>±s"; optional in/out
      "end_start": 10.55,                                // close leak + plate + end card from here
      "endcard_src": 1.95,                               // where in the card file to start (time its slam to a word)
      "shots": [
        {"t": 2.89, "mt": 43.70, "x": 0.47, "note": "hangar silhouettes - 'clarity'"},
        {"t": 9.37, "mt": 54.60, "x": 0.50, "note": "campus hall - 'home'"}
      ]
    }
  }
}
```

## Shot fields

| field | meaning |
|---|---|
| `t` | timeline start (s); the shot runs to the next shot's `t` or `end_start` |
| `mt` | master time of the moment wanted; `resolve.py --fill` turns it into `file`, `src_in`, `speed`, `src_wh` |
| `track` | force a long-form video track (1-based) when the visible clip is not the one exported |
| `file`, `src_in`, `speed`, `src_wh` | the source; edit `src_in` by hand to move within the take (`--fill` keeps it) |
| `x`, `y` | crop centre, 0–1 of source width/height |
| `x_end` | pan the crop centre linearly to this value over the shot (follow a walking subject) |
| `zoom` | > 1 crops tighter (removes letterbox bars, punches in) |
| `mode` | `crop` (default) · `square` (centred square gate on black — archival 4:3) · `fit` (whole frame on black) |
| `grade` | `match` (default when `mt` is set) · `none` · path to a 1D `.cube` |
| `grade_strength` | per-shot override of the histogram-match blend |
| `note` | what the shot is *for* — becomes the beat map on the review canvas |
