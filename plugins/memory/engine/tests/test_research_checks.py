"""Pure parts of `mem-research`: web input, page check, verdict application. No network beyond 127.0.0.1."""
import functools
import http.server
import socket
import sys
import threading
from pathlib import Path

import pytest

import mem
import records
import research_checks as rc

ENGINE = Path(__file__).resolve().parent.parent
HANDLE = "attention-replaces-recurrence"
LONG = "The invented gadget survives ten thousand folding cycles"
FAKE_TOKEN = "ghp_" + "a" * 36  # built from parts: obviously fake


# ---- a local page server ----

PAGES = {
    "/page": ("text/html; charset=utf-8", f"<html><head><style>.x{{}} STYLEONLY</style><script>var s='SCRIPTONLY marker text';</script></head>"
              f"<body><p>{LONG}, said the “maker”.</p><p>Fish &amp; chips\nare\nserved</p></body></html>".encode()),
    "/plain": ("text/plain", b"plain text with the words in a row"),
    "/pdf": ("application/pdf", b"%PDF-1.4 binary"),
    "/big": ("text/plain", b"a" * (3 * 1024 * 1024) + b" TAILMARK"),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/redir-private"):
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/secret")
            self.end_headers()
        elif self.path.startswith("/redir-loop"):
            self.send_response(302)
            self.send_header("Location", "/redir-loop")
            self.end_headers()
        elif self.path.startswith("/redir-page"):
            self.send_response(301)
            self.send_header("Location", "/page")
            self.end_headers()
        elif self.path in PAGES:
            ctype, body = PAGES[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def fetch_local():
    return functools.partial(rc.fetch_text, allow_hosts=["127.0.0.1"])


# ---- step 2 ----

def test_web_input_keeps_question_and_clean_claims_and_drops_the_rest(tmp_path, monkeypatch):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    f.write_text("Zorbco\n", encoding="utf-8")
    notes = [
        {"handle": "a", "claim": "Folding cycles matter."},
        {"handle": "b", "claim": f"Use token {FAKE_TOKEN} for it"},
        {"handle": "c", "claim": "Zorbco ships this"},
        {"handle": "d", "claim": "A local fact", "scope": "project"},
        {"handle": "e", "claim": "   "},
    ]
    got = rc.web_input("What is the cycle limit?", notes)
    assert got.items == [{"kind": "question", "text": "What is the cycle limit?"},
                         {"kind": "claim", "handle": "a", "text": "Folding cycles matter."}]
    reasons = {d["handle"]: d["reason"] for d in got.dropped}
    assert set(reasons) == {"b", "c", "d", "e"}
    assert "secret" in reasons["b"] and "forbidden" in reasons["c"] and "global" in reasons["d"]


def test_web_input_fails_closed_when_the_terms_list_is_unreadable(tmp_path):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\xff\xfe\x00bad")
    got = rc.web_input("q", [{"handle": "a", "claim": "A claim."}])
    assert [i["kind"] for i in got.items] == ["question"] and got.dropped[0]["handle"] == "a"


# ---- step 4: fetch ----

def test_html_reduced_to_visible_text(server, fetch_local):
    text = fetch_local(f"{server}/page")
    assert LONG in text and "Fish & chips" in text
    assert "SCRIPTONLY" not in text and "STYLEONLY" not in text


def test_loopback_refused_without_allow_hosts(server):
    with pytest.raises(rc.FetchRefused):
        rc.fetch_text(f"{server}/page")


@pytest.mark.parametrize("url", ["http://10.1.2.3/", "http://169.254.169.254/x", "http://[::1]/", "http://192.168.0.1/",
                                 "http://[::ffff:127.0.0.1]/", "ftp://example.org/", "file:///etc/passwd",
                                 "http://user:pw@example.org/"])
def test_private_and_foreign_urls_refused(url):
    with pytest.raises(rc.FetchRefused):
        rc.fetch_text(url)


def test_redirect_to_a_private_address_is_refused(server, fetch_local):
    with pytest.raises(rc.FetchRefused, match="non-public"):
        fetch_local(f"{server}/redir-private")


def test_redirect_is_followed_and_capped(server, fetch_local):
    assert LONG in fetch_local(f"{server}/redir-page")
    with pytest.raises(rc.FetchRefused, match="redirects"):
        fetch_local(f"{server}/redir-loop")


def test_size_cap_and_plain_text(server, fetch_local):
    assert fetch_local(f"{server}/plain").startswith("plain text")
    big = fetch_local(f"{server}/big")
    assert len(big) == rc.MAX_BYTES and "TAILMARK" not in big


def test_pdf_is_reported_as_not_checked(server, fetch_local):
    with pytest.raises(rc.NotChecked, match="not checked: application/pdf"):
        fetch_local(f"{server}/pdf")


def test_http_error_is_a_failure(server, fetch_local):
    with pytest.raises(rc.FetchFailed):
        fetch_local(f"{server}/missing")


def test_hostname_resolving_to_loopback_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))])
    with pytest.raises(rc.FetchRefused):
        rc.fetch_text("http://innocent.example/")


