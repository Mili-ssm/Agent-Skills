"""Pure parts of `mem-research`: web input, page check, verdict application. No network beyond 127.0.0.1."""
import functools
import http.server
import os
import socket
import sys
import threading
import time
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
        port = self.server.server_address[1]
        if self.path.startswith("/drip"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(1000):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.1)
            except OSError:
                pass
        elif self.path.startswith("/redir-other"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/page")
            self.end_headers()
        elif self.path.startswith("/redir-file") or self.path.startswith("/redir-ftp"):
            self.send_response(302)
            self.send_header("Location", "file:///etc/passwd" if "file" in self.path else "ftp://example.org/x")
            self.end_headers()
        elif self.path.startswith("/chain/"):
            n = int(self.path.rsplit("/", 1)[1])
            self.send_response(302)
            self.send_header("Location", f"/chain/{n + 1}" if n < 9 else "/page")
            self.end_headers()
        elif self.path.startswith("/redir-private"):
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


@pytest.fixture
def public_name(server, monkeypatch):
    """Any name resolves to a public address (counted in `lookups`) that actually connects to the local server."""
    lookups = []
    real, real_lookup = socket.create_connection, socket.getaddrinfo

    def lookup(host, port, *a, **k):
        if host == "127.0.0.1":
            return real_lookup(host, port, *a, **k)
        lookups.append(host)
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "create_connection", lambda addr, *a, **k: real(("127.0.0.1", addr[1]), *a, **k))
    return f"http://public.example:{server.rsplit(':', 1)[1]}", lookups


def test_relative_redirect_is_followed_and_rechecked(public_name):
    base, lookups = public_name
    assert LONG in rc.fetch_text(f"{base}/redir-page")
    assert lookups == ["public.example", "public.example"]


def test_redirects_are_capped_at_three(public_name):
    base, _ = public_name
    assert LONG in rc.fetch_text(f"{base}/chain/7")  # 3 redirects
    with pytest.raises(rc.FetchRefused, match="redirects"):
        rc.fetch_text(f"{base}/chain/6")  # 4
    with pytest.raises(rc.FetchRefused, match="redirects"):
        rc.fetch_text(f"{base}/redir-loop")


@pytest.mark.parametrize("path", ["/redir-file", "/redir-ftp"])
def test_redirect_to_a_foreign_scheme_is_refused(public_name, path):
    with pytest.raises(rc.FetchRefused, match="only http"):
        rc.fetch_text(public_name[0] + path)


def test_allow_hosts_covers_only_the_first_hop(server, fetch_local):
    assert LONG in fetch_local(f"{server}/page")
    with pytest.raises(rc.FetchRefused, match="non-public"):
        fetch_local(f"{server}/redir-other")
    with pytest.raises(rc.FetchRefused, match="non-public"):
        fetch_local(f"{server}/redir-page")  # a relative redirect to the same host too


def test_host_with_one_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 80)), (2, 1, 6, "", ("10.0.0.1", 80))])
    with pytest.raises(rc.FetchRefused, match="non-public"):
        rc.fetch_text("http://mixed.example/")


def test_a_dripping_server_hits_the_total_deadline(server, fetch_local, monkeypatch):
    monkeypatch.setattr(rc, "TOTAL_DEADLINE", 0.6)
    started = time.monotonic()
    with pytest.raises(rc.FetchFailed):
        fetch_local(f"{server}/drip")
    assert time.monotonic() - started < 2.5


