"""Offline tests for scripts/h3_job.py. urlopen is replaced, so nothing leaves the machine."""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import h3_job  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MINIMAX_H3_API_KEY", "secret")
    monkeypatch.setattr(h3_job.time, "sleep", lambda s: None)
    state = {"calls": [], "statuses": []}

    def urlopen(req, timeout=None):
        state["calls"].append(req)
        url = req.full_url
        if url.endswith("/videos/generations"):
            return Resp(json.dumps({"request_id": f"job{len(state['calls'])}"}).encode())
        if url.endswith("/content"):
            return Resp(b"MP4")
        if "/videos/" in url:
            return Resp(json.dumps(state["statuses"].pop(0)).encode())
        if url.endswith("/media/uploads"):
            return Resp(b'{"upload_url": "https://put.test/x", "media_url": "https://cdn.test/x.png"}')
        if url == "https://put.test/x":
            return Resp(b"")
        raise AssertionError(url)

    monkeypatch.setattr(h3_job.urllib.request, "urlopen", urlopen)
    return state


def run(capsys, *argv):
    code = h3_job.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_check_is_free_and_prices_reference_video(capsys, api):
    code, out = run(capsys, "check", "dance like @Video 1", "--video", "moves.mp4", "--duration", "8",
                    "--ref-video-seconds", "5.4")
    assert code == 0 and api["calls"] == []
    assert out["body"]["reference_videos"] == [{"url": "https://upload.invalid/moves.mp4"}]
    assert out["billed_seconds"] == 13 and out["estimated_usd"] == pytest.approx(0.507)


@pytest.mark.parametrize("argv", [
    ["--resolution", "720p"], ["--duration", "20"], ["--audio", "https://a.test/a.mp3"],
    ["--first", "https://a.test/f.png", "--image", "https://a.test/i.png"],
    ["--first", "https://a.test/f.png", "--ratio", "1:1"], ["--last", "https://a.test/l.png"],
])
def test_rule_breaks_exit_2_without_sending(capsys, api, argv):
    code, out = run(capsys, "submit", "x", *argv)
    assert code == 2 and out["sent"] is False and api["calls"] == []


def test_submit_uploads_records_and_blocks_duplicates(capsys, api, tmp_path):
    (tmp_path / "hero.png").write_bytes(b"png")
    code, out = run(capsys, "submit", "@Image 1 bows", "--image", "hero.png")
    assert code == 0
    ticket, put, submit = api["calls"]
    assert json.loads(ticket.data)["content_type"] == "image/png"
    assert put.get_header("Authorization") is None
    assert submit.get_header("Authorization") == "Bearer secret"
    ledger = json.loads((tmp_path / ".h3-jobs" / f"{out['request_id']}.json").read_text())
    assert ledger["status"] == "submitted" and ledger["estimated_usd"] == pytest.approx(0.195)

    code, again = run(capsys, "submit", "@Image 1 bows", "--image", "hero.png")
    assert code == 2 and "still pending" in again["error"]
    code, forced = run(capsys, "submit", "@Image 1 bows", "--image", "hero.png", "--force")
    assert code == 0 and forced["request_id"] != out["request_id"]


def test_wait_then_fetch(capsys, api, tmp_path):
    api["statuses"] += [{"status": "pending", "progress": 50}, {"status": "done", "usage": {"billed_seconds": 5}}]
    code, job = run(capsys, "wait", "abc")
    assert code == 0 and job["usage"]["billed_seconds"] == 5
    code, saved = run(capsys, "fetch", "abc", "--out", "clip.mp4")
    assert code == 0 and (tmp_path / "clip.mp4").read_bytes() == b"MP4"


def test_wait_timeout_says_do_not_resubmit(capsys, api):
    api["statuses"] += [{"status": "pending", "progress": 10}]
    code, out = run(capsys, "wait", "abc", "--timeout", "0")
    assert code == 3 and "do not resubmit" in out["note"]


def test_failed_job_explains_retry(capsys, api):
    api["statuses"] += [{"status": "failed", "error": {"code": "capacity_unavailable", "retryable": True}}]
    code, out = run(capsys, "wait", "abc")
    assert code == 1 and "resubmitting is safe" in out["error"] and "not billed" in out["error"]


def test_missing_key(capsys, api, monkeypatch):
    monkeypatch.delenv("MINIMAX_H3_API_KEY")
    code, out = run(capsys, "status", "abc")
    assert code == 1 and "MINIMAX_H3_API_KEY" in out["error"]
