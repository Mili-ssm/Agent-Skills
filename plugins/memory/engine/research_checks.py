"""Pure parts of the `mem-research` pipeline (stage 1b): the web step's input (step 2), the page check (step 4) and
the application of the verdicts (step 6). No model session and no third-party dependency here.

Text that comes from the web is data: no quote or claim is ever executed, used as a command name or as an option.
"""
from __future__ import annotations

import html.parser
import http.client
import ipaddress
import os
import socket
import ssl
import subprocess
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Sequence

import records

STANCES = ("supports", "contradicts")
SOURCE_KINDS = ("official", "paper", "other")
VERDICTS = ("confirmed", "contradicted", "no source")
MIN_QUOTE = 20
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = 10
MEM_ENTRY = [str(Path(__file__).resolve().parent.parent / "bin" / "mem")]


# ---- step 2: web input ----

class WebInput(NamedTuple):
    items: list[dict[str, str]]  # {"kind": "question", "text"} then {"kind": "claim", "handle", "text"}
    dropped: list[dict[str, str]]  # {"handle", "reason"}


def web_input(question: str, notes: Sequence[Mapping[str, Any]], env: Mapping[str, str] | None = None) -> WebInput:
    """What may go to the web: the question as given, and each note claim that passes the secret and the
    forbidden-terms checks of `mem remember`. A note is `{"handle", "claim"}` and, when given, `"scope": "global"`:
    a project-scope record is never accepted. A soft term counts as a hit too, since nobody can approve it here."""
    env = os.environ if env is None else env
    items = [{"kind": "question", "text": question}]
    dropped: list[dict[str, str]] = []
    for note in notes:
        handle = note.get("handle") if isinstance(note, Mapping) else None
        claim = note.get("claim") if isinstance(note, Mapping) else None
        label = handle if isinstance(handle, str) else "?"
        if not isinstance(handle, str) or not handle or not isinstance(claim, str) or not claim.strip():
            dropped.append({"handle": label, "reason": "bad shape"})
            continue
        if note.get("scope", "global") != "global":
            dropped.append({"handle": handle, "reason": "not a global record"})
            continue
        claim = " ".join(claim.split())
        secret = records.secret_in([claim])
        if secret is not None:
            dropped.append({"handle": handle, "reason": f"looks like a secret ({secret})"})
            continue
        try:
            hits = records.term_hits([claim], env, "note")
        except records.ForbiddenListError as exc:
            dropped.append({"handle": handle, "reason": f"forbidden-terms list unreadable ({exc})"})
            continue
        if hits:
            dropped.append({"handle": handle, "reason": "contains a forbidden term"})
            continue
        items.append({"kind": "claim", "handle": handle, "text": claim})
    return WebInput(items, dropped)


# ---- step 4: fetch ----

class FetchError(Exception):
    """A page that could not be used."""


class FetchRefused(FetchError):
    """The address, scheme or redirect is not allowed."""


class FetchFailed(FetchError):
    """The network or the server failed."""


class NotChecked(FetchError):
    """The content type is not text: the message reads "not checked: <type>"."""


