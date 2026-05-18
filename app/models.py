from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey,
    Text, Enum as SAEnum, Date, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .database import Base


class UserRole(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    ADMIN = "ADMIN"


class GoalSheetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REWORK_REQUESTED = "REWORK_REQUESTED"


class UoMType(str, enum.Enum):
    NUMERIC_MIN = "NUMERIC_MIN"   # higher is better (e.g. revenue)
    NUMERIC_MAX = "NUMERIC_MAX"   # lower is better (e.g. TAT, cost)
    PERCENT_MIN = "PERCENT_MIN"   # higher % is better
    PERCENT_MAX = "PERCENT_MAX"   # lower % is better
    TIMELINE = "TIMELINE"         # date-based completion
    ZERO_BASED = "ZERO_BASED"     # zero = success


class CheckInStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    ON_TRACK = "ON_TRACK"
    COMPLETED = "COMPLETED"


class Quarter(str, enum.Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class EscalationRuleType(str, enum.Enum):
    GOAL_NOT_SUBMITTED = "GOAL_NOT_SUBMITTED"
    GOAL_NOT_APPROVED = "GOAL_NOT_APPROVED"
    CHECKIN_NOT_COMPLETED = "CHECKIN_NOT_COMPLETED"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_role", "role"),
        Index("ix_users_manager_id", "manager_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.EMPLOYEE)
    department = Column(String(100))
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    manager = relationship("User", remote_side=[id], back_populates="reports", lazy="select")
    reports = relationship("User", back_populates="manager", lazy="select")
    goal_sheets = relationship("GoalSheet", foreign_keys="GoalSheet.employee_id", back_populates="employee", lazy="select")
    approved_sheets = relationship("GoalSheet", foreign_keys="GoalSheet.approved_by_id", back_populates="approved_by", lazy="select")
    audit_logs = relationship("AuditLog", back_populates="user", lazy="select")
    notifications = relationship("Notification", back_populates="user", lazy="select")
    escalations_received = relationship("Escalation", foreign_keys="Escalation.target_user_id", back_populates="target_user", lazy="select")


class ThrustArea(Base):
    __tablename__ = "thrust_areas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    department = Column(String(100))
    is_active = Column(Boolean, default=True)

    goals = relationship("Goal", back_populates="thrust_area", lazy="select")


class GoalCycle(Base):
    __tablename__ = "goal_cycles"
    __table_args__ = (
        Index("ix_goal_cycles_is_active", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    goal_setting_start = Column(Date, nullable=False)
    goal_setting_end = Column(Date, nullable=False)
    q1_start = Column(Date)
    q1_end = Column(Date)
    q2_start = Column(Date)
    q2_end = Column(Date)
    q3_start = Column(Date)
    q3_end = Column(Date)
    q4_start = Column(Date)
    q4_end = Column(Date)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    goal_sheets = relationship("GoalSheet", back_populates="cycle", lazy="select")
    escalation_rules = relationship("EscalationRule", back_populates="cycle", lazy="select")


class GoalSheet(Base):
    __tablename__ = "goal_sheets"
    __table_args__ = (
        Index("ix_goal_sheets_employee_cycle", "employee_id", "cycle_id", unique=True),
        Index("ix_goal_sheets_cycle_status", "cycle_id", "status"),
        Index("ix_goal_sheets_approved_by", "approved_by_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cycle_id = Column(Integer, ForeignKey("goal_cycles.id"), nullable=False)
    status = Column(SAEnum(GoalSheetStatus), default=GoalSheetStatus.DRAFT, nullable=False)
    submitted_at = Column(DateTime(timezone=True))
    approved_at = Column(DateTime(timezone=True))
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rework_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    employee = relationship("User", foreign_keys=[employee_id], back_populates="goal_sheets", lazy="joined")
    approved_by = relationship("User", foreign_keys=[approved_by_id], back_populates="approved_sheets", lazy="select")
    cycle = relationship("GoalCycle", back_populates="goal_sheets", lazy="select")
    goals = relationship(
        "Goal", back_populates="goal_sheet",
        cascade="all, delete-orphan",
        lazy="joined",  # always load goals with the sheet
        order_by="Goal.id"
    )


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        Index("ix_goals_goal_sheet_id", "goal_sheet_id"),
        Index("ix_goals_thrust_area_id", "thrust_area_id"),
        Index("ix_goals_uom_type", "uom_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    goal_sheet_id = Column(Integer, ForeignKey("goal_sheets.id"), nullable=False)
    thrust_area_id = Column(Integer, ForeignKey("thrust_areas.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    uom_type = Column(SAEnum(UoMType), nullable=False)
    target_value = Column(Float)
    target_date = Column(Date)
    weightage = Column(Float, nullable=False)
    is_shared = Column(Boolean, default=False, nullable=False)
    shared_from_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    is_locked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    goal_sheet = relationship("GoalSheet", back_populates="goals", lazy="select")
    thrust_area = relationship("ThrustArea", back_populates="goals", lazy="joined")
    check_ins = relationship(
        "CheckIn", back_populates="goal",
        cascade="all, delete-orphan",
        lazy="joined",  # always load check-ins with goals
        order_by="CheckIn.quarter"
    )
    shared_from = relationship("Goal", remote_side=[id], back_populates="shared_copies", lazy="select")
    shared_copies = relationship("Goal", back_populates="shared_from", lazy="select")


class CheckIn(Base):
    __tablename__ = "check_ins"
    __table_args__ = (
        Index("ix_check_ins_goal_quarter", "goal_id", "quarter", unique=True),
        Index("ix_check_ins_manager_id", "manager_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    quarter = Column(SAEnum(Quarter), nullable=False)
    actual_value = Column(Float)
    actual_date = Column(Date)
    status = Column(SAEnum(CheckInStatus), default=CheckInStatus.NOT_STARTED)
    progress_score = Column(Float)
    employee_notes = Column(Text)
    manager_comment = Column(Text)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    manager_checked_at = Column(DateTime(timezone=True))
    employee_updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    goal = relationship("Goal", back_populates="check_ins", lazy="select")
    manager = relationship("User", foreign_keys=[manager_id], lazy="select")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Integer, nullable=False)
    field_changed = Column(String(100))
    old_value = Column(Text)
    new_value = Column(Text)
    description = Column(Text)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="audit_logs", lazy="joined")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50))
    is_read = Column(Boolean, default=False, nullable=False)
    link = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications", lazy="select")


class EscalationRule(Base):
    __tablename__ = "escalation_rules"

    id = Column(Integer, primary_key=True, index=True)
    cycle_id = Column(Integer, ForeignKey("goal_cycles.id"), nullable=False)
    rule_type = Column(SAEnum(EscalationRuleType), nullable=False)
    days_threshold = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    cycle = relationship("GoalCycle", back_populates="escalation_rules", lazy="select")
    escalations = relationship("Escalation", back_populates="rule", lazy="select")


class Escalation(Base):
    __tablename__ = "escalations"
    __table_args__ = (
        Index("ix_escalations_open", "target_user_id", "resolved_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("escalation_rules.id"), nullable=False)
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    level = Column(Integer, default=1)
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    rule = relationship("EscalationRule", back_populates="escalations", lazy="joined")
    target_user = relationship("User", foreign_keys=[target_user_id], back_populates="escalations_received", lazy="joined")
