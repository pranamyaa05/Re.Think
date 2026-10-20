"""
PlatformLink — connects a user to their Codeforces (or future platform) handle.

Contains the sync lease fields used for atomic concurrency control during
long-running platform API syncs.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PlatformLink(Base):
    __tablename__ = "platform_links"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", name="uq_user_platform"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(
        String(20), nullable=False  # 'codeforces'
    )
    handle: Mapped[str] = mapped_column(String(100), nullable=False)
    auth_token: Mapped[Optional[str]] = mapped_column(Text, default=None)

    # ── Sync state ────────────────────────────────────────────────────────
    # last_synced_at: when the most recent successful sync completed.
    # sync_status: idle | syncing | synced | failed
    # sync_worker_id: fencing token — release must match this to prevent
    #                 stale workers from overwriting newer sync state.
    # lease_expires_at: NULL when idle. Set to NOW()+15min on acquire.
    #                   If a worker dies, the lease naturally expires.
    # sync_error: NULL on success, error message on failure.
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="idle"
    )
    sync_worker_id: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    sync_error: Mapped[Optional[str]] = mapped_column(default=None)

    # ── Last-sync progress counts (honest sync) ───────────────────────────
    # fetched = what the platform API returned; inserted/upserted = what was
    # new to this database. A re-sync of already-stored data yields fetched>0
    # with inserted=0, so the two are never conflated again.
    submissions_fetched: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    submissions_inserted: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    contests_fetched: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    contests_inserted: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )
    problems_upserted: Mapped[int] = mapped_column(
        Integer, server_default="0", default=0, nullable=False
    )

    # Whether per-submission data is available for this link. LeetCode links
    # without a session cookie can only provide contests + aggregate stats,
    # so submissions_available=False with a user-facing message.
    submissions_available: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="platform_links")

    def __repr__(self) -> str:
        return (
            f"<PlatformLink(id={self.id}, platform='{self.platform}', "
            f"handle='{self.handle}', sync_status='{self.sync_status}')>"
        )
