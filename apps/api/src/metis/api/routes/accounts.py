"""HTTP routes for user accounts and login sessions, and the guard of the other routes.

The user routes make and list user accounts. The admin token protects them, and they are off
when the server has no admin token. The auth routes start and end a login session and name the
current user account.

`login_guard` is the one place that decides if a request can reach a route. When login is on,
each `/api` route needs a login session, except the routes in ``_OPEN_PATHS``. A new router gets
this rule with no code of its own.
"""

from __future__ import annotations

import hmac
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from metis.api.accounts import LOGIN_SESSION_LIFETIME, Accounts, UserAccount
from metis.api.routes.wizard import ServiceError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

LOGIN_COOKIE = "metis_login"
"""The cookie that holds the value of a login session."""

users_router = APIRouter(prefix="/api/v1/users", tags=["users"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_OPEN_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/users"})
"""The `/api` routes that need no login session. A password protects the login route, and the
admin token protects the user routes. The logout route ends only the login session of its own
cookie, so it also removes a cookie whose login session has ended."""

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ServiceError},
    404: {"model": ServiceError},
    422: {"model": ServiceError},
    500: {"model": ServiceError},
}


class AccountError(Exception):
    """A user or auth route cannot serve the request. The app gives it the service error shape."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers


class UserAccountBody(BaseModel):
    """One user account. It never holds a password or a password hash."""

    id: str
    username: str
    created_at: datetime


class NewUserAccountBody(UserAccountBody):
    """A new user account with its password. No later response gives the password again."""

    password: str


class UserAccountList(BaseModel):
    """The user accounts of the server, oldest first."""

    users: list[UserAccountBody]


class LoginRequest(BaseModel):
    """The credentials of one user account."""

    username: str
    password: str


class CurrentUser(BaseModel):
    """Whether login is on, and the user account of the request.

    With login off, ``login`` is false and ``user`` is null. With login on, ``user`` is the user
    account of the login session.
    """

    login: bool
    user: UserAccountBody | None


def _body(account: UserAccount) -> UserAccountBody:
    return UserAccountBody(
        id=account.id, username=account.username, created_at=account.created_at
    )


def _failure(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    error = ServiceError(code=code, message=message, retryable=False)
    return JSONResponse(error.model_dump(), status_code=status, headers=headers)


def account_error_response(exc: AccountError) -> JSONResponse:
    """The response of an ``AccountError``, in the service error shape."""
    return _failure(exc.status, exc.code, exc.message, exc.headers)


def get_accounts(request: Request) -> Accounts:
    """Return the user accounts that the app composed at startup."""
    accounts: Accounts | None = getattr(request.app.state, "accounts", None)
    if accounts is None:
        raise RuntimeError(
            "The user accounts were not composed at application startup."
        )
    return accounts


def _login_is_on(request: Request) -> bool:
    return bool(getattr(request.app.state, "login", False))


def _same_origin(request: Request) -> bool:
    """Whether a request that changes data comes from a page of this server.

    A browser tells where a request comes from in ``Sec-Fetch-Site``, and a page cannot change
    that header. `same-origin` is a page of this server, and `none` is an action of the person,
    for example a typed address. This check does not read ``Host``, so it also works behind a
    proxy that changes ``Host``.

    An older browser sends no ``Sec-Fetch-Site``. Then the ``Origin`` header must name the host
    of the request. A request with neither header comes from a program, for example the server
    of another website, and that request cannot use the cookie of a person.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


