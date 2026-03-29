from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from csre.db.base import Base, utcnow


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email_hash: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    referral_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    referrer_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True, index=True)
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class ReferralRecord(Base):
    __tablename__ = "referrals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    referrer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    referred_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="VALID", index=True)
    depth: Mapped[int] = mapped_column(default=1)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    device_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fraud_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fraud_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RewardRecord(Base):
    __tablename__ = "rewards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    referral_id: Mapped[str] = mapped_column(String(36), ForeignKey("referrals.id"), index=True)
    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    trigger_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    level: Mapped[int] = mapped_column(default=1)
    reward_type: Mapped[str] = mapped_column(String(20), default="PERCENTAGE")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FraudEventRecord(Base):
    __tablename__ = "fraud_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    referral_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("referrals.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(50))
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    severity: Mapped[int] = mapped_column(default=1)
    reviewed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ActivityEventRecord(Base):
    __tablename__ = "activity_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class GraphSyncQueueRecord(Base):
    __tablename__ = "graph_sync_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
