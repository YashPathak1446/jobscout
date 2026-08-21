"""
Inspect generated resumes — layout facts you can't get from validation.

Content validation checks bullet counts and character zones. This checks
what the resume actually looks like once rendered: how many pages, how many
bullets per component, and how much vertical room is left.

Usage:
    python scripts/inspect_resume.py                     # newest outputs/ dir
    python scripts/inspect_resume.py outputs/2026-08-20  # a directory
    python scripts/inspect_resume.py path/to/one.tex     # one file
    python scripts/inspect_resume.py --components        # per-component detail
    python scripts/inspect_resume.py --headroom          # bullets before spill

--headroom is the slow one: it recompiles with synthetic bullets appended
until the page breaks, so budget ~1s per extra bullet per resume. It is also
the only trustworthy way to measure fill — \\pagetotal/\\pagegoal from the log
reads near-100% even on resumes with two bullets of room, because the
template's vertical glue is stretchable and TeX absorbs the difference.

Location: jobscout_v3/scripts/inspect_resume.py
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.generation.pdf_builder import (  # noqa: E402
    compile_pdf,
    detect_flavor,
    find_pdflatex,
)

BULLET_RE = re.compile(r'\\resumeItem\{(.*?)\}\s*$', re.M)
SECTION_RE = r'\\section\{{{name}\}}(.*?)(?=\\section|\Z)'

# A realistic two-line bullet, matching the zone the fitter targets.
FILLER_BULLET = (
    r"\resumeItem{Engineered a synthetic filler bullet of representative "
    r"length to measure vertical headroom on the rendered page, matching "
    r"the two-line zone the bullet fitter targets in practice.}"
)

MAX_PROBE_BULLETS = 6


def find_targets(args_paths):
    """Resolve CLI paths to a list of .tex files."""
    if not args_paths:
        dated = sorted(
            d for d in Path("outputs").glob("*-*-*") if d.is_dir()
        )
        if not dated:
            sys.exit("No dated directories under outputs/.")
        args_paths = [str(dated[-1])]

    targets = []
    for raw in args_paths:
        path = Path(raw)
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.tex")))
        elif path.exists():
            targets.append(path)
        else:
            print(f"skipping (not found): {path}")

    return targets


def parse_components(tex):
    """Return {section: [(label, [bullet_len, ...]), ...]}."""
    out = {}

    for section in ("Experience", "Projects"):
        match = re.search(SECTION_RE.format(name=section), tex, re.S)
        if not match:
            out[section] = []
            continue

        components = []
        blocks = re.split(r'\\resume(?:Subheading|ProjectHeading)', match.group(1))[1:]

        for block in blocks:
            head = block.strip()[:110].replace("\n", " ")
            label = re.sub(r'https?://\S+', '', head)
            label = re.sub(r'[\\{}$|]', ' ', label)
            label = re.sub(r'\s+', ' ', label).strip()[:40]
            components.append((label, [len(b) for b in BULLET_RE.findall(block)]))

        out[section] = components

    return out


def compile_copy(tex_path, binary, flavor):
    """
    Compile a throwaway copy and return its PdfResult.

    Inspection must not mutate what it inspects. Compiling in place would
    overwrite the .pdf the pipeline produced and litter the output directory
    on failure. The generated .tex is self-contained apart from
    \\input{glyphtounicode}, which comes from the TeX distribution, so a
    temp directory compiles identically.
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / tex_path.name
        work.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        return compile_pdf(work, binary=binary, flavor=flavor)


def measure_headroom(tex_path, binary, flavor):
    """
    How many more bullets fit before the resume spills to a second page.

    Returns (headroom, base_pages). headroom is None if it couldn't be
    determined; MAX_PROBE_BULLETS means "at least that many".
    """
    src = Path(tex_path).read_text(encoding="utf-8")
    anchor = src.rfind(r"\resumeItemListEnd")
    if anchor == -1:
        return None, None

    with tempfile.TemporaryDirectory() as tmp:
        def pages_for(text):
            work = Path(tmp) / "probe.tex"
            work.write_text(text, encoding="utf-8")
            cmd = [binary, "-interaction=nonstopmode", "-file-line-error"]
            if flavor == "miktex":
                cmd.append("--enable-installer")
            cmd.append(work.name)
            subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                           errors="replace", timeout=300)
            log = Path(tmp) / "probe.log"
            if not log.exists():
                return None
            flat = re.sub(r"\s+", " ", log.read_text(encoding="utf-8", errors="replace"))
            found = re.search(r"Output written.*?\(\s*(\d+)\s+page", flat)
            return int(found.group(1)) if found else None

        base = pages_for(src)
        if base is None or base > 1:
            return 0, base

        current = src
        for extra in range(1, MAX_PROBE_BULLETS + 1):
            anchor = current.rfind(r"\resumeItemListEnd")
            current = (
                current[:anchor] + "        " + FILLER_BULLET + "\n      " + current[anchor:]
            )
            count = pages_for(current)
            if count is None:
                return None, base
            if count > 1:
                return extra - 1, base

        return MAX_PROBE_BULLETS, base


def main():
    parser = argparse.ArgumentParser(
        description="Inspect layout of generated resumes."
    )
    parser.add_argument("paths", nargs="*",
                        help="A .tex file or directory (default: newest outputs/ dir)")
    parser.add_argument("--components", action="store_true",
                        help="Show per-component bullet counts and lengths")
    parser.add_argument("--headroom", action="store_true",
                        help="Measure bullets-until-spill (slow: recompiles repeatedly)")
    args = parser.parse_args()

    targets = find_targets(args.paths)
    if not targets:
        sys.exit("No .tex files to inspect.")

    binary = find_pdflatex()
    flavor = detect_flavor(binary) if binary else None
    if not binary:
        print("pdflatex not found — reporting bullet counts only.\n")

    header = f"{'resume':52} {'exp':>4} {'proj':>5} {'total':>6} {'pages':>6}"
    if args.headroom:
        header += f" {'headroom':>9}"
    print(header)
    print("-" * len(header))

    for tex_path in targets:
        tex = tex_path.read_text(encoding="utf-8")
        components = parse_components(tex)

        exp_bullets = sum(len(lens) for _, lens in components["Experience"])
        proj_bullets = sum(len(lens) for _, lens in components["Projects"])

        pages = "-"
        if binary:
            result = compile_copy(tex_path, binary, flavor)
            pages = str(result.pages) if result.success else result.status

        name = tex_path.stem[:50]
        row = (f"{name:52} {exp_bullets:4} {proj_bullets:5} "
               f"{exp_bullets + proj_bullets:6} {pages:>6}")

        if args.headroom:
            if not binary:
                row += f" {'n/a':>9}"
            else:
                room, _ = measure_headroom(tex_path, binary, flavor)
                if room is None:
                    label = "?"
                elif room >= MAX_PROBE_BULLETS:
                    label = f"{MAX_PROBE_BULLETS}+"
                else:
                    label = str(room)
                row += f" {label:>9}"

        print(row)

        if args.components:
            for section, entries in components.items():
                print(f"    [{section}]")
                for label, lens in entries:
                    print(f"      {len(lens)} bullets  chars={lens}  {label}")
            print()

    if binary and not args.headroom:
        print("\nPass --headroom to measure how many more bullets each page can take.")


if __name__ == "__main__":
    main()
