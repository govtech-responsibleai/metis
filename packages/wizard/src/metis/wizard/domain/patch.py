"""How the document gets changed.

The model returns a **patch** — one instruction saying *what to do*, *where*, and *the new
value* — never the whole document. Everything else about editing (which addresses each step
owns, what the applier rejects) lives in `metis.wizard.domain.permissions`, because it is
policy rather than shape.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class PatchOp(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    SET = "set"
    REORDER = "reorder"


class PatchOrigin(StrEnum):
    """Who composed this patch.

    This is what makes the tick possible at all. Ticking is a patch carried by the option,
    and `measured` is deliberately absent from StepPermissions so the model can never write
    it. Both are right, and together they would reject the user's own tick — the two patches
    are byte-identical, and an address check cannot see the difference:

        the model's attempt   SET  features[…].behaviours[EB-1].measured = True
        the user's click      SET  features[…].behaviours[EB-1].measured = True

    The wizard composed one of them, and knows it did, at the moment it drew the option. So
    the check reads origin first.
    """

    WIZARD = "wizard"  # composed by the package — ticks, chips, toggles. trusted
    MODEL = "model"  # composed by the model. checked against StepPermissions


class Patch(BaseModel):
    op: PatchOp
    path: str  # "features[F-2].behaviours[EB-4].criteria[AC-4-1]"
    value: Any = None
    # The safe default is to check it. Nothing the model returns is ever marked WIZARD:
    # origin is stamped by the code that builds the patch, and is stripped from structured
    # output before validation, so the model cannot claim it.
    origin: PatchOrigin = PatchOrigin.MODEL
