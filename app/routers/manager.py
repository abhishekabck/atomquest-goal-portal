from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date
from typing import Optional
from ..database import get_db
from ..auth import get_current_user_from_cookie
from ..models import (
    User, UserRole, GoalSheet, GoalSheetStatus, Goal, UoMType,
    ThrustArea, GoalCycle, CheckIn, Quarter, CheckInStatus,
    AuditLog, Notification
)
from ..services.progress import compute_progress_score

router = APIRouter(prefix="/manager", tags=["manager"])
templates = Templates(directory="app/templates")


def _get_active_cycle(db: Session) -> Optional[GoalCycle]:
    return db.query(GoalCycle).filter(GoalCycle.is_active == True).first()


def _get_active_quarter(cycle: GoalCycle) -> Optional[str]:
    today = date.today()
    if cycle.q1_start and cycle.q1_end and cycle.q1_start <= today <= cycle.q1_end:
        return Quarter.Q1
    if cycle.q2_start and cycle.q2_end and cycle.q2_start <= today <= cycle.q2_end:
        return Quarter.Q2
    if cycle.q3_start and cycle.q3_end and cycle.q3_start <= today <= cycle.q3_end:
        return Quarter.Q3
    if cycle.q4_start and cycle.q4_end and cycle.q4_start <= today <= cycle.q4_end:
        return Quarter.Q4
    return None


@router.get("/dashboard", response_class=HTMLResponse)
def manager_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    cycle = _get_active_cycle(db)
    active_quarter = _get_active_quarter(cycle) if cycle else None

    team = db.query(User).filter(
        User.manager_id == user.id, User.is_active == True
    ).all()

    # Batch-load all sheets for this cycle in one query (N+1 prevention)
    team_ids = [m.id for m in team]
    sheets_by_emp: dict = {}
    if cycle and team_ids:
        sheets = db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(team_ids)
        ).all()
        sheets_by_emp = {s.employee_id: s for s in sheets}

    team_data = []
    for member in team:
        sheet = sheets_by_emp.get(member.id) if cycle else None
        team_data.append({"user": member, "sheet": sheet})

    pending_count = sum(
        1 for t in team_data
        if t["sheet"] and t["sheet"].status == GoalSheetStatus.SUBMITTED
    )
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("manager/dashboard.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "team_data": team_data,
        "pending_count": pending_count,
        "active_quarter": active_quarter,
        "unread_count": unread_count,
        "GoalSheetStatus": GoalSheetStatus,
    })


@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    cycle = _get_active_cycle(db)
    pending_sheets = []
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    if cycle:
        team_ids = [u.id for u in db.query(User.id).filter(
            User.manager_id == user.id, User.is_active == True
        ).all()]
        pending_sheets = db.query(GoalSheet).options(
            joinedload(GoalSheet.employee),
            joinedload(GoalSheet.goals).joinedload(Goal.thrust_area)
        ).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(team_ids),
            GoalSheet.status == GoalSheetStatus.SUBMITTED
        ).all()

    thrust_areas = db.query(ThrustArea).filter(ThrustArea.is_active == True).all()

    return templates.TemplateResponse("manager/approvals.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "pending_sheets": pending_sheets,
        "thrust_areas": thrust_areas,
        "unread_count": unread_count,
        "GoalSheetStatus": GoalSheetStatus,
        "UoMType": UoMType,
    })


