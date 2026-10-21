"""Binding of a CHECK result to the exact local Storage and BOM versions it was calculated from.

A CHECK result may be published as current only if, after the calculation, each source was confirmed to still be the
version the calculation read:

1. The reader returns a WorkbookData whose `fingerprint` (path, size, times, ZIP part CRCs/sizes) was taken before
   the parse and found identical after it, so it identifies the version the calculation used.
2. The database synchronisation runs after the calculation. If it verified a role (IMPORTED / UNCHANGED, re-confirmed by
   sync_all after both roles), its `observed` fingerprint is the confirmed version. A synchronisation that verified a
   *different* version (a retry that imported a newer file) therefore never validates the earlier calculation.
3. If the synchronisation did not verify a role (no database, database error, source unavailable or still changing),
   the file is fingerprinted again directly, after the calculation.
4. The result is current only if confirmed == calculated for both roles. Otherwise the whole read / calculate /
   synchronise workflow is repeated, a bounded number of times, and then the result is marked OUTDATED.

This proves that one local file version was used and still present at `checked_at`; it cannot prove the file stays
unchanged afterwards, and it says nothing about the Google Drive cloud copy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time

from .core import DataReadError
from .reader import fingerprint
from .sync import content_signature

CHECK_ATTEMPTS = 3  # whole CHECK workflows per request when a source keeps changing
OUTDATED = "OUTDATED / RECHECK REQUIRED"
ROLE_NAMES = {"stock": "Storage", "bom": "BOM"}


@dataclass(frozen=True)
class SourceBinding:
    versions: dict    # role -> fingerprint of the version the calculation read
    confirmed: dict   # role -> fingerprint confirmed after the calculation; None if the file could not be read
    via_sync: dict    # role -> True when confirmed by a verified database synchronisation
    checked_at: float
    attempts: int

    @property
    def current(self) -> bool:
        return all(self.confirmed.get(role) == version for role, version in self.versions.items())

    @property
    def changed(self) -> tuple[str, ...]:
        return tuple(role for role, version in self.versions.items() if self.confirmed.get(role) != version)

    def describe(self) -> str:
        """Exactly which local versions were used, and when they were confirmed."""
        lines = [f"Result: {'Local Sources Verified' if self.current else OUTDATED}",
                 f"Confirmed at {datetime.fromtimestamp(self.checked_at):%Y-%m-%d %H:%M:%S} "
                 f"(CHECK attempt {self.attempts} of at most {CHECK_ATTEMPTS})"]
        for role, version in self.versions.items():
            how = "verified by the database synchronisation" if self.via_sync.get(role) else "re-read directly"
            state = "same version" if self.confirmed.get(role) == version else "CHANGED or unreadable"
            lines.append(f"{ROLE_NAMES[role]}: {version[0]}\n  saved {datetime.fromtimestamp(version[2] / 1e9):%Y-%m-%d %H:%M:%S}"
                         f" · {version[1]} bytes · content {content_signature(version)[:12]} · {state}, {how}")
        lines.append("Local file versions only: the Google Drive cloud copy is not verified.")
        return "\n".join(lines)


def bind(books: dict, sync_results: dict, attempt: int) -> SourceBinding:
    """books: role -> WorkbookData used by the calculation; sync_results: role -> SyncResult of the sync after it."""
    versions, confirmed, via_sync = {}, {}, {}
    for role, book in books.items():
        versions[role] = book.fingerprint
        result = sync_results.get(role)
        if result is not None and result.ok:
            confirmed[role], via_sync[role] = result.observed, True
        else:
            try:
                confirmed[role] = fingerprint(book.path)
            except DataReadError:
                confirmed[role] = None
            via_sync[role] = False
    return SourceBinding(versions, confirmed, via_sync, time.time(), attempt)


class ExportVerificationError(ValueError):
    """The CHECK cannot be exported; binding retains the failed local observations for the UI."""

    def __init__(self, binding, reason):
        super().__init__(reason)
        self.binding = binding


def verify_export(bound: SourceBinding, paths: dict) -> SourceBinding:
    """Recheck both selected local sources against the CHECK, without SQLite or cached-file fallback.

    Two fixed passes also catch Storage changing while BOM is inspected. This is a bounded point-in-time
    observation, never a guarantee of continued local stability or of Google Drive cloud freshness.
    A failed CHECK binding cannot be made exportable again here: the user must CHECK again.
    """
    if not isinstance(bound, SourceBinding) or set(bound.versions) != set(ROLE_NAMES) or not bound.current:
        raise ExportVerificationError(bound, "CHECK source versions are unverified; please CHECK again.")
    confirmed, reasons = {}, []
    for _ in range(2):
        for role in ROLE_NAMES:
            try:
                observed = fingerprint(paths.get(role, ""))
                if observed != bound.versions[role]:
                    reasons.append(f"{ROLE_NAMES[role]} source version or path changed")
            except (DataReadError, OSError, ValueError) as exc:
                observed = None
                reasons.append(f"{ROLE_NAMES[role]} source unavailable or verification failed: {exc}")
            # Never let a later successful observation hide a mismatch in this verification request.
            if role not in confirmed or confirmed[role] == bound.versions[role]:
                confirmed[role] = observed
    verified = SourceBinding(dict(bound.versions), confirmed, dict.fromkeys(ROLE_NAMES, False),
                             time.time(), bound.attempts)
    if reasons:
        raise ExportVerificationError(verified, "; ".join(dict.fromkeys(reasons)))
    return verified
