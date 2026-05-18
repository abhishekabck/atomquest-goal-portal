from fastapi import APIRouter, Depends, HTTPException, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from ..template_utils import Templates
from sqlalchemy.orm import Session
from datetime import timedelta
from ..database import get_db
from ..auth import authenticate_user, create_access_token, get_current_user_from_cookie, ACCESS_TOKEN_EXPIRE_MINUTES
from ..models import UserRole

router = APIRouter()
templates = Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    token = request.cookies.get("access_token")
    if token:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password"
        })

    token = create_access_token(
        data={"sub": str(user.id), "role": user.role},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/dashboard")
def dashboard_redirect(request: Request, db: Session = Depends(get_db)):
    try:
        user = get_current_user_from_cookie(request, db)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=302)

    if user.role == UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    elif user.role == UserRole.MANAGER:
        return RedirectResponse(url="/manager/dashboard", status_code=302)
    else:
        return RedirectResponse(url="/employee/dashboard", status_code=302)

