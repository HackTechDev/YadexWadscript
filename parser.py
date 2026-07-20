"""Recursive-descent parser for the wadscript DSL.

Grammar (informal EBNF), see wadscript/README.md for the full reference:

    script      := { statement } ;
    statement   := map_stmt | defaults_stmt | sector_stmt | edge_stmt | thing_stmt ;

    map_stmt      := "map" STRING ;
    defaults_stmt := "defaults" "{" { default_field } "}" ;
    sector_stmt   := "sector" IDENT "{" { sector_field } "}" ;
                     -- sector_field includes "holes" "{" { "{" point { point } "}" } "}"
    edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
    thing_stmt    := "thing" (IDENT | "raw" INT) "at" point "angle" INT
                      [ "flags" "{" { IDENT } "}" ] ;
    point         := "(" INT "," INT ")" ;

AST nodes are plain dataclasses; this module has no knowledge of the
curated symbol tables (tables.py) or of WAD binary layout -- it only
builds a structural representation of the source text, tracking the
source line of every statement for error reporting.
"""

from dataclasses import dataclass, field

from errors import WsParseError


# ---------------------------------------------------------------- AST ----

@dataclass
class SpecialRef:
    """Either a symbolic name (kind="name") or an explicit `raw N` (kind="raw")."""
    kind: str   # "name" | "raw"
    value: object  # str name, or int raw id


@dataclass
class Defaults:
    line: int
    floor: int = None
    ceiling: int = None
    floor_flat: str = None
    ceiling_flat: str = None
    wall_texture: str = None
    middle_texture: str = None
    light: int = None


@dataclass
class Sector:
    line: int
    name: str
    floor: int = None
    ceiling: int = None
    floor_flat: str = None
    ceiling_flat: str = None
    light: int = None
    special: SpecialRef = None
    tag: object = 0   # int (literal) or str (symbolic name, resolved in geometry.py)
    points: list = field(default_factory=list)  # list[(int,int)]
    holes: list = field(default_factory=list)   # list[list[(int,int)]] -- one closed loop per hole


@dataclass
class TextureOverride:
    line: int
    sector_name: str
    upper: str = None
    lower: str = None
    middle: str = None
    x_offset: int = None
    y_offset: int = None


@dataclass
class EdgeOverride:
    line: int
    p1: tuple
    p2: tuple
    special: SpecialRef = None
    tag: object = None   # int (literal), str (symbolic name), or None (unset)
    flags: list = field(default_factory=list)
    textures: dict = field(default_factory=dict)  # sector_name -> TextureOverride


@dataclass
class Thing:
    line: int
    kind_ref: SpecialRef
    x: int
    y: int
    angle: int
    flags: list = None  # list[str] or None (=> caller applies default)


@dataclass
class Script:
    map_name: str = None
    map_line: int = None
    defaults: Defaults = None
    sectors: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    things: list = field(default_factory=list)


