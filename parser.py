"""Recursive-descent parser for the wadscript DSL.

Grammar (informal EBNF), see wadscript/README.md for the full reference:

    script      := { statement } ;
    statement   := map_stmt | defaults_stmt | texture_preset_stmt | const_stmt
                 | include_stmt
                 | sector_stmt | edge_stmt | thing_stmt | repeat_stmt ;

    const_stmt    := "const" IDENT "=" expr ;
                     -- top-level only (not valid inside `repeat`); resolved
                        immediately (may reference an earlier `const`, not a
                        `repeat` loop variable, since none is in scope here);
                        the name is then usable in any later `expr` exactly
                        like a plain integer literal
    include_stmt  := "include" STRING ;
                     -- path resolved relative to the including file's own
                        directory; the included file may itself only contain
                        defaults_stmt/texture_preset_stmt/const_stmt/include_stmt
                        (see "Sharing conventions across scripts (include)" in
                        README.md) -- its statements are merged into this
                        script as if written out at this point
    map_stmt      := "map" STRING ;
    defaults_stmt := "defaults" "{" { default_field } "}" ;
    texture_preset_stmt := "texture_preset" IDENT "{" { texture_field_no_preset } "}" ;
                     -- top-level only (not valid inside `repeat`); order
                        relative to the edges that reference it doesn't matter
    sector_stmt   := "sector" IDENT "{" { sector_field } "}" ;
                     -- sector_field includes "holes" "{" { "{" point { point } "}" } "}"
                        and "offset" (point | "relative_to" IDENT DIRECTION INT);
                        "floor"/"ceiling"/"light" are expr-valued, like every
                        coordinate
    edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
    thing_stmt    := "thing" (IDENT | "raw" INT) "at" point "angle" angle_expr
                      [ "flags" "{" { IDENT } "}" ] ;
    angle_expr    := expr ;   -- but a bare DIRECTION is also a legal atom here
                                 (east=0, north=90, west=180, south=270), unlike
                                 in a plain `expr` (points, offset, tags...)
    repeat_stmt   := "repeat" IDENT INT "{" { sector_stmt | edge_stmt | thing_stmt | repeat_stmt } "}"
                      [ "rotate" expr "around" point ] ;
                     -- IDENT is the loop variable, bound to 0..INT-1 in each
                        iteration; usable inside `expr`s in the body (including
                        a nested repeat's own body). Sector names in the body
                        get the enclosing iteration index(es) appended, so
                        `sector cell { ... }` inside `repeat i 4 { ... }`
                        produces `cell0`..`cell3`. An optional trailing
                        `rotate <angle> around <point>` rotates iteration i's
                        own geometry (points, edge endpoints, thing positions
                        and facing angle) by `<angle> * i` degrees around
                        `<point>` -- iteration 0 is never rotated. A sector
                        inside a rotated repeat can only use a literal
                        `offset`, not `offset relative_to` (the anchor's
                        position isn't resolved until geometry.py runs, well
                        after rotation has already been applied here).
    point         := "(" expr "," expr ")" ;
    expr          := term { ("+" | "-") term } ;
    term          := unary { ("*" | "/" | "%") unary } ;
                     -- "/" truncates toward negative infinity (Python's `//`);
                        "%" always has the same sign as its right operand, and
                        `(a // b) * b + a % b == a` always holds
    unary         := "-" unary | atom ;
    atom          := INT | IDENT | "random" "(" expr "," expr ")" | "(" expr ")" ;
                     -- a bare IDENT is a `const` name, or (only inside an
                        enclosing repeat's body) one of its (or an outer
                        repeat's) loop variables -- a loop variable of the
                        same name as a `const` shadows it. `random(min,max)`
                        draws one inclusive integer from the RNG seeded by
                        `--seed` (see wadscript.py); a script that never calls
                        `random()` is unaffected by the seed and always
                        produces byte-identical output.

AST nodes are plain dataclasses; this module has no knowledge of the
curated symbol tables (tables.py) or of WAD binary layout -- it only
builds a structural representation of the source text, tracking the
source line of every statement for error reporting. `repeat` bodies
are parsed once into a template (Expr-valued coordinates) and then
materialized (Expr -> int, one Sector/EdgeOverride/Thing per
iteration, `rotate` applied if present) directly into the Script --
geometry.py never sees an Expr, a RepeatTemplate, or a `const`, only
fully concrete int-valued AST nodes.
"""

