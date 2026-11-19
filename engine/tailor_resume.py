"""Make a tailored copy of a resume .docx with Word tracked changes (author "Claude").

Usage:  python engine/tailor_resume.py <source.docx> <output.docx> <edits.json>

edits.json is a list of edits, each [find, before, deleted, inserted, after]:
  find      text that appears inside one Word run (used to locate it)
  before    text kept before the change ("*" = everything in the run before `find`)
  deleted   text shown as a tracked deletion ("" for a pure insertion)
  inserted  text shown as a tracked insertion ("" for a pure deletion)
  after     text kept after the change ("*" = the rest of the run)
before + deleted + after must equal the run's text exactly (XML-escaped, e.g. "&amp;").
Why only `inserted` is escaped: before, deleted and after are pieces of the run's existing XML text, which Word has
already escaped, and the equality check above guarantees they are exactly that; escaping them again would turn
"&amp;" into "&amp;amp;". `inserted` is new text, so it is escaped. The edited XML is parsed before writing.

The source file is never modified. Check the output in Word afterwards: revisions count,
one page with all changes accepted (Word COM: Revisions.Count, AcceptAllRevisions, ComputeStatistics(2)).
Handles runs saved by Word with attributes (e.g. <w:r w:rsidR=...>).
"""
import datetime as dt
import json
import re
import sys
import zipfile
from xml.sax.saxutils import escape

# A run with optional formatting (<w:rPr>), then its text. Runs without formatting are valid Word and common.
RUN = re.compile(r"<w:r(?: [^>]*)?>(<w:rPr>(?:(?!</w:rPr>|<w:r[ >]).)*</w:rPr>)?"
                 r"<w:t(?: xml:space=\"preserve\")?>([^<]*)</w:t></w:r>")


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, dst, edits_file = sys.argv[1:4]
    from pathlib import Path
    if Path(src).resolve() == Path(dst).resolve():
        sys.exit("The output must be a new file: the source resume is never modified.")
    if Path(dst).exists():
        sys.exit(f"{dst} already exists; choose a new name (earlier drafts are never overwritten).")
    if not Path(dst).resolve().parent.is_dir():
        sys.exit(f"The output folder {Path(dst).resolve().parent} is missing; create it (or pick an existing "
                 f"folder) and rerun.")
    zin = zipfile.ZipFile(src)
    x = zin.read("word/document.xml").decode("utf-8")
    stamp = f'w:author="Claude" w:date="{dt.date.today().isoformat()}T00:00:00Z"'
    ids = [9000]

    def nid():
        ids[0] += 1
        return ids[0]

    for find, before, deleted, inserted, after in json.load(open(edits_file, encoding="utf-8")):
        m = next((mm for mm in RUN.finditer(x) if find in mm.group(2)), None)
        if not m:
            sys.exit(f"Not found in any single run: {find!r}")
        rpr, text = m.group(1) or "", m.group(2)
        if before == "*":
            before = text[:text.index(find)]
        if after == "*":
            after = text[len(before) + len(deleted):]
        if before + deleted + after != text:
            sys.exit(f"Edit doesn't match the run text.\n  run:  {text!r}\n  edit: {before!r} + {deleted!r} + {after!r}")

        def run(t):
            return f'<w:r>{rpr}<w:t xml:space="preserve">{t}</w:t></w:r>' if t else ""

        out = run(before)
        if deleted:
            out += (f'<w:del w:id="{nid()}" {stamp}><w:r>{rpr}'
                    f'<w:delText xml:space="preserve">{deleted}</w:delText></w:r></w:del>')
        if inserted:
            out += (f'<w:ins w:id="{nid()}" {stamp}><w:r>{rpr}'
                    f'<w:t xml:space="preserve">{escape(inserted)}</w:t></w:r></w:ins>')
        out += run(after)
        x = x[:m.start()] + out + x[m.end():]

    # The edited XML must still parse before anything is written: a malformed result never reaches the output.
    from xml.dom.minidom import parseString
    from xml.parsers.expat import ExpatError
    try:
        parseString(x.encode("utf-8"))
    except ExpatError as e:
        sys.exit(f"The edited document.xml isn't well-formed ({e}); nothing was written. Check the edits.")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, x.encode("utf-8") if item.filename == "word/document.xml" else zin.read(item.filename))
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
