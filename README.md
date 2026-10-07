# MiniMax H3 Video Skill for Claude Code and Codex

An agent skill that lets Claude Code, Codex or any agent that reads `SKILL.md` produce MiniMax H3 videos end to end: it picks the mode, checks the request against the model's limits, shows the price, submits once, waits and saves the MP4. Standard-library Python, no SDK.

[What it does](#what-the-skill-does) · [Install](#install) · [API key](#api-key) · [First run](#first-run) · [Modes and limits](#modes-and-limits) · [Prices](#prices) · [Troubleshooting](#troubleshooting)

<sub>Last checked: 2026-10-07 against the MiniMax H3 model page and the agent docs linked below.</sub>

## What the skill does

| File | Role |
|---|---|
| [`SKILL.md`](./SKILL.md) | the playbook the agent follows: choose a mode, draft the prompt, check, confirm cost, submit once, wait, fetch, handle errors |
| [`scripts/h3_job.py`](./scripts/h3_job.py) | `check`, `submit`, `wait`, `fetch`, `status`, `jobs`; uploads local files; JSON output; exit codes 0/1/2/3 |
| [`references/api.md`](./references/api.md) | endpoints, fields, status payloads, error table, billing formula; loaded only when needed |

Two guards matter for paid generation. `check` validates locally and prices the job without touching the network, so an invalid request never becomes a paid one. `submit` records every job in `.h3-jobs/` and refuses an identical body while the first is still pending, so an agent that times out does not buy the same clip twice.

## Install

With the `skills` installer ([vercel-labs/skills](https://github.com/vercel-labs/skills)):

```bash
npx skills add ferguslindholm/minimax-h3-video-skill -a claude-code -a codex
```

By hand, clone into the folder your agent scans (the folder name becomes the skill name):

| Agent | Personal (all projects) | One project |
|---|---|---|
| Claude Code | `~/.claude/skills/minimax-h3-video/` | `.claude/skills/minimax-h3-video/` |
| Codex | `~/.agents/skills/minimax-h3-video/` | `.agents/skills/minimax-h3-video/` |

```bash
git clone https://github.com/ferguslindholm/minimax-h3-video-skill ~/.claude/skills/minimax-h3-video
```

Other agents: point their rules or system prompt at `SKILL.md`; the workflow only needs `python3` and network access. Requirements: Python 3.8+, nothing to `pip install`.

## API key

The script sends requests to `https://argolink.io/v1`, where MiniMax H3 is billed per second. Create a key in the ArgoLink console and export it in the shell you start the agent from:

```bash
export MINIMAX_H3_API_KEY=your-key
export MINIMAX_H3_BASE_URL=https://argolink.io/v1   # optional; any server with the same /v1/videos API works
```

The skill tells the agent never to echo the key, and the script never prints it.

## First run

Ask in plain words: *"Use the MiniMax H3 skill: a 6-second vertical clip of a fox trotting through fresh snow at dawn."* The agent then runs:

```bash
python3 scripts/h3_job.py check "A red fox trots through fresh snow at dawn, low tracking shot, breath steaming" --duration 6 --ratio 9:16
# {"body": {...}, "billed_seconds": 6, "estimated_usd": 0.234}

python3 scripts/h3_job.py submit "A red fox trots through fresh snow at dawn, low tracking shot, breath steaming" --duration 6 --ratio 9:16
# {"request_id": "...", "billed_seconds": 6, "estimated_usd": 0.234}

python3 scripts/h3_job.py wait <request_id>        # prints "pending 40%" lines, then the finished job with usage
python3 scripts/h3_job.py fetch <request_id> --out fox.mp4
```

| Exit code | Meaning | The agent should |
|---|---|---|
| 0 | done | report the file and the cost |
| 1 | API error, or the job `failed` / `expired` (not billed) | read the message; resubmit only if it says resubmitting is safe |
| 2 | the request breaks a limit; nothing was sent | fix the named field |
| 3 | still pending after `--timeout` | run `wait` again with the same ID |

## Modes and limits

| Mode | What the user gives | Flags | Rules |
|---|---|---|---|
| Text | an idea | prompt, `--ratio` | ratio 21:9, 16:9, 4:3, 1:1, 3:4 or 9:16 |
| First frame | one still | `--first` | shape follows the still; no `--ratio`, no references |
| First + last frame | two stills | `--first`, `--last` | the model fills the motion between them |
| Reference | characters, products, motion, music | `--image` ≤ 9, `--video` ≤ 3, `--audio` ≤ 3 | ≤ 12 total; audio needs an image or video; `adaptive` ratio allowed |

All modes: model `minimax-h3`, 4–15 s, `768p` or `2k`, prompt ≤ 7,000 characters, soundtrack always on, one MP4 per job. Clips and tracks run 2–15 s each and 15 s per kind; images are JPEG/PNG ≤ 20 MiB, video MP4/MOV ≤ 100 MiB, audio MP3/WAV ≤ 15 MB.

### API calls behind the script

| Script step | HTTP |
|---|---|
| upload a local file | `POST /v1/media/uploads`, then `PUT` to the signed `upload_url` |
| `submit` | `POST /v1/videos/generations` |
| `status`, `wait` | `GET /v1/videos/{request_id}` (`pending`, `done`, `failed`, `expired`) |
| `fetch` | `GET /v1/videos/{request_id}/content` |

## Prices

| Provider | 768p | 2K | 6 s at 768p |
|---|---:|---:|---:|
| **[ArgoLink](https://argolink.io/gh-minimax-h3-video-skill)** | **$0.039/s** | **$0.064/s** | **$0.234** |
| [MiniMax pay-as-you-go](https://platform.minimax.io/docs/guides/pricing-paygo) (official) | $0.08/s | $0.13/s | $0.48 |
| [fal.ai](https://fal.ai/models/minimax/h3/reference-to-video) | $0.06/s | $0.13/s | $0.36 |

<sub>Read 2026-10-07. On ArgoLink, reference video seconds are added to the billed seconds and reference images and audio are free; MiniMax and fal charge for images beyond the fifth.</sub>

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `resolution 720p does not exist for MiniMax H3` | only `768p` and `2k` exist |
| `audio cannot be the only reference` | add an `--image` or `--video` |
| `frames and references cannot be combined` | pick one mode per job |
| `an identical job ... is still pending` | `wait` on that ID; `--force` only if a second copy is really wanted |
| `HTTP 402` / `403` | account balance or key permission |
| `invalid_input` after submit | an asset broke a size, format or length rule; nothing was charged |
| the agent keeps polling for long | normal for long or 2K clips; `wait --timeout` returns exit 3 without losing the job |

## FAQ

**Does it work without Claude Code?**
Yes. `scripts/h3_job.py` is a plain CLI; Codex, other agents and humans can run the same commands.

**Can it make a silent video or a 1080p video?**
No. MiniMax H3 always adds sound and renders 768p or 2K. The skill tells the agent to say so instead of trying.

**Where are jobs recorded?**
In `.h3-jobs/<request_id>.json` under the working directory: body, fingerprint, estimate, status and the saved file.

**How do I test it without a key?**
`pip install pytest && pytest tests/` runs offline against a fake HTTP layer; `check` also works without a key.

## License

MIT
