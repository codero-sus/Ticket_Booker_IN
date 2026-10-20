"""BRUTE ALGEBRA — arithmetic for gods who find 9,223,372,036,854,775,807 too small.

The GOD dial used to be a number. Now it is an *expression*::

    god of god of god of god
    ultimate brute god
    god ^ god
    too much brute
    9223372036854775807
    (god of god) * god!
    brute!

Grammar (right-associative powers, like every self-respecting god)::

    expr    := term (('of' | '^' | '**') expr)?      # 'of' == '^' == power
    term    := unary (('*' | 'x' | 'times') unary)*
    unary   := '+' unary | postfix
    postfix := primary '!'*
    primary := NUMBER | CONSTANT | '(' expr ')'

Everything saturates at INT64_MAX — gods do not wrap around, they top out.
100% pure/offline/unit-tested; no browser, no clock, no side effects.
"""

from __future__ import annotations

import re

INT64_MAX = 9223372036854775807

MAX_EXPR_LEN = 240

# Words that mean something brutally large.
CONSTANTS: dict[str, int] = {
    "brute": 5,
    "god": 1_000_000,
    "omega": 999_999_999,
    "brute god": 1_000_000_000,
    "ultimate god": 1_000_000_000_000,
    "ultimate brute god": INT64_MAX,
    "radioactive": INT64_MAX,
    "apotheosis": INT64_MAX,
    "max": INT64_MAX,
    "infinity": INT64_MAX,
    "inf": INT64_MAX,
    "too much brute": INT64_MAX,
}

# The warcry that evaluates to the entire dial.
DEFAULT_BRUTALITY = "god of god of god of god"

_NUM_RE = re.compile(r"\d[\d,_]*")
_WORD_RE = re.compile(r"[a-z]+")


class BruteAlgebraError(ValueError):
    """The expression was not brutal enough to parse."""


# --------------------------------------------------------------------------- #
# saturating math
# --------------------------------------------------------------------------- #

def sat_add(a: int, b: int) -> int:
    return min(INT64_MAX, max(0, int(a)) + max(0, int(b)))


def sat_mul(a: int, b: int) -> int:
    a, b = max(0, int(a)), max(0, int(b))
    if a == 0 or b == 0:
        return 0
    if a > INT64_MAX // b:
        return INT64_MAX
    return a * b


def sat_pow(base: int, exponent: int) -> int:
    base, exponent = max(0, int(base)), max(0, int(exponent))
    if exponent == 0:
        return 1
    if base in (0, 1):
        return base
    if exponent == 1:
        return min(base, INT64_MAX)
    if base >= 2 and exponent >= 63:
        return INT64_MAX  # 2**63 already exceeds int64
    result = 1
    for _ in range(exponent):
        result = sat_mul(result, base)
        if result >= INT64_MAX:
            return INT64_MAX
    return result


def sat_fact(n: int) -> int:
    n = max(0, int(n))
    if n <= 1:
        return 1
    if n > 20:
        return INT64_MAX  # 21! overflows int64
    result = 1
    for i in range(2, n + 1):
        result = sat_mul(result, i)
    return result


def is_saturated(value: int) -> bool:
    return int(value) >= INT64_MAX


# --------------------------------------------------------------------------- #
# lexer
# --------------------------------------------------------------------------- #

def _merge_phrases(tokens: list[tuple[str, object]]) -> list[tuple[str, object]]:
    """Collapse multi-word constants: 'ultimate brute god' -> INT64_MAX."""
    out: list[tuple[str, object]] = []
    i = 0
    while i < len(tokens):
        kind, value = tokens[i]
        if kind != "word":
            out.append((kind, value))
            i += 1
            continue
        matched = False
        for size in (3, 2, 1):
            chunk = tokens[i:i + size]
            if len(chunk) == size and all(t[0] == "word" for t in chunk):
                phrase = " ".join(str(t[1]) for t in chunk)
                if phrase in CONSTANTS:
                    out.append(("num", CONSTANTS[phrase]))
                    i += size
                    matched = True
                    break
        if not matched:
            raise BruteAlgebraError(f"unknown brute word: {value!r}")
    return out


