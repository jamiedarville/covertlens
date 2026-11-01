"""CL-46 acceptance: structure test v2 and structured fixtures."""

import json

import pytest

from covertlens.geo_benchmark import build_structured_pair, run_structured_recall
from covertlens.geometric import (
    CODES_V2,
    GeometricConfig,
    analyze_geometric_bytes,
    validate_geometric_report,
)
from covertlens.geometric_fixtures import SUBFAMILIES, build_geo_pair
from covertlens.runtime import (
    AuditLog,
    EvidenceGateway,
    Principal,
    validate_runtime_policy,
    load_runtime_policy,
)
from covertlens.store import ArtifactStore

DATASET = "ds_structure"


def test_every_channel_has_an_applicable_code():
    assert set(CODES_V2) == {"height", "gap", "lit", "colour", "angle"}
    names = {c["code"] for codes in CODES_V2.values() for c in codes}
    assert {"alphabet_position_a0", "alphabet_position_a1",
            "timing_ratios", "bit_packing", "base_k_digits",
            "ordinal_rank"} <= names


def test_wordlist_is_hashed_into_the_config():
    config = GeometricConfig().to_dict()
    assert config["structure"]["wordlist_sha256"].startswith("sha256:")
    assert config["structure"]["min_symbols"] >= 4
    assert config["structure"]["alpha"] <= 0.05


@pytest.mark.parametrize("subfamily", SUBFAMILIES)
def test_structure_detected_from_pixels_per_subfamily(subfamily):
    _clean, encoded = build_structured_pair(subfamily, 0)
    report = analyze_geometric_bytes(encoded.data)
    assert validate_geometric_report(report) == []
    assert report["classification"] == "structure_claimed", (
        subfamily, report["structure"])
    assert report["structure"]["null_exceedance"] <= 0.01


def test_structure_recall_at_least_0p8_with_n20_per_subfamily():
    rows = run_structured_recall(20)
    for subfamily, row in rows.items():
        assert row["n"] >= 20
        assert row["structure_recall"]["rate"] >= 0.8, (subfamily, row)


def test_finding_contains_no_mapped_text_and_gateway_roles():
    _clean, encoded = build_structured_pair("height_position", 0)
    report = analyze_geometric_bytes(encoded.data)
    finding_json = json.dumps(report["finding"].to_dict())
    assert "DECAF" not in finding_json
    assert "mapped_preview" not in finding_json

    gateway = EvidenceGateway(ArtifactStore(), AuditLog())
    decode_id = gateway.record_candidate_decode(
        DATASET, "ver_height_1", report["candidate_decode"])
    assert decode_id is not None
    reviewer = Principal("rev-1", roles={"reviewer"}, datasets={DATASET})
    researcher = Principal("res-1", roles={"researcher"}, datasets={DATASET})
    decode = gateway.read_candidate_decode(reviewer, DATASET, decode_id)
    assert decode["text"].startswith("DECAF")
    with pytest.raises(PermissionError):
        gateway.read_candidate_decode(researcher, DATASET, decode_id)
    # Denial is audited and the chain still verifies; the text never
    # appears in audit details.
    from dataclasses import asdict
    assert gateway._audit.verify_chain() is True
    entries = [asdict(e) for e in gateway._audit.entries]
    assert any(e["action"] == "candidate_decode.read"
               and e["outcome"] == "denied" for e in entries)
    assert "DECAF" not in json.dumps(entries)


def test_payload_modes_encode_expected_streams():
    # Morse on gap: SOS -> dit/dah stream with letter separators.
    _c, gap = build_geo_pair("gap_timing", payload_mode="morse",
                             payload_text="SOS", scene_seed=99)
    assert gap.symbols[:8] == (0, 0, 0, 2, 1, 1, 1, 2)
    assert gap.encoder["config"]["payload_mode"] == "morse"
    # ASCII on lit: bits of the payload bytes, MSB first.
    _c2, lit = build_geo_pair("lit_dark", payload_mode="ascii",
                              payload_text="A", scene_seed=99)
    assert lit.symbols[:8] == tuple((0x41 >> s) & 1 for s in range(7, -1, -1))
    # Word on height: letter positions.
    _c3, height = build_geo_pair("height_position", payload_mode="word",
                                 payload_text="CAB", scene_seed=99)
    assert height.symbols[:6] == (2, 0, 1, 2, 0, 1)


def test_random_payloads_rarely_claim_structure():
    claimed = 0
    for seed in (11, 23, 37, 41, 53, 67):
        _clean, encoded = build_geo_pair(
            "height_position", scene_seed=seed * 3, payload_seed=seed)
        report = analyze_geometric_bytes(encoded.data)
        claimed += report["classification"] == "structure_claimed"
    assert claimed == 0


def test_runtime_policy_has_reviewer_decode_permission():
    policy = load_runtime_policy()
    assert validate_runtime_policy(policy) == []
    assert "candidate.decode.read" in policy["permissions"]
    assert "candidate.decode.read" in policy["roles"]["reviewer"]["allow"]
    assert "candidate.decode.read" not in policy["roles"]["researcher"]["allow"]
