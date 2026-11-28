"""Render an application kit's interview-prep Markdown into phone-friendly PDF reading packets, a combined master
PDF, and an anonymized ("cleaned") copy of the master.

Usage:
  python engine/prep_pdf.py all      <kit> [--manifest FILE] [--browser PATH] [--data my-data]
  python engine/prep_pdf.py packets  <kit> ...      one PDF per packet in the manifest
  python engine/prep_pdf.py master   <kit> ...      the manifest's "master" packets combined, one document per page run
  python engine/prep_pdf.py cleaned  <kit> ...      the "cleaned" packets combined, anonymized with the kit's rules
  python engine/prep_pdf.py anonymize --rules FILE --in FILE --out FILE [--preamble FILE]

<kit> is a kit folder, or its name under 3-applications/. The Markdown in the kit is the source; the PDFs are
rebuilt from it after every edit, never edited by hand. Everything specific to one kit (file names, titles, the
subtitle, the reading order, the anonymization rules) lives in the kit, in a manifest (default <kit>/prep-pdf.json):

  {
    "out": "interviews/round1",                        output folder, relative to the kit
    "subtitle": "Company · Role · Round 1, Mon Jan 5",  shown under every packet's title
    "reading_order": ["Game plan (this file)", ...],    optional box on the packet marked "toc": true
    "packets": [
      {"source": "interview-prep.md", "parts": ["01 Game plan", "02 The panel"]},
          one packet per '# N. Title' part, named in order; master label "0N Title"
      {"source": "fit-map.md", "name": "07 Fit map", "title": "Fit map: requirements vs. your evidence",
       "label": "07 Fit map"},                          a whole file (its first '# ' line dropped)
      {"source": "interview-prep.md", "section": "Questions to ask", "name": "10 My questions to ask",
       "title": "My questions to ask (ranked)"},        one '## ' section (matched by its heading's start)
      {"source": "reading-list.md", ..., "optional": true}   skipped when the file is missing
    ],
    "master":  {"name": "master-prep-info", "subtitle": "...", "include": ["01 Game plan", ...]},
    "cleaned": {"name": "cleaned-master-prep-info", "subtitle": "...", "include": [...],
                "rules": "anonymize-rules.txt", "preamble": "anonymize-preamble.md"}
  }

"include" lists packet names; a packet's master heading is its "label" (default: its name). A packet with
"toc": true carries the reading-order box (default: the first packet).

Markdown subset: headings, paragraphs, bullets (one nested level), numbered lists, blockquotes, pipe tables
(two-column tables stay tables; wider ones become stacked cards, which read better on a phone), **bold**, *italic*,
`code`, ~~strike~~ and [links](url) (relative links are dropped to their text: they don't work on a phone).

Anonymization rules file: one rule per line, applied in order; blank lines and '#' lines are ignored.
  old text ==> new text          literal replacement (all occurrences); 'old text ==>' deletes it
  re: pattern ==> replacement    Python regex (re.M); use (?s) inline when a rule must span lines
  capitalize: phrase             after all rules, capitalize the phrase's first letter where it starts a sentence,
                                 line, table cell, bullet, quote, heading or bold run (e.g. 'the Client')
'\\n' in a replacement is a newline. Rules that matched nothing are reported, so stale rules show up when the prep
changes. The rules and the preamble stay in the kit (personal data never enters the engine).

Rendering prints HTML to PDF with headless Microsoft Edge or Chrome (--browser to choose another); the HTML is
written to a temporary folder outside the project.
"""
import argparse
import collections
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from paths import Paths

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
BROWSER_NAMES = ["msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"]
MANIFEST = "prep-pdf.json"


# ---------------------------------------------------------------- Markdown to HTML

