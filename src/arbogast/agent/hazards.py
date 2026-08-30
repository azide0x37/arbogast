"""Machine-readable mathematical and implementation hazards."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from arbogast.formats import HAZARD_SCHEMA, JSONValue


class HazardSeverity(StrEnum):
    INFORMATION = "information"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Hazard:
    """A regression lesson attached to relevant operations or types."""

    id: str
    message: str
    triggered_by: tuple[str, ...]
    severity: HazardSeverity = HazardSeverity.WARNING
    remediation: str | None = None
    schema: str = HAZARD_SCHEMA

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or not isinstance(self.message, str)
            or not self.message.strip()
        ):
            raise ValueError("hazard id and message must not be empty")
        triggers = tuple(self.triggered_by)
        if not triggers or any(
            not isinstance(trigger, str) or not trigger.strip() for trigger in triggers
        ):
            raise ValueError("hazards require at least one non-empty trigger")
        if not isinstance(self.severity, HazardSeverity):
            raise ValueError("hazard severity is invalid")
        if self.remediation is not None and not isinstance(self.remediation, str):
            raise ValueError("hazard remediation must be a string or null")
        if self.schema != HAZARD_SCHEMA:
            raise ValueError("unsupported hazard schema")
        object.__setattr__(self, "triggered_by", tuple(sorted(set(triggers))))

    def relevant_to(self, values: Iterable[str]) -> bool:
        candidates = {
            alternative.strip()
            for value in values
            for alternative in value.split("|")
            if alternative.strip()
        }
        return bool(candidates.intersection(self.triggered_by))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "id": self.id,
            "message": self.message,
            "remediation": self.remediation,
            "schema": self.schema,
            "severity": self.severity.value,
            "triggered_by": list(self.triggered_by),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Hazard:
        expected = {"id", "message", "remediation", "schema", "severity", "triggered_by"}
        if set(value) != expected:
            raise ValueError("hazard has missing or unknown fields")
        if value["schema"] != HAZARD_SCHEMA:
            raise ValueError("unsupported hazard schema")
        hazard_id = value["id"]
        message = value["message"]
        remediation = value["remediation"]
        triggers = value["triggered_by"]
        if not isinstance(hazard_id, str) or not isinstance(message, str):
            raise ValueError("hazard id and message must be strings")
        if remediation is not None and not isinstance(remediation, str):
            raise ValueError("hazard remediation must be a string or null")
        if not isinstance(triggers, list) or any(not isinstance(item, str) for item in triggers):
            raise ValueError("hazard triggered_by must be an array of strings")
        try:
            severity = HazardSeverity(value["severity"])
        except (TypeError, ValueError) as error:
            raise ValueError("hazard severity is invalid") from error
        return cls(hazard_id, message, tuple(triggers), severity, remediation)


class HazardRegistry:
    def __init__(self, hazards: Iterable[Hazard] = ()) -> None:
        self._hazards: dict[str, Hazard] = {}
        for hazard in hazards:
            self.register(hazard)

    def register(self, hazard: Hazard, *, replace: bool = False) -> None:
        if hazard.id in self._hazards and not replace:
            raise ValueError(f"hazard {hazard.id!r} is already registered")
        self._hazards[hazard.id] = hazard

    def all(self) -> tuple[Hazard, ...]:
        return tuple(self._hazards[key] for key in sorted(self._hazards))

    def get(self, hazard_id: str) -> Hazard:
        try:
            return self._hazards[hazard_id]
        except KeyError as error:
            raise LookupError(f"unknown hazard: {hazard_id}") from error

    def resolve(self, hazard_ids: Iterable[str]) -> tuple[Hazard, ...]:
        return tuple(self.get(hazard_id) for hazard_id in sorted(set(hazard_ids)))

    def relevant(
        self,
        values: Iterable[str],
        *,
        declared_ids: Iterable[str] = (),
    ) -> tuple[Hazard, ...]:
        materialized = tuple(values)
        selected = {hazard.id: hazard for hazard in self.all() if hazard.relevant_to(materialized)}
        for hazard in self.resolve(declared_ids):
            selected[hazard.id] = hazard
        return tuple(selected[key] for key in sorted(selected))


DEFAULT_HAZARDS = HazardRegistry(
    (
        Hazard(
            id="hurwitz.source-vs-parameter-genus",
            triggered_by=("hurwitz.source_genus", "hurwitz.hurwitz_genus"),
            message="Source genus and Hurwitz-parameter genus are different invariants.",
            remediation="Compute and name each genus separately.",
        ),
        Hazard(
            id="groups.concrete-vs-abstract-embedding",
            triggered_by=(
                "CanonicalGroupElement",
                "ConcreteGroupElement",
                "NielsenClass",
                "hurwitz.nielsen_class",
            ),
            message="Canonical ambient conjugates need not lie in a pinned concrete embedding.",
            remediation="Use an explicit transport map and preserve its provenance.",
        ),
        Hazard(
            id="arithmetic.moduli-vs-definition",
            triggered_by=("field_of_moduli", "field_of_definition"),
            message="A field of moduli is not automatically a field of definition.",
            remediation="Require and verify effective descent data.",
        ),
        Hazard(
            id="numeric.real-input-vs-real-model",
            triggered_by=("numeric.exactify", "hurwitz.real_points"),
            message="Real branch coordinates do not imply real normalized coefficients.",
            remediation="Verify the real structure on the exactified model.",
        ),
        Hazard(
            id="cohom.full-shift-quotient-descent",
            triggered_by=("QuotientModule", "cohom.h0", "cohom.h1", "cohom.h2"),
            message="A full-shift quotient need not descend through the intended action.",
            remediation="Verify the quotient action and descent maps explicitly.",
        ),
        Hazard(
            id="cohom.induced-map-needs-explicit-group-map",
            triggered_by=(
                "cohom.inflate",
                "cohom.inflation_map",
                "cohom.restrict",
                "cohom.restriction_map",
            ),
            message=(
                "An abstract subgroup or quotient identification does not define a certified "
                "cohomology transport."
            ),
            remediation=(
                "Supply and replay the explicit injective or surjective finite group map."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="cohom.transfer-needs-complete-transversal",
            triggered_by=("cohom.corestrict", "cohom.corestriction_map"),
            message="Corestriction is not certified by a partial or unbound coset transversal.",
            remediation=(
                "Bind a complete transversal and replay every transfer summand and "
                "representative-independence check."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="cohom.five-term-dimensions-vs-exactness",
            triggered_by=("cohom.inflation_restriction", "cohom.transgression"),
            message=(
                "Compatible dimensions and zero composites do not by themselves prove exactness."
            ),
            remediation="Independently recompute image equals kernel at every interior term.",
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="backends.gap-reserved-identifier",
            triggered_by=("GAP", "gap"),
            message="EI is a reserved identifier in GAP and cannot be used as a local name.",
            remediation="Generate backend-safe identifiers instead of forwarding Python names.",
        ),
        Hazard(
            id="arithmetic.class-rationality-vs-component-field",
            triggered_by=("ComponentField", "RationalityField", "hurwitz.components"),
            message="A class rationality field does not determine the component field.",
            remediation="Compute component descent and Galois action separately.",
        ),
        Hazard(
            id="hurwitz.orbit-length-vs-order",
            triggered_by=("BraidAction", "hurwitz.braid_action", "hurwitz.components"),
            message="An orbit length does not by itself determine an acting element's order.",
            remediation="Verify the permutation action and element order explicitly.",
        ),
        Hazard(
            id="arithmetic.finite-s-kummer-vs-unrestricted-squareclasses",
            triggered_by=("KummerSpace", "galois.kummer_space"),
            message="K^*/K^{*2} is not represented by an unrestricted finite vector space.",
            remediation=(
                "Declare the complete place set S and bind S-units, class-group 2-torsion, "
                "and principalization witnesses."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.local-h1-vs-decomposition-quotient",
            triggered_by=(
                "LocalH1Space",
                "decomposition_quotient_h1",
                "galois.decomposition_quotient_h1",
                "galois.local_h1",
            ),
            message="Finite H^1(D_v,M) is not silently continuous H^1(K_v,mu_p).",
            remediation="Name and certify the two constructions through separate operations.",
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.candidate-kernel-vs-selmer-group",
            triggered_by=("SelmerGroup", "SelmerKernel", "arithmetic.selmer"),
            message="A candidate global-to-local kernel is not a complete Selmer group.",
            remediation=(
                "Promote only after proving completeness of the Kummer space, every local "
                "space and condition, and the complete relevant place set."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.assumptions-trust-completeness-axes",
            triggered_by=(
                "Completeness",
                "ProofContext",
                "SelmerProblem",
                "galois.kummer_space",
                "arithmetic.selmer",
            ),
            message="Assumptions, verifier portability, and completeness are independent axes.",
            remediation=(
                "Record each axis explicitly; PARI certification can remove GRH without "
                "making the witness portable."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.pairing-before-dual-selmer",
            triggered_by=(
                "CartierDual",
                "LocalPairing",
                "arithmetic.cartier_dual",
                "arithmetic.dual_selmer",
                "arithmetic.local_pairing",
            ),
            message="Orthogonal local conditions require a certified nondegenerate local pairing.",
            remediation="Replay pairing dimensions and nondegeneracy before forming orthogonals.",
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.local-vs-global-solubility",
            triggered_by=(
                "KummerDescentProblem",
                "arithmetic.elementary_descent",
                "local_solubility",
            ),
            message="Locally unobstructed does not imply globally soluble.",
            remediation=(
                "Return Realized only with a checked global witness and Obstructed only with "
                "a replayable global obstruction; otherwise return Unknown."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="arithmetic.failed-search-vs-obstruction",
            triggered_by=(
                "arithmetic.aim",
                "arithmetic.elementary_descent",
                "arithmetic.unique",
            ),
            message="Failed search, timeout, and budget exhaustion are not obstruction proofs.",
            remediation="Require a literal left-nullspace or descent obstruction witness.",
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="galois.nonabelian-pointed-set-vs-vector-space",
            triggered_by=(
                "TwistClassSet",
                "galois.nonabelian_h1",
                "galois.twist_classes",
            ),
            message="Nonabelian H^1 is a pointed set of cocycle orbits, not a vector space.",
            remediation="Expose the basepoint and orbit witnesses without linear operations.",
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="galois.complete-quotient-needs-arithmetic-proof",
            triggered_by=(
                "FiniteGaloisQuotient",
                "galois.finite_galois_quotient_certificate",
                "galois.galois_module",
            ),
            message=(
                "A COMPLETE proof-context flag does not prove a nontrivial absolute-Galois "
                "quotient realization."
            ),
            remediation=(
                "Attach and replay a certificate bound to the exact base field, concrete "
                "group, label, and arithmetic presentation."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="backends.pari-handle-vs-canonical-identity",
            triggered_by=("NumberField", "PARI", "pari"),
            message=(
                "PARI handles, session indices, and printed p-adics are not canonical identities."
            ),
            remediation=(
                "Bind defining polynomials, bases, embedding images, ideal HNF data, and exact "
                "place presentations at the adapter boundary."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.finite-complex-vs-geometric-presentation",
            triggered_by=("DeformationComplex", "deform.deformation_problem"),
            message=(
                "A supplied finite three-term complex is not an automatically constructed "
                "geometric cotangent or deformation complex."
            ),
            remediation=(
                "Pin the source and presentation explicitly; treat automatic geometric "
                "presentation outside the bounded finite-exact slice as unsupported."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.obstruction-space-vs-lift-existence",
            triggered_by=(
                "ObstructionSpace",
                "deform.lift",
                "deform.obstructions",
            ),
            message="A zero obstruction space does not itself construct a deformation lift.",
            remediation=(
                "Return a lift only from a checked correction solution; return obstruction "
                "only with a literal separating witness."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.invariant-complex-vs-invariant-cohomology",
            triggered_by=(
                "InvariantDeformations",
                "deform.equivariant_decomposition",
                "deform.invariant_deformations",
            ),
            message="The cohomology of C^G is not silently the invariant part of H(C).",
            remediation=(
                "Keep the invariant subcomplex claim separate and require additional exact "
                "hypotheses before identifying invariant cohomology."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.modular-action-vs-projector-decomposition",
            triggered_by=(
                "DeformationAction",
                "EquivariantDecomposition",
                "deform.equivariant_decomposition",
            ),
            message="A finite action does not imply a semisimple projector decomposition.",
            remediation=(
                "Supply and replay complete orthogonal chain projectors; otherwise return the "
                "typed unsupported result."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.tangent-zero-vs-unscoped-rigidity",
            triggered_by=("Rigid", "deform.rigid"),
            message=(
                "Zero tangent dimension proves only the declared finite infinitesimal rigidity "
                "criterion."
            ),
            remediation=(
                "Retain the pinned problem scope and do not promote to formal, algebraic, or "
                "geometric rigidity without additional theorems."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="deform.unique-lift-vs-canonical-fixed-lift",
            triggered_by=(
                "FixedLift",
                "UniqueLift",
                "deform.fixed_lift",
                "deform.unique_lift",
            ),
            message="Uniqueness modulo gauge does not supply a canonical fixed lift.",
            remediation=(
                "Bind an affine lift endomorphism and replay a contraction certificate before "
                "naming a distinguished fixed lift."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.approximation-vs-exact-value",
            triggered_by=(
                "ComplexBall",
                "RealBall",
                "numeric.condition_number",
                "numeric.recognize",
            ),
            message="A certified enclosure is validated numerical evidence, not an exact value.",
            remediation=(
                "Retain NUMERICAL status until a separate exactification witness replays exact "
                "polynomial identities."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.continuation-vs-exact-braid-action",
            triggered_by=(
                "BraidContinuationResult",
                "ContinuationResult",
                "NumericalCover",
                "QuadraticB2Homotopy",
                "numeric.braid_continue",
                "numeric.continue_path",
            ),
            message=(
                "A validated numerical continuation endpoint is not by itself an exact braid "
                "target."
            ),
            remediation=(
                "Keep a bare endpoint numerical. Promote only the exact normalized quadratic "
                "B2 generator or inverse with its QuadraticB2Homotopy; local sheet loops are "
                "not a cover-coefficient homotopy."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.incomplete-tracking-vs-exact-branch-cycles",
            triggered_by=(
                "BranchCycleTuple",
                "NielsenVertex",
                "numeric.bind_vertex",
                "numeric.branch_cycles",
            ),
            message=(
                "Raw or incomplete numerical tracking does not justify an exact discrete branch "
                "cycle tuple or Nielsen vertex."
            ),
            remediation=(
                "Require complete separated continuation for every sheet and finite branch, the "
                "exact infinity product convention, one generating product-one tuple, and a "
                "literal computed-complete class match before exact promotion."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.recognition-candidate-vs-exactification",
            triggered_by=(
                "AlgebraicCandidate",
                "numeric.exactify",
                "numeric.recognize",
            ),
            message="An algebraic relation compatible with a ball is only a recognition candidate.",
            remediation=(
                "Call exactify with the pinned exact system and replay substitution before "
                "emitting an exact claim."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.real-branch-points-vs-real-model",
            triggered_by=("ExactCover", "NumericalCover", "numeric.branch_cycles"),
            message="Numerically real branch coordinates do not prove a real normalized model.",
            remediation=(
                "Bind exact coefficients, normalization, and a real-structure witness before "
                "claiming descent to the reals."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.label-permutation-vs-model-identity",
            triggered_by=("NielsenVertex", "NumericalCover", "numeric.bind_vertex"),
            message="Relabelling ordered numerical sheets or branches changes the model binding.",
            remediation=(
                "Preserve branch and sheet order and replay the explicit permutation witness "
                "against the exact Nielsen vertex."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.precision-increase-vs-proof",
            triggered_by=("NumericUnknown", "RecognitionBounds", "numeric.recognize"),
            message="Increasing precision is not itself a proof rule.",
            remediation=(
                "Use additional precision only to construct a new explicit witness; replay that "
                "witness before strengthening the claim status."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.regular-fiber-vs-generic-degree",
            triggered_by=(
                "DegreeResult",
                "RegularFiberDegree",
                "numeric.projection_degree",
            ),
            message="The cardinality of one supplied regular fiber is not a generic-degree proof.",
            remediation=(
                "Report the scoped regular-fiber count unless an exact generic witness proves "
                "nondegeneracy and completeness on a generic locus."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="numeric.weight-vs-mathematical-shortest-path",
            triggered_by=("WeightedBraidPlan", "numeric.weighted_braid_plan"),
            message=(
                "A minimum-cost word in one supplied finite action is not an intrinsic geometric "
                "shortest path."
            ),
            remediation=(
                "Scope optimality to the declared action graph, generator convention, and exact "
                "nonnegative cost map."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="fleet.pari-and-python-verification-task-separation",
            triggered_by=(
                "backends.pari.arithmetic.v1",
                "cert.python.replay.v1",
                "fleet.plan_pari_arithmetic_task",
                "fleet.plan_python_certificate_replay_task",
            ),
            message=(
                "Pinned external arithmetic and portable Python receipt replay are distinct "
                "fleet trust boundaries."
            ),
            remediation=(
                "Route PARI certificates only to the exact pinned PARI capability task; route "
                "allowlisted portable receipts to the Python verification task."
            ),
            severity=HazardSeverity.ERROR,
        ),
        Hazard(
            id="fleet.scheduler-outcome-vs-mathematical-closure",
            triggered_by=(
                "backends.pari.arithmetic.v1",
                "cert.python.replay.v1",
                "FleetRun",
            ),
            message="A scheduler outcome or verified cache binding is non-closing.",
            remediation=(
                "Use the central certificate verifier report for receipt validity and the claim "
                "graph for mathematical closure."
            ),
            severity=HazardSeverity.ERROR,
        ),
    )
)
