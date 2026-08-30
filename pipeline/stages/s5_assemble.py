"""Stage 5: ffmpeg assembly.

Two passes, on purpose:

  Pass 1  one still -> one Ken Burns clip, rendered independently. Slow but
          restartable, and a single bad shot costs one clip, not the episode.
  Pass 2  xfade chain across the clips + audio mix.

The timing that makes this line up:

  Each clip is rendered `shot_duration + crossfade` long. An xfade chain where
  clip k joins at offset = sum(shot_duration[0..k-1]) then makes the transition
  begin exactly on its beat boundary, and the finished video runs
  sum(shot_duration) + crossfade -- narration length plus a held final frame.
  Render clips at the beat length instead and the video finishes
  (n-1) * crossfade short, which at 40 beats is over half a minute of drift.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import ASSETS, Config
from ..media import duration, run as ff
from ..state import Manifest

# Ken Burns moves, cycled so consecutive shots never share one.
MOVES = ["zoom_in_center", "pan_right", "zoom_out_center", "pan_down", "zoom_in_slow"]
TRANSITIONS = ["fade", "fade", "dissolve", "fadeblack"]


def _kenburns(move: str, frames: int, w: int, h: int, upscale: int) -> str:
    """zoompan expression.

    zoompan samples its *input* raster, so without upscaling first the move
    stair-steps visibly. But the cost is quadratic in the upscale factor and
    zoompan is the whole render's bottleneck: 4x on a 1344x768 still means
    every one of ~18,000 frames is resampled from a 16MP source. 2x is the
    knee of that curve -- clean motion, roughly a quarter of the CPU."""
    zi = "min(zoom+0.00045,1.14)"
    zo = "if(lte(zoom,1.0),1.14,max(1.001,zoom-0.00045))"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    if move == "zoom_in_center":
        z, x, y = zi, cx, cy
    elif move == "zoom_out_center":
        z, x, y = zo, cx, cy
    elif move == "pan_right":
        z, x, y = "1.16", f"(iw-iw/zoom)*on/{frames}", cy
    elif move == "pan_down":
        z, x, y = "1.16", cx, f"(ih-ih/zoom)*on/{frames}"
    else:  # zoom_in_slow
        z, x, y = "min(zoom+0.00022,1.08)", cx, cy

    return (
        f"scale={w * upscale}:{h * upscale}:flags=lanczos,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={{fps}},"
        f"setsar=1"
    )


def _build_clips(m: Manifest, cfg: Config, force: bool) -> list[Path]:
    """Pass 1. Shots are independent, so they render in parallel -- this pass
    is ~80% of wall-clock time and scales almost linearly with cores."""
    r = cfg.channel["render"]
    w, h = (int(x) for x in cfg.channel["visual"]["aspect"].split("x"))
    fps, xf = r["fps"], float(r["crossfade_seconds"])
    upscale = int(r.get("kb_upscale", 2))
    preset = r.get("clip_preset", "medium")
    timeline = m.data["timeline"]

    jobs, clips = [], []
    for i, t in enumerate(timeline):
        src = m.path("images", f"beat_{t['id']:03d}.png")
        dst = m.path("clips", f"clip_{t['id']:03d}.mp4")
        clips.append(dst)
        if dst.exists() and not force:
            continue
        if not src.exists():
            raise SystemExit(f"Missing image for beat {t['id']}: {src}")
        jobs.append((i, t, src, dst))

    if not jobs:
        return clips

    # Each ffmpeg already threads internally; oversubscribing thrashes. Cap the
    # pool and hand each job a slice of the cores.
    cores = os.cpu_count() or 4
    workers = max(1, min(len(jobs), max(2, cores // 2)))
    threads = max(1, cores // workers)
    done = [0]

    def render(job) -> None:
        i, t, src, dst = job
        clip_len = t["shot_duration"] + xf
        frames = max(2, int(round(clip_len * fps)))
        move = MOVES[i % len(MOVES)] if r["ken_burns"] else "none"
        vf = (
            _kenburns(move, frames, w, h, upscale).format(fps=fps)
            if move != "none"
            else f"scale={w}:{h},setsar=1,fps={fps}"
        )
        ff([
            "ffmpeg", "-y", "-threads", str(threads),
            "-loop", "1", "-framerate", str(fps), "-i", str(src),
            "-t", f"{clip_len:.3f}", "-vf", vf,
            "-c:v", "libx264", "-preset", preset, "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(fps), "-an", str(dst),
        ])
        done[0] += 1
        print(f"  assemble: clips {done[0]}/{len(jobs)} ...", end="\r", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(render, jobs):
            pass
    return clips


def _video_chain(n: int, starts: list[float], xf: float, cfg: Config) -> tuple[str, str]:
    """xfade chain + grade. Returns (filter_graph, final_label)."""
    parts, prev = [], "0:v"
    for k in range(1, n):
        label = f"vx{k}"
        trans = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        parts.append(
            f"[{prev}][{k}:v]xfade=transition={trans}:"
            f"duration={xf:.3f}:offset={starts[k]:.3f}[{label}]"
        )
        prev = label

    r = cfg.channel["render"]
    grade = ["format=yuv420p"]
    if r.get("vignette"):
        grade.append("vignette=PI/5")
    if r.get("grain"):
        # Temporally varying grain sells the "found footage" texture and hides
        # banding in the dark gradients FLUX likes to produce -- but it is the
        # single biggest driver of output bitrate, because per-frame noise is
        # by definition incompressible. Measured on a 1080p30 gradient at
        # CRF 19: strength 4 -> ~2 Mbps, strength 7 -> ~8.6 Mbps. Stay at 4
        # unless you have a reason; drop allf to `u` alone for static grain,
        # which is a quarter the bitrate again but reads as sensor dirt.
        grade.append(f"noise=alls={int(r.get('grain_strength', 4))}:allf=t+u")
    grade.append("eq=contrast=1.06:saturation=0.88:gamma=0.97")

    parts.append(f"[{prev}]{','.join(grade)}[vout]")
    return ";".join(parts), "vout"


def _audio_chain(m: Manifest, cfg: Config, n_clips: int, total: float) -> tuple[str, list[str], str]:
    """Returns (filter_graph_fragment, extra_input_args, audio_label)."""
    narr = m.path("audio", "narration.mp3")
    extra = ["-i", str(narr)]
    narr_idx = n_clips

    # apad + the outer -t: the video runs one crossfade longer than the
    # narration (the final frame holds), so without padding the mp4 carries a
    # short audio stream and players disagree about the file's real length.
    pad = f"apad,atrim=0:{total:.3f},asetpts=N/SR/TB"

    music = m.data.get("music")
    if not music:
        return f"[{narr_idx}:a]{pad}[aout]", extra, "aout"

    mpath = ASSETS.parent / music["path"]
    if not mpath.exists():
        print(f"  assemble: music file missing ({mpath}), rendering narration only")
        return f"[{narr_idx}:a]{pad}[aout]", extra, "aout"

    mc = cfg.channel["music"]
    extra += ["-stream_loop", "-1", "-i", str(mpath)]
    music_idx = narr_idx + 1

    graph = (
        # amix duration=first keys off the narration, and the bed is trimmed to
        # `total` anyway, so the looped music can never outrun the episode.
        # Narration is the master and the sidechain key, so it gets split.
        f"[{narr_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:"
        f"channel_layouts=stereo,asplit=2[narr][key];"
        f"[{music_idx}:a]aformat=sample_fmts=fltp:sample_rates=44100:"
        f"channel_layouts=stereo,atrim=0:{total:.3f},"
        f"volume={mc['bed_volume']},"
        f"afade=t=in:st=0:d=3,afade=t=out:st={max(0.0, total - 5):.3f}:d=5[bed];"
        # Duck the bed under speech instead of fighting it with static levels.
        f"[bed][key]sidechaincompress=threshold={mc['duck_threshold']}:"
        f"ratio={mc['duck_ratio']}:attack=25:release=900[ducked];"
        f"[narr][ducked]amix=inputs=2:duration=first:normalize=0[mixed];"
        # -16 LUFS integrated is YouTube's normalisation target: master louder
        # and YouTube turns it down anyway, master quieter and you lose headroom.
        f"[mixed]alimiter=limit=0.95,loudnorm=I=-16:TP=-1.5:LRA=11,{pad}[aout]"
    )
    return graph, extra, "aout"


def _write_srt(m: Manifest) -> Path:
    """Beat-level cues are too long to read, so each beat is split into ~2
    cues proportionally by character count. Upload this as a caption track --
    it beats YouTube's auto-captions on proper nouns, which horror scripts
    are full of."""
    def ts(sec: float) -> str:
        h, rem = divmod(max(0.0, sec), 3600)
        mnt, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(mnt):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    beats = {b["id"]: b for b in m.beats}
    lines, idx = [], 1
    for t in m.data["timeline"]:
        text = beats[t["id"]]["narration"].strip()
        words = text.split()
        chunks = [text] if len(words) <= 18 else [
            " ".join(words[: len(words) // 2]),
            " ".join(words[len(words) // 2 :]),
        ]
        chars = sum(len(c) for c in chunks) or 1
        cursor = t["start"]
        for c in chunks:
            span = t["speech"] * (len(c) / chars)
            lines.append(f"{idx}\n{ts(cursor)} --> {ts(cursor + span)}\n{c}\n")
            cursor += span
            idx += 1
    out = m.path("meta", "captions.srt")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def run(m: Manifest, cfg: Config, force: bool = False) -> Manifest:
    if m.done("assemble") and not force:
        print("  assemble: already done, skipping")
        return m
    if "timeline" not in m.data:
        raise SystemExit("No timeline -- run the voice stage first.")

    xf = float(cfg.channel["render"]["crossfade_seconds"])
    clips = _build_clips(m, cfg, force)

    timeline = m.data["timeline"]
    starts = [t["start"] for t in timeline]
    total = sum(t["shot_duration"] for t in timeline) + xf

    vgraph, vlabel = _video_chain(len(clips), starts, xf, cfg)
    agraph, extra_inputs, alabel = _audio_chain(m, cfg, len(clips), total)

    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    inputs += extra_inputs

    out = m.path(f"{m.slug}.mp4")
    print(f"  assemble: mixing {len(clips)} clips -> {total / 60:.2f} min ...")
    ff([
        "ffmpeg", "-y", *inputs,
        "-filter_complex", f"{vgraph};{agraph}",
        "-map", f"[{vlabel}]", "-map", f"[{alabel}]",
        "-c:v", "libx264", "-preset", cfg.channel["render"].get("final_preset", "medium"),
        "-crf", "19",
        # Safety net: grain on a detailed frame can push CRF 19 well past what
        # YouTube will keep. This never binds on a normal episode.
        "-maxrate", "16M", "-bufsize", "32M",
        "-pix_fmt", "yuv420p", "-r", str(cfg.channel["render"]["fps"]),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-movflags", "+faststart", "-t", f"{total:.3f}", str(out),
    ])

    srt = _write_srt(m)
    actual = duration(out)
    m.data["video"] = {
        "path": out.name,
        "seconds": round(actual, 2),
        "captions": srt.name,
    }
    m.mark("assemble", seconds=round(actual, 2), clips=len(clips))
    print(f"  assemble: {out.name} ({actual / 60:.2f} min)")
    return m
