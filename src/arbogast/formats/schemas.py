"""Versioned schema identifiers and minimal structural validation.

The identifiers are part of Arbogast's public interchange contract.  Schema
versions are explicit; readers must never guess a document type from fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Final

from .canonical import JSONValue, normalize_json

TASK_SCHEMA: Final = "arbogast.fleet.task.v1"
SHARD_SCHEMA: Final = "arbogast.fleet.shard.v1"
PLAN_SCHEMA: Final = "arbogast.fleet.plan.v1"
ARTIFACT_SCHEMA: Final = "arbogast.fleet.artifact.v1"
RUN_SCHEMA: Final = "arbogast.fleet.run.v1"
OPERATION_DESCRIPTION_SCHEMA: Final = "arbogast.agent.operation-description.v1"
AGENT_MANIFEST_SCHEMA: Final = "arbogast.agent.manifest.v1"
AGENT_TASK_SCHEMA: Final = "arbogast.agent.task.v1"
AGENT_CONTEXT_SCHEMA: Final = "arbogast.agent.context.v1"
OPERATION_CODE_DEPENDENCIES_SCHEMA: Final = "arbogast.agent.operation-code-dependencies.v1"
CODE_DEPENDENCY_GRAPH_SCHEMA: Final = "arbogast.agent.code-dependency-graph.v1"
ROUTE_SCHEMA: Final = "arbogast.agent.route.v1"
HAZARD_SCHEMA: Final = "arbogast.agent.hazard.v1"
BACKEND_STATUS_SCHEMA: Final = "arbogast.backend.status.v1"
CLI_VERSION_SCHEMA: Final = "arbogast.cli.version.v1"
CLI_BACKENDS_SCHEMA: Final = "arbogast.cli.backends.v1"
CLI_DESCRIBE_SCHEMA: Final = "arbogast.cli.describe.v1"
CLI_VERIFY_SCHEMA: Final = "arbogast.cli.verify.v1"
CLI_CLAIMS_SCHEMA: Final = "arbogast.cli.claims.v1"
CLI_PROOF_GAP_SCHEMA: Final = "arbogast.cli.proof-gap.v1"
CLI_ROUTE_SCHEMA: Final = "arbogast.cli.route.v1"
CLI_CAMPAIGN_SCHEMA: Final = "arbogast.cli.campaign.v1"

# Certified-arithmetic object identities introduced in 0.2.0.  These are v1
# interchange schemas: the package release and the schema version are kept as
# independent axes so a future Arbogast release can continue reading these
# exact documents without renaming them.
NUMBER_FIELD_SCHEMA: Final = "arbogast.galois.number-field/v1"
NUMBER_FIELD_ELEMENT_SCHEMA: Final = "arbogast.galois.number-field-element/v1"
FIELD_EMBEDDING_SCHEMA: Final = "arbogast.galois.field-embedding/v1"
IDEAL_SCHEMA: Final = "arbogast.galois.ideal/v1"
FINITE_PLACE_SCHEMA: Final = "arbogast.galois.finite-place/v1"
INFINITE_PLACE_SCHEMA: Final = "arbogast.galois.infinite-place/v1"

# Independently versioned Galois and arithmetic receipt families.  The values
# intentionally match the receipt classes' existing ``schema_version``
# contracts; registering them here makes the public schema catalog complete
# without introducing a new evidence layer.
FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA: Final = "arbogast.galois.finite-quotient-receipt/v1"
GALOIS_MODULE_RECEIPT_SCHEMA: Final = "arbogast.galois.module-receipt/v1"
KUMMER_RECEIPT_SCHEMA: Final = "arbogast.galois.kummer/v1"
LOCAL_H1_RECEIPT_SCHEMA: Final = "arbogast.galois.local-h1/v1"
LOCALIZATION_RECEIPT_SCHEMA: Final = "arbogast.galois.localization/v1"
TWIST_RECEIPT_SCHEMA: Final = "arbogast.galois.twists/v1"

AIM_RECEIPT_SCHEMA: Final = "arbogast.aim/v1"
CARTIER_DUAL_RECEIPT_SCHEMA: Final = "arbogast.cartier-dual/v1"
DESCENT_RECEIPT_SCHEMA: Final = "arbogast.descent/v1"
DUAL_SELMER_RECEIPT_SCHEMA: Final = "arbogast.dual-selmer/v1"
LOCAL_CONDITION_RECEIPT_SCHEMA: Final = "arbogast.local-condition/v1"
LOCAL_PAIRING_RECEIPT_SCHEMA: Final = "arbogast.local-pairing/v1"
SELMER_RECEIPT_SCHEMA: Final = "arbogast.selmer/v1"

# Finite-exact deformation identities introduced in 0.3.0.  As with the
# arithmetic schemas above, release versions and interchange versions are
# independent: later releases must continue to recognize these exact v1
# documents unless a new schema identifier is explicitly introduced.
DEFORM_ARTIN_RING_SCHEMA_V1: Final = "arbogast.deform.artin-ring/v1"
DEFORM_ARTIN_RING_ELEMENT_SCHEMA_V1: Final = "arbogast.deform.artin-ring-element/v1"
DEFORM_ARTIN_RING_MAP_SCHEMA_V1: Final = "arbogast.deform.artin-ring-map/v1"
DEFORM_SMALL_EXTENSION_SCHEMA_V1: Final = "arbogast.deform.small-extension/v1"
DEFORM_COMPLEX_SCHEMA_V1: Final = "arbogast.deform.complex/v1"
DEFORM_PRESENTATION_SCHEMA_V1: Final = "arbogast.deform.presentation/v1"
DEFORM_PROBLEM_SCHEMA_V1: Final = "arbogast.deform.problem/v1"
DEFORM_FRAMING_SCHEMA_V1: Final = "arbogast.deform.framing/v1"
DEFORM_ACTION_SCHEMA_V1: Final = "arbogast.deform.action/v1"
DEFORM_EQUIVARIANT_SCHEMA_V1: Final = "arbogast.deform.equivariant/v1"
DEFORM_INVARIANT_DEFORMATIONS_SCHEMA_V1: Final = "arbogast.deform.invariant-deformations/v1"
DEFORM_EQUIVARIANT_COMPONENT_SCHEMA_V1: Final = "arbogast.deform.equivariant-component/v1"
DEFORM_EQUIVARIANT_DECOMPOSITION_SCHEMA_V1: Final = "arbogast.deform.equivariant-decomposition/v1"
DEFORM_GAUGE_SPACE_SCHEMA_V1: Final = "arbogast.deform.gauge-space/v1"
DEFORM_TANGENT_SPACE_SCHEMA_V1: Final = "arbogast.deform.tangent-space/v1"
DEFORM_OBSTRUCTION_SPACE_SCHEMA_V1: Final = "arbogast.deform.obstruction-space/v1"
DEFORM_OBSTRUCTION_CLASS_SCHEMA_V1: Final = "arbogast.deform.obstruction-class/v1"
DEFORM_LIFT_DATUM_SCHEMA_V1: Final = "arbogast.deform.lift-datum/v1"
DEFORM_LIFT_FAMILY_SCHEMA_V1: Final = "arbogast.deform.lift-family/v1"
DEFORM_LIFT_OBSTRUCTED_SCHEMA_V1: Final = "arbogast.deform.lift-obstructed/v1"
DEFORM_LIFT_UNKNOWN_SCHEMA_V1: Final = "arbogast.deform.lift-unknown/v1"
DEFORM_UNIQUE_LIFT_SCHEMA_V1: Final = "arbogast.deform.unique-lift/v1"
DEFORM_NONUNIQUE_LIFT_SCHEMA_V1: Final = "arbogast.deform.nonunique-lift/v1"
DEFORM_LIFT_ENDOMORPHISM_SCHEMA_V1: Final = "arbogast.deform.lift-endomorphism/v1"
DEFORM_CONTRACTION_CERTIFICATE_SCHEMA_V1: Final = "arbogast.deform.contraction-certificate/v1"
DEFORM_FIXED_LIFT_SCHEMA_V1: Final = "arbogast.deform.fixed-lift/v1"
DEFORM_RIGID_SCHEMA_V1: Final = "arbogast.deform.rigid/v1"
DEFORM_NONRIGID_SCHEMA_V1: Final = "arbogast.deform.nonrigid/v1"
DEFORM_UNSUPPORTED_SCHEMA_V1: Final = "arbogast.deform.unsupported/v1"

# Each deformation proving receipt evolves independently while sharing the
# same portable verifier and central VerificationCertificate envelope.
DEFORM_ARTIN_RING_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.artin-ring-receipt/v1"
DEFORM_ARTIN_MAP_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.artin-map-receipt/v1"
DEFORM_SMALL_EXTENSION_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.small-extension-receipt/v1"
DEFORM_COMPLEX_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.complex-receipt/v1"
DEFORM_PROBLEM_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.problem-receipt/v1"
DEFORM_GAUGE_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.gauge-receipt/v1"
DEFORM_TANGENT_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.tangent-receipt/v1"
DEFORM_OBSTRUCTION_SPACE_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.obstruction-space-receipt/v1"
DEFORM_OBSTRUCTION_CLASS_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.obstruction-class-receipt/v1"
DEFORM_FRAMING_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.framing-receipt/v1"
DEFORM_ACTION_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.action-receipt/v1"
DEFORM_EQUIVARIANT_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.equivariant-receipt/v1"
DEFORM_INVARIANT_COMPLEX_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.invariant-complex-receipt/v1"
DEFORM_DECOMPOSITION_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.decomposition-receipt/v1"
DEFORM_LIFT_DATUM_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.lift-datum-receipt/v1"
DEFORM_LIFT_FAMILY_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.lift-family-receipt/v1"
DEFORM_LIFT_OBSTRUCTED_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.lift-obstructed-receipt/v1"
DEFORM_LIFT_UNKNOWN_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.lift-unknown-receipt/v1"
DEFORM_UNIQUE_LIFT_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.unique-lift-receipt/v1"
DEFORM_NONUNIQUE_LIFT_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.nonunique-lift-receipt/v1"
DEFORM_LIFT_ENDOMORPHISM_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.lift-endomorphism-receipt/v1"
DEFORM_CONTRACTION_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.contraction-receipt/v1"
DEFORM_FIXED_LIFT_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.fixed-lift-receipt/v1"
DEFORM_RIGID_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.rigid-receipt/v1"
DEFORM_NONRIGID_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.nonrigid-receipt/v1"
DEFORM_UNSUPPORTED_RECEIPT_SCHEMA_V1: Final = "arbogast.deform.unsupported-receipt/v1"

# Exact-dyadic numerical bridge identities introduced in 0.4.0.  Runtime
# objects and proving receipts evolve independently: a future package release
# may keep reading these v1 documents while adding a separately named schema.
NUMERIC_DYADIC_SCHEMA_V1: Final = "arbogast.numeric.dyadic/v1"
NUMERIC_COMPLEX_DYADIC_SCHEMA_V1: Final = "arbogast.numeric.complex-dyadic/v1"
NUMERIC_REAL_BALL_SCHEMA_V1: Final = "arbogast.numeric.real-ball/v1"
NUMERIC_COMPLEX_BALL_SCHEMA_V1: Final = "arbogast.numeric.complex-ball/v1"
NUMERIC_EXACT_POLYNOMIAL_SCHEMA_V1: Final = "arbogast.numeric.exact-polynomial/v1"
NUMERIC_POLYNOMIAL_SYSTEM_SCHEMA_V1: Final = "arbogast.numeric.polynomial-system/v1"
NUMERIC_POLYNOMIAL_FAMILY_SCHEMA_V1: Final = "arbogast.numeric.polynomial-family/v1"
NUMERIC_PARAMETER_PATH_SCHEMA_V1: Final = "arbogast.numeric.parameter-path/v1"
NUMERIC_POINT_SCHEMA_V1: Final = "arbogast.numeric.point/v1"
NUMERIC_EXACT_COVER_SCHEMA_V1: Final = "arbogast.numeric.exact-cover/v1"
NUMERIC_CONTINUATION_STEP_SCHEMA_V1: Final = "arbogast.numeric.continuation-step/v1"
NUMERIC_CONTINUATION_TUBE_SCHEMA_V1: Final = "arbogast.numeric.continuation-tube/v1"
NUMERIC_CONTINUATION_RESULT_SCHEMA_V1: Final = "arbogast.numeric.continuation-result/v1"
NUMERIC_CONDITION_BOUND_SCHEMA_V1: Final = "arbogast.numeric.condition-bound/v1"
NUMERIC_RECOGNITION_BOUNDS_SCHEMA_V1: Final = "arbogast.numeric.recognition-bounds/v1"
NUMERIC_ALGEBRAIC_CANDIDATE_SCHEMA_V1: Final = "arbogast.numeric.algebraic-candidate/v1"
NUMERIC_EXACTIFICATION_RESULT_SCHEMA_V1: Final = "arbogast.numeric.exactification-result/v1"
NUMERIC_REGULAR_FIBER_WITNESS_SCHEMA_V1: Final = "arbogast.numeric.regular-fiber-witness/v1"
NUMERIC_GENERIC_DEGREE_WITNESS_SCHEMA_V1: Final = "arbogast.numeric.generic-degree-witness/v1"
NUMERIC_REGULAR_FIBER_DEGREE_SCHEMA_V1: Final = "arbogast.numeric.regular-fiber-degree/v1"
NUMERIC_DEGREE_RESULT_SCHEMA_V1: Final = "arbogast.numeric.degree-result/v1"
NUMERIC_BRANCH_LOOP_SCHEMA_V1: Final = "arbogast.numeric.branch-loop/v1"
NUMERIC_BRANCH_TRACKING_SCHEMA_V1: Final = "arbogast.numeric.branch-tracking/v1"
NUMERIC_NUMERICAL_COVER_SCHEMA_V1: Final = "arbogast.numeric.numerical-cover/v1"
NUMERIC_BRANCH_CYCLE_TUPLE_SCHEMA_V1: Final = "arbogast.numeric.branch-cycle-tuple/v1"
NUMERIC_NIELSEN_VERTEX_SCHEMA_V1: Final = "arbogast.numeric.nielsen-vertex/v1"
NUMERIC_BRAID_CONTINUATION_WITNESS_SCHEMA_V1: Final = (
    "arbogast.numeric.braid-continuation-witness/v1"
)
NUMERIC_QUADRATIC_B2_HOMOTOPY_SCHEMA_V1: Final = "arbogast.numeric.quadratic-b2-homotopy/v1"
NUMERIC_BRAID_CONTINUATION_RESULT_SCHEMA_V1: Final = "arbogast.numeric.braid-continuation-result/v1"
NUMERIC_WEIGHTED_BRAID_PLAN_SCHEMA_V1: Final = "arbogast.numeric.weighted-braid-plan/v1"
NUMERIC_UNKNOWN_SCHEMA_V1: Final = "arbogast.numeric.unknown/v1"
NUMERIC_UNSUPPORTED_SCHEMA_V1: Final = "arbogast.numeric.unsupported/v1"

# Every numeric runtime identity has a one-to-one receipt identity.  Receipts
# share the central VerificationCertificate envelope but remain independently
# versioned so their exact replay contracts cannot be inferred from objects.
NUMERIC_DYADIC_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.dyadic-receipt/v1"
NUMERIC_COMPLEX_DYADIC_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.complex-dyadic-receipt/v1"
NUMERIC_REAL_BALL_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.real-ball-receipt/v1"
NUMERIC_COMPLEX_BALL_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.complex-ball-receipt/v1"
NUMERIC_EXACT_POLYNOMIAL_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.exact-polynomial-receipt/v1"
NUMERIC_POLYNOMIAL_SYSTEM_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.polynomial-system-receipt/v1"
NUMERIC_POLYNOMIAL_FAMILY_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.polynomial-family-receipt/v1"
NUMERIC_PARAMETER_PATH_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.parameter-path-receipt/v1"
NUMERIC_POINT_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.point-receipt/v1"
NUMERIC_EXACT_COVER_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.exact-cover-receipt/v1"
NUMERIC_CONTINUATION_STEP_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.continuation-step-receipt/v1"
NUMERIC_CONTINUATION_TUBE_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.continuation-tube-receipt/v1"
NUMERIC_CONTINUATION_RESULT_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.continuation-result-receipt/v1"
)
NUMERIC_CONDITION_BOUND_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.condition-bound-receipt/v1"
NUMERIC_RECOGNITION_BOUNDS_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.recognition-bounds-receipt/v1"
)
NUMERIC_ALGEBRAIC_CANDIDATE_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.algebraic-candidate-receipt/v1"
)
NUMERIC_EXACTIFICATION_RESULT_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.exactification-result-receipt/v1"
)
NUMERIC_REGULAR_FIBER_WITNESS_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.regular-fiber-witness-receipt/v1"
)
NUMERIC_GENERIC_DEGREE_WITNESS_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.generic-degree-witness-receipt/v1"
)
NUMERIC_REGULAR_FIBER_DEGREE_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.regular-fiber-degree-receipt/v1"
)
NUMERIC_DEGREE_RESULT_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.degree-result-receipt/v1"
NUMERIC_BRANCH_LOOP_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.branch-loop-receipt/v1"
NUMERIC_BRANCH_TRACKING_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.branch-tracking-receipt/v1"
NUMERIC_NUMERICAL_COVER_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.numerical-cover-receipt/v1"
NUMERIC_BRANCH_CYCLE_TUPLE_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.branch-cycle-tuple-receipt/v1"
)
NUMERIC_NIELSEN_VERTEX_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.nielsen-vertex-receipt/v1"
NUMERIC_BRAID_CONTINUATION_WITNESS_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.braid-continuation-witness-receipt/v1"
)
NUMERIC_QUADRATIC_B2_HOMOTOPY_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.quadratic-b2-homotopy-receipt/v1"
)
NUMERIC_BRAID_CONTINUATION_RESULT_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.braid-continuation-result-receipt/v1"
)
NUMERIC_WEIGHTED_BRAID_PLAN_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.numeric.weighted-braid-plan-receipt/v1"
)
NUMERIC_UNKNOWN_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.unknown-receipt/v1"
NUMERIC_UNSUPPORTED_RECEIPT_SCHEMA_V1: Final = "arbogast.numeric.unsupported-receipt/v1"

# Bounded finite-exact p-adic identities introduced after 0.4.0.  Runtime
# objects and proving receipts keep independent schema identifiers so the
# finite-precision, reduction, lifting, and descent boundaries remain literal.
PADIC_AUTOMORPHISM_SCHEMA_V1: Final = "arbogast.padic.automorphism/v1"
PADIC_AUTOMORPHISM_TRIVIALITY_WITNESS_SCHEMA_V1: Final = (
    "arbogast.padic.automorphism-triviality-witness/v1"
)
PADIC_BALL_SCHEMA_V1: Final = "arbogast.padic.ball/v1"
PADIC_BRANCH_FIBER_WITNESS_SCHEMA_V1: Final = "arbogast.padic.branch-fiber-witness/v1"
PADIC_CERTIFIED_SCHEMA_V1: Final = "arbogast.padic.certified/v1"
PADIC_COMPONENT_MAP_WITNESS_SCHEMA_V1: Final = "arbogast.padic.component-map-witness/v1"
PADIC_DEFORMATION_DATUM_WITNESS_SCHEMA_V1: Final = "arbogast.padic.deformation-datum-witness/v1"
PADIC_DEFORMATION_DATUM_SCHEMA_V1: Final = "arbogast.padic.deformation-datum/v1"
PADIC_DEFORMATION_SIGNATURE_SCHEMA_V1: Final = "arbogast.padic.deformation-signature/v1"
PADIC_DERIVATIVE_WITNESS_SCHEMA_V1: Final = "arbogast.padic.derivative-witness/v1"
PADIC_DESCENDED_MODEL_SCHEMA_V1: Final = "arbogast.padic.descended-model/v1"
PADIC_DESCENT_COCYCLE_SCHEMA_V1: Final = "arbogast.padic.descent-cocycle/v1"
PADIC_DESCENT_ISOMORPHISM_SCHEMA_V1: Final = "arbogast.padic.descent-isomorphism/v1"
PADIC_ELEMENT_SCHEMA_V1: Final = "arbogast.padic.element/v1"
PADIC_FIBER_FACTOR_SCHEMA_V1: Final = "arbogast.padic.fiber-factor/v1"
PADIC_FIELD_WITNESS_SCHEMA_V1: Final = "arbogast.padic.field-witness/v1"
PADIC_FIELD_SCHEMA_V1: Final = "arbogast.padic.field/v1"
PADIC_FINITE_FIELD_FACTOR_SCHEMA_V1: Final = "arbogast.padic.finite-field-factor/v1"
PADIC_FINITE_INERTIA_QUOTIENT_SCHEMA_V1: Final = "arbogast.padic.finite-inertia-quotient/v1"
PADIC_FINITE_LIFT_ACTION_SCHEMA_V1: Final = "arbogast.padic.finite-lift-action/v1"
PADIC_FIXED_LIFT_SET_SCHEMA_V1: Final = "arbogast.padic.fixed-lift-set/v1"
PADIC_FIXED_LIFT_SCHEMA_V1: Final = "arbogast.padic.fixed-lift/v1"
PADIC_FROBENIUS_OPERATOR_SCHEMA_V1: Final = "arbogast.padic.frobenius-operator/v1"
PADIC_GOOD_REDUCTION_WITNESS_SCHEMA_V1: Final = "arbogast.padic.good-reduction-witness/v1"
PADIC_GOOD_REDUCTION_SCHEMA_V1: Final = "arbogast.padic.good-reduction/v1"
PADIC_INERTIA_FILTRATION_SCHEMA_V1: Final = "arbogast.padic.inertia-filtration/v1"
PADIC_INERTIA_REPRESENTATION_SCHEMA_V1: Final = "arbogast.padic.inertia-representation/v1"
PADIC_LIFT_CANDIDATE_SCHEMA_V1: Final = "arbogast.padic.lift-candidate/v1"
PADIC_LIFT_CHART_SCHEMA_V1: Final = "arbogast.padic.lift-chart/v1"
PADIC_LIFT_ENUMERATION_WITNESS_SCHEMA_V1: Final = "arbogast.padic.lift-enumeration-witness/v1"
PADIC_LIFT_GALOIS_ACTION_SCHEMA_V1: Final = "arbogast.padic.lift-galois-action/v1"
PADIC_LIFT_SET_SCHEMA_V1: Final = "arbogast.padic.lift-set/v1"
PADIC_LIFT_TRANSPORT_WITNESS_SCHEMA_V1: Final = "arbogast.padic.lift-transport-witness/v1"
PADIC_LOCAL_FACTORIZATION_FRAGMENT_SCHEMA_V1: Final = (
    "arbogast.padic.local-factorization-fragment/v1"
)
PADIC_LOCAL_FIELD_EMBEDDING_SCHEMA_V1: Final = "arbogast.padic.local-field-embedding/v1"
PADIC_MARKED_REDUCTION_COMPONENT_SCHEMA_V1: Final = "arbogast.padic.marked-reduction-component/v1"
PADIC_MATRIX_SCHEMA_V1: Final = "arbogast.padic.matrix/v1"
PADIC_MODULE_SCHEMA_V1: Final = "arbogast.padic.module/v1"
PADIC_NEWTON_SEGMENT_SCHEMA_V1: Final = "arbogast.padic.newton-segment/v1"
PADIC_PARTIAL_SCHEMA_V1: Final = "arbogast.padic.partial/v1"
PADIC_PRECISION_RING_SCHEMA_V1: Final = "arbogast.padic.precision-ring/v1"
PADIC_PROJECTIVE_RATIONAL_POINT_SCHEMA_V1: Final = "arbogast.padic.projective-rational-point/v1"
PADIC_PROOF_OBLIGATION_SCHEMA_V1: Final = "arbogast.padic.proof-obligation/v1"
PADIC_RATIONAL_DIFFERENTIAL_SCHEMA_V1: Final = "arbogast.padic.rational-differential/v1"
PADIC_REDUCED_BRANCH_FIBER_SCHEMA_V1: Final = "arbogast.padic.reduced-branch-fiber/v1"
PADIC_REDUCED_FIBER_FACTOR_SCHEMA_V1: Final = "arbogast.padic.reduced-fiber-factor/v1"
PADIC_REDUCED_PROJECTIVE_POINT_SCHEMA_V1: Final = "arbogast.padic.reduced-projective-point/v1"
PADIC_RIEMANN_HURWITZ_WITNESS_SCHEMA_V1: Final = "arbogast.padic.riemann-hurwitz-witness/v1"
PADIC_RIGID_DESCENT_WITNESS_SCHEMA_V1: Final = "arbogast.padic.rigid-descent-witness/v1"
PADIC_RIGID_FIXED_LIFT_SCHEMA_V1: Final = "arbogast.padic.rigid-fixed-lift/v1"
PADIC_SEMISTABLE_REDUCTION_WITNESS_SCHEMA_V1: Final = (
    "arbogast.padic.semistable-reduction-witness/v1"
)
PADIC_SEMISTABLE_REDUCTION_SCHEMA_V1: Final = "arbogast.padic.semistable-reduction/v1"
PADIC_SLOPE_DECOMPOSITION_SCHEMA_V1: Final = "arbogast.padic.slope-decomposition/v1"
PADIC_SLOPE_MULTIPLICITY_SCHEMA_V1: Final = "arbogast.padic.slope-multiplicity/v1"
PADIC_SLOPE_PROJECTOR_SCHEMA_V1: Final = "arbogast.padic.slope-projector/v1"
PADIC_SPECIAL_FIBER_MARKING_SCHEMA_V1: Final = "arbogast.padic.special-fiber-marking/v1"
PADIC_SPECIALITY_WITNESS_SCHEMA_V1: Final = "arbogast.padic.speciality-witness/v1"
PADIC_STABLE_REDUCTION_WITNESS_SCHEMA_V1: Final = "arbogast.padic.stable-reduction-witness/v1"
PADIC_STABLE_REDUCTION_SCHEMA_V1: Final = "arbogast.padic.stable-reduction/v1"
PADIC_SUBMODULE_SCHEMA_V1: Final = "arbogast.padic.submodule/v1"
PADIC_THREE_POINT_COVER_SCHEMA_V1: Final = "arbogast.padic.three-point-cover/v1"
PADIC_UNKNOWN_SCHEMA_V1: Final = "arbogast.padic.unknown/v1"
PADIC_UNSUPPORTED_SCHEMA_V1: Final = "arbogast.padic.unsupported/v1"
PADIC_VALUATION_INTERVAL_SCHEMA_V1: Final = "arbogast.padic.valuation-interval/v1"

PADIC_AUTOMORPHISM_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.automorphism-receipt/v1"
PADIC_DEFORMATION_DATUM_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.deformation-datum-receipt/v1"
PADIC_DESCENDED_MODEL_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.descended-model-receipt/v1"
PADIC_FIELD_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.field-receipt/v1"
PADIC_FINITE_PARTIAL_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.finite-partial-receipt/v1"
PADIC_FINITE_UNKNOWN_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.finite-unknown-receipt/v1"
PADIC_FINITE_UNSUPPORTED_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.finite-unsupported-receipt/v1"
PADIC_FIXED_LIFT_SET_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.fixed-lift-set-receipt/v1"
PADIC_FROBENIUS_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.frobenius-receipt/v1"
PADIC_GOOD_REDUCTION_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.good-reduction-receipt/v1"
PADIC_INERTIA_REPRESENTATION_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.padic.inertia-representation-receipt/v1"
)
PADIC_LIFT_ACTION_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.lift-action-receipt/v1"
PADIC_LIFT_SET_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.lift-set-receipt/v1"
PADIC_LOCAL_FACTORIZATION_FRAGMENT_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.padic.local-factorization-fragment-receipt/v1"
)
PADIC_LOCAL_FIELD_EMBEDDING_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.padic.local-field-embedding-receipt/v1"
)
PADIC_MODULE_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.module-receipt/v1"
PADIC_ORDINARY_PART_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.ordinary-part-receipt/v1"
PADIC_PRECISION_RING_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.precision-ring-receipt/v1"
PADIC_SEMISTABLE_REDUCTION_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.padic.semistable-reduction-receipt/v1"
)
PADIC_SLOPE_DECOMPOSITION_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.slope-decomposition-receipt/v1"
PADIC_STABLE_REDUCTION_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.stable-reduction-receipt/v1"
PADIC_SUBMODULE_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.submodule-receipt/v1"
PADIC_THREE_POINT_PARTIAL_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.three-point-partial-receipt/v1"
PADIC_THREE_POINT_UNKNOWN_RECEIPT_SCHEMA_V1: Final = "arbogast.padic.three-point-unknown-receipt/v1"
PADIC_THREE_POINT_UNSUPPORTED_RECEIPT_SCHEMA_V1: Final = (
    "arbogast.padic.three-point-unsupported-receipt/v1"
)


class SchemaError(ValueError):
    """Raised for an unknown schema or structurally invalid document."""


@dataclass(frozen=True, slots=True)
class SchemaDefinition:
    """A stable schema identifier and its required top-level fields."""

    identifier: str
    required: tuple[str, ...]
    title: str
    marker: str = "schema"

    def document(self) -> dict[str, JSONValue]:
        """Return a small JSON Schema document for external tooling."""

        properties: dict[str, JSONValue] = {
            self.marker: {"const": self.identifier, "type": "string"}
        }
        for key in self.required:
            properties.setdefault(key, {})
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": self.identifier,
            "title": self.title,
            "type": "object",
            "required": [self.marker, *self.required],
            "properties": properties,
            "additionalProperties": True,
        }


_DEFINITIONS: Final = {
    definition.identifier: definition
    for definition in (
        SchemaDefinition(TASK_SCHEMA, ("operation", "input_refs", "parameters", "backend"), "Task"),
        SchemaDefinition(SHARD_SCHEMA, ("task_hash", "key", "payload"), "Shard"),
        SchemaDefinition(PLAN_SCHEMA, ("task", "shards"), "Fleet plan"),
        SchemaDefinition(ARTIFACT_SCHEMA, ("algorithm", "digest", "size"), "Artifact reference"),
        SchemaDefinition(RUN_SCHEMA, ("task", "shards", "result", "state"), "Fleet run"),
        SchemaDefinition(
            OPERATION_DESCRIPTION_SCHEMA,
            (
                "name",
                "inputs",
                "input_bundles",
                "outputs",
                "preconditions",
                "mathematical_guarantees",
            ),
            "Operation description",
        ),
        SchemaDefinition(
            AGENT_MANIFEST_SCHEMA,
            (
                "package",
                "version",
                "scope",
                "purpose",
                "operations",
                "primary_types",
                "invariants",
                "do_not",
                "code_dependencies",
            ),
            "Agent manifest",
        ),
        SchemaDefinition(AGENT_TASK_SCHEMA, ("objective", "expected_output"), "Agent task"),
        SchemaDefinition(
            AGENT_CONTEXT_SCHEMA,
            (
                "manifest",
                "operations",
                "hazards",
                "capability_routes",
                "capability_frontier",
                "code_dependency_graph",
                "tasks",
                "undeclared_code_dependencies",
                "omitted",
            ),
            "Agent context",
        ),
        SchemaDefinition(
            OPERATION_CODE_DEPENDENCIES_SCHEMA,
            (
                "operation",
                "implementation_module",
                "module_dependencies",
                "required_backends",
                "optional_backends",
            ),
            "Declared operation code dependencies",
        ),
        SchemaDefinition(
            CODE_DEPENDENCY_GRAPH_SCHEMA,
            ("nodes", "edges", "content_id"),
            "Declared code dependency graph",
        ),
        SchemaDefinition(ROUTE_SCHEMA, ("source", "target", "steps"), "Capability route"),
        SchemaDefinition(HAZARD_SCHEMA, ("id", "message", "triggered_by"), "Agent hazard"),
        SchemaDefinition(
            BACKEND_STATUS_SCHEMA,
            ("name", "available", "capabilities"),
            "Backend status",
        ),
        SchemaDefinition(CLI_VERSION_SCHEMA, ("version",), "CLI version response"),
        SchemaDefinition(CLI_BACKENDS_SCHEMA, ("backend",), "CLI backend probe response"),
        SchemaDefinition(CLI_DESCRIBE_SCHEMA, ("operation",), "CLI describe response"),
        SchemaDefinition(CLI_VERIFY_SCHEMA, ("valid",), "CLI verification response"),
        SchemaDefinition(CLI_CLAIMS_SCHEMA, ("claims", "count"), "CLI claims response"),
        SchemaDefinition(
            CLI_PROOF_GAP_SCHEMA,
            ("summary", "obligations"),
            "CLI proof-gap response",
        ),
        SchemaDefinition(CLI_ROUTE_SCHEMA, ("route",), "CLI route response"),
        SchemaDefinition(CLI_CAMPAIGN_SCHEMA, ("command", "result"), "CLI campaign response"),
        SchemaDefinition(
            NUMBER_FIELD_SCHEMA,
            (
                "defining_polynomial",
                "integral_basis",
                "irreducibility_requirement",
                "irreducibility_witness",
                "type",
            ),
            "Pinned number field",
        ),
        SchemaDefinition(
            NUMBER_FIELD_ELEMENT_SCHEMA,
            ("coefficients", "field_id", "type"),
            "Pinned number-field element",
        ),
        SchemaDefinition(
            FIELD_EMBEDDING_SCHEMA,
            ("codomain_id", "domain_id", "generator_image", "type"),
            "Explicit number-field embedding",
        ),
        SchemaDefinition(
            IDEAL_SCHEMA,
            ("field_id", "integral_basis", "ideal_hnf", "type"),
            "Canonical nonzero integral ideal",
        ),
        SchemaDefinition(
            FINITE_PLACE_SCHEMA,
            (
                "field_id",
                "ideal_hnf",
                "ramification_index",
                "rational_prime",
                "residue_degree",
                "residue_field_witness",
                "type",
                "verification_requirement",
            ),
            "Canonical finite place",
        ),
        SchemaDefinition(
            INFINITE_PLACE_SCHEMA,
            (
                "embedding_index",
                "field_id",
                "isolation",
                "kind",
                "type",
                "verification_requirement",
            ),
            "Canonical infinite place",
        ),
        SchemaDefinition(
            FINITE_GALOIS_QUOTIENT_RECEIPT_SCHEMA,
            (
                "arithmetic_witness",
                "base_field",
                "base_field_id",
                "group",
                "label",
                "presentation",
                "type",
            ),
            "Finite Galois quotient receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            GALOIS_MODULE_RECEIPT_SCHEMA,
            (
                "module",
                "module_id",
                "quotient",
                "quotient_certificate_id",
                "quotient_id",
                "type",
            ),
            "Galois module receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            KUMMER_RECEIPT_SCHEMA,
            (
                "object_type",
                "field",
                "field_id",
                "prime",
                "places",
                "place_ids",
                "generators",
                "generator_ids",
                "coordinates",
                "proof_context",
                "completeness_witness",
                "proving_certificates",
            ),
            "Kummer receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            LOCAL_H1_RECEIPT_SCHEMA,
            (
                "object_type",
                "place",
                "place_id",
                "prime",
                "basis",
                "basis_ids",
                "coordinates",
                "proof_context",
                "presentation",
                "proving_certificates",
            ),
            "Local H1 receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            LOCALIZATION_RECEIPT_SCHEMA,
            (
                "domain",
                "codomain",
                "matrix",
                "proof_context",
                "localization_witness",
                "proving_certificates",
                "source_coordinates",
                "image_coordinates",
            ),
            "Localization receipt",
            marker="schema_version",
        ),
        SchemaDefinition(
            TWIST_RECEIPT_SCHEMA,
            (
                "acting_elements",
                "acting_table",
                "acting_identity",
                "acting_inverses",
                "coefficient_elements",
                "coefficient_table",
                "coefficient_identity",
                "coefficient_inverses",
                "action_table",
                "cocycles",
                "orbits",
                "representatives",
                "assumptions",
            ),
            "Nonabelian twist receipt",
            marker="schema_version",
        ),
        *(
            SchemaDefinition(
                identifier,
                ("layer", "kind", "payload", "proof_context", "evidence"),
                title,
                marker="schema_version",
            )
            for identifier, title in (
                (AIM_RECEIPT_SCHEMA, "Cocycle aiming receipt"),
                (CARTIER_DUAL_RECEIPT_SCHEMA, "Cartier dual receipt"),
                (DESCENT_RECEIPT_SCHEMA, "Elementary descent receipt"),
                (DUAL_SELMER_RECEIPT_SCHEMA, "Dual Selmer receipt"),
                (LOCAL_CONDITION_RECEIPT_SCHEMA, "Local condition receipt"),
                (LOCAL_PAIRING_RECEIPT_SCHEMA, "Local pairing receipt"),
                (SELMER_RECEIPT_SCHEMA, "Selmer receipt"),
            )
        ),
        SchemaDefinition(
            DEFORM_ARTIN_RING_SCHEMA_V1,
            (
                "basis_names",
                "dimension",
                "field",
                "maximal_ideal_powers",
                "residue",
                "structure_constants",
                "type",
                "unit",
            ),
            "Pinned finite local Artin ring",
        ),
        SchemaDefinition(
            DEFORM_ARTIN_RING_ELEMENT_SCHEMA_V1,
            ("coordinates", "ring_id", "type"),
            "Pinned Artin-ring element",
        ),
        SchemaDefinition(
            DEFORM_ARTIN_RING_MAP_SCHEMA_V1,
            ("codomain_id", "domain_id", "matrix", "type"),
            "Explicit Artin-ring map",
        ),
        SchemaDefinition(
            DEFORM_SMALL_EXTENSION_SCHEMA_V1,
            ("inclusion", "kernel_basis", "projection_id", "type"),
            "Pinned small extension",
        ),
        SchemaDefinition(
            DEFORM_COMPLEX_SCHEMA_V1,
            ("d0", "d1", "dimensions", "field", "name", "type"),
            "Three-term deformation complex",
        ),
        SchemaDefinition(
            DEFORM_PRESENTATION_SCHEMA_V1,
            ("complex", "name", "source_id", "type"),
            "Pinned deformation presentation",
        ),
        SchemaDefinition(
            DEFORM_PROBLEM_SCHEMA_V1,
            ("effective_complex", "framing", "presentation", "type"),
            "Finite deformation problem",
        ),
        SchemaDefinition(
            DEFORM_FRAMING_SCHEMA_V1,
            ("allowed_gauge", "ambient_dimension", "constraints", "label", "type"),
            "Exact deformation framing",
        ),
        SchemaDefinition(
            DEFORM_ACTION_SCHEMA_V1,
            (
                "complex_id",
                "degree_matrices",
                "group_order",
                "identity_index",
                "multiplication_table",
                "type",
            ),
            "Exact finite chain action on a deformation complex",
        ),
        SchemaDefinition(
            DEFORM_EQUIVARIANT_SCHEMA_V1,
            ("action", "problem_id", "type"),
            "Equivariant deformation problem",
        ),
        SchemaDefinition(
            DEFORM_INVARIANT_DEFORMATIONS_SCHEMA_V1,
            ("equivariant_id", "identifies_invariant_cohomology", "problem", "type"),
            "Invariant deformation subcomplex",
        ),
        SchemaDefinition(
            DEFORM_EQUIVARIANT_COMPONENT_SCHEMA_V1,
            ("ambient_id", "complex", "label", "projectors", "subspaces", "type"),
            "Equivariant deformation summand",
        ),
        SchemaDefinition(
            DEFORM_EQUIVARIANT_DECOMPOSITION_SCHEMA_V1,
            ("complete", "components", "equivariant_id", "type"),
            "Complete equivariant deformation decomposition",
        ),
        SchemaDefinition(
            DEFORM_GAUGE_SPACE_SCHEMA_V1,
            ("complex_id", "problem_id", "space", "type"),
            "Infinitesimal gauge space",
        ),
        SchemaDefinition(
            DEFORM_TANGENT_SPACE_SCHEMA_V1,
            ("complex_id", "problem_id", "quotient", "type"),
            "Deformation tangent space",
        ),
        SchemaDefinition(
            DEFORM_OBSTRUCTION_SPACE_SCHEMA_V1,
            ("complex_id", "problem_id", "quotient", "type"),
            "Deformation obstruction space",
        ),
        SchemaDefinition(
            DEFORM_OBSTRUCTION_CLASS_SCHEMA_V1,
            ("ambient_vector", "class_coordinates", "is_zero", "space_id", "type"),
            "Pinned obstruction class",
        ),
        SchemaDefinition(
            DEFORM_LIFT_DATUM_SCHEMA_V1,
            (
                "base_point",
                "correction_matrix",
                "extension_id",
                "gauge_matrix",
                "label",
                "problem_id",
                "target",
                "type",
            ),
            "Finite Artin-ring lift datum",
        ),
        SchemaDefinition(
            DEFORM_LIFT_FAMILY_SCHEMA_V1,
            (
                "datum_id",
                "directions",
                "gauge_directions",
                "mod_gauge",
                "particular",
                "representative",
                "type",
            ),
            "Complete affine lift family",
        ),
        SchemaDefinition(
            DEFORM_LIFT_OBSTRUCTED_SCHEMA_V1,
            ("datum_id", "obstruction_class", "separating_witness", "type"),
            "Obstructed lift result",
        ),
        SchemaDefinition(
            DEFORM_LIFT_UNKNOWN_SCHEMA_V1,
            ("datum_id", "reason", "type"),
            "Unknown lift result",
        ),
        SchemaDefinition(
            DEFORM_UNIQUE_LIFT_SCHEMA_V1,
            ("family_id", "representative", "type"),
            "Unique lift result",
        ),
        SchemaDefinition(
            DEFORM_NONUNIQUE_LIFT_SCHEMA_V1,
            ("family_id", "first", "second", "separating_class_coordinates", "type"),
            "Non-unique lift result",
        ),
        SchemaDefinition(
            DEFORM_LIFT_ENDOMORPHISM_SCHEMA_V1,
            ("family_id", "linear", "translation", "type"),
            "Lift-family endomorphism",
        ),
        SchemaDefinition(
            DEFORM_CONTRACTION_CERTIFICATE_SCHEMA_V1,
            ("endomorphism_id", "exponent", "type"),
            "Finite contraction certificate",
        ),
        SchemaDefinition(
            DEFORM_FIXED_LIFT_SCHEMA_V1,
            ("contraction_id", "endomorphism_id", "family_id", "representative", "type"),
            "Distinguished fixed lift",
        ),
        SchemaDefinition(
            DEFORM_RIGID_SCHEMA_V1,
            ("problem_id", "tangent_id", "type"),
            "Rigid deformation result",
        ),
        SchemaDefinition(
            DEFORM_NONRIGID_SCHEMA_V1,
            ("problem_id", "tangent_id", "type", "witness"),
            "Non-rigid deformation result",
        ),
        SchemaDefinition(
            DEFORM_UNSUPPORTED_SCHEMA_V1,
            ("operation", "reason", "requested", "supported", "type"),
            "Unsupported deformation result",
        ),
        *(
            SchemaDefinition(
                identifier,
                (
                    "assumptions",
                    "completeness",
                    "dependencies",
                    "kind",
                    "layer",
                    "payload",
                    "verifier_trust",
                ),
                title,
                marker="schema_version",
            )
            for identifier, title in (
                (DEFORM_ARTIN_RING_RECEIPT_SCHEMA_V1, "Artin-ring deformation receipt"),
                (DEFORM_ARTIN_MAP_RECEIPT_SCHEMA_V1, "Artin-map deformation receipt"),
                (
                    DEFORM_SMALL_EXTENSION_RECEIPT_SCHEMA_V1,
                    "Small-extension deformation receipt",
                ),
                (DEFORM_COMPLEX_RECEIPT_SCHEMA_V1, "Deformation-complex receipt"),
                (DEFORM_PROBLEM_RECEIPT_SCHEMA_V1, "Deformation-problem receipt"),
                (DEFORM_GAUGE_RECEIPT_SCHEMA_V1, "Gauge-space receipt"),
                (DEFORM_TANGENT_RECEIPT_SCHEMA_V1, "Tangent-space receipt"),
                (
                    DEFORM_OBSTRUCTION_SPACE_RECEIPT_SCHEMA_V1,
                    "Obstruction-space receipt",
                ),
                (
                    DEFORM_OBSTRUCTION_CLASS_RECEIPT_SCHEMA_V1,
                    "Obstruction-class receipt",
                ),
                (DEFORM_FRAMING_RECEIPT_SCHEMA_V1, "Deformation-framing receipt"),
                (DEFORM_ACTION_RECEIPT_SCHEMA_V1, "Deformation-action receipt"),
                (DEFORM_EQUIVARIANT_RECEIPT_SCHEMA_V1, "Equivariant deformation receipt"),
                (
                    DEFORM_INVARIANT_COMPLEX_RECEIPT_SCHEMA_V1,
                    "Invariant-complex deformation receipt",
                ),
                (
                    DEFORM_DECOMPOSITION_RECEIPT_SCHEMA_V1,
                    "Equivariant-decomposition receipt",
                ),
                (DEFORM_LIFT_DATUM_RECEIPT_SCHEMA_V1, "Lift-datum receipt"),
                (DEFORM_LIFT_FAMILY_RECEIPT_SCHEMA_V1, "Lift-family receipt"),
                (DEFORM_LIFT_OBSTRUCTED_RECEIPT_SCHEMA_V1, "Obstructed-lift receipt"),
                (DEFORM_LIFT_UNKNOWN_RECEIPT_SCHEMA_V1, "Unknown-lift receipt"),
                (DEFORM_UNIQUE_LIFT_RECEIPT_SCHEMA_V1, "Unique-lift receipt"),
                (DEFORM_NONUNIQUE_LIFT_RECEIPT_SCHEMA_V1, "Non-unique-lift receipt"),
                (
                    DEFORM_LIFT_ENDOMORPHISM_RECEIPT_SCHEMA_V1,
                    "Lift-endomorphism receipt",
                ),
                (DEFORM_CONTRACTION_RECEIPT_SCHEMA_V1, "Lift-contraction receipt"),
                (DEFORM_FIXED_LIFT_RECEIPT_SCHEMA_V1, "Fixed-lift receipt"),
                (DEFORM_RIGID_RECEIPT_SCHEMA_V1, "Rigid-deformation receipt"),
                (DEFORM_NONRIGID_RECEIPT_SCHEMA_V1, "Non-rigid-deformation receipt"),
                (DEFORM_UNSUPPORTED_RECEIPT_SCHEMA_V1, "Unsupported-deformation receipt"),
            )
        ),
        *(
            SchemaDefinition(identifier, required, title)
            for identifier, required, title in (
                (
                    NUMERIC_DYADIC_SCHEMA_V1,
                    ("exponent", "mantissa", "type"),
                    "Exact dyadic",
                ),
                (
                    NUMERIC_COMPLEX_DYADIC_SCHEMA_V1,
                    ("imag", "real", "type"),
                    "Exact complex dyadic",
                ),
                (
                    NUMERIC_REAL_BALL_SCHEMA_V1,
                    ("center", "radius", "type"),
                    "Closed exact real ball",
                ),
                (
                    NUMERIC_COMPLEX_BALL_SCHEMA_V1,
                    ("center", "radius", "type"),
                    "Closed exact complex ball",
                ),
                (
                    NUMERIC_EXACT_POLYNOMIAL_SCHEMA_V1,
                    ("nvariables", "terms", "type", "variable_names"),
                    "Exact sparse polynomial",
                ),
                (
                    NUMERIC_POLYNOMIAL_SYSTEM_SCHEMA_V1,
                    ("label", "nvariables", "polynomials", "type"),
                    "Exact polynomial system",
                ),
                (
                    NUMERIC_POLYNOMIAL_FAMILY_SCHEMA_V1,
                    ("nvariables", "parameter_name", "polynomials", "type"),
                    "Exact one-parameter polynomial family",
                ),
                (
                    NUMERIC_PARAMETER_PATH_SCHEMA_V1,
                    ("type", "vertices"),
                    "Exact parameter path",
                ),
                (
                    NUMERIC_POINT_SCHEMA_V1,
                    ("coordinates", "system", "type"),
                    "Certified numeric point",
                ),
                (
                    NUMERIC_EXACT_COVER_SCHEMA_V1,
                    (
                        "branch_points",
                        "degree",
                        "discriminant",
                        "family",
                        "infinity_branch",
                        "infinity_convention",
                        "label",
                        "type",
                    ),
                    "Exact bounded cover model",
                ),
                (
                    NUMERIC_CONTINUATION_STEP_SCHEMA_V1,
                    (
                        "contraction_bound",
                        "domain",
                        "family",
                        "inverse_jacobian",
                        "parameter_end",
                        "parameter_start",
                        "residual_bound",
                        "type",
                    ),
                    "Certified continuation step",
                ),
                (
                    NUMERIC_CONTINUATION_TUBE_SCHEMA_V1,
                    ("family", "path", "start_point", "steps", "type"),
                    "Certified continuation tube",
                ),
                (
                    NUMERIC_CONTINUATION_RESULT_SCHEMA_V1,
                    ("endpoint", "tube", "type"),
                    "Certified continuation result",
                ),
                (
                    NUMERIC_CONDITION_BOUND_SCHEMA_V1,
                    (
                        "bound",
                        "inverse_jacobian",
                        "inverse_norm",
                        "jacobian_norm",
                        "point",
                        "system",
                        "type",
                    ),
                    "Certified Jacobian condition bound",
                ),
                (
                    NUMERIC_RECOGNITION_BOUNDS_SCHEMA_V1,
                    ("max_degree", "max_height", "type"),
                    "Exact algebraic-recognition bounds",
                ),
                (
                    NUMERIC_ALGEBRAIC_CANDIDATE_SCHEMA_V1,
                    (
                        "bounds",
                        "isolating_interval",
                        "minimal_polynomial",
                        "source",
                        "type",
                    ),
                    "Bounded algebraic candidate",
                ),
                (
                    NUMERIC_EXACTIFICATION_RESULT_SCHEMA_V1,
                    ("candidate", "point", "type"),
                    "Exactification result",
                ),
                (
                    NUMERIC_REGULAR_FIBER_WITNESS_SCHEMA_V1,
                    ("degree", "factors", "system", "type"),
                    "Complete regular-fiber witness",
                ),
                (
                    NUMERIC_GENERIC_DEGREE_WITNESS_SCHEMA_V1,
                    ("degree", "polynomial", "type"),
                    "Generic polynomial-degree witness",
                ),
                (
                    NUMERIC_REGULAR_FIBER_DEGREE_SCHEMA_V1,
                    ("degree", "generic", "type", "witness"),
                    "Scoped regular-fiber degree",
                ),
                (
                    NUMERIC_DEGREE_RESULT_SCHEMA_V1,
                    ("degree", "generic", "type", "witness"),
                    "Certified generic degree",
                ),
                (
                    NUMERIC_BRANCH_LOOP_SCHEMA_V1,
                    ("branch_index", "model", "path", "type"),
                    "Exact branch loop",
                ),
                (
                    NUMERIC_BRANCH_TRACKING_SCHEMA_V1,
                    ("continuations", "loop", "permutation", "source_points", "type"),
                    "Complete branch tracking",
                ),
                (
                    NUMERIC_NUMERICAL_COVER_SCHEMA_V1,
                    ("base_parameter", "fiber_points", "model", "trackings", "type"),
                    "Certified numerical cover",
                ),
                (
                    NUMERIC_BRANCH_CYCLE_TUPLE_SCHEMA_V1,
                    ("cover", "entries", "type"),
                    "Tracked branch-cycle tuple",
                ),
                (
                    NUMERIC_NIELSEN_VERTEX_SCHEMA_V1,
                    (
                        "base_parameter",
                        "fiber_points",
                        "model",
                        "nielsen",
                        "trackings",
                        "type",
                    ),
                    "Numerical cover bound to a Nielsen vertex",
                ),
                (
                    NUMERIC_BRAID_CONTINUATION_WITNESS_SCHEMA_V1,
                    (
                        "action",
                        "sheet_continuations",
                        "sheet_permutation",
                        "source",
                        "target",
                        "type",
                        "word",
                    ),
                    "Local-sheet braid continuation witness",
                ),
                (
                    NUMERIC_QUADRATIC_B2_HOMOTOPY_SCHEMA_V1,
                    (
                        "action",
                        "branch_paths",
                        "coefficient_homotopy",
                        "collision_sos",
                        "convention",
                        "orientation",
                        "q",
                        "sheet_paths",
                        "sheet_permutation",
                        "source",
                        "target",
                        "type",
                        "word",
                    ),
                    "Exact normalized quadratic B2 homotopy",
                ),
                (
                    NUMERIC_BRAID_CONTINUATION_RESULT_SCHEMA_V1,
                    ("homotopy", "type"),
                    "Exact braid continuation result",
                ),
                (
                    NUMERIC_WEIGHTED_BRAID_PLAN_SCHEMA_V1,
                    (
                        "costs",
                        "distances",
                        "graph",
                        "source",
                        "steps",
                        "target",
                        "total_cost",
                        "type",
                        "word",
                    ),
                    "Exact weighted braid plan",
                ),
                (
                    NUMERIC_UNKNOWN_SCHEMA_V1,
                    ("operation", "reason", "requested", "type"),
                    "Explicit unknown numeric result",
                ),
                (
                    NUMERIC_UNSUPPORTED_SCHEMA_V1,
                    ("operation", "reason", "requested", "supported", "type"),
                    "Unsupported numeric result",
                ),
            )
        ),
        *(
            SchemaDefinition(
                identifier,
                (
                    "assumptions",
                    "completeness",
                    "dependencies",
                    "kind",
                    "layer",
                    "payload",
                    "verifier_trust",
                ),
                title,
                marker="schema_version",
            )
            for identifier, title in (
                (NUMERIC_DYADIC_RECEIPT_SCHEMA_V1, "Exact-dyadic numeric receipt"),
                (
                    NUMERIC_COMPLEX_DYADIC_RECEIPT_SCHEMA_V1,
                    "Complex-dyadic numeric receipt",
                ),
                (NUMERIC_REAL_BALL_RECEIPT_SCHEMA_V1, "Real-ball numeric receipt"),
                (NUMERIC_COMPLEX_BALL_RECEIPT_SCHEMA_V1, "Complex-ball numeric receipt"),
                (
                    NUMERIC_EXACT_POLYNOMIAL_RECEIPT_SCHEMA_V1,
                    "Exact-polynomial numeric receipt",
                ),
                (
                    NUMERIC_POLYNOMIAL_SYSTEM_RECEIPT_SCHEMA_V1,
                    "Polynomial-system numeric receipt",
                ),
                (
                    NUMERIC_POLYNOMIAL_FAMILY_RECEIPT_SCHEMA_V1,
                    "Polynomial-family numeric receipt",
                ),
                (
                    NUMERIC_PARAMETER_PATH_RECEIPT_SCHEMA_V1,
                    "Parameter-path numeric receipt",
                ),
                (NUMERIC_POINT_RECEIPT_SCHEMA_V1, "Numeric-point receipt"),
                (NUMERIC_EXACT_COVER_RECEIPT_SCHEMA_V1, "Exact-cover numeric receipt"),
                (
                    NUMERIC_CONTINUATION_STEP_RECEIPT_SCHEMA_V1,
                    "Continuation-step numeric receipt",
                ),
                (
                    NUMERIC_CONTINUATION_TUBE_RECEIPT_SCHEMA_V1,
                    "Continuation-tube numeric receipt",
                ),
                (
                    NUMERIC_CONTINUATION_RESULT_RECEIPT_SCHEMA_V1,
                    "Continuation-result numeric receipt",
                ),
                (
                    NUMERIC_CONDITION_BOUND_RECEIPT_SCHEMA_V1,
                    "Condition-bound numeric receipt",
                ),
                (
                    NUMERIC_RECOGNITION_BOUNDS_RECEIPT_SCHEMA_V1,
                    "Recognition-bounds numeric receipt",
                ),
                (
                    NUMERIC_ALGEBRAIC_CANDIDATE_RECEIPT_SCHEMA_V1,
                    "Algebraic-candidate numeric receipt",
                ),
                (
                    NUMERIC_EXACTIFICATION_RESULT_RECEIPT_SCHEMA_V1,
                    "Exactification-result numeric receipt",
                ),
                (
                    NUMERIC_REGULAR_FIBER_WITNESS_RECEIPT_SCHEMA_V1,
                    "Regular-fiber-witness numeric receipt",
                ),
                (
                    NUMERIC_GENERIC_DEGREE_WITNESS_RECEIPT_SCHEMA_V1,
                    "Generic-degree-witness numeric receipt",
                ),
                (
                    NUMERIC_REGULAR_FIBER_DEGREE_RECEIPT_SCHEMA_V1,
                    "Regular-fiber-degree numeric receipt",
                ),
                (
                    NUMERIC_DEGREE_RESULT_RECEIPT_SCHEMA_V1,
                    "Generic-degree-result numeric receipt",
                ),
                (NUMERIC_BRANCH_LOOP_RECEIPT_SCHEMA_V1, "Branch-loop numeric receipt"),
                (
                    NUMERIC_BRANCH_TRACKING_RECEIPT_SCHEMA_V1,
                    "Branch-tracking numeric receipt",
                ),
                (
                    NUMERIC_NUMERICAL_COVER_RECEIPT_SCHEMA_V1,
                    "Numerical-cover receipt",
                ),
                (
                    NUMERIC_BRANCH_CYCLE_TUPLE_RECEIPT_SCHEMA_V1,
                    "Branch-cycle-tuple receipt",
                ),
                (
                    NUMERIC_NIELSEN_VERTEX_RECEIPT_SCHEMA_V1,
                    "Nielsen-vertex numeric receipt",
                ),
                (
                    NUMERIC_BRAID_CONTINUATION_WITNESS_RECEIPT_SCHEMA_V1,
                    "Braid-continuation-witness receipt",
                ),
                (
                    NUMERIC_QUADRATIC_B2_HOMOTOPY_RECEIPT_SCHEMA_V1,
                    "Quadratic-B2-homotopy receipt",
                ),
                (
                    NUMERIC_BRAID_CONTINUATION_RESULT_RECEIPT_SCHEMA_V1,
                    "Braid-continuation-result receipt",
                ),
                (
                    NUMERIC_WEIGHTED_BRAID_PLAN_RECEIPT_SCHEMA_V1,
                    "Weighted-braid-plan receipt",
                ),
                (NUMERIC_UNKNOWN_RECEIPT_SCHEMA_V1, "Unknown numeric-result receipt"),
                (
                    NUMERIC_UNSUPPORTED_RECEIPT_SCHEMA_V1,
                    "Unsupported numeric-result receipt",
                ),
            )
        ),
        *(
            SchemaDefinition(identifier, required, title)
            for identifier, required, title in (
                (
                    PADIC_AUTOMORPHISM_SCHEMA_V1,
                    ("basis_images", "inverse_images", "ring_id", "type"),
                    "PAdicAutomorphism",
                ),
                (
                    PADIC_AUTOMORPHISM_TRIVIALITY_WITNESS_SCHEMA_V1,
                    ("automorphisms", "category_scope", "exhaustive", "fixed_lift_id", "type"),
                    "AutomorphismTrivialityWitness",
                ),
                (
                    PADIC_BALL_SCHEMA_V1,
                    ("coordinates", "ring_id", "type", "valuation_lower", "valuation_upper"),
                    "PAdicBall",
                ),
                (
                    PADIC_BRANCH_FIBER_WITNESS_SCHEMA_V1,
                    ("branch", "factors", "scalar", "type"),
                    "BranchFiberWitness",
                ),
                (PADIC_CERTIFIED_SCHEMA_V1, ("receipt", "type", "value"), "Certified"),
                (
                    PADIC_COMPONENT_MAP_WITNESS_SCHEMA_V1,
                    ("degree", "source_component_id", "target_component_id", "type"),
                    "ComponentMapWitness",
                ),
                (
                    PADIC_DEFORMATION_DATUM_SCHEMA_V1,
                    (
                        "character_exponent",
                        "character_values",
                        "component_relation_scope",
                        "completeness_scope",
                        "differential",
                        "differential_signature_relation_claimed",
                        "label",
                        "origin_scope",
                        "signature",
                        "speciality",
                        "tame_order",
                        "type",
                    ),
                    "DeformationDatum",
                ),
                (
                    PADIC_DEFORMATION_DATUM_WITNESS_SCHEMA_V1,
                    (
                        "datum",
                        "differential_extraction_rule",
                        "divisor_residue_data",
                        "group_action",
                        "source_component",
                        "source_reduction_id",
                        "theorem_profile",
                        "type",
                    ),
                    "DeformationDatumWitness",
                ),
                (
                    PADIC_DEFORMATION_SIGNATURE_SCHEMA_V1,
                    ("entries", "type"),
                    "DeformationSignature",
                ),
                (
                    PADIC_DERIVATIVE_WITNESS_SCHEMA_V1,
                    ("derivative", "factors", "scalar", "type"),
                    "DerivativeWitness",
                ),
                (
                    PADIC_DESCENDED_MODEL_SCHEMA_V1,
                    (
                        "automorphisms_trivial",
                        "characteristic_zero_descent_claimed",
                        "cocycle_verified",
                        "coefficients",
                        "coordinate_labels",
                        "descent_scope",
                        "fixed_set",
                        "geometric_cover_descent_claimed",
                        "model_field_scope",
                        "number_field_descent_claimed",
                        "prime",
                        "source_fixed_set_certificate_id",
                        "two_sided_base_change_verified",
                        "type",
                        "witness",
                    ),
                    "DescendedModel",
                ),
                (
                    PADIC_DESCENT_COCYCLE_SCHEMA_V1,
                    (
                        "action_id",
                        "cocycle_convention",
                        "isomorphisms",
                        "quotient_id",
                        "rigid_fixed_lift_id",
                        "type",
                    ),
                    "DescentCocycle",
                ),
                (
                    PADIC_DESCENT_ISOMORPHISM_SCHEMA_V1,
                    (
                        "forward",
                        "inverse",
                        "isomorphism_scope",
                        "quotient_element",
                        "rigid_fixed_lift_id",
                        "type",
                    ),
                    "DescentIsomorphism",
                ),
                (PADIC_ELEMENT_SCHEMA_V1, ("coordinates", "field_id", "type"), "PAdicElement"),
                (PADIC_FIBER_FACTOR_SCHEMA_V1, ("multiplicity", "point", "type"), "FiberFactor"),
                (
                    PADIC_FIELD_SCHEMA_V1,
                    (
                        "defining_polynomial",
                        "integral_basis",
                        "prime",
                        "ramification_index",
                        "residue_degree",
                        "residue_polynomial",
                        "type",
                        "uniformizer",
                        "witness",
                    ),
                    "PAdicField",
                ),
                (PADIC_FIELD_WITNESS_SCHEMA_V1, ("kind", "type"), "PAdicFieldWitness"),
                (
                    PADIC_FINITE_FIELD_FACTOR_SCHEMA_V1,
                    ("coefficients", "degree", "irreducible", "multiplicity", "prime", "type"),
                    "FiniteFieldFactor",
                ),
                (
                    PADIC_FINITE_INERTIA_QUOTIENT_SCHEMA_V1,
                    (
                        "arithmetic_origin_claimed",
                        "group",
                        "place_id",
                        "residue_cardinality",
                        "residue_characteristic",
                        "residue_degree",
                        "source_id",
                        "scope",
                        "type",
                    ),
                    "FiniteInertiaQuotient",
                ),
                (
                    PADIC_FINITE_LIFT_ACTION_SCHEMA_V1,
                    (
                        "action_scope",
                        "arithmetic_galois_action",
                        "group",
                        "lifts",
                        "type",
                        "witnesses",
                    ),
                    "FiniteLiftAction",
                ),
                (
                    PADIC_FIXED_LIFT_SCHEMA_V1,
                    (
                        "action_id",
                        "candidate",
                        "conclusion_scope",
                        "descent_claimed",
                        "lift_index",
                        "type",
                    ),
                    "FixedLift",
                ),
                (
                    PADIC_FIXED_LIFT_SET_SCHEMA_V1,
                    (
                        "action",
                        "action_kind",
                        "completeness_scope",
                        "descent_claimed",
                        "fixed",
                        "source_action_certificate_id",
                        "type",
                    ),
                    "FixedLiftSet",
                ),
                (
                    PADIC_FROBENIUS_OPERATOR_SCHEMA_V1,
                    (
                        "action_convention",
                        "characteristic_polynomial",
                        "coefficient_field",
                        "coefficient_field_id",
                        "convention",
                        "linearized_matrix",
                        "linearized_power",
                        "matrix",
                        "module",
                        "module_id",
                        "precision_ring",
                        "precision_ring_id",
                        "semilinear_period",
                        "sigma_id",
                        "sigma",
                        "sigma_residue_action",
                        "type",
                        "valuation_intervals",
                    ),
                    "FrobeniusOperator",
                ),
                (
                    PADIC_GOOD_REDUCTION_SCHEMA_V1,
                    ("cover_id", "prime", "type", "witness"),
                    "GoodReduction",
                ),
                (
                    PADIC_GOOD_REDUCTION_WITNESS_SCHEMA_V1,
                    (
                        "cover",
                        "degree_preserved",
                        "marked_source_points",
                        "prime",
                        "ramification_points",
                        "reduced_derivative",
                        "reduced_derivative_factors",
                        "reduced_fibers",
                        "reduced_polynomial",
                        "tame",
                        "type",
                    ),
                    "GoodReductionWitness",
                ),
                (
                    PADIC_INERTIA_FILTRATION_SCHEMA_V1,
                    (
                        "arithmetic_lower_numbering_claimed",
                        "level_element_indices",
                        "numbering",
                        "quotient_id",
                        "scope",
                        "tame_quotient_order",
                        "type",
                        "wild_residue_characteristic",
                    ),
                    "InertiaFiltration",
                ),
                (
                    PADIC_INERTIA_REPRESENTATION_SCHEMA_V1,
                    (
                        "action_convention",
                        "action_matrices",
                        "coefficient_field",
                        "filtration",
                        "filtration_id",
                        "frobenius_operator",
                        "frobenius_relation",
                        "module",
                        "module_id",
                        "precision_ring",
                        "quotient",
                        "quotient_id",
                        "scope",
                        "type",
                    ),
                    "InertiaRepresentation",
                ),
                (
                    PADIC_LIFT_CANDIDATE_SCHEMA_V1,
                    (
                        "chart_id",
                        "coordinate_labels",
                        "isomorphism_key",
                        "model_coefficients",
                        "model_scope",
                        "parameter",
                        "type",
                    ),
                    "LiftCandidate",
                ),
                (
                    PADIC_LIFT_CHART_SCHEMA_V1,
                    (
                        "completeness_scope",
                        "coordinate_labels",
                        "datum",
                        "equation_coefficients",
                        "label",
                        "model_coordinate_polynomials",
                        "model_scope",
                        "type",
                    ),
                    "LiftChart",
                ),
                (
                    PADIC_LIFT_ENUMERATION_WITNESS_SCHEMA_V1,
                    (
                        "candidates",
                        "chart_id",
                        "completeness_scope",
                        "exhausted_parameters",
                        "type",
                    ),
                    "LiftEnumerationWitness",
                ),
                (
                    PADIC_LIFT_GALOIS_ACTION_SCHEMA_V1,
                    (
                        "action_scope",
                        "arithmetic_galois_action",
                        "characteristic_zero_lift_action_claimed",
                        "coefficient_action_rule",
                        "finite_action",
                        "geometric_lift_action_claimed",
                        "lift_set_certificate_id",
                        "quotient_id",
                        "quotient_presentation_certificate_id",
                        "quotient_proving_certificate_id",
                        "quotient_snapshot",
                        "type",
                    ),
                    "LiftGaloisAction",
                ),
                (
                    PADIC_LIFT_SET_SCHEMA_V1,
                    (
                        "candidates",
                        "chart",
                        "class_indices",
                        "completeness_scope",
                        "datum_id",
                        "deduplication_scope",
                        "representatives",
                        "source_datum_certificate_id",
                        "type",
                        "witness",
                    ),
                    "LiftSet",
                ),
                (
                    PADIC_LIFT_TRANSPORT_WITNESS_SCHEMA_V1,
                    (
                        "arithmetic_compatible",
                        "group_element",
                        "lift_permutation",
                        "lift_set_id",
                        "model_coordinate_permutations",
                        "model_transport_verified",
                        "transport_labels",
                        "transport_scope",
                        "type",
                    ),
                    "LiftTransportWitness",
                ),
                (
                    PADIC_LOCAL_FACTORIZATION_FRAGMENT_SCHEMA_V1,
                    (
                        "factor_degrees",
                        "factorization_complete",
                        "factors",
                        "polynomial",
                        "prime",
                        "ramification_indices",
                        "scope",
                        "source_id",
                        "type",
                        "unit",
                    ),
                    "LocalFactorizationFragment",
                ),
                (
                    PADIC_LOCAL_FIELD_EMBEDDING_SCHEMA_V1,
                    ("codomain_id", "domain_id", "generator_image", "type"),
                    "LocalFieldEmbedding",
                ),
                (
                    PADIC_MARKED_REDUCTION_COMPONENT_SCHEMA_V1,
                    (
                        "component_id",
                        "genus",
                        "incident_nodes",
                        "markings",
                        "role",
                        "smooth",
                        "stability_index",
                        "type",
                    ),
                    "MarkedReductionComponent",
                ),
                (
                    PADIC_MATRIX_SCHEMA_V1,
                    ("base_id", "base_kind", "column_action", "entries", "shape", "type"),
                    "PAdicMatrix",
                ),
                (
                    PADIC_MODULE_SCHEMA_V1,
                    ("basis_labels", "coordinate_convention", "rank", "ring_id", "type"),
                    "PAdicModule",
                ),
                (
                    PADIC_NEWTON_SEGMENT_SCHEMA_V1,
                    (
                        "frobenius_slope",
                        "geometric_slope",
                        "left_index",
                        "left_valuation",
                        "multiplicity",
                        "normalization",
                        "right_index",
                        "right_valuation",
                        "semilinear_period",
                        "type",
                    ),
                    "NewtonSegment",
                ),
                (
                    PADIC_PARTIAL_SCHEMA_V1,
                    ("fragments", "obligations", "operation", "reason", "receipt", "type"),
                    "Partial",
                ),
                (
                    PADIC_PRECISION_RING_SCHEMA_V1,
                    (
                        "cardinality",
                        "field_id",
                        "modulus_hnf",
                        "precision",
                        "type",
                        "uniformizer_power_convention",
                    ),
                    "PAdicPrecisionRing",
                ),
                (
                    PADIC_PROJECTIVE_RATIONAL_POINT_SCHEMA_V1,
                    ("denominator", "numerator", "type"),
                    "ProjectiveRationalPoint",
                ),
                (
                    PADIC_PROOF_OBLIGATION_SCHEMA_V1,
                    (
                        "blocked_result_kind",
                        "input_ids",
                        "obligation_id",
                        "required_witness_kind",
                        "statement",
                        "type",
                    ),
                    "ProofObligation",
                ),
                (
                    PADIC_RATIONAL_DIFFERENTIAL_SCHEMA_V1,
                    (
                        "cartier_relation",
                        "denominator",
                        "differential_kind",
                        "logarithmic_unit",
                        "numerator",
                        "prime",
                        "type",
                    ),
                    "RationalDifferential",
                ),
                (
                    PADIC_REDUCED_BRANCH_FIBER_SCHEMA_V1,
                    ("branch", "factors", "prime", "scalar", "type"),
                    "ReducedBranchFiber",
                ),
                (
                    PADIC_REDUCED_FIBER_FACTOR_SCHEMA_V1,
                    ("linear_coefficient", "multiplicity", "point", "type"),
                    "ReducedFiberFactor",
                ),
                (
                    PADIC_REDUCED_PROJECTIVE_POINT_SCHEMA_V1,
                    ("prime", "residue", "type"),
                    "ReducedProjectivePoint",
                ),
                (
                    PADIC_RIEMANN_HURWITZ_WITNESS_SCHEMA_V1,
                    ("degree", "expected_ramification", "profiles", "ramification_sum", "type"),
                    "RiemannHurwitzWitness",
                ),
                (
                    PADIC_RIGID_DESCENT_WITNESS_SCHEMA_V1,
                    (
                        "base_change_forward",
                        "base_change_inverse",
                        "cocycle",
                        "descended_model_coefficients",
                        "descent_scope",
                        "fixed_set_id",
                        "rigid",
                        "type",
                    ),
                    "RigidDescentWitness",
                ),
                (
                    PADIC_RIGID_FIXED_LIFT_SCHEMA_V1,
                    ("fixed", "rigidity_scope", "triviality", "type"),
                    "RigidFixedLift",
                ),
                (
                    PADIC_SEMISTABLE_REDUCTION_SCHEMA_V1,
                    ("cover_id", "prime", "type", "witness"),
                    "SemistableReduction",
                ),
                (
                    PADIC_SEMISTABLE_REDUCTION_WITNESS_SCHEMA_V1,
                    (
                        "complete",
                        "component_maps",
                        "good_reduction",
                        "nodes",
                        "source_components",
                        "target_components",
                        "type",
                    ),
                    "SemistableReductionWitness",
                ),
                (
                    PADIC_SLOPE_DECOMPOSITION_SCHEMA_V1,
                    (
                        "intervals",
                        "multiplicities",
                        "operator_id",
                        "operator",
                        "polygon_complete",
                        "projectors",
                        "projectors_complete",
                        "segments",
                        "type",
                    ),
                    "SlopeDecomposition",
                ),
                (
                    PADIC_SLOPE_MULTIPLICITY_SCHEMA_V1,
                    ("multiplicity", "slope", "type"),
                    "SlopeMultiplicity",
                ),
                (
                    PADIC_SLOPE_PROJECTOR_SCHEMA_V1,
                    (
                        "basis_change",
                        "basis_change_inverse",
                        "operator_id",
                        "operator",
                        "projector",
                        "rank",
                        "slope",
                        "submodule",
                        "type",
                    ),
                    "SlopeProjector",
                ),
                (
                    PADIC_SPECIALITY_WITNESS_SCHEMA_V1,
                    (
                        "normalized_labels",
                        "primitive_labels",
                        "profile",
                        "signature",
                        "type",
                        "wild_labels",
                    ),
                    "SpecialityWitness",
                ),
                (
                    PADIC_SPECIAL_FIBER_MARKING_SCHEMA_V1,
                    ("branch", "label", "point", "ramification_index", "type"),
                    "SpecialFiberMarking",
                ),
                (
                    PADIC_STABLE_REDUCTION_SCHEMA_V1,
                    ("cover_id", "prime", "semistable_reduction_id", "type", "witness"),
                    "StableReduction",
                ),
                (
                    PADIC_STABLE_REDUCTION_WITNESS_SCHEMA_V1,
                    (
                        "complete",
                        "contracted_components",
                        "semistable_reduction",
                        "source_stability_indices",
                        "target_stability_indices",
                        "type",
                    ),
                    "StableReductionWitness",
                ),
                (
                    PADIC_SUBMODULE_SCHEMA_V1,
                    ("ambient_id", "cardinality", "preimage_hnf", "type"),
                    "PAdicSubmodule",
                ),
                (
                    PADIC_THREE_POINT_COVER_SCHEMA_V1,
                    (
                        "degree",
                        "derivative_witness",
                        "fibers",
                        "generic_degree_witness",
                        "label",
                        "polynomial",
                        "riemann_hurwitz_witness",
                        "type",
                    ),
                    "ThreePointCover",
                ),
                (
                    PADIC_UNKNOWN_SCHEMA_V1,
                    ("operation", "reason", "reason_code", "receipt", "requested", "type"),
                    "Unknown",
                ),
                (
                    PADIC_UNSUPPORTED_SCHEMA_V1,
                    (
                        "operation",
                        "reason",
                        "reason_code",
                        "receipt",
                        "requested",
                        "supported",
                        "type",
                    ),
                    "Unsupported",
                ),
                (
                    PADIC_VALUATION_INTERVAL_SCHEMA_V1,
                    ("lower", "normalization", "type", "upper"),
                    "ValuationInterval",
                ),
            )
        ),
        *(
            SchemaDefinition(
                identifier,
                (
                    "closure",
                    "evidence",
                    "kind",
                    "layer",
                    "payload",
                    "proof_context",
                    "verifier",
                ),
                title,
                marker="schema_version",
            )
            for identifier, title in (
                (PADIC_AUTOMORPHISM_RECEIPT_SCHEMA_V1, "automorphism p-adic receipt"),
                (PADIC_DEFORMATION_DATUM_RECEIPT_SCHEMA_V1, "deformation-datum p-adic receipt"),
                (PADIC_DESCENDED_MODEL_RECEIPT_SCHEMA_V1, "descended-model p-adic receipt"),
                (PADIC_FIELD_RECEIPT_SCHEMA_V1, "field p-adic receipt"),
                (PADIC_FINITE_PARTIAL_RECEIPT_SCHEMA_V1, "finite-partial p-adic receipt"),
                (PADIC_FINITE_UNKNOWN_RECEIPT_SCHEMA_V1, "finite-unknown p-adic receipt"),
                (PADIC_FINITE_UNSUPPORTED_RECEIPT_SCHEMA_V1, "finite-unsupported p-adic receipt"),
                (PADIC_FIXED_LIFT_SET_RECEIPT_SCHEMA_V1, "fixed-lift-set p-adic receipt"),
                (PADIC_FROBENIUS_RECEIPT_SCHEMA_V1, "frobenius p-adic receipt"),
                (PADIC_GOOD_REDUCTION_RECEIPT_SCHEMA_V1, "good-reduction p-adic receipt"),
                (
                    PADIC_INERTIA_REPRESENTATION_RECEIPT_SCHEMA_V1,
                    "inertia-representation p-adic receipt",
                ),
                (PADIC_LIFT_ACTION_RECEIPT_SCHEMA_V1, "lift-action p-adic receipt"),
                (PADIC_LIFT_SET_RECEIPT_SCHEMA_V1, "lift-set p-adic receipt"),
                (
                    PADIC_LOCAL_FACTORIZATION_FRAGMENT_RECEIPT_SCHEMA_V1,
                    "local-factorization-fragment p-adic receipt",
                ),
                (
                    PADIC_LOCAL_FIELD_EMBEDDING_RECEIPT_SCHEMA_V1,
                    "local-field-embedding p-adic receipt",
                ),
                (PADIC_MODULE_RECEIPT_SCHEMA_V1, "module p-adic receipt"),
                (PADIC_ORDINARY_PART_RECEIPT_SCHEMA_V1, "ordinary-part p-adic receipt"),
                (PADIC_PRECISION_RING_RECEIPT_SCHEMA_V1, "precision-ring p-adic receipt"),
                (
                    PADIC_SEMISTABLE_REDUCTION_RECEIPT_SCHEMA_V1,
                    "semistable-reduction p-adic receipt",
                ),
                (PADIC_SLOPE_DECOMPOSITION_RECEIPT_SCHEMA_V1, "slope-decomposition p-adic receipt"),
                (PADIC_STABLE_REDUCTION_RECEIPT_SCHEMA_V1, "stable-reduction p-adic receipt"),
                (PADIC_SUBMODULE_RECEIPT_SCHEMA_V1, "submodule p-adic receipt"),
                (PADIC_THREE_POINT_PARTIAL_RECEIPT_SCHEMA_V1, "three-point-partial p-adic receipt"),
                (PADIC_THREE_POINT_UNKNOWN_RECEIPT_SCHEMA_V1, "three-point-unknown p-adic receipt"),
                (
                    PADIC_THREE_POINT_UNSUPPORTED_RECEIPT_SCHEMA_V1,
                    "three-point-unsupported p-adic receipt",
                ),
            )
        ),
    )
}


def schema_ids() -> tuple[str, ...]:
    """Return all supported schema identifiers in stable order."""

    return tuple(sorted(_DEFINITIONS))


def schema_document(identifier: str) -> dict[str, JSONValue]:
    """Return a copy of the JSON Schema document for ``identifier``."""

    try:
        document = _DEFINITIONS[identifier].document()
    except KeyError as error:
        raise SchemaError(f"unknown schema: {identifier}") from error
    return deepcopy(document)


def validate_document(
    document: Mapping[str, Any], expected: str | None = None
) -> dict[str, JSONValue]:
    """Validate a document's version marker and required top-level fields.

    This intentionally provides structural boundary validation rather than a
    partial reimplementation of a JSON Schema engine.
    """

    normalized = normalize_json(document)
    if not isinstance(normalized, dict):
        raise SchemaError("schema document must be a JSON object")
    schema_marker = normalized.get("schema")
    version_marker = normalized.get("schema_version")
    if schema_marker is not None and version_marker is not None:
        raise SchemaError("document cannot carry both 'schema' and 'schema_version'")
    identifier = schema_marker if schema_marker is not None else version_marker
    if not isinstance(identifier, str):
        raise SchemaError("document has no string 'schema' identifier")
    if expected is not None and identifier != expected:
        raise SchemaError(f"expected schema {expected!r}, got {identifier!r}")
    try:
        definition = _DEFINITIONS[identifier]
    except KeyError as error:
        raise SchemaError(f"unknown schema: {identifier}") from error
    if definition.marker not in normalized:
        raise SchemaError(
            f"document {identifier!r} must use the {definition.marker!r} version marker"
        )
    missing = tuple(key for key in definition.required if key not in normalized)
    if missing:
        names = ", ".join(missing)
        raise SchemaError(f"document {identifier!r} is missing required fields: {names}")
    return normalized
