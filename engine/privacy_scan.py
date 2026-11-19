"""Privacy scan: make sure shareable files hold none of the user's personal details before they leave the machine.

Usage:
  python engine/privacy_scan.py [PATH ...] [--terms FILE] [--strict]   # default: engine/ (exit 1 on any hit)

What it looks for:
  - every term in a private-terms list (one per line, case-insensitive; # starts a comment): the user's name,
    home town, employers, contacts, accounts. The list never goes in the repo. It is found, in order, at:
    --terms FILE, the PRIVATE_TERMS environment variable, or <data>/private-terms.txt. --strict fails when
    no list is found (the pre-commit hook uses it).
  - patterns that leak whatever the list misses: Windows or macOS home-folder paths, email addresses,
    LinkedIn profile links.
A line marked "privacy-scan: ignore" is skipped only inside privacy_scan.py itself (its own pattern
definitions); anywhere else the marker does nothing.
Deliberate exceptions (e.g. the author's name in LICENSE) go in an allow file, one per line: "<path> | <phrase>",
paths relative to the folder being scanned. The phrase is removed from that file's lines before checking, so every
other term in the same line is still caught. Default: .privacy-allow in the folder being scanned; --allow FILE
overrides it (the pre-commit hook passes the staged copy).
Run it on the engine after every change meant for the public repo, and on the whole repo before every push.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ROOT, Paths  # noqa: E402

IGNORE = "privacy-scan: " + "ignore"  # split so this line itself is still scanned
PATTERNS = {
    "home-folder path": r"[A-Za-z]:\\Users\\[^\\\s]+|/Users/[^/\s]+/|/home/[^/\s]+/",  # privacy-scan: ignore
    "email address": r"\b[\w.+-]+@(?!example\.(?:com|org|net)\b)[\w-]+\.[\w.]+\b",  # privacy-scan: ignore
    "LinkedIn profile link": r"linkedin\.com/in/[\w-]+",  # privacy-scan: ignore
}
TEXT = {".py", ".md", ".json", ".txt", ".html", ".svg", ".toml", ".cfg", ".yml", ".yaml", ".csv", ".tsv", ".xml",
        ".ini", ".sh", ".ps1", ".bat", ".gitignore", ".gitattributes", ""}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp"}
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
    for line in f.read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip()
        if t:
            out.append(t)
    return out


def allowed(f):
    """{relative path: [phrases]} from an allow file ('<path> | <phrase>' per line; # comments)."""
    out = {}
    if f and Path(f).is_file():
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                path, phrase = (x.strip() for x in line.split("|", 1))
                out.setdefault(path.replace("\\", "/"), []).append(phrase)
    return out


def read_text(f):
    """A file's text, or None when it isn't text. Every file is checked, whatever its extension: known text
    types are read as text; anything else counts as text only if it has no NUL bytes and decodes as UTF-8, so an
    archive or other binary can't slip past the scan just because its extension isn't listed."""
    data = f.read_bytes()
    if f.suffix.lower() in TEXT:
        return data.decode("utf-8", errors="replace")
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan(paths, words, allow_file=None):
    rx = [(f"private term '{w}'", re.compile(rf"(?<![\w]){re.escape(w)}(?![\w])", re.I)) for w in words]
    rx += [(name, re.compile(p)) for name, p in PATTERNS.items()]
    hits = 0
    for root in paths:
        allow = allowed(allow_file or (root / ".privacy-allow" if root.is_dir() else None))
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            if SKIP_DIRS & set(f.parts):
                continue
            rel = f.relative_to(root).as_posix() if root.is_dir() else f.name
            if rel == ".privacy-allow":  # the exceptions list names what it allows
                continue
            shown = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
            text = read_text(f)
            if text is None:  # not text: an image is only flagged for a look; anything else can't be checked
                if f.suffix.lower() in IMAGES:
                    print(f"{shown}: image, not scanned: check it by eye for names, paths or screenshots of personal data")
                else:
                    hits += 1
                    print(f"{shown}: binary file the scan can't read (archive or unknown format): keep it out of "
                          f"shareable folders")
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if IGNORE in line and f.name == "privacy_scan.py":  # only the scanner's own pattern lines
                    continue
                for phrase in allow.get(rel, []):
                    line = re.sub(re.escape(phrase), " ", line, flags=re.I)
                for name, r in rx:
                    if r.search(line):
                        hits += 1
                        print(f"{shown}:{n}: {name}: {line.strip()[:120]}")
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--data", default=None)
    ap.add_argument("--terms", help="private-terms list (kept outside the repo)")
    ap.add_argument("--strict", action="store_true", help="fail when no private-terms list is found")
    ap.add_argument("--allow", help="allow file of deliberate exceptions (default: <folder>/.privacy-allow)")
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
    targets = [Path(p).resolve() for p in a.paths] or [ROOT / "engine"]
    hits = scan(targets, words, a.allow)
    print(f"{hits} hit{'' if hits == 1 else 's'} in {', '.join(t.name for t in targets)} "
          f"({len(words)} private terms + {len(PATTERNS)} patterns)")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
