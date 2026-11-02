---
name: video-editing
description: >-
  Cut an existing long-form brand film, anthem or commercial down into short versions
  (:06/:15/:30) in any aspect ratio — usually vertical 9:16 for social — using the edit's own
  project file, camera originals, voiceover session and music stems. Resolves every master shot
  to its source clip and in point from the Premiere project, picks slated VO takes, cuts the
  music on its bar grid, reframes and grade-matches each shot to the master, then composites the
  open/close plates, light leaks and the alpha end card. Always starts by asking for the
  materials, checking them, asking the key decisions and writing a plan for approval — nothing
  renders before a go-ahead. Use for "make cut-downs", "make :15s
  from the long form", "vertical versions of the spot", "social cut-downs of this commercial",
  "re-edit the anthem as 9:16". Not for raw talking-head footage with no finished master
  (branded-ad-edit / reel-recut) or an event recap from takes (recap-video).
---

# Video Editing

A finished long-form spot already contains every decision a short version needs: the shots,
their grade, the voice, the music and the end card. The cut-down's job is to **re-use those
decisions exactly** — the same source frames, the same colour, the same performance, music that
still lands on its downbeats — while re-telling the story in 6–30 seconds and a new shape.

This is the brand-film lane of [video-edit-pipeline](../video-edit-pipeline/SKILL.md) and can be
invoked directly. It reuses `reel-style-clone` (style of the master), `video-qa` (frame evidence)
and `video-review-canvas` (delivery). Everything is driven by one `cutdown.json` per project —
[references/config.md](references/config.md) is the schema; `assets/cutdown.example.json` is a
filled-in starting point.

## Start here: gather, ask, plan — then wait for a go

Every invocation opens with this interview, even when the request already names some files.
**Nothing is rendered, published or written outside the project folder until the user has
approved the plan.** Read-only analysis (probing files, parsing the project, transcribing,
mapping the music) is fine before approval — it is what makes the plan concrete.

**1. Ask for the materials** in one message, as a checklist the user can answer with paths
(a single project folder is ideal; say that a path to a mounted drive is fine):

| # | Material | Why it matters |
|---|---|---|
| 1 | Master export of the long form | timing, grade and style reference |
| 2 | Edit project (`.prproj`, or FCP XML) | exact source clip + in point for every shot |
| 3 | Camera originals / collected media | full-resolution reframes |
| 4 | Final VO and the raw VO session | slated takes for the short versions |
| 5 | Music: full mix + stems | bar-aligned music edit |
| 6 | End card (ProRes 4444 with alpha) + logo slate | the close |
| 7 | Transition overlays (light leaks), bookend plates | the house transitions |
| 8 | Scripts for each version, **as text** | images of deck pages may not arrive |

**2. Check what arrived** before asking anything else: probe every file (duration, resolution,
fps, codec, alpha), list folders, parse the project, and reply with a table — *found / missing /
problem* (e.g. "edit project's `client-supplied/` is empty", "logo slate not provided", "archival
clips are 480p"). Ask only for what is missing or broken; offer a fallback for each (crop from the
master, end on the card without the logo slate).

**3. Ask the decisions** with AskUserQuestion — at most four per round, recommended option first:
- **Versions and lengths** (:06 / :15 / :30, how many of each) and **aspect ratios** (9:16, 1:1,
  4:5, 16:9).
- **Which part of the master** is in scope (e.g. skip a hyper-paced intro) and anything off-limits
  (people, shots with rights limits, burned-in graphics).
- **Captions and sound**: brand anthems usually run clean (no captions, minimal SFX) — confirm, and
  check `MASTER_CONTEXT.md` hard rules.
- **Delivery**: review canvases public link / password / invite-only, file naming, deadline.
Script text and anything with no fixed options are asked in plain text, not as buttons.

**4. Analyse, then write the plan.** Run Pipeline steps 1–4 below (style guide, project parse,
VO map, music map), then fill `assets/plan.template.md` into `<project>/plan.md`: per version the
script, the chosen VO takes (with alternates), the music structure on the bar grid, the draft shot
list (beat → shot → why) with a master|source sheet from `resolve.py --at`, reframe risks, open
questions, and exactly what will be rendered and published. Present a short summary with a link to
the plan and **stop**. Revise on feedback; build only on an explicit go-ahead ("approved", "build
it"). If the user asked to skip planning, say once what is being assumed and proceed.

## Pipeline

Steps 1–4 are the analysis that feeds the plan; steps 5–10 run after it is approved.


1. **Style first.** Run `reel-style-clone` on the master's main section (skip any intro the user
   excludes). The guide names the bookends, the chapter transitions, what each shot is *for*,
   and the beat map. Write the guide before choosing shots.