def _tokenize(expr: str) -> list[tuple[str, object]]:
    raw = str(expr or "").strip()
    if not raw:
        raise BruteAlgebraError("empty brute level")
    if len(raw) > MAX_EXPR_LEN:
        raise BruteAlgebraError(f"expression too long (max {MAX_EXPR_LEN} chars)")
    raw = raw.lower().replace("∞", " infinity ")
    raw = re.sub(r"(?<=\d),(?=\d)", "", raw)  # 9,223,... -> 9223...
    raw = re.sub(r"(?<=\d)_(?=\d)", "", raw)
    raw = re.sub(r"\bthe\b", " ", raw)
    raw = re.sub(r"(?<=\w)-(?=\w)", " ", raw)  # ultimate-brute-god -> words

    tokens: list[tuple[str, object]] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch.isspace():
            i += 1
            continue
        if ch.isdigit():
            m = _NUM_RE.match(raw, i)
            assert m is not None
            digits = m.group(0).replace(",", "").replace("_", "")
            try:
                tokens.append(("num", int(digits)))
            except ValueError as exc:  # pragma: no cover - regex guarantees digits
                raise BruteAlgebraError(f"bad number {digits!r}") from exc
            i = m.end()
            continue
        if ch.isalpha():
            m = _WORD_RE.match(raw, i)
            assert m is not None
            word = m.group(0)
            i = m.end()
            if word == "of":
                tokens.append(("op", "of"))
            elif word in ("x", "times"):
                tokens.append(("op", "*"))
            else:
                tokens.append(("word", word))
            continue
        if raw.startswith("**", i):
            tokens.append(("op", "^"))
            i += 2
            continue
        if ch in "+*^!()":
            tokens.append(("op", ch))
            i += 1
            continue
        raise BruteAlgebraError(f"cannot read {ch!r} in expression")
    return _merge_phrases(tokens)


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

class _Parser:
    def __init__(self, tokens: list[tuple[str, object]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> tuple[str, object] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _take(self) -> tuple[str, object]:
        tok = self._peek()
        assert tok is not None
        self.pos += 1
        return tok

    def parse(self) -> int:
        if not self.tokens:
            raise BruteAlgebraError("empty brute level")
        value = self._expr()
        if self.pos != len(self.tokens):
            raise BruteAlgebraError(f"trailing garbage: {self.tokens[self.pos:]!r}")
        return max(1, min(INT64_MAX, int(value)))

    def _expr(self) -> int:
        left = self._term()
        tok = self._peek()
        if tok is not None and tok[0] == "op" and tok[1] in ("of", "^"):
            self._take()
            right = self._expr()  # right-associative: god^(god^god)
            return sat_pow(left, right)
        return left

    def _term(self) -> int:
        left = self._unary()
        while True:
            tok = self._peek()
            if tok is not None and tok[0] == "op" and tok[1] == "*":
                self._take()
                left = sat_mul(left, self._unary())
                continue
            return left

    def _unary(self) -> int:
        tok = self._peek()
        if tok is not None and tok[0] == "op" and tok[1] == "+":
            self._take()
            return self._unary()
        if tok is not None and tok[0] == "op" and tok[1] == "-":
            raise BruteAlgebraError("gods do not subtract")
        return self._postfix()

    def _postfix(self) -> int:
        value = self._primary()
        while True:
            tok = self._peek()
            if tok is not None and tok[0] == "op" and tok[1] == "!":
                self._take()
                value = sat_fact(value)
                continue
            return value

    def _primary(self) -> int:
        tok = self._peek()
        if tok is None:
            raise BruteAlgebraError("expression ended too early")
        kind, value = tok
        if kind == "num":
            self._take()
            return min(INT64_MAX, int(value))
        if kind == "op" and value == "(":
            self._take()
            inner = self._expr()
            closing = self._peek()
            if closing is None or closing != ("op", ")"):
                raise BruteAlgebraError("missing ')' — even gods close brackets")
            self._take()
            return inner
        raise BruteAlgebraError(f"expected a number or brute word, got {value!r}")


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #

def evaluate(expr) -> int:
    """Evaluate a brute expression to an int (1..INT64_MAX), saturating."""
    if isinstance(expr, bool):
        return max(1, min(INT64_MAX, int(expr)))
    if isinstance(expr, int):
        return max(1, min(INT64_MAX, expr))
    try:
        tokens = _tokenize(str(expr))
    except BruteAlgebraError:
        raise
    except Exception as exc:  # never leak random exceptions to CLI/WebUI
        raise BruteAlgebraError(str(exc)) from exc
    return _Parser(tokens).parse()


def parse_level(raw, fallback: int | None = None) -> int:
    """Parse a CLI/WebUI/JSON level. With `fallback`, never raise."""
    try:
        return evaluate(raw)
    except BruteAlgebraError:
        if fallback is not None:
            return max(1, min(INT64_MAX, int(fallback)))
        raise


def try_parse_level(raw, fallback: int = 4) -> int:
    """Never raises — for the WebUI where a typo must not kill the server."""
    return parse_level(raw, fallback=fallback)


def format_level(level: int) -> str:
    return f"{int(level):,}"


__all__ = [
    "INT64_MAX",
    "DEFAULT_BRUTALITY",
    "CONSTANTS",
    "BruteAlgebraError",
    "sat_add",
    "sat_mul",
    "sat_pow",
    "sat_fact",
    "is_saturated",
    "evaluate",
    "parse_level",
    "try_parse_level",
    "format_level",
]