import math
import os
import random
from dataclasses import dataclass, field

from errors import WsError, WsParseError
from lexer import tokenize

# Doom angle convention (0 = east, 90 = north, ...), shared by `offset
# relative_to`'s direction and a thing's symbolic `angle`.
DIRECTION_ANGLES = {"east": 0, "north": 90, "west": 180, "south": 270}


# ---------------------------------------------------------------- AST ----

@dataclass
class SpecialRef:
    """Either a symbolic name (kind="name") or an explicit `raw N` (kind="raw")."""
    kind: str   # "name" | "raw"
    value: object  # str name, or int raw id


@dataclass
class Expr:
    """A small arithmetic expression over integer constants, `const`
    names, `random(min,max)` calls, and `repeat` loop variables. Every
    coordinate (`points{}`/`holes{}`, a sector's `floor`/`ceiling`/
    `light`, a thing's `at`/`angle`, an `offset`'s literal point) parses
    to one of these; outside any `repeat`/`random()` it's always a bare
    "const" (parse_atom rejects any IDENT that isn't a known `const` or
    an enclosing repeat's loop variable), so a plain script evaluates
    exactly as if these fields were plain ints."""
    kind: str            # "const" | "var" | "add" | "sub" | "mul" | "div" | "mod" | "neg" | "random"
    a: object = None     # int (const), str (var name), or Expr (operators)
    b: object = None     # Expr, for add/sub/mul/div/mod/random
    line: int = None     # only needed for errors possible at eval time (div/mod/random)

    def eval(self, env, rng):
        if self.kind == "const":
            return self.a
        if self.kind == "var":
            return env[self.a]
        if self.kind == "neg":
            return -self.a.eval(env, rng)
        if self.kind == "random":
            lo, hi = self.a.eval(env, rng), self.b.eval(env, rng)
            if lo > hi:
                raise WsParseError(f"random({lo}, {hi}): min must be <= max", self.line)
            return rng.randint(lo, hi)
        left, right = self.a.eval(env, rng), self.b.eval(env, rng)
        if self.kind == "add":
            return left + right
        if self.kind == "sub":
            return left - right
        if self.kind == "mul":
            return left * right
        if self.kind == "div":
            if right == 0:
                raise WsParseError("division by zero in an expression", self.line)
            return left // right
        if self.kind == "mod":
            if right == 0:
                raise WsParseError("modulo by zero in an expression", self.line)
            return left % right
        raise AssertionError(self.kind)


@dataclass
class OffsetRef:
    """A sector's `offset` field: either a literal `(dx,dy)` point, or
    `relative_to <sector> <direction> <gap>`, resolved against the
    referenced (already-declared) sector's bounding box in geometry.py."""
    kind: str            # "literal" | "relative"
    line: int
    dx: Expr = None
    dy: Expr = None
    anchor: str = None
    direction: str = None   # "east" | "west" | "north" | "south"
    gap: int = None


@dataclass
class RepeatTemplate:
    """Parsed (but not yet materialized) body of a `repeat` statement."""
    var: str
    count: int
    line: int
    body: list = field(default_factory=list)  # [("sector"|"edge"|"thing"|"repeat", node), ...]
    rotate_angle: object = None   # Expr, or None (no "rotate" clause) -- per-iteration increment
    pivot: object = None          # (Expr,Expr), or None -- required together with rotate_angle


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
    floor: object = None    # Expr pre-materialize, int after (or None => defaults{})
    ceiling: object = None  # Expr pre-materialize, int after (or None => defaults{})
    floor_flat: str = None
    ceiling_flat: str = None
    light: object = None    # Expr pre-materialize, int after (or None => defaults{})
    special: SpecialRef = None
    tag: object = 0   # int (literal) or str (symbolic name, resolved in geometry.py)
    points: list = field(default_factory=list)  # list[(Expr,Expr)] pre-materialize, (int,int) after
    holes: list = field(default_factory=list)   # list[list[(Expr,Expr)]] -- one closed loop per hole
    offset: OffsetRef = None


