# Demo archive

Nothing in here should be sent to Swiggy. Kept for reference only.

## rejected_fabricated/
`demo_v2_narrated.mp4` and its inputs. Segment A of this cut does NOT talk to
Swiggy: it was produced by a hardcoded print/sleep script that replayed canned
text on a timer, with no network calls, while the screen and voiceover both
claim it is running live. Rejected during QA. `segA_final.mp4` is that fake
recording; `demo_v2_silent.mp4` is the same cut without audio.

## failed_takes/
Attempts at recording the real live segment that failed at capture:
`segA.mp4` recorded the wrong window entirely (a notes app, not the terminal),
and the rest are aborted retries (`segA_bg_test2.mp4` is 48 bytes).

## superseded/
The first demo (July), mock backend only, before the live Swiggy integration
existed. Accurate for its time, just out of date.

## What is current
Segment B (`../segB.mp4`, the offline safety scenarios) is a genuine recording
and is reused. Segment A needs a real screen recording of:

    python verify_live.py --dwell 15 --timings live_marks.json

then assemble with `../mux_demo.py`.
