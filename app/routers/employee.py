from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from datetime import date, datetime
from typing import Optional
from ..database import get_db
from ..auth import get_current_user_from_cookie, require_role
from ..models import (
    User, UserRole, GoalSheet, GoalSheetStatus, Goal, UoMType,
    ThrustArea, GoalCycle, CheckIn, Quarter, CheckInStatus,
    AuditLog, Notification
)
from ..services.progress import compute_progress_score

router = APIRouter(prefix="/employee", tags=["employee"])
templates = Templates(directory="app/templates")


def _get_active_cycle(db: Session) -> Optional[GoalCycle]:
    return db.query(GoalCycle).filter(GoalCycle.is_active == True).first()


def _get_or_create_sheet(db: Session, employee_id: int, cycle: GoalCycle) -> GoalSheet:
    sheet = db.query(GoalSheet).options(
        joinedload(GoalSheet.goals).joinedload(Goal.check_ins),
        joinedload(GoalSheet.goals).joinedload(Goal.thrust_area),
        joinedload(GoalSheet.goals).joinedload(Goal.shared_copies),
    ).filter(
        GoalSheet.employee_id == employee_id,
        GoalSheet.cycle_id == cycle.id
    ).first()
    if not sheet:
        sheet = GoalSheet(employee_id=employee_id, cycle_id=cycle.id)
        db.add(sheet)
        db.commit()
        db.refresh(sheet)
    return sheet


def _is_goal_setting_open(cycle: GoalCycle) -> bool:
    today = date.today()
    return cycle.goal_setting_start <= today <= cycle.goal_setting_end


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
def employee_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    cycle = _get_active_cycle(db)
    sheet = None
    goals_with_checkins = []
    active_quarter = None
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    if cycle:
        active_quarter = _get_active_quarter(cycle)
        if db.query(GoalSheet).filter(GoalSheet.employee_id == user.id, GoalSheet.cycle_id == cycle.id).first():
            sheet = _get_or_create_sheet(db, user.id, cycle)
            for goal in sheet.goals:
                ci = None
                if active_quarter:
                    ci = next((c for c in goal.check_ins if c.quarter == active_quarter), None)
                goals_with_checkins.append((goal, ci))

    return templates.TemplateResponse("employee/dashboard.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "sheet": sheet,
        "goals_with_checkins": goals_with_checkins,
        "active_quarter": active_quarter,
        "unread_count": unread_count,
        "GoalSheetStatus": GoalSheetStatus,
        "Quarter": Quarter,
    })


@router.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    cycle = _get_active_cycle(db)
    sheet = None
    thrust_areas = db.query(ThrustArea).filter(ThrustArea.is_active == True).all()
    goal_setting_open = False
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    if cycle:
        sheet = _get_or_create_sheet(db, user.id, cycle)
        goal_setting_open = _is_goal_setting_open(cycle)

    return templates.TemplateResponse("employee/goals.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "sheet": sheet,
        "thrust_areas": thrust_areas,
        "goal_setting_open": goal_setting_open,
        "UoMType": UoMType,
        "GoalSheetStatus": GoalSheetStatus,
        "unread_count": unread_count,
    })