@dataclass
class TextureOverride:
    line: int
    sector_name: str
    upper: str = None
    lower: str = None
    middle: str = None
    x_offset: int = None
    y_offset: int = None
    preset_name: str = None   # `preset <name>` -- fills any field above still None


@dataclass
class TexturePreset:
    """A top-level `texture_preset <name> { ... }` -- the same fields as
    a TextureOverride minus sector_name/preset_name (no nested presets).
    Applied in geometry.py as a fallback layer beneath a texture{}
    block's own explicit fields, order-independent within the block."""
    line: int
    name: str
    upper: str = None
    lower: str = None
    middle: str = None
    x_offset: int = None
    y_offset: int = None


@dataclass
class EdgeOverride:
    line: int
    p1: tuple   # (Expr,Expr) pre-materialize, (int,int) after
    p2: tuple
    special: SpecialRef = None
    tag: object = None   # int (literal), str (symbolic name), or None (unset)
    flags: list = field(default_factory=list)
    textures: dict = field(default_factory=dict)  # sector_name -> TextureOverride


@dataclass
class Thing:
    line: int
    kind_ref: SpecialRef
    x: object   # Expr pre-materialize, int after
    y: object
    angle: object
    flags: list = None  # list[str] or None (=> caller applies default)


@dataclass
class Script:
    map_name: str = None
    map_line: int = None
    defaults: Defaults = None
    texture_presets: list = field(default_factory=list)
    consts: dict = field(default_factory=dict)   # name -> already-resolved int
    sectors: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    things: list = field(default_factory=list)


# ------------------------------------------------------------- parser ----