def inline(s):
    s = html.escape(s, quote=False)

    def link(m):
        text, url = m.group(1), m.group(2)
        if url.startswith("http"):
            # The whole line was escaped above, so only the quote is left to escape here: escaping again turned
            # every "&" of a query string into "&amp;amp;" and broke the link.
            return f'<a href="{url.replace(chr(34), "&quot;")}">{text}</a>'
        return text  # relative project links don't work on a phone
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"~~(.+?)~~", r"<del>\1</del>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def table(rows):
    """Two-column tables with short cells stay tables; anything wider becomes one card per row (phone-friendly)."""
    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    if len(head) == 2 and body and max(len(c) for r in body for c in r) < 400:
        out = ['<table><tr>' + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr>"]
        out += ['<tr>' + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body]
        return "\n".join(out) + "</table>"
    out = []
    for r in body:
        r = r + [""] * (len(head) - len(r))
        lines = [f'<div class="card-title">{inline(r[0])}</div>']
        for h, c in zip(head[1:], r[1:]):
            if c:
                lines.append(f'<div class="card-row"><span class="lab">{inline(h)}</span> {inline(c)}</div>')
        out.append('<div class="card">' + "".join(lines) + "</div>")
    return "\n".join(out)


LIST_ITEM = r"^(\s*)([-*]|\d+\.)\s+(.*)"


def convert(md):
    lines = md.splitlines()
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", ln)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
            i += 1
            continue
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.append(table(lines[i:j]))
            i = j
            continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i][1:].lstrip())
                i += 1
            out.append("<blockquote>" + convert("\n".join(buf)) + "</blockquote>")
            continue
        m = re.match(LIST_ITEM, ln)
        if m and len(m.group(1)) < 2:
            ordered = m.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                l2 = lines[i]
                mm = re.match(LIST_ITEM, l2)
                if mm and len(mm.group(1)) < 2:
                    items.append({"text": mm.group(3), "sub": [], "more": []})
                elif mm and items:
                    items[-1]["sub"].append(mm.group(3))
                elif l2.startswith("  ") and l2.strip() and items:
                    items[-1]["more"].append(l2.strip())
                elif (not l2.strip() and i + 1 < len(lines) and items
                      and re.match(r"^(\s{2,}\S|\s*([-*]|\d+\.)\s)", lines[i + 1])):
                    pass  # a blank line inside a list that continues
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            h = [f"<{tag}>"]
            for it in items:
                s = f"<li>{inline(it['text'])}"
                for mo in it["more"]:
                    s += (f"<blockquote>{inline(mo[1:].strip())}</blockquote>" if mo.startswith(">")
                          else f"<p>{inline(mo)}</p>")
                if it["sub"]:
                    s += "<ul>" + "".join(f"<li>{inline(x)}</li>" for x in it["sub"]) + "</ul>"
                h.append(s + "</li>")
            out.append("".join(h) + f"</{tag}>")
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|>|\s*\||\s*([-*]|\d+\.)\s)", lines[i]):
            buf.append(lines[i].strip())
            i += 1
        if not buf:
            buf.append(lines[i].strip())
            i += 1
        out.append(f"<p>{inline(' '.join(buf))}</p>")
    return "\n".join(out)


CSS = """
@page { size: 5.5in 8.5in; margin: 0.45in 0.4in 0.5in 0.4in; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.42; color: #1d1d1f; }
h1 { font-size: 17pt; margin: 0 0 4pt; color: #0b3d6b; }
.sub { color: #555; font-size: 9pt; margin-bottom: 10pt; }
h2 { font-size: 13pt; color: #0b3d6b; border-bottom: 1.5px solid #0b3d6b; padding-bottom: 2pt; margin: 16pt 0 6pt; break-after: avoid; }
h3, h4 { font-size: 11pt; margin: 10pt 0 4pt; break-after: avoid; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt; padding-left: 16pt; }
li { margin-bottom: 3pt; }
li p { margin: 3pt 0; }
blockquote { margin: 6pt 0; padding: 5pt 8pt; background: #eef4fa; border-left: 3px solid #0b3d6b; }
blockquote p { margin: 0 0 3pt; }
code { font-family: Consolas, monospace; font-size: 9pt; background: #f2f2f2; padding: 0 2px; }
a { color: #0b5cad; text-decoration: none; word-break: break-word; }
del { color: #888; }
.card { border: 1px solid #c9d6e3; border-radius: 5px; padding: 5pt 7pt; margin: 0 0 6pt; }
.card-title { font-weight: 600; margin-bottom: 3pt; color: #0b3d6b; break-after: avoid; }
.card-row { margin: 2pt 0; orphans: 2; widows: 2; }
.lab { font-weight: 600; color: #444; font-size: 9pt; text-transform: uppercase; letter-spacing: .02em; display: block; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 0 0 8pt; font-size: 9.5pt; }
th, td { border: 1px solid #c9d6e3; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef4fa; }
.toc { background: #f6f8fa; border: 1px solid #dde3ea; padding: 6pt 9pt; border-radius: 5px; margin-bottom: 10pt; }
"""