# ------------------------------------------------------------- parser ----

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def expect_punct(self, ch):
        tok = self.peek()
        if tok.kind != "PUNCT" or tok.value != ch:
            raise WsParseError(f"expected {ch!r}, got {self._describe(tok)}", tok.line)
        return self.advance()

    def expect_ident(self, name=None):
        tok = self.peek()
        if tok.kind != "IDENT":
            raise WsParseError(f"expected identifier, got {self._describe(tok)}", tok.line)
        if name is not None and tok.value != name:
            raise WsParseError(f"expected {name!r}, got {tok.value!r}", tok.line)
        return self.advance()

    def expect_int(self):
        tok = self.peek()
        if tok.kind != "INT":
            raise WsParseError(f"expected integer, got {self._describe(tok)}", tok.line)
        return self.advance()

    def expect_string(self):
        tok = self.peek()
        if tok.kind != "STRING":
            raise WsParseError(f"expected string literal, got {self._describe(tok)}", tok.line)
        return self.advance()

    def at_ident(self, name):
        tok = self.peek()
        return tok.kind == "IDENT" and tok.value == name

    def at_punct(self, ch):
        tok = self.peek()
        return tok.kind == "PUNCT" and tok.value == ch

    @staticmethod
    def _describe(tok):
        if tok.kind == "EOF":
            return "end of file"
        return f"{tok.kind} {tok.value!r}"

    # -- shared bits --

    def parse_point(self):
        self.expect_punct("(")
        x = self.expect_int().value
        self.expect_punct(",")
        y = self.expect_int().value
        self.expect_punct(")")
        return (x, y)

    def parse_special_ref(self):
        """`<ident>` or `raw <int>`."""
        tok = self.expect_ident()
        if tok.value == "raw":
            n = self.expect_int()
            return SpecialRef("raw", n.value)
        return SpecialRef("name", tok.value)

    def parse_tag_ref(self):
        """`<int>` (a literal tag) or `<ident>` (a symbolic tag name,
        auto-assigned a consistent integer during geometry resolution)."""
        tok = self.peek()
        if tok.kind == "INT":
            self.advance()
            return tok.value
        if tok.kind == "IDENT":
            self.advance()
            return tok.value
        raise WsParseError(f"expected a tag (integer or name), got {self._describe(tok)}", tok.line)

    def parse_flag_set(self):
        """`flags { IDENT ... }` body, called after 'flags' consumed."""
        self.expect_punct("{")
        flags = []
        while not self.at_punct("}"):
            flags.append(self.expect_ident().value)
        self.expect_punct("}")
        return flags

    def _check_dup(self, seen, field_name, line):
        if field_name in seen:
            raise WsParseError(f"duplicate field {field_name!r} in this block", line)
        seen.add(field_name)

    # -- top level --

    def parse_script(self):
        script = Script()
        while self.peek().kind != "EOF":
            tok = self.peek()
            if tok.kind != "IDENT":
                raise WsParseError(f"expected a statement, got {self._describe(tok)}", tok.line)
            if tok.value == "map":
                self._parse_map(script)
            elif tok.value == "defaults":
                self._parse_defaults(script)
            elif tok.value == "sector":
                script.sectors.append(self._parse_sector())
            elif tok.value == "edge":
                script.edges.append(self._parse_edge())
            elif tok.value == "thing":
                script.things.append(self._parse_thing())
            else:
                raise WsParseError(f"unknown statement {tok.value!r}", tok.line)
        return script

    def _parse_map(self, script):
        tok = self.advance()  # 'map'
        if script.map_name is not None:
            raise WsParseError("duplicate 'map' statement", tok.line)
        name_tok = self.expect_string()
        script.map_name = name_tok.value
        script.map_line = tok.line

    def _parse_defaults(self, script):
        tok = self.advance()  # 'defaults'
        if script.defaults is not None:
            raise WsParseError("duplicate 'defaults' block", tok.line)
        d = Defaults(line=tok.line)
        self.expect_punct("{")
        seen = set()
        while not self.at_punct("}"):
            ftok = self.expect_ident()
            self._check_dup(seen, ftok.value, ftok.line)
            if ftok.value in ("floor", "ceiling", "light"):
                setattr(d, ftok.value, self.expect_int().value)
            elif ftok.value in ("floor_flat", "ceiling_flat", "wall_texture", "middle_texture"):
                setattr(d, ftok.value, self.expect_string().value)
            else:
                raise WsParseError(f"unknown defaults field {ftok.value!r}", ftok.line)
        self.expect_punct("}")
        script.defaults = d

    def _parse_sector(self):
        tok = self.advance()  # 'sector'
        name = self.expect_ident().value
        s = Sector(line=tok.line, name=name)
        self.expect_punct("{")
        seen = set()
        while not self.at_punct("}"):
            ftok = self.expect_ident()
            self._check_dup(seen, ftok.value, ftok.line)
            if ftok.value in ("floor", "ceiling", "light"):
                setattr(s, ftok.value, self.expect_int().value)
            elif ftok.value in ("floor_flat", "ceiling_flat"):
                setattr(s, ftok.value, self.expect_string().value)
            elif ftok.value == "special":
                s.special = self.parse_special_ref()
            elif ftok.value == "tag":
                s.tag = self.parse_tag_ref()
            elif ftok.value == "points":
                self.expect_punct("{")
                pts = []
                while not self.at_punct("}"):
                    pts.append(self.parse_point())
                self.expect_punct("}")
                s.points = pts
            elif ftok.value == "holes":
                self.expect_punct("{")
                holes = []
                while not self.at_punct("}"):
                    self.expect_punct("{")
                    pts = []
                    while not self.at_punct("}"):
                        pts.append(self.parse_point())
                    self.expect_punct("}")
                    holes.append(pts)
                self.expect_punct("}")
                s.holes = holes
            else:
                raise WsParseError(f"unknown sector field {ftok.value!r}", ftok.line)
        self.expect_punct("}")
        return s

    def _parse_edge(self):
        tok = self.advance()  # 'edge'
        p1 = self.parse_point()
        self.expect_punct("-")
        p2 = self.parse_point()
        e = EdgeOverride(line=tok.line, p1=p1, p2=p2)
        self.expect_punct("{")
        seen = set()
        while not self.at_punct("}"):
            ftok = self.expect_ident()
            if ftok.value == "texture":
                # multiple `texture <sector> {...}` blocks are expected
                # (one per bordering sector), so no dup check on the
                # 'texture' keyword itself -- dup-checked per sector name.
                sector_name = self.expect_ident().value
                if sector_name in e.textures:
                    raise WsParseError(
                        f"duplicate 'texture {sector_name}' block on this edge", ftok.line)
                e.textures[sector_name] = self._parse_texture_override(sector_name)
                continue
            self._check_dup(seen, ftok.value, ftok.line)
            if ftok.value == "special":
                e.special = self.parse_special_ref()
            elif ftok.value == "tag":
                e.tag = self.parse_tag_ref()
            elif ftok.value == "flags":
                e.flags = self.parse_flag_set()
            else:
                raise WsParseError(f"unknown edge field {ftok.value!r}", ftok.line)
        self.expect_punct("}")
        return e

    def _parse_texture_override(self, sector_name):
        line = self.peek().line
        t = TextureOverride(line=line, sector_name=sector_name)
        self.expect_punct("{")
        seen = set()
        while not self.at_punct("}"):
            ftok = self.expect_ident()
            self._check_dup(seen, ftok.value, ftok.line)
            if ftok.value in ("upper", "lower", "middle"):
                setattr(t, ftok.value, self.expect_string().value)
            elif ftok.value in ("x_offset", "y_offset"):
                setattr(t, ftok.value, self.expect_int().value)
            else:
                raise WsParseError(f"unknown texture field {ftok.value!r}", ftok.line)
        self.expect_punct("}")
        return t

    def _parse_thing(self):
        tok = self.advance()  # 'thing'
        kind_ref = self.parse_special_ref()
        self.expect_ident("at")
        x, y = self.parse_point()
        self.expect_ident("angle")
        angle = self.expect_int().value
        flags = None
        if self.at_ident("flags"):
            self.advance()
            flags = self.parse_flag_set()
        return Thing(line=tok.line, kind_ref=kind_ref, x=x, y=y, angle=angle, flags=flags)


def parse(tokens):
    return _Parser(tokens).parse_script()