class _Parser:
    def __init__(self, tokens, base_dir=".", including_stack=(), rng=None):
        self.tokens = tokens
        self.pos = 0
        self.repeat_vars = []   # stack of enclosing repeat loop-variable names
        self.consts = {}        # name -> already-resolved int, in declaration order
        self.base_dir = base_dir             # for resolving relative `include` paths
        self.including_stack = list(including_stack)  # resolved paths, for cycle detection
        # Shared across an `include` chain (see _parse_include) so that a
        # `random()` anywhere in the whole script/include tree draws from one
        # continuous stream, deterministic given the top-level --seed.
        self.rng = rng if rng is not None else random.Random()

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
        x = self.parse_expr()
        self.expect_punct(",")
        y = self.parse_expr()
        self.expect_punct(")")
        return (x, y)

    def parse_expr(self, allow_directions=False):
        node = self.parse_term(allow_directions)
        while self.at_punct("+") or self.at_punct("-"):
            op_tok = self.advance()
            rhs = self.parse_term(allow_directions)
            node = Expr("add" if op_tok.value == "+" else "sub", node, rhs, line=op_tok.line)
        return node

    def parse_term(self, allow_directions=False):
        node = self.parse_unary(allow_directions)
        while self.at_punct("*") or self.at_punct("/") or self.at_punct("%"):
            op_tok = self.advance()
            rhs = self.parse_unary(allow_directions)
            kind = {"*": "mul", "/": "div", "%": "mod"}[op_tok.value]
            node = Expr(kind, node, rhs, line=op_tok.line)
        return node

    def parse_unary(self, allow_directions=False):
        if self.at_punct("-"):
            tok = self.advance()
            return Expr("neg", self.parse_unary(allow_directions), line=tok.line)
        return self.parse_atom(allow_directions)

    def _peek_is_punct(self, offset, ch):
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return False
        tok = self.tokens[idx]
        return tok.kind == "PUNCT" and tok.value == ch

    def _parse_random_call(self, allow_directions, line):
        self.advance()  # 'random'
        self.expect_punct("(")
        lo = self.parse_expr(allow_directions)
        self.expect_punct(",")
        hi = self.parse_expr(allow_directions)
        self.expect_punct(")")
        return Expr("random", lo, hi, line=line)

    def parse_atom(self, allow_directions=False):
        tok = self.peek()
        if tok.kind == "INT":
            self.advance()
            return Expr("const", tok.value, line=tok.line)
        if tok.kind == "IDENT":
            if tok.value == "random" and self._peek_is_punct(1, "("):
                return self._parse_random_call(allow_directions, tok.line)
            is_repeat_var = tok.value in self.repeat_vars
            if allow_directions and tok.value in DIRECTION_ANGLES and not is_repeat_var:
                self.advance()
                return Expr("const", DIRECTION_ANGLES[tok.value], line=tok.line)
            if is_repeat_var:
                self.advance()
                return Expr("var", tok.value, line=tok.line)
            if tok.value in self.consts:
                self.advance()
                return Expr("const", self.consts[tok.value], line=tok.line)
            raise WsParseError(
                f"unknown name {tok.value!r} in an expression (expected a number, "
                + ("a direction (east/north/west/south), " if allow_directions else "")
                + "a 'random(min,max)' call, a 'const' name, or an enclosing 'repeat' loop variable)",
                tok.line)
        if tok.kind == "PUNCT" and tok.value == "(":
            self.advance()
            node = self.parse_expr(allow_directions)
            self.expect_punct(")")
            return node
        raise WsParseError(f"expected a number or expression, got {self._describe(tok)}", tok.line)

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

    def parse_offset_ref(self):
        """`offset` field body: a literal point, or `relative_to <sector>
        <direction> <gap>`."""
        line = self.peek().line
        if self.at_punct("("):
            dx, dy = self.parse_point()
            return OffsetRef(kind="literal", line=line, dx=dx, dy=dy)
        self.expect_ident("relative_to")
        anchor = self.expect_ident().value
        dir_tok = self.expect_ident()
        if dir_tok.value not in DIRECTION_ANGLES:
            raise WsParseError(
                f"expected a direction (east/west/north/south), got {dir_tok.value!r}", dir_tok.line)
        gap = self.expect_int().value
        return OffsetRef(kind="relative", line=line, anchor=anchor, direction=dir_tok.value, gap=gap)

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

    def parse_script(self, restricted=False):
        """`restricted=True` is for an included file: only defaults/
        texture_preset/const/(nested) include are allowed -- see _parse_include."""
        script = Script()
        while self.peek().kind != "EOF":
            tok = self.peek()
            if tok.kind != "IDENT":
                raise WsParseError(f"expected a statement, got {self._describe(tok)}", tok.line)
            if tok.value == "defaults":
                self._parse_defaults(script)
            elif tok.value == "texture_preset":
                script.texture_presets.append(self._parse_texture_preset())
            elif tok.value == "const":
                self._parse_const(script)
            elif tok.value == "include":
                self._parse_include(script)
            elif restricted:
                raise WsParseError(
                    f"{tok.value!r} is not allowed in an included file -- only 'defaults', "
                    f"'texture_preset', 'const', and nested 'include' statements are", tok.line)
            elif tok.value == "map":
                self._parse_map(script)
            elif tok.value == "sector":
                script.sectors.append(_materialize_sector(self._parse_sector(), {}, [], self.rng))
            elif tok.value == "edge":
                script.edges.append(_materialize_edge(self._parse_edge(), {}, self.rng))
            elif tok.value == "thing":
                script.things.append(_materialize_thing(self._parse_thing(), {}, self.rng))
            elif tok.value == "repeat":
                rt = self._parse_repeat_template()
                sectors, edges, things = _materialize_repeat(rt, {}, [], self.rng)
                script.sectors.extend(sectors)
                script.edges.extend(edges)
                script.things.extend(things)
            else:
                raise WsParseError(f"unknown statement {tok.value!r}", tok.line)
        return script

    def _parse_const(self, script):
        self.advance()  # 'const'
        name_tok = self.expect_ident()
        name = name_tok.value
        if name == "random" or name in DIRECTION_ANGLES:
            raise WsParseError(f"{name!r} is a reserved name and cannot be used as a const name", name_tok.line)
        if name in self.consts:
            raise WsParseError(f"duplicate 'const {name}'", name_tok.line)
        self.expect_punct("=")
        expr = self.parse_expr()
        value = expr.eval({}, self.rng)
        self.consts[name] = value
        script.consts[name] = value

    def _parse_include(self, script):
        tok = self.advance()  # 'include'
        rel_path = self.expect_string().value
        full_path = os.path.normpath(
            rel_path if os.path.isabs(rel_path) else os.path.join(self.base_dir, rel_path))

        if full_path in self.including_stack:
            cycle = " -> ".join(self.including_stack + [full_path])
            raise WsParseError(f"circular 'include': {cycle}", tok.line)

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                source = f.read()
        except OSError as e:
            raise WsParseError(f"cannot open included file {rel_path!r}: {e.strerror}", tok.line)

        sub_parser = _Parser(
            tokenize(source), base_dir=os.path.dirname(full_path),
            including_stack=self.including_stack + [full_path], rng=self.rng)
        try:
            included = sub_parser.parse_script(restricted=True)
        except WsError as inner:
            loc = f"{rel_path}:{inner.line}" if inner.line is not None else rel_path
            raise WsParseError(f"in included file {loc}: {inner.message}", tok.line) from inner

        if included.defaults is not None:
            if script.defaults is not None:
                raise WsParseError(
                    f"duplicate 'defaults' block (this script or one of its includes "
                    f"already has one; {rel_path!r} defines another)", tok.line)
            script.defaults = included.defaults
        script.texture_presets.extend(included.texture_presets)
        for name, value in included.consts.items():
            if name in self.consts:
                raise WsParseError(
                    f"duplicate 'const {name}' (already defined in this script or another "
                    f"include; {rel_path!r} defines it again)", tok.line)
            self.consts[name] = value
            script.consts[name] = value

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

    def _parse_texture_preset(self):
        tok = self.advance()  # 'texture_preset'
        name = self.expect_ident().value
        p = TexturePreset(line=tok.line, name=name)
        self.expect_punct("{")
        seen = set()
        while not self.at_punct("}"):
            ftok = self.expect_ident()
            self._check_dup(seen, ftok.value, ftok.line)
            if ftok.value in ("upper", "lower", "middle"):
                setattr(p, ftok.value, self.expect_string().value)
            elif ftok.value in ("x_offset", "y_offset"):
                setattr(p, ftok.value, self.expect_int().value)
            else:
                raise WsParseError(f"unknown texture_preset field {ftok.value!r}", ftok.line)
        self.expect_punct("}")
        return p

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
                setattr(s, ftok.value, self.parse_expr())
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
            elif ftok.value == "offset":
                s.offset = self.parse_offset_ref()
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
            elif ftok.value == "preset":
                t.preset_name = self.expect_ident().value
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
        angle = self.parse_expr(allow_directions=True)
        flags = None
        if self.at_ident("flags"):
            self.advance()
            flags = self.parse_flag_set()
        return Thing(line=tok.line, kind_ref=kind_ref, x=x, y=y, angle=angle, flags=flags)

    def _parse_repeat_template(self):
        tok = self.advance()  # 'repeat'
        var_tok = self.expect_ident()
        if var_tok.value in self.repeat_vars:
            raise WsParseError(
                f"repeat variable {var_tok.value!r} shadows an enclosing repeat's variable "
                f"of the same name", var_tok.line)
        count_tok = self.expect_int()
        if count_tok.value < 0:
            raise WsParseError(f"repeat count must be >= 0, got {count_tok.value}", count_tok.line)
        self.expect_punct("{")
        self.repeat_vars.append(var_tok.value)
        body = []
        try:
            while not self.at_punct("}"):
                stok = self.peek()
                if stok.kind != "IDENT":
                    raise WsParseError(
                        f"expected a statement inside 'repeat', got {self._describe(stok)}", stok.line)
                if stok.value == "sector":
                    body.append(("sector", self._parse_sector()))
                elif stok.value == "edge":
                    body.append(("edge", self._parse_edge()))
                elif stok.value == "thing":
                    body.append(("thing", self._parse_thing()))
                elif stok.value == "repeat":
                    body.append(("repeat", self._parse_repeat_template()))
                else:
                    raise WsParseError(f"statement {stok.value!r} is not allowed inside 'repeat'", stok.line)
        finally:
            self.repeat_vars.pop()
        self.expect_punct("}")
        rotate_angle, pivot = None, None
        if self.at_ident("rotate"):
            self.advance()
            rotate_angle = self.parse_expr()
            self.expect_ident("around")
            pivot = self.parse_point()
        return RepeatTemplate(var=var_tok.value, count=count_tok.value, line=tok.line, body=body,
                               rotate_angle=rotate_angle, pivot=pivot)


