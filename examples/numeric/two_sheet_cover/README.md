# Two-sheet cover and exact Nielsen binding

This journey starts from the exact family \(x^2-t(t-1)\), records ordered numerical branch data
for a two-sheet cover with finite branch divisor \((0,1)\), and replays the cover's continuation
witnesses. It then recovers the numerical
branch cycles and binds them to one exact vertex of a supplied Nielsen class.
It finally replays the genuine normalized quadratic (B_2) coefficient homotopy for one braid
generator, producing an exact target rather than promoting the earlier local sheet-loop evidence.

The conclusions are kept separate: validated continuation certifies the numerical cover;
`bind_vertex` supplies the additional exact permutation witness needed to identify the canonical
Nielsen vertex; and `QuadraticB2Homotopy` separately proves the supported coefficient path. The
script also changes the ordered branch evidence and checks that the old binding no longer
verifies.

Run it from the repository root:

```bash
uv run python examples/numeric/two_sheet_cover/run.py
```

No external algebra backend is used.