def page_html(title, subtitle, body, extra_css=""):
    head = f"<h1>{html.escape(title)}</h1><div class='sub'>{html.escape(subtitle)}</div>"
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{CSS}{extra_css}</style></head><body>{head}{body}</body></html>")


def toc_box(heading, items):
    return f"<div class='toc'><strong>{html.escape(heading)}</strong><br>" + "<br>".join(items) + "</div>"


# ---------------------------------------------------------------- reading the kit

def drop_title(text):
    """A whole-file packet: drop the file's own '# ' title line (the packet supplies its title)."""
    return re.sub(r"(?m)\A# .*\n", "", text)


def split_parts(text):
    """'# N. Title' parts -> [(N, Title, body)]. Text before the first '# ' line is ignored."""
    out = []
    for p in re.split(r"(?m)^# ", text)[1:]:
        title, _, body = p.partition("\n")
        num, dot, name = title.partition(".")
        if not dot or not num.strip().isdigit():
            raise SystemExit(f"Expected a numbered part ('# 1. Title'), got '# {title.strip()}'")
        out.append((int(num), name.strip(), body))
    return out


def section(text, heading):
    """The body of the first '## ' section whose heading starts with `heading`, up to the next '## ' or '# '."""
    m = re.search(rf"(?m)^## {re.escape(heading)}.*\n", text)
    if not m:
        raise SystemExit(f"No '## {heading}' section found")
    rest = text[m.end():]
    end = re.search(r"(?m)^#{1,2} ", rest)
    return rest[:end.start()] if end else rest


def load_manifest(kit, manifest=None):
    path = Path(manifest) if manifest else kit / MANIFEST
    if not path.exists():
        raise SystemExit(f"No manifest at {path}. See the docstring of engine/prep_pdf.py for its format.")
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path.name} isn't valid JSON: {e}")
    if not isinstance(m, dict):
        raise SystemExit(f"{path.name} must be a JSON object (see the docstring of engine/prep_pdf.py for its format)")
    # Deliberate (code reviews, 2026-11-25 and 2026-11-27): 'source' and 'out' are not confined to the kit folder.
    # The manifest is the user's own file, and pointing it at shared material elsewhere in the data folder is a use.
    if not isinstance(m.get("packets"), list) or not m["packets"]:
        raise SystemExit(f"{path.name} needs a non-empty 'packets' list")
    return m


def packets(kit, m):
    """The manifest's packets as dicts: name (PDF file stem), title (shown), label (master heading), md, toc."""
    out, cache = [], {}

    def read(src):
        if src not in cache:
            cache[src] = (kit / src).read_text(encoding="utf-8-sig")
        return cache[src]
    for spec in m["packets"]:
        src = spec.get("source")
        if not src:
            raise SystemExit(f"A packet has no 'source': {spec}")
        if not (kit / src).exists():
            if spec.get("optional"):
                continue
            raise SystemExit(f"Packet source not found: {kit / src}")
        if "parts" in spec:
            parts = split_parts(read(src))
            names = spec["parts"]
            if len(names) != len(parts):
                raise SystemExit(f"{src} has {len(parts)} parts but the manifest names {len(names)}")
            for name, (num, title, body) in zip(names, parts):
                out.append({"name": name, "title": title, "label": f"{num:02d} {title}", "md": body,
                            "toc": False})
            continue
        md = section(read(src), spec["section"]) if spec.get("section") else drop_title(read(src))
        name = spec.get("name") or Path(src).stem
        out.append({"name": name, "title": spec.get("title", name), "label": spec.get("label", name), "md": md,
                    "toc": bool(spec.get("toc"))})
    # A packet's name is its PDF's file name: two packets with one name would write the same file twice, each
    # reported as done, and the first packet's PDF would be gone.
    seen = collections.Counter(p["name"] for p in out)
    twice = sorted(n for n, c in seen.items() if c > 1)
    if twice:
        raise SystemExit(f"The manifest has several packets named {', '.join(twice)}: give each its own \"name\" "
                         f"(two sections of one source file both default to the file's name).")
    if out and m.get("reading_order") and not any(p["toc"] for p in out):
        out[0]["toc"] = True
    return out