@router.post("/goals/{goal_id}/edit-inline")
def edit_goal_inline(
    goal_id: int,
    request: Request,
    target_value: Optional[float] = Form(default=None),
    target_date: Optional[str] = Form(default=None),
    weightage: float = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    goal = db.query(Goal).join(GoalSheet).join(User, GoalSheet.employee_id == User.id).filter(
        Goal.id == goal_id,
        User.manager_id == user.id,
        GoalSheet.status == GoalSheetStatus.SUBMITTED
    ).first()

    if not goal:
        return RedirectResponse(url="/manager/approvals?error=not_found", status_code=302)

    sheet = goal.goal_sheet
    other_total = sum(g.weightage for g in sheet.goals if g.id != goal_id)
    if other_total + weightage > 100.01:
        return RedirectResponse(url="/manager/approvals?error=weight_exceeded", status_code=302)

    # Log audit
    log = AuditLog(
        user_id=user.id,
        action="MANAGER_EDIT",
        entity_type="Goal",
        entity_id=goal.id,
        field_changed="target/weightage",
        old_value=f"target={goal.target_value}, weightage={goal.weightage}",
        new_value=f"target={target_value}, weightage={weightage}",
        description=f"Manager {user.name} edited goal before approval"
    )
    db.add(log)

    goal.target_value = target_value
    if target_date:
        try:
            goal.target_date = date.fromisoformat(target_date)
        except ValueError:
            pass
    goal.weightage = weightage
    db.commit()
    return RedirectResponse(url="/manager/approvals?success=edited", status_code=302)


@router.post("/sheets/{sheet_id}/approve")
def approve_sheet(
    sheet_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    sheet = db.query(GoalSheet).join(User, GoalSheet.employee_id == User.id).filter(
        GoalSheet.id == sheet_id,
        User.manager_id == user.id,
        GoalSheet.status == GoalSheetStatus.SUBMITTED
    ).first()

    if not sheet:
        return RedirectResponse(url="/manager/approvals?error=not_found", status_code=302)

    total_weightage = sum(g.weightage for g in sheet.goals)
    if abs(total_weightage - 100.0) > 0.01:
        return RedirectResponse(url="/manager/approvals?error=weightage_not_100", status_code=302)

    sheet.status = GoalSheetStatus.APPROVED
    sheet.approved_at = datetime.utcnow()
    sheet.approved_by_id = user.id

    # Lock all goals
    for goal in sheet.goals:
        goal.is_locked = True

    # Log audit
    log = AuditLog(
        user_id=user.id,
        action="APPROVE",
        entity_type="GoalSheet",
        entity_id=sheet.id,
        description=f"Manager {user.name} approved goal sheet"
    )
    db.add(log)

    # Notify employee
    notif = Notification(
        user_id=sheet.employee_id,
        message="Your goal sheet has been approved! Goals are now locked.",
        type="GOAL_APPROVED",
        link="/employee/goals"
    )
    db.add(notif)

    db.commit()
    return RedirectResponse(url="/manager/approvals?success=approved", status_code=302)


@router.post("/sheets/{sheet_id}/return")
def return_for_rework(
    sheet_id: int,
    request: Request,
    rework_comment: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    sheet = db.query(GoalSheet).join(User, GoalSheet.employee_id == User.id).filter(
        GoalSheet.id == sheet_id,
        User.manager_id == user.id,
        GoalSheet.status == GoalSheetStatus.SUBMITTED
    ).first()

    if not sheet:
        return RedirectResponse(url="/manager/approvals?error=not_found", status_code=302)

    sheet.status = GoalSheetStatus.REWORK_REQUESTED
    sheet.rework_comment = rework_comment

    log = AuditLog(
        user_id=user.id,
        action="RETURN_FOR_REWORK",
        entity_type="GoalSheet",
        entity_id=sheet.id,
        description=f"Returned for rework: {rework_comment}"
    )
    db.add(log)

    notif = Notification(
        user_id=sheet.employee_id,
        message=f"Your goal sheet has been returned for rework: {rework_comment}",
        type="GOAL_REWORK",
        link="/employee/goals"
    )
    db.add(notif)

    db.commit()
    return RedirectResponse(url="/manager/approvals?success=returned", status_code=302)


@router.get("/checkins", response_class=HTMLResponse)
def manager_checkins(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    cycle = _get_active_cycle(db)
    active_quarter = _get_active_quarter(cycle) if cycle else None
    team_checkins = []
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    if cycle and active_quarter:
        team = db.query(User).filter(User.manager_id == user.id, User.is_active == True).all()
        team_ids = [m.id for m in team]
        # Batch load approved sheets with goals+check-ins in one query
        approved_sheets = db.query(GoalSheet).options(
            joinedload(GoalSheet.employee),
            joinedload(GoalSheet.goals).joinedload(Goal.check_ins),
            joinedload(GoalSheet.goals).joinedload(Goal.thrust_area),
        ).filter(
            GoalSheet.employee_id.in_(team_ids),
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.status == GoalSheetStatus.APPROVED
        ).all()

        sheet_by_emp = {s.employee_id: s for s in approved_sheets}
        for member in team:
            sheet = sheet_by_emp.get(member.id)
            if sheet:
                goals_ci = []
                for goal in sheet.goals:
                    ci = next((c for c in goal.check_ins if c.quarter == active_quarter), None)
                    goals_ci.append((goal, ci))
                team_checkins.append({"member": member, "sheet": sheet, "goals_ci": goals_ci})

    return templates.TemplateResponse("manager/checkins.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "active_quarter": active_quarter,
        "team_checkins": team_checkins,
        "unread_count": unread_count,
        "CheckInStatus": CheckInStatus,
        "UoMType": UoMType,
    })


@router.post("/checkins/{checkin_id}/comment")
def add_manager_comment(
    checkin_id: int,
    request: Request,
    manager_comment: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    ci = db.query(CheckIn).join(Goal).join(GoalSheet).join(
        User, GoalSheet.employee_id == User.id
    ).filter(
        CheckIn.id == checkin_id,
        User.manager_id == user.id
    ).first()

    if not ci:
        return RedirectResponse(url="/manager/checkins?error=not_found", status_code=302)

    ci.manager_comment = manager_comment
    ci.manager_id = user.id
    ci.manager_checked_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(url="/manager/checkins?success=commented", status_code=302)


@router.post("/shared-goals/push")
def push_shared_goal(
    request: Request,
    thrust_area_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    uom_type: str = Form(...),
    target_value: Optional[float] = Form(default=None),
    target_date: Optional[str] = Form(default=None),
    employee_ids: str = Form(...),  # comma-separated IDs
    default_weightage: float = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.MANAGER, UserRole.ADMIN):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    cycle = _get_active_cycle(db)
    if not cycle:
        return RedirectResponse(url="/manager/approvals?error=no_cycle", status_code=302)

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            pass

    ids = [int(x.strip()) for x in employee_ids.split(",") if x.strip().isdigit()]

    # Create a "master" goal first â€” attached to manager's own tracking
    # Then create shared copies per employee
    first_goal_id = None
    for emp_id in ids:
        emp = db.query(User).filter(User.id == emp_id, User.manager_id == user.id).first()
        if not emp:
            continue

        sheet = db.query(GoalSheet).filter(
            GoalSheet.employee_id == emp_id,
            GoalSheet.cycle_id == cycle.id
        ).first()
        if not sheet:
            sheet = GoalSheet(employee_id=emp_id, cycle_id=cycle.id)
            db.add(sheet)
            db.flush()

        if sheet.status == GoalSheetStatus.APPROVED:
            continue

        if len(sheet.goals) >= 8:
            continue

        goal = Goal(
            goal_sheet_id=sheet.id,
            thrust_area_id=thrust_area_id,
            title=title,
            description=description,
            uom_type=UoMType(uom_type),
            target_value=target_value,
            target_date=parsed_date,
            weightage=default_weightage,
            is_shared=True,
            shared_from_id=first_goal_id,
        )
        db.add(goal)
        db.flush()
        if first_goal_id is None:
            first_goal_id = goal.id
            goal.shared_from_id = None  # primary

        notif = Notification(
            user_id=emp_id,
            message=f"A shared goal '{title}' has been added to your goal sheet by {user.name}.",
            type="SHARED_GOAL",
            link="/employee/goals"
        )
        db.add(notif)

    db.commit()
    return RedirectResponse(url="/manager/approvals?success=shared", status_code=302)