# ---- step 4: quotes ----

def test_quote_normalization():
    page = "He said “the  gadget survives” — ten\nthousand cycles in a row."
    assert rc.quote_found('He said "the gadget survives" - ten thousand cycles', page)
    assert rc.quote_found("He said “the gadget survives” – ten thousand cycles", page)
    assert not rc.quote_found("he said \"the gadget survives\" - ten thousand cycles", page)  # case is kept


def test_quote_floor_of_20_characters():
    assert not rc.quote_found("short quote here", "a short quote here is on the page")
    assert not rc.quote_found("x" * 19, "x" * 40)
    assert rc.quote_found("x" * 20, "x" * 40)
    assert not rc.quote_found(" " * 5 + "x" * 19 + "   ", "x" * 40)  # counted after normalizing


def row(**kw):
    base = {"item": HANDLE, "url": "http://p/1", "quote": LONG, "stance": "supports", "source_kind": "official"}
    return {**base, **kw}


def test_check_items_fetches_once_and_drops_with_reasons():
    calls = []

    def fetch(url):
        calls.append(url)
        if url == "http://p/refused":
            raise rc.FetchRefused("non-public address")
        if url == "http://p/pdf":
            raise rc.NotChecked("not checked: application/pdf")
        if url == "http://p/down":
            raise rc.FetchFailed("HTTP 500")
        return f"intro {LONG} outro"

    items = [row(), row(quote="A sentence that the page does not carry"), row(url="http://p/refused"),
             row(url="http://p/pdf"), row(url="http://p/down"), row(stance="neutral"), row(source_kind="blog"),
             row(quote=""), "junk", row(quote=LONG[:19])]
    got = rc.check_items(items, fetch=fetch)
    assert got.surviving == [row()]
    reasons = [d["reason"] for d in got.dropped]
    assert reasons[0].startswith("quote not on the page")
    assert reasons[1].startswith("fetch refused") and reasons[2] == "not checked: application/pdf"
    assert reasons[3].startswith("fetch failed")
    assert all(r.startswith("bad shape") for r in reasons[4:8]) and reasons[8].startswith("quote not")
    assert calls.count("http://p/1") == 1 and len(calls) == 4


def test_check_items_end_to_end_on_the_local_page(server, fetch_local):
    got = rc.check_items([row(url=f"{server}/page", quote="Fish & chips are served"),
                          row(url=f"{server}/page", quote="SCRIPTONLY marker text")], fetch=fetch_local)
    assert len(got.surviving) == 1 and got.dropped[0]["reason"].startswith("quote not on the page")


# ---- step 6: plan ----

Q_OK = row(quote="the gadget survives ten thousand cycles")
SURV = [
    row(),                                                                     # 0 supports, official
    row(stance="contradicts", source_kind="paper"),                            # 1
    row(stance="contradicts", source_kind="other"),                            # 2
    row(item="other-note"),                                                    # 3 about another note
    row(item="", url="http://p/2", stance="supports", source_kind="other"),    # 4 finding source
]
SENT = [HANDLE, "other-note"]


def plan(notes=(), findings=()):
    return rc.plan_commands({"answer": "x", "notes": list(notes), "findings": list(findings)}, SURV, SENT)


def test_plan_commands_for_each_verdict():
    got = plan(
        notes=[{"note": HANDLE, "verdict": "confirmed", "quote": 0, "fact": "holds"},
               {"note": HANDLE, "verdict": "contradicted", "quote": 1, "fact": "differs"},
               {"note": HANDLE, "verdict": "no source", "quote": 0, "fact": "-"}],
        findings=[{"claim": "A new claim.", "quote": 0}])
    assert got.refused == []
    assert got.commands == [
        ["note", "confirm", HANDLE, "--fact", "holds", "--source", "http://p/1", "--quote", LONG],
        ["note", "dispute", HANDLE, "--fact", "differs", "--source", "http://p/1", "--quote", LONG],
        ["remember", "--global", "--kind", "finding", "--origin", "web", "--source", "http://p/1", "--claim", "A new claim."]]