def pick(pk, include, what):
    by = {p["name"]: p for p in pk}
    missing = [n for n in include if n not in by]
    if missing:
        raise SystemExit(f"'{what}' includes packets that don't exist: {', '.join(missing)}")
    return [by[n] for n in include]


def compose(docs):
    """Combined Markdown: one '# label' heading per document (the form the anonymizer works on)."""
    return "\n".join(f"# {p['label']}\n{p['md'].strip()}\n" for p in docs)


def combined_html(md, title, subtitle):
    docs = [p.split("\n", 1) + [""] for p in re.split(r"(?m)^# ", md)[1:]]
    toc = toc_box("Contents", [html.escape(t.strip()) for t, *_ in docs])
    body = toc + "".join(f"<h1 class='doc'>{html.escape(t.strip())}</h1>" + convert(b) for t, b, *_ in docs)
    return page_html(title, subtitle, body, "\nh1.doc { break-before: page; }\n")


# ---------------------------------------------------------------- anonymizing

CAP_START = r"(^|[.!?][\"”*]*\s+|\|\s+|^\s*[-*]\s+|\*\*|^\d+\.\s+|>\s+|(?<![\w,;] )[\"“]|^#+\s+\d*\s*)"


def parse_rules(rules_text):
    """-> (rules, capitalize): rules are (line number, kind, old, new); kind is 're' or 'lit'."""
    rules, caps = [], []
    for n, line in enumerate(rules_text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("capitalize: "):
            caps.append(line[len("capitalize: "):].strip())
            continue
        old, new = (line.split(" ==> ", 1) if " ==> " in line else (line.rsplit(" ==>", 1)[0], ""))
        new = new.replace("\\n", "\n")
        rules.append((n, "re", old[4:], new) if old.startswith("re: ") else (n, "lit", old, new))
    return rules, caps


def anonymize(text, rules_text):
    """Apply the rules in order, then the capitalize pass. Returns (text, unused rule descriptions)."""
    rules, caps = parse_rules(rules_text)
    unused = []
    for n, kind, old, new in rules:
        if kind == "re":
            try:
                text, k = re.subn(old, new, text, flags=re.M)
            except re.error as e:
                raise SystemExit(f"Rule on line {n} isn't a valid regex: {e}")
        else:
            k = text.count(old)
            text = text.replace(old, new)
        if k == 0:
            unused.append(f"line {n}: {('re: ' if kind == 're' else '') + old[:70]}")
    if caps:
        alt = "|".join(re.escape(c) for c in sorted(caps, key=len, reverse=True))
        # (?!\w): the whole phrase only, so "the Client" never capitalizes "the Clientele"
        text = re.sub(CAP_START + rf"({alt})(?!\w)", lambda m: m.group(1) + m.group(2)[0].upper() + m.group(2)[1:],
                      text, flags=re.M)
    return text, unused


# ---------------------------------------------------------------- printing

def find_browser(override=None):
    if override:
        if not Path(override).exists() and not shutil.which(override):
            raise SystemExit(f"Browser not found: {override}")
        return shutil.which(override) or override
    for b in BROWSERS:
        if Path(b).exists():
            return b
    for name in BROWSER_NAMES:
        if shutil.which(name):
            return shutil.which(name)
    raise SystemExit("No Edge or Chrome found to print PDFs; pass --browser <path>.")


def print_pdf(browser, page, pdf, timeout=180):
    """Print an HTML page to `pdf` with a headless browser. The path is made absolute: Edge silently writes nothing
    for a relative --print-to-pdf path on Windows."""
    pdf = Path(pdf).resolve()
    pdf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        src = tmp / "page.html"
        src.write_text(page, encoding="utf-8")
        out = tmp / "out.pdf"
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                        f"--user-data-dir={tmp / 'profile'}", f"--print-to-pdf={out}", src.as_uri()],
                       capture_output=True, timeout=timeout)
        # On Windows the Edge launcher can return before the headless process writes the file: wait for it.
        for _ in range(timeout * 2):
            if out.exists() and out.stat().st_size > 0:
                time.sleep(0.5)  # let the write finish
                break
            time.sleep(0.5)
        if not out.exists() or out.stat().st_size == 0:
            raise SystemExit(f"The browser did not write {pdf.name}")
        # Copy next to the destination first, then swap it in with one os.replace: if the copy fails, the
        # previous PDF is still there.
        part = pdf.with_name(pdf.name + ".part")
        try:
            shutil.copyfile(str(out), str(part))
            os.replace(str(part), str(pdf))  # fails on Windows if a viewer holds the PDF open: the old one stays
        finally:
            if part.exists():
                part.unlink()
    print(f"OK  {pdf.name}  ({pdf.stat().st_size:,} bytes)")
    return pdf


