from __future__ import annotations
import sys

from .config import Config
from .controller.controller import Controller


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    task = " ".join(argv) or "hello, aetheris"
    result = Controller(Config.from_env()).handle(task)
    print(result.output)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
