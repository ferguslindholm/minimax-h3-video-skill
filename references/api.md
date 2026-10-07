# MiniMax H3 over the /v1/videos API — reference

Checked 2026-10-07 against https://argolink.io/en/models/minimax-h3 and https://argolink.io/en/docs.
Base URL: `https://argolink.io/v1` (override with `MINIMAX_H3_BASE_URL`). Auth: `Authorization: Bearer <key>`.

## Endpoints

| Step | Method and path | Notes |
|---|---|---|
| upload a local file | `POST /media/uploads` `{"model","type","content_type","size_bytes"}` | free; returns `upload_url` (PUT within 15 min, same Content-Type, no bearer) and `media_url` (readable 7 days) |
| submit | `POST /videos/generations` | returns `{"request_id": "..."}`, the only handle for the job |
| status | `GET /videos/{request_id}` | `pending`, `done`, `failed`, `expired` |
| download | `GET /videos/{request_id}/content` | MP4; 409 `job_video_not_ready` before done, 424 `job_failed` after a failure |

## Request fields

| Field | Rule |
|---|---|
| `model` | `minimax-h3` |
| `prompt` | required in every mode, ≤ 7,000 characters |
| `duration` | integer 4–15, default 5 (alias `seconds`) |
| `resolution` | `768p` (default) or `2k`; `size` such as `1366x768` may replace resolution + ratio |
| `aspect_ratio` | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 (default 16:9); references may use `adaptive`; frame modes `adaptive` only (alias `ratio`) |
| `start_image`, `end_image` | `{"url": "https://..."}`; end needs start; not combinable with references |
| `reference_images` | ≤ 9 `{"url"}` objects, JPEG/PNG ≤ 20 MiB |
| `reference_videos` | ≤ 3, MP4/MOV ≤ 100 MiB, 2–15 s each, 15 s together; their seconds are billed |
| `reference_audios` | ≤ 3, WAV/MP3 ≤ 15 MB, 2–15 s each, 15 s together; needs an image or video beside it |
| `generate_audio` | `true` or omitted; `false` is rejected (sound is always on) |
| `n` | 1 or omitted |
| `seed`, `watermark: true` | rejected with 400 |

fal / OpenRouter names are accepted too: `image_url` (= `start_image`), `image_urls`, `video_urls`, `audio_urls`, `frame_images`, `input_references`.

## Status payloads

- `pending`: `progress` 0–99 and, once there is an estimate, `estimated_seconds_remaining`.
- `done`: `progress` 100, `video.url` (same as the content endpoint, needs the key), `usage` = `output_seconds`, `reference_video_seconds`, `billed_seconds`.
- `failed`: `error.code`, `error.message`, `error.retryable`, and for input problems `error.field`. Not billed.
- `expired`: nothing produced. Not billed.

## Errors on any call

Body: `{"error": {"type", "code", "param", "message"}}`.

| HTTP | Meaning |
|---|---|
| 400 `request_unsupported` / `field_invalid` | the request breaks a model rule or is malformed; nothing charged |
| 401 | missing or wrong key |
| 402 / 403 | balance too low, or the key may not use video models |
| 404 `video_request_not_found` | unknown ID, or a job owned by another user |
| 409 `job_video_not_ready` | download asked for before `done` |
| 424 `job_failed` | download asked for a failed job |
| 429 | rate or concurrency limit; retry after running jobs finish |
| 503 | no capacity or service unavailable; retry after `Retry-After`; nothing charged |

## Billing

billed seconds = output seconds + total reference-video seconds (fraction dropped) → × $0.039 (768p) or $0.064 (2k).
Example: 8 s at 768p with a 5.4 s reference clip → 13 s → $0.507.
