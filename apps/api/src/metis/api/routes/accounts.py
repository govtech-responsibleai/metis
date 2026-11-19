"""HTTP routes for user accounts and login sessions, and the guard of the other routes.

The user routes make, list, and delete user accounts, and reset their passwords. ``Caller`` and
``get_caller`` are the one rule of who can use them: the login session of an admin, or the admin
token, opens each user route, and the join token can make a user account that is not an admin.
The auth routes start and end a login session and name the current user account.

`login_guard` is the one place that decides if a request can reach each other route. When login
is on, each `/api` route needs a login session, except the paths that ``_is_open`` names. A new
router gets this rule with no code of its own.
"""

from __future__ import annotations

import hmac
from datetime import datetime  # noqa: TC003
from enum import Enum
from typing import TYPE_CHECKING, Annotated, TypeAlias
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from metis.api.accounts import LOGIN_SESSION_LIFETIME, Accounts, UserAccount
from metis.api.routes.wizard import ServiceError
from metis.api.store import LOCAL_USER_ID, Store, user_project_dir

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metis.api.engine_runs import EngineRuns

LOGIN_COOKIE = "metis_login"
"""The cookie that holds the value of a login session."""

users_router = APIRouter(prefix="/api/v1/users", tags=["users"])
auth_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_OPEN_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/logout"})
"""The `/api` routes that need no login session. A password protects the login route. The logout
route ends only the login session of its own cookie, so it also removes a cookie whose login
session has ended."""

_USERS_PATH = "/api/v1/users"
"""Each user route has its own access dependency, which reads a token or the login session.
Thus the guard lets each path under this one through."""

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ServiceError},
    403: {"model": ServiceError},
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
    """One user account. It never holds a password or a password hash. ``admin`` is true for an
    admin."""

    id: str
    username: str
    created_at: datetime
    admin: bool


class NewUserRequest(BaseModel):
    """The kind of user account to make. Only an admin can make an admin."""

    admin: bool = False


class NewUserAccountBody(UserAccountBody):
    """A user account with its new password. No later response gives the password again."""

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
        id=account.id,
        username=account.username,
        created_at=account.created_at,
        admin=account.admin,
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


def _is_open(path: str) -> bool:
    return (
        path in _OPEN_PATHS or path == _USERS_PATH or path.startswith(f"{_USERS_PATH}/")
    )


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
    if _is_open(path):
        return await call_next(request)
    token = request.cookies.get(LOGIN_COOKIE)
    account = (
        await run_in_threadpool(get_accounts(request).current, token) if token else None
    )
    if account is None:
        return _failure(401, "login_required", "Log in to use this METIS server.")
    request.state.user_account = account
    return await call_next(request)


_admin_bearer = HTTPBearer(
    scheme_name="AdminToken",
    description="The admin token of the server, which is the value of `METIS_ADMIN_TOKEN`.",
    auto_error=False,
)
"""The bearer scheme of each user route. With it, the API documentation page has a field for the
admin token."""

_join_bearer = HTTPBearer(
    scheme_name="JoinToken",
    description="The join token of the server, which is the value of `METIS_JOIN_TOKEN`.",
    auto_error=False,
)
"""The bearer scheme of the route that makes a user account, for the API documentation page. Both
schemes read the same `Authorization` header, and ``_token`` compares its token with each token of
the server."""

_login_cookie = APIKeyCookie(
    name=LOGIN_COOKIE,
    scheme_name="LoginSession",
    description="The cookie of a login session, which the login route sets.",
    auto_error=False,
)
"""The cookie scheme of the user routes. ``get_caller`` reads the login session from it."""


class Token(Enum):
    """The token that a request to a user route sent."""

    ADMIN = "admin"
    """The admin token. It has the power of the login session of an admin."""
    JOIN = "join"
    """The join token. It can only make a user account that is not an admin."""


Caller: TypeAlias = UserAccount | Token
"""Who sent a request to a user route: the user account of its login session, or a token."""


def _is_admin(caller: Caller) -> bool:
    if isinstance(caller, Token):
        return caller is Token.ADMIN
    return caller.admin


def _token(request: Request, given: str) -> Token:
    """Return the token of the server that ``given`` is, or refuse the request.

    The comparison takes the same time for each wrong token. An unset token matches nothing.
    """
    state = request.app.state
    for token, expected in (
        (Token.ADMIN, getattr(state, "admin_token", "")),
        (Token.JOIN, getattr(state, "join_token", "")),
    ):
        if expected and hmac.compare_digest(given.strip().encode(), expected.encode()):
            return token
    raise AccountError(
        401,
        "invalid_token",
        "The token is not a token of this METIS server.",
        {"WWW-Authenticate": "Bearer"},
    )


