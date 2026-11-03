"""Authenticated identities mapped to CL-11 principals (CL-67, OP-01).

Phase 2 used a labelled demo-role toggle (`X-Demo-Role`). A real
deployment authenticates people (OIDC, in the web service) and maps
each identity to runtime-policy roles and dataset scopes through a
versioned configuration file, `config/identity-mapping.json`.

Rules:

- **Deny by default.** An authenticated identity that matches no rule
  gets the mapping's `default` grant, which ships empty: a viewer with
  no dataset. Unauthenticated requests are anonymous viewers.
- **Human roles only.** Mappings may grant `viewer`, `researcher`,
  `reviewer`, `operator` and `approver`. System roles (`agent`,
  `detector_worker`, `scorer`) are never granted to a person.
- **Dataset scopes are patterns.** Each grant lists `fnmatch`
  patterns over dataset (run) ids; `principal_for` resolves an
  identity to a CL-11 `Principal` scoped to exactly the requested
  dataset when a pattern matches, so `runtime.can` and the
  `EvidenceGateway` checks stay unchanged and dataset-scoped.
- **The audit actor is the identity.** `actor_id` is
  `oidc:<claim value>` (the stable `sub` claim by default), so every
  audit entry written through a principal names the authenticated
  person, never a demo label.

Pure standard library; the web layer does the OIDC protocol work.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._validation import make_need
from .runtime import Principal

IDENTITY_MAPPING_SCHEMA = "covertlens.identity-mapping"
IDENTITY_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "identity-mapping.json"
)
HUMAN_ROLES = ("viewer", "researcher", "reviewer", "operator", "approver")
MATCH_OPERATORS = ("equals", "contains", "suffix")
ANONYMOUS_ACTOR = "anonymous"
_ACTOR_SAFE = re.compile(r"[^A-Za-z0-9@._:+-]")


@dataclass(frozen=True)
class Identity:
    """One authenticated person and the grants their claims map to."""

    subject: str
    issuer: str
    actor_id: str
    roles: frozenset[str] = frozenset({"viewer"})
    dataset_patterns: tuple[str, ...] = ()
    display_name: str = ""
    email: str = ""
    auth_method: str = "oidc"
    matched_rules: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "issuer": self.issuer,
            "actor_id": self.actor_id,
            "roles": sorted(self.roles),
            "dataset_patterns": list(self.dataset_patterns),
            "display_name": self.display_name,
            "email": self.email,
            "auth_method": self.auth_method,
            "matched_rules": list(self.matched_rules),
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Identity:
        return cls(
            subject=str(doc["subject"]),
            issuer=str(doc["issuer"]),
            actor_id=str(doc["actor_id"]),
            roles=frozenset(doc.get("roles") or ()),
            dataset_patterns=tuple(doc.get("dataset_patterns") or ()),
            display_name=str(doc.get("display_name") or ""),
            email=str(doc.get("email") or ""),
            auth_method=str(doc.get("auth_method") or "oidc"),
            matched_rules=tuple(doc.get("matched_rules") or ()),
        )

    def covers(self, dataset_id: str) -> bool:
        return any(
            fnmatch.fnmatchcase(dataset_id, pattern)
            for pattern in self.dataset_patterns
        )


@dataclass(frozen=True)
class IdentityMapping:
    """Versioned claim -> (roles, dataset scopes) rules."""

    version: str
    rules: tuple[dict[str, Any], ...] = ()
    default_roles: frozenset[str] = frozenset({"viewer"})
    default_datasets: tuple[str, ...] = ()
    actor_id_claim: str = "sub"
    groups_claim: str = "groups"
    doc: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def load_identity_mapping(path: str | Path | None = None) -> IdentityMapping:
    """Load and validate the mapping file; raises ValueError when invalid."""
    doc = json.loads(Path(path or IDENTITY_MAPPING_PATH).read_text())
    errors = validate_identity_mapping(doc)
    if errors:
        raise ValueError("invalid identity mapping: " + "; ".join(errors))
    default = doc.get("default") or {}
    return IdentityMapping(
        version=str(doc["mapping_version"]),
        rules=tuple(doc.get("rules") or ()),
        default_roles=frozenset(default.get("roles") or ["viewer"]),
        default_datasets=tuple(default.get("datasets") or ()),
        actor_id_claim=str(doc.get("actor_id_claim") or "sub"),
        groups_claim=str(doc.get("groups_claim") or "groups"),
        doc=doc,
    )


def _claim_values(claims: dict[str, Any], name: str) -> list[str]:
    value = claims.get(name)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if isinstance(value, str) and name == "scope":
        return value.split()
    return [str(value)]


def _rule_matches(rule: dict[str, Any], claims: dict[str, Any]) -> bool:
    match = rule.get("match") or {}
    values = _claim_values(claims, str(match.get("claim") or ""))
    expected = str(match.get("value") or "")
    operator = match.get("op", "equals")
    if operator == "equals":
        return expected in values
    if operator == "contains":
        return any(expected in v for v in values)
    if operator == "suffix":
        return any(v.endswith(expected) for v in values)
    return False


def _actor(claims: dict[str, Any], claim: str) -> str:
    raw = str(claims.get(claim) or claims.get("sub") or "")
    safe = _ACTOR_SAFE.sub("_", raw)[:200]
    if not safe:
        raise ValueError("identity has no subject")
    return f"oidc:{safe}"


def identity_from_claims(
    claims: dict[str, Any],
    mapping: IdentityMapping,
    *,
    auth_method: str = "oidc",
) -> Identity:
    """Map validated token claims to roles and dataset scopes.

    Every matching rule adds its roles and dataset patterns. With no
    match the mapping default applies (shipped: viewer, no datasets).
    """
    subject = str(claims.get("sub") or "")
    if not subject:
        raise ValueError("identity has no subject")
    roles: set[str] = set()
    patterns: list[str] = []
    matched: list[str] = []
    for rule in mapping.rules:
        if _rule_matches(rule, claims):
            roles.update(rule.get("roles") or ())
            patterns.extend(rule.get("datasets") or ())
            matched.append(str(rule.get("id") or ""))
    if not matched:
        roles = set(mapping.default_roles)
        patterns = list(mapping.default_datasets)
    roles = {r for r in roles if r in HUMAN_ROLES} or {"viewer"}
    return Identity(
        subject=subject,
        issuer=str(claims.get("iss") or ""),
        actor_id=_actor(claims, mapping.actor_id_claim),
        roles=frozenset(roles),
        dataset_patterns=tuple(dict.fromkeys(patterns)),
        display_name=str(
            claims.get("name")
            or claims.get("preferred_username")
            or claims.get("email")
            or ""
        )[:120],
        email=str(claims.get("email") or "")[:200],
        auth_method=auth_method,
        matched_rules=tuple(matched),
    )


def principal_for(identity: Identity | None, dataset_id: str) -> Principal:
    """CL-11 principal for one request on one dataset (deny by default)."""
    if identity is None:
        return Principal(actor_id=ANONYMOUS_ACTOR, roles=frozenset({"viewer"}))
    datasets = frozenset({dataset_id}) if identity.covers(dataset_id) else frozenset()
    return Principal(
        actor_id=identity.actor_id, roles=identity.roles, datasets=datasets
    )


def validate_identity_mapping(doc: dict[str, Any]) -> list[str]:
    """Return validation errors for a mapping document; empty is valid."""
    errors: list[str] = []
    need = make_need(errors)
    need(
        doc.get("schema") == IDENTITY_MAPPING_SCHEMA,
        f"schema must be {IDENTITY_MAPPING_SCHEMA}",
    )
    need(bool(doc.get("mapping_version")), "mapping_version is required")
    default = doc.get("default") or {}
    for role in default.get("roles") or []:
        need(role in HUMAN_ROLES, f"default role {role!r} is not a human role")
    need(
        not (default.get("datasets") or []),
        "the default grant must not include datasets (deny by default)",
    )
    seen: set[str] = set()
    for index, rule in enumerate(doc.get("rules") or []):
        prefix = f"rules[{index}]"
        rule_id = str(rule.get("id") or "")
        need(bool(rule_id), f"{prefix}.id is required")
        need(rule_id not in seen, f"{prefix}.id {rule_id!r} is duplicated")
        seen.add(rule_id)
        match = rule.get("match") or {}
        need(bool(match.get("claim")), f"{prefix}.match.claim is required")
        need(bool(match.get("value")), f"{prefix}.match.value is required")
        need(
            match.get("op", "equals") in MATCH_OPERATORS,
            f"{prefix}.match.op must be one of {MATCH_OPERATORS}",
        )
        roles = rule.get("roles") or []
        need(bool(roles), f"{prefix}.roles must not be empty")
        for role in roles:
            need(
                role in HUMAN_ROLES,
                f"{prefix} grants {role!r}; only human roles {HUMAN_ROLES} may be mapped",
            )
        for pattern in rule.get("datasets") or []:
            need(
                isinstance(pattern, str) and bool(pattern.strip()),
                f"{prefix}.datasets entries must be non-empty patterns",
            )
    return errors
