"""metis.api — REST API service.

A thin HTTP door over the wizard's public Interview interface, and the store of each Target. The
wizard routes translate request and response JSON and status codes and keep no state. The store
routes keep the Interview, the Specification, and the Experiments of each Target. Every wizard rule
stays inside metis-wizard.
"""

from importlib.metadata import PackageNotFoundError, version

from metis.core import __version__ as core_version

try:
    __version__ = version("metis-api")
except PackageNotFoundError:
    __version__ = "0.0.0.dev0"

__all__ = ["__version__", "core_version"]
