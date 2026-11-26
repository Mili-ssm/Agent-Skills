"""Pure parts of the `mem-research` pipeline (stage 1b): the web step's input, the page check (fetch, passages) and
the application of the verdicts. No model session and no third-party dependency here.

Text that comes from the web is data: no quote or claim is ever executed, used as a command name or as an option.
"""

from __future__ import annotations

import html.parser
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import threading
import time
import unicodedata
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, TypedDict, TypeGuard, Unpack

import records
import safe_io

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

STANCES = ("supports", "contradicts")
SOURCE_KINDS = ("official", "paper", "other")
VERDICTS = ("confirmed", "contradicted", "no source")
MIN_QUOTE = 20
MIN_PARAGRAPH = 20  # a shorter paragraph is no passage
HTTP_OK = 200
MAX_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024
PAGE_CHARS = 3000  # passages handed to the verdict step, per page
ITEM_CHARS = 12000  # and per item, over all its pages
MIN_FINDING_WORDS = 0.7  # share of a finding's content words that its quote must hold
QUESTION = "(question)"  # the item key of the question; a note's key is its handle
MAX_REDIRECTS = 3
TIMEOUT = 10  # per socket operation
TOTAL_DEADLINE = 20  # per `fetch_text` call, all hops together
ROWS_PER_URL = 4  # `check_rows` considers at most this many rows per allowed URL
MEM_ENTRY = [str(Path(__file__).resolve().parent.parent / "bin" / "mem")]


# ---- step 2: web input ----


class WebInput(NamedTuple):
    # {"kind": "question", "text"} then {"kind": "claim", "handle", "text"}
    items: list[dict[str, str]]
    dropped: list[dict[str, str]]  # {"handle", "reason"}


def _shaped(note: Mapping[str, Any]) -> tuple[str, str] | None:
    """(handle, claim) of a note that has both as text, else None."""
    handle = note.get("handle") if isinstance(note, Mapping) else None
    claim = note.get("claim") if isinstance(note, Mapping) else None
    if isinstance(handle, str) and handle and isinstance(claim, str) and claim.strip():
        return handle, claim
    return None


def _label(note: Mapping[str, Any]) -> str:
    handle = note.get("handle") if isinstance(note, Mapping) else None
    return handle if isinstance(handle, str) else "?"


def _web_problem(note: Mapping[str, Any], claim: str, env: Mapping[str, str]) -> str | None:
    """Why a well-shaped note may not go to the web (`claim` is its normalized claim), else None."""
    if note.get("scope", "global") != "global":
        return "not a global record"
    secret = records.secret_in([claim])
    if secret is not None:
        return f"looks like a secret ({secret})"
    try:
        hits = records.term_hits([claim], env, "note")
    except records.ForbiddenListError as exc:
        return f"forbidden-terms list unreadable ({exc})"
    return "contains a forbidden term" if hits else None


def web_input(
    question: str, notes: Sequence[Mapping[str, Any]], env: Mapping[str, str] | None = None
) -> WebInput:
    """What may go to the web: the question as given, and each note claim that passes the secret and the
    forbidden-terms checks of `mem remember`. A note is `{"handle", "claim"}` and, when given, `"scope": "global"`:
    a project-scope record is never accepted. A soft term counts as a hit too, since nobody can approve it here."""
    env = os.environ if env is None else env
    items = [{"kind": "question", "text": question}]
    dropped: list[dict[str, str]] = []
    for note in notes:
        shaped = _shaped(note)
        if shaped is None:
            dropped.append({"handle": _label(note), "reason": "bad shape"})
            continue
        handle, claim = shaped
        claim = " ".join(claim.split())
        reason = _web_problem(note, claim, env)
        if reason is None:
            items.append({"kind": "claim", "handle": handle, "text": claim})
        else:
            dropped.append({"handle": handle, "reason": reason})
    return WebInput(items, dropped)


def question_problem(question: str, env: Mapping[str, str] | None = None) -> str | None:
    """Why the question may not go to the web (the secret and forbidden-terms checks of `mem remember`), else None."""
    env = os.environ if env is None else env
    text = " ".join(question.split())
    if not text:
        return "the question is empty"
    secret = records.secret_in([text])
    if secret is not None:
        return f"the question looks like a secret ({secret})"
    try:
        hits = records.term_hits([text], env, "note")
    except records.ForbiddenListError as exc:
        return f"forbidden-terms list unreadable ({exc})"
    return "the question contains a forbidden term" if hits else None