@pytest.mark.parametrize("notes, why", [
    ([{"note": "unsent", "verdict": "confirmed", "quote": 0, "fact": "f"}], "not sent"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": 9, "fact": "f"}], "no surviving quote"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": True, "fact": "f"}], "no surviving quote"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": 3, "fact": "f"}], "another note"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": 1, "fact": "f"}], "stance"),
    ([{"note": HANDLE, "verdict": "contradicted", "quote": 0, "fact": "f"}], "stance"),
    ([{"note": HANDLE, "verdict": "contradicted", "quote": 2, "fact": "f"}], "downgraded to no source"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": 0, "fact": "--force"}], "starts with"),
    ([{"note": HANDLE, "verdict": "confirmed", "quote": 0, "fact": ""}], "fact"),
    ([{"note": HANDLE, "verdict": "maybe", "quote": 0, "fact": "f"}], "verdict"),
    (["junk"], "bad shape"),
])
def test_plan_refuses_a_row_with_a_reason(notes, why):
    got = plan(notes=notes)
    assert got.commands == [] and len(got.refused) == 1 and why in got.refused[0]["reason"]


def test_plan_refuses_dash_values_and_bad_findings():
    dashed = [row(quote="- an item that starts with a dash"), row(url="http://p/x", stance="contradicts")]
    got = rc.plan_commands({"notes": [{"note": HANDLE, "verdict": "confirmed", "quote": 0, "fact": "f"}],
                            "findings": [{"claim": "-rf", "quote": 2}, {"claim": "ok claim", "quote": 1},
                                         {"claim": "ok claim", "quote": 7}]}, dashed + [row(stance="supports")], SENT)
    assert got.commands == []
    assert [r["reason"].split(":")[0] for r in got.refused] == ["a value starts with '-'"] * 2 + \
        ["a finding needs a quote that supports it", "no surviving quote at that index"]


# ---- step 6: apply to a temporary store ----

@pytest.fixture
def mem_env(hub_root, tmp_path, monkeypatch):
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    return {"mem_cmd": [sys.executable, str(ENGINE / "mem.py")], "root": hub_root}


def test_apply_writes_the_marks_and_the_finding(hub_root, tmp_path, mem_env):
    verdicts = {"answer": "a",
                "notes": [{"note": HANDLE, "verdict": "confirmed", "quote": 0, "fact": "the page agrees"},
                          {"note": HANDLE, "verdict": "contradicted", "quote": 1, "fact": "the paper differs"},
                          {"note": "unsent", "verdict": "confirmed", "quote": 0, "fact": "x"}],
                "findings": [{"claim": "A page-backed finding.", "quote": 0}]}
    surviving = [row(url="https://example.org/a"), row(url="https://example.org/b", stance="contradicts", source_kind="paper")]
    report = rc.apply(verdicts, surviving, [HANDLE], **mem_env)
    assert report["failed"] == [] and len(report["applied"]) == 3
    assert len(report["refused"]) == 1 and "not sent" in report["refused"][0]["reason"]
    meta, body = mem.split_frontmatter((hub_root / "knowledge/computing" / f"{HANDLE}.md").read_text())[:2]
    assert meta["disputed"][0]["source"] == "https://example.org/b"
    assert "confirmed: the page agrees" in body and LONG in body
    (found,) = records.load_memories(tmp_path / "gmem", "global")
    assert found.origin == "web" and found.claim == "A page-backed finding."


def test_apply_reports_a_failing_command(mem_env):
    verdicts = {"notes": [{"note": "no-such-note", "verdict": "confirmed", "quote": 0, "fact": "x"}]}
    report = rc.apply(verdicts, [row(item="no-such-note", url="https://example.org/a")], ["no-such-note"], **mem_env)
    assert report["applied"] == [] and report["failed"][0]["code"] != 0 and "no note" in report["failed"][0]["stderr"]


def test_apply_runs_without_a_shell(mem_env, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rc.subprocess, "run", lambda args, **kw: seen.append((args, kw)) or type("R", (), {"returncode": 0, "stderr": ""})())
    evil = "x; touch " + str(tmp_path / "pwned")
    rc.apply({"findings": [{"claim": evil, "quote": 0}]}, [row()], [HANDLE], **mem_env)
    args, kw = seen[0]
    assert kw["shell"] is False and args[-1] == evil and not (tmp_path / "pwned").exists()
