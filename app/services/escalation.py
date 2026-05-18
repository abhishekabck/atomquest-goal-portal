from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from ..models import (
    GoalCycle, GoalSheet, GoalSheetStatus, CheckIn, Quarter,
    EscalationRule, EscalationRuleType, Escalation, User, UserRole,
    Notification
)


def run_escalation_checks(db: Session):
    """Run all active escalation rules for the current active cycle."""
    cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()
    if not cycle:
        return

    rules = db.query(EscalationRule).filter(
        EscalationRule.cycle_id == cycle.id,
        EscalationRule.is_active == True
    ).all()

    today = date.today()
    for rule in rules:
        if rule.rule_type == EscalationRuleType.GOAL_NOT_SUBMITTED:
            _check_goal_not_submitted(db, cycle, rule, today)
        elif rule.rule_type == EscalationRuleType.GOAL_NOT_APPROVED:
            _check_goal_not_approved(db, cycle, rule, today)
        elif rule.rule_type == EscalationRuleType.CHECKIN_NOT_COMPLETED:
            _check_checkin_not_completed(db, cycle, rule, today)

    db.commit()


def _check_goal_not_submitted(db: Session, cycle: GoalCycle, rule: EscalationRule, today: date):
    if not cycle.goal_setting_start:
        return

    days_since_open = (today - cycle.goal_setting_start).days
    if days_since_open < rule.days_threshold:
        return

    # Find employees who haven't submitted
    employees = db.query(User).filter(
        User.role == UserRole.EMPLOYEE, User.is_active == True
    ).all()

    for emp in employees:
        sheet = db.query(GoalSheet).filter(
            GoalSheet.employee_id == emp.id,
            GoalSheet.cycle_id == cycle.id
        ).first()

        if not sheet or sheet.status == GoalSheetStatus.DRAFT:
            _create_escalation_if_not_exists(db, rule, emp, f"Goals not submitted after {rule.days_threshold} days")


def _check_goal_not_approved(db: Session, cycle: GoalCycle, rule: EscalationRule, today: date):
    submitted_sheets = db.query(GoalSheet).filter(
        GoalSheet.cycle_id == cycle.id,
        GoalSheet.status == GoalSheetStatus.SUBMITTED
    ).all()

    for sheet in submitted_sheets:
        if not sheet.submitted_at:
            continue
        days_pending = (today - sheet.submitted_at.date()).days
        if days_pending >= rule.days_threshold:
            manager = sheet.employee.manager
            if manager:
                _create_escalation_if_not_exists(db, rule, manager, f"Goal approval pending for {sheet.employee.name}")


def _check_checkin_not_completed(db: Session, cycle: GoalCycle, rule: EscalationRule, today: date):
    active_quarter = _get_active_quarter(cycle, today)
    if not active_quarter:
        return

    quarter_start = _get_quarter_start(cycle, active_quarter)
    if not quarter_start:
        return

    days_since_start = (today - quarter_start).days
    if days_since_start < rule.days_threshold:
        return

    approved_sheets = db.query(GoalSheet).filter(
        GoalSheet.cycle_id == cycle.id,
        GoalSheet.status == GoalSheetStatus.APPROVED
    ).all()

    for sheet in approved_sheets:
        all_done = True
        for goal in sheet.goals:
            ci = next((c for c in goal.check_ins if c.quarter == active_quarter), None)
            if not ci or not ci.employee_updated_at:
                all_done = False
                break
        if not all_done:
            _create_escalation_if_not_exists(db, rule, sheet.employee, f"Q{active_quarter} check-in not completed")


def _create_escalation_if_not_exists(db: Session, rule: EscalationRule, user: User, notes: str):
    existing = db.query(Escalation).filter(
        Escalation.rule_id == rule.id,
        Escalation.target_user_id == user.id,
        Escalation.resolved_at == None
    ).first()

    if not existing:
        esc = Escalation(rule_id=rule.id, target_user_id=user.id, notes=notes)
        db.add(esc)
        # Also create a notification
        notif = Notification(
            user_id=user.id,
            message=f"Action required: {notes}",
            type="ESCALATION",
            link="/goals"
        )
        db.add(notif)


def _get_active_quarter(cycle: GoalCycle, today: date) -> str | None:
    if cycle.q1_start and cycle.q1_end and cycle.q1_start <= today <= cycle.q1_end:
        return Quarter.Q1
    if cycle.q2_start and cycle.q2_end and cycle.q2_start <= today <= cycle.q2_end:
        return Quarter.Q2
    if cycle.q3_start and cycle.q3_end and cycle.q3_start <= today <= cycle.q3_end:
        return Quarter.Q3
    if cycle.q4_start and cycle.q4_end and cycle.q4_start <= today <= cycle.q4_end:
        return Quarter.Q4
    return None


def _get_quarter_start(cycle: GoalCycle, quarter: str):
    mapping = {
        Quarter.Q1: cycle.q1_start,
        Quarter.Q2: cycle.q2_start,
        Quarter.Q3: cycle.q3_start,
        Quarter.Q4: cycle.q4_start,
    }
    return mapping.get(quarter)
