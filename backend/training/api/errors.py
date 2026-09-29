"""Service errors → HTTP: NotFoundError 404, InvalidInputError 422, other ServiceError 502 (bad gateway:
Garmin unreachable / login rejected). Bodies are `{"detail": "<message>"}`, like FastAPI's own errors."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from training.services.errors import InvalidInputError, NotFoundError, ServiceError


class ErrorBody(BaseModel):
    detail: str


NOT_FOUND = {404: {"model": ErrorBody, "description": "The requested entity does not exist."}}
INVALID = {422: {"model": ErrorBody, "description": "Invalid or unacceptable parameters / body."}}
UPSTREAM = {502: {"model": ErrorBody, "description": "Garmin Connect failed or rejected the login."}}


def _handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handle


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    """FastAPI's own parameter/body validation errors, with `detail` as one string like every other error."""
    assert isinstance(exc, RequestValidationError)
    problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return JSONResponse(status_code=422, content={"detail": problems})


def register_error_handlers(app: FastAPI) -> None:
    """The most specific handler wins (Starlette walks the exception's MRO)."""
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(NotFoundError, _handler(404))
    app.add_exception_handler(InvalidInputError, _handler(422))
    app.add_exception_handler(ServiceError, _handler(502))