# ---------------------------------------------------------------- commands

def build_packets(kit, m, browser, out):
    pk = packets(kit, m)
    sub = m.get("subtitle", "")
    order = m.get("reading_order") or []
    for p in pk:
        intro = toc_box("Reading order", [f"{i}. {html.escape(t)}" for i, t in enumerate(order, 1)]) \
            if p["toc"] and order else ""
        print_pdf(browser, page_html(p["title"], sub, intro + convert(p["md"])), out / f"{p['name']}.pdf")


def build_master(kit, m, browser, out):
    cfg = m.get("master")
    if not cfg:
        raise SystemExit("The manifest has no 'master' section")
    md = compose(pick(packets(kit, m), cfg["include"], "master"))
    name = cfg.get("name", "master-prep-info")
    print_pdf(browser, combined_html(md, name, cfg.get("subtitle", m.get("subtitle", ""))), out / f"{name}.pdf")


def cleaned_markdown(kit, m):
    cfg = m.get("cleaned")
    if not cfg:
        raise SystemExit("The manifest has no 'cleaned' section")
    md = compose(pick(packets(kit, m), cfg["include"], "cleaned"))
    rules = kit / cfg.get("rules", "anonymize-rules.txt")
    if not rules.exists():
        raise SystemExit(f"Rules file not found: {rules}")
    md, unused = anonymize(md, rules.read_text(encoding="utf-8-sig"))
    if cfg.get("preamble"):
        md = (kit / cfg["preamble"]).read_text(encoding="utf-8-sig").rstrip() + "\n\n" + md
    return md, unused


def build_cleaned(kit, m, browser, out):
    cfg = m.get("cleaned") or {}
    md, unused = cleaned_markdown(kit, m)
    print(f"rules that matched nothing: {len(unused)}")
    for u in unused:
        print("   ", u)
    name = cfg.get("name", "cleaned-master-prep-info")
    print_pdf(browser, combined_html(md, name, cfg.get("subtitle", "")), out / f"{name}.pdf")


def resolve_kit(P, kit):
    k = Path(kit)
    if k.is_dir():
        return k.resolve()
    if (P.applications / kit).is_dir():
        return (P.applications / kit).resolve()
    raise SystemExit(f"Kit not found: {kit} (a folder, or a name under {P.applications})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("all", "packets", "master", "cleaned"):
        s = sub.add_parser(c)
        s.add_argument("kit")
        s.add_argument("--manifest", default=None)
        s.add_argument("--browser", default=None)
        s.add_argument("--data", default=None)
    a = sub.add_parser("anonymize")
    a.add_argument("--rules", required=True)
    a.add_argument("--in", dest="inp", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--preamble", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "anonymize":
        text, unused = anonymize(Path(args.inp).read_text(encoding="utf-8-sig"),
                                 Path(args.rules).read_text(encoding="utf-8-sig"))
        if args.preamble:
            text = Path(args.preamble).read_text(encoding="utf-8-sig").rstrip() + "\n\n" + text
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"rules that matched nothing: {len(unused)}")
        for u in unused:
            print("   ", u)
        return

    P = Paths(args.data)
    kit = resolve_kit(P, args.kit)
    m = load_manifest(kit, args.manifest)
    out = kit / m.get("out", ".")
    browser = find_browser(args.browser)
    if args.cmd in ("all", "packets"):
        build_packets(kit, m, browser, out)
    if args.cmd in ("all", "master") and (args.cmd == "master" or m.get("master")):
        build_master(kit, m, browser, out)
    if args.cmd in ("all", "cleaned") and (args.cmd == "cleaned" or m.get("cleaned")):
        build_cleaned(kit, m, browser, out)


if __name__ == "__main__":
    sys.exit(main())
