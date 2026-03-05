"""Entry point for `python -m parrot.finance`.

Usage:
    python -m parrot.finance --help
    python -m parrot.finance deliberate --with-history
    python -m parrot.finance memos list
    python -m parrot.finance research list
"""

from parrot.finance.cli import main

if __name__ == "__main__":
    main()
