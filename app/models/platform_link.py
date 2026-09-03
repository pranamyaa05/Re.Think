"""
PlatformLink — connects a user to their Codeforces (or future platform) handle.

Contains the sync lease fields used for atomic concurrency control during
long-running platform API syncs.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
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
