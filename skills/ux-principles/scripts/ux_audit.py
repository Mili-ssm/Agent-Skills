#!/usr/bin/env python3
"""Capture UX evidence for one or more URLs with Playwright.

For every URL x viewport it writes to --out:
  - <slug>_<WxH>.png        full-page screenshot
  - <slug>_<WxH>_axe.json   axe-core violations (WCAG 2.x A/AA + best practices)
  - <slug>_focus.json       keyboard focus order (first --tabs Tab presses, first viewport only)
and prints a compact summary table so the calling agent does not need to open the JSON files.

Usage:
  python3 ux_audit.py http://localhost:8000/ [more URLs] --out ux-audit \
      --viewports 375x812,1440x900 --tabs 25 [--axe-path ./axe.min.js] [--executable-path /opt/pw-browsers/chromium]

Requires: Python Playwright with Chromium (`pip install playwright` + browser).
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# Pinned axe-core release served from jsDelivr; override with --axe-path when offline.
AXE_CDN = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"
# Rule tags passed to axe.run: WCAG 2.0/2.1/2.2 levels A and AA plus best practices.
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]

# JS executed in the page to describe the element that currently has focus.
FOCUS_JS = """() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const r = el.getBoundingClientRect();
  const style = getComputedStyle(el);
  return {
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role'),
    name: (el.getAttribute('aria-label') || el.innerText || el.value || el.getAttribute('title') || '').trim().slice(0, 60),
    id: el.id || null,
    size: [Math.round(r.width), Math.round(r.height)],
    // A focus indicator is likely present if an outline or box-shadow is drawn.
    focus_indicator: style.outlineStyle !== 'none' && style.outlineWidth !== '0px' || style.boxShadow !== 'none'
  };
}"""


def slugify(url: str) -> str:
    """Turn a URL into a filesystem-safe name (scheme stripped, separators collapsed)."""
    slug = re.sub(r"^https?://", "", url)
    return re.sub(r"[^A-Za-z0-9]+", "_", slug).strip("_")[:80] or "page"


def parse_viewports(spec: str) -> list[tuple[int, int]]:
    """Parse '375x812,1440x900' into [(375, 812), (1440, 900)]."""
    return [tuple(int(n) for n in part.lower().split("x")) for part in spec.split(",")]  # type: ignore[misc]


def run_axe(page: Page, axe_path: str | None) -> list[dict]:
    """Inject axe-core and return its violations, reduced to the fields useful for a report."""
    if axe_path:
        page.add_script_tag(path=axe_path)
    else:
        page.add_script_tag(url=AXE_CDN)
    result = page.evaluate("tags => axe.run(document, {runOnly: {type: 'tag', values: tags}})", AXE_TAGS)
    return [
        {
            "id": v["id"],
            "impact": v["impact"],
            "help": v["help"],
            "count": len(v["nodes"]),
            # Keep a few CSS targets so the agent can locate the offending elements.
            "targets": [n["target"] for n in v["nodes"][:5]],
        }
        for v in result["violations"]
    ]


def focus_order(page: Page, tabs: int) -> list[dict | None]:
    """Press Tab repeatedly and record which element receives focus each time."""
    page.locator("body").click(position={"x": 1, "y": 1})  # start from the document, not the URL bar
    order = []
    for _ in range(tabs):
        page.keyboard.press("Tab")
        order.append(page.evaluate(FOCUS_JS))
    return order


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--out", default="ux-audit")
    parser.add_argument("--viewports", default="375x812,1440x900")
    parser.add_argument("--tabs", type=int, default=25)
    parser.add_argument("--axe-path", default=None, help="local axe.min.js instead of the CDN")
    # Pre-installed Chromium whose version differs from the pip Playwright build (common in cloud images).
    parser.add_argument("--executable-path", default=os.environ.get("PW_CHROMIUM_PATH"),
                        help="Chromium binary to launch (default: $PW_CHROMIUM_PATH or Playwright's own)")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    viewports = parse_viewports(args.viewports)
    rows = []  # summary rows: (url, viewport, violations, serious+critical)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.executable_path)
        for url in args.urls:
            slug = slugify(url)
            for i, (w, h) in enumerate(viewports):
                page = browser.new_page(viewport={"width": w, "height": h})
                page.goto(url, wait_until="load")
                page.screenshot(path=out / f"{slug}_{w}x{h}.png", full_page=True)
                violations = run_axe(page, args.axe_path)
                (out / f"{slug}_{w}x{h}_axe.json").write_text(json.dumps(violations, indent=2))
                severe = sum(1 for v in violations if v["impact"] in ("serious", "critical"))
                rows.append((url, f"{w}x{h}", len(violations), severe))
                # Focus order does not depend on width in most layouts: capture it once per URL.
                if i == 0 and args.tabs > 0:
                    order = focus_order(page, args.tabs)
                    (out / f"{slug}_focus.json").write_text(json.dumps(order, indent=2))
                    missing = sum(1 for f in order if f and not f["focus_indicator"])
                    print(f"focus {url}: {sum(1 for f in order if f)} stops, {missing} without visible indicator")
                page.close()
        browser.close()

    print("| URL | Viewport | axe violations | serious+critical |")
    print("|---|---|---|---|")
    for url, vp, total, severe in rows:
        print(f"| {url} | {vp} | {total} | {severe} |")
    print(f"evidence: {out.resolve()}")


if __name__ == "__main__":
    main()