async def login_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Let a request reach an `/api` route only with a login session, when login is on.

    The cookie is `SameSite=Lax`, but a page on another subdomain is the same site to the
    browser. Thus the guard also refuses a request that changes data from another origin.
    """
    path = request.url.path
    if not _login_is_on(request) or not path.startswith("/api/"):
        return await call_next(request)
    if request.method not in _SAFE_METHODS and not _same_origin(request):
        return _failure(
            403,
            "cross_site_request",
            "A request that changes data must come from the METIS web app.",
        )
    if path in _OPEN_PATHS:
        return await call_next(request)
    token = request.cookies.get(LOGIN_COOKIE)
    account = (
        await run_in_threadpool(get_accounts(request).current, token) if token else None
    )
    if account is None:
        return _failure(401, "login_required", "Log in to use this METIS server.")
    request.state.user_account = account
    return await call_next(request)


_admin_token = HTTPBearer(
    scheme_name="AdminToken",
    description="The admin token of the server, which is the value of `METIS_ADMIN_TOKEN`.",
    auto_error=False,
)
"""The bearer scheme of the user routes. With it, the API documentation page has a field for
the admin token. ``require_admin`` gives the answer for a wrong token."""


def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_token)],
) -> None:
    """Refuse a request that does not have the admin token of the server.

    The comparison takes the same time for each wrong token.
    """
    expected: str = getattr(request.app.state, "admin_token", "")
    if not expected:
        raise AccountError(
            404,
            "not_found",
            "This METIS server has no admin token, so the route is off.",
        )
    given = credentials.credentials if credentials is not None else ""
    if not hmac.compare_digest(given.strip().encode(), expected.encode()):
        raise AccountError(
            401,
            "invalid_admin_token",
            "The request needs the admin token in an Authorization: Bearer header.",
            {"WWW-Authenticate": "Bearer"},
        )


@users_router.post(
    "",
    summary="Make a user account",
    status_code=201,
    response_model=NewUserAccountBody,
    responses=_ERRORS,
    dependencies=[Depends(require_admin)],
)
def create_user(
    accounts: Annotated[Accounts, Depends(get_accounts)],
) -> NewUserAccountBody:
    """Make a user account and return its username and password.

    METIS makes both values. This response is the only one that has the password. Each request
    makes one more user account.
    """
    new = accounts.create()
    return NewUserAccountBody(**_body(new.account).model_dump(), password=new.password)


@users_router.get(
    "",
    summary="List the user accounts",
    response_model=UserAccountList,
    responses=_ERRORS,
    dependencies=[Depends(require_admin)],
)
def list_users(
    accounts: Annotated[Accounts, Depends(get_accounts)],
) -> UserAccountList:
    """Return each user account with its id, username, and creation time."""
    return UserAccountList(users=[_body(account) for account in accounts.accounts()])


@auth_router.post(
    "/login",
    summary="Start a login session",
    response_model=CurrentUser,
    responses=_ERRORS,
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    accounts: Annotated[Accounts, Depends(get_accounts)],
) -> CurrentUser:
    """Check the credentials and give the browser the cookie of a new login session.

    Wrong credentials get 401 `invalid_credentials`, with one message for an unknown username
    and for a wrong password. A server with login off gets 404 `not_found`.
    """
    if not _login_is_on(request):
        raise AccountError(404, "not_found", "Login is off on this METIS server.")
    session = accounts.login(body.username, body.password)
    if session is None:
        raise AccountError(
            401, "invalid_credentials", "The username or the password is not correct."
        )
    response.set_cookie(
        LOGIN_COOKIE,
        session.token,
        max_age=int(LOGIN_SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=bool(getattr(request.app.state, "secure_cookie", False)),
    )
    return CurrentUser(login=True, user=_body(session.account))


@auth_router.post(
    "/logout", summary="End the login session", status_code=204, responses=_ERRORS
)
def logout(
    request: Request, accounts: Annotated[Accounts, Depends(get_accounts)]
) -> Response:
    """End the login session of the request and remove its cookie."""
    token = request.cookies.get(LOGIN_COOKIE)
    if token:
        accounts.logout(token)
    response = Response(status_code=204)
    response.delete_cookie(LOGIN_COOKIE)
    return response


@auth_router.get(
    "/me",
    summary="Read the current user account",
    response_model=CurrentUser,
    responses=_ERRORS,
)
def current_user(request: Request) -> CurrentUser:
    """Tell if login is on, and name the user account of the login session.

    With login on and no login session, the guard gives 401 `login_required`, as for each
    other route. A client reads that as "show the login page".
    """
    account: UserAccount | None = getattr(request.state, "user_account", None)
    return CurrentUser(
        login=_login_is_on(request),
        user=_body(account) if account is not None else None,
    )


__all__ = [
    "LOGIN_COOKIE",
    "AccountError",
    "CurrentUser",
    "LoginRequest",
    "NewUserAccountBody",
    "UserAccountBody",
    "UserAccountList",
    "account_error_response",
    "auth_router",
    "get_accounts",
    "login_guard",
    "require_admin",
    "users_router",
]
