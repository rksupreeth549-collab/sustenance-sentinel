"""Assemble the narrated demo: segment A + segment B video, with the voiceover
clips placed at the offsets each segment actually recorded.

  python mux_demo.py segA_real.mp4 live_marks.json segB.mp4 mock_marks.json [leadA] [leadB]

Checks every clip fits its slot BEFORE encoding, so a too-long clip is reported
rather than silently overlapping the next section.
"""
from __future__ import annotations

import json
import subprocess
import sys

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
VOICE = "voiceover_v2"

# clip file stem -> section id in that segment's marks file
SEG_A = [("A1_live_01", "live_01"), ("A2_live_02", "live_02"),
         ("A3_live_03", "live_03"), ("A4_live_04", "live_04"),
         ("A5_live_05", "live_05"), ("A6_live_06", "live_06")]
SEG_B = [("B1_01_opening", "01_opening"), ("B2_02_ladder", "02_ladder"),
         ("B3_03_scenario_a", "03_scenario_a"), ("B4_04_scenario_b", "04_scenario_b"),
         ("B5_05_scenario_c", "05_scenario_c"), ("B6_06_scenario_d", "06_scenario_d"),
         ("B7_07_close", "07_close")]


def probe_duration(path: str) -> float:
    out = subprocess.run([FF, "-hide_banner", "-i", path],
                         capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f"no duration for {path}")


def lead_in(video: str, marks: list[dict], override: float | None = None) -> float:
    """Recording starts before the command runs; the manifest starts at 0.

    Inferring the lead-in as (video - run) assumes nothing was recorded AFTER
    the run finished. Any trailing padding would otherwise push every cue late,
    so pass an explicit value when you know it.
    """
    if override is not None:
        return override
    return probe_duration(video) - marks[-1]["at"]


def plan(video: str, marks_path: str, clips, base: float, lead_override=None):
    marks = json.load(open(marks_path, encoding="utf-8"))
    at = {m["section"]: m["at"] for m in marks}
    order = [m["section"] for m in marks]
    lead = lead_in(video, marks, lead_override)
    if lead < 0:
        print(f"  ! {video} is SHORTER than its manifest — wrong pair of files?")
        lead = 0.0
    print(f"  {video}: {probe_duration(video):.2f}s video, "
          f"{marks[-1]['at']:.2f}s of run, {lead:.2f}s lead-in")

    rows, ok = [], True
    for stem, section in clips:
        if section not in at:
            print(f"  ! {section} missing from {marks_path}")
            ok = False
            continue
        nxt = order[order.index(section) + 1]
        budget = at[nxt] - at[section]
        clip = f"{VOICE}/{stem}.mp3"
        dur = probe_duration(clip)
        fits = dur <= budget
        ok &= fits
        print(f"    {stem:<20} {dur:6.2f}s / {budget:6.2f}s "
              f"{'ok' if fits else 'TOO LONG'}")
        rows.append((clip, base + lead + at[section]))
    return rows, ok


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    segA, marksA, segB, marksB = sys.argv[1:5]
    # optional: explicit lead-in seconds for each segment, if auto-inference is off
    leadA = float(sys.argv[5]) if len(sys.argv) > 5 else None
    leadB = float(sys.argv[6]) if len(sys.argv) > 6 else None

    print("Planning segment A")
    rowsA, okA = plan(segA, marksA, SEG_A, base=0.0, lead_override=leadA)
    lenA = probe_duration(segA)
    print("Planning segment B")
    rowsB, okB = plan(segB, marksB, SEG_B, base=lenA, lead_override=leadB)

    if not (okA and okB):
        print("\nABORT: at least one clip does not fit its slot. "
              "Shorten it or re-record with a larger --dwell.")
        return 1

    rows = rowsA + rowsB
    print(f"\nConcatenating video ({lenA:.2f}s + {probe_duration(segB):.2f}s)")
    with open("concat.txt", "w", encoding="utf-8") as fh:
        for p in (segA, segB):
            fh.write(f"file '{p}'\n")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", "concat.txt", "-c", "copy",
                    "demo_v3_concat.mp4"], check=True)
    # Hold the last frame for a couple of seconds: the closing narration runs
    # marginally past the end of the recording and would otherwise be clipped.
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", "demo_v3_concat.mp4",
                    "-vf", "tpad=stop_mode=clone:stop_duration=1.0",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-an",
                    "demo_v3_silent.mp4"], check=True)

    print("Building the audio track and muxing")
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-y", "-i", "demo_v3_silent.mp4"]
    for clip, _ in rows:
        cmd += ["-i", clip]
    # delay each clip to its offset, then mix them into one stereo track
    filters = "".join(
        f"[{i + 1}:a]adelay={int(off * 1000)}|{int(off * 1000)}[a{i}];"
        for i, (_, off) in enumerate(rows))
    filters += "".join(f"[a{i}]" for i in range(len(rows)))
    filters += (f"amix=inputs={len(rows)}:dropout_transition=0:normalize=0,"
                "aresample=48000,aformat=channel_layouts=stereo[mix]")
    cmd += ["-filter_complex", filters, "-map", "0:v", "-map", "[mix]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "demo_v3_narrated.mp4"]
    subprocess.run(cmd, check=True)

    print(f"\nDone: demo_v3_narrated.mp4  ({probe_duration('demo_v3_narrated.mp4'):.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
