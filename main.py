#!/usr/bin/env python3
"""graph2Thread launcher — opens the graphical flowchart editor.

Requires a Python built with Tk (tkinter).  On macOS the system interpreter
has it:

    /usr/bin/python3 main.py

If you see "No module named '_tkinter'", run with such an interpreter, or use
the headless CLI instead:  python3 -m g2t.cli --help
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    try:
        import tkinter  # noqa: F401
    except Exception:
        sys.stderr.write(
            "tkinter is not available in this Python build.\n"
            "Run with a Tk-enabled interpreter, e.g.:  /usr/bin/python3 main.py\n"
            "Or use the headless CLI:  python3 -m g2t.cli --help\n")
        return 1
    from g2t.editor import run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
