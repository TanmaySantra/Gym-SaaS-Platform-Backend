"""Shared enums referenced by multiple modules (models, schemas, services)."""
import enum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class GymStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PAYMENT_DUE = "PAYMENT_DUE"
    RESTRICTED = "RESTRICTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class WorkoutSessionStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class NotificationType(str, enum.Enum):
    PAYMENT_OVERDUE = "PAYMENT_OVERDUE"
    MEMBERSHIP_EXPIRING = "MEMBERSHIP_EXPIRING"
    MEMBERSHIP_RESTRICTED = "MEMBERSHIP_RESTRICTED"
    AI_INSIGHT = "AI_INSIGHT"


class RiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    LOGGED_OUT = "LOGGED_OUT"
    EXPIRED = "EXPIRED"
