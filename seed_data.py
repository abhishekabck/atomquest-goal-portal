"""Run once to populate demo data: python seed_data.py"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import date, datetime
from app.database import engine, SessionLocal, Base
from app.models import *
from app.auth import get_password_hash

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def seed():
    if db.query(User).first():
        print("Database already seeded. Skipping.")
        return

    # ── Users ──────────────────────────────────────────────────────────
    admin = User(name="HR Admin", email="admin@atomberg.com",
                 hashed_password=get_password_hash("admin123"),
                 role=UserRole.ADMIN, department="HR")
    db.add(admin); db.flush()

    mgr1 = User(name="Rajesh Kumar", email="manager@atomberg.com",
                hashed_password=get_password_hash("manager123"),
                role=UserRole.MANAGER, department="Sales")
    mgr2 = User(name="Priya Sharma", email="priya.mgr@atomberg.com",
                hashed_password=get_password_hash("manager123"),
                role=UserRole.MANAGER, department="Engineering")
    db.add_all([mgr1, mgr2]); db.flush()

    emp1 = User(name="Alice Fernandes", email="alice@atomberg.com",
                hashed_password=get_password_hash("emp123"),
                role=UserRole.EMPLOYEE, department="Sales", manager_id=mgr1.id)
    emp2 = User(name="Bob Patel", email="bob@atomberg.com",
                hashed_password=get_password_hash("emp123"),
                role=UserRole.EMPLOYEE, department="Sales", manager_id=mgr1.id)
    emp3 = User(name="Carol Singh", email="carol@atomberg.com",
                hashed_password=get_password_hash("emp123"),
                role=UserRole.EMPLOYEE, department="Engineering", manager_id=mgr2.id)
    emp4 = User(name="David Nair", email="david@atomberg.com",
                hashed_password=get_password_hash("emp123"),
                role=UserRole.EMPLOYEE, department="Engineering", manager_id=mgr2.id)
    emp5 = User(name="Eva Menon", email="eva@atomberg.com",
                hashed_password=get_password_hash("emp123"),
                role=UserRole.EMPLOYEE, department="Sales", manager_id=mgr1.id)
    db.add_all([emp1, emp2, emp3, emp4, emp5]); db.flush()

    # ── Thrust Areas ───────────────────────────────────────────────────
    areas = [
        ThrustArea(name="Revenue Growth", department="Sales"),
        ThrustArea(name="Customer Satisfaction", department="Sales"),
        ThrustArea(name="Operational Efficiency", department="Operations"),
        ThrustArea(name="Product Quality", department="Engineering"),
        ThrustArea(name="Safety & Compliance", department="Operations"),
        ThrustArea(name="Team Development", department="HR"),
        ThrustArea(name="Cost Optimization", department="Finance"),
        ThrustArea(name="Digital Transformation", department="Engineering"),
    ]
    db.add_all(areas); db.flush()

    # ── Active Cycle ───────────────────────────────────────────────────
    cycle = GoalCycle(
        name="FY 2025-26",
        year=2025,
        goal_setting_start=date(2025, 5, 1),
        goal_setting_end=date(2025, 5, 31),
        q1_start=date(2025, 7, 1),   q1_end=date(2025, 7, 31),
        q2_start=date(2025, 10, 1),  q2_end=date(2025, 10, 31),
        q3_start=date(2026, 1, 1),   q3_end=date(2026, 1, 31),
        q4_start=date(2026, 3, 1),   q4_end=date(2026, 4, 30),
        is_active=True,
    )
    db.add(cycle); db.flush()

    # ── Escalation Rules ───────────────────────────────────────────────
    rules = [
        EscalationRule(cycle_id=cycle.id, rule_type=EscalationRuleType.GOAL_NOT_SUBMITTED, days_threshold=14),
        EscalationRule(cycle_id=cycle.id, rule_type=EscalationRuleType.GOAL_NOT_APPROVED, days_threshold=7),
        EscalationRule(cycle_id=cycle.id, rule_type=EscalationRuleType.CHECKIN_NOT_COMPLETED, days_threshold=10),
    ]
    db.add_all(rules); db.flush()

    # ── Alice: APPROVED sheet with Q1 check-ins ────────────────────────
    sheet1 = GoalSheet(employee_id=emp1.id, cycle_id=cycle.id,
                       status=GoalSheetStatus.APPROVED,
                       submitted_at=datetime(2025, 5, 10),
                       approved_at=datetime(2025, 5, 15),
                       approved_by_id=mgr1.id)
    db.add(sheet1); db.flush()

    g1 = Goal(goal_sheet_id=sheet1.id, thrust_area_id=areas[0].id,
              title="Achieve Q3 Sales Revenue Target",
              description="Drive regional sales to hit 1.2Cr revenue",
              uom_type=UoMType.NUMERIC_MIN, target_value=12000000,
              weightage=40, is_locked=True)
    g2 = Goal(goal_sheet_id=sheet1.id, thrust_area_id=areas[1].id,
              title="Improve Customer NPS Score",
              uom_type=UoMType.NUMERIC_MIN, target_value=80,
              weightage=30, is_locked=True)
    g3 = Goal(goal_sheet_id=sheet1.id, thrust_area_id=areas[2].id,
              title="Reduce Order TAT",
              description="Lower average turnaround time from 5 to 3 days",
              uom_type=UoMType.NUMERIC_MAX, target_value=3,
              weightage=20, is_locked=True)
    g4 = Goal(goal_sheet_id=sheet1.id, thrust_area_id=areas[4].id,
              title="Zero Safety Incidents",
              uom_type=UoMType.ZERO_BASED, target_value=0,
              weightage=10, is_locked=True)
    db.add_all([g1, g2, g3, g4]); db.flush()

    # Q1 check-ins for Alice
    ci1 = CheckIn(goal_id=g1.id, quarter=Quarter.Q1, actual_value=9500000,
                  status=CheckInStatus.ON_TRACK, progress_score=79.2,
                  employee_notes="Strong pipeline, on track for Q3",
                  manager_comment="Good progress, keep it up!",
                  employee_updated_at=datetime(2025, 7, 15),
                  manager_checked_at=datetime(2025, 7, 16), manager_id=mgr1.id)
    ci2 = CheckIn(goal_id=g2.id, quarter=Quarter.Q1, actual_value=72,
                  status=CheckInStatus.ON_TRACK, progress_score=90.0,
                  employee_notes="Survey response rate improved",
                  employee_updated_at=datetime(2025, 7, 15))
    ci3 = CheckIn(goal_id=g3.id, quarter=Quarter.Q1, actual_value=4,
                  status=CheckInStatus.ON_TRACK, progress_score=75.0,
                  employee_updated_at=datetime(2025, 7, 15))
    ci4 = CheckIn(goal_id=g4.id, quarter=Quarter.Q1, actual_value=0,
                  status=CheckInStatus.COMPLETED, progress_score=100.0,
                  employee_updated_at=datetime(2025, 7, 15))
    db.add_all([ci1, ci2, ci3, ci4])

    # Q2 check-ins for Alice
    ci1q2 = CheckIn(goal_id=g1.id, quarter=Quarter.Q2, actual_value=10800000,
                    status=CheckInStatus.ON_TRACK, progress_score=90.0,
                    employee_updated_at=datetime(2025, 10, 12))
    ci2q2 = CheckIn(goal_id=g2.id, quarter=Quarter.Q2, actual_value=78,
                    status=CheckInStatus.ON_TRACK, progress_score=97.5,
                    employee_updated_at=datetime(2025, 10, 12))
    db.add_all([ci1q2, ci2q2])

    # ── Bob: SUBMITTED sheet (pending approval) ────────────────────────
    sheet2 = GoalSheet(employee_id=emp2.id, cycle_id=cycle.id,
                       status=GoalSheetStatus.SUBMITTED,
                       submitted_at=datetime(2025, 5, 18))
    db.add(sheet2); db.flush()

    bg1 = Goal(goal_sheet_id=sheet2.id, thrust_area_id=areas[0].id,
               title="New Customer Acquisition", uom_type=UoMType.NUMERIC_MIN,
               target_value=50, weightage=35, is_locked=False)
    bg2 = Goal(goal_sheet_id=sheet2.id, thrust_area_id=areas[6].id,
               title="Reduce Travel Expenses by 15%", uom_type=UoMType.PERCENT_MAX,
               target_value=15, weightage=25, is_locked=False)
    bg3 = Goal(goal_sheet_id=sheet2.id, thrust_area_id=areas[7].id,
               title="Complete CRM Migration", uom_type=UoMType.TIMELINE,
               target_date=date(2025, 9, 30), weightage=25, is_locked=False)
    bg4 = Goal(goal_sheet_id=sheet2.id, thrust_area_id=areas[5].id,
               title="Complete 40 hrs of Training", uom_type=UoMType.NUMERIC_MIN,
               target_value=40, weightage=15, is_locked=False)
    db.add_all([bg1, bg2, bg3, bg4])

    # ── Carol: REWORK_REQUESTED ────────────────────────────────────────
    sheet3 = GoalSheet(employee_id=emp3.id, cycle_id=cycle.id,
                       status=GoalSheetStatus.REWORK_REQUESTED,
                       submitted_at=datetime(2025, 5, 12),
                       rework_comment="Please add specific numeric targets to all goals and ensure total weightage equals 100%.")
    db.add(sheet3); db.flush()

    cg1 = Goal(goal_sheet_id=sheet3.id, thrust_area_id=areas[3].id,
               title="Improve Code Review Coverage", uom_type=UoMType.PERCENT_MIN,
               target_value=90, weightage=50, is_locked=False)
    cg2 = Goal(goal_sheet_id=sheet3.id, thrust_area_id=areas[7].id,
               title="Launch New API Gateway", uom_type=UoMType.TIMELINE,
               target_date=date(2025, 12, 31), weightage=50, is_locked=False)
    db.add_all([cg1, cg2])

    # ── David: DRAFT ───────────────────────────────────────────────────
    sheet4 = GoalSheet(employee_id=emp4.id, cycle_id=cycle.id,
                       status=GoalSheetStatus.DRAFT)
    db.add(sheet4); db.flush()

    dg1 = Goal(goal_sheet_id=sheet4.id, thrust_area_id=areas[3].id,
               title="Reduce Bug Escape Rate", uom_type=UoMType.PERCENT_MAX,
               target_value=2, weightage=40, is_locked=False)
    dg2 = Goal(goal_sheet_id=sheet4.id, thrust_area_id=areas[4].id,
               title="Zero Critical Security Incidents", uom_type=UoMType.ZERO_BASED,
               weightage=30, is_locked=False)
    db.add_all([dg1, dg2])

    # ── Audit Log samples ──────────────────────────────────────────────
    logs = [
        AuditLog(user_id=mgr1.id, action="APPROVE", entity_type="GoalSheet",
                 entity_id=sheet1.id, description=f"Manager {mgr1.name} approved goal sheet"),
        AuditLog(user_id=mgr1.id, action="RETURN_FOR_REWORK", entity_type="GoalSheet",
                 entity_id=sheet3.id, description="Returned for rework: Please add specific numeric targets"),
    ]
    db.add_all(logs)

    # ── Notifications ──────────────────────────────────────────────────
    notifs = [
        Notification(user_id=emp1.id, message="Your goal sheet has been approved! Goals are now locked.",
                     type="GOAL_APPROVED", link="/employee/goals", is_read=True),
        Notification(user_id=emp3.id, message="Your goal sheet has been returned for rework.",
                     type="GOAL_REWORK", link="/employee/goals"),
        Notification(user_id=mgr1.id, message="Bob Patel has submitted their goals for review.",
                     type="GOAL_SUBMITTED", link="/manager/approvals"),
    ]
    db.add_all(notifs)

    db.commit()
    print("Database seeded successfully!")
    print("\nDemo credentials:")
    print("  Admin:   admin@atomberg.com   / admin123")
    print("  Manager: manager@atomberg.com / manager123")
    print("  Employee:alice@atomberg.com   / emp123")
    print("\nReady! Run: python run.py")


if __name__ == "__main__":
    seed()
    db.close()