# --------------------------------------------------------- materialization ---
# Evaluates Expr-valued coordinate fields (points/holes/offset/floor/ceiling/
# light/thing at/angle) into plain ints, given an environment mapping repeat
# loop-variable names to their current value, and the script's shared RNG (for
# `random(min,max)`). For top-level (non-repeat) statements env is always {}
# -- parse_atom already guarantees no Expr can reference a variable name
# there, so evaluation is just unwrapping constants (and drawing from rng, if
# `random()` was used directly outside any repeat).

def _eval_pt(pt, env, rng):
    x, y = pt
    return (x.eval(env, rng), y.eval(env, rng))


def _materialize_offset(offset, env, rng):
    if offset is None:
        return None
    if offset.kind == "literal":
        return OffsetRef(kind="literal", line=offset.line,
                          dx=offset.dx.eval(env, rng), dy=offset.dy.eval(env, rng))
    return offset   # "relative" has no Expr fields (anchor/direction/gap are already concrete)


def _materialize_sector(s, env, index_path, rng):
    name = s.name if not index_path else f"{s.name}_{'_'.join(str(i) for i in index_path)}"
    return Sector(
        line=s.line, name=name,
        floor=s.floor.eval(env, rng) if s.floor is not None else None,
        ceiling=s.ceiling.eval(env, rng) if s.ceiling is not None else None,
        floor_flat=s.floor_flat, ceiling_flat=s.ceiling_flat,
        light=s.light.eval(env, rng) if s.light is not None else None,
        special=s.special, tag=s.tag,
        points=[_eval_pt(p, env, rng) for p in s.points],
        holes=[[_eval_pt(p, env, rng) for p in hole] for hole in s.holes],
        offset=_materialize_offset(s.offset, env, rng),
    )


