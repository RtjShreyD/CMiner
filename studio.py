#!/usr/bin/env python3
"""CMiner Studio — Terminal-based AI Content Creation Studio.

Launch with:
    python3 studio.py
"""

from studio.app import CMinerStudioApp


def main() -> None:
    app = CMinerStudioApp()
    app.run()


if __name__ == "__main__":
    main()
