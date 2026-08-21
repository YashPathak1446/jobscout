"""
PDF Builder - Compile generated .tex resumes to PDF via pdflatex.

Generation writes LaTeX; this turns it into the artifact you actually
submit. Kept deliberately separate from generation_agent so the pipeline
still produces .tex files on machines with no LaTeX toolchain — a missing
pdflatex is a skip, never a failure.

Design notes:

- **Rerun only when the log asks.** Jake's template has no table of contents
  and no internal cross-references, so the usual "always run it twice" rule is
  waste. But hyperref writes its bookmark file (.out) *during* pass one, so
  pass one emits a PDF with no outline and the log says "Rerun to get outlines
  right". We do what latexmk does: parse the log, run again only if asked.
  Typical cost is one extra ~0.7s pass.
- **cwd = the .tex directory.** Simpler than -output-directory, and it makes
  \\input{glyphtounicode} resolve the same way it does when you compile by
  hand.
- **MiKTeX gets --enable-installer.** A basic MiKTeX install lacks titlesec
  and marvosym, which this template needs. Without the flag MiKTeX pops a GUI
  prompt and the subprocess hangs until the timeout. With it, the first
  compile is slow (packages download) and every later one is fast.

Location: jobscout_v3/tools/generation/pdf_builder.py
"""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# A cold MiKTeX install downloads missing packages on the first compile, which
# can genuinely take a minute. Steady-state compiles are ~1s.
COMPILE_TIMEOUT_SECONDS = 180

# Byproducts pdflatex leaves next to the .pdf. Removed after a compile so the
# outputs directory holds only files worth looking at.
AUX_SUFFIXES = ('.aux', '.log', '.out', '.fls', '.fdb_latexmk', '.synctex.gz')

# Hard ceiling on passes. Two is enough for this template; the cap exists so a
# pathological document can't loop asking to be rerun forever.
MAX_PASSES = 2

# How LaTeX and its packages ask to be run again.
_RERUN_PATTERN = re.compile(
    r'Rerun (?:LaTeX|to get)|Please rerun|rerunfilecheck Warning',
    re.IGNORECASE,
)

# Windows LaTeX installers routinely leave pdflatex off PATH — MiKTeX's
# per-user install in particular. Checked only after shutil.which() misses.
_FALLBACK_DIRS = (
    r"C:\Program Files\MiKTeX\miktex\bin\x64",
    r"C:\Program Files (x86)\MiKTeX\miktex\bin",
    r"~\AppData\Local\Programs\MiKTeX\miktex\bin\x64",
    r"C:\texlive\2026\bin\windows",
    r"C:\texlive\2025\bin\windows",
    "/usr/bin",
    "/usr/local/bin",
    "/Library/TeX/texbin",
)


@dataclass
class PdfResult:
    """
    Outcome of one compile attempt.

    status is one of:
        'ok'      - PDF written, path in pdf_path
        'skipped' - no pdflatex on this machine; nothing was attempted
        'failed'  - pdflatex ran and errored; see error / log_excerpt
        'timeout' - pdflatex hung past COMPILE_TIMEOUT_SECONDS
    """
    status: str
    pdf_path: Optional[Path] = None
    error: Optional[str] = None
    log_excerpt: Optional[str] = None
    passes: int = 0
    pages: int = 0

    @property
    def success(self) -> bool:
        return self.status == 'ok'


def find_pdflatex() -> Optional[str]:
    """
    Locate a pdflatex binary, or None if this machine has no LaTeX.

    Checks PATH first, then the handful of default install locations that
    commonly aren't on PATH.
    """
    found = shutil.which("pdflatex")
    if found:
        return found

    for directory in _FALLBACK_DIRS:
        base = Path(directory).expanduser()
        for name in ("pdflatex.exe", "pdflatex"):
            candidate = base / name
            if candidate.exists():
                return str(candidate)

    return None


def detect_flavor(binary: str) -> str:
    """
    Return 'miktex', 'texlive', or 'unknown'.

    Only used to decide whether --enable-installer is safe to pass; TeX Live
    rejects the flag outright.
    """
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            errors='replace',
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug(f"Could not probe pdflatex version: {exc}")
        return 'unknown'

    banner = f"{proc.stdout}\n{proc.stderr}".lower()

    if 'miktex' in banner:
        return 'miktex'
    if 'tex live' in banner or 'texlive' in banner:
        return 'texlive'
    return 'unknown'


