"""CLI output utilities: terminal formatting, colour, banners."""

from __future__ import annotations

import sys

# ANSI colour codes — disabled automatically when stdout is not a TTY.
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_BLUE = "\033[34m"
_RESET = "\033[0m"

_USE_COLOUR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOUR else text


def bold(text: str) -> str:
    return _c(_BOLD, text)


def dim(text: str) -> str:
    return _c(_DIM, text)


def green(text: str) -> str:
    return _c(_GREEN, text)


def yellow(text: str) -> str:
    return _c(_YELLOW, text)


def red(text: str) -> str:
    return _c(_RED, text)


def cyan(text: str) -> str:
    return _c(_CYAN, text)


def blue(text: str) -> str:
    return _c(_BLUE, text)


def rule(char: str = "═", width: int = 60) -> str:
    return char * width


def print_banner(title: str) -> None:
    print()
    print(bold(title))
    print(rule())


def print_section(title: str) -> None:
    print()
    print(bold(title))
    print(rule("─", 40))


def print_ok(msg: str) -> None:
    print(f"  {green('✓')} {msg}")


def print_warn(msg: str) -> None:
    print(f"  {yellow('⚠')} {msg}")


def print_error(msg: str) -> None:
    print(f"  {red('✗')} {msg}", file=sys.stderr)


def print_info(msg: str) -> None:
    print(f"  {cyan('→')} {msg}")


def print_item(label: str, value: str, indent: int = 4) -> None:
    pad = " " * indent
    print(f"{pad}{bold(label)}: {value}")


def print_code_loc(file: str, line: int | None, symbol: str | None,
                   kind: str, indent: int = 6) -> None:
    pad = " " * indent
    loc = f"{file}:{line}" if line else file
    sym = f"  {dim(symbol)}" if symbol else ""
    tag = yellow(f"[{kind}]") if kind == "INDIRECT" else cyan(f"[{kind}]")
    print(f"{pad}{tag}  {loc}{sym}")