def _public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _resolve(host: str, port: int, allow: bool) -> str:
    """The first address of the host; every address must be public unless the host is allowed."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchFailed(f"cannot resolve {host}: {exc}") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise FetchFailed(f"no address for {host}")
    if not allow:
        for address in addresses:
            if not _public(address):
                raise FetchRefused(f"{host} resolves to a non-public address")
    return addresses[0]


def _connection(parts: urllib.parse.SplitResult, address: str, port: int) -> http.client.HTTPConnection:
    """A connection pinned to the checked address, so a second DNS answer cannot change the target."""
    host = parts.hostname or ""

    class Pinned(http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection):  # type: ignore[misc]
        def connect(self) -> None:
            sock = socket.create_connection((address, port), self.timeout)
            if parts.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            self.sock = sock

    return Pinned(host, port, timeout=TIMEOUT)


_BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "h1", "h2", "h3", "h4", "h5", "h6",
          "section", "article", "header", "footer", "pre", "blockquote", "title", "body", "head"}
_SKIP = {"script", "style", "template", "noscript"}


class _Text(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def html_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    parser.close()
    return "".join(parser.parts)


def _is_text_type(ctype: str) -> bool:
    return ctype.startswith("text/") or ctype in ("application/xhtml+xml", "application/xml", "application/json")


def fetch_text(url: str, allow_hosts: Iterable[str] = ()) -> str:
    """The visible text of a page. Only http(s); a non-public address is refused at every hop (3 redirects at most);
    10 s timeout; 2 MB read at most. `allow_hosts` names hosts that skip the address check (a local test page)."""
    allowed = {h.lower() for h in allow_hosts}
    for hop in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchRefused("only http and https URLs are fetched")
        if parts.username is not None or parts.password is not None:
            raise FetchRefused("a URL with credentials is refused")
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as exc:
            raise FetchRefused("bad port") from exc
        address = _resolve(parts.hostname, port, parts.hostname.lower() in allowed)
        conn = _connection(parts, address, port)
        try:
            path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
            conn.request("GET", path, headers={"Host": parts.netloc.rsplit("@", 1)[-1], "Accept": "text/html,text/plain",
                                               "User-Agent": "mem-research", "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                target = resp.getheader("Location")
                if not target:
                    raise FetchFailed(f"redirect without a location ({resp.status})")
                if hop == MAX_REDIRECTS:
                    raise FetchRefused("too many redirects")
                url = urllib.parse.urljoin(url, target)
                continue
            if resp.status != 200:
                raise FetchFailed(f"HTTP {resp.status}")
            header = resp.getheader("Content-Type") or ""
            ctype = header.split(";")[0].strip().lower()
            if not _is_text_type(ctype):
                raise NotChecked(f"not checked: {ctype or 'unknown type'}")
            raw = resp.read(MAX_BYTES)
        except (OSError, http.client.HTTPException) as exc:
            raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
        finally:
            conn.close()
        charset = "utf-8"
        for piece in header.split(";")[1:]:
            key, _, value = piece.partition("=")
            if key.strip().lower() == "charset" and value.strip():
                charset = value.strip().strip("\"'")
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        return html_text(text) if ctype in ("text/html", "application/xhtml+xml") else text
    raise FetchRefused("too many redirects")  # unreachable


# ---- step 4: quotes ----

_PLAIN = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
                        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
                        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
                        "−": "-"})


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_PLAIN).split())


def quote_found(quote: str, text: str) -> bool:
    """True when the quote, at least 20 characters long once normalized, occurs in the text word for word."""
    wanted = normalize(quote)
    return len(wanted) >= MIN_QUOTE and wanted in normalize(text)


class Checked(NamedTuple):
    surviving: list[dict[str, str]]
    dropped: list[dict[str, Any]]  # {"row", "reason"}


_FIELDS = ("item", "url", "quote", "stance", "source_kind")


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


def check_items(items: Iterable[Any], fetch: Callable[[str], str] = fetch_text) -> Checked:
    """Keep the rows whose quote is on the page; each distinct URL is fetched once."""
    surviving: list[dict[str, str]] = []
    dropped: list[dict[str, Any]] = []
    pages: dict[str, str | FetchError] = {}
    for row in items:
        problem = _shape_problem(row)
        if problem:
            dropped.append({"row": row, "reason": problem})
            continue
        url = row["url"]
        if url not in pages:
            try:
                pages[url] = normalize(fetch(url))
            except FetchRefused as exc:
                pages[url] = FetchRefused(f"fetch refused: {exc}")
            except NotChecked as exc:
                pages[url] = exc
            except (FetchError, OSError, ValueError) as exc:
                pages[url] = FetchFailed(f"fetch failed: {exc}")
        page = pages[url]
        if isinstance(page, FetchError):
            dropped.append({"row": row, "reason": str(page)})
        elif not quote_found(row["quote"], page):
            dropped.append({"row": row, "reason": "quote not on the page (or shorter than 20 characters)"})
        else:
            surviving.append({key: row[key] for key in _FIELDS})
    return Checked(surviving, dropped)


# ---- step 6: apply ----

class Plan(NamedTuple):
    commands: list[list[str]]  # arguments after the program: ["note", "confirm", NOTE, "--fact", ...]
    refused: list[dict[str, Any]]  # {"row", "reason"}; reason "downgraded to no source" for a weak contradiction


def _index(value: Any, surviving: Sequence[Mapping[str, str]]) -> Mapping[str, str] | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(surviving):
        return surviving[value]
    return None


def _dash(values: Iterable[str]) -> str | None:
    return next((v for v in values if v.startswith("-")), None)


def plan_commands(verdicts: Mapping[str, Any], surviving: Sequence[Mapping[str, str]],
                  sent: Iterable[str]) -> Plan:
    """The commands for a parsed `verdicts.json`. `sent` holds the handles that went to the web in step 2.
    Every value is one argument; a value that starts with `-` refuses its row."""
    sent = set(sent)
    commands: list[list[str]] = []
    refused: list[dict[str, Any]] = []

    def refuse(row: Any, reason: str) -> None:
        refused.append({"row": row, "reason": reason})

    notes = verdicts.get("notes", []) if isinstance(verdicts, Mapping) else []
    findings = verdicts.get("findings", []) if isinstance(verdicts, Mapping) else []
    for row in notes if isinstance(notes, list) else []:
        if not isinstance(row, Mapping):
            refuse(row, "bad shape")
            continue
        note, verdict, fact = row.get("note"), row.get("verdict"), row.get("fact")
        if not isinstance(note, str) or note not in sent:
            refuse(row, "note was not sent to the web")
            continue
        if verdict not in VERDICTS:
            refuse(row, "unknown verdict")
            continue
        if verdict == "no source":
            continue
        quote = _index(row.get("quote"), surviving)
        if quote is None:
            refuse(row, "no surviving quote at that index")
            continue
        if quote["item"] != note:
            refuse(row, "the quote is about another note")
            continue
        if quote["stance"] != ("supports" if verdict == "confirmed" else "contradicts"):
            refuse(row, f"the quote's stance ({quote['stance']}) does not match {verdict}")
            continue
        if verdict == "contradicted" and quote["source_kind"] not in ("official", "paper"):
            refuse(row, "downgraded to no source: the source is neither official nor a paper")
            continue
        if not isinstance(fact, str) or not fact.strip():
            refuse(row, "the fact is empty")
            continue
        bad = _dash([note, fact, quote["url"], quote["quote"]])
        if bad is not None:
            refuse(row, "a value starts with '-'")
            continue
        verb = "confirm" if verdict == "confirmed" else "dispute"
        commands.append(["note", verb, note, "--fact", fact, "--source", quote["url"], "--quote", quote["quote"]])
    for row in findings if isinstance(findings, list) else []:
        if not isinstance(row, Mapping):
            refuse(row, "bad shape")
            continue
        claim = row.get("claim")
        quote = _index(row.get("quote"), surviving)
        if not isinstance(claim, str) or not claim.strip():
            refuse(row, "the claim is empty")
        elif quote is None:
            refuse(row, "no surviving quote at that index")
        elif quote["stance"] != "supports":
            refuse(row, "a finding needs a quote that supports it")
        elif _dash([claim, quote["url"]]) is not None:
            refuse(row, "a value starts with '-'")
        else:
            commands.append(["remember", "--global", "--kind", "finding", "--origin", "web",
                             "--source", quote["url"], "--claim", claim])
    return Plan(commands, refused)


def apply(verdicts: Mapping[str, Any], surviving: Sequence[Mapping[str, str]], sent: Iterable[str],
          mem_cmd: Sequence[str] = MEM_ENTRY, root: str | Path | None = None, timeout: int = 120) -> dict[str, Any]:
    """Run the planned commands, no shell, through `mem_cmd` (the repository's `bin/mem` by default).
    Report: applied (argument lists), refused (rows with reasons), failed (argument list, exit code, stderr)."""
    plan = plan_commands(verdicts, surviving, sent)
    prefix = [*mem_cmd, *(["--root", str(root)] if root is not None else [])]
    applied: list[list[str]] = []
    failed: list[dict[str, Any]] = []
    for args in plan.commands:
        try:
            done = subprocess.run([*prefix, *args], shell=False, capture_output=True, text=True, timeout=timeout)
            code, err = done.returncode, done.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, err = -1, f"{type(exc).__name__}: {exc}"
        if code == 0:
            applied.append(args)
        else:
            failed.append({"args": args, "code": code, "stderr": err})
    return {"applied": applied, "refused": plan.refused, "failed": failed}
