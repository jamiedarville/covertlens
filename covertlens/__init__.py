"""CovertLens harness contracts (CL-7).

Public surface: the allowed-channel manifest loader/validator, the stable
harness event contracts, the artifact route inventory, and ID helpers.
"""

from . import ids
from .events import (
    Event,
    EventType,
    ParseStatus,
    TraceLog,
    Verdict,
    validate_event,
)
from .manifest import channel_families, load_manifest, validate_manifest
from .routes import ROUTES, Route, routes_by_kind, validate_inventory

__version__ = "0.1.0"

__all__ = [
    "Event",
    "EventType",
    "ParseStatus",
    "ROUTES",
    "Route",
    "TraceLog",
    "Verdict",
    "channel_families",
    "ids",
    "load_manifest",
    "routes_by_kind",
    "validate_event",
    "validate_inventory",
    "validate_manifest",
]
