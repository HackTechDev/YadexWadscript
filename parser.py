"""Recursive-descent parser for the wadscript DSL.

Grammar (informal EBNF), see wadscript/README.md for the full reference:

    script      := { statement } ;
    statement   := map_stmt | defaults_stmt | texture_preset_stmt
                 | sector_stmt | edge_stmt | thing_stmt | repeat_stmt ;

    map_stmt      := "map" STRING ;
    defaults_stmt := "defaults" "{" { default_field } "}" ;
    texture_preset_stmt := "texture_preset" IDENT "{" { texture_field_no_preset } "}" ;
                     -- top-level only (not valid inside `repeat`); order
                        relative to the edges that reference it doesn't matter
    sector_stmt   := "sector" IDENT "{" { sector_field } "}" ;
                     -- sector_field includes "holes" "{" { "{" point { point } "}" } "}"
                        and "offset" (point | "relative_to" IDENT DIRECTION INT)
    edge_stmt     := "edge" point "-" point "{" { edge_field } "}" ;
    thing_stmt    := "thing" (IDENT | "raw" INT) "at" point "angle" angle_expr
                      [ "flags" "{" { IDENT } "}" ] ;
    angle_expr    := expr ;   -- but a bare DIRECTION is also a legal atom here
                                 (east=0, north=90, west=180, south=270), unlike
                                 in a plain `expr` (points, offset, tags...)
    repeat_stmt   := "repeat" IDENT INT "{" { sector_stmt | edge_stmt | thing_stmt | repeat_stmt } "}" ;
                     -- IDENT is the loop variable, bound to 0..INT-1 in each
                        iteration; usable inside `expr`s in the body (including
                        a nested repeat's own body). Sector names in the body
                        get the enclosing iteration index(es) appended, so
                        `sector cell { ... }` inside `repeat i 4 { ... }`
                        produces `cell0`..`cell3`.
    point         := "(" expr "," expr ")" ;
    expr          := term { ("+" | "-") term } ;
    term          := unary { "*" unary } ;
    unary         := "-" unary | INT | IDENT | "(" expr ")" ;
                     -- a bare IDENT is only legal inside an enclosing repeat's
                        body, and must name one of its (or an outer repeat's)
                        loop variables. Outside `repeat`, `expr` is always a
                        constant, so plain coordinates work exactly as before.

AST nodes are plain dataclasses; this module has no knowledge of the
curated symbol tables (tables.py) or of WAD binary layout -- it only
builds a structural representation of the source text, tracking the
source line of every statement for error reporting. `repeat` bodies
are parsed once into a template (Expr-valued coordinates) and then
materialized (Expr -> int, one Sector/EdgeOverride/Thing per
iteration) directly into the Script -- geometry.py never sees an Expr
or a RepeatTemplate, only fully concrete int-valued AST nodes.
"""

from dataclasses import dataclass, field

from errors import WsParseError

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
    """A small arithmetic expression over integer constants and `repeat`
    loop variables. Every coordinate (`points{}`/`holes{}`, a thing's
    `at`/`angle`, an `offset`'s literal point) parses to one of these;
    outside any `repeat` it's always a bare "const" (parse_atom rejects
    any IDENT that isn't an enclosing repeat's loop variable), so a
    plain script evaluates exactly as if these fields were plain ints."""
    kind: str            # "const" | "var" | "add" | "sub" | "mul" | "neg"
    a: object = None     # int (const), str (var name), or Expr (operators)
    b: object = None     # Expr, for add/sub/mul

    def eval(self, env):
        if self.kind == "const":
            return self.a
        if self.kind == "var":
            return env[self.a]
        if self.kind == "neg":
            return -self.a.eval(env)
        left, right = self.a.eval(env), self.b.eval(env)
        if self.kind == "add":
            return left + right
        if self.kind == "sub":
            return left - right
        if self.kind == "mul":
            return left * right
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
    sectors: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    things: list = field(default_factory=list)