2. **Parse the project.** `scripts/prproj.py edit.prproj sequences.json` lists every sequence's
   video items with source, in point, speed, scale and an `enabled` flag. Projects often already
   hold empty placeholder cut-down sequences (copies of the long form) — check before assuming
   work exists. Set `edit.sequence`, then `scripts/resolve.py cutdown.json --align` for the
   master→sequence offset.
3. **Voiceover.** Sessions usually contain takes slated for the short versions (e.g. "15A alt
   ending, ABC"). `scripts/vo_takes.py map <session> --from S --to E` labels phrase islands;
   choose candidates, then `vo_takes.py extract` re-transcribes each select alone. Use the slated
   reads (they are paced for the length); trim a longer read's line only where a natural pause
   exists, and verify. Agency `*_ab.wav` files are often scratch/audition VO in another voice.
4. **Music map.** `scripts/music_map.py <mix> --stems <stems…> --master <master>` gives section
   levels, tempo/bar length, drum entries/exits on the bar grid, and where the long form's
   music sits in the track. Build each version from bar-aligned segments, e.g. *2 breakdown bars
   → the drop → N peak bars → the last fill bar → the outro*. Name segments (`drop`, `outro`) so
   VO and picture can reference them.
5. **Audio build.** `scripts/build_audio.py cutdown.json` places VO lines (`"at": "drop-0.86"`),
   ducks the bed, masters to the loudness target with an exact length, and writes `cues.json`
   with the **spoken phrase groups**. Cut the picture to those groups (a few frames before each
   onset) — whisper's first-word times include the take's leading room tone.
6. **Shots.** Per version, list shots with the **master time** (`mt`) of the moment you want;
   `resolve.py --at …` builds master|source comparison sheets and `--fill` writes file, in point,
   speed and size. One shot per scripted beat ("toward cures" → the MRI). Hold the bookend plates
   and the payoff longer than the montage. Avoid shots carrying burned-in graphics (score bugs,
   lower thirds) the new crop would keep.
7. **Reframe.** Pull a gridded frame of each source and set `x` (crop centre), `zoom` (removes
   letterbox bars), `x_end` (pan to follow a subject who walks across), `mode: square|fit` for
   archival/4:3 material (a gate on black reads as intentional). 4K/3.2K originals give full
   quality at 9:16; 1080p sports/news rips will be softer — say so.
8. **Render.** `scripts/build_video.py cutdown.json` grade-matches each shot to its master frame
   (per-channel histogram match at 75% strength), renders frame-exact ProRes segments, then
   composites leaks (screen, 70%) and the end card, timed so its slam lands on the line that
   names it (`endcard_src`).
9. **QA in pixels.** `scripts/qa_sheet.py cutdown.json` asserts frames/size/audio length/loudness
   and writes a strip per version: a frame from every shot, the frame after each cut, the end
   card. Look at them — this catches lost subjects, letterbox bars and leak tints that turn a
   whole shot red. Then the `video-qa` engine on the MP4s for the full four layers.
10. **Deliver.** One `video-review-canvas` per version (they are different spots, not revisions
    of one). Publish with the here-now skill's `publish.sh`, or `scripts/publish_api.py` if it is
    not installed; keep slugs stable across rounds. Lead the reply with the URLs.

## Hard-won rules

- **The project file beats eyeballing the master.** It gives the exact clip and in point, and the
  camera originals are 3–4× the resolution a crop of the master can give.
- **Disabled clips sit on top.** Premiere marks them `IsMuted`; the resolver skips them. Still
  compare every resolved frame against the master — blend modes and crops are not modelled.
- **Camera originals lie about colour tags.** Some decode as `csp:gbr prim:reserved`; every
  filter chain starts with `setparams=…bt709`, grading happens in 10-bit RGB, and frames are
  re-tagged before the YUV conversion. JPEG thumbnails of those files fail — use PNG.
- **Splice music on the bar grid, never on a guess.** Measure the tempo from the drum stem, snap
  every in point to a bar line, and crossfade ~20 ms with the source shifted by the same amount.
- **`loudnorm` is not for frame-exact deliverables** — it trims the tail. Measure, apply a static
  gain, limit with a latency-compensated limiter, pad to the exact sample count.
- **Re-transcribe every VO select by itself.** Session transcripts drift by a word; a select can
  start on the wrong word and still look right in the log.
- **Raw VO sessions can carry ultrasonic tones** (monitoring pilot ~20 kHz). Low-pass the VO.
- **Delivered files are never overwritten** — bump `output.revision`.

## Outputs

In the project folder: `cutdown.json`, `cues.json`, `renders/audio/*`, `renders/<prefix><v>_<W>x<H>_<rev>.mp4`,
`renders/segments/<v>/` (ProRes intermediates, `.cube` grades), `evidence/resolve/`, `_qa/`.

## Requirements

Python 3.9+ with numpy · ffmpeg/ffprobe 7+ · whisper-cli with a ggml model (`$WHISPER_MODEL`, or
the HyperFrames cache) · node for the review canvas · here.now credentials for publishing.
No paid API calls.
