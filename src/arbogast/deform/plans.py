"""Explicit non-sharding boundary for the finite deformation slice.

The 0.3 operations solve small globally coupled kernel, quotient, projector,
and affine systems.  Splitting their rows or columns would produce scheduler
fragments without independent mathematical meaning, so this module exports no
``plan/run/reduce`` surface.  Operation contracts therefore advertise every
deformation operation as non-shardable.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