# ------------------------------------------------------------- parser ----

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.repeat_vars = []   # stack of enclosing repeat loop-variable names

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
            op = self.advance().value
            rhs = self.parse_term(allow_directions)
            node = Expr("add" if op == "+" else "sub", node, rhs)
        return node

    def parse_term(self, allow_directions=False):
        node = self.parse_unary(allow_directions)
        while self.at_punct("*"):
            self.advance()
            rhs = self.parse_unary(allow_directions)
            node = Expr("mul", node, rhs)
        return node

    def parse_unary(self, allow_directions=False):
        if self.at_punct("-"):
            self.advance()
            return Expr("neg", self.parse_unary(allow_directions))
        return self.parse_atom(allow_directions)

    def parse_atom(self, allow_directions=False):
        tok = self.peek()
        if tok.kind == "INT":
            self.advance()
            return Expr("const", tok.value)
        if tok.kind == "IDENT":
            if (allow_directions and tok.value in DIRECTION_ANGLES
                    and tok.value not in self.repeat_vars):
                self.advance()
                return Expr("const", DIRECTION_ANGLES[tok.value])
            if tok.value not in self.repeat_vars:
                raise WsParseError(
                    f"unknown name {tok.value!r} in an expression (expected a number, "
                    + ("a direction (east/north/west/south), " if allow_directions else "")
                    + "or an enclosing 'repeat' loop variable)", tok.line)
            self.advance()
            return Expr("var", tok.value)
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
            elif tok.value == "texture_preset":
                script.texture_presets.append(self._parse_texture_preset())
            elif tok.value == "sector":
                script.sectors.append(_materialize_sector(self._parse_sector(), {}, []))
            elif tok.value == "edge":
                script.edges.append(_materialize_edge(self._parse_edge(), {}))
            elif tok.value == "thing":
                script.things.append(_materialize_thing(self._parse_thing(), {}))
            elif tok.value == "repeat":
                rt = self._parse_repeat_template()
                for i in range(rt.count):
                    _materialize_stmts(rt.body, {rt.var: i}, [i], script)
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
        return RepeatTemplate(var=var_tok.value, count=count_tok.value, line=tok.line, body=body)


# --------------------------------------------------------- materialization ---
# Evaluates Expr-valued coordinate fields (points/holes/offset/thing at/angle)
# into plain ints, given an environment mapping repeat loop-variable names to
# their current value. For top-level (non-repeat) statements env is always
# {} -- parse_atom already guarantees no Expr can reference a variable name
# there, so evaluation is just unwrapping constants.

def _eval_pt(pt, env):
    x, y = pt
    return (x.eval(env), y.eval(env))


def _materialize_offset(offset, env):
    if offset is None:
        return None
    if offset.kind == "literal":
        return OffsetRef(kind="literal", line=offset.line, dx=offset.dx.eval(env), dy=offset.dy.eval(env))
    return offset   # "relative" has no Expr fields (anchor/direction/gap are already concrete)


def _materialize_sector(s, env, index_path):
    name = s.name if not index_path else f"{s.name}_{'_'.join(str(i) for i in index_path)}"
    return Sector(
        line=s.line, name=name, floor=s.floor, ceiling=s.ceiling,
        floor_flat=s.floor_flat, ceiling_flat=s.ceiling_flat, light=s.light,
        special=s.special, tag=s.tag,
        points=[_eval_pt(p, env) for p in s.points],
        holes=[[_eval_pt(p, env) for p in hole] for hole in s.holes],
        offset=_materialize_offset(s.offset, env),
    )


def _materialize_edge(e, env):
    return EdgeOverride(
        line=e.line, p1=_eval_pt(e.p1, env), p2=_eval_pt(e.p2, env),
        special=e.special, tag=e.tag, flags=e.flags, textures=e.textures,
    )


def _materialize_thing(t, env):
    return Thing(
        line=t.line, kind_ref=t.kind_ref,
        x=t.x.eval(env), y=t.y.eval(env), angle=t.angle.eval(env),
        flags=t.flags,
    )


def _materialize_stmts(body, env, index_path, script):
    for kind, node in body:
        if kind == "sector":
            script.sectors.append(_materialize_sector(node, env, index_path))
        elif kind == "edge":
            script.edges.append(_materialize_edge(node, env))
        elif kind == "thing":
            script.things.append(_materialize_thing(node, env))
        elif kind == "repeat":
            for i in range(node.count):
                child_env = dict(env)
                child_env[node.var] = i
                _materialize_stmts(node.body, child_env, index_path + [i], script)
        else:
            raise AssertionError(kind)


def parse(tokens):
    return _Parser(tokens).parse_script()