def _materialize_edge(e, env, rng):
    return EdgeOverride(
        line=e.line, p1=_eval_pt(e.p1, env, rng), p2=_eval_pt(e.p2, env, rng),
        special=e.special, tag=e.tag, flags=e.flags, textures=e.textures,
    )


def _materialize_thing(t, env, rng):
    return Thing(
        line=t.line, kind_ref=t.kind_ref,
        x=t.x.eval(env, rng), y=t.y.eval(env, rng), angle=t.angle.eval(env, rng),
        flags=t.flags,
    )


def _materialize_body(body, env, index_path, rng):
    """Materializes the direct (sector/edge/thing/repeat) statements of one
    `repeat` body (or the top level) into concrete (sectors, edges, things)
    lists -- a nested `repeat`'s own `rotate` (if any) is already applied to
    its contribution by the time it's added here, via _materialize_repeat."""
    sectors, edges, things = [], [], []
    for kind, node in body:
        if kind == "sector":
            sectors.append(_materialize_sector(node, env, index_path, rng))
        elif kind == "edge":
            edges.append(_materialize_edge(node, env, rng))
        elif kind == "thing":
            things.append(_materialize_thing(node, env, rng))
        elif kind == "repeat":
            s2, e2, t2 = _materialize_repeat(node, env, index_path, rng)
            sectors.extend(s2)
            edges.extend(e2)
            things.extend(t2)
        else:
            raise AssertionError(kind)
    return sectors, edges, things


