---
name: minimax-h3-video
description: Generate MiniMax H3 videos (text-to-video, first frame, first and last frame, or image/video/audio references) through the async /v1/videos API, then return the saved MP4. Use when the user asks for a MiniMax H3 or Hailuo H3 video, wants to animate a still, morph between two frames, or build a clip from reference images, footage or audio. Prices every job before sending it and never pays twice for the same job.
license: MIT
compatibility: Python 3.8+ (standard library only); network access to the video API; MINIMAX_H3_API_KEY in the environment
---

# MiniMax H3 video

Turn a request into one MiniMax H3 job, run it to completion and hand back the MP4.
All calls go through `scripts/h3_job.py` in this skill's folder (in Claude Code:
`${CLAUDE_SKILL_DIR}/scripts/h3_job.py`). It validates against the model's published limits,
uploads local files, keeps a ledger in `.h3-jobs/` and prints JSON.

## Do not use this skill for

- silent videos, 720p/1080p/4K output, more than 15 seconds, or editing an existing clip: MiniMax H3 cannot do these. Say so and stop.
- image generation, music or speech on their own.

## 1. Pick the mode

| The user has | Mode | Flags |
|---|---|---|
| only an idea | text | prompt only, choose `--ratio` (default 16:9) |
| one still to bring to life | first frame | `--first still.png` (shape follows the still; no `--ratio`) |
| a start and an end picture | first + last frame | `--first a.png --last b.png` |
| a character, product, motion clip or beat to follow | reference | `--image`, `--video`, `--audio` (repeatable) |

Frames and references never mix. Audio needs at least one image or video beside it.

## 2. Limits

| | |
|---|---|
| duration | 4–15 s (`--duration`, default 5) |
| resolution | `768p` (default) or `2k` |
| ratio | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16; `adaptive` only with references |
| references | ≤ 9 images, ≤ 3 videos, ≤ 3 audio, ≤ 12 total; clips 2–15 s each, 15 s per kind |
| files | images JPEG/PNG ≤ 20 MiB, video MP4/MOV ≤ 100 MiB, audio MP3/WAV ≤ 15 MB |
| prompt | required, ≤ 7,000 characters |
| sound | always generated (stereo); cannot be turned off |
| price | $0.039/s at 768p, $0.064/s at 2k; reference video seconds are billed too, images and audio are free |

## 3. Workflow

1. **Draft.** Write the prompt in this order: subject, action, camera move, setting and light, sound or dialogue. In reference mode, point at assets as `@Image 1`, `@Video 1`, `@Audio 1` (numbered per kind, in the order passed). Ask the user only for what is missing and cannot be defaulted.
2. **Check (free).**
   `python3 scripts/h3_job.py check "<prompt>" --duration 6 --resolution 768p --ratio 9:16 [--image hero.png ...] [--ref-video-seconds 5]`
   Exit 2 means the request breaks a limit: fix it using the message, do not send it. Tell the user the `estimated_usd`; if it is above $1, or the user set a budget, get a yes first.
3. **Submit once.**
   `python3 scripts/h3_job.py submit "<prompt>" <same flags>` prints `request_id`. Local files are uploaded automatically. If it says an identical job is still pending, wait for that job instead of resubmitting.
4. **Wait.**
   `python3 scripts/h3_job.py wait <request_id> --timeout 1500`
   Generation usually takes minutes. Exit 3 means still pending: run `wait` again with the same ID. Never submit again because of a timeout.
5. **Fetch.**
   `python3 scripts/h3_job.py fetch <request_id> --out <name>.mp4`
   Report the file path, the duration and the billed seconds × rate.

`python3 scripts/h3_job.py jobs` lists everything submitted from this folder, with status.

## 4. When something fails

| Message contains | What to do |
|---|---|
| `MINIMAX_H3_API_KEY is not set` | ask the user for a key; never print it back |
| `request_unsupported` / exit 2 | a limit was broken; fix the named field |
| `invalid_input` | an asset is unusable (format, size, clip length); replace it |
| `content_policy_violation` | rewrite the named input (for example a real person's likeness) |
| `capacity_unavailable`, `resubmitting is safe` | submit the same request again later |
| `HTTP 402` or `403` | balance or permission problem on the account: tell the user |
| `HTTP 429` / `503` | wait a minute; nothing was charged |

Failed and expired jobs are never billed. Read `references/api.md` for the full status and error tables.

## 5. Prompt notes for H3

- One shot, one main action. Name the camera move ("slow push-in", "handheld follow", "static wide").
- Put spoken lines in quotes with who says them; the model writes the soundtrack itself.
- For a product, say what must stay unchanged ("logo stays readable, color unchanged").
- For first/last frame, describe the change between the two pictures, not the pictures.
- Iterate cheaply: 4–5 s at 768p first, then the keeper at the final length or at 2k.
