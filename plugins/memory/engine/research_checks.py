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
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Sequence

import mem
import records

STANCES = ("supports", "contradicts")
SOURCE_KINDS = ("official", "paper", "other")
VERDICTS = ("confirmed", "contradicted", "no source")
MIN_QUOTE = 20
MAX_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024
PAGE_CHARS = 3000   # passages handed to the verdict step, per page
ITEM_CHARS = 12000  # and per item, over all its pages
MIN_FINDING_WORDS = 0.7   # share of a finding's content words that its quote must hold
QUESTION = "(question)"   # the item key of the question; a note's key is its handle
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


_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\n(.*?)```", re.S)


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


def _pdf_text(raw: bytes) -> str:
    """The text of a PDF through `pdftotext` (no shell; the bytes go to its standard input)."""
    try:
        done = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", "-", "-"], input=raw, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NotChecked(f"not checked: pdf ({type(exc).__name__})") from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise NotChecked("not checked: pdf unreadable")
    return done.stdout.decode("utf-8", errors="replace")


def fetch_text(url: str, allow_hosts: Iterable[str] = ()) -> str:
    """The visible text of a page. Only http(s); a non-public address is refused at every hop (3 redirects at most);
    10 s timeout; 2 MB read at most (8 MB for a PDF, which `pdftotext` reads when installed; else it is not checked). `allow_hosts` names hosts that skip the address check (a local test page)."""
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
            conn.request("GET", path, headers={"Host": parts.netloc.rsplit("@", 1)[-1], "Accept": "text/html,text/plain,application/pdf",
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
            pdf = ctype == "application/pdf" and shutil.which("pdftotext") is not None
            if not (pdf or _is_text_type(ctype)):
                raise NotChecked(f"not checked: {ctype or 'unknown type'}")
            raw = resp.read(MAX_PDF_BYTES if pdf else MAX_BYTES)
        except (OSError, http.client.HTTPException) as exc:
            raise FetchFailed(f"{type(exc).__name__}: {exc}") from exc
        finally:
            conn.close()
        if pdf:
            return _pdf_text(raw)
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
    entries: list[dict[str, Any]]  # {"item": key, "url", "stance", "source_kind", "passages": [str]}
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


def select_passages(page: str, text: str, limit: int = PAGE_CHARS) -> list[str]:
    """Whole paragraphs of `page` that share content words with `text`, best first, about `limit` characters at most
    (one paragraph longer than that is cut). The engine's tokenizer and stop words."""
    terms = set(mem.tokenize(text)) - records.STOPWORDS
    if limit < MIN_QUOTE:
        return []
    chunks = re.split(r"\n\s*\n", page)
    if len(chunks) == 1:
        chunks = page.split("\n")
    scored = []
    for index, chunk in enumerate(chunks):
        paragraph = " ".join(chunk.split())
        score = len(terms & set(mem.tokenize(paragraph)))
        if score and len(paragraph) >= 20:
            scored.append((-score, index, paragraph))
    chosen: list[str] = []
    used = 0
    for _, _, paragraph in sorted(scored):
        paragraph = paragraph[:limit]
        if used + len(paragraph) > limit:
            continue
        chosen.append(paragraph)
        used += len(paragraph)
    return chosen


def check_rows(rows: Iterable[Any], items: Mapping[str, Mapping[str, str]], fetch: Callable[[str], str] = fetch_text,
               max_pages: int = 5) -> Checked:
    """The web session's rows (`item` is an id of `items`, see `item_ids`) -> entries with the passages of their page.
    Each distinct URL is fetched once and at most `max_pages` of them; a row whose page could not be fetched, or whose
    page shares no term with its item, is dropped with its reason."""
    entries: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    pages: dict[str, str | FetchError] = {}
    spent: dict[str, int] = {}
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        problem = _shape_problem(row)
        if problem:
            dropped.append({"row": row, "reason": problem})
            continue
        item = items.get(row["item"])
        if item is None:
            dropped.append({"row": row, "reason": "unknown item id"})
            continue
        key, url = item_key(item), row["url"]
        if (key, url, row["stance"]) in seen:
            continue
        seen.add((key, url, row["stance"]))
        if url not in pages:
            if len(pages) >= max_pages:
                dropped.append({"row": row, "reason": f"over the page cap ({max_pages})"})
                continue
            try:
                pages[url] = fetch(url)
            except FetchRefused as exc:
                pages[url] = FetchRefused(f"fetch refused: {exc}")
            except NotChecked as exc:
                pages[url] = exc
            except (FetchError, OSError, ValueError) as exc:
                pages[url] = FetchFailed(f"fetch failed: {exc}")
        page = pages[url]
        if isinstance(page, FetchError):
            dropped.append({"row": row, "reason": str(page)})
            continue
        passages = select_passages(page, item["text"], min(PAGE_CHARS, ITEM_CHARS - spent.get(key, 0)))
        if not passages:
            dropped.append({"row": row, "reason": "no passage of the page shares terms with the item (or the item's budget is spent)"})
            continue
        spent[key] = spent.get(key, 0) + sum(len(p) for p in passages)
        entries.append({"item": key, "url": url, "stance": row["stance"], "source_kind": row["source_kind"],
                        "passages": passages})
    return Checked(entries, {u: p for u, p in pages.items() if isinstance(p, str)}, dropped)


# ---- step 6: apply ----

class Plan(NamedTuple):
    commands: list[list[str]]  # arguments after the program: ["note", "confirm", NOTE, "--fact", ...]
    refused: list[dict[str, Any]]  # {"row", "reason"}; reason "downgraded to no source" for a weak contradiction


def _dash(values: Iterable[str]) -> str | None:
    return next((v for v in values if v.startswith("-")), None)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def finding_problem(claim: str, quote: str) -> str | None:
    """Why a finding says more than its quote: a number of the claim missing from the quote, or fewer than 70% of the
    claim's content words in it. None when it is covered."""
    wanted = set(_NUMBER.findall(normalize(claim)))
    if not wanted <= set(_NUMBER.findall(normalize(quote))):
        return "a number of the claim is not in its quote"
    if records.containment(mem.tokenize(claim), mem.tokenize(quote)) < MIN_FINDING_WORDS:
        return "the claim says more than its quote (under 70% of its content words are in it)"
    return None


def plan_commands(verdicts: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], pages: Mapping[str, str],
                  sent: Iterable[str]) -> Plan:
    """The commands for a parsed `verdicts.json`. `entries` and `pages` are what `check_rows` kept; `sent` holds the
    handles that went to the web. A row is kept only when its URL was returned by the web step for that item with the
    matching stance and its quote is on the text fetched for that URL word for word. Every value is one argument;
    a value that starts with `-` refuses its row."""
    sent = set(sent)
    commands: list[list[str]] = []
    refused: list[dict[str, Any]] = []
    found: dict[str, bool] = {}

    def refuse(row: Any, reason: str) -> None:
        refused.append({"row": row, "reason": reason})

    def on_page(quote: Any, url: str) -> bool:
        key = f"{url}\n{quote}"
        if key not in found:
            found[key] = isinstance(quote, str) and quote_found(quote, pages.get(url, ""))
        return found[key]

    notes = verdicts.get("notes", []) if isinstance(verdicts, Mapping) else []
    findings = verdicts.get("findings", []) if isinstance(verdicts, Mapping) else []
    for row in notes if isinstance(notes, list) else []:
        if not isinstance(row, Mapping):
            refuse(row, "bad shape")
            continue
        note, verdict, fact, url = row.get("note"), row.get("verdict"), row.get("fact"), row.get("url")
        if not isinstance(note, str) or note not in sent:
            refuse(row, "note was not sent to the web")
            continue
        if verdict not in VERDICTS:
            refuse(row, "unknown verdict")
            continue
        if verdict == "no source":
            continue
        stance = "supports" if verdict == "confirmed" else "contradicts"
        match = [e for e in entries if e["item"] == note and e["url"] == url and e["stance"] == stance]
        if not isinstance(url, str) or not match:
            refuse(row, f"the web step gave no {stance} URL like this one for the note")
            continue
        if verdict == "contradicted" and not any(e["source_kind"] in ("official", "paper") for e in match):
            refuse(row, "downgraded to no source: the source is neither official nor a paper")
            continue
        quote = row.get("quote")
        if not on_page(quote, url):
            refuse(row, "the quote is not on the fetched page word for word (or is shorter than 20 characters)")
            continue
        if not isinstance(fact, str) or not fact.strip():
            refuse(row, "the fact is empty")
            continue
        if _dash([note, fact, url, quote]) is not None:
            refuse(row, "a value starts with '-'")
            continue
        verb = "confirm" if verdict == "confirmed" else "dispute"
        commands.append(["note", verb, note, "--fact", fact, "--source", url, "--quote", quote])
    for row in findings if isinstance(findings, list) else []:
        if not isinstance(row, Mapping):
            refuse(row, "bad shape")
            continue
        claim, url, quote = row.get("claim"), row.get("url"), row.get("quote")
        if not isinstance(claim, str) or not claim.strip():
            refuse(row, "the claim is empty")
        elif not isinstance(url, str) or not any(e["url"] == url and e["stance"] == "supports" for e in entries):
            refuse(row, "the web step gave no supporting URL like this one")
        elif not on_page(quote, url):
            refuse(row, "the quote is not on the fetched page word for word (or is shorter than 20 characters)")
        elif (why := finding_problem(claim, quote)) is not None:
            refuse(row, why)
        elif _dash([claim, url]) is not None:
            refuse(row, "a value starts with '-'")
        else:
            commands.append(["remember", "--global", "--kind", "finding", "--origin", "web",
                             "--source", url, "--claim", claim])
    return Plan(commands, refused)


def apply(verdicts: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], pages: Mapping[str, str],
          sent: Iterable[str], mem_cmd: Sequence[str] = MEM_ENTRY, root: str | Path | None = None,
          timeout: int = 120) -> dict[str, Any]:
    """Run the planned commands, no shell, through `mem_cmd` (the repository's `bin/mem` by default).
    Report: applied (argument lists), refused (rows with reasons), failed (argument list, exit code, stderr)."""
    plan = plan_commands(verdicts, entries, pages, sent)
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
