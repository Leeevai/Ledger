from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"


class APIError(Exception):
    """Every deliberate failure in this app raises one of these."""

    def __init__(self, status: int, code: str, message: str, **extra):
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(message)


def _body(status: int, code: str, message: str, request: Request, **extra) -> dict:
    return {
        "type": f"https://api.ledger.example/errors/{code.lower()}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "code": code,           # STABLE — this is the contract
        "detail": message,      # for humans — explicitly unstable
        "instance": request.url.path,
        "trace_id": request.headers.get("x-request-id", "-"),
        **extra,
    }


def install(app):
    @app.exception_handler(APIError)
    def _api_error(request: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status,
            media_type=CONTENT_TYPE,
            content=_body(exc.status, exc.code, exc.message, request, **exc.extra),
            headers=exc.extra.pop("headers", {}) or {},
        )

    @app.exception_handler(RequestValidationError)
    def _validation(request: Request, exc: RequestValidationError):
        # Return EVERY problem at once, not the first one (Lesson 8).
        errors = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or "body",
                "code": e["type"].upper(),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            media_type=CONTENT_TYPE,
            content=_body(422, "VALIDATION_FAILED",
                          f"The request contained {len(errors)} invalid field(s).",
                          request, errors=errors),
        )

    @app.exception_handler(Exception)
    def _unhandled(request: Request, exc: Exception):
        # NEVER leak the traceback. Log it; return a trace id.
        import logging, uuid
        trace = str(uuid.uuid4())
        logging.exception("unhandled error trace_id=%s", trace)
        return JSONResponse(
            status_code=500,
            media_type=CONTENT_TYPE,
            content={"type": "https://api.ledger.example/errors/internal",
                     "title": "Internal Server Error", "status": 500,
                     "code": "INTERNAL", "detail": "An unexpected error occurred.",
                     "instance": request.url.path, "trace_id": trace},
        )
