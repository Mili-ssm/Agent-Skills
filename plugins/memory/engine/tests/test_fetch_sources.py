from collections import UserList
from types import SimpleNamespace

import mem
import pytest
from commands import read, sources
from research import checks as research_checks
from test_find_new import write_note

A = "literature/computing/2017-vaswani-attention.md"
B = "literature/computing/2020-lee-b.md"
PAIR = 2
SEEN_REQUESTS = 11
TEXT_ONLY_TIMEOUT = 60
DOWNLOAD_TIMEOUT = 30
PAGE = b"<html><body><p>" + b"word " * 250 + b"</p></body></html>"


@pytest.fixture
def calls(monkeypatch):
    """Replace the network: every URL returns the response set in `responses` and is recorded."""

    class Calls(UserList):
        responses: dict

    log = Calls()
    responses = {}

    def download(url):
        log.append(url)
        result = responses.get(url, (PAGE, "text/html; charset=utf-8"))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(sources, "_download", download)
    monkeypatch.setattr(sources, "time", SimpleNamespace(sleep=lambda _: None))
    monkeypatch.setattr(sources.shutil, "which", lambda _: None)
    log.responses = responses
    return log


def add_b(root, url="https://b.example/doc"):
    write_note(
        root,
        B,
        f"---\ntitle: B\nauthors: [Lee]\nyear: 2020\nkind: web\nurl: {url}\n"
        "topics: [llm]\nadded: 2026-11-07\n---\n",
    )


def run(root, capsys, *args):
    code = mem.main(["--root", str(root), "fetch-sources", *args])
    return code, capsys.readouterr().out.splitlines()


def url_of(root, rel):
    return mem.discover_notes(root)[[n.rel for n in mem.discover_notes(root)].index(rel)].meta[
        "url"
    ]


def test_extension_follows_content_type_then_url_suffix(hub_root, calls, capsys):
    add_b(hub_root, "https://b.example/paper.pdf")
    calls.responses[url_of(hub_root, A)] = (b"%PDF", "application/pdf")
    calls.responses["https://b.example/paper.pdf"] = (b"x", "application/octet-stream")
    code, out = run(hub_root, capsys)
    assert code == 0
    assert out == [f"fetched {A}", f"fetched {B}", "fetched 2, skipped 0, failed 0"]
    assert (hub_root / ".sources/2017-vaswani-attention/source.pdf").read_bytes() == b"%PDF"
    assert (hub_root / ".sources/2020-lee-b/source.pdf").read_bytes() == b"x"


def test_default_extension_is_html_and_text_plain_is_txt(hub_root, calls, capsys):
    add_b(hub_root)
    calls.responses["https://b.example/doc"] = (b"t", "text/plain")
    run(hub_root, capsys)
    assert (hub_root / ".sources/2020-lee-b/source.txt").exists()
    assert (hub_root / ".sources/2017-vaswani-attention/source.html").exists()


def test_cached_notes_are_skipped_unless_forced(hub_root, calls, capsys):
    run(hub_root, capsys)
    assert len(calls) == 1
    _code, out = run(hub_root, capsys)
    assert out == [f"skipped {A} (already cached)", "fetched 0, skipped 1, failed 0"]
    assert len(calls) == 1
    _code, out = run(hub_root, capsys, "--force")
    assert out[0] == f"fetched {A}" and len(calls) == PAIR


def test_failure_is_reported_and_exits_1(hub_root, calls, capsys):
    add_b(hub_root)
    calls.responses["https://b.example/doc"] = OSError("HTTP Error 404")
    code, out = run(hub_root, capsys)
    assert code == 1
    assert out == [f"fetched {A}", f"failed {B}: HTTP Error 404", "fetched 1, skipped 0, failed 1"]
    assert not (hub_root / ".sources/2020-lee-b").exists()


def test_non_http_url_is_refused_without_a_request(hub_root, calls, capsys):
    add_b(hub_root, "ftp://b.example/doc")
    code, out = run(hub_root, capsys, B)
    assert code == 1
    assert out[0] == f"failed {B}: url must start with http:// or https://"
    assert calls == []


