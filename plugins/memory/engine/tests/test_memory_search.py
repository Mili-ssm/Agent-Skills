import json
from typing import TypedDict, Unpack

import mem
import pytest
from conftest import usage_log_path
from store import records

PER_SCOPE_LIMIT = 3
MEMORY_SECTION_LINES = 2
USAGE_ERROR = 2
TABS_IN_LINE = 2


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root / ".memory"


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


class MemoryFields(TypedDict, total=False):
    kind: str
    status: str
    valid_until: str | None
    body: str
    created: str
    observed: int


def put(folder, claim, **fields: Unpack[MemoryFields]):
    kind = fields.get("kind", "lesson")
    status = fields.get("status", "active")
    valid_until = fields.get("valid_until")
    body = fields.get("body", "")
    created = fields.get("created", "2026-01-05")
    observed = fields.get("observed", 1)
    folder.mkdir(parents=True, exist_ok=True)
    slug = records.slug_of(claim)
    text = f"---\nkind: {kind}\nclaim: {claim}\ncreated: '{created}'\nobserved: {observed}\nstatus: {status}\n"
    if valid_until:
        text += f"valid_until: '{valid_until}'\n"
    (folder / f"{slug}.md").write_text(text + f"---\n{body}", encoding="utf-8")
    return slug


def run(capsys, *argv):
    code = mem.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_no_memory_matching_leaves_output_unchanged(hub_root, project, capsys):
    _, before, _ = run(capsys, "--root", str(hub_root), "search", "attention")
    put(project, "Unrelated pottery glaze notes")
    _, after, _ = run(capsys, "--root", str(hub_root), "search", "attention")
    assert after == before and after


def test_parity_after_removing_memory_sections(hub_root, project, gfolder, capsys):
    _, before, err0 = run(capsys, "--root", str(hub_root), "search", "attention recurrence")
    put(project, "Attention recurrence pitfall")
    put(gfolder, "Recurrence and attention lesson")
    _, after, err1 = run(capsys, "--root", str(hub_root), "search", "attention recurrence")
    keep, skipping = [], False
    for line in after.splitlines(keepends=True):
        if line.startswith("-- memories ("):
            skipping = True
        elif line == "-- notes --\n":
            skipping = False
        elif not skipping:
            keep.append(line)
    assert "".join(keep) == before
    assert "-- memories (project) --" in after and "-- memories (global) --" in after
    assert err1 == err0


def test_line_format_order_and_notes_separator(hub_root, project, capsys):
    slug = put(project, "Attention needs care", kind="pitfall", observed=3)
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention", "--deep")
    lines = out.splitlines()
    assert lines[0] == "-- memories (project) --"
    assert lines[1] == f"m:{slug}\t[memory: pitfall, observed 3, 2026-01-05]\tAttention needs care"
    assert lines[2] == "-- notes --"
    assert lines[3].startswith("literature/")


def test_dead_memories_hidden_then_shown(hub_root, project, capsys):
    put(project, "Attention refuted claim", status="refuted")
    put(project, "Attention superseded claim", status="superseded")
    put(project, "Attention expired claim", valid_until="2020-01-01")
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention")
    assert "-- memories" not in out
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention", "--all-memories")
    assert ", refuted]" in out and ", superseded]" in out and ", expired]" in out


def test_at_most_three_per_scope(hub_root, project, capsys):
    for i in range(5):
        put(project, f"Attention variant {i}")
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention")
    assert sum(line.startswith("m:") for line in out.splitlines()) == PER_SCOPE_LIMIT


def test_scopes(hub_root, project, capsys):
    put(project, "Attention memory")
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention", "--scope", "memories")
    lines = out.splitlines()
    assert (
        lines[0] == "-- memories (project) --"
        and len(lines) == MEMORY_SECTION_LINES
        and "-- notes --" not in out
    )
    _, out, _ = run(
        capsys, "--root", str(hub_root), "search", "attention", "--scope", "notes", "--deep"
    )
    assert "-- memories" not in out and "-- notes --" not in out and out.startswith("literature/")


def test_no_memory_section_with_offset_filter_or_paths(hub_root, project, capsys):
    put(project, "Attention memory")
    for extra in (["--offset", "1"], ["--type", "knowledge"], ["--detail", "paths"]):
        _, out, _ = run(capsys, "--root", str(hub_root), "search", "attention", *extra)
        assert "m:" not in out and "-- " not in out
    _, out, _ = run(
        capsys,
        "--root",
        str(hub_root),
        "search",
        "attention",
        "--scope",
        "memories",
        "--detail",
        "paths",
    )
    assert out.splitlines() == ["m:attention-memory"]


def test_also_and_no_matches(hub_root, project, capsys):
    put(project, "Attention memory")
    _, out, err = run(
        capsys, "--root", str(hub_root), "search", "attention", "--also", "zzzunknown"
    )
    assert out.splitlines()[:2] == ["== attention ==", "-- memories (project) --"]
    assert "== zzzunknown ==" in out
    _, out, err = run(
        capsys, "--root", str(hub_root), "search", "zzzunknown", "--scope", "memories"
    )
    assert not out and "no matches" in err
    put(project, "Zzzunknown only memory")
    _, out, err = run(capsys, "--root", str(hub_root), "search", "zzzunknown")
    assert "m:" in out and "no matches" not in err


