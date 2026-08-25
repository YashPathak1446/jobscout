"""
Start the local UI without having to know where `app.py` lives.

`streamlit run app.py` is fine from a clone and useless once installed: the
file is somewhere inside site-packages and the user has no reason to know the
path. This resolves it and hands it to Streamlit.

A subprocess rather than an import, because Streamlit's entry point expects to
own the process — it parses its own arguments, installs signal handlers and
runs a server. Calling into it in-process works until it does not, and the
failure looks like a hung terminal.

Location: jobscout_v3/scripts/launch_ui.py
"""

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).parent.parent / "app.py"


def main() -> int:
    if not APP.exists():
        print(f"Could not find the app at {APP}", file=sys.stderr)
        return 1

    try:
        import streamlit  # noqa: F401
    except ImportError:
        print("Streamlit is not installed.\n"
              "  pip install streamlit", file=sys.stderr)
        return 1

    # `-m streamlit` rather than the `streamlit` binary: the binary may not be
    # on PATH in a virtualenv that was never activated, and this interpreter
    # demonstrably has the package because the import above succeeded.
    command = [sys.executable, "-m", "streamlit", "run", str(APP)]
    try:
        return subprocess.call(command)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