def _materialize_repeat(rt, env, index_path, rng):
    """Materializes every iteration of one `repeat` template into concrete
    (sectors, edges, things) lists, applying `rotate ... around ...` (if
    present) to each iteration's own contribution before it's returned --
    iteration i is rotated `rotate_angle * i` degrees, so iteration 0 is
    always left as-is."""
    sectors, edges, things = [], [], []
    for i in range(rt.count):
        child_env = dict(env)
        child_env[rt.var] = i
        s2, e2, t2 = _materialize_body(rt.body, child_env, index_path + [i], rng)
        if rt.rotate_angle is not None:
            # Checked on every iteration, including one where the angle
            # happens to work out to 0 (i==0 always, but also e.g. i==2 for
            # a rotate_angle of 180) -- a sector's compatibility with
            # 'rotate' shouldn't depend on which iteration it's currently
            # rendering as.
            for s in s2:
                _reject_relative_offset(s)
            angle = (rt.rotate_angle.eval(child_env, rng) * i) % 360
            if angle:
                px = rt.pivot[0].eval(child_env, rng)
                py = rt.pivot[1].eval(child_env, rng)
                for s in s2:
                    _rotate_sector(s, px, py, angle)
                for e in e2:
                    _rotate_edge(e, px, py, angle)
                for t in t2:
                    _rotate_thing(t, px, py, angle)
        sectors.extend(s2)
        edges.extend(e2)
        things.extend(t2)
    return sectors, edges, things


def _rotate_xy(x, y, px, py, angle_deg):
    """Rotates (x,y) by angle_deg (Doom convention: increasing angle turns
    counterclockwise, same direction as east(0)->north(90)) around (px,py).
    Multiples of 90 degrees stay exact integers (a 4-way rotational
    duplicate, the common case, never drifts off the lattice); any other
    angle is rounded to the nearest integer coordinate."""
    dx, dy = x - px, y - py
    if angle_deg % 90 == 0:
        for _ in range((angle_deg // 90) % 4):
            dx, dy = -dy, dx
        return (px + dx, py + dy)
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    nx = dx * cos_t - dy * sin_t
    ny = dx * sin_t + dy * cos_t
    return (px + round(nx), py + round(ny))


def _reject_relative_offset(s):
    if s.offset is not None and s.offset.kind != "literal":
        raise WsParseError(
            f"sector {s.name!r} uses 'offset relative_to', which isn't allowed inside a "
            f"'repeat ... rotate' block -- the anchor sector's position isn't resolved "
            f"until after rotation would need to apply here; use a literal 'offset (dx,dy)' "
            f"instead, or move this sector out of the rotated repeat", s.line)


def _rotate_sector(s, px, py, angle_deg):
    if s.offset is not None:
        dx, dy = s.offset.dx, s.offset.dy
        s.points = [(x + dx, y + dy) for (x, y) in s.points]
        s.holes = [[(x + dx, y + dy) for (x, y) in hole] for hole in s.holes]
        s.offset = None
    s.points = [_rotate_xy(x, y, px, py, angle_deg) for (x, y) in s.points]
    s.holes = [[_rotate_xy(x, y, px, py, angle_deg) for (x, y) in hole] for hole in s.holes]


def _rotate_edge(e, px, py, angle_deg):
    e.p1 = _rotate_xy(e.p1[0], e.p1[1], px, py, angle_deg)
    e.p2 = _rotate_xy(e.p2[0], e.p2[1], px, py, angle_deg)


def _rotate_thing(t, px, py, angle_deg):
    t.x, t.y = _rotate_xy(t.x, t.y, px, py, angle_deg)
    t.angle = (t.angle + angle_deg) % 360


def parse(tokens, base_dir=".", seed=None):
    """`base_dir` is the directory `include` paths are resolved relative
    to -- normally the directory of the top-level .wsl file being compiled.
    `seed` seeds the RNG backing `random(min,max)`; a script that never
    calls `random()` produces identical output regardless of `seed`."""
    return _Parser(tokens, base_dir=base_dir, rng=random.Random(seed)).parse_script()
