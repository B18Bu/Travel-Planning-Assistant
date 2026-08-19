from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为响应添加请求标识和基础安全响应头。"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id")
        try:
            request.state.request_id = str(UUID(request_id)) if request_id else str(uuid4())
        except ValueError:
            request.state.request_id = str(uuid4())

        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
