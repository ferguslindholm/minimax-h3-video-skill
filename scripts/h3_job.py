#!/usr/bin/env python3
"""MiniMax H3 job runner for agents: check -> submit -> wait -> fetch.

Every submitted job is written to a ledger (.h3-jobs/ in the working directory),
and `submit` refuses to send a body identical to one that is still pending, so an
agent that loses track of a job cannot pay for it twice. Standard library only.

    python3 h3_job.py check  "prompt" [--duration 6 --resolution 2k --ratio 9:16 ...]
    python3 h3_job.py submit "prompt" [same options]      -> {"request_id": ...}
    python3 h3_job.py wait   <request_id> [--timeout 1800]
    python3 h3_job.py fetch  <request_id> [--out clip.mp4]
    python3 h3_job.py status <request_id>
    python3 h3_job.py jobs                                 -> the ledger

Environment: MINIMAX_H3_API_KEY (required to send), MINIMAX_H3_BASE_URL (optional).
Exit codes: 0 ok, 1 API error or failed/expired job, 2 invalid request, 3 still pending.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("MINIMAX_H3_BASE_URL", "https://argolink.io/v1").rstrip("/")
LEDGER = os.environ.get("H3_LEDGER_DIR", ".h3-jobs")
RATE = {"768p": 0.039, "2k": 0.064}  # USD per billed second, model page 2026-10-07
FIXED = ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".mp4": "video/mp4",
         ".mov": "video/quicktime", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


class Invalid(Exception):
    """The request breaks a published MiniMax H3 limit; nothing was sent."""


class Failed(Exception):
    """The API refused a call or the job ended without a video."""


# ---------------------------------------------------------------------------- request rules

def compose(a):
    """argparse namespace -> request body. Raises Invalid with a fix-it message."""
    if not a.prompt.strip():
        raise Invalid("prompt is empty")
    if len(a.prompt) > 7000:
        raise Invalid("prompt is over 7,000 characters")
    if not 4 <= a.duration <= 15:
        raise Invalid("duration must be 4-15 s")
    if a.resolution not in RATE:
        raise Invalid(f"resolution {a.resolution} does not exist for MiniMax H3; use 768p or 2k")
    body = {"model": "minimax-h3", "prompt": a.prompt, "duration": a.duration, "resolution": a.resolution}
    refs = {"reference_images": a.image, "reference_videos": a.video, "reference_audios": a.audio}
    n_refs = sum(len(v) for v in refs.values())
    if a.first or a.last:
        if not a.first:
            raise Invalid("--last needs --first")
        if n_refs:
            raise Invalid("frames and references cannot be combined: drop --image/--video/--audio or the frames")
        if a.ratio not in (None, "adaptive"):
            raise Invalid("frame mode takes the first frame's shape: omit --ratio")
        body["aspect_ratio"] = "adaptive"
        body["start_image"] = {"url": a.first}
        if a.last:
            body["end_image"] = {"url": a.last}
        return body
    if len(a.image) > 9 or len(a.video) > 3 or len(a.audio) > 3 or n_refs > 12:
        raise Invalid("too many references: max 9 images, 3 videos, 3 audio, 12 total")
    if a.audio and not (a.image or a.video):
        raise Invalid("audio cannot be the only reference: add an --image or --video")
    ratio = a.ratio or "16:9"
    if ratio not in FIXED and not (ratio == "adaptive" and n_refs):
        raise Invalid(f"ratio {ratio} not accepted here; use {', '.join(FIXED)}")
    body["aspect_ratio"] = ratio
    for key, urls in refs.items():
        if urls:
            body[key] = [{"url": u} for u in urls]
    return body


def estimate(body, ref_video_seconds=0.0):
    billed = body["duration"] + math.floor(ref_video_seconds)
    return {"billed_seconds": billed, "estimated_usd": round(billed * RATE[body["resolution"]], 4)}


# ---------------------------------------------------------------------------- HTTP

def http(method, url, payload=None, raw=False, auth=True, headers=None):
    req = urllib.request.Request(url, method=method, data=None if payload is None else
                                 (payload if isinstance(payload, bytes) else json.dumps(payload).encode()))
    if auth:
        key = os.environ.get("MINIMAX_H3_API_KEY")
        if not key:
            raise Failed("MINIMAX_H3_API_KEY is not set; ask the user for an API key")
        req.add_header("Authorization", "Bearer " + key)
    if payload is not None and not isinstance(payload, bytes):
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", "replace")
        try:
            detail = json.loads(text).get("error", {})
            text = f"{detail.get('code', '')} {detail.get('message', '')}".strip() or text
        except (ValueError, AttributeError):
            pass
        raise Failed(f"HTTP {err.code} on {method} {url.split('?')[0]}: {text[:300]}") from None
    except urllib.error.URLError as err:
        raise Failed(f"network error on {method}: {err.reason}") from None
    return data if raw else json.loads(data or b"{}")


def upload(path):
    """Local file -> media_url via the free upload ticket and a signed PUT."""
    ctype = TYPES.get(os.path.splitext(path)[1].lower())
    if not ctype:
        raise Invalid(f"{path}: MiniMax H3 takes JPEG/PNG, MP4/MOV, MP3/WAV")
    ticket = http("POST", API + "/media/uploads", {"model": "minimax-h3", "type": ctype.split("/")[0],
                                                  "content_type": ctype, "size_bytes": os.path.getsize(path)})
    with open(path, "rb") as fh:
        http("PUT", ticket["upload_url"], fh.read(), raw=True, auth=False, headers={"Content-Type": ctype})
    return ticket["media_url"]


def materialize(a):
    """Upload any local paths in place; https URLs are kept as they are."""
    fix = lambda v: v if v is None or v.startswith("https://") else upload(v)
    a.first, a.last = fix(a.first), fix(a.last)
    a.image, a.video, a.audio = [fix(v) for v in a.image], [fix(v) for v in a.video], [fix(v) for v in a.audio]


def placeholders(a):
    stand_in = lambda v: v if v is None or v.startswith("https://") else "https://upload.invalid/" + os.path.basename(v)
    copy = argparse.Namespace(**vars(a))
    copy.first, copy.last = stand_in(a.first), stand_in(a.last)
    copy.image, copy.video, copy.audio = [stand_in(v) for v in a.image], [stand_in(v) for v in a.video], [stand_in(v) for v in a.audio]
    return copy


# ---------------------------------------------------------------------------- ledger

def fingerprint(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def ledger_entries():
    if not os.path.isdir(LEDGER):
        return []
    out = []
    for name in sorted(os.listdir(LEDGER)):
        if name.endswith(".json"):
            with open(os.path.join(LEDGER, name)) as fh:
                out.append(json.load(fh))
    return out


def record(entry):
    os.makedirs(LEDGER, exist_ok=True)
    with open(os.path.join(LEDGER, entry["request_id"] + ".json"), "w") as fh:
        json.dump(entry, fh, indent=2)


def update(request_id, **fields):
    path = os.path.join(LEDGER, request_id + ".json")
    if os.path.exists(path):
        with open(path) as fh:
            entry = json.load(fh)
        entry.update(fields)
        record(entry)


# ---------------------------------------------------------------------------- commands

def cmd_check(a):
    body = compose(placeholders(a))
    return {"body": body, **estimate(body, a.ref_video_seconds)}


def cmd_submit(a):
    compose(placeholders(a))                      # refuse before uploading anything
    materialize(a)
    body = compose(a)
    fp = fingerprint(body)
    if not a.force:
        for entry in ledger_entries():
            if entry.get("fingerprint") == fp and entry.get("status") in ("submitted", "pending"):
                raise Invalid(f"an identical job {entry['request_id']} is still pending; wait for it "
                              "(or pass --force to pay for a second copy)")
    request_id = http("POST", API + "/videos/generations", body)["request_id"]
    record({"request_id": request_id, "fingerprint": fp, "status": "submitted", "body": body,
            "submitted_at": int(time.time()), **estimate(body, a.ref_video_seconds)})
    return {"request_id": request_id, **estimate(body, a.ref_video_seconds)}


def cmd_status(a):
    job = http("GET", f"{API}/videos/{a.request_id}")
    update(a.request_id, status=job.get("status"))
    return job


def cmd_wait(a):
    give_up = time.monotonic() + a.timeout
    while True:
        job = cmd_status(a)
        state = job.get("status")
        if state == "done":
            return job
        if state in ("failed", "expired"):
            err = job.get("error") or {}
            hint = "resubmitting is safe" if err.get("retryable") else "change the input named in error.field before resubmitting"
            raise Failed(f"job {state}: {err.get('code', '')} {err.get('message', '')} ({hint}); not billed")
        if time.monotonic() >= give_up:
            return {"request_id": a.request_id, "status": state, "progress": job.get("progress"),
                    "note": "still pending; run wait again with the same request_id, do not resubmit"}
        print(f"{state} {job.get('progress', 0)}%", file=sys.stderr)
        time.sleep(a.every)


def cmd_fetch(a):
    out = a.out or f"{a.request_id}.mp4"
    data = http("GET", f"{API}/videos/{a.request_id}/content", raw=True)
    with open(out + ".part", "wb") as fh:
        fh.write(data)
    os.replace(out + ".part", out)
    update(a.request_id, status="done", file=out)
    return {"file": os.path.abspath(out), "bytes": len(data)}


def cmd_jobs(_a):
    return ledger_entries()


def parser():
    p = argparse.ArgumentParser(description="MiniMax H3 job runner")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("check", "submit"):
        s = sub.add_parser(name)
        s.add_argument("prompt")
        s.add_argument("--duration", type=int, default=5)
        s.add_argument("--resolution", default="768p")
        s.add_argument("--ratio")
        s.add_argument("--first")
        s.add_argument("--last")
        s.add_argument("--image", action="append", default=[])
        s.add_argument("--video", action="append", default=[])
        s.add_argument("--audio", action="append", default=[])
        s.add_argument("--ref-video-seconds", type=float, default=0.0)
        if name == "submit":
            s.add_argument("--force", action="store_true")
    for name in ("status", "wait", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("request_id")
        if name == "wait":
            s.add_argument("--timeout", type=float, default=1800)
            s.add_argument("--every", type=float, default=10)
        if name == "fetch":
            s.add_argument("--out")
    sub.add_parser("jobs")
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        result = globals()["cmd_" + a.command](a)
    except Invalid as err:
        print(json.dumps({"error": str(err), "sent": False}))
        return 2
    except Failed as err:
        print(json.dumps({"error": str(err)}))
        return 1
    print(json.dumps(result, indent=2))
    if a.command == "wait" and result.get("status") != "done":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
