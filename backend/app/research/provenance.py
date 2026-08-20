"""Portable source-content provenance for the frozen strategy implementation.

The research protocol intentionally uses source content rather than a Git
revision as its executable-strategy identity.  That remains exact for dirty
working trees and source archives while avoiding checkout paths, database
identifiers, import caches, and bytecode in canonical fingerprints.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.backtesting.fingerprint import research_fingerprint

STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA = "strategy-source-manifest-v1"
STRATEGY_IMPLEMENTATION_PACKAGES = (
    "strategies",
    "opportunities",
    "challenger",
    "regimes",
    "indicators",
)


def _normalized_source(raw: bytes) -> bytes:
    """Return deterministic UTF-8 source bytes across checkout line endings."""

    normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    try:
        normalized.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("strategy implementation source must be valid UTF-8") from exc
    return normalized


def _validate_logical_path(logical_path: str) -> None:
    path = PurePosixPath(logical_path)
    if (
        path.is_absolute()
        or path.suffix != ".py"
        or not path.parts
        or path.parts[0] != "app"
        or ".." in path.parts
        or "__pycache__" in path.parts
    ):
        raise ValueError(f"invalid strategy source logical path: {logical_path!r}")


@dataclass(frozen=True, slots=True)
class StrategySourceModule:
    """One normalized Python source file identified without a filesystem path."""

    logical_path: str
    sha256: str
    normalized_byte_count: int

    def __post_init__(self) -> None:
        _validate_logical_path(self.logical_path)
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("strategy source SHA-256 must be 64 lowercase hexadecimal digits")
        if self.normalized_byte_count < 0:
            raise ValueError("normalized source byte count cannot be negative")


@dataclass(frozen=True, slots=True)
class StrategyImplementationProvenance:
    """Canonical manifest for every source module in the strategy stack."""

    modules: tuple[StrategySourceModule, ...]
    schema_version: str = STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA
    identity_basis: str = "normalized-utf8-python-source-content"
    repository_revision_policy: str = "source-content-authoritative-git-not-required"
    runtime_paths_included: bool = False
    bytecode_included: bool = False
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != STRATEGY_IMPLEMENTATION_PROVENANCE_SCHEMA:
            raise ValueError("unsupported strategy implementation provenance schema")
        if (
            self.identity_basis,
            self.repository_revision_policy,
            self.runtime_paths_included,
            self.bytecode_included,
        ) != (
            "normalized-utf8-python-source-content",
            "source-content-authoritative-git-not-required",
            False,
            False,
        ):
            raise ValueError("strategy implementation identity policy is immutable")
        ordered = tuple(sorted(self.modules, key=lambda module: module.logical_path))
        if not ordered:
            raise ValueError("strategy implementation provenance cannot be empty")
        paths = tuple(module.logical_path for module in ordered)
        if len(paths) != len(set(paths)):
            raise ValueError("strategy implementation logical paths must be unique")
        object.__setattr__(self, "modules", ordered)
        object.__setattr__(
            self,
            "digest",
            research_fingerprint(
                {
                    "kind": "strategy_implementation_source_manifest",
                    "schema_version": self.schema_version,
                    "identity_basis": self.identity_basis,
                    "repository_revision_policy": self.repository_revision_policy,
                    "runtime_paths_included": self.runtime_paths_included,
                    "bytecode_included": self.bytecode_included,
                    "modules": tuple(
                        {
                            "logical_path": module.logical_path,
                            "sha256": module.sha256,
                            "normalized_byte_count": module.normalized_byte_count,
                        }
                        for module in ordered
                    ),
                }
            ),
        )

    def audit_details(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "digest": self.digest,
            "identity_basis": self.identity_basis,
            "repository_revision_policy": self.repository_revision_policy,
            "runtime_paths_included": self.runtime_paths_included,
            "bytecode_included": self.bytecode_included,
            "modules": tuple(
                {
                    "logical_path": module.logical_path,
                    "sha256": module.sha256,
                    "normalized_byte_count": module.normalized_byte_count,
                }
                for module in self.modules
            ),
        }


def build_strategy_implementation_provenance(
    source_by_logical_path: Mapping[str, bytes | str],
) -> StrategyImplementationProvenance:
    """Build a content manifest from logical paths and source payloads.

    This pure constructor is also useful to verify that mapping order, checkout
    location, and line-ending style do not affect the identity.
    """

    modules: list[StrategySourceModule] = []
    for logical_path, source in source_by_logical_path.items():
        _validate_logical_path(logical_path)
        raw = source.encode("utf-8") if isinstance(source, str) else source
        normalized = _normalized_source(raw)
        modules.append(
            StrategySourceModule(
                logical_path=logical_path,
                sha256=hashlib.sha256(normalized).hexdigest(),
                normalized_byte_count=len(normalized),
            )
        )
    return StrategyImplementationProvenance(tuple(modules))


def load_strategy_implementation_provenance(
    app_source_root: Path | None = None,
) -> StrategyImplementationProvenance:
    """Load the complete frozen strategy stack from Python source, fail closed."""

    root = (app_source_root or Path(__file__).resolve().parents[1]).resolve()
    source_by_logical_path: dict[str, bytes] = {}
    for package in STRATEGY_IMPLEMENTATION_PACKAGES:
        package_root = root / package
        if not package_root.is_dir() or not (package_root / "__init__.py").is_file():
            raise RuntimeError(f"strategy implementation package is unavailable: app/{package}")
        package_files = tuple(sorted(package_root.rglob("*.py")))
        if not package_files:
            raise RuntimeError(f"strategy implementation package is empty: app/{package}")
        for source_path in package_files:
            try:
                relative = source_path.relative_to(root)
            except ValueError as exc:
                raise RuntimeError("strategy source resolved outside the application root") from exc
            logical_path = PurePosixPath("app", *relative.parts).as_posix()
            if logical_path in source_by_logical_path:
                raise RuntimeError(f"duplicate strategy source module: {logical_path}")
            try:
                source_by_logical_path[logical_path] = source_path.read_bytes()
            except OSError as exc:
                raise RuntimeError(f"strategy source is unreadable: {logical_path}") from exc
    return build_strategy_implementation_provenance(source_by_logical_path)
