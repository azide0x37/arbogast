"""Build the exact versioned Git source archive for an Arbogast release."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout


def _version_from_pyproject(payload: str, *, label: str) -> str:
    value = tomllib.loads(payload)
    version = value.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{label} must declare a non-empty project version")
    return version


def project_version(root: Path) -> str:
    return _version_from_pyproject(
        (root / "pyproject.toml").read_text(encoding="utf-8"),
        label="pyproject.toml",
    )


def revision_version(root: Path, revision: str) -> str:
    payload = _git(root, "show", f"{revision}:pyproject.toml")
    return _version_from_pyproject(payload, label=f"{revision}:pyproject.toml")


def resolve_revision(root: Path, revision: str) -> str:
    resolved = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
    if len(resolved) != 40 or any(character not in "0123456789abcdef" for character in resolved):
        raise RuntimeError(f"Git returned a non-canonical commit ID for {revision!r}: {resolved!r}")
    return resolved


def _require_clean_worktree(root: Path) -> None:
    changes = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if changes:
        first = changes.splitlines()[0]
        raise RuntimeError(
            "refusing to mix worktree metadata with a Git source archive while the worktree "
            f"is dirty (first change: {first!r}); commit the candidate or pass --revision "
            "explicitly to archive one resolved commit"
        )


def build_source_archive(
    root: Path,
    dist_dir: Path,
    *,
    revision: str | None,
) -> Path:
    """Create a deterministic archive from one resolved, version-consistent commit.

    The default path is intentionally strict: it refuses a dirty worktree because the
    wheel/sdist build would otherwise see bytes that ``git archive HEAD`` cannot see.  An
    explicit ``revision`` is the safe escape hatch for archival/audit use; both the version and
    the bytes then come from that resolved commit, never from the surrounding worktree.
    """

    if revision is None:
        _require_clean_worktree(root)
    resolved = resolve_revision(root, revision or "HEAD")
    version = revision_version(root, resolved)
    if revision is None:
        worktree_version = project_version(root)
        if worktree_version != version:
            raise RuntimeError(
                "clean worktree version does not match HEAD: "
                f"worktree={worktree_version!r}, HEAD={version!r}"
            )
    output = dist_dir / f"arbogast-{version}-source.tar.gz"
    dist_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        (
            "git",
            "archive",
            "--format=tar.gz",
            f"--prefix=arbogast-{version}/",
            f"--output={output}",
            resolved,
        ),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"git archive failed: {detail}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--dist-dir", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument(
        "--revision",
        help=(
            "archive this explicitly resolved commit even if the worktree is dirty; "
            "the archive version is read from that commit"
        ),
    )
    args = parser.parse_args()
    try:
        output = build_source_archive(
            args.root.resolve(),
            args.dist_dir.resolve(),
            revision=args.revision,
        )
    except (OSError, RuntimeError, ValueError, tomllib.TOMLDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
