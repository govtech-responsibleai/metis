"""User accounts and login sessions in the database of the store.

A user account is one person who can log in to a METIS server. METIS makes its username and its
password. The database keeps a scrypt hash of the password and never the password.

For debugging, ``users/<user id>/user.json`` in the server project folder names each user account:
its id, its username, and when it was made, last logged in, and last written. METIS writes the file
when it makes the user account and at each login. It holds no password, so a copy of the server
folder cannot be used to log in.

A login session starts at a login and ends at a logout or after ``LOGIN_SESSION_LIFETIME``. The
browser holds a random cookie value. The database keeps only the SHA-256 of that value, so a
copy of the database cannot be used to log in.

Note: not to be mistaken for the Session of a Trial (see the glossary).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from metis.api.store import user_project_dir
from metis.api.tables import login_sessions, users
from metis.core.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

logger = get_logger(__name__)

USER_FILE = "user.json"
"""The file in the project folder of a user account that names it, for debugging. It holds no
password."""

LOGIN_SESSION_LIFETIME = timedelta(days=30)
"""The time from a login to the end of its login session."""

_ADJECTIVES = (
    "amber", "bold", "brave", "bright", "calm", "clever", "cosmic", "curious",
    "daring", "eager", "gentle", "golden", "happy", "humble", "jolly", "keen",
    "kind", "lively", "lucky", "mellow", "merry", "mighty", "nimble", "noble",
    "patient", "plucky", "polite", "proud", "quick", "quiet", "rapid", "royal",
    "silver", "snowy", "steady", "sunny", "swift", "tidy", "vivid", "witty",
)  # fmt: skip

_ANIMALS = (
    "badger", "beaver", "bison", "crane", "dolphin", "eagle", "falcon", "ferret",
    "finch", "gecko", "heron", "ibis", "jaguar", "koala", "lemur", "lynx",
    "marten", "moose", "narwhal", "ocelot", "orca", "osprey", "otter", "owl",
    "panda", "pelican", "puffin", "quokka", "raven", "robin", "salmon", "seal",
    "sparrow", "stork", "tapir", "tiger", "toucan", "turtle", "walrus", "wombat",
)  # fmt: skip

_PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
"""Lower-case letters and digits, without `i`, `l`, `o`, `0`, and `1`, which look alike."""
_PASSWORD_GROUP = 5
_PASSWORD_GROUPS = 2

_PLAIN_NAME_TRIES = 8
_NUMBERED_NAME_TRIES = 8

# The scrypt cost. A password has about 49 bits of randomness, so this cost is sufficient.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_SALT_BYTES = 16
_SCRYPT_KEY_BYTES = 32


@dataclass(frozen=True)
class UserAccount:
    """One user account, without its password."""

    id: str
    username: str
    created_at: datetime


@dataclass(frozen=True)
class NewUserAccount:
    """A user account that was made a moment ago, with its password.

    This is the only value that holds the password. ``repr`` leaves it out.
    """

    account: UserAccount
    password: str

    def __repr__(self) -> str:
        return f"NewUserAccount(account={self.account!r})"


@dataclass(frozen=True)
class LoginSession:
    """A new login session: the cookie value for the browser, and its user account."""

    token: str
    account: UserAccount

    def __repr__(self) -> str:
        return f"LoginSession(account={self.account!r})"


def new_username() -> str:
    """Two words, an adjective and an animal, for example `curious-otter`."""
    return f"{secrets.choice(_ADJECTIVES)}-{secrets.choice(_ANIMALS)}"


def new_password() -> str:
    """Ten random characters in two groups, for example `k7mwp-3xr9t`."""
    groups = (
        "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_GROUP))
        for _ in range(_PASSWORD_GROUPS)
    )
    return "-".join(groups)


def hash_password(password: str) -> str:
    """The scrypt hash of ``password`` with a new salt, with its cost in the text."""
    salt = secrets.token_bytes(_SCRYPT_SALT_BYTES)
    key = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, password_hash: str | None) -> bool:
    """Whether ``password`` gives ``password_hash``.

    A user account with no password hash, or with a hash that this version cannot read, accepts
    no password.
    """
    if password_hash is None:
        return False
    try:
        scheme, n, r, p, salt, key = password_hash.split("$")
        expected = bytes.fromhex(key)
        actual = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return scheme == "scrypt" and hmac.compare_digest(actual, expected)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=r, p=p, dklen=_SCRYPT_KEY_BYTES
    )


_NO_ACCOUNT_HASH = hash_password(new_password())
"""A hash that no person has the password of. A login with an unknown username checks its
password against this hash, so it takes the same time as a login with a known username."""


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    """SQLite gives back a time with no zone. All times in the store are UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _account(row: Any) -> UserAccount:
    return UserAccount(
        id=row.id, username=row.username, created_at=_utc(row.created_at)
    )