@router.post("/goals/add")
def add_goal(
    request: Request,
    thrust_area_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    uom_type: str = Form(...),
    target_value: Optional[float] = Form(default=None),
    target_date: Optional[str] = Form(default=None),
    weightage: float = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    cycle = _get_active_cycle(db)
    if not cycle:
        return RedirectResponse(url="/employee/goals?error=no_cycle", status_code=302)

    sheet = _get_or_create_sheet(db, user.id, cycle)

    if sheet.status not in (GoalSheetStatus.DRAFT, GoalSheetStatus.REWORK_REQUESTED):
        return RedirectResponse(url="/employee/goals?error=locked", status_code=302)

    if not _is_goal_setting_open(cycle):
        return RedirectResponse(url="/employee/goals?error=window_closed", status_code=302)

    # Validation
    if len(sheet.goals) >= 8:
        return RedirectResponse(url="/employee/goals?error=max_goals", status_code=302)

    if weightage < 10:
        return RedirectResponse(url="/employee/goals?error=min_weight", status_code=302)

    current_total = sum(g.weightage for g in sheet.goals)
    if current_total + weightage > 100:
        return RedirectResponse(url=f"/employee/goals?error=weight_exceeded", status_code=302)

    parsed_date = None
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            pass

    goal = Goal(
        goal_sheet_id=sheet.id,
        thrust_area_id=thrust_area_id,
        title=title,
        description=description,
        uom_type=UoMType(uom_type),
        target_value=target_value,
        target_date=parsed_date,
        weightage=weightage,
        is_locked=False
    )
    db.add(goal)
    db.commit()
    return RedirectResponse(url="/employee/goals?success=added", status_code=302)


@router.post("/goals/{goal_id}/delete")
def delete_goal(goal_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    goal = db.query(Goal).join(GoalSheet).filter(
        Goal.id == goal_id,
        GoalSheet.employee_id == user.id
    ).first()

    if not goal:
        return RedirectResponse(url="/employee/goals?error=not_found", status_code=302)

    if goal.is_locked or goal.goal_sheet.status == GoalSheetStatus.APPROVED:
        return RedirectResponse(url="/employee/goals?error=locked", status_code=302)

    db.delete(goal)
    db.commit()
    return RedirectResponse(url="/employee/goals?success=deleted", status_code=302)


@router.post("/goals/{goal_id}/edit")
def edit_goal(
    goal_id: int,
    request: Request,
    thrust_area_id: int = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    uom_type: str = Form(...),
    target_value: Optional[float] = Form(default=None),
    target_date: Optional[str] = Form(default=None),
    weightage: float = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    goal = db.query(Goal).join(GoalSheet).filter(
        Goal.id == goal_id,
        GoalSheet.employee_id == user.id
    ).first()

    if not goal:
        return RedirectResponse(url="/employee/goals?error=not_found", status_code=302)

    sheet = goal.goal_sheet
    if goal.is_locked or sheet.status == GoalSheetStatus.APPROVED:
        return RedirectResponse(url="/employee/goals?error=locked", status_code=302)

    if goal.is_shared:
        # Shared goals: only weightage can be changed
        if weightage < 10:
            return RedirectResponse(url="/employee/goals?error=min_weight", status_code=302)
        other_total = sum(g.weightage for g in sheet.goals if g.id != goal_id)
        if other_total + weightage > 100:
            return RedirectResponse(url="/employee/goals?error=weight_exceeded", status_code=302)
        goal.weightage = weightage
    else:
        if weightage < 10:
            return RedirectResponse(url="/employee/goals?error=min_weight", status_code=302)
        other_total = sum(g.weightage for g in sheet.goals if g.id != goal_id)
        if other_total + weightage > 100:
            return RedirectResponse(url="/employee/goals?error=weight_exceeded", status_code=302)

        parsed_date = None
        if target_date:
            try:
                parsed_date = date.fromisoformat(target_date)
            except ValueError:
                pass

        goal.thrust_area_id = thrust_area_id
        goal.title = title
        goal.description = description
        goal.uom_type = UoMType(uom_type)
        goal.target_value = target_value
        goal.target_date = parsed_date
        goal.weightage = weightage

    db.commit()
    return RedirectResponse(url="/employee/goals?success=updated", status_code=302)


@router.post("/goals/submit")
def submit_goals(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    cycle = _get_active_cycle(db)
    if not cycle:
        return RedirectResponse(url="/employee/goals?error=no_cycle", status_code=302)

    sheet = db.query(GoalSheet).filter(
        GoalSheet.employee_id == user.id,
        GoalSheet.cycle_id == cycle.id
    ).first()

    if not sheet:
        return RedirectResponse(url="/employee/goals?error=no_sheet", status_code=302)

    if sheet.status not in (GoalSheetStatus.DRAFT, GoalSheetStatus.REWORK_REQUESTED):
        return RedirectResponse(url="/employee/goals?error=already_submitted", status_code=302)

    if not sheet.goals:
        return RedirectResponse(url="/employee/goals?error=no_goals", status_code=302)

    total_weightage = sum(g.weightage for g in sheet.goals)
    if abs(total_weightage - 100.0) > 0.01:
        return RedirectResponse(url=f"/employee/goals?error=weightage_not_100", status_code=302)

    sheet.status = GoalSheetStatus.SUBMITTED
    sheet.submitted_at = datetime.utcnow()

    # Notify manager
    if user.manager_id:
        notif = Notification(
            user_id=user.manager_id,
            message=f"{user.name} has submitted their goals for review.",
            type="GOAL_SUBMITTED",
            link="/manager/approvals"
        )
        db.add(notif)

    db.commit()
    return RedirectResponse(url="/employee/goals?success=submitted", status_code=302)


@router.get("/checkin", response_class=HTMLResponse)
def checkin_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    cycle = _get_active_cycle(db)
    active_quarter = None
    sheet = None
    goals_with_checkins = []
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    if cycle:
        active_quarter = _get_active_quarter(cycle)
        sheet = db.query(GoalSheet).filter(
            GoalSheet.employee_id == user.id,
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.status == GoalSheetStatus.APPROVED
        ).first()

        if sheet:
            for goal in sheet.goals:
                ci = None
                if active_quarter:
                    ci = next((c for c in goal.check_ins if c.quarter == active_quarter), None)
                goals_with_checkins.append((goal, ci))

    return templates.TemplateResponse("employee/checkin.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "sheet": sheet,
        "active_quarter": active_quarter,
        "goals_with_checkins": goals_with_checkins,
        "CheckInStatus": CheckInStatus,
        "UoMType": UoMType,
        "unread_count": unread_count,
        "quarters": [Quarter.Q1, Quarter.Q2, Quarter.Q3, Quarter.Q4],
    })


@router.post("/checkin/{goal_id}")
def update_checkin(
    goal_id: int,
    request: Request,
    quarter: str = Form(...),
    actual_value: Optional[float] = Form(default=None),
    actual_date: Optional[str] = Form(default=None),
    status: str = Form(...),
    employee_notes: str = Form(default=""),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    goal = db.query(Goal).join(GoalSheet).filter(
        Goal.id == goal_id,
        GoalSheet.employee_id == user.id,
        GoalSheet.status == GoalSheetStatus.APPROVED
    ).first()

    if not goal:
        return RedirectResponse(url="/employee/checkin?error=not_found", status_code=302)

    q = Quarter(quarter)
    ci = db.query(CheckIn).filter(CheckIn.goal_id == goal_id, CheckIn.quarter == q).first()

    parsed_date = None
    if actual_date:
        try:
            parsed_date = date.fromisoformat(actual_date)
        except ValueError:
            pass

    if not ci:
        ci = CheckIn(goal_id=goal_id, quarter=q)
        db.add(ci)

    ci.actual_value = actual_value
    ci.actual_date = parsed_date
    ci.status = CheckInStatus(status)
    ci.employee_notes = employee_notes
    ci.employee_updated_at = datetime.utcnow()

    # Compute progress score
    ci.progress_score = compute_progress_score(goal, ci)

    # Sync shared goal achievements
    if goal.shared_copies:
        for shared_goal in goal.shared_copies:
            shared_ci = db.query(CheckIn).filter(
                CheckIn.goal_id == shared_goal.id, CheckIn.quarter == q
            ).first()
            if not shared_ci:
                shared_ci = CheckIn(goal_id=shared_goal.id, quarter=q)
                db.add(shared_ci)
            shared_ci.actual_value = actual_value
            shared_ci.actual_date = parsed_date
            shared_ci.status = CheckInStatus(status)
            shared_ci.progress_score = compute_progress_score(shared_goal, shared_ci)

    db.commit()
    return RedirectResponse(url="/employee/checkin?success=saved", status_code=302)


@router.get("/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    notifications = db.query(Notification).filter(
        Notification.user_id == user.id
    ).order_by(Notification.created_at.desc()).limit(50).all()

    # Mark all as read
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).update({"is_read": True})
    db.commit()

    return templates.TemplateResponse("employee/notifications.html", {
        "request": request,
        "user": user,
        "notifications": notifications,
        "unread_count": 0,
    })

