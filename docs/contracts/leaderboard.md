# Leaderboard of encoder strategies vs detector versions (CL-70)

Implements: CL-70 (OP-02, OP-06). Schema:
[schemas/leaderboard-entry.schema.json](../../schemas/leaderboard-entry.schema.json).
Module: `covertlens.leaderboard`; page `/leaderboard`.

## What is recorded

A submission is one image made on the Generate page (CL-51), named by
its `artifact_version_id`. The server finds it in the red-team index,
checks the stored bytes against the recorded content hash, scores them
itself under the shipped freeze (`analyze_all_bytes` + `decide_verdict`,
in the analysis process pool), and stores an entry with:

- `pin_hash`, `detectors`, `threshold_config_version`: the CL-26 pin
  of the release configuration, the same `pin_hash` the CL-65
  scorecard publishes (CL-9 dataset, detector name@versions, freeze
  version and statuses, geometric config version);
- `encoder`: the Generate page's caller-facing parameters plus encoder
  name and version; hidden attacker grids stay hidden (`grid_full` and
  encoder config are never published, and for a hidden grid the scene
  and payload seeds it is derived from are dropped too);
- `outcome`: verdict, per-family max scores, and `evades` for each
  operating point (triage = verdict `log`, quarantine = `log`/`flag`,
  fail-run = not `fail_run`); `payload.bits` (bytes × 8, or
  symbols × log2(alphabet) for geometric) and bits per pixel;
- `submitter.display_name` (public) and the account id (moderators
  only); `status` and an append-only `moderation` history.

Outcomes are evidence about an encoder against a pinned detector,
never a collusion finding (`equated_with_collusion: false`).

## Boards and ranking

- One board per pin hash. A new detector version, freeze or benchmark
  dataset changes the pin, so `GET /api/leaderboard` shows an empty
  current board while every older board stays readable at
  `GET /api/leaderboard/boards/{pin_hash}`; entries are never rescored
  or moved. The pin is recomputed from the live detector versions, so
  a deployment with bumped detectors starts a new board on restart.
- For each operating point the board ranks visible entries that stayed
  below it by payload bits carried (ties: bits per pixel, then the
  earliest submission). Triage is the headline board.
- One artifact can be submitted once per board (409 on a repeat).

## Public deployments

- **Rate limiting:** `COVERTLENS_LEADERBOARD_RATE_PER_HOUR` (default 20)
  submissions per identity, or per client address when anonymous;
  idle windows are evicted. Generation and analysis keep their own
  per-minute limit.
- **Sign-in:** in OIDC mode (CL-67) submitting needs a signed-in
  identity; the display name defaults to the identity's name. Display
  names are 1–40 letters, digits, spaces, `.`, `_` or `-`.
- **Moderation:** `COVERTLENS_LEADERBOARD_MODERATION` (default on in
  OIDC mode, off otherwise) makes new entries `pending` until approved.
  `POST /api/leaderboard/entries/{id}/moderation` (`approve` or `hide`,
  optional reason) and `GET /api/leaderboard/pending` need the
  runtime-policy permission `leaderboard.moderate` on dataset
  `leaderboard`, granted to `operator` (policy 1.2.0). Hidden and
  pending entries are not served publicly.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| Changing the detector version starts a new leaderboard; old entries stay visible under their pin hash | `tests/test_leaderboard.py::test_changing_detector_version_starts_a_new_board_over_http` (monkeypatched detector version: empty current board, old board listed and served by pin hash, the same artifact accepted on the new board), `test_new_detector_version_starts_a_new_board_and_old_entries_stay`, `test_configuration_pin_matches_the_scorecard_and_tracks_detectors` |
| Submissions recorded with encoder parameters and outcome; ranked by payload below each operating point | `test_submission_is_scored_server_side_and_ranked`, `test_ranks_by_payload_below_each_operating_point`, `test_hidden_attacker_grid_is_never_published` |
| Rate limiting and moderation | `test_submissions_are_rate_limited`, `test_public_deployment_moderates_and_needs_sign_in`, `test_duplicates_moderation_and_validation` |