@pytest.mark.parametrize("address", ["::127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2002:7f00:1::",
                                     "2002:c0a8:101::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "::ffff:169.254.169.254"])
def test_ipv6_embedding_a_private_ipv4_is_not_public(address):
    assert not rc._public(address)


def test_ipv6_embedding_a_public_ipv4_stays_public_where_it_is_global():
    assert rc._public("64:ff9b::5db8:d822") and rc._public("2606:4700:4700::1111")


def test_hidden_text_is_not_returned():
    markup = ("<p>shown one</p><div hidden>HID1 <span>HID2</span></div><p>shown two</p>"
              "<div aria-hidden='true'>HID3<p>HID4</div><span style='Color:red; DISPLAY : None'>HID5</span>"
              "<span style=\"visibility:  hidden\">HID6<b>HID7</b></span><p>shown three<br/>and <img src=x>more</p>"
              "<div aria-hidden='false'>shown four</div><script>SCRIPTONLY</script>")
    text = rc.html_text(markup)
    assert "HID" not in text and "SCRIPTONLY" not in text
    for word in ("shown one", "shown two", "shown three", "and", "more", "shown four"):
        assert word in text


def test_an_unclosed_script_or_style_does_not_hide_the_page():
    for tag in ("script", "style"):
        markup = f"<html><head><{tag}>var JSONLY = 1;</head><body><p>{LONG}, said the maker.</p></body></html>"
        text = rc.html_text(markup)
        assert LONG in text and "JSONLY" not in text
    assert "after" in rc.html_text("<html><head><script>x<1</head><BODY>after</body>")
    assert "swallowed" not in rc.html_text("<p>shown</p><script>swallowed to the end")


def test_an_unclosed_script_or_style_in_the_body_keeps_the_next_tag_text():
    for tag in ("script", "style"):
        text = rc.html_text(f"<p>before</p><{tag}>var a=1;<p>QUOTE SENTENCE here</p>")
        assert "before" in text and "QUOTE SENTENCE here" in text


def test_size_cap_and_plain_text(server, fetch_local):
    assert fetch_local(f"{server}/plain").startswith("plain text")
    big = fetch_local(f"{server}/big")
    assert len(big) == rc.MAX_BYTES and "TAILMARK" not in big


def test_pdf_is_not_checked_without_pdftotext(server, fetch_local, monkeypatch):
    monkeypatch.setattr(rc.shutil, "which", lambda name: None)
    with pytest.raises(rc.NotChecked, match="not checked: application/pdf"):
        fetch_local(f"{server}/pdf")


def test_pdf_is_read_through_pdftotext(server, fetch_local, monkeypatch, tmp_path):
    fake = tmp_path / "bin" / "pdftotext"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\ncat >/dev/null\necho 'text of the fake pdf'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ['PATH']}")
    assert fetch_local(f"{server}/pdf").strip() == "text of the fake pdf"
    fake.write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(rc.NotChecked, match="pdf unreadable"):
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


ITEMS = {"q": {"kind": "question", "text": "How many folding cycles does the gadget survive?"},
         "c1": {"kind": "claim", "handle": HANDLE, "text": "The invented gadget survives ten thousand folding cycles"}}


def row(**kw):
    base = {"item": "c1", "url": "http://p/1", "stance": "supports", "source_kind": "official"}
    return {**base, **kw}


def test_item_ids_and_keys():
    items = [ITEMS["q"], ITEMS["c1"], {"kind": "claim", "handle": "b", "text": "t"}]
    assert list(rc.item_ids(items)) == ["q", "c1", "c2"]
    assert [rc.item_key(i) for i in items] == [rc.QUESTION, HANDLE, "b"]


def test_question_problem(tmp_path):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    f.write_text("Zorbco\n", encoding="utf-8")
    assert rc.question_problem("How many cycles?") is None
    assert "secret" in rc.question_problem(f"Does {FAKE_TOKEN} work?")
    assert "forbidden" in rc.question_problem("What does Zorbco ship?")
    assert rc.question_problem("  ") == "the question is empty"


def test_parse_web_reply_tolerates_a_fence_and_nothing_else():
    rows = '[{"item": "q"}]'
    assert rc.parse_web_reply(rows) == [{"item": "q"}]
    assert rc.parse_web_reply(f"Here you go:\n```json\n{rows}\n```\nDone.") == [{"item": "q"}]
    for bad in ("Found some pages", '{"item": "q"}', "", "```\nnot json\n```", "[1, 2"):
        assert rc.parse_web_reply(bad) is None


def test_select_passages_takes_whole_paragraphs_best_first_within_the_limit():
    page = ("Intro words about nothing relevant at all.\n\n"
            "The gadget survives ten thousand folding cycles in the lab.\n\n"
            "The gadget colour is red.\n\n"
            + "gadget folding cycles " * 40)
    got = rc.select_passages(page, "gadget folding cycles survives", limit=1000)
    assert got[0].startswith("gadget folding cycles gadget") or got[0].startswith("The gadget survives")
    assert "Intro words about nothing relevant at all." not in got and sum(map(len, got)) <= 1000
    assert rc.select_passages("Nothing in common with it.", "gadget") == []
    assert rc.select_passages("short\n\nThe gadget survives many cycles of folding here.", "gadget cycles") == [
        "The gadget survives many cycles of folding here."]


def test_check_rows_fetches_once_and_drops_with_reasons():
    calls = []

    def fetch(url):
        calls.append(url)
        if url == "http://p/refused":
            raise rc.FetchRefused("non-public address")
        if url == "http://p/pdf":
            raise rc.NotChecked("not checked: application/pdf")
        if url == "http://p/down":
            raise rc.FetchFailed("HTTP 500")
        if url == "http://p/off":
            return "A page about something else entirely, nothing shared."
        return f"intro\n\n{LONG} in the lab\n\nthe end of it all"

    rows = [row(), row(stance="contradicts"), row(), row(url="http://p/refused"), row(url="http://p/pdf"),
            row(url="http://p/down"), row(url="http://p/off"), row(stance="neutral"), row(source_kind="blog"),
            row(item="zz"), "junk", row(url="http://p/capped")]
    got = rc.check_rows(rows, ITEMS, fetch=fetch, max_urls=5)
    assert [(e["item"], e["stance"]) for e in got.entries] == [(HANDLE, "supports"), (HANDLE, "contradicts")]
    assert got.entries[0]["passages"] == [f"{LONG} in the lab"]
    assert list(got.pages) == ["http://p/1", "http://p/off"]
    reasons = [d["reason"] for d in got.dropped]
    assert reasons[0].startswith("fetch refused") and reasons[1] == "not checked: application/pdf"
    assert reasons[2].startswith("fetch failed") and reasons[3].startswith("no passage")
    assert all(r.startswith("bad shape") for r in reasons[4:6]) and reasons[6] == "unknown item id"
    assert reasons[7].startswith("bad shape") and reasons[8].startswith("over the page limit")
    assert calls.count("http://p/1") == 1 and "http://p/capped" not in calls


def test_check_rows_caps_urls_and_rows_before_fetching():
    calls = []
    rows = [row(url=f"http://p/{i}") for i in range(5)] + [row(url="http://p/0", stance="contradicts")]
    got = rc.check_rows(rows, ITEMS, fetch=lambda u: calls.append(u) or f"{LONG} here", max_urls=2)
    assert calls == ["http://p/0", "http://p/1"]
    assert [d["reason"] for d in got.dropped] == ["over the page limit"] * 3
    assert len(got.entries) == 3  # the second row of an admitted URL still counts
    calls.clear()
    many = [row(url="http://p/same", stance="supports", source_kind=k) for k in ("official", "paper", "other")] * 10
    got = rc.check_rows(many + [row(url="http://p/late")], ITEMS, fetch=lambda u: calls.append(u) or LONG, max_urls=2)
    assert "http://p/late" not in calls and any("row limit" in d["reason"] for d in got.dropped)


def test_check_rows_gives_an_item_at_most_its_passage_budget(monkeypatch):
    monkeypatch.setattr(rc, "ITEM_CHARS", 100)
    page = "\n\n".join(f"The gadget survives cycle number {i} of the test." for i in range(6))
    got = rc.check_rows([row(url="http://p/a"), row(url="http://p/b")], ITEMS, fetch=lambda u: page)
    assert sum(len(p) for e in got.entries for p in e["passages"]) <= 100 and len(got.dropped) == 1


def test_check_rows_end_to_end_on_the_local_page(server, fetch_local):
    got = rc.check_rows([row(url=f"{server}/page"), row(url=f"{server}/redir-private")], ITEMS, fetch=fetch_local)
    assert len(got.entries) == 1 and LONG in got.entries[0]["passages"][0]
    assert "SCRIPTONLY" not in " ".join(got.entries[0]["passages"]) and "non-public" in got.dropped[0]["reason"]
    assert LONG in got.pages[f"{server}/page"]


# ---- step 6: plan ----

PAGE = f"Intro paragraph.\n\n{LONG} in the lab, 28.4 BLEU were reported on the task.\n\nOutro."
ENTRIES = [
    {"item": HANDLE, "url": "http://p/1", "stance": "supports", "source_kind": "other", "passages": ["x"]},
    {"item": HANDLE, "url": "http://p/2", "stance": "contradicts", "source_kind": "paper", "passages": ["x"]},
    {"item": HANDLE, "url": "http://p/3", "stance": "contradicts", "source_kind": "other", "passages": ["x"]},
    {"item": "other-note", "url": "http://p/1", "stance": "supports", "source_kind": "official", "passages": ["x"]},
]
PAGES_FETCHED = {u: PAGE for u in ("http://p/1", "http://p/2", "http://p/3")}
SENT = [HANDLE, "other-note"]
Q = LONG + " in the lab"


def plan(notes=(), findings=()):
    return rc.plan_commands({"answer": "x", "notes": list(notes), "findings": list(findings)}, ENTRIES, PAGES_FETCHED, SENT)


def note_row(**kw):
    return {**{"note": HANDLE, "verdict": "confirmed", "url": "http://p/1", "quote": Q, "fact": "holds"}, **kw}


def test_plan_commands_for_each_verdict():
    got = plan(
        notes=[note_row(),
               note_row(verdict="contradicted", url="http://p/2", fact="differs"),
               note_row(verdict="no source", url="", quote="", fact="")],
        findings=[{"claim": "The gadget survives ten thousand folding cycles in the lab.", "url": "http://p/1", "quote": Q}])
    assert got.refused == []
    assert got.commands == [
        ["note", "confirm", HANDLE, "--fact", "holds", "--source", "http://p/1", "--quote", Q],
        ["note", "dispute", HANDLE, "--fact", "differs", "--source", "http://p/2", "--quote", Q],
        ["remember", "--global", "--kind", "finding", "--origin", "web", "--source", "http://p/1", "--claim",
         "The gadget survives ten thousand folding cycles in the lab."]]


@pytest.mark.parametrize("notes, why", [
    ([note_row(note="unsent")], "not sent"),
    ([note_row(url="http://p/9")], "no supports URL"),
    ([note_row(url=None)], "no supports URL"),
    ([note_row(verdict="contradicted", url="http://p/1")], "no contradicts URL"),
    ([note_row(verdict="confirmed", url="http://p/2")], "no supports URL"),
    ([note_row(note="other-note", url="http://p/2")], "no supports URL"),
    ([note_row(verdict="contradicted", url="http://p/3")], "downgraded to no source"),
    ([note_row(quote="A sentence that the page does not carry")], "not on the fetched page"),
    ([note_row(quote=Q[:19])], "not on the fetched page"),
    ([note_row(quote=None)], "not on the fetched page"),
    ([note_row(fact="--force")], "starts with"),
    ([note_row(fact="")], "fact"),
    ([note_row(verdict="maybe")], "verdict"),
    (["junk"], "bad shape"),
])
def test_plan_refuses_a_row_with_a_reason(notes, why):
    got = plan(notes=notes)
    assert got.commands == [] and len(got.refused) == 1 and why in got.refused[0]["reason"]


@pytest.mark.parametrize("claim, why", [
    ("The gadget reports 30.1 BLEU on the task.", "number"),
    ("The gadget survives ten thousand folding cycles in the lab and also floats on water while glowing brightly purple.", "says more"),
    ("-The gadget survives ten thousand folding cycles in the lab.", "starts with"),
    ("", "claim is empty"),
])
def test_plan_refuses_a_finding_its_quote_does_not_cover(claim, why):
    got = plan(findings=[{"claim": claim, "url": "http://p/1", "quote": Q + ", 28.4 BLEU were reported on the task"}])
    assert got.commands == [] and why in got.refused[0]["reason"]


def test_plan_refuses_a_finding_without_a_supporting_url_or_quote():
    got = plan(findings=[{"claim": "The gadget survives ten thousand folding cycles", "url": "http://p/2", "quote": Q},
                         {"claim": "The gadget survives ten thousand folding cycles", "url": "http://p/1", "quote": "not on it at all, no"},
                         "junk"])
    assert got.commands == [] and [r["reason"][:20] for r in got.refused] == ["the web step gave no", "the quote is not on ", "bad shape"]


def test_plan_counts_a_number_with_its_own_digits():
    ok = rc.finding_problem("It reaches 28.4 BLEU on the task here", "It reaches 28.4 BLEU on the task here, they say")
    assert ok is None
    assert rc.finding_problem("It reaches 28 BLEU on the task here", "It reaches 28.4 BLEU on the task here") is not None


def test_a_finding_may_not_state_the_opposite_of_its_quote():
    assert rc.finding_problem("The gadget survives ten thousand folding cycles",
                              "The gadget does not survive ten thousand folding cycles") is not None
    assert rc.finding_problem("The cache is enabled by default in every release",
                              "The cache is disabled by default in every release") is not None
    assert rc.finding_problem("The cache is enabled by default",
                              "Caching is described below. The cache is enabled by default. It is never shared, and "
                              "no entry is kept without a key.") is None


# ---- step 6: apply to a temporary store ----

@pytest.fixture
def mem_env(hub_root, tmp_path, monkeypatch):
    monkeypatch.setenv("MEM_MEMORIES", str(tmp_path / "gmem"))
    return {"mem_cmd": [sys.executable, str(ENGINE / "mem.py")], "root": hub_root}


def test_apply_writes_the_marks_and_the_finding(hub_root, tmp_path, mem_env):
    verdicts = {"answer": "a",
                "notes": [note_row(fact="the page agrees"),
                          note_row(verdict="contradicted", url="http://p/2", fact="the paper differs"),
                          note_row(note="unsent", fact="x")],
                "findings": [{"claim": "The gadget survives ten thousand folding cycles in the lab.", "url": "http://p/1", "quote": Q}]}
    report = rc.apply(verdicts, ENTRIES, PAGES_FETCHED, [HANDLE], **mem_env)
    assert report["failed"] == [] and len(report["applied"]) == 3
    assert len(report["refused"]) == 1 and "not sent" in report["refused"][0]["reason"]
    meta, body = mem.split_frontmatter((hub_root / "knowledge/computing" / f"{HANDLE}.md").read_text())[:2]
    assert meta["disputed"][0]["source"] == "http://p/2"
    assert "confirmed: the page agrees" in body and Q in body
    (found,) = records.load_memories(tmp_path / "gmem", "global")
    assert found.origin == "web" and found.claim.startswith("The gadget survives")


def test_apply_reports_a_failing_command(mem_env):
    entries = [{"item": "no-such-note", "url": "http://p/1", "stance": "supports", "source_kind": "other", "passages": ["x"]}]
    verdicts = {"notes": [note_row(note="no-such-note")]}
    report = rc.apply(verdicts, entries, PAGES_FETCHED, ["no-such-note"], **mem_env)
    assert report["applied"] == [] and report["failed"][0]["code"] != 0 and "no note" in report["failed"][0]["stderr"]


def test_apply_runs_mem_with_the_pinned_environment(mem_env, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rc.subprocess, "run", lambda args, **kw: seen.append(kw) or type("R", (), {"returncode": 0, "stderr": ""})())
    env = {"MEM_STORE": str(tmp_path), "PATH": "/usr/bin"}
    page = {"http://p/1": "The gadget survives ten thousand folding cycles"}
    rc.apply({"findings": [{"claim": "The gadget survives ten thousand folding cycles", "url": "http://p/1",
                            "quote": "The gadget survives ten thousand folding cycles"}]}, ENTRIES, page, [HANDLE], env=env, **mem_env)
    assert seen[0]["env"] == env


def test_apply_runs_without_a_shell(mem_env, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(rc.subprocess, "run", lambda args, **kw: seen.append((args, kw)) or type("R", (), {"returncode": 0, "stderr": ""})())
    evil = "x; touch " + str(tmp_path / "pwned")
    page = {"http://p/1": f"{evil} appears on this page"}
    rc.apply({"findings": [{"claim": evil, "url": "http://p/1", "quote": f"{evil} appears on this page"}]}, ENTRIES, page, [HANDLE], **mem_env)
    args, kw = seen[0]
    assert kw["shell"] is False and args[-1] == evil and not (tmp_path / "pwned").exists()
