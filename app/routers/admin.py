from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, date
from typing import Optional
from ..database import get_db
from ..auth import get_current_user_from_cookie, get_password_hash
from ..models import (
    User, UserRole, GoalSheet, GoalSheetStatus, Goal,
    ThrustArea, GoalCycle, AuditLog, Notification,
    EscalationRule, EscalationRuleType, Escalation
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Templates(directory="app/templates")


def _require_admin(request: Request, db: Session):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()
    total_users = db.query(User).filter(User.role == UserRole.EMPLOYEE, User.is_active == True).count()
    total_managers = db.query(User).filter(User.role == UserRole.MANAGER, User.is_active == True).count()

    submitted = approved = rework = draft = 0
    completion_data = []
    if cycle:
        submitted = db.query(GoalSheet).filter(GoalSheet.cycle_id == cycle.id, GoalSheet.status == GoalSheetStatus.SUBMITTED).count()
        approved = db.query(GoalSheet).filter(GoalSheet.cycle_id == cycle.id, GoalSheet.status == GoalSheetStatus.APPROVED).count()
        rework = db.query(GoalSheet).filter(GoalSheet.cycle_id == cycle.id, GoalSheet.status == GoalSheetStatus.REWORK_REQUESTED).count()
        draft = db.query(GoalSheet).filter(GoalSheet.cycle_id == cycle.id, GoalSheet.status == GoalSheetStatus.DRAFT).count()
        # No sheet = not started
        employees_with_sheet = db.query(GoalSheet.employee_id).filter(GoalSheet.cycle_id == cycle.id).distinct().count()

    open_escalations = db.query(Escalation).filter(Escalation.resolved_at == None).count()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "total_users": total_users,
        "total_managers": total_managers,
        "submitted": submitted,
        "approved": approved,
        "rework": rework,
        "draft": draft,
        "open_escalations": open_escalations,
        "unread_count": unread_count,
    })


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    users = db.query(User).filter(User.is_active == True).order_by(User.name).all()
    managers = db.query(User).filter(User.role == UserRole.MANAGER, User.is_active == True).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "user": user,
        "users": users,
        "managers": managers,
        "UserRole": UserRole,
        "unread_count": unread_count,
    })


@router.post("/users/add")
def add_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    department: str = Form(default=""),
    manager_id: Optional[int] = Form(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return RedirectResponse(url="/admin/users?error=email_exists", status_code=302)

    new_user = User(
        name=name,
        email=email,
        hashed_password=get_password_hash(password),
        role=UserRole(role),
        department=department,
        manager_id=manager_id if manager_id else None
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/admin/users?success=added", status_code=302)


@router.post("/users/{user_id}/edit")
def edit_user(
    user_id: int,
    request: Request,
    name: str = Form(...),
    role: str = Form(...),
    department: str = Form(default=""),
    manager_id: Optional[int] = Form(default=None),
    is_active: bool = Form(default=True),
    db: Session = Depends(get_db)
):
    try:
        admin = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if admin.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/admin/users?error=not_found", status_code=302)

    target.name = name
    target.role = UserRole(role)
    target.department = department
    target.manager_id = manager_id if manager_id else None
    target.is_active = is_active
    db.commit()
    return RedirectResponse(url="/admin/users?success=updated", status_code=302)


@router.get("/cycles", response_class=HTMLResponse)
def cycles_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    cycles = db.query(GoalCycle).order_by(GoalCycle.year.desc()).all()
    thrust_areas = db.query(ThrustArea).filter(ThrustArea.is_active == True).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/cycles.html", {
        "request": request,
        "user": user,
        "cycles": cycles,
        "thrust_areas": thrust_areas,
        "unread_count": unread_count,
    })


