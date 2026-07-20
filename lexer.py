"""Tokenizer for the wadscript DSL.

Grammar is small and regular enough for a single hand-written scanner:
identifiers, integers (signed), double-quoted strings, and the
punctuation ( ) { } , - + *

The one wrinkle: '-' is both the edge-endpoint separator in
`(x,y)-(x,y)` (and the arithmetic minus in a `repeat` expression) and
a negative-number sign. Resolved by maximal munch: at each position we
first try to match `-?[0-9]+` as a single INT token; only if no digit
follows a '-' is it emitted as its own PUNCT token. Practical
consequence for `repeat` expressions: write `i - 1` (with a space),
not `i-1` -- the latter lexes as the two tokens IDENT "i", INT -1,
with no operator between them.
"""

from dataclasses import dataclass

from errors import WsParseError

PUNCT_CHARS = "(){},+*"


@dataclass
class Token:
    kind: str    # "IDENT" | "INT" | "STRING" | "PUNCT" | "EOF"
    value: object
    line: int

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, line={self.line})"


_INT_RE_NOTE = "maximal munch: -?[0-9]+ tried before a lone '-' is emitted"


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1

    while i < n:
        c = source[i]

        if c == "\n":
            line += 1
            i += 1
            continue

        if c in " \t\r":
            i += 1
            continue

        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if c == "-" or c.isdigit():
            start = i
            j = i
            if source[j] == "-":
                j += 1
            if j < n and source[j].isdigit():
                while j < n and source[j].isdigit():
                    j += 1
                tokens.append(Token("INT", int(source[start:j]), line))
                i = j
                continue
            # lone '-', not followed by a digit: punctuation token
            tokens.append(Token("PUNCT", "-", line))
            i += 1
            continue

        if c.isalpha() or c == "_":
            start = i
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            tokens.append(Token("IDENT", source[start:i], line))
            continue

        if c == '"':
            start_line = line
            i += 1
            start = i
            while i < n and source[i] != '"':
                if source[i] == "\n":
                    raise WsParseError("unterminated string literal", start_line)
                i += 1
            if i >= n:
                raise WsParseError("unterminated string literal", start_line)
            tokens.append(Token("STRING", source[start:i], start_line))
            i += 1
            continue

        if c in PUNCT_CHARS:
            tokens.append(Token("PUNCT", c, line))
            i += 1
            continue

        raise WsParseError(f"unexpected character {c!r}", line)

    tokens.append(Token("EOF", None, line))
    return tokens
