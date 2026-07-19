# tests

Empty for now. When this grows a real test suite, put it here:

- `wadwriter.py` is pure binary formatting (`LevelData` -> bytes) —
  ideal for golden-byte tests with `pytest` (build a small `LevelData`
  by hand, assert the exact output bytes).
- `geometry.py` is pure data transformation (`Script` AST -> `LevelData`)
  — hand-construct small `Script` objects (or parse tiny `.wsl`
  snippets) and assert on the resolved vertex/linedef/sidedef counts
  and fields.