@router.post("/cycles/add")
def add_cycle(
    request: Request,
    name: str = Form(...),
    year: int = Form(...),
    goal_setting_start: str = Form(...),
    goal_setting_end: str = Form(...),
    q1_start: str = Form(default=""),
    q1_end: str = Form(default=""),
    q2_start: str = Form(default=""),
    q2_end: str = Form(default=""),
    q3_start: str = Form(default=""),
    q3_end: str = Form(default=""),
    q4_start: str = Form(default=""),
    q4_end: str = Form(default=""),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    def parse_date(s):
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None

    cycle = GoalCycle(
        name=name,
        year=year,
        goal_setting_start=parse_date(goal_setting_start),
        goal_setting_end=parse_date(goal_setting_end),
        q1_start=parse_date(q1_start), q1_end=parse_date(q1_end),
        q2_start=parse_date(q2_start), q2_end=parse_date(q2_end),
        q3_start=parse_date(q3_start), q3_end=parse_date(q3_end),
        q4_start=parse_date(q4_start), q4_end=parse_date(q4_end),
    )
    db.add(cycle)
    db.commit()
    return RedirectResponse(url="/admin/cycles?success=added", status_code=302)


@router.post("/cycles/{cycle_id}/activate")
def activate_cycle(cycle_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    db.query(GoalCycle).update({"is_active": False})
    db.query(GoalCycle).filter(GoalCycle.id == cycle_id).update({"is_active": True})
    db.commit()
    return RedirectResponse(url="/admin/cycles?success=activated", status_code=302)


@router.post("/goals/{goal_id}/unlock")
def unlock_goal(goal_id: int, request: Request, reason: str = Form(...), db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    goal = db.query(Goal).filter(Goal.id == goal_id).first()
    if not goal:
        return RedirectResponse(url="/admin/dashboard?error=not_found", status_code=302)

    goal.is_locked = False
    log = AuditLog(
        user_id=user.id,
        action="ADMIN_UNLOCK",
        entity_type="Goal",
        entity_id=goal_id,
        description=f"Admin unlocked goal. Reason: {reason}"
    )
    db.add(log)
    db.commit()
    return RedirectResponse(url="/admin/dashboard?success=unlocked", status_code=302)


@router.get("/audit-log", response_class=HTMLResponse)
def audit_log_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    logs = db.query(AuditLog).options(
        joinedload(AuditLog.user)
    ).order_by(AuditLog.timestamp.desc()).limit(200).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/audit_log.html", {
        "request": request,
        "user": user,
        "logs": logs,
        "unread_count": unread_count,
    })


@router.get("/completion", response_class=HTMLResponse)
def completion_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()
    employees = db.query(User).filter(User.role == UserRole.EMPLOYEE, User.is_active == True).all()
    managers = db.query(User).filter(User.role == UserRole.MANAGER, User.is_active == True).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    emp_status = []
    if cycle:
        # Batch load all sheets for the cycle in one query
        all_emp_ids = [e.id for e in employees]
        sheets_in_cycle = db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(all_emp_ids)
        ).all() if all_emp_ids else []
        sheets_by_emp = {s.employee_id: s for s in sheets_in_cycle}
        for emp in employees:
            emp_status.append({"user": emp, "sheet": sheets_by_emp.get(emp.id)})

    mgr_status = []
    if managers:
        # Batch: all reports keyed by manager_id
        all_mgr_ids = [m.id for m in managers]
        all_reports = db.query(User).filter(
            User.manager_id.in_(all_mgr_ids), User.is_active == True
        ).all()
        reports_by_mgr: dict = {}
        emp_to_mgr: dict = {}
        for r in all_reports:
            reports_by_mgr.setdefault(r.manager_id, []).append(r)
            emp_to_mgr[r.id] = r.manager_id

        approved_by_mgr: dict = {}
        pending_by_mgr: dict = {}
        if cycle:
            # One query: all sheets in cycle for all employees under these managers
            all_report_ids = [r.id for r in all_reports]
            cycle_sheets = db.query(GoalSheet).filter(
                GoalSheet.cycle_id == cycle.id,
                GoalSheet.employee_id.in_(all_report_ids)
            ).all() if all_report_ids else []

            for s in cycle_sheets:
                if s.status == GoalSheetStatus.SUBMITTED:
                    emp_mgr = emp_to_mgr.get(s.employee_id)
                    if emp_mgr:
                        pending_by_mgr[emp_mgr] = pending_by_mgr.get(emp_mgr, 0) + 1
                if s.approved_by_id:
                    approved_by_mgr[s.approved_by_id] = approved_by_mgr.get(s.approved_by_id, 0) + 1

        for mgr in managers:
            team = reports_by_mgr.get(mgr.id, [])
            approved = approved_by_mgr.get(mgr.id, 0) if cycle else 0
            pending = pending_by_mgr.get(mgr.id, 0) if cycle else 0
            mgr_status.append({"user": mgr, "team_size": len(team), "approved": approved, "pending": pending})

    return templates.TemplateResponse("admin/completion.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "emp_status": emp_status,
        "mgr_status": mgr_status,
        "unread_count": unread_count,
        "GoalSheetStatus": GoalSheetStatus,
    })


@router.get("/escalations", response_class=HTMLResponse)
def escalations_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()
    escalations = db.query(Escalation).order_by(Escalation.triggered_at.desc()).all()
    rules = db.query(EscalationRule).all()
    cycles = db.query(GoalCycle).order_by(GoalCycle.year.desc()).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/escalations.html", {
        "request": request,
        "user": user,
        "cycle": cycle,
        "escalations": escalations,
        "rules": rules,
        "cycles": cycles,
        "unread_count": unread_count,
        "EscalationRuleType": EscalationRuleType,
    })


@router.post("/escalation-rules/add")
def add_escalation_rule(
    request: Request,
    cycle_id: int = Form(...),
    rule_type: str = Form(...),
    days_threshold: int = Form(...),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    rule = EscalationRule(
        cycle_id=cycle_id,
        rule_type=EscalationRuleType(rule_type),
        days_threshold=days_threshold
    )
    db.add(rule)
    db.commit()
    return RedirectResponse(url="/admin/escalations?success=rule_added", status_code=302)


@router.post("/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: int, request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if esc:
        esc.resolved_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(url="/admin/escalations?success=resolved", status_code=302)


@router.get("/thrust-areas", response_class=HTMLResponse)
def thrust_areas_page(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    areas = db.query(ThrustArea).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/thrust_areas.html", {
        "request": request,
        "user": user,
        "areas": areas,
        "unread_count": unread_count,
    })


@router.post("/thrust-areas/add")
def add_thrust_area(
    request: Request,
    name: str = Form(...),
    department: str = Form(default=""),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    area = ThrustArea(name=name, department=department)
    db.add(area)
    db.commit()
    return RedirectResponse(url="/admin/thrust-areas?success=added", status_code=302)