def test_only_given_paths_are_fetched(hub_root, calls, capsys):
    add_b(hub_root)
    code, out = run(hub_root, capsys, B)
    assert out == [f"fetched {B}", "fetched 1, skipped 0, failed 0"]
    assert calls == ["https://b.example/doc"]
    code, out = run(hub_root, capsys, "knowledge/computing/attention-replaces-recurrence.md")
    assert code == 1 and out[0].endswith("not a literature note")


def test_pdftotext_runs_next_to_a_pdf_when_available(hub_root, calls, capsys, monkeypatch):
    calls.responses[url_of(hub_root, A)] = (b"%PDF", "application/pdf")
    monkeypatch.setattr(sources.shutil, "which", lambda _: "/usr/bin/pdftotext")
    ran = []
    monkeypatch.setattr(sources.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw)))
    run(hub_root, capsys)
    cmd, kw = ran[0]
    assert cmd[0] == "pdftotext" and cmd[-1].endswith("source.txt") and kw["check"] is False


def test_force_replaces_copies_of_another_type(hub_root, calls, capsys):
    folder = hub_root / ".sources" / "2017-vaswani-attention"
    folder.mkdir(parents=True)
    (folder / "source.html").write_text("old")
    (folder / "source.txt").write_text("stale")
    calls.responses["https://arxiv.org/abs/1706.03762"] = (b"%PDF", "application/pdf")
    mem.main(["--root", str(hub_root), "fetch-sources", A, "--force"])
    assert sorted(p.name for p in folder.iterdir()) == ["source.pdf"]


class FakeConnection:
    """Stands in for `research_checks._connection`: answers each request from `replies` (status, headers, body)."""

    def __init__(self, replies, seen):
        self.replies, self.seen, self.sock = replies, seen, None

    def request(self, method, path, headers=None):
        self.seen.append((path, headers))

    def getresponse(self):
        status, headers, body = self.replies.pop(0)
        return FakeResponse(status, headers, body)

    def close(self):
        pass


class FakeResponse:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def getheader(self, name):
        return self.headers.get(name)

    def read1(self, n):
        chunk, self.body = self.body[:n], self.body[n:]
        return chunk


@pytest.fixture
def wire(monkeypatch):
    """Every name resolves to a public address; connections come from `replies`. Returns (replies, requests seen)."""
    replies, seen = [], []
    monkeypatch.setattr(
        research_checks.socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [
            (2, 1, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34", port))
        ],
    )
    monkeypatch.setattr(
        research_checks, "_connection", lambda *a, **k: FakeConnection(replies, seen)
    )
    return replies, seen


def test_download_refuses_a_private_address(monkeypatch):
    monkeypatch.setattr(
        research_checks.socket,
        "getaddrinfo",
        lambda host, port, *a, **k: [(2, 1, 6, "", ("169.254.169.254", port))],
    )
    with pytest.raises(ValueError, match="non-public"):
        sources._download("http://metadata.example/latest")


def test_download_refuses_a_redirect_to_localhost(wire):
    replies, _ = wire
    replies.append((302, {"Location": "http://127.0.0.1/admin"}, b""))
    with pytest.raises(ValueError, match="non-public"):
        sources._download("https://x.org/a")


def test_download_keeps_its_user_agent_and_ten_redirects(wire):
    replies, seen = wire
    replies.extend(
        [(302, {"Location": "/n"}, b"")] * 10 + [(200, {"Content-Type": "Text/HTML"}, b"ok")]
    )
    assert sources._download("https://x.org/a") == (b"ok", "text/html")
    assert len(seen) == SEEN_REQUESTS and all(
        h["User-Agent"] == sources._USER_AGENT for _, h in seen
    )
    replies.extend([(302, {"Location": "/n"}, b"")] * 11)
    with pytest.raises(ValueError, match="too many redirects"):
        sources._download("https://x.org/a")


def test_download_refuses_oversized_and_non_http_redirects(wire, monkeypatch):
    replies, _ = wire
    monkeypatch.setattr(sources, "FETCH_MAX_BYTES", 100)
    replies.append((200, {"Content-Type": "text/html"}, b"x" * 101))
    with pytest.raises(ValueError, match="larger than"):
        sources._download("https://x.org/a")
    replies.append((302, {"Location": "ftp://x.org/a"}, b""))
    with pytest.raises(ValueError, match="only http"):
        sources._download("https://x.org/a")


def test_html_to_text_drops_chrome_decodes_and_collapses():
    page = (
        "<html><head><meta http-equiv='Content-Type' content='text/html; charset=latin-1'>"
        "<style>p{}</style><script>var x;</script></head><body><nav>menu <b>x</b></nav>"
        "<h1>Title</h1><p>caf\xe9  &amp;\n  tea</p><br><br><br><div>last<footer>foot</footer></div></body></html>"
    )
    assert sources.html_to_text(page.encode("latin-1")) == "Title\n\ncaf\u00e9 & tea\n\nlast\n"


def test_html_to_text_falls_back_to_latin1_on_bad_utf8():
    assert sources.html_to_text(b"<p>caf\xe9</p>") == "caf\u00e9\n"


def test_fetch_writes_source_txt_for_html_and_flags_short_pages(hub_root, calls, capsys):
    add_b(hub_root)
    calls.responses["https://b.example/doc"] = (b"<p>tiny</p>", "text/html")
    _code, out = run(hub_root, capsys)
    assert out[0] == f"fetched {A}"
    assert out[1] == f"fetched {B} (no text: page has under 200 words of text)"
    assert (hub_root / ".sources/2017-vaswani-attention/source.txt").read_text().split() == [
        "word"
    ] * 250
    assert not (hub_root / ".sources/2020-lee-b/source.txt").exists()


def make_folder(root, stem, **files):
    folder = root / ".sources" / stem
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name.replace("_", ".")).write_bytes(data)
    return folder


