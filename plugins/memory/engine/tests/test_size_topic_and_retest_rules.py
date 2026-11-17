import pytest
import yaml

import mem
from test_find_new import write_note

MB5 = 5 * 1024 * 1024
SIZE_MSG = "file over 5 MB: keep it out of git and link it by https:// URL (spec 5.1)"


def sparse(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.truncate(size)


def test_rule_13_reports_file_over_limit(hub_root):
    sparse(hub_root / "research" / "big.bin", MB5 + 1)
    sparse(hub_root / "exact.bin", MB5)
    sparse(hub_root / "tools" / "__pycache__" / "x.bin", MB5 + 1)
    sparse(hub_root / ".hidden" / "x.bin", MB5 + 1)
    found = [p for p in mem.check(hub_root) if "5 MB" in p.message]
    assert [(p.path, p.line, p.message) for p in found] == [("research/big.bin", 1, SIZE_MSG)]


def test_rule_13_ignores_symlinks_and_broken_links(hub_root, tmp_path):
    big = tmp_path / "outside.bin"
    sparse(big, MB5 + 1)
    (hub_root / "link.bin").symlink_to(big)
    (hub_root / "broken.md").symlink_to(tmp_path / "missing")
    assert [p for p in mem.check(hub_root) if "5 MB" in p.message] == []


def test_reserved_topic_general(hub_root):
    (hub_root / "topics.yaml").write_text("general: {}\n", encoding="utf-8")
    found = [p for p in mem.check(hub_root) if p.path == "topics.yaml" and "reserved" in p.message]
    assert [(p.line, p.message) for p in found] == [(1, "topic id 'general' is reserved (it is the fallback "
                                                       "heading of domain indexes): rename it")]


def knowledge(root, name, topics, updated):
    write_note(root, f"knowledge/{name}.md",
               f"---\nclaim: C\ntopics: [{topics}]\nconfidence: low\norigin: experience\n"
               f"updated: {updated}\n---\n")


def retests(root, capsys, today="2027-11-07"):
    assert mem.main(["--root", str(root), "review", "--today", today]) == 0
    return [ln for ln in capsys.readouterr().out.splitlines() if "re-test" in ln]


def test_review_lists_stale_llm_notes(hub_root, capsys):
    (hub_root / "topics.yaml").write_text(
        (hub_root / "topics.yaml").read_text() + "prompt-engineering: {parent: llm}\n", encoding="utf-8")
    # today 2027-11-07: 366 days after 2026-11-06, 365 days after 2026-11-07
    knowledge(hub_root, "computing/old-llm", "llm", "2026-11-06")
    knowledge(hub_root, "computing/edge-llm", "llm", "2026-11-07")
    knowledge(hub_root, "computing/child-topic", "prompt-engineering", "2020-01-01")
    knowledge(hub_root, "biology/ancient-biology", "biology", "2000-01-01")
    knowledge(hub_root, "math/stats-for-llm-evals", "math, llm, deep-learning, ml, computing", "2020-01-01")
    suffix = "advice that depends on model behaviour ages (spec 5.4)"
    assert retests(hub_root, capsys) == [
        f"knowledge/computing/child-topic.md:1: re-test: updated 2020-01-01; {suffix}",
        f"knowledge/computing/old-llm.md:1: re-test: updated 2026-11-06; {suffix}"]


def test_loader_semantics_on_active_base():
    # Under a PyYAML with libyaml this runs on CSafeLoader (see tools/README.md, Tests).
    assert issubclass(mem.HubLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    assert mem.load_yaml("a: on\nb: yes\nd: 2026-11-07\n") == {"a": "on", "b": "yes", "d": "2026-11-07"}
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        mem.load_yaml("a: 1\na: 2\n")


def literature(root, name, kind, topics, added):
    write_note(root, f"literature/{name}.md",
               f"---\ntitle: T\nauthors: [Lee]\nyear: 2020\nkind: {kind}\nurl: https://x.org\n"
               f"topics: [{topics}]\nadded: {added}\n---\n")


def test_review_lists_old_llm_web_docs(hub_root, capsys):
    # today 2027-11-07: 183 days after 2027-05-08, 182 days after 2027-05-09
    literature(hub_root, "computing/2020-lee-old", "web", "llm", "2027-05-08")
    literature(hub_root, "computing/2020-lee-edge", "web", "llm", "2027-05-09")
    literature(hub_root, "computing/2020-lee-paper", "paper", "llm", "2020-01-01")
    literature(hub_root, "biology/2020-lee-bio", "web", "biology", "2020-01-01")
    assert mem.main(["--root", str(hub_root), "review", "--today", "2027-11-07"]) == 0
    out = [ln for ln in capsys.readouterr().out.splitlines() if "re-read" in ln]
    assert out == ["literature/computing/2020-lee-old.md:1: re-read: added 2027-05-08; "
                   "vendor documentation changes (spec 5.3)"]
