"""metis.api — REST API service.

A thin HTTP door over the wizard's public Interview interface, plus saved Interview records and
their files. The wizard routes translate request and response JSON and status codes and keep no
state. The store routes save the complete Interview state and transcript. Every wizard rule stays
inside metis-wizard.
"""

from importlib.metadata import PackageNotFoundError, version

from metis.core import Status
from metis.core import __version__ as core_version

try:
    __version__ = version("metis-api")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["Status", "__version__", "core_version"]
