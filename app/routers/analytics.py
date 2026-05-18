from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..auth import get_current_user_from_cookie
from ..models import (
    User, UserRole, GoalSheet, GoalSheetStatus, Goal, UoMType,
    GoalCycle, CheckIn, Quarter, ThrustArea, Notification
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
templates = Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
def analytics_dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return RedirectResponse(url="/login", status_code=302)

    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    cycles = db.query(GoalCycle).order_by(GoalCycle.year.desc()).all()
    unread_count = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False
    ).count()

    return templates.TemplateResponse("admin/analytics.html", {
        "request": request,
        "user": user,
        "cycles": cycles,
        "unread_count": unread_count,
    })


@router.get("/qoq-trends")
def qoq_trends(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return JSONResponse({"labels": [], "datasets": []})

    labels = ["Q1", "Q2", "Q3", "Q4"]
    quarters = [Quarter.Q1, Quarter.Q2, Quarter.Q3, Quarter.Q4]

    # Average progress per quarter
    avg_scores = []
    for q in quarters:
        checkins = db.query(CheckIn).join(Goal).join(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.status == GoalSheetStatus.APPROVED,
            CheckIn.quarter == q,
            CheckIn.progress_score != None
        ).all()
        if checkins:
            avg = sum(c.progress_score for c in checkins) / len(checkins)
        else:
            avg = 0
        avg_scores.append(round(avg, 2))

    return JSONResponse({
        "labels": labels,
        "datasets": [{
            "label": f"Avg Progress Score ({cycle.year})",
            "data": avg_scores,
            "borderColor": "#1E3A5F",
            "backgroundColor": "rgba(30,58,95,0.15)",
            "fill": True,
            "tension": 0.4,
            "pointRadius": 6,
            "pointBackgroundColor": "#F57C00",
        }]
    })


@router.get("/goal-distribution")
def goal_distribution(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return JSONResponse({"labels": [], "data": []})

    # Goals by Thrust Area
    rows = db.query(ThrustArea.name, func.count(Goal.id)).join(
        Goal, Goal.thrust_area_id == ThrustArea.id
    ).join(GoalSheet, Goal.goal_sheet_id == GoalSheet.id).filter(
        GoalSheet.cycle_id == cycle.id
    ).group_by(ThrustArea.name).all()

    labels = [r[0] for r in rows]
    data = [r[1] for r in rows]
    colors = ["#1E3A5F", "#F57C00", "#2196F3", "#4CAF50", "#FF5722", "#9C27B0", "#00BCD4", "#FFC107"]

    return JSONResponse({
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": colors[:len(labels)],
            "borderWidth": 2,
            "borderColor": "#fff"
        }]
    })


@router.get("/uom-distribution")
def uom_distribution(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return JSONResponse({"labels": [], "data": []})

    rows = db.query(Goal.uom_type, func.count(Goal.id)).join(GoalSheet).filter(
        GoalSheet.cycle_id == cycle.id
    ).group_by(Goal.uom_type).all()

    labels = [r[0].value for r in rows]
    data = [r[1] for r in rows]
    colors = ["#1E3A5F", "#F57C00", "#2196F3", "#4CAF50", "#FF5722", "#9C27B0"]

    return JSONResponse({
        "labels": labels,
        "datasets": [{
            "data": data,
            "backgroundColor": colors[:len(labels)],
        }]
    })


@router.get("/completion-heatmap")
def completion_heatmap(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return JSONResponse({"departments": [], "data": []})

    # Per-department completion rates by quarter
    departments = db.query(User.department).filter(
        User.role == UserRole.EMPLOYEE, User.is_active == True, User.department != None
    ).distinct().all()
    dept_names = [d[0] for d in departments if d[0]]

    quarters = [Quarter.Q1, Quarter.Q2, Quarter.Q3, Quarter.Q4]
    heatmap_data = []

    for dept in dept_names:
        row = {"department": dept, "quarters": {}}
        emps = db.query(User).filter(User.department == dept, User.role == UserRole.EMPLOYEE).all()
        emp_ids = [e.id for e in emps]

        sheets = db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(emp_ids),
            GoalSheet.status == GoalSheetStatus.APPROVED
        ).all()
        goal_ids = [g.id for s in sheets for g in s.goals]

        for q in quarters:
            if not goal_ids:
                row["quarters"][q.value] = 0
                continue
            done = db.query(CheckIn).filter(
                CheckIn.goal_id.in_(goal_ids),
                CheckIn.quarter == q,
                CheckIn.employee_updated_at != None
            ).count()
            rate = (done / len(goal_ids) * 100) if goal_ids else 0
            row["quarters"][q.value] = round(rate, 1)

        heatmap_data.append(row)

    return JSONResponse({
        "departments": dept_names,
        "quarters": ["Q1", "Q2", "Q3", "Q4"],
        "data": heatmap_data
    })


@router.get("/manager-effectiveness")
def manager_effectiveness(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return JSONResponse({"labels": [], "datasets": []})

    managers = db.query(User).filter(User.role == UserRole.MANAGER, User.is_active == True).all()

    labels = []
    approval_rates = []
    checkin_rates = []

    for mgr in managers:
        team = db.query(User).filter(User.manager_id == mgr.id, User.is_active == True).all()
        if not team:
            continue

        team_ids = [t.id for t in team]
        total_sheets = db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(team_ids)
        ).count()

        approved = db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.approved_by_id == mgr.id
        ).count()

        # Check-in completion rate (manager-commented check-ins)
        goal_ids = []
        for sheet in db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(team_ids),
            GoalSheet.status == GoalSheetStatus.APPROVED
        ).all():
            goal_ids.extend([g.id for g in sheet.goals])

        total_checkins = db.query(CheckIn).filter(CheckIn.goal_id.in_(goal_ids)).count() if goal_ids else 0
        mgr_checkins = db.query(CheckIn).filter(
            CheckIn.goal_id.in_(goal_ids),
            CheckIn.manager_id == mgr.id
        ).count() if goal_ids else 0

        labels.append(mgr.name[:20])
        approval_rates.append(round(approved / total_sheets * 100, 1) if total_sheets else 0)
        checkin_rates.append(round(mgr_checkins / total_checkins * 100, 1) if total_checkins else 0)

    return JSONResponse({
        "labels": labels,
        "datasets": [
            {
                "label": "Goal Approval Rate (%)",
                "data": approval_rates,
                "backgroundColor": "rgba(30,58,95,0.8)",
                "borderColor": "#1E3A5F",
                "borderWidth": 2,
            },
            {
                "label": "Check-in Comment Rate (%)",
                "data": checkin_rates,
                "backgroundColor": "rgba(245,124,0,0.8)",
                "borderColor": "#F57C00",
                "borderWidth": 2,
            }
        ]
    })

