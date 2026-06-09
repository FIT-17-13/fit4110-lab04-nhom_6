import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from http.client import responses as HTTP_STATUS_CODES
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.3.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")

app = FastAPI(
    title="FIT4110 Lab 04 - Notification Service",
    version=SERVICE_VERSION,
    description=(
        "Dockerized Notification API aligned with the Lab 03 OpenAPI/Postman contract."
    ),
)


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str
    instance: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class NotificationCreate(BaseModel):
    alert_id: str = Field(..., min_length=3)
    channel: str = Field(...)
    recipient: str = Field(..., min_length=1)
    subject: Optional[str] = Field(default=None, max_length=120)
    message: str = Field(..., max_length=500)
    metadata: Optional[Dict] = None


class NotificationCreated(BaseModel):
    notification_id: str
    alert_id: str
    status: str
    created_at: str


class NotificationDetail(NotificationCreated):
    channel: str
    recipient: str
    subject: Optional[str] = None
    message: str
    attempts: int


NOTIFICATIONS: List[Dict] = []


def build_problem(*, status_code: int, title: str, detail: str, instance: Optional[str] = None, problem_type: str = "about:blank") -> Dict:
    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    return problem


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title=HTTP_STATUS_CODES.get(exc.status_code, "HTTP Error"),
            detail=str(exc.detail),
            instance=str(request.url.path),
        )

    problem.setdefault("status", exc.status_code)
    problem.setdefault("title", HTTP_STATUS_CODES.get(exc.status_code, "HTTP Error"))
    problem.setdefault("type", "about:blank")
    problem.setdefault("detail", "Request failed")
    problem.setdefault("instance", str(request.url.path))

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Request validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation error",
            detail=detail,
            instance=str(request.url.path),
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )

    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_notification_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"N-{today}-{len(NOTIFICATIONS) + 1:04d}"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME, version=SERVICE_VERSION)


@app.post(
    "/notifications",
    response_model=NotificationCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_bearer_token)],
    responses={400: {"model": ProblemDetails}, 401: {"model": ProblemDetails}, 409: {"model": ProblemDetails}},
)
def create_notification(payload: NotificationCreate, response: Response) -> NotificationCreated:
    # validate channel
    if payload.channel not in ["email", "sms", "push", "webhook"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=build_problem(
                status_code=status.HTTP_400_BAD_REQUEST,
                title="Validation error",
                detail="channel must be one of [email, sms, push, webhook]",
                instance="/notifications",
                problem_type="https://smart-campus.local/problems/validation-error",
            ),
        )

    # dedupe by alert_id
    for n in NOTIFICATIONS:
        if n.get("alert_id") == payload.alert_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=build_problem(
                    status_code=status.HTTP_409_CONFLICT,
                    title="Duplicate alert",
                    detail="notification already exists for alert_id",
                    instance="/notifications",
                    problem_type="https://smart-campus.local/problems/duplicate-alert",
                ),
            )

    notification_id = next_notification_id()
    created_at = now_iso()

    item = {
        "notification_id": notification_id,
        "alert_id": payload.alert_id,
        "status": "queued",
        "channel": payload.channel,
        "recipient": payload.recipient,
        "subject": payload.subject,
        "message": payload.message,
        "attempts": 0,
        "created_at": created_at,
    }
    NOTIFICATIONS.append(item)

    return NotificationCreated(
        notification_id=notification_id, alert_id=payload.alert_id, status="queued", created_at=created_at
    )


@app.get("/notifications")
def list_notifications(status: Optional[str] = Query(default=None), limit: int = Query(default=20, ge=1, le=100), authorization: Optional[str] = Header(default=None)) -> Dict:
    # Auth check
    verify_bearer_token(authorization)

    items = NOTIFICATIONS
    if status:
        items = [i for i in items if i.get("status") == status]

    return {"items": items[-limit:], "total": len(items)}


@app.get("/notifications/{notification_id}")
def get_notification(notification_id: str, authorization: Optional[str] = Header(default=None)) -> Dict:
    verify_bearer_token(authorization)
    for n in NOTIFICATIONS:
        if n["notification_id"] == notification_id:
            return n

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail="notification_id not found",
            instance=f"/notifications/{notification_id}",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )


@app.post("/notifications/{notification_id}/retry")
def retry_notification(notification_id: str, authorization: Optional[str] = Header(default=None)) -> Dict:
    verify_bearer_token(authorization)
    for n in NOTIFICATIONS:
        if n["notification_id"] == notification_id:
            n["status"] = "queued"
            n["attempts"] = n.get("attempts", 0) + 1
            return {"notification_id": notification_id, "status": "queued", "retried_at": now_iso()}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail="notification_id not found",
            instance=f"/notifications/{notification_id}/retry",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )
