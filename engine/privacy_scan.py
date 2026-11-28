"""Privacy scan: make sure shareable files hold none of the user's personal details before they leave the machine.

Usage:
  python engine/privacy_scan.py [PATH ...] [--terms FILE] [--strict]   # default: engine/ (exit 1 on any hit)

What it looks for:
  - every term in a private-terms list (one per line, case-insensitive; # starts a comment): the user's name,
    home town, employers, contacts, accounts. The list never goes in the repo. It is found, in order, at:
    --terms FILE, the PRIVATE_TERMS environment variable, or <data>/private-terms.txt. --strict fails when
    no list is found or the list is empty (the pre-commit hook uses it).
    A term is found with or without accents, with its words joined by anything but letters and digits (First Last,
    first-last, First_Last, firstlast), wrapped over a line break, and behind JSON escapes, URL encoding and HTML
    entities (%22Name%22 in a search link, \\nName in a job record). It is not found inside a longer word.
  - the same terms and patterns in every file's own path: file and folder names are public too.
  - patterns that leak whatever the list misses: Windows home-folder paths (with backslashes, forward slashes or
    JSON-escaped backslashes), macOS or Linux home-folder paths, email addresses, LinkedIn profile links.
  - files it can't read: an image counts as a hit until it has been checked by eye and listed in the allow file
    ("<path> | image checked by eye"); an archive or unknown binary is always a hit.
A line marked "privacy-scan: ignore" is skipped only inside privacy_scan.py itself (its own pattern
definitions); anywhere else the marker does nothing.
Deliberate exceptions (e.g. the author's name in LICENSE) go in an allow file, one per line: "<path> | <phrase>",
paths relative to the folder being scanned. The phrase is removed from that file's lines before checking, so every
other term in the same line is still caught. Default: .privacy-allow in the folder being scanned; --allow FILE
overrides it (the pre-commit hook passes the staged copy).
Run it on the engine after every change meant for the public repo, and on the whole repo before every push.
"""
import argparse
import html
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote_plus

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT, Paths  # noqa: E402

IGNORE = "privacy-scan: " + "ignore"  # split so this line itself is still scanned
PATTERNS = {
    # A Windows home folder in any case, with one or more backslashes (JSON inside JSON doubles them twice), a
    # forward slash, or an administrative share name; then a macOS, Linux or Git Bash home folder, which needs no
    # trailing slash but must not be the tail of a web address (a site's own "home" page path).
    "home-folder path": r"(?i:[a-z][:$](?:\\+|/)users(?:\\+|/)[^\\/\s\"]+)|(?<![\w.-])/(?:[A-Za-z]/)?(?:Users|home)/[^/\s\"'`<>)]+",  # privacy-scan: ignore
    # The example domains (.com, .org, .net) are for examples, but only as the whole domain: an address at a
    # longer domain that merely starts with one is real.
    "email address": r"\b[\w.+-]+@(?!example\.(?:com|org|net)(?![\w-]|\.[\w-]))[\w-]+\.[\w.]+\b",  # privacy-scan: ignore
    "LinkedIn profile link": r"(?i:linkedin\.com/in/[\w-]+)",  # privacy-scan: ignore
}
TEXT = {".py", ".md", ".json", ".txt", ".html", ".svg", ".toml", ".cfg", ".yml", ".yaml", ".csv", ".tsv", ".xml",
        ".ini", ".sh", ".ps1", ".bat", ".gitignore", ".gitattributes", ""}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"}
MIN_PHRASE = 3  # shortest phrase an allow-file line may allow
IMAGE_OK = "image checked by eye"
SKIP_DIRS = {"__pycache__", ".git"}  # archive/ folders are scanned too: old reports hold the same details


def terms_file(P, given=None):
    for cand in (given, os.environ.get("PRIVATE_TERMS"), P.data / "private-terms.txt"):
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def terms(f):
    if not f:
        return []
    out = []
    # utf-8-sig: a byte-order mark (Windows PowerShell and some editors write one) would otherwise stick to the
    # first term, which then never matches.
    for line in f.read_text(encoding="utf-8-sig").splitlines():
        t = line.split("#", 1)[0].strip()
        if t:
            out.append(t)
    return out