def compile_pdf(
    tex_path,
    binary: Optional[str] = None,
    flavor: Optional[str] = None,
    timeout: int = COMPILE_TIMEOUT_SECONDS,
    keep_aux: bool = False,
) -> PdfResult:
    """
    Compile one .tex file to PDF alongside itself.

    Args:
        tex_path: Path to the .tex file to compile
        binary: pdflatex path; resolved via find_pdflatex() when omitted
        flavor: 'miktex' / 'texlive' / 'unknown'; probed when omitted
        timeout: Seconds before the compile is killed
        keep_aux: Leave .aux/.log/.out in place (useful when debugging)

    Never raises on a LaTeX problem — the failure comes back as a PdfResult
    so one bad resume doesn't take down a batch.
    """
    tex_path = Path(tex_path)

    if not tex_path.exists():
        return PdfResult(status='failed', error=f"No such .tex file: {tex_path}")

    binary = binary or find_pdflatex()
    if not binary:
        return PdfResult(
            status='skipped',
            error="pdflatex not found — install MiKTeX (Windows) or TeX Live",
        )

    if flavor is None:
        flavor = detect_flavor(binary)

    cmd: List[str] = [
        binary,
        "-interaction=nonstopmode",   # never stop to ask; errors go to the log
        "-file-line-error",           # file:line: message — parseable errors
        "-halt-on-error",             # stop at the first error, don't cascade
    ]

    if flavor == 'miktex':
        cmd.append("--enable-installer")

    cmd.append(tex_path.name)

    log_path = tex_path.with_suffix('.log')
    passes = 0

    while passes < MAX_PASSES:
        passes += 1
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tex_path.parent),
                capture_output=True,
                text=True,
                errors='replace',         # LaTeX logs aren't reliably UTF-8
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            _cleanup_aux(tex_path, keep_aux)
            return PdfResult(
                status='timeout',
                error=f"pdflatex exceeded {timeout}s on pass {passes} and was killed",
                passes=passes,
            )
        except OSError as exc:
            return PdfResult(
                status='failed',
                error=f"Could not run pdflatex: {exc}",
                passes=passes,
            )

        # A failed pass won't be fixed by running it again.
        if proc.returncode != 0:
            break

        if not _needs_rerun(log_path):
            break

        logger.debug(f"{tex_path.name}: log requested a rerun (pass {passes})")

    pdf_path = tex_path.with_suffix('.pdf')
    log_excerpt = _read_log_excerpt(log_path)
    pages = _read_page_count(log_path)

    # Trust the artifact over the exit code: MiKTeX sometimes returns nonzero
    # for warnings it recovered from, and a PDF on disk means it recovered.
    if pdf_path.exists():
        if proc.returncode != 0:
            logger.warning(
                f"pdflatex exited {proc.returncode} but produced a PDF: {pdf_path.name}"
            )
        _cleanup_aux(tex_path, keep_aux)
        return PdfResult(
            status='ok',
            pdf_path=pdf_path,
            log_excerpt=log_excerpt,
            passes=passes,
            pages=pages,
        )

    fallback = (proc.stdout or proc.stderr or "").strip()[-500:]
    _cleanup_aux(tex_path, keep_aux)

    return PdfResult(
        status='failed',
        error=f"pdflatex exited {proc.returncode} with no PDF",
        log_excerpt=log_excerpt or fallback or None,
        passes=passes,
    )


def _read_page_count(log_path: Path) -> int:
    """
    Page count of the produced PDF, from the log's "Output written" line.

    Returns 0 when it can't be determined. Whitespace is flattened before
    matching because pdflatex hard-wraps the log at ~79 columns, which
    routinely splits "(1 page, 112672 bytes)" across two lines.
    """
    if not log_path.exists():
        return 0

    try:
        text = log_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return 0

    flat = re.sub(r'\s+', ' ', text)
    match = re.search(r'Output written.*?\((\d+) page', flat)

    return int(match.group(1)) if match else 0


def _needs_rerun(log_path: Path) -> bool:
    """
    True when the .log asks to be run again.

    Cheaper and more honest than compiling twice unconditionally: most runs
    of this template settle after one pass, and the ones that don't say so.
    """
    if not log_path.exists():
        return False

    try:
        text = log_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False

    return bool(_RERUN_PATTERN.search(text))


def _read_log_excerpt(log_path: Path, max_lines: int = 12) -> Optional[str]:
    """
    Pull the first real LaTeX error out of the .log.

    A pdflatex log is thousands of lines; the useful part is the block
    starting at the first line beginning with '!' (or a file:line: error from
    -file-line-error). Everything before it is package chatter.
    """
    if not log_path.exists():
        return None

    try:
        text = log_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None

    lines = text.splitlines()
    error_pattern = re.compile(r'^(!|.+?:\d+:\s)')

    for i, line in enumerate(lines):
        if error_pattern.match(line):
            return "\n".join(lines[i:i + max_lines]).strip()

    return None


def _cleanup_aux(tex_path: Path, keep_aux: bool) -> None:
    """Delete pdflatex byproducts sitting next to the .tex."""
    if keep_aux:
        return

    for suffix in AUX_SUFFIXES:
        try:
            tex_path.with_suffix(suffix).unlink(missing_ok=True)
        except OSError as exc:
            logger.debug(f"Could not remove {tex_path.stem}{suffix}: {exc}")