def test_broken_file_named_once(hub_root, project, capsys):
    project.mkdir(parents=True)
    (project / "bad.md").write_text("---\nkind: nope\nclaim: x\n---\n", encoding="utf-8")
    code, _, err = run(
        capsys, "--root", str(hub_root), "search", "attention", "--also", "recurrence"
    )
    assert code == 0
    assert err.count("mem: skipped") == 1 and "bad.md" in err and "Traceback" not in err


def test_usage_log_names_memories(hub_root, project, capsys):
    slug = put(project, "Attention memory")
    run(capsys, "--root", str(hub_root), "search", "attention")
    entry = json.loads(usage_log_path().read_text().splitlines()[-1])
    assert entry["memories"] == [f"m:{slug}"]


def test_search_memories_without_store(project, capsys):
    put(project, "Attention memory")
    code, out, _ = run(capsys, "search", "attention", "--scope", "memories")
    assert code == 0 and "-- memories (project) --" in out
    code, _, err = run(capsys, "search", "attention")
    assert code == USAGE_ERROR and "no store is set" in err


def test_show_memory(hub_root, project, gfolder, capsys):
    slug = put(project, "Attention needs care", body="Body text here.\n")
    code, out, _ = run(capsys, "--root", str(hub_root), "show", f"m:{slug}")
    assert code == 0
    assert out == (
        f"== m:{slug} (project)\nkind: lesson · observed 1 · status active · created 2026-01-05\n"
        "\n## Claim\nAttention needs care\n\nBody text here.\n"
    )
    _, out, _ = run(capsys, "--root", str(hub_root), "show", f"m:{slug}", "--section", "conclusion")
    assert out.rstrip("\n").endswith("Attention needs care") and "Body text" not in out


def test_show_mixed_and_unknown(hub_root, project, capsys):
    slug = put(project, "Attention needs care")
    code, out, _ = run(
        capsys, "--root", str(hub_root), "show", "attention-replaces-recurrence", f"m:{slug}"
    )
    assert code == 0 and out.index("== knowledge/") < out.index("== m:")
    code, out, err = run(capsys, "--root", str(hub_root), "show", "m:nope")
    assert code == 1 and "m:nope" in err


def test_stats_counts_memories(hub_root, project, gfolder, capsys):
    _, out, _ = run(capsys, "--root", str(hub_root), "stats")
    assert "memories:" not in out
    put(project, "One")
    put(gfolder, "Two", status="refuted")
    _, out, _ = run(capsys, "--root", str(hub_root), "stats")
    lines = out.splitlines()
    assert lines[0].startswith("store:") and lines[1] == "memories: 1 project, 1 global (1 live)"


def test_show_broken_memory_reports_and_fails(hub_root, project, capsys):
    project.mkdir()
    (project / "bad.md").write_text("---\nkind: nonsense\nclaim: Bad one.\n---\n")
    code, out, err = run(capsys, "--root", str(hub_root), "show", "m:bad")
    assert code == 1 and "== m:bad" not in out
    assert err.startswith("mem: skipped ") and "bad.md: " in err and "kind" in err


def test_show_memory_needs_no_store(project, capsys):
    slug = put(project, "Attention needs care")
    code, out, _ = run(capsys, "show", f"m:{slug}")
    assert code == 0 and out.startswith(f"== m:{slug} (project)")
    code, _, err = run(capsys, "show", "some-note")
    assert code == USAGE_ERROR and "no store is set" in err


def test_claim_whitespace_is_collapsed_in_line_and_block(hub_root, project, capsys):
    project.mkdir()
    (project / "tabby.md").write_text('---\nkind: lesson\nclaim: "Tab\\there\\nand newline"\n---\n')
    _, out, _ = run(capsys, "--root", str(hub_root), "search", "tab newline", "--scope", "memories")
    line = next(ln for ln in out.splitlines() if ln.startswith("m:tabby"))
    assert line.endswith("\tTab here and newline") and line.count("\t") == TABS_IN_LINE
    _, out, _ = run(capsys, "--root", str(hub_root), "show", "m:tabby")
    assert "## Claim\nTab here and newline" in out


def test_read_is_an_alias_of_show(hub_root, project, capsys):
    slug = put(project, "Attention needs care", body="Body text here.\n")
    _, shown, _ = run(capsys, "--root", str(hub_root), "show", f"m:{slug}")
    code, read, _ = run(capsys, "--root", str(hub_root), "read", f"m:{slug}")
    assert code == 0 and read == shown
    code, read, _ = run(capsys, "read", f"m:{slug}")
    assert code == 0 and read == shown


def test_document_listing_and_show_sources_line(project, capsys):
    put(project, "Vendor spec says X", kind="document")
    text = (
        (project / "vendor-spec-says-x.md")
        .read_text()
        .replace("status: active\n", "status: active\nsources:\n- a.pdf\n- https://example.org/b\n")
    )
    (project / "vendor-spec-says-x.md").write_text(text)
    assert mem.main(["search", "vendor", "--scope", "memories"]) == 0
    assert "[memory: document, observed 1, 2026-01-05]" in capsys.readouterr().out
    assert mem.main(["show", "m:vendor-spec-says-x"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (
        lines[1].startswith("kind: document")
        and lines[2] == "sources: a.pdf, https://example.org/b"
    )