def _time(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


class Accounts:
    """The user accounts and the login sessions of one database.

    With ``server_dir``, the project folder of the server, each new user account and each login
    writes the ``user.json`` of the user account. Without it, no file is written.
    """

    def __init__(self, engine: Engine, server_dir: Path | None = None) -> None:
        self._engine = engine
        self._server_dir = server_dir

    def create(self) -> NewUserAccount:
        """Make a user account with a new username and a new password.

        A username that is taken gets another try. After some tries, the username gets a number,
        so a server with many user accounts can always make one more.
        """
        password = new_password()
        password_hash = hash_password(password)
        for attempt in range(_PLAIN_NAME_TRIES + _NUMBERED_NAME_TRIES):
            username = new_username()
            if attempt >= _PLAIN_NAME_TRIES:
                username = f"{username}-{secrets.randbelow(900) + 100}"
            account = UserAccount(
                id=uuid.uuid4().hex, username=username, created_at=datetime.now(UTC)
            )
            try:
                with self._engine.begin() as connection:
                    connection.execute(
                        insert(users).values(
                            id=account.id,
                            username=account.username,
                            password_hash=password_hash,
                            created_at=account.created_at,
                        )
                    )
            except IntegrityError:
                continue
            self._write_user_file(account, last_login_at=None)
            return NewUserAccount(account=account, password=password)
        raise RuntimeError("The store could not find a free username.")

    def accounts(self) -> list[UserAccount]:
        """All user accounts, oldest first."""
        query = select(users).order_by(users.c.created_at, users.c.username)
        with self._engine.connect() as connection:
            return [_account(row) for row in connection.execute(query)]

    def login(self, username: str, password: str) -> LoginSession | None:
        """Start a login session, or return ``None`` when the credentials are wrong.

        The check ignores space around each value and the case of the letters, because a
        username and a password have only lower-case letters.
        """
        query = select(users).where(users.c.username == username.strip().lower())
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        password_hash = row.password_hash if row is not None else _NO_ACCOUNT_HASH
        correct = verify_password(password.strip().lower(), password_hash)
        if row is None or not correct:
            return None
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        account = _account(row)
        with self._engine.begin() as connection:
            connection.execute(
                delete(login_sessions).where(login_sessions.c.expires_at <= now)
            )
            connection.execute(
                insert(login_sessions).values(
                    token_hash=_token_hash(token),
                    user_id=row.id,
                    created_at=now,
                    expires_at=now + LOGIN_SESSION_LIFETIME,
                )
            )
        self._write_user_file(account, last_login_at=now)
        return LoginSession(token=token, account=account)

    def current(self, token: str) -> UserAccount | None:
        """The user account of a cookie value, or ``None`` when no login session has it."""
        query = (
            select(users, login_sessions.c.expires_at)
            .join(login_sessions, login_sessions.c.user_id == users.c.id)
            .where(login_sessions.c.token_hash == _token_hash(token))
        )
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        if row is None or _utc(row.expires_at) <= datetime.now(UTC):
            return None
        return _account(row)

    def _write_user_file(
        self, account: UserAccount, *, last_login_at: datetime | None
    ) -> None:
        """Write ``user.json`` of ``account`` in one rename, readable by the server's user only.

        A write that fails is logged and does not stop the caller, because the file is only for
        debugging.
        """
        if self._server_dir is None:
            return
        path = user_project_dir(self._server_dir, account.id) / USER_FILE
        temporary = path.with_name(f".{uuid.uuid4().hex}.part")
        content = {
            "id": account.id,
            "username": account.username,
            "created_at": _time(account.created_at),
            "last_login_at": _time(last_login_at),
            "updated_at": _time(datetime.now(UTC)),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(content, stream, indent=2)
                stream.write("\n")
            temporary.replace(path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                temporary.unlink(missing_ok=True)
            logger.warning(
                "user_file_not_written",
                user_id=account.id,
                error_type=type(exc).__name__,
            )

    def logout(self, token: str) -> None:
        """End the login session of a cookie value. An unknown value changes nothing."""
        with self._engine.begin() as connection:
            connection.execute(
                delete(login_sessions).where(
                    login_sessions.c.token_hash == _token_hash(token)
                )
            )


__all__ = [
    "LOGIN_SESSION_LIFETIME",
    "USER_FILE",
    "Accounts",
    "LoginSession",
    "NewUserAccount",
    "UserAccount",
    "hash_password",
    "new_password",
    "new_username",
    "verify_password",
]