def item_ids(items: Sequence[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    """The id each item has in the web prompt (`q` for the question, `c1`, `c2`... for the claims) -> the item."""
    ids: dict[str, dict[str, str]] = {}
    n = 0
    for item in items:
        if item["kind"] == "question":
            ids["q"] = dict(item)
        else:
            n += 1
            ids[f"c{n}"] = dict(item)
    return ids


def item_key(item: Mapping[str, str]) -> str:
    return QUESTION if item["kind"] == "question" else item["handle"]


_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\n(.*?)```", re.DOTALL)


def parse_web_reply(text: str) -> list[Any] | None:
    """The web session's final reply as a JSON list, a code fence tolerated; anything else is None (no web results)."""
    text = (text or "").strip()
    found = _FENCE.search(text)
    if found:
        text = found.group(1).strip()
    try:
        rows = json.loads(text)
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


# ---- step 4: fetch ----


class FetchError(Exception):
    """A page that could not be used."""


SANDBOX = safe_io.SANDBOX  # MEM_SANDBOX=1: a background session; see safe_io.sandbox_refusal


class FetchRefusedError(FetchError):
    """The address, scheme or redirect is not allowed."""


class FetchFailedError(FetchError):
    """The network or the server failed."""


class NotCheckedError(FetchError):
    """The content type is not text: the message reads "not checked: <type>"."""


_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPATIBLE = ipaddress.ip_network("::/96")


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """The IPv4 addresses an IPv6 address carries: mapped, compatible, NAT64, 6to4 and Teredo (server and client)."""
    found = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip in _NAT64 or ip in _V4_COMPATIBLE:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    return found


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", maxsplit=1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if not all(_public(str(v4)) for v4 in _embedded_v4(ip)):
            return False
        if ip in _V4_COMPATIBLE:  # deprecated form: when in doubt, refuse
            return False
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int, allow: bool) -> str:
    """The first address of the host; every address must be public unless the host is allowed."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchFailedError(f"cannot resolve {host}: {exc}") from exc
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        raise FetchFailedError(f"no address for {host}")
    if not allow:
        for address in addresses:
            if not _public(address):
                raise FetchRefusedError(f"{host} resolves to a non-public address")
    return addresses[0]


def _connection(
    parts: urllib.parse.SplitResult, address: str, port: int, timeout: float = TIMEOUT
) -> http.client.HTTPConnection:
    """A connection pinned to the checked address, so a second DNS answer cannot change the target."""
    host = parts.hostname or ""
    https = parts.scheme == "https"

    def open_socket(timeout: float | None) -> socket.socket:
        sock = socket.create_connection((address, port), timeout)
        if https:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        return sock

    class PinnedHTTP(http.client.HTTPConnection):
        def connect(self) -> None:
            self.sock = open_socket(self.timeout)

    class PinnedHTTPS(http.client.HTTPSConnection):
        def connect(self) -> None:
            self.sock = open_socket(self.timeout)

    return (PinnedHTTPS if https else PinnedHTTP)(host, port, timeout=timeout)


_BLOCK = {
    "p",
    "div",
    "br",
    "li",
    "ul",
    "ol",
    "tr",
    "td",
    "th",
    "table",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "header",
    "footer",
    "pre",
    "blockquote",
    "title",
    "body",
    "head",
}
_SKIP = {"script", "style", "template", "noscript"}


_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_HIDING_STYLE = re.compile(r"display:none|visibility:hidden")


def _hides(attrs: Any) -> bool:
    for name, value in attrs:
        if name == "hidden":
            return True
        if name == "aria-hidden" and (value or "").strip().lower() == "true":
            return True
        if name == "style" and _HIDING_STYLE.search(re.sub(r"\s+", "", (value or "").lower())):
            return True
    return False


class _Text(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.open: list[tuple[str, bool]] = []  # open non-void elements: (tag, hides its content)
        self.hidden = 0
        # an open script/style: the parser hands everything up to its end tag as data
        self.raw_tag: str | None = None
        self.raw: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self.raw_tag, self.raw = tag, []
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag not in _VOID:
            hides = _hides(attrs)
            self.open.append((tag, hides))
            self.hidden += hides

    def handle_endtag(self, tag: str) -> None:
        if tag == self.raw_tag:
            self.raw_tag = None
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")
        # closes the nearest open element of that name and what it holds
        for index in range(len(self.open) - 1, -1, -1):
            if self.open[index][0] == tag:
                self.hidden -= sum(h for _, h in self.open[index:])
                del self.open[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.raw_tag:
            self.raw.append(data)
        if not self.skip and not self.hidden:
            self.parts.append(data)


_PAST_RAW = re.compile(r"<[a-z/]", re.IGNORECASE)


def html_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts)
    if parser.raw_tag:  # a script/style never closed: its "content" runs to the end; resume at the next tag start (known limit: script source before it may leak into the text)
        rest = "".join(parser.raw)
        if (end := _PAST_RAW.search(rest)) is not None:
            return text + html_text(rest[end.start() :])
    return text


def _is_text_type(ctype: str) -> bool:
    return ctype.startswith("text/") or ctype in {
        "application/xhtml+xml",
        "application/xml",
        "application/json",
    }


def _pdf_text(raw: bytes) -> str:
    """The text of a PDF through `pdftotext` (no shell; the bytes go to its standard input)."""
    try:
        done = subprocess.run(
            ["pdftotext", "-q", "-enc", "UTF-8", "-", "-"],
            input=raw,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotCheckedError(f"not checked: pdf ({type(exc).__name__})") from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise NotCheckedError("not checked: pdf unreadable")
    return done.stdout.decode("utf-8", errors="replace")


def _cut(conn: http.client.HTTPConnection, cut: threading.Event) -> None:
    """Shut the socket down from another thread, which ends a read blocked on it."""
    cut.set()
    try:
        if conn.sock is not None:
            conn.sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def _read(resp: http.client.HTTPResponse, limit: int, deadline: float) -> bytes:
    """At most `limit` bytes, in chunks, so the deadline is checked between reads."""
    chunks: list[bytes] = []
    size = 0
    while size < limit:
        if time.monotonic() >= deadline:
            raise FetchFailedError("total time limit passed")
        chunk = resp.read1(min(65536, limit - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


class FetchOptions(TypedDict, total=False):
    """The keyword options of `fetch_raw`; an omitted one has the default in the comment after its field."""

    over: Literal["truncate", "fail"]  # "truncate"
    headers: Mapping[str, str] | None  # None
    deadline: float | None  # None: TOTAL_DEADLINE
    max_redirects: int  # MAX_REDIRECTS
    allow_hosts: Iterable[str]  # ()
    timeout: float  # TIMEOUT


class _Call(NamedTuple):
    """What every hop of one `fetch_raw` call shares."""

    limit_for: Callable[[str], int]
    over: str
    end: float  # the monotonic time the whole call must be over by
    sent: dict[str, str]  # request headers
    max_redirects: int
    allowed: set[str]  # hosts that skip the address check, on the first hop
    timeout: float


def _call(limit_for: Callable[[str], int], options: FetchOptions) -> _Call:
    if safe_io.sandbox_active():
        raise FetchRefusedError("network access is off in this session")
    deadline = options.get("deadline")
    return _Call(
        limit_for,
        options.get("over", "truncate"),
        time.monotonic() + (TOTAL_DEADLINE if deadline is None else deadline),
        {
            "Accept": "text/html,text/plain,application/pdf",
            "User-Agent": "mem-research",
            **(options.get("headers") or {}),
        },
        options.get("max_redirects", MAX_REDIRECTS),
        {h.lower() for h in options.get("allow_hosts", ())},
        options.get("timeout", TIMEOUT),
    )


def _checked_address(
    url: str, hop: int, allowed: set[str]
) -> tuple[urllib.parse.SplitResult, str, int]:
    """(parts, address, port) of a URL to connect to: http(s) only, no credentials, and an address that is public
    (or a host of `allowed` on the first hop)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise FetchRefusedError("only http and https URLs are fetched")
    if parts.username is not None or parts.password is not None:
        raise FetchRefusedError("a URL with credentials is refused")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise FetchRefusedError("bad port") from exc
    return (
        parts,
        _resolve(parts.hostname, port, hop == 0 and parts.hostname.lower() in allowed),
        port,
    )


def _start_cutter(
    conn: http.client.HTTPConnection, remaining: float
) -> tuple[threading.Event, threading.Timer]:
    """A server that drips bytes keeps every single read within its timeout: cut the socket at the deadline."""
    cut = threading.Event()
    cutter = threading.Timer(remaining, _cut, (conn, cut))
    cutter.daemon = True
    cutter.start()
    return cut, cutter


def _location(resp: http.client.HTTPResponse) -> str:
    target = resp.getheader("Location")
    if not target:
        raise FetchFailedError(f"redirect without a location ({resp.status})")
    return target


def _body(resp: http.client.HTTPResponse, call: _Call, cut: threading.Event) -> tuple[bytes, str]:
    header = (resp.getheader("Content-Type") or "").lower()
    limit = call.limit_for(header.split(";")[0].strip())
    raw = _read(resp, limit + (call.over == "fail"), call.end)
    if cut.is_set():
        raise FetchFailedError("total time limit passed")
    if len(raw) > limit:
        raise FetchFailedError(f"response larger than {limit // (1024 * 1024)} MB")
    return raw, header


def _exchange(
    conn: http.client.HTTPConnection,
    parts: urllib.parse.SplitResult,
    call: _Call,
    cut: threading.Event,
) -> tuple[bytes, str] | str:
    """One request: (body, Content-Type) of the page, or the Location a redirect points to."""
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    conn.request(
        "GET",
        path,
        headers={
            **call.sent,
            "Host": parts.netloc.rsplit("@", 1)[-1],
            "Accept-Encoding": "identity",
        },
    )
    resp = conn.getresponse()
    if resp.status in {301, 302, 303, 307, 308}:
        return _location(resp)
    if resp.status != HTTP_OK:
        raise FetchFailedError(f"HTTP {resp.status}")
    return _body(resp, call, cut)


def _failure(exc: Exception, cut: threading.Event) -> FetchFailedError:
    if cut.is_set():
        return FetchFailedError("total time limit passed")
    return FetchFailedError(f"{type(exc).__name__}: {exc}")


def fetch_raw(
    url: str, limit_for: Callable[[str], int], **options: Unpack[FetchOptions]
) -> tuple[bytes, str]:
    """(body, Content-Type lowercased, parameters kept) of a page. Only http(s); a non-public address is refused at
    every hop (`max_redirects` at most); `timeout` seconds per socket operation (TIMEOUT) and `deadline` seconds (TOTAL_DEADLINE) for the whole
    call. `limit_for(content type)` gives the byte limit (it may raise to refuse the type); past it, "truncate" cuts the
    body and "fail" raises FetchFailedError. `allow_hosts` names hosts that skip the address check, for the URL given only
    (a local test page): every redirect target is checked as any other. The pinned connection ignores HTTPS_PROXY."""
    call = _call(limit_for, options)
    for hop in range(call.max_redirects + 1):
        parts, address, port = _checked_address(url, hop, call.allowed)
        remaining = call.end - time.monotonic()
        if remaining <= 0:
            raise FetchFailedError("total time limit passed")
        conn = _connection(parts, address, port, min(call.timeout, remaining))
        cut, cutter = _start_cutter(conn, remaining)
        try:
            got = _exchange(conn, parts, call, cut)
        except (OSError, http.client.HTTPException) as exc:
            raise _failure(exc, cut) from exc
        finally:
            cutter.cancel()
            conn.close()
        if not isinstance(got, str):
            return got
        if hop == call.max_redirects:
            raise FetchRefusedError("too many redirects")
        url = urllib.parse.urljoin(url, got)
    raise FetchRefusedError("too many redirects")  # unreachable


def _charset(header: str) -> str:
    """The charset parameter of a Content-Type header (utf-8 when absent)."""
    charset = "utf-8"
    for piece in header.split(";")[1:]:
        key, _, value = piece.partition("=")
        if key.strip() == "charset" and value.strip():
            charset = value.strip().strip("\"'")
    return charset


def _decode(raw: bytes, charset: str) -> str:
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def fetch_text(url: str, allow_hosts: Iterable[str] = (), deadline: float | None = None) -> str:
    """The visible text of a page, through `fetch_raw`: 3 redirects at most; 2 MB read at most (8 MB for a PDF, which
    `pdftotext` reads when installed; else it is not checked); any other non-text type is not checked."""
    pdf = False

    def limit_for(ctype: str) -> int:
        nonlocal pdf
        pdf = ctype == "application/pdf" and shutil.which("pdftotext") is not None
        if not (pdf or _is_text_type(ctype)):
            raise NotCheckedError(f"not checked: {ctype or 'unknown type'}")
        return MAX_PDF_BYTES if pdf else MAX_BYTES

    raw, header = fetch_raw(url, limit_for, allow_hosts=allow_hosts, deadline=deadline)
    if pdf:
        return _pdf_text(raw)
    text = _decode(raw, _charset(header))
    ctype = header.split(";")[0].strip()
    return html_text(text) if ctype in {"text/html", "application/xhtml+xml"} else text


# ---- step 4: quotes ----

_PLAIN = str.maketrans({
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201a": "'",  # single low-9 quotation mark
    "\u201b": "'",  # single high-reversed-9 quotation mark
    "\u2032": "'",  # prime
    "\u201c": '"',  # left double quotation mark
    "\u201d": '"',  # right double quotation mark
    "\u201e": '"',  # double low-9 quotation mark
    "\u201f": '"',  # double high-reversed-9 quotation mark
    "\u2033": '"',  # double prime
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
})


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_PLAIN).split())


def quote_found(quote: str, text: str) -> bool:
    """True when the quote, at least 20 characters long once normalized, occurs in the text word for word."""
    wanted = normalize(quote)
    return len(wanted) >= MIN_QUOTE and wanted in normalize(text)


class Checked(NamedTuple):
    # {"item": key, "url", "stance", "source_kind", "passages": [str]}
    entries: list[dict[str, Any]]
    pages: dict[str, str]  # url -> the text fetched (only URLs that were fetched)
    dropped: list[dict[str, Any]]  # {"row", "reason"}


_FIELDS = ("item", "url", "stance", "source_kind")


def _shape_problem(row: Any) -> str | None:
    if not isinstance(row, Mapping):
        return "bad shape: not an object"
    for key in _FIELDS:
        if not isinstance(row.get(key), str) or not row[key].strip():
            return f"bad shape: {key} missing or not text"
    if row["stance"] not in STANCES:
        return f"bad shape: unknown stance {row['stance']!r}"
    if row["source_kind"] not in SOURCE_KINDS:
        return f"bad shape: unknown source_kind {row['source_kind']!r}"
    return None


def _scored_paragraphs(page: str, terms: set[str]) -> list[tuple[int, int, str]]:
    """(-score, index, paragraph) of each paragraph of `page` that shares a term and is long enough; the paragraphs
    are blank-line separated, or line separated when the page has no blank line."""
    chunks = re.split(r"\n\s*\n", page)
    if len(chunks) == 1:
        chunks = page.split("\n")
    scored = []
    for index, chunk in enumerate(chunks):
        paragraph = " ".join(chunk.split())
        score = len(terms & set(records.tokenize(paragraph)))
        if score and len(paragraph) >= MIN_PARAGRAPH:
            scored.append((-score, index, paragraph))
    return scored


def select_passages(page: str, text: str, limit: int = PAGE_CHARS) -> list[str]:
    """Whole paragraphs of `page` that share content words with `text`, best first, about `limit` characters at most
    (one paragraph longer than that is cut). The engine's tokenizer and stop words."""
    terms = set(records.tokenize(text)) - records.STOPWORDS
    if limit < MIN_QUOTE:
        return []
    chosen: list[str] = []
    used = 0
    for _, _, paragraph in sorted(_scored_paragraphs(page, terms)):
        cut = paragraph[:limit]
        if used + len(cut) > limit:
            continue
        chosen.append(cut)
        used += len(cut)
    return chosen


def _allowed_urls(
    rows: Sequence[Any], items: Mapping[str, Mapping[str, str]], max_urls: int
) -> list[str]:
    """The first `max_urls` distinct URLs of the rows that are well shaped and name a known item."""
    allowed: list[str] = []
    for row in rows:
        if (
            _shape_problem(row) is None
            and row["item"] in items
            and row["url"] not in allowed
            and len(allowed) < max_urls
        ):
            allowed.append(row["url"])
    return allowed


def _fetch_page(fetch: Callable[[str], str], url: str) -> str | FetchError:
    """The page text, or the error that says why it is not usable."""
    try:
        return fetch(url)
    except FetchRefusedError as exc:
        return FetchRefusedError(f"fetch refused: {exc}")
    except NotCheckedError as exc:
        return exc
    except (FetchError, OSError, ValueError) as exc:
        return FetchFailedError(f"fetch failed: {exc}")


class _RowCheck:
    """The state of one `check_rows` run: what each row adds to the entries or to the dropped rows."""

    def __init__(
        self,
        items: Mapping[str, Mapping[str, str]],
        fetch: Callable[[str], str],
        allowed: list[str],
        dropped: list[dict[str, Any]],
    ) -> None:
        self.items, self.fetch, self.allowed, self.dropped = items, fetch, allowed, dropped
        self.entries: list[dict[str, Any]] = []
        self.pages: dict[str, str | FetchError] = {}
        self.spent: dict[str, int] = {}
        self.seen: set[tuple[str, str, str]] = set()

    def _rejection(self, row: Any) -> str | None:
        problem = _shape_problem(row)
        if problem:
            return problem
        if row["item"] not in self.items:
            return "unknown item id"
        if row["url"] not in self.allowed:
            return "over the page limit"
        return None

    def _page(self, url: str) -> str | FetchError:
        if url not in self.pages:
            self.pages[url] = _fetch_page(self.fetch, url)
        return self.pages[url]

    def _keep(self, row: Any, item: Mapping[str, str], page: str) -> None:
        key = item_key(item)
        passages = select_passages(
            page, item["text"], min(PAGE_CHARS, ITEM_CHARS - self.spent.get(key, 0))
        )
        if not passages:
            self.dropped.append({
                "row": row,
                "reason": "no passage of the page shares terms with the item (or the item's budget is spent)",
            })
            return
        self.spent[key] = self.spent.get(key, 0) + sum(len(p) for p in passages)
        self.entries.append({
            "item": key,
            "url": row["url"],
            "stance": row["stance"],
            "source_kind": row["source_kind"],
            "passages": passages,
        })

    def add(self, row: Any) -> None:
        reason = self._rejection(row)
        if reason is not None:
            self.dropped.append({"row": row, "reason": reason})
            return
        item = self.items[row["item"]]
        mark = (item_key(item), row["url"], row["stance"])
        if mark in self.seen:
            return
        self.seen.add(mark)
        page = self._page(row["url"])
        if isinstance(page, FetchError):
            self.dropped.append({"row": row, "reason": str(page)})
            return
        self._keep(row, item, page)

    def result(self) -> Checked:
        return Checked(
            self.entries, {u: p for u, p in self.pages.items() if isinstance(p, str)}, self.dropped
        )


def check_rows(
    rows: Iterable[Any],
    items: Mapping[str, Mapping[str, str]],
    fetch: Callable[[str], str] = fetch_text,
    max_urls: int = 5,
) -> Checked:
    """The web session's rows (`item` is an id of `items`, see `item_ids`) -> entries with the passages of their page.
    Only the first `4 * max_urls` rows are considered and only the first `max_urls` distinct URLs among them are
    fetched, each once, after all rows are checked for shape: a row of any other URL is dropped before any fetch.
    A row whose page could not be fetched, or whose page shares no term with its item, is dropped with its reason."""
    rows = list(rows)
    dropped: list[dict[str, Any]] = []
    limit = ROWS_PER_URL * max_urls
    if len(rows) > limit:
        dropped.append({"row": f"{len(rows) - limit} more rows", "reason": "over the row limit"})
        rows = rows[:limit]
    check = _RowCheck(items, fetch, _allowed_urls(rows, items, max_urls), dropped)
    for row in rows:
        check.add(row)
    return check.result()


# ---- step 6: apply ----


class Plan(NamedTuple):
    # arguments after the program: ["note", "confirm", NOTE, "--fact", ...]
    commands: list[list[str]]
    # {"row", "reason"}; reason "downgraded to no source" for a weak contradiction
    refused: list[dict[str, Any]]


def _dash(values: Iterable[str]) -> str | None:
    return next((v for v in values if v.startswith("-")), None)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def finding_problem(claim: str, quote: str) -> str | None:
    """Why a finding says more than its quote or says the opposite: a number of the claim missing from the quote,
    fewer than 70% of the claim's content words in it, or a negation or opposite present on only one side of the claim
    and the sentence of the quote it rests on. None when it is covered."""
    wanted = set(_NUMBER.findall(normalize(claim)))
    if not wanted <= set(_NUMBER.findall(normalize(quote))):
        return "a number of the claim is not in its quote"
    if records.containment(records.tokenize(claim), records.tokenize(quote)) < MIN_FINDING_WORDS:
        return "the claim says more than its quote (under 70% of its content words are in it)"
    claim_tokens = records.tokenize(claim)
    rests_on = max(
        _SENTENCE.split(quote.strip()),
        key=lambda s: records.containment(claim_tokens, records.tokenize(s)),
    )
    if any(not any(c.isdigit() for c in w) for w in records.flagged_words(claim, rests_on)):
        return "the claim and its quote differ by a negation or an opposite"
    return None


_QUOTE_OFF_PAGE = (
    "the quote is not on the fetched page word for word (or is shorter than 20 characters)"
)


class _Planner:
    """The state of one `plan_commands` run: the commands kept, the rows refused and the quote lookups."""

    def __init__(
        self, entries: Sequence[Mapping[str, Any]], pages: Mapping[str, str], sent: Iterable[str]
    ) -> None:
        self.entries, self.pages, self.sent = entries, pages, set(sent)
        self.commands: list[list[str]] = []
        self.refused: list[dict[str, Any]] = []
        self.found: dict[tuple[str, Any], bool] = {}
        self.normalized: dict[str, str] = {}  # url -> its page, normalized once

    def refuse(self, row: Any, reason: str) -> None:
        self.refused.append({"row": row, "reason": reason})

    def on_page(self, quote: Any, url: str) -> TypeGuard[str]:
        key = (url, quote)
        if key not in self.found:
            if url not in self.normalized:
                self.normalized[url] = normalize(self.pages.get(url, ""))
            wanted = normalize(quote) if isinstance(quote, str) else ""
            self.found[key] = len(wanted) >= MIN_QUOTE and wanted in self.normalized[url]
        return self.found[key]

    def _verdict_problem(self, row: Mapping[str, Any]) -> str | None:
        note = row.get("note")
        if not isinstance(note, str) or note not in self.sent:
            return "note was not sent to the web"
        if row.get("verdict") not in VERDICTS:
            return "unknown verdict"
        return None

    def _source_problem(self, row: Mapping[str, Any]) -> str | None:
        note, verdict, url = row.get("note"), row.get("verdict"), row.get("url")
        stance = "supports" if verdict == "confirmed" else "contradicts"
        match = [
            e
            for e in self.entries
            if e["item"] == note and e["url"] == url and e["stance"] == stance
        ]
        if not isinstance(url, str) or not match:
            return f"the web step gave no {stance} URL like this one for the note"
        if verdict == "contradicted" and not any(
            e["source_kind"] in {"official", "paper"} for e in match
        ):
            return "downgraded to no source: the source is neither official nor a paper"
        return None

    def _text_problem(self, row: Mapping[str, Any]) -> str | None:
        note, url, fact, quote = row["note"], row["url"], row.get("fact"), row.get("quote")
        if not self.on_page(quote, url):
            return _QUOTE_OFF_PAGE
        if not isinstance(fact, str) or not fact.strip():
            return "the fact is empty"
        if _dash([note, fact, url, quote]) is not None:
            return "a value starts with '-'"
        return None

    def _note_problem(self, row: Mapping[str, Any]) -> str | None:
        reason = self._verdict_problem(row)
        if reason is not None or row.get("verdict") == "no source":
            return reason
        return self._source_problem(row) or self._text_problem(row)

    def note(self, row: Mapping[str, Any]) -> None:
        """Plan the command of a note row, or refuse it; a `no source` verdict plans nothing."""
        reason = self._note_problem(row)
        if reason is not None:
            self.refuse(row, reason)
        elif row["verdict"] != "no source":
            verb = "confirm" if row["verdict"] == "confirmed" else "dispute"
            self.commands.append([
                "note",
                verb,
                row["note"],
                "--fact",
                row["fact"],
                "--source",
                row["url"],
                "--quote",
                row["quote"],
            ])

    def _quote_problem(self, claim: str, url: str, quote: Any) -> str | None:
        if not self.on_page(quote, url):
            return _QUOTE_OFF_PAGE
        why = finding_problem(claim, quote)
        if why is not None:
            return why
        if _dash([claim, url]) is not None:
            return "a value starts with '-'"
        return None

    def _finding_problem(self, row: Mapping[str, Any]) -> str | None:
        claim, url = row.get("claim"), row.get("url")
        if not isinstance(claim, str) or not claim.strip():
            return "the claim is empty"
        if not isinstance(url, str) or not any(
            e["url"] == url and e["stance"] == "supports" for e in self.entries
        ):
            return "the web step gave no supporting URL like this one"
        return self._quote_problem(claim, url, row.get("quote"))

    def finding(self, row: Mapping[str, Any]) -> None:
        """Plan the command of a finding row, or refuse it."""
        reason = self._finding_problem(row)
        if reason is not None:
            self.refuse(row, reason)
        else:
            self.commands.append([
                "remember",
                "--global",
                "--kind",
                "finding",
                "--origin",
                "web",
                "--source",
                row["url"],
                "--claim",
                row["claim"],
            ])

    def rows(self, rows: Any, plan_row: Callable[[Mapping[str, Any]], None]) -> None:
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, Mapping):
                plan_row(row)
            else:
                self.refuse(row, "bad shape")


def plan_commands(
    verdicts: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    pages: Mapping[str, str],
    sent: Iterable[str],
) -> Plan:
    """The commands for a parsed `verdicts.json`. `entries` and `pages` are what `check_rows` kept; `sent` holds the
    handles that went to the web. A row is kept only when its URL was returned by the web step for that item with the
    matching stance and its quote is on the text fetched for that URL word for word. Every value is one argument;
    a value that starts with `-` refuses its row."""
    planner = _Planner(entries, pages, sent)
    notes = verdicts.get("notes", []) if isinstance(verdicts, Mapping) else []
    findings = verdicts.get("findings", []) if isinstance(verdicts, Mapping) else []
    planner.rows(notes, planner.note)
    planner.rows(findings, planner.finding)
    return Plan(planner.commands, planner.refused)


class ApplyOptions(TypedDict, total=False):
    """The keyword options of `apply`; an omitted one has the default named beside it."""

    mem_cmd: Sequence[str]  # MEM_ENTRY
    root: str | Path | None  # None
    timeout: int  # 120
    env: Mapping[str, str] | None  # None


def apply(
    verdicts: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    pages: Mapping[str, str],
    sent: Iterable[str],
    **options: Unpack[ApplyOptions],
) -> dict[str, Any]:
    """Run the planned commands, no shell, through `mem_cmd` (the repository's `bin/mem` by default),
    with `env` as their environment (the inherited one when None).
    Report: applied (argument lists), refused (rows with reasons), failed (argument list, exit code, stderr)."""
    plan = plan_commands(verdicts, entries, pages, sent)
    root, env = options.get("root"), options.get("env")
    prefix = [
        *options.get("mem_cmd", MEM_ENTRY),
        *(["--root", str(root)] if root is not None else []),
    ]
    applied: list[list[str]] = []
    failed: list[dict[str, Any]] = []
    for args in plan.commands:
        try:
            done = subprocess.run(
                [*prefix, *args],
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=options.get("timeout", 120),
                env=None if env is None else dict(env),
            )
            code, err = done.returncode, done.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, err = -1, f"{type(exc).__name__}: {exc}"
        if code == 0:
            applied.append(args)
        else:
            failed.append({"args": args, "code": code, "stderr": err})
    return {"applied": applied, "refused": plan.refused, "failed": failed}