def test_text_only_builds_missing_texts_and_never_touches_existing(hub_root, calls, capsys):
    add_b(hub_root)
    make_folder(hub_root, "2017-vaswani-attention", source_html=PAGE)
    kept = make_folder(hub_root, "2020-lee-b", source_html=PAGE, notes_txt=b"by hand")
    code, out = run(hub_root, capsys, "--text-only")
    assert code == 0 and calls == []
    assert out == [f"text {A} (250 words)", "text written 1, without text 0, already had text 1"]
    assert [p.name for p in kept.iterdir() if p.suffix == ".txt"] == ["notes.txt"]
    assert (kept / "notes.txt").read_bytes() == b"by hand"


def test_text_only_reports_pages_without_text_and_pdf_without_tool(hub_root, calls, capsys):
    add_b(hub_root)
    make_folder(hub_root, "2017-vaswani-attention", source_html=b"<p>tiny</p>")
    make_folder(hub_root, "2020-lee-b", source_pdf=b"%PDF")
    code, out = run(hub_root, capsys, "--text-only")
    assert code == 0
    assert out == [
        f"no text {A}: page has under 200 words of text",
        f"no text {B}: pdftotext is not installed",
        "text written 0, without text 2, already had text 0",
    ]


def test_text_only_runs_pdftotext_with_an_argument_list(hub_root, calls, capsys, monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd, kw))
        (hub_root / ".sources/2017-vaswani-attention/source.txt").write_text("a b c")

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(sources.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(sources.subprocess, "run", fake_run)
    make_folder(hub_root, "2017-vaswani-attention", source_pdf=b"%PDF")
    _code, out = run(hub_root, capsys, A, "--text-only")
    assert out[0] == f"text {A} (3 words)"
    cmd, kw = seen[0]
    assert (
        cmd[0] == "pdftotext"
        and cmd[1].endswith("source.pdf")
        and kw["timeout"] == TEXT_ONLY_TIMEOUT
        and "shell" not in kw
    )


def test_text_only_rejects_a_path_that_is_not_a_literature_note(hub_root, calls, capsys):
    code, out = run(
        hub_root, capsys, "knowledge/computing/attention-replaces-recurrence.md", "--text-only"
    )
    assert code == 1
    assert (
        out[0]
        == "failed knowledge/computing/attention-replaces-recurrence.md: not a literature note"
    )


def test_source_text_falls_back_to_the_largest_markdown_only_without_txt(hub_root):
    folder = make_folder(hub_root, "2017-vaswani-attention", a_md=b"small", b_md=b"bigger one")
    assert read.source_text(hub_root, A) == folder / "b.md"
    (folder / "x.txt").write_text("t")
    assert read.source_text(hub_root, A) == folder / "x.txt"


def test_never_writes_source_txt_beside_another_txt(hub_root, calls, capsys):
    add_b(hub_root)
    folder = make_folder(hub_root, "2017-vaswani-attention", source_html=PAGE, Notes_TXT=b"by hand")
    run(hub_root, capsys, A, "--text-only")
    assert not (folder / "source.txt").exists()
    calls.responses[url_of(hub_root, A)] = (b"plain", "text/plain")
    code, out = run(hub_root, capsys, A, "--force")
    assert code == 1 and out[0] == f"failed {A}: the folder already holds a .txt"
    assert not (folder / "source.txt").exists()
    calls.responses[url_of(hub_root, A)] = (PAGE, "text/html")
    run(hub_root, capsys, A, "--force")
    assert (
        not (folder / "source.txt").exists() and (folder / "Notes.TXT").read_bytes() == b"by hand"
    )


def test_symlinked_source_folder_is_skipped_or_refused(hub_root, calls, capsys, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "source.html").write_bytes(PAGE)
    (hub_root / ".sources").mkdir()
    (hub_root / ".sources/2017-vaswani-attention").symlink_to(target)
    code, out = run(hub_root, capsys, "--text-only")
    assert out[0] == f"no text {A}: .sources/2017-vaswani-attention is a symlink"
    code, out = run(hub_root, capsys, A, "--force")
    assert code == 1 and out[0] == f"failed {A}: .sources/2017-vaswani-attention is a symlink"
    assert calls == [] and sorted(p.name for p in target.iterdir()) == ["source.html"]


def test_symlinked_copy_does_not_count_as_cached(hub_root, calls, capsys, tmp_path):
    (tmp_path / "x.html").write_bytes(PAGE)
    folder = make_folder(hub_root, "2017-vaswani-attention")
    (folder / "source.html").symlink_to(tmp_path / "x.html")
    _code, out = run(hub_root, capsys, A)
    assert out[0] == f"fetched {A}" and calls


def test_html_to_text_keeps_forms_and_headers_in_articles_and_drops_form_controls():
    page = (
        b"<title>Tab</title><header>top</header><form><p>whole page</p><select><option>opt</option></select>"
        b"<button>go</button></form><article><header>kept head</header><p>body</p></article>"
    )
    assert sources.html_to_text(page) == "whole page\n\nkept head\nbody\n"


def test_text_only_falls_back_to_the_pdf_and_captures_pdftotext_stderr(
    hub_root, calls, capsys, monkeypatch
):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(kw)
        (hub_root / ".sources/2017-vaswani-attention/source.txt").write_text("a b c")

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(sources.shutil, "which", lambda _: "/usr/bin/pdftotext")
    monkeypatch.setattr(sources.subprocess, "run", fake_run)
    make_folder(hub_root, "2017-vaswani-attention", source_html=b"<p>tiny</p>", source_pdf=b"%PDF")
    _code, out = run(hub_root, capsys, "--text-only")
    assert out[0] == f"text {A} (3 words)" and seen[0]["capture_output"] is True


def test_text_only_reports_a_write_error(hub_root, calls, capsys, monkeypatch):
    def boom(folder):
        raise OSError("disk full")

    monkeypatch.setattr(sources, "_write_text_copy", boom)
    make_folder(hub_root, "2017-vaswani-attention", source_html=PAGE)
    code, out = run(hub_root, capsys, "--text-only")
    assert code == 0 and out[0] == f"no text {A}: disk full"


def test_download_keeps_its_socket_timeout_and_accepts_any_type(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        research_checks,
        "fetch_raw",
        lambda url, limit_for, **kw: seen.update(kw) or (b"x", "text/plain"),
    )
    assert sources._download("https://x.org/a") == (b"x", "text/plain")
    assert seen["timeout"] == DOWNLOAD_TIMEOUT and seen["headers"]["Accept"] == "*/*"
