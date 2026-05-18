from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session, joinedload
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from ..database import get_db
from ..auth import get_current_user_from_cookie
from ..models import (
    User, UserRole, GoalSheet, GoalSheetStatus, Goal,
    GoalCycle, CheckIn, Quarter
)
from ..services.progress import compute_progress_score

router = APIRouter(prefix="/reports", tags=["reports"])
templates = Templates(directory="app/templates")

HEADER_FILL = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ALT_FILL = PatternFill(start_color="EBF2FA", end_color="EBF2FA", fill_type="solid")


def _style_header_row(ws, row_num):
    for cell in ws[row_num]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


@router.get("/achievement")
def achievement_report(
    request: Request,
    cycle_id: int = Query(default=None),
    format: str = Query(default="xlsx"),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return RedirectResponse(url="/login", status_code=302)

    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        return RedirectResponse(url="/employee/dashboard", status_code=302)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return RedirectResponse(url="/admin/dashboard?error=no_cycle", status_code=302)

    # Fetch all sheets with full eager loading to avoid N+1 in the Excel loop
    sheet_q = db.query(GoalSheet).options(
        joinedload(GoalSheet.employee).joinedload(User.manager),
        joinedload(GoalSheet.goals).joinedload(Goal.thrust_area),
        joinedload(GoalSheet.goals).joinedload(Goal.check_ins),
    ).filter(GoalSheet.cycle_id == cycle.id)

    if user.role == UserRole.MANAGER:
        team_ids = [u.id for u in db.query(User.id).filter(User.manager_id == user.id).all()]
        sheets = sheet_q.filter(GoalSheet.employee_id.in_(team_ids)).all()
    else:
        sheets = sheet_q.all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Achievement Report"

    headers = [
        "Employee", "Department", "Manager", "Goal Title", "Thrust Area",
        "UoM", "Target", "Weightage",
        "Q1 Actual", "Q1 Score", "Q1 Status",
        "Q2 Actual", "Q2 Score", "Q2 Status",
        "Q3 Actual", "Q3 Score", "Q3 Status",
        "Q4 Actual", "Q4 Score", "Q4 Status",
        "Overall Weighted Score"
    ]
    ws.append(headers)
    _style_header_row(ws, 1)

    row_num = 2
    for sheet in sheets:
        emp = sheet.employee
        manager_name = emp.manager.name if emp.manager else "N/A"
        dept = emp.department or "N/A"

        goal_weighted_scores = []
        for goal in sheet.goals:
            row = [
                emp.name, dept, manager_name,
                goal.title,
                goal.thrust_area.name if goal.thrust_area else "N/A",
                goal.uom_type.value,
                str(goal.target_value or goal.target_date or "N/A"),
                f"{goal.weightage}%"
            ]

            for q in [Quarter.Q1, Quarter.Q2, Quarter.Q3, Quarter.Q4]:
                ci = next((c for c in goal.check_ins if c.quarter == q), None)
                if ci:
                    row.extend([
                        str(ci.actual_value or ci.actual_date or "N/A"),
                        f"{ci.progress_score:.1f}%" if ci.progress_score is not None else "N/A",
                        ci.status.value
                    ])
                    if ci.progress_score is not None:
                        goal_weighted_scores.append(ci.progress_score * goal.weightage / 100)
                else:
                    row.extend(["N/A", "N/A", "NOT_STARTED"])

            # Overall weighted score for this goal
            q4_ci = next((c for c in goal.check_ins if c.quarter == Quarter.Q4), None)
            if q4_ci and q4_ci.progress_score is not None:
                overall = f"{q4_ci.progress_score * goal.weightage / 100:.2f}"
            else:
                overall = "N/A"
            row.append(overall)
            ws.append(row)

            if row_num % 2 == 0:
                for cell in ws[row_num]:
                    cell.fill = ALT_FILL
            row_num += 1

    # Auto-size columns
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"achievement_report_{cycle.year}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/completion-csv")
def completion_csv(
    request: Request,
    cycle_id: int = Query(default=None),
    db: Session = Depends(get_db)
):
    try:
        user = get_current_user_from_cookie(request, db)
    except Exception:
        return RedirectResponse(url="/login", status_code=302)

    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/dashboard", status_code=302)

    if cycle_id:
        cycle = db.query(GoalCycle).filter(GoalCycle.id == cycle_id).first()
    else:
        cycle = db.query(GoalCycle).filter(GoalCycle.is_active == True).first()

    if not cycle:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Employee", "Department", "Manager", "Sheet Status", "Submitted At", "Approved At"])

    # Batch: load all sheets for cycle in one query
    employees = db.query(User).options(
        joinedload(User.manager)
    ).filter(User.role == UserRole.EMPLOYEE, User.is_active == True).all()
    emp_ids = [e.id for e in employees]
    sheets_map = {}
    if emp_ids:
        for s in db.query(GoalSheet).filter(
            GoalSheet.cycle_id == cycle.id,
            GoalSheet.employee_id.in_(emp_ids)
        ).all():
            sheets_map[s.employee_id] = s

    for emp in employees:
        sheet = sheets_map.get(emp.id)
        manager_name = emp.manager.name if emp.manager else "N/A"
        writer.writerow([
            emp.name,
            emp.department or "N/A",
            manager_name,
            sheet.status.value if sheet else "NOT_STARTED",
            sheet.submitted_at.date() if sheet and sheet.submitted_at else "N/A",
            sheet.approved_at.date() if sheet and sheet.approved_at else "N/A",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=completion_{cycle.year}.csv"}
    )