def plain(s):
    """Text with accents dropped ('José' -> 'Jose'), so a term matches with or without them."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


ESCAPES = re.compile(r"\\u([0-9a-fA-F]{4})|\\[nrt]")


def decoded(s):
    """A line as a reader or a browser would see it: JSON escapes (\\n, \\t, \\uXXXX), URL encoding (%22, %20, +)
    and HTML entities (&nbsp;) resolved, and look-alike characters (non-breaking space) made plain. Files the engine
    writes hold terms in these forms: a search link carries the company as %22Name%22, and a job record's text
    carries a line break as \\n right before the next word."""
    s = ESCAPES.sub(lambda m: chr(int(m.group(1), 16)) if m.group(1) else " ", s)
    s = html.unescape(unquote_plus(s))
    return unicodedata.normalize("NFKC", s)


def term_rx(term):
    """A private term as a pattern: its words in order with anything but letters and digits between them (spaces,
    '-', '_', nothing at all), so 'First Last' also matches first-last, First_Last and firstlast. The term must not
    sit inside a longer word, but digits and underscores may touch it (Name_Resume.pdf, name2026)."""
    words = re.findall(r"[^\W_]+", plain(term))
    body = r"[\W_]*".join(map(re.escape, words)) if words else re.escape(term)
    return re.compile(rf"(?<![^\W\d_]){body}(?![^\W\d_])", re.I), len(words) > 1


def line_hits(line, term_rxs, pattern_rxs):
    """Names of everything found in one line (or one file path), checked as written and decoded."""
    forms = {line, decoded(line)}
    plains = {plain(x) for x in forms}
    found = [name for name, r, _ in term_rxs if any(r.search(x) for x in plains)]
    return found + [name for name, r in pattern_rxs if any(r.search(x) for x in forms)]


def allowed(f):
    """{relative path: [phrases]} from an allow file ('<path> | <phrase>' per line; # comments)."""
    out = {}
    if f and Path(f).is_file():
        for line in Path(f).read_text(encoding="utf-8-sig").splitlines():
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                path, phrase = (x.strip() for x in line.split("|", 1))
                # A phrase is removed from the file's lines before they are checked, so an empty or one-letter
                # phrase would blank out every line and switch the scan off for that file: such a line is ignored.
                if len(phrase) < MIN_PHRASE:
                    print(f"{Path(f).name}: ignored the line for {path!r}: its phrase is shorter than "
                          f"{MIN_PHRASE} characters")
                    continue
                out.setdefault(path.replace("\\", "/"), []).append(phrase)
    return out


def read_text(f):
    """A file's text, or None when it isn't text. Every file is checked, whatever its extension: UTF-16 with a
    byte-order mark is decoded; any other file with NUL bytes isn't text; known text types are read as UTF-8;
    anything else counts as text only if it decodes as UTF-8, so an archive or other binary can't slip past the scan
    just because its extension isn't listed."""
    data = f.read_bytes()
    # UTF-16 text (with its byte-order mark) is decoded properly; read as UTF-8 its letters are split by NUL bytes
    # and no term would match.
    # UTF-32 first: its little-endian mark starts with UTF-16's, and read as UTF-16 the text is letters split by
    # NULs, which no term matches.
    for marks, codec in (((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"), "utf-32"), ((b"\xff\xfe", b"\xfe\xff"), "utf-16")):
        if data.startswith(marks):
            try:
                text = data.decode(codec)
            except UnicodeDecodeError:
                return None
            return None if "\0" in text else text  # NULs left after decoding: not readable text (a hit)
    if b"\0" in data:  # NUL bytes without a BOM: not readable text, whatever the extension (a hit)
        return None
    if f.suffix.lower() in TEXT:
        return data.decode("utf-8", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(paths, words, allow_file=None, skip=True):
    term_rxs = [(f"private term '{w}'", *term_rx(w)) for w in words]
    pattern_rxs = [(name, re.compile(p)) for name, p in PATTERNS.items()]
    hits = 0
    for root in paths:
        allow = allowed(allow_file or (root / ".privacy-allow" if root.is_dir() else None))
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            rel = f.relative_to(root).as_posix() if root.is_dir() else f.name
            # Only folders inside the scanned folder are skipped, by name: a parent folder called .git, or a file
            # called __pycache__, switches nothing off. The pre-commit hook skips nothing at all (skip=False).
            if skip and SKIP_DIRS & set(rel.split("/")[:-1]):
                continue
            shown = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
            if rel == ".privacy-allow":
                # The exceptions list names the terms it allows, so terms aren't checked in it; paths, email
                # addresses and profile links have no reason to be there and are.
                for n, line in enumerate((read_text(f) or "").splitlines(), 1):
                    for name in line_hits(line, [], pattern_rxs):
                        hits += 1
                        print(f"{shown}:{n}: {name}: {line.strip()[:120]}")
                continue

            def unallowed(s):
                for phrase in allow.get(rel, []):
                    s = re.sub(re.escape(phrase), " ", s, flags=re.I)
                return s
            # The file's own path is public too (kit folders and recommendation folders are named after employers
            # and people), so it is checked like a line of text.
            for name in line_hits(unallowed(rel), term_rxs, pattern_rxs):
                hits += 1
                print(f"{shown}: file name: {name}")
            text = read_text(f)
            if text is None:  # not text: the scan can't read it, so it counts as a hit unless deliberately allowed
                if f.suffix.lower() in IMAGES:
                    # Listed in .privacy-allow after a look by eye, with that exact phrase: a line allowing some
                    # other phrase in the file's name doesn't vouch for the picture.
                    if IMAGE_OK in [p.lower() for p in allow.get(rel, [])]:
                        print(f"{shown}: image, allowed in .privacy-allow (checked by eye)")
                    else:
                        hits += 1
                        print(f"{shown}: image the scan can't read: check it by eye for names, paths or screenshots "
                              f"of personal data, then list it in .privacy-allow as '{rel} | image checked by eye'")
                else:
                    hits += 1
                    print(f"{shown}: binary file the scan can't read (archive or unknown format): keep it out of "
                          f"shareable folders")
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if IGNORE in line and f.name == "privacy_scan.py":  # only the scanner's own pattern lines
                    continue
                line = unallowed(line)
                for name in line_hits(line, term_rxs, pattern_rxs):
                    hits += 1
                    print(f"{shown}:{n}: {name}: {line.strip()[:120]}")
            # A term of several words wrapped over a line break ("First" ending one line, "Last" starting the next).
            whole = plain(unallowed(text))
            for name, r, several in term_rxs:
                for m in (r.finditer(whole) if several else ()):
                    if "\n" in m.group(0):
                        hits += 1
                        print(f"{shown}:{whole.count(chr(10), 0, m.start()) + 1}: {name} (across a line break)")
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--data", default=None)
    ap.add_argument("--terms", help="private-terms list (kept outside the repo)")
    ap.add_argument("--strict", action="store_true", help="fail when no private-terms list is found")
    ap.add_argument("--allow", help="allow file of deliberate exceptions (default: <folder>/.privacy-allow)")
    ap.add_argument("--no-skip", action="store_true",
                    help="scan every file, including __pycache__ and .git folders (the pre-commit hook uses it)")
    a = ap.parse_args()
    P = Paths(a.data)
    f = terms_file(P, a.terms)
    words = terms(f)
    if not f:
        if a.strict:
            print("No private-terms list found (--terms, PRIVATE_TERMS, or <data>/private-terms.txt): "
                  "refusing to pass. Point to the list and try again.")
            sys.exit(2)
        print("Note: no private-terms list found; only the generic patterns are checked.")
    elif not words:  # an empty list (or one saved in a way that lost its lines) would pass everything
        if a.strict:
            print(f"The private-terms list has no terms in it ({f}): refusing to pass. Add your terms, one per line.")
            sys.exit(2)
        print(f"Note: the private-terms list has no terms in it ({f}); only the generic patterns are checked.")
    targets = [Path(p).resolve() for p in a.paths] or [ROOT / "engine"]
    hits = scan(targets, words, a.allow, skip=not a.no_skip)
    print(f"{hits} hit{'' if hits == 1 else 's'} in {', '.join(t.name for t in targets)} "
          f"({len(words)} private terms + {len(PATTERNS)} patterns)")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
