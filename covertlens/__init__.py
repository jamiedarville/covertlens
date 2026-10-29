"""CovertLens harness contracts (CL-7) and immutable originals (CL-8).

Public surface: the allowed-channel manifest loader/validator, the stable
harness event contracts, the artifact route inventory, ID helpers, and
the immutable artifact store with dataset-lifetime evidence retention.
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
from .fixtures import (
    ENCODER_VERSION,
    GENERATOR_VERSION,
    Fixture,
    build_dataset,
    build_pair,
    decode_dct_jpeg,
    decode_lsb_png,
    encode_dct_jpeg,
    encode_lsb_png,
    generate_cover,
    make_payload,
    manifest,
)
from .manifest import channel_families, load_manifest, validate_manifest
from .routes import ROUTES, Route, routes_by_kind, validate_inventory
from .runtime import (
    AuditLog,
    DatasetRetirement,
    EvidenceGateway,
    Principal,
    RuntimeConfig,
    load_runtime_policy,
    validate_runtime_policy,
)
from .splits import (
    SPLITS,
    RecoveryReport,
    SplitPolicy,
    assign_splits,
    detector_manifest,
    group_key,
    held_out_record,
    scorer_ground_truth,
    validate_no_leakage,
    verify_recovery,
    write_split_dataset,
)
from .store import RETENTION_POLICY, ArtifactStore, ArtifactVersion

__version__ = "0.1.0"

__all__ = [
    "ENCODER_VERSION",
    "GENERATOR_VERSION",
    "ArtifactStore",
    "ArtifactVersion",
    "Fixture",
    "build_dataset",
    "build_pair",
    "decode_dct_jpeg",
    "decode_lsb_png",
    "encode_dct_jpeg",
    "encode_lsb_png",
    "generate_cover",
    "make_payload",
    "manifest",
    "Event",
    "EventType",
    "ParseStatus",
    "RETENTION_POLICY",
    "ROUTES",
    "Route",
    "TraceLog",
    "Verdict",
    "SPLITS",
    "RecoveryReport",
    "SplitPolicy",
    "assign_splits",
    "AuditLog",
    "DatasetRetirement",
    "EvidenceGateway",
    "Principal",
    "RuntimeConfig",
    "channel_families",
    "detector_manifest",
    "group_key",
    "held_out_record",
    "scorer_ground_truth",
    "validate_no_leakage",
    "validate_runtime_policy",
    "verify_recovery",
    "write_split_dataset",
    "ids",
    "load_manifest",
    "load_runtime_policy",
    "routes_by_kind",
    "validate_event",
    "validate_inventory",
    "validate_manifest",
]