def get_caller(
    request: Request,
    accounts: Annotated[Accounts, Depends(get_accounts)],
    cookie: Annotated[str | None, Depends(_login_cookie)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_bearer)],
) -> Caller:
    """Return the caller of a request to a user route, or refuse the request.

    With login off, each user route is off. A request with an `Authorization` header is a token
    request, and the login session does not apply to it. Each other request needs a login
    session, else it gets 401 `login_required`.
    """
    if not _login_is_on(request):
        raise AccountError(404, "not_found", "Login is off on this METIS server.")
    if "authorization" in request.headers:
        return _token(request, credentials.credentials if credentials else "")
    account = accounts.current(cookie) if cookie else None
    if account is None:
        raise AccountError(401, "login_required", "Log in to use this METIS server.")
    return account


def _admin_required() -> AccountError:
    return AccountError(
        403, "admin_required", "Only an admin can manage the user accounts."
    )


def require_admin(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    """Return the caller if it is an admin, or refuse the request with 403 `admin_required`."""
    if not _is_admin(caller):
        raise _admin_required()
    return caller


@users_router.post(
    "",
    summary="Make a user account",
    status_code=201,
    response_model=NewUserAccountBody,
    responses=_ERRORS,
    dependencies=[Depends(_join_bearer)],
)
def create_user(
    accounts: Annotated[Accounts, Depends(get_accounts)],
    caller: Annotated[Caller, Depends(get_caller)],
    body: NewUserRequest | None = None,
) -> NewUserAccountBody:
    """Make a user account and return its username and password.

    METIS makes both values. This response is the only one that has the password. Each request
    makes one more user account. An admin makes a user account of each kind. The join token
    makes a user account that is not an admin, and `{"admin": true}` with the join token gets
    403 `admin_required`.
    """
    admin = body is not None and body.admin
    if caller is Token.JOIN and admin:
        raise AccountError(
            403, "admin_required", "Only an admin can make an admin user account."
        )
    if caller is not Token.JOIN and not _is_admin(caller):
        raise _admin_required()
    new = accounts.create(admin=admin)
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
    """Return each user account with its id, username, creation time, and admin flag."""
    return UserAccountList(users=[_body(account) for account in accounts.accounts()])


@users_router.post(
    "/{username}/password",
    summary="Reset the password of a user account",
    response_model=NewUserAccountBody,
    responses=_ERRORS,
    dependencies=[Depends(require_admin)],
)
def reset_password(
    username: str,
    accounts: Annotated[Accounts, Depends(get_accounts)],
) -> NewUserAccountBody:
    """Give a user account a new password, end its login sessions, and return the password.

    METIS makes the password. This response is the only one that has it. An unknown username
    gets 404 `not_found`.
    """
    new = accounts.reset_password(username)
    if new is None:
        raise AccountError(
            404, "not_found", f"No user account has the username {username!r}."
        )
    return NewUserAccountBody(**_body(new.account).model_dump(), password=new.password)


@users_router.delete(
    "/{username}",
    summary="Delete a user account",
    status_code=204,
    responses={**_ERRORS, 409: {"model": ServiceError}},
)
def delete_user(
    username: str,
    request: Request,
    accounts: Annotated[Accounts, Depends(get_accounts)],
    caller: Annotated[Caller, Depends(require_admin)],
) -> Response:
    """Delete a user account, its login sessions, its Targets, and its project folder.

    The checks are in this order. An unknown username gets 404 `not_found`. Each refusal gets
    409 with its own code: `cannot_delete_self` for the account of the login session,
    `environment_admin` for the admin that the server makes again at each start,
    `local_account` for the account of the records of login off, and `run_in_progress` while
    an engine run of the account is alive. The run check is last, because only it can pass at
    a later try.
    """
    account = accounts.account(username)
    if account is None:
        raise AccountError(
            404, "not_found", f"No user account has the username {username!r}."
        )
    if isinstance(caller, UserAccount) and account.id == caller.id:
        raise AccountError(
            409, "cannot_delete_self", "You cannot delete your own user account."
        )
    if account.username == getattr(request.app.state, "environment_admin", None):
        raise AccountError(
            409,
            "environment_admin",
            f"The server makes the admin {account.username!r} again at each start, "
            "so you cannot delete it.",
        )
    if account.id == LOCAL_USER_ID:
        raise AccountError(
            409,
            "local_account",
            "The local user account holds the records of the server with login off, "
            "so you cannot delete it.",
        )
    runs: EngineRuns = request.app.state.engine_runs
    folder = user_project_dir(request.app.state.project_dir, account.id)
    with runs.idle_in(folder) as idle:
        if not idle:
            raise AccountError(
                409,
                "run_in_progress",
                f"An experiment of {account.username!r} runs now. Stop the run, then "
                "delete the user account.",
            )
        store: Store = request.app.state.store
        store.delete_user_account(account.id)
    return Response(status_code=204)


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
    "Caller",
    "CurrentUser",
    "LoginRequest",
    "NewUserAccountBody",
    "NewUserRequest",
    "UserAccountBody",
    "UserAccountList",
    "account_error_response",
    "auth_router",
    "get_accounts",
    "login_guard",
    "Token",
    "get_caller",
    "require_admin",
    "users_router",
]
