"""Built-in mathematical contracts, preserving every v0.1 contract additively."""

from __future__ import annotations

from importlib import import_module

from .operations import (
    FailureMode,
    OperationExample,
    OperationRegistry,
    OperationSpec,
    OperationSpecError,
    default_operations,
)

INVALID_INPUT = FailureMode(
    "invalid_input",
    "the supplied values do not satisfy the operation's stated preconditions",
    "TypeError | ValueError",
)
DIMENSION_MISMATCH = FailureMode(
    "dimension_mismatch",
    "matrix, vector, or ambient-space dimensions are incompatible",
    "DimensionMismatchError",
)
FIELD_MISMATCH = FailureMode(
    "field_mismatch",
    "inputs use different prime coefficient fields",
    "FieldMismatchError",
)
SINGULAR_MATRIX = FailureMode(
    "singular_matrix",
    "the requested inverse does not exist",
    "SingularMatrixError",
)
NOT_CONTAINED = FailureMode(
    "not_contained",
    "a required subspace containment does not hold",
    "ValidationError",
)
CONCRETE_EMBEDDING = FailureMode(
    "concrete_embedding_mismatch",
    "objects do not use the same explicit concrete group embedding",
    "ConcreteEmbeddingError",
)
INVALID_ACTION = FailureMode(
    "invalid_action",
    "the supplied matrices do not define the stated group action",
    "InvalidActionError",
)
NONSEMISIMPLE = FailureMode(
    "semisimplicity_not_certified",
    "the requested projector or decomposition needs semisimplicity not certified in v0.1",
    "NonSemisimpleError",
)
NONSPLIT = FailureMode(
    "representation_not_split",
    "the cyclic action has non-linear factors over the base field",
    "NonSplitRepresentationError",
)
REPRESENTATION_FAILURE = FailureMode(
    "representation_verification_failed",
    "an advertised projector, decomposition, or completeness check fails exact validation",
    "RepresentationError",
)
COMPLEXITY_LIMIT = FailureMode(
    "complexity_limit",
    "the normalized-bar construction exceeds an explicit configured finite limit",
    "ComplexityLimitError",
)
INVALID_GROUP = FailureMode(
    "invalid_group",
    "the finite group table or supplied group map fails exact group-law checks",
    "InvalidGroupError",
)
COHOMOLOGY_FAILURE = FailureMode(
    "cohomology_verification_failed",
    "the exact differential, quotient, or certificate consistency check fails",
    "CohomologyError | CertificateVerificationError",
)
HURWITZ_UNSUPPORTED = FailureMode(
    "unsupported_hurwitz_scope",
    "v0.1 does not infer the missing concrete embedding, convention, or geometric structure",
    "UnsupportedHurwitzOperation",
)
BRAID_CLOSURE = FailureMode(
    "braid_closure_failed",
    "the requested move or operator leaves the supplied Nielsen class or component",
    "BraidClosureError",
)
HURWITZ_VERIFICATION = FailureMode(
    "hurwitz_verification_failed",
    "an exact finite Hurwitz witness fails replay or consistency checks",
    "CertificateVerificationError",
)
IMPORTED_BOUNDARY = FailureMode(
    "imported_boundary",
    "the operation requires exhaustive enumeration but received imported representatives",
    "ImportedBoundaryError",
)
PORTABILITY_BOUNDARY = FailureMode(
    "portable_promotion_refused",
    (
        "fresh-process promotion requires a computed-complete Nielsen receipt and, where "
        "applicable, a serializable operation definition"
    ),
    "CertificateVerificationError",
)
PORTABLE_HURWITZ_RESULT_TYPES = (
    "BraidAction",
    "ComponentCollection",
    "HurwitzComponent",
    "RealStructure",
    "RealCensus",
    "ReducedComponent",
    "CuspData",
    "BoundaryIncidence",
)
PORTABLE_HURWITZ_CLAIM_TYPES = (
    "NielsenClass",
    "NielsenEnumerationCertificate",
    "HurwitzOperationCertificate",
    *PORTABLE_HURWITZ_RESULT_TYPES,
)
GALOIS_SEMANTIC_RESULT_TYPES = (
    "FiniteGaloisQuotient",
    "GaloisModule",
    "KummerSpace",
    "KummerClass",
    "LocalH1Space",
    "LocalH1Class",
    "LocalizationMap",
    "TwistClassSet",
    "TwistClass",
    "NonabelianCocycle",
    "Unsupported",
)
ARITHMETIC_SEMANTIC_RESULT_TYPES = (
    "CartierDual",
    "LocalCondition",
    "LocalPairing",
    "SelmerKernel",
    "SelmerGroup",
    "DualSelmerResult",
    "AffineFamily",
    "LeftNullspaceObstruction",
    "Realized",
    "Obstructed",
    "Unknown",
)
DEFORMATION_SEMANTIC_RESULT_TYPES = (
    "ArtinRing",
    "ArtinRingMap",
    "SmallExtension",
    "DeformationComplex",
    "DeformationProblem",
    "GaugeSpace",
    "TangentSpace",
    "ObstructionSpace",
    "ObstructionClass",
    "Framing",
    "DeformationAction",
    "EquivariantDeformation",
    "InvariantDeformations",
    "EquivariantDecomposition",
    "LiftDatum",
    "LiftFamily",
    "LiftObstructed",
    "LiftUnknown",
    "UniqueLift",
    "NonUniqueLift",
    "LiftEndomorphism",
    "ContractionCertificate",
    "FixedLift",
    "Rigid",
    "NonRigid",
    "UnsupportedDeformation",
    "DeformationReceipt",
)
NUMERIC_SEMANTIC_RESULT_TYPES = (
    "Dyadic",
    "ComplexDyadic",
    "RealBall",
    "ComplexBall",
    "ExactPolynomial",
    "PolynomialSystem",
    "PolynomialFamily",
    "ParameterPath",
    "NumericPoint",
    "ExactCover",
    "ContinuationStep",
    "ContinuationTube",
    "ContinuationResult",
    "ConditionBound",
    "RecognitionBounds",
    "AlgebraicCandidate",
    "ExactificationResult",
    "RegularFiberWitness",
    "GenericDegreeWitness",
    "RegularFiberDegree",
    "DegreeResult",
    "BranchLoop",
    "BranchTracking",
    "NumericalCover",
    "BranchCycleTuple",
    "NielsenVertex",
    "BraidContinuationWitness",
    "QuadraticB2Homotopy",
    "BraidContinuationResult",
    "WeightedBraidPlan",
    "NumericUnknown",
    "UnsupportedNumeric",
    "NumericReceipt",
)
IO_OR_SCHEMA = FailureMode(
    "dataset_io_or_schema",
    "the imported dataset cannot be read or does not match the strict typed schema",
    "OSError | ValueError",
)
M23_EXACT_FAILURE = FailureMode(
    "m23_exact_replay_failed",
    "the specialized M23 v2 schema, digest binding, or compact finite witness replay fails",
    "M23ExactVerificationError",
)
ARITHMETIC_UNSUPPORTED = FailureMode(
    "unsupported_arithmetic_scope",
    "automatic arithmetic is outside the bounded prime-2 scope of Arbogast 0.2",
    "Unsupported",
)
ARITHMETIC_PRESENTATION = FailureMode(
    "invalid_arithmetic_presentation",
    (
        "a defining polynomial, basis, embedding, ideal HNF, place, group map, or module "
        "presentation fails canonical exact validation"
    ),
    "TypeError | ValueError | ArithmeticError",
)
INCOMPLETE_EVIDENCE = FailureMode(
    "incomplete_evidence",
    "the result remains a candidate because a declared completeness witness is absent",
    "IncompleteEvidenceError | Unsupported",
)
ASSUMPTION_BOUNDARY = FailureMode(
    "unresolved_assumption",
    "one or more explicit mathematical assumptions keep the claim conditional",
    "Unsupported",
)
PAIRING_VERIFICATION = FailureMode(
    "pairing_verification_failed",
    "the local pairing is not certified perfect or the proposed conditions are not orthogonal",
    "ValueError | CertificateVerificationError",
)
ARITHMETIC_VERIFICATION = FailureMode(
    "arithmetic_verification_failed",
    "a finite arithmetic, Kummer, local, Selmer, twist, or descent witness fails replay",
    "ValueError | CertificateVerificationError",
)
BACKEND_BUDGET = FailureMode(
    "backend_unknown_or_budget_exhausted",
    "the optional arithmetic backend is absent, unsupported, malformed, timed out, or capped",
    "BackendUnavailableError | PariBackendError",
)
DEFORMATION_UNSUPPORTED = FailureMode(
    "unsupported_deformation_scope",
    (
        "automatic geometric presentation, projector discovery, or canonical-lift theorem "
        "is outside the bounded finite-exact deformation slice"
    ),
    "UnsupportedDeformation | LiftUnknown | UnsupportedDeformationOperation",
)
DEFORMATION_PRESENTATION = FailureMode(
    "invalid_deformation_presentation",
    (
        "a ring, complex, framing, action, projector, lift datum, or endomorphism fails exact "
        "finite validation"
    ),
    "DeformationError | TypeError | ValueError",
)
DEFORMATION_VERIFICATION = FailureMode(
    "deformation_verification_failed",
    "a finite deformation identity, quotient, obstruction, or receipt fails exact replay",
    "DeformationVerificationError | CertificateVerificationError",
)
DEFORMATION_CONTRACTION = FailureMode(
    "contraction_not_certified",
    "the supplied affine lift operator is not certified contracting on all lift differences",
    "DeformationError | DeformationVerificationError | LiftUnknown",
)
NUMERIC_UNSUPPORTED = FailureMode(
    "unsupported_numeric_scope",
    (
        "the requested model, recognition bound, witness, or nontrivial cover deformation is "
        "outside the bounded portable numeric slice"
    ),
    "UnsupportedNumeric | UnsupportedNumericOperation",
)
NUMERIC_PRESENTATION = FailureMode(
    "invalid_numeric_presentation",
    (
        "an exact dyadic, ball, polynomial, path, cover, continuation, recognition, projection, "
        "or braid witness fails canonical bounded validation"
    ),
    "NumericError | TypeError | ValueError",
)
NUMERIC_NONCONCLUSION = FailureMode(
    "numeric_nonconclusion",
    (
        "missing witness data, insufficient isolation, or an unimplemented nontrivial cover "
        "homotopy leaves the requested conclusion explicitly unknown"
    ),
    "NumericUnknown | UnsupportedNumeric",
)
NUMERIC_VERIFICATION = FailureMode(
    "numeric_verification_failed",
    "an exact-dyadic inequality, discrete binding, or numeric receipt fails portable replay",
    "NumericVerificationError | CertificateVerificationError",
)
PADIC_UNSUPPORTED = FailureMode(
    "unsupported_padic_scope",
    (
        "the requested local-field, reduction, lifting, or descent computation is outside "
        "the bounded finite-exact p-adic slice"
    ),
    "Unsupported | UnsupportedPAdicOperation",
)
PADIC_PRESENTATION = FailureMode(
    "invalid_padic_presentation",
    (
        "a local-field, finite-precision, Frobenius, inertia, cover, reduction, lifting, "
        "or descent witness fails strict canonical validation"
    ),
    "PAdicError | TypeError | ValueError",
)
PADIC_NONCONCLUSION = FailureMode(
    "padic_nonconclusion",
    (
        "missing or incomplete exact witnesses leave certified fragments with obligations, "
        "an explicitly unknown conclusion, or a bounded software refusal"
    ),
    "Partial | Unknown | Unsupported",
)
PADIC_VERIFICATION = FailureMode(
    "padic_verification_failed",
    (
        "a finite local-field, reduction, lifting, descent, or p-adic receipt witness fails "
        "portable replay"
    ),
    "PAdicVerificationError | CertificateVerificationError",
)


def _spec(
    name: str,
    domain: str,
    requires: tuple[str, ...],
    ensures: tuple[str, ...],
    complexity: str,
    certificate_type: str | None,
    example: str,
    *,
    exact: bool = True,
    failure_modes: tuple[FailureMode, ...] = (INVALID_INPUT,),
    shardable: bool = False,
    shard_strategy: str | None = None,
    input_types: tuple[str, ...] = (),
    input_bundles: tuple[tuple[str, ...], ...] = (),
    output_type: str | None = None,
) -> OperationSpec:
    return OperationSpec(
        name=name,
        mathematical_domain=domain,
        requires=requires,
        ensures=ensures,
        exact=exact,
        shardable=shardable,
        complexity=complexity,
        failure_modes=failure_modes,
        certificate_type=certificate_type,
        examples=(OperationExample(example),),
        shard_strategy=shard_strategy,
        input_types=input_types,
        input_bundles=input_bundles,
        output_type=output_type,
    )


BUILTIN_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "cohom.h0",
        "finite group cohomology",
        ("finite group", "finite-dimensional exact module", "explicit group action"),
        ("returns exactly the invariant submodule M^G", "emits inclusion and kernel evidence"),
        "exact kernel of stacked action-minus-identity maps",
        "arbogast.cohom.CohomologyCertificate",
        "h0(group, module)",
        failure_modes=(INVALID_INPUT, COMPLEXITY_LIMIT, INVALID_GROUP, COHOMOLOGY_FAILURE),
        input_types=("FiniteGroup", "Module"),
        input_bundles=(("FiniteGroup", "Module"), ("CochainComplex",)),
        output_type="H0Result",
    ),
    _spec(
        "cohom.h1",
        "finite group cohomology",
        ("finite group", "finite-dimensional exact module", "explicit compatible action"),
        ("returns H^1 = Z^1/B^1", "returns explicit cocycles and quotient certificate"),
        "exact sparse kernel/image quotient",
        "arbogast.cohom.CohomologyCertificate",
        "h1(group, module).verify()",
        failure_modes=(INVALID_INPUT, COMPLEXITY_LIMIT, INVALID_GROUP, COHOMOLOGY_FAILURE),
        input_types=("FiniteGroup", "Module"),
        input_bundles=(("FiniteGroup", "Module"), ("CochainComplex",)),
        output_type="H1Result",
    ),
    _spec(
        "cohom.h2",
        "finite group cohomology",
        ("finite group", "finite-dimensional exact module", "cochain complex through degree 3"),
        ("returns H^2 = Z^2/B^2", "returns explicit obstruction representatives"),
        "exact sparse kernel/image quotient",
        "arbogast.cohom.CohomologyCertificate",
        "h2(group, module).verify()",
        failure_modes=(INVALID_INPUT, COMPLEXITY_LIMIT, INVALID_GROUP, COHOMOLOGY_FAILURE),
        input_types=("FiniteGroup", "Module"),
        input_bundles=(("FiniteGroup", "Module"), ("CochainComplex",)),
        output_type="H2Result",
    ),
    _spec(
        "hurwitz.nielsen_class",
        "Hurwitz theory",
        (
            "finite permutation group",
            "ordered explicit conjugacy classes; string labels are not resolved",
            "declared equivalence convention",
        ),
        (
            "every tuple is class-compatible, product-one, and generating",
            "enumeration is exhaustive",
            (
                "the result carries a portable NielsenEnumerationCertificate eligible for "
                "central promotion"
            ),
        ),
        "finite tuple enumeration modulo declared equivalence",
        "arbogast.hurwitz.NielsenEnumerationCertificate",
        "nielsen_class(group, classes)",
        failure_modes=(INVALID_INPUT, HURWITZ_UNSUPPORTED, HURWITZ_VERIFICATION),
        shardable=True,
        shard_strategy="fixed tuple prefixes and centralizer orbits",
        input_types=("FiniteGroup", "ConjugacyClassVector"),
        output_type="NielsenClass",
    ),
    _spec(
        "hurwitz.braid_action",
        "Hurwitz theory",
        ("finite canonical Nielsen class", "ordered branch-cycle convention"),
        (
            "each generator edge is an exact Hurwitz move",
            "action preserves the Nielsen class",
            (
                "fresh-process promotion is available only when the source has a "
                "computed-complete Nielsen receipt"
            ),
            "an imported source retains only context-bound edge receipts",
        ),
        "O(|Ni| * number_of_generators * canonicalization_cost)",
        (
            "tuple[arbogast.hurwitz.BraidEdgeCertificate, ...]; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for computed-complete sources"
        ),
        "braid_action(nielsen, mode='pure')",
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("NielsenClass",),
        output_type="BraidAction",
    ),
    _spec(
        "hurwitz.components",
        "Hurwitz theory",
        ("certified braid action", "declared pure or full braid subgroup"),
        (
            "returns the exhaustive orbit partition",
            "each component carries a connectivity witness",
            "fresh-process promotion requires a computed-complete Nielsen source",
            "an imported source retains only context-bound spanning-tree receipts",
        ),
        "linear in the certified braid graph",
        (
            "tuple[arbogast.hurwitz.SpanningTreeCertificate, ...]; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for computed-complete sources"
        ),
        "components(action)",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("NielsenClass", "BraidAction"),
        input_bundles=(("NielsenClass",), ("BraidAction",)),
        output_type="ComponentCollection",
    ),
    _spec(
        "hurwitz.real_points",
        "Hurwitz theory",
        ("finite Nielsen class", "ordered branch-cycle convention", "optional fiber conjugation"),
        (
            "every returned tuple satisfies the exact real criterion",
            "result is exhaustive over the supplied Nielsen class and selected fiber conjugations",
            (
                "returns a plain tuple and emits no certificate; real_census provides the "
                "certifiable result surface"
            ),
        ),
        "O(|Ni| * real_operator_cost)",
        None,
        "real_points(nielsen, c=nielsen.context.identity)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenClass",),
        output_type="tuple[NielsenTuple, ...]",
    ),
    _spec(
        "hurwitz.totally_real",
        "Hurwitz theory",
        ("finite Nielsen class", "ordered branch-cycle convention"),
        (
            "returns exactly the c=1 real classes",
            "does not infer coefficient reality",
            (
                "returns a plain tuple and emits no certificate; real_census provides the "
                "certifiable result surface"
            ),
        ),
        "O(|Ni| * real_operator_cost)",
        None,
        "totally_real(nielsen)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenClass",),
        output_type="tuple[NielsenTuple, ...]",
    ),
    _spec(
        "hurwitz.reduced",
        "Hurwitz theory",
        ("certified Hurwitz component", "one or more explicit finite symmetries"),
        (
            "returns exactly the quotient by the supplied symmetries",
            "carries a context-bound ReducedQuotientCertificate",
            "fresh-process promotion requires a computed-complete Nielsen source",
        ),
        "finite quotient-orbit computation",
        (
            "arbogast.hurwitz.ReducedQuotientCertificate; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for computed-complete sources"
        ),
        "reduced(component, (identity_symmetry,))",
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE, HURWITZ_VERIFICATION),
        input_types=("HurwitzComponent",),
        output_type="ReducedComponent",
    ),
    _spec(
        "hurwitz.cusps",
        "Hurwitz theory",
        ("certified component", "explicit braid-operator name or word"),
        (
            "returns exhaustive cusp orbits",
            "returns exact cusp widths",
            "carries a context-bound CuspCertificate",
            "fresh-process promotion requires a computed-complete Nielsen source",
        ),
        "finite permutation orbit computation",
        (
            "arbogast.hurwitz.CuspCertificate; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for computed-complete sources"
        ),
        "cusps(component, action.generators[0].name)",
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE, HURWITZ_VERIFICATION),
        input_types=("HurwitzComponent",),
        output_type="CuspData",
    ),
    _spec(
        "hurwitz.boundary",
        "Hurwitz theory",
        (
            "Nielsen tuple or certified Hurwitz component",
            "valid zero-based oriented adjacent collision",
        ),
        (
            "tuple input returns a product-one BoundaryTuple without asserting generation",
            (
                "component input returns exact incidence with a context-bound "
                "BoundaryIncidenceCertificate"
            ),
            "fresh-process promotion of component incidence requires a computed-complete source",
        ),
        "linear in component cardinality plus canonicalization",
        (
            "arbogast.hurwitz.BoundaryIncidenceCertificate for component input; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for computed-complete sources"
        ),
        "boundary(component, (0, 1))",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple", "HurwitzComponent"),
        input_bundles=(
            ("NielsenTuple", "Collision"),
            ("HurwitzComponent", "Collision"),
        ),
        output_type="BoundaryTuple | BoundaryIncidence",
    ),
    _spec(
        "cohom.claim_graph",
        "mathematical claims",
        ("exact verified H0, H1, or H2 result", "replayable cohomology certificate"),
        (
            "returns a central ClaimGraph",
            "binds the exact statement and claim ID to replayable finite evidence",
        ),
        "linear in certificate serialization size",
        "arbogast.cert.VerificationCertificate",
        "claim_graph_for_result(h1_result)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("H0Result", "H1Result", "H2Result"),
        input_bundles=(("H0Result",), ("H1Result",), ("H2Result",)),
        output_type="ClaimGraph",
    ),
    _spec(
        "cohom.verification_certificate",
        "certificate bridge",
        ("exact verified H0, H1, or H2 result", "self-contained domain certificate"),
        (
            "returns a central VerificationCertificate",
            "binds claim ID and statement hash to a replayed normalized-bar receipt",
        ),
        "linear in domain certificate serialization size",
        "arbogast.cert.VerificationCertificate",
        "verification_certificate_for_result(h1_result)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("H0Result", "H1Result", "H2Result"),
        input_bundles=(("H0Result",), ("H1Result",), ("H2Result",)),
        output_type="VerificationCertificate",
    ),
    _spec(
        "hurwitz.claim_graph",
        "mathematical claims",
        (
            "supported exact Hurwitz result with a self-contained portable receipt",
            "computed-complete Nielsen source and serializable operation definition where needed",
        ),
        (
            "returns a central ClaimGraph",
            "binds the exact statement and claim ID to replayable finite evidence",
            "refuses imported sources, opaque transforms, and unsupported context-only results",
        ),
        "linear in portable certificate serialization size",
        "arbogast.cert.VerificationCertificate",
        "claim_graph_for(nielsen)",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=PORTABLE_HURWITZ_CLAIM_TYPES,
        input_bundles=tuple((type_name,) for type_name in PORTABLE_HURWITZ_CLAIM_TYPES),
        output_type="ClaimGraph",
    ),
    _spec(
        "hurwitz.verification_certificate",
        "certificate bridge",
        (
            "supported exact Hurwitz result with a self-contained portable receipt",
            "computed-complete Nielsen source and serializable operation definition where needed",
        ),
        (
            "returns a central VerificationCertificate",
            "derives the only justified proposition and deterministic claim ID from the receipt",
        ),
        "linear in the portable Nielsen table",
        "arbogast.cert.VerificationCertificate",
        "verification_certificate_for(nielsen)",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=PORTABLE_HURWITZ_CLAIM_TYPES,
        input_bundles=tuple((type_name,) for type_name in PORTABLE_HURWITZ_CLAIM_TYPES),
        output_type="VerificationCertificate",
    ),
)


LINALG_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "linalg.as_dense",
        "exact linear algebra over prime fields",
        ("native DenseMatrix or SparseMatrix over one PrimeField",),
        ("returns the entrywise-equal canonical DenseMatrix",),
        "O(number of matrix entries)",
        None,
        "as_dense(matrix)",
        input_types=("Matrix",),
        output_type="DenseMatrix",
    ),
    _spec(
        "linalg.rref",
        "exact linear algebra over prime fields",
        ("finite matrix over one PrimeField",),
        (
            "returns deterministic reduced row-echelon form",
            "returns an invertible row transform mapping the input to that form",
        ),
        "O(rows * columns * min(rows, columns)) field operations",
        "arbogast.linalg.RREFResult",
        "rref(matrix).verify(matrix)",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH),
        input_types=("Matrix",),
        output_type="RREFResult",
    ),
    _spec(
        "linalg.rank",
        "exact linear algebra over prime fields",
        ("finite matrix over one PrimeField",),
        ("returns the exact row and column rank",),
        "RREF complexity",
        None,
        "rank(matrix)",
        input_types=("Matrix",),
        output_type="int",
    ),
    _spec(
        "linalg.determinant",
        "exact linear algebra over prime fields",
        ("square finite matrix over one PrimeField",),
        ("returns the determinant as the canonical residue; det(0x0)=1",),
        "O(n^3) field operations",
        None,
        "determinant(matrix)",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH),
        input_types=("Matrix",),
        output_type="int",
    ),
    _spec(
        "linalg.inverse",
        "exact linear algebra over prime fields",
        ("square invertible finite matrix over one PrimeField",),
        ("returns the unique two-sided exact inverse",),
        "O(n^3) field operations",
        None,
        "inverse(matrix)",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH, SINGULAR_MATRIX),
        input_types=("Matrix",),
        output_type="DenseMatrix",
    ),
    _spec(
        "linalg.row_space",
        "exact linear algebra over prime fields",
        ("finite matrix over one PrimeField",),
        ("returns its row span with a unique reduced basis",),
        "RREF complexity",
        None,
        "row_space(matrix)",
        input_types=("Matrix",),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.image",
        "exact linear algebra over prime fields",
        ("finite matrix representing F^n to F^m",),
        ("returns the exact column space with a unique reduced basis",),
        "RREF complexity",
        None,
        "image(matrix)",
        input_types=("Matrix",),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.nullspace",
        "exact linear algebra over prime fields",
        ("finite matrix representing F^n to F^m",),
        ("returns exactly the vectors annihilated by the matrix",),
        "RREF complexity",
        None,
        "nullspace(matrix)",
        input_types=("Matrix",),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.left_nullspace",
        "exact linear algebra over prime fields",
        ("finite matrix over one PrimeField",),
        ("returns exactly the row vectors y with y^T A = 0",),
        "RREF complexity",
        None,
        "left_nullspace(matrix)",
        input_types=("Matrix",),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.sum_subspaces",
        "exact linear algebra over prime fields",
        ("two subspaces of the same finite-dimensional space over the same field",),
        ("returns their exact vector-space sum with a unique reduced basis",),
        "RREF complexity in the combined basis size",
        None,
        "sum_subspaces(left, right)",
        failure_modes=(INVALID_INPUT, FIELD_MISMATCH, DIMENSION_MISMATCH),
        input_types=("LinearSubspace", "LinearSubspace"),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.intersection",
        "exact linear algebra over prime fields",
        ("two subspaces of the same finite-dimensional space over the same field",),
        ("returns their exact intersection with a unique reduced basis",),
        "one nullspace computation on the joined bases",
        None,
        "intersection(left, right)",
        failure_modes=(INVALID_INPUT, FIELD_MISMATCH, DIMENSION_MISMATCH),
        input_types=("LinearSubspace", "LinearSubspace"),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.complement",
        "exact linear algebra over prime fields",
        ("subspace contained in the optional containing subspace",),
        (
            "returns the deterministic direct complement inside the requested container",
            "does not claim a canonical complement independent of the coordinate basis",
        ),
        "RREF plus exact direct-sum checks",
        None,
        "complement(subspace, within=container)",
        failure_modes=(INVALID_INPUT, FIELD_MISMATCH, DIMENSION_MISMATCH, NOT_CONTAINED),
        input_types=("LinearSubspace", "LinearSubspace | None"),
        input_bundles=(("LinearSubspace",),),
        output_type="LinearSubspace",
    ),
    _spec(
        "linalg.quotient_space",
        "exact linear algebra over prime fields",
        ("denominator contained in numerator over the same field and ambient space",),
        (
            "returns numerator/denominator with deterministic coordinate representatives",
            "verifies containment and the canonical coordinate complement",
        ),
        "complement and RREF complexity",
        "arbogast.linalg.QuotientSpace",
        "quotient_space(numerator, denominator).verify()",
        failure_modes=(INVALID_INPUT, FIELD_MISMATCH, DIMENSION_MISMATCH, NOT_CONTAINED),
        input_types=("LinearSubspace", "LinearSubspace"),
        output_type="QuotientSpace",
    ),
    _spec(
        "linalg.solve",
        "exact linear algebra over prime fields",
        ("finite matrix and right-hand side of matching row dimension",),
        (
            "returns a particular solution and full kernel when consistent",
            "otherwise returns an exact separating left-nullspace witness",
        ),
        "RREF complexity",
        "arbogast.linalg.LinearSolveResult",
        "solve(matrix, rhs).verify(matrix, rhs)",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH),
        input_types=("Matrix", "Iterable[Scalar]"),
        output_type="LinearSolveResult",
    ),
)

BUILTIN_OPERATION_SPECS += LINALG_OPERATION_SPECS


REP_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "rep.symmetric_group",
        "finite concrete permutation groups",
        ("nonnegative integer permutation degree",),
        ("returns the standard concrete symmetric group on range(degree)",),
        "finite closure of two standard generators",
        None,
        "symmetric_group(4)",
        input_types=("int",),
        output_type="PermutationGroup",
    ),
    _spec(
        "rep.cyclic_group",
        "finite concrete permutation groups",
        (
            "positive order or explicit permutation generator",
            "any declared degree and generator order agree",
        ),
        ("returns the exact concrete cyclic permutation group generated by that element",),
        "finite closure of one permutation generator",
        None,
        "cyclic_group(5)",
        input_types=("int | Permutation", "int | None", "Permutation | None"),
        input_bundles=(("int",), ("Permutation",)),
        output_type="CyclicGroup",
    ),
    _spec(
        "rep.representation",
        "finite-field group representations",
        (
            "finite enumerable concrete group",
            "prime field and one square action matrix for every concrete element",
        ),
        (
            "returns the supplied concrete action without isomorphism transport",
            "validates identity and every multiplication pair unless validate=False is explicit",
        ),
        "O(|G|^2 d^3) when validation is enabled",
        None,
        "representation(group, field, action)",
        failure_modes=(INVALID_INPUT, CONCRETE_EMBEDDING, INVALID_ACTION),
        input_types=("FiniteGroup", "PrimeField | int", "Mapping | Callable"),
        output_type="Representation",
    ),
    _spec(
        "rep.fixed_part",
        "finite-field group representations",
        ("exact representation and a literal element of its concrete group",),
        ("returns exactly ker(rho(sigma)-I)",),
        "one exact kernel computation",
        None,
        "fixed_part(module, sigma)",
        failure_modes=(INVALID_INPUT, CONCRETE_EMBEDDING),
        input_types=("Representation", "GroupElement"),
        output_type="LinearSubspace",
    ),
    _spec(
        "rep.semisimple",
        "finite-field group representations",
        ("exact finite representation",),
        (
            "a true result certifies semisimplicity by Maschke or an explicitly trivial action",
            (
                "a false result means v0.1 does not certify semisimplicity; "
                "it is not a proof of failure"
            ),
        ),
        "O(|G| d^2) for the modular trivial-action check",
        None,
        "semisimple(module)",
        failure_modes=(INVALID_INPUT, INVALID_ACTION),
        input_types=("Representation",),
        output_type="SemisimplicityResult",
    ),
    _spec(
        "rep.weight_spaces",
        "finite-field cyclic representations",
        (
            "exact cyclic representation with distinguished generator",
            "generator order prime to the characteristic and split over the base field",
        ),
        (
            "returns the complete eigenspace decomposition over the base field",
            "does not extend scalars to split non-linear factors",
        ),
        "factor x^n-1 and evaluate exact CRT projectors",
        None,
        "weight_spaces(module)",
        failure_modes=(
            INVALID_INPUT,
            CONCRETE_EMBEDDING,
            NONSEMISIMPLE,
            NONSPLIT,
            REPRESENTATION_FAILURE,
        ),
        input_types=("Representation", "GroupElement | None"),
        input_bundles=(("Representation",),),
        output_type="WeightDecomposition",
    ),
    _spec(
        "rep.projector",
        "finite-field representation decomposition",
        (
            "exact representation",
            "explicit Character or factor of a certified cyclic decomposition",
        ),
        (
            "returns an exact idempotent equivariant projector for the requested component",
            "does not infer a character table or scalar extension",
        ),
        "finite group averaging or cyclic CRT factorization",
        None,
        "projector(module, character)",
        failure_modes=(
            INVALID_INPUT,
            CONCRETE_EMBEDDING,
            NONSEMISIMPLE,
            REPRESENTATION_FAILURE,
        ),
        input_types=("Representation", "Character | CyclicFactor | int"),
        output_type="DenseMatrix",
    ),
    _spec(
        "rep.isotypic",
        "finite-field representation decomposition",
        (
            "exact representation",
            "explicit Character or factor of a certified cyclic decomposition",
        ),
        ("returns the exact image of the corresponding checked projector",),
        "projector computation plus exact image",
        None,
        "isotypic(module, character)",
        failure_modes=(
            INVALID_INPUT,
            CONCRETE_EMBEDDING,
            NONSEMISIMPLE,
            REPRESENTATION_FAILURE,
        ),
        input_types=("Representation", "Character | CyclicFactor | int"),
        output_type="LinearSubspace",
    ),
    _spec(
        "rep.decompose",
        "finite-field representation decomposition",
        (
            "exact representation",
            "either explicit characters or a distinguished cyclic generator",
        ),
        (
            "returns checked orthogonal projectors and their exact images",
            "retains an explicit residual unless require_complete=True",
            "does not infer abstract-group transport or a missing character table",
        ),
        "finite character averaging or cyclic CRT factorization",
        None,
        "decompose(module, characters=characters)",
        failure_modes=(
            INVALID_INPUT,
            CONCRETE_EMBEDDING,
            NONSEMISIMPLE,
            REPRESENTATION_FAILURE,
        ),
        input_types=("Representation", "FiniteGroup | None"),
        input_bundles=(("Representation",),),
        output_type="CyclicDecomposition | IsotypicDecomposition",
    ),
)

BUILTIN_OPERATION_SPECS += REP_OPERATION_SPECS


COHOM_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "cohom.cochain_complex",
        "normalized finite-group cohomology",
        (
            "finite enumerable group with explicit identity and multiplication",
            "finite-dimensional exact module over a prime field with a compatible action",
            "nonnegative requested degree within explicit complexity limits",
        ),
        (
            "returns the normalized inhomogeneous bar complex through the requested degree",
            "binds finite multiplication/action snapshots and exact differential hashes",
        ),
        "exponential in cochain degree and group order, guarded by explicit limits",
        None,
        "cochain_complex(group, module, 2)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, INVALID_ACTION, COMPLEXITY_LIMIT),
        input_types=("FiniteGroup", "Module", "int"),
        output_type="CochainComplex",
    ),
    _spec(
        "cohom.cohomology",
        "normalized finite-group cohomology",
        ("verified CochainComplex built through the requested nonnegative degree",),
        (
            "returns exactly ker(d_n)/im(d_(n-1))",
            "returns quotient projection, section, representatives, and replayable certificate",
        ),
        "exact kernel, image, complement, and quotient linear algebra",
        "arbogast.cohom.CohomologyCertificate",
        "cohomology(complex_, degree).verify()",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("CochainComplex", "int"),
        output_type="CohomologyResult",
    ),
    _spec(
        "cohom.cocycles",
        "normalized finite-group cohomology",
        ("verified CochainComplex containing the outgoing differential",),
        ("returns exactly ker(d_n) with a canonical finite-field basis",),
        "full cohomology computation in the requested degree",
        None,
        "cocycles(complex_, degree)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("CochainComplex", "int"),
        output_type="CochainSubspace",
    ),
    _spec(
        "cohom.coboundaries",
        "normalized finite-group cohomology",
        ("verified CochainComplex containing the preceding differential",),
        ("returns exactly im(d_(n-1)) with a canonical finite-field basis",),
        "full cohomology computation in the requested degree",
        None,
        "coboundaries(complex_, degree)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("CochainComplex", "int"),
        output_type="CochainSubspace",
    ),
    _spec(
        "cohom.is_cocycle",
        "normalized finite-group cohomology",
        ("cochain whose complex contains the outgoing differential",),
        ("returns true exactly when the outgoing differential annihilates the cochain",),
        "one sparse differential application",
        None,
        "is_cocycle(cochain)",
        input_types=("Cochain",),
        output_type="bool",
    ),
    _spec(
        "cohom.is_coboundary",
        "normalized finite-group cohomology",
        ("cochain and optional matching CohomologyResult in the same degree and complex",),
        (
            "decides exact membership in im(d_(n-1))",
            "when membership holds, returns an explicit primitive witness",
        ),
        "cohomology plus exact linear solve unless a matching result is supplied",
        "arbogast.cohom.CoboundaryWitness",
        "is_coboundary(cochain)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("Cochain", "CohomologyResult | None"),
        input_bundles=(("Cochain",),),
        output_type="CoboundaryWitness",
    ),
    _spec(
        "cohom.class_of",
        "normalized finite-group cohomology",
        ("cocycle and optional matching CohomologyResult in the same degree and complex",),
        (
            "returns canonical quotient coordinates and representative of its cohomology class",
            "rejects a cochain that is not a cocycle",
        ),
        "cohomology plus quotient projection unless a matching result is supplied",
        None,
        "class_of(cocycle)",
        failure_modes=(INVALID_INPUT, COHOMOLOGY_FAILURE),
        input_types=("Cochain", "CohomologyResult | None"),
        input_bundles=(("Cochain",),),
        output_type="CohomologyClass",
    ),
    _spec(
        "cohom.restrict",
        "functorial finite-group cohomology maps",
        (
            "cochain or represented class on an exact finite complex",
            "literal subgroup inclusion or explicit injective homomorphism",
        ),
        (
            "checks identity, multiplication, and injectivity before transport",
            "returns the exact restricted cochain or recomputed cohomology class",
            "does not infer an abstract subgroup isomorphism",
        ),
        "quadratic homomorphism validation plus target bar construction",
        None,
        "restrict(cochain, subgroup, inclusion)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=("Cochain | CohomologyClass", "FiniteGroup", "GroupMap | None"),
        output_type="Cochain | CohomologyClass",
    ),
    _spec(
        "cohom.inflate",
        "functorial finite-group cohomology maps",
        (
            "cochain or represented class on an exact quotient complex",
            "explicit surjective homomorphism from the total group",
        ),
        (
            "checks identity, multiplication, and surjectivity before transport",
            "returns the exact inflated cochain or recomputed cohomology class",
            "does not infer an extension or quotient map from group labels",
        ),
        "quadratic homomorphism validation plus target bar construction",
        None,
        "inflate(cochain, group, projection)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=("Cochain | CohomologyClass", "FiniteGroup | Extension", "GroupMap | None"),
        output_type="Cochain | CohomologyClass",
    ),
    _spec(
        "cohom.restriction_map",
        "certified functorial finite-group cohomology",
        (
            "exact H^0, H^1, or H^2 result on a pinned finite group action",
            "literal subgroup inclusion or explicit injective FiniteGroupMap",
        ),
        (
            "returns a first-class induced linear map on the requested cohomology degree",
            "replays group-map axioms, cochain transport, and quotient independence",
            "binds source, target, degree, matrices, and finite witness in one certificate",
        ),
        "finite homomorphism validation, bar transport, and quotient projection",
        "arbogast.cohom.CohomologyMapCertificate",
        "restriction_map(h1_result, subgroup)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=("CohomologyResult", "FiniteGroup", "FiniteGroupMap | None"),
        input_bundles=(("CohomologyResult", "FiniteGroup"),),
        output_type="InducedCohomologyMap",
    ),
    _spec(
        "cohom.inflation_map",
        "certified functorial finite-group cohomology",
        (
            "exact H^0, H^1, or H^2 result on a pinned quotient action",
            "explicit surjective FiniteGroupMap or pinned FiniteGroupExtension",
        ),
        (
            "returns a first-class induced linear map on the requested cohomology degree",
            "replays the quotient projection, cochain transport, and quotient independence",
            "does not infer an implicit quotient identification",
        ),
        "finite homomorphism validation, bar transport, and quotient projection",
        "arbogast.cohom.CohomologyMapCertificate",
        "inflation_map(h1_quotient, extension)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=(
            "CohomologyResult",
            "FiniteGroup | FiniteGroupExtension",
            "FiniteGroupMap | None",
        ),
        input_bundles=(
            ("CohomologyResult", "FiniteGroupExtension"),
            ("CohomologyResult", "FiniteGroup", "FiniteGroupMap"),
        ),
        output_type="InducedCohomologyMap",
    ),
    _spec(
        "cohom.corestriction_map",
        "certified transfer in finite-group cohomology",
        (
            "exact H^0, H^1, or H^2 result for a pinned finite subgroup action",
            "explicit subgroup inclusion into the ambient finite group",
            "complete declared transversal or deterministic complete transversal construction",
        ),
        (
            "returns the induced corestriction map computed by the complete transfer formula",
            "certifies the transversal and every finite transfer summand",
            "checks class-level independence from cocycle representative choices",
        ),
        "complete transversal transfer followed by exact quotient projection",
        "arbogast.cohom.CohomologyMapCertificate",
        "corestriction_map(h1_subgroup, ambient_group)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=(
            "CohomologyResult",
            "FiniteGroup",
            "Representation | None",
            "FiniteGroupMap | None",
        ),
        input_bundles=(("CohomologyResult", "FiniteGroup"),),
        output_type="InducedCohomologyMap",
    ),
    _spec(
        "cohom.corestrict",
        "finite-group cohomology convenience transport",
        (
            "cochain or represented class for a pinned finite subgroup action",
            "explicit ambient action and subgroup inclusion",
            "complete declared or deterministically constructed transversal",
        ),
        (
            "preserves the v0.2 convenience return shape while using certified transfer",
            "returns the exact transferred cochain or recomputed cohomology class",
            "does not claim a first-class map when called on one value",
        ),
        "one certified corestriction-map construction and application",
        None,
        "corestrict(cocycle, ambient_group)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=(
            "Cochain | CohomologyClass",
            "FiniteGroup",
            "Representation | None",
            "FiniteGroupMap | None",
        ),
        input_bundles=(("Cochain | CohomologyClass", "FiniteGroup"),),
        output_type="Cochain | CohomologyClass",
    ),
    _spec(
        "cohom.transgression",
        "certified inflation--restriction cohomology",
        (
            "pinned finite group extension 1 -> N -> G -> Q -> 1",
            "prime-field G-module, or an already certified five-term sequence",
        ),
        (
            "returns the exact connecting map H^1(N,M)^Q -> H^2(Q,M^N)",
            "binds the complete finite transgression witnesses and endpoint cohomology",
            "participates in independently replayed zero composites and image-equals-kernel",
        ),
        "one complete normalized-bar five-term construction unless a sequence is supplied",
        "arbogast.cohom.InflationRestrictionCertificate",
        "transgression(extension, module)",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=(
            "FiniteGroupExtension | InflationRestrictionSequence",
            "Representation | None",
        ),
        input_bundles=(
            ("FiniteGroupExtension", "Representation"),
            ("InflationRestrictionSequence",),
        ),
        output_type="ExactLinearMap",
    ),
    _spec(
        "cohom.inflation_restriction",
        "certified inflation--restriction cohomology",
        (
            "pinned exact finite group extension 1 -> N -> G -> Q -> 1",
            "finite-dimensional prime-field G-module with explicit action",
        ),
        (
            "returns the complete five-term sequence through H^2",
            "checks all adjacent composites are zero",
            "independently recomputes image equals kernel at every interior term",
            "returns one portable central verification certificate for the full exactness claim",
        ),
        "five normalized-bar cohomology calculations plus complete finite witness replay",
        "arbogast.cohom.InflationRestrictionCertificate",
        "inflation_restriction(extension, module).verify()",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=("FiniteGroupExtension", "Representation"),
        output_type="InflationRestrictionSequence",
    ),
)

BUILTIN_OPERATION_SPECS += COHOM_OPERATION_SPECS


GALOIS_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "galois.finite_galois_quotient",
        "finite Galois quotient presentations",
        (
            "pinned exact base NumberField and concrete finite PermutationGroup",
            "explicit label, arithmetic presentation, and proof context",
            "a COMPLETE context only when paired with a bound proving certificate",
        ),
        (
            "returns the canonical candidate or certified finite quotient presentation",
            "binds the base field, concrete group table, label, and arithmetic presentation",
            "never promotes a nontrivial arithmetic realization from a completeness flag alone",
        ),
        "complete finite presentation validation and optional proving-certificate replay",
        "arbogast.cert.VerificationCertificate using galois.quotient_presentation.v1",
        "finite_galois_quotient(Q, group, label='candidate')",
        failure_modes=(
            INVALID_INPUT,
            INVALID_GROUP,
            ARITHMETIC_PRESENTATION,
            INCOMPLETE_EVIDENCE,
            ARITHMETIC_VERIFICATION,
        ),
        input_types=(
            "NumberField",
            "PermutationGroup",
            "ProofContext | None",
            "VerificationCertificate | None",
        ),
        input_bundles=(("NumberField", "PermutationGroup"),),
        output_type="FiniteGaloisQuotient",
    ),
    _spec(
        "galois.galois_module",
        "finite Galois modules",
        (
            "pinned finite Galois quotient",
            "finite-dimensional representation over one prime field",
        ),
        (
            "binds the quotient presentation and every action matrix canonically",
            "validates the complete finite group action without implicit isomorphism transport",
        ),
        "complete finite representation validation",
        "arbogast.galois.GaloisModuleReceipt nested in arbogast.cert.VerificationCertificate",
        "galois_module(quotient, representation)",
        failure_modes=(INVALID_INPUT, ARITHMETIC_PRESENTATION, INVALID_ACTION),
        input_types=(
            "FiniteGaloisQuotient",
            "Representation | PrimeField | int",
            "Mapping | Callable | None",
        ),
        input_bundles=(
            ("FiniteGaloisQuotient", "Representation"),
            ("FiniteGaloisQuotient", "PrimeField", "Mapping | Callable"),
        ),
        output_type="GaloisModule",
    ),
    _spec(
        "galois.finite_galois_quotient_certificate",
        "finite Galois quotient proof factories",
        (
            "pinned exact base NumberField and concrete finite PermutationGroup",
            "exact label and arithmetic presentation",
            "the bounded portable factory currently accepts only the canonical trivial quotient",
        ),
        (
            "returns a central verification certificate with a complete finite-group receipt",
            "binds the base field, group table, label, and arithmetic presentation exactly",
            "rejects nontrivial quotient promotion without external arithmetic proving evidence",
        ),
        "complete replay of the trivial group table and portable base-field witness",
        "arbogast.cert.VerificationCertificate using galois.finite_quotient.v1",
        (
            "finite_galois_quotient_certificate(Q, trivial_group, "
            "label='trivial', presentation=portable_presentation)"
        ),
        failure_modes=(
            INVALID_INPUT,
            INVALID_GROUP,
            ARITHMETIC_PRESENTATION,
            INCOMPLETE_EVIDENCE,
            ARITHMETIC_VERIFICATION,
        ),
        input_types=("NumberField", "PermutationGroup"),
        output_type="VerificationCertificate",
    ),
    _spec(
        "galois.kummer_space",
        "finite Kummer arithmetic",
        (
            "pinned exact number-field presentation and complete declared place set",
            "prime 2 for automatic arithmetic, or a certified finite prime-p presentation",
        ),
        (
            "returns finite K(S,p), never unrestricted K^*/K^{*p}",
            (
                "binds its ordered basis, S-units, class-group p-torsion, and "
                "principalization witnesses"
            ),
            "keeps assumptions, verifier trust, and completeness as independent evidence axes",
            "returns typed Unsupported outside the automatic p=2 slice",
            (
                "returns a receipt-bearing non-closing PariArithmeticResult for backend "
                "UNKNOWN or BUDGET_EXHAUSTED"
            ),
        ),
        "finite S-unit and class-group presentation replay; discovery may require pinned PARI",
        "arbogast.galois.KummerReceipt nested in arbogast.cert.VerificationCertificate",
        "kummer_space(Q, (place_2, place_infinity))",
        failure_modes=(
            INVALID_INPUT,
            ARITHMETIC_PRESENTATION,
            ARITHMETIC_UNSUPPORTED,
            INCOMPLETE_EVIDENCE,
            ASSUMPTION_BOUNDARY,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        input_types=("NumberField", "Iterable[Place]"),
        output_type="KummerSpace | Unsupported | PariArithmeticResult",
    ),
    _spec(
        "galois.kummer_class",
        "finite Kummer arithmetic",
        ("certified finite KummerSpace", "prime-field coordinate vector of matching dimension"),
        (
            "returns the canonical Kummer class in the pinned ordered basis",
            "binds the class coordinates to the complete source-space receipt",
        ),
        "linear coordinate canonicalization",
        "arbogast.galois.KummerReceipt nested in arbogast.cert.VerificationCertificate",
        "kummer_class(space, (1, 0))",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH, ARITHMETIC_VERIFICATION),
        input_types=("KummerSpace", "Iterable[int]"),
        output_type="KummerClass",
    ),
    _spec(
        "galois.local_h1",
        "continuous local Kummer cohomology",
        (
            "exact finite or infinite place",
            "prime 2 for automatic arithmetic, or a certified finite prime-p presentation",
        ),
        (
            "returns genuine certified H^1(K_v,mu_p)",
            "includes exact archimedean and finite-place identity in the receipt",
            "never silently identifies continuous local cohomology with finite D_v cohomology",
            "returns typed Unsupported outside the automatic p=2 slice",
            (
                "returns a receipt-bearing non-closing PariArithmeticResult for backend "
                "UNKNOWN or BUDGET_EXHAUSTED"
            ),
        ),
        "finite local squareclass presentation replay",
        "arbogast.galois.LocalH1Receipt nested in arbogast.cert.VerificationCertificate",
        "local_h1(place_2)",
        failure_modes=(
            INVALID_INPUT,
            ARITHMETIC_PRESENTATION,
            ARITHMETIC_UNSUPPORTED,
            INCOMPLETE_EVIDENCE,
            ASSUMPTION_BOUNDARY,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        shardable=True,
        shard_strategy="one deterministic shard per canonical place ID",
        input_types=("FinitePlace | InfinitePlace",),
        output_type="LocalH1Space | Unsupported | PariArithmeticResult",
    ),
    _spec(
        "galois.local_h1_class",
        "continuous local Kummer cohomology",
        (
            "genuine certified finite local H^1 space",
            "prime-field coordinate vector of matching dimension",
        ),
        (
            "returns the canonical class in the pinned local squareclass basis",
            "binds its coordinates to the exact local H^1 receipt",
            "does not identify the class with finite decomposition-quotient cohomology",
        ),
        "linear coordinate canonicalization",
        "arbogast.galois.LocalH1Receipt nested in arbogast.cert.VerificationCertificate",
        "local_h1_class(local_space, (1, 0, 0))",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH, ARITHMETIC_VERIFICATION),
        input_types=("LocalH1Space", "Iterable[int]"),
        output_type="LocalH1Class",
    ),
    _spec(
        "galois.decomposition_quotient_h1",
        "finite decomposition-quotient cohomology",
        (
            "explicit finite decomposition quotient and prime-field module",
            "complete finite group presentation",
        ),
        (
            "returns certified finite H^1(D_v,M)",
            "keeps this result separate from continuous H^1(K_v,M)",
        ),
        "normalized finite-group bar cohomology",
        "arbogast.cohom.CohomologyCertificate",
        "decomposition_quotient_h1(module)",
        failure_modes=(INVALID_INPUT, COMPLEXITY_LIMIT, COHOMOLOGY_FAILURE),
        input_types=("FiniteGroup | GaloisModule", "Representation | None"),
        input_bundles=(("GaloisModule",), ("FiniteGroup", "Representation")),
        output_type="H1Result",
    ),
    _spec(
        "galois.localize",
        "Kummer localization",
        (
            "certified finite global Kummer space or class",
            "genuine local H^1 space or exact target place",
            (
                "automatic certified mu2 arithmetic at supported rational, finite-PARI, "
                "or exact archimedean places, or a certified localization matrix"
            ),
        ),
        (
            "binds the global basis, local basis, place, and exact matrix",
            "returns the induced local class when the source is a Kummer class",
            "returns typed Unsupported rather than guessing an unavailable matrix",
            (
                "returns a receipt-bearing non-closing PariArithmeticResult for backend "
                "UNKNOWN or BUDGET_EXHAUSTED"
            ),
        ),
        "exact prime-field matrix construction and application",
        "arbogast.galois.LocalizationReceipt nested in arbogast.cert.VerificationCertificate",
        "localize(kummer, local_space)",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            FIELD_MISMATCH,
            ARITHMETIC_UNSUPPORTED,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        shardable=True,
        shard_strategy="one deterministic shard for each canonical place and Kummer generator",
        input_types=("KummerSpace | KummerClass", "LocalH1Space | Place"),
        output_type=("LocalizationMap | LocalH1Class | Unsupported | PariArithmeticResult"),
    ),
    _spec(
        "galois.nonabelian_h1",
        "finite nonabelian cohomology",
        (
            "two completely enumerated finite groups",
            "explicit action of the first group by automorphisms of the second",
            "declared exhaustive-enumeration budget",
        ),
        (
            "exhaustively enumerates crossed homomorphisms and coefficient-conjugacy orbits",
            "returns a pointed set whose first class is the identity class",
            "does not expose vector-space operations or construct twisted models",
        ),
        "exponential finite enumeration bounded by max_assignments",
        "arbogast.galois.TwistReceipt nested in arbogast.cert.VerificationCertificate",
        "nonabelian_h1(C2, S3, action='trivial')",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, ARITHMETIC_VERIFICATION),
        input_types=("FiniteGroup", "FiniteGroup", "Action | None"),
        output_type="TwistClassSet | Unsupported",
    ),
    _spec(
        "galois.twist_classes",
        "finite nonabelian twist classes",
        (
            "two completely enumerated finite groups",
            "explicit finite action and declared enumeration budget",
        ),
        (
            "returns exactly the pointed nonabelian H^1 cocycle-orbit set",
            "does not claim automatic twisted models, curves, or descent",
        ),
        "the same bounded exhaustive enumeration as nonabelian_h1",
        "arbogast.galois.TwistReceipt nested in arbogast.cert.VerificationCertificate",
        "twist_classes(C2, S3, action='trivial')",
        failure_modes=(INVALID_INPUT, INVALID_GROUP, COMPLEXITY_LIMIT, ARITHMETIC_VERIFICATION),
        input_types=("FiniteGroup", "FiniteGroup", "Action | None"),
        output_type="TwistClassSet | Unsupported",
    ),
)

BUILTIN_OPERATION_SPECS += GALOIS_OPERATION_SPECS


ARITHMETIC_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "arithmetic.cartier_dual",
        "Cartier-dual finite Galois modules",
        (
            "explicit verified finite GaloisModule action",
            "a certified cyclotomic character when an automatic p>2 Tate twist is unavailable",
        ),
        (
            "returns the exact contragredient action M^vee(1)",
            "binds the source quotient, action matrices, Tate twist, and optional dual module",
            "does not infer an unavailable cyclotomic character",
        ),
        "one inverse-transpose per complete finite action matrix",
        "arbogast.arithmetic.ArithmeticReceipt nested in arbogast.cert.VerificationCertificate",
        "cartier_dual(module)",
        failure_modes=(
            INVALID_INPUT,
            FIELD_MISMATCH,
            ARITHMETIC_UNSUPPORTED,
            ARITHMETIC_VERIFICATION,
        ),
        input_types=("GaloisModule", "GaloisModule | None"),
        input_bundles=(("GaloisModule",), ("GaloisModule", "GaloisModule")),
        output_type="CartierDual",
    ),
    _spec(
        "arithmetic.local_pairing",
        "exact local Tate and Hilbert pairings",
        (
            "one or two genuine certified local H^1 spaces at the same exact place",
            "either an exact matrix or supported automatic p=2 Hilbert arithmetic",
        ),
        (
            "returns an exact bilinear pairing bound to both local spaces and their place",
            "keeps candidate pairing matrices distinct from certified complete Hilbert evidence",
            "records pinned PARI verification separately when portable replay is unavailable",
        ),
        "matrix validation or one closed Hilbert-symbol call per ordered basis pair",
        "arbogast.arithmetic.LocalPairingCertificate",
        "local_pairing(local_space)",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            FIELD_MISMATCH,
            PAIRING_VERIFICATION,
            ARITHMETIC_UNSUPPORTED,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        input_types=("LocalH1Space", "LocalH1Space | None", "Matrix | None"),
        input_bundles=(
            ("LocalH1Space",),
            ("LocalH1Space", "LocalH1Space"),
            ("LocalH1Space", "LocalH1Space", "Matrix"),
        ),
        output_type="LocalPairing",
    ),
    _spec(
        "arithmetic.local_condition",
        "Kummer local conditions",
        (
            "genuine certified finite local H^1 space",
            "explicit prime-field subspace basis and exact place",
        ),
        (
            "returns the exact pinned local-condition subspace",
            "binds the ambient local space, place, basis, and quotient map",
            "cannot claim completeness beyond the independently verified ambient local space",
        ),
        "exact subspace canonicalization and quotient-kernel replay",
        "arbogast.arithmetic.LocalConditionCertificate",
        "local_condition(local_space, ((1, 0, 0),))",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            FIELD_MISMATCH,
            INCOMPLETE_EVIDENCE,
            ARITHMETIC_VERIFICATION,
        ),
        input_types=("LocalH1Space", "LinearSubspace | Iterable[Iterable[int]]"),
        output_type="LocalCondition",
    ),
    _spec(
        "arithmetic.selmer",
        "finite Kummer Selmer problems",
        (
            "finite global Kummer space with exact localization maps",
            "one certified local condition at every declared place",
            "explicit relevant place set",
        ),
        (
            "returns the exact kernel of the global-to-local quotient map",
            "keeps an incompletely justified result typed as SelmerKernel",
            (
                "promotes to SelmerGroup only when global space, local spaces, maps, "
                "conditions, and place set all independently replay as complete"
            ),
            "keeps assumptions, verifier trust, and completeness independent",
        ),
        "exact block-matrix assembly and prime-field nullspace",
        "arbogast.arithmetic.SelmerCertificate",
        "selmer(SelmerProblem(global_space, localizations, conditions))",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            FIELD_MISMATCH,
            ARITHMETIC_PRESENTATION,
            INCOMPLETE_EVIDENCE,
            ASSUMPTION_BOUNDARY,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        shardable=True,
        shard_strategy="place-major, Kummer-generator-minor exact quotient-matrix columns",
        input_types=(
            "SelmerProblem | KummerSpace",
            "LocalizationCollection | None",
            "LocalConditionCollection | None",
        ),
        input_bundles=(
            ("SelmerProblem",),
            ("KummerSpace", "LocalizationCollection", "LocalConditionCollection"),
        ),
        output_type="SelmerKernel | SelmerGroup",
    ),
    _spec(
        "arithmetic.dual_selmer",
        "Cartier-dual Selmer problems",
        (
            "constructed primal SelmerProblem and M^vee(1)",
            "one certified perfect local Tate/Hilbert pairing per declared place",
            "supplied or exactly constructed orthogonal dual local conditions",
        ),
        (
            "checks every pairing is nondegenerate before forming orthogonal conditions",
            "recomputes every orthogonal complement over the prime field",
            "returns the exact dual Selmer kernel with the same completeness gates",
        ),
        "pairing rank checks, orthogonal nullspaces, and one Selmer kernel computation",
        "arbogast.arithmetic.DualSelmerCertificate",
        "dual_selmer(primal_problem, pairings=pairings, cartier_dual=dual)",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            FIELD_MISMATCH,
            PAIRING_VERIFICATION,
            INCOMPLETE_EVIDENCE,
            ARITHMETIC_VERIFICATION,
        ),
        input_types=(
            "SelmerProblem",
            "SelmerProblem | PairingCollection | None",
            "PairingCollection | None",
            "CartierDual",
        ),
        input_bundles=(
            ("SelmerProblem", "PairingCollection", "CartierDual"),
            ("SelmerProblem", "SelmerProblem", "PairingCollection", "CartierDual"),
        ),
        output_type="DualSelmerResult",
    ),
    _spec(
        "arithmetic.aim",
        "Kummer and cocycle aiming",
        (
            "exact finite prime-field system or certified global-to-local map",
            "target vector of matching codomain dimension",
        ),
        (
            "returns an affine family with a checked representative and full homogeneous kernel",
            "or returns a literal checked left-nullspace separator for an inconsistent target",
            "never converts failed search into an obstruction",
        ),
        "one exact linear solve with kernel and separating-witness replay",
        "arbogast.arithmetic.AimCertificate",
        "aim(matrix, target)",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH, ARITHMETIC_VERIFICATION),
        input_types=("Matrix | SelmerProblem | LocalizationMap", "Vector | None"),
        input_bundles=(
            ("Matrix", "Vector"),
            ("SelmerProblem", "Vector"),
            ("LocalizationMap", "Vector"),
        ),
        output_type="AffineFamily | LeftNullspaceObstruction",
    ),
    _spec(
        "arithmetic.unique",
        "Kummer and cocycle aiming",
        ("certified aiming result, or an exact finite aiming system and target",),
        (
            "returns true exactly when a consistent aiming family has zero-dimensional kernel",
            "returns false for a literal obstruction and never hides inconsistency",
        ),
        "aim verification or one exact aiming computation",
        None,
        "unique(aim(matrix, target))",
        failure_modes=(INVALID_INPUT, DIMENSION_MISMATCH, ARITHMETIC_VERIFICATION),
        input_types=("AimResult | Matrix", "Vector | None"),
        input_bundles=(("AimResult",), ("Matrix", "Vector")),
        output_type="bool",
    ),
    _spec(
        "arithmetic.elementary_descent",
        "bounded elementary Kummer descent",
        (
            "KummerDescentProblem with exact finite local/Kummer conditions",
            "explicit realization witness or a finite linear realization boundary",
        ),
        (
            "returns Realized only with a checked global realization witness",
            "returns Obstructed only with a literal checked separating certificate",
            "otherwise returns Unknown with a reason",
            "never promotes local solubility, failed search, or timeout to a global conclusion",
        ),
        "one exact aiming computation plus explicit realization-boundary replay",
        "arbogast.arithmetic.DescentCertificate",
        "elementary_descent(KummerDescentProblem(system, target))",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            INCOMPLETE_EVIDENCE,
            ARITHMETIC_UNSUPPORTED,
            ARITHMETIC_VERIFICATION,
            BACKEND_BUDGET,
        ),
        input_types=("KummerDescentProblem",),
        output_type="Realized | Obstructed | Unknown",
    ),
)

BUILTIN_OPERATION_SPECS += ARITHMETIC_OPERATION_SPECS


DEFORMATION_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "deform.deformation_problem",
        "finite exact deformation problems",
        (
            "a pinned three-term prime-field deformation complex or presentation",
            "an optional exact degree-zero framing with matching field and ambient dimension",
        ),
        (
            "returns the canonical pinned deformation problem and its effective complex",
            "replays d1*d0 = 0 and every supplied framing restriction exactly",
            "does not infer a geometric cotangent complex from an arbitrary object",
        ),
        "finite matrix validation and, when framed, one exact kernel restriction",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "deformation_problem(complex_)",
        failure_modes=(
            INVALID_INPUT,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_UNSUPPORTED,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
            "Framing | None",
        ),
        input_bundles=(
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
            ),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "Framing",
            ),
        ),
        output_type="DeformationProblem",
    ),
    _spec(
        "deform.gauge",
        "infinitesimal deformation gauge",
        ("a verified finite deformation complex, presentation, or problem",),
        (
            "returns exactly T0 = ker(d0) in the effective complex",
            "binds the gauge space to the pinned problem and complex identities",
        ),
        "one exact prime-field nullspace computation",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "gauge(problem)",
        failure_modes=(INVALID_INPUT, DEFORMATION_PRESENTATION, DEFORMATION_VERIFICATION),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
        ),
        output_type="GaugeSpace",
    ),
    _spec(
        "deform.tangent",
        "first-order deformation space",
        ("a verified finite deformation complex, presentation, or problem",),
        (
            "returns exactly T1 = ker(d1)/im(d0)",
            "retains canonical quotient representatives and the effective problem binding",
        ),
        "exact kernel, image, and quotient-space computations",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "tangent(problem)",
        failure_modes=(INVALID_INPUT, DEFORMATION_PRESENTATION, DEFORMATION_VERIFICATION),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
        ),
        output_type="TangentSpace",
    ),
    _spec(
        "deform.obstructions",
        "finite deformation obstruction space",
        ("a verified finite deformation complex, presentation, or problem",),
        (
            "returns exactly T2 = C2/im(d1)",
            "does not claim that a zero obstruction space constructs a geometric lift",
        ),
        "one exact image and quotient-space computation",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "obstructions(problem)",
        failure_modes=(INVALID_INPUT, DEFORMATION_PRESENTATION, DEFORMATION_VERIFICATION),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
        ),
        output_type="ObstructionSpace",
    ),
    _spec(
        "deform.frame",
        "exact deformation framing",
        (
            "a verified finite deformation complex, presentation, or unframed problem",
            "a degree-zero constraint matrix over the same prime field",
        ),
        (
            "restricts degree-zero gauges to the exact kernel of the framing constraints",
            "preserves the pinned presentation and independently replays the effective complex",
        ),
        "one nullspace and one differential restriction",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "frame(problem, framing)",
        failure_modes=(
            INVALID_INPUT,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
            "Framing",
        ),
        output_type="DeformationProblem",
    ),
    _spec(
        "deform.equivariant",
        "finite equivariant deformation problems",
        (
            "a verified finite deformation problem",
            "a fully enumerated finite-group action by chain automorphisms in degrees 0 through 2",
        ),
        (
            "checks the group law, identities, inverses, and chain-map equations exactly",
            "binds the checked action to the effective deformation complex",
        ),
        "complete finite action-table and chain-map replay",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "equivariant(problem, action)",
        failure_modes=(
            INVALID_INPUT,
            INVALID_GROUP,
            INVALID_ACTION,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
            "DeformationAction",
        ),
        output_type="EquivariantDeformation",
    ),
    _spec(
        "deform.invariant_deformations",
        "invariant deformation subcomplexes",
        ("an exactly verified equivariant deformation problem",),
        (
            "restricts every degree and differential to the exact invariant subspaces",
            "returns a pinned invariant subcomplex deformation problem",
            "does not silently identify H(C^G) with H(C)^G",
        ),
        "one invariant-space computation in each degree and two exact restrictions",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "invariant_deformations(equivariant_problem)",
        failure_modes=(
            INVALID_INPUT,
            INVALID_ACTION,
            DEFORMATION_PRESENTATION,
            DEFORMATION_VERIFICATION,
        ),
        input_types=("EquivariantDeformation",),
        output_type="InvariantDeformations",
    ),
    _spec(
        "deform.equivariant_decomposition",
        "supplied-projector equivariant decomposition",
        (
            "an exactly verified equivariant deformation problem",
            "a supplied labeled family of degreewise chain projectors, or no projectors",
        ),
        (
            (
                "certifies idempotence, action commutation, chain compatibility, orthogonality, "
                "and completeness"
            ),
            "returns typed UnsupportedDeformation when automatic projector discovery is requested",
            "does not infer a semisimple decomposition in modular characteristic",
        ),
        "complete finite projector replay in every degree",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "equivariant_decomposition(equivariant_problem, projectors)",
        failure_modes=(
            INVALID_INPUT,
            INVALID_ACTION,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            NONSEMISIMPLE,
            DEFORMATION_UNSUPPORTED,
            DEFORMATION_VERIFICATION,
        ),
        input_types=("EquivariantDeformation", "ProjectorMapping | None"),
        input_bundles=(
            ("EquivariantDeformation",),
            ("EquivariantDeformation", "ProjectorMapping"),
        ),
        output_type="EquivariantDecomposition | UnsupportedDeformation",
    ),
    _spec(
        "deform.lift",
        "finite Artin-ring lifting",
        (
            (
                "a verified LiftDatum, or a finite deformation problem with a pinned small "
                "Artin-ring extension"
            ),
            "an explicit object-specific target before any correction equation is solved",
            (
                "a one-dimensional square-zero kernel for the default d1/d0 chart, or explicit "
                "correction and gauge matrices for every higher-dimensional kernel"
            ),
        ),
        (
            "returns the complete affine lift family modulo exact gauge when consistent",
            "returns a literal left-nullspace separator when obstructed",
            (
                "returns UnsupportedDeformation rather than inventing an object-specific target "
                "from a complex and extension alone"
            ),
        ),
        "one exact linear solve, kernel, image, and quotient computation",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "lift(problem, extension, target=target)",
        failure_modes=(
            INVALID_INPUT,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_UNSUPPORTED,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            (
                "LiftDatum | DeformationComplex | DeformationPresentation | "
                "DeformationProblem | InvariantDeformations"
            ),
            "SmallExtension | None",
            "Vector | None",
            "Vector | None",
            "DenseMatrix | None",
            "DenseMatrix | None",
            "str | None",
        ),
        input_bundles=(
            ("LiftDatum",),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
            ),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
                "Vector",
            ),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
                "Vector",
                "Vector",
                "DenseMatrix",
                "DenseMatrix",
                "str",
            ),
        ),
        output_type="LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",
    ),
    _spec(
        "deform.unique_lift",
        "uniqueness modulo deformation gauge",
        (
            "a verified lift datum, exact lift outcome, or explicit problem/extension lift call",
            (
                "a one-dimensional square-zero kernel for the default chart, or explicit "
                "correction and gauge matrices for every higher-dimensional kernel"
            ),
        ),
        (
            "returns UniqueLift exactly when the lift-family quotient by gauge has dimension zero",
            "returns two gauge-inequivalent representatives when uniqueness fails",
            "preserves obstructed, unknown, and unsupported outcomes without strengthening them",
        ),
        "one lift computation or exact quotient-dimension and witness replay",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "unique_lift(problem, extension, target=target)",
        failure_modes=(
            INVALID_INPUT,
            FIELD_MISMATCH,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_UNSUPPORTED,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            (
                "LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | "
                "UnsupportedDeformation | DeformationComplex | DeformationPresentation | "
                "DeformationProblem | InvariantDeformations"
            ),
            "SmallExtension | None",
            "Vector | None",
            "Vector | None",
            "DenseMatrix | None",
            "DenseMatrix | None",
            "str | None",
        ),
        input_bundles=(
            ("LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
            ),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
                "Vector",
            ),
            (
                (
                    "DeformationComplex | DeformationPresentation | DeformationProblem | "
                    "InvariantDeformations"
                ),
                "SmallExtension",
                "Vector",
                "Vector",
                "DenseMatrix",
                "DenseMatrix",
                "str",
            ),
        ),
        output_type=(
            "UniqueLift | NonUniqueLift | LiftObstructed | LiftUnknown | UnsupportedDeformation"
        ),
    ),
    _spec(
        "deform.fixed_lift",
        "contracting fixed lifts",
        (
            "a verified lift datum or exact lift outcome, including typed unsupported outcomes",
            "a bound affine lift-family endomorphism",
            "a checked contraction certificate or explicit finite exponent",
        ),
        (
            "returns an explicit fixed representative only after exact contraction replay",
            (
                "preserves obstruction and unsupported outcomes and returns LiftUnknown when "
                "contraction data is absent"
            ),
            "does not claim a general canonical-lift theorem",
        ),
        "one lift solve plus bounded exact affine iteration and nilpotence replay",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "fixed_lift(family, endomorphism, contraction=certificate)",
        failure_modes=(
            INVALID_INPUT,
            DIMENSION_MISMATCH,
            DEFORMATION_PRESENTATION,
            DEFORMATION_CONTRACTION,
            DEFORMATION_UNSUPPORTED,
            DEFORMATION_VERIFICATION,
        ),
        input_types=(
            "LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",
            "LiftEndomorphism | None",
            "ContractionCertificate | int | None",
        ),
        input_bundles=(
            ("LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",),
            (
                "LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",
                "LiftEndomorphism",
            ),
            (
                "LiftDatum | LiftFamily | LiftObstructed | LiftUnknown | UnsupportedDeformation",
                "LiftEndomorphism",
                "ContractionCertificate | int",
            ),
        ),
        output_type="FixedLift | LiftObstructed | LiftUnknown | UnsupportedDeformation",
    ),
    _spec(
        "deform.rigid",
        "infinitesimal deformation rigidity",
        ("a verified finite deformation complex, presentation, or problem",),
        (
            "returns Rigid exactly when the pinned effective tangent space is zero",
            "otherwise returns NonRigid with a literal nonzero tangent-class witness",
            "makes no formal or geometric rigidity claim beyond this finite tangent criterion",
        ),
        "one exact tangent-space computation and optional witness selection",
        "arbogast.deform.DeformationReceipt nested in arbogast.cert.VerificationCertificate",
        "rigid(problem)",
        failure_modes=(INVALID_INPUT, DEFORMATION_PRESENTATION, DEFORMATION_VERIFICATION),
        input_types=(
            (
                "DeformationComplex | DeformationPresentation | DeformationProblem | "
                "InvariantDeformations"
            ),
        ),
        output_type="Rigid | NonRigid",
    ),
)

BUILTIN_OPERATION_SPECS += DEFORMATION_OPERATION_SPECS


DEFORMATION_VERIFICATION_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "deform.verify_receipt",
        "portable finite deformation receipt replay",
        ("an independently versioned DeformationReceipt with dependency-closed evidence",),
        (
            "replays the complete advertised finite witness using exact prime-field arithmetic",
            "rejects backend-local handles and preserves assumptions, completeness, and trust axes",
        ),
        "bounded by the explicit finite dimensions and dependency receipt closure",
        None,
        "verify_deformation_receipt(receipt)",
        failure_modes=(INVALID_INPUT, DEFORMATION_VERIFICATION),
        input_types=("DeformationReceipt",),
        output_type="tuple[str, ...]",
    ),
)

BUILTIN_OPERATION_SPECS += DEFORMATION_VERIFICATION_OPERATION_SPECS


NUMERIC_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "numeric.continue_path",
        "validated bounded path continuation",
        (
            "an exact one-parameter polynomial family, start point, and piecewise-dyadic path",
            "an explicit dependency-closed contraction tube for every path segment",
        ),
        (
            "returns only the endpoint enclosure certified by the supplied tube",
            "keeps the conclusion NUMERICAL and never promotes a tube to an exact value",
            "returns a typed non-conclusion when the tube or supported family is absent",
        ),
        "exact interval replay over every supplied bounded tube step",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "continue_path(family, point, path, tube=tube)",
        exact=False,
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=(
            "PolynomialFamily | PolynomialSystem",
            "NumericPoint",
            "ParameterPath",
            "ContinuationTube | None",
        ),
        input_bundles=(
            ("PolynomialFamily | PolynomialSystem", "NumericPoint", "ParameterPath"),
            (
                "PolynomialFamily | PolynomialSystem",
                "NumericPoint",
                "ParameterPath",
                "ContinuationTube",
            ),
        ),
        output_type="ContinuationResult | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.condition_number",
        "certified local numerical conditioning",
        (
            "a square exact polynomial system and a numerical point bound to that system",
            "an exact inverse of the center Jacobian for a positive bound",
        ),
        (
            "returns a RealBall carrying the exact row-sum condition upper bound",
            "keeps the local conditioning conclusion NUMERICAL",
            "does not infer global stability from the displayed local bound",
        ),
        "one exact Jacobian evaluation, inverse replay, and row-sum bound",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "condition_number(system, point, inverse_jacobian=inverse)",
        exact=False,
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=("PolynomialSystem", "NumericPoint", "InverseJacobianMatrix | None"),
        input_bundles=(
            ("PolynomialSystem", "NumericPoint"),
            ("PolynomialSystem", "NumericPoint", "InverseJacobianMatrix"),
        ),
        output_type="ConditionBound | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.branch_cycles",
        "validated quadratic-cover branch-cycle recovery",
        (
            "a certified monic quadratic NumericalCover with complete finite branch trackings",
            "the exact infinity convention and inverse-product cycle when parity requires it",
        ),
        (
            "returns a proof-bearing NielsenTuple subtype with exact concrete permutations",
            "checks generation and the product-one relation",
            (
                "promotes only the unambiguous discrete tuple to EXACT after complete separated "
                "continuation replay; the upstream cover and trackings remain NUMERICAL"
            ),
        ),
        "complete replay of every sheet tube and exact finite permutation check",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "branch_cycles(cover)",
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_VERIFICATION,
        ),
        input_types=("NumericalCover",),
        output_type="BranchCycleTuple | NumericUnknown",
    ),
    _spec(
        "numeric.bind_vertex",
        "validated numerical-to-Nielsen vertex binding",
        (
            "a complete NumericalCover and a computed-complete exact NielsenClass",
            "a literal match between the tracked permutations and one canonical vertex",
        ),
        (
            "returns the canonical NielsenVertex matching the recovered branch cycles",
            "embeds and replays the complete exact Nielsen certificate as a dependency",
            (
                "promotes the literal complete vertex binding to EXACT only after the exact "
                "BranchCycleTuple boundary has closed"
            ),
        ),
        "complete Nielsen certificate replay plus one finite canonicalization lookup",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "bind_vertex(cover, nielsen_class)",
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=("NumericalCover", "NielsenClass", "NielsenTuple | int | None"),
        input_bundles=(
            ("NumericalCover", "NielsenClass"),
            ("NumericalCover", "NielsenClass", "NielsenTuple | int"),
        ),
        output_type="NielsenVertex | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.braid_continue",
        "typed cover braid-continuation boundary",
        (
            "a certified NumericalCover and an exact BraidWord",
            ("an explicit QuadraticB2Homotopy for the normalized degree-two generator or inverse"),
        ),
        (
            "returns the input NumericalCover unchanged for the identity word",
            (
                "returns an exact BraidContinuationResult for the witnessed normalized "
                "sigma_0 generator or inverse"
            ),
            "returns NumericUnknown or UnsupportedNumeric outside that exact bounded slice",
            "rejects a witness bound to a different cover, word, endpoint, or action",
            "never treats local sheet-loop evidence as a cover-coefficient homotopy",
        ),
        "constant identity replay or exact fixed-degree polynomial identity replay",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "braid_continue(cover, word)",
        exact=False,
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=(
            "NumericalCover",
            "BraidWord",
            "BraidContinuationWitness | QuadraticB2Homotopy | None",
        ),
        input_bundles=(
            ("NumericalCover", "BraidWord"),
            ("NumericalCover", "BraidWord", "BraidContinuationWitness"),
            ("NumericalCover", "BraidWord", "QuadraticB2Homotopy"),
        ),
        output_type=(
            "NumericalCover | BraidContinuationResult | NumericUnknown | UnsupportedNumeric"
        ),
    ),
    _spec(
        "numeric.recognize",
        "bounded real algebraic recognition",
        (
            "a real-centered exact dyadic ball",
            "automatic bounds of degree at most 2 and coefficient height at most 16",
        ),
        (
            "exhausts the declared finite search and returns one isolated AlgebraicCandidate",
            "keeps the compatible relation NUMERICAL rather than asserting an exact value",
            (
                "returns a typed unknown for zero or multiple matches and unsupported for "
                "larger bounds"
            ),
        ),
        "finite exhaustive degree-one/two coefficient search with exact Sturm replay",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "recognize(ball, RecognitionBounds(2, 16))",
        exact=False,
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=("ComplexBall | RealBall", "RecognitionBounds | None"),
        input_bundles=(
            ("ComplexBall | RealBall",),
            ("ComplexBall | RealBall", "RecognitionBounds"),
        ),
        output_type="AlgebraicCandidate | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.exactify",
        "bounded univariate algebraic exactification",
        (
            "a univariate NumericPoint bound to exact real dyadic polynomial equations",
            "a uniquely isolated AlgebraicCandidate, supplied or found within supported bounds",
            (
                "candidate and bounds are mutually exclusive: supply the candidate directly "
                "or omit it to request bounded recognition"
            ),
        ),
        (
            "proves exact divisibility of every system equation by the candidate polynomial",
            "returns ExactificationResult only after exact substitution replay",
            "keeps failed recognition or divisibility as a typed non-conclusion",
        ),
        "bounded recognition followed by exact univariate polynomial divisions",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "exactify(point, candidate=candidate)",
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=(
            "NumericPoint",
            "AlgebraicCandidate | None",
            "RecognitionBounds | None",
        ),
        input_bundles=(
            ("NumericPoint",),
            ("NumericPoint", "AlgebraicCandidate"),
            ("NumericPoint", "RecognitionBounds"),
        ),
        output_type="ExactificationResult | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.projection_degree",
        "scoped exact projection-degree witnesses",
        (
            "an exact polynomial, polynomial system, or bounded ExactCover and declared functions",
            "either a complete square-free regular-fiber factorization or the supported exact "
            "univariate generic witness",
            "regular-fiber and generic witnesses are mutually exclusive",
        ),
        (
            "returns RegularFiberDegree only for the one displayed regular fiber",
            "returns DegreeResult only for the narrowly bound exact univariate polynomial map",
            "never promotes a regular-fiber count or unbound functions to generic degree",
        ),
        "exact univariate factorization/divisibility and leading-term witness replay",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "projection_degree(polynomial, (polynomial,))",
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=(
            "ExactPolynomial | PolynomialSystem | ExactCover",
            "ProjectionFunctionSequence",
            "RegularFiberWitness | None",
            "GenericDegreeWitness | None",
        ),
        input_bundles=(
            ("ExactPolynomial | PolynomialSystem | ExactCover", "ProjectionFunctionSequence"),
            (
                "ExactPolynomial | PolynomialSystem | ExactCover",
                "ProjectionFunctionSequence",
                "RegularFiberWitness",
            ),
            (
                "ExactPolynomial | PolynomialSystem | ExactCover",
                "ProjectionFunctionSequence",
                "GenericDegreeWitness",
            ),
        ),
        output_type="DegreeResult | RegularFiberDegree | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.weighted_braid_plan",
        "exact minimum-cost planning in a finite braid action",
        (
            (
                "a complete finite BraidAction, source and target vertices, and exact "
                "nonnegative costs"
            ),
            "one cost for each forward and inverse declared generator",
        ),
        (
            "returns a realizing exact BraidWord and vertex path",
            "proves global optimality inside the supplied finite action by a distance potential",
            "does not claim an intrinsic geometric shortest path or perform numerical continuation",
        ),
        "Dijkstra over the bounded finite action plus complete edge-potential replay",
        "arbogast.numeric.NumericReceipt nested in arbogast.cert.VerificationCertificate",
        "weighted_braid_plan(action, source, target, costs)",
        failure_modes=(
            INVALID_INPUT,
            NUMERIC_PRESENTATION,
            NUMERIC_NONCONCLUSION,
            NUMERIC_UNSUPPORTED,
            NUMERIC_VERIFICATION,
        ),
        input_types=(
            "BraidAction",
            "NielsenTuple | int",
            "NielsenTuple | int",
            "GeneratorCostMap",
        ),
        output_type="WeightedBraidPlan | NumericUnknown | UnsupportedNumeric",
    ),
    _spec(
        "numeric.verify_receipt",
        "portable numeric receipt replay",
        ("an independently versioned NumericReceipt with dependency-closed evidence",),
        (
            "replays exact dyadic inequalities and finite witnesses without a numerical backend",
            "preserves NUMERICAL, EXACT, CONDITIONAL, and UNKNOWN conclusion boundaries",
            "rejects backend-local handles and altered supporting certificates",
        ),
        "bounded by the canonical payload and embedded finite dependency closure",
        None,
        "verify_numeric_receipt(receipt)",
        failure_modes=(INVALID_INPUT, NUMERIC_PRESENTATION, NUMERIC_VERIFICATION),
        input_types=("NumericReceipt",),
        output_type="tuple[str, ...]",
    ),
)

BUILTIN_OPERATION_SPECS += NUMERIC_OPERATION_SPECS


PADIC_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "padic.frobenius",
        "bounded finite-precision semilinear Frobenius",
        (
            "a canonical finite-precision p-adic module",
            "an explicit semilinear matrix, field embedding, convention, and period",
        ),
        (
            "returns a Certified[FrobeniusOperator] only after exact finite replay",
            "returns Unknown rather than discovering a missing Frobenius datum",
            "keeps arithmetic and geometric Frobenius conventions distinct",
        ),
        "finite matrix arithmetic through the declared semilinear period",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "frobenius(module, datum=datum)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_NONCONCLUSION, PADIC_VERIFICATION),
        input_types=("PAdicModule", "FrobeniusOperator | FrobeniusDatum | None"),
        input_bundles=(
            ("PAdicModule",),
            ("PAdicModule", "FrobeniusOperator"),
            ("PAdicModule", "FrobeniusDatum"),
        ),
        output_type="Certified[FrobeniusOperator] | Unknown",
    ),
    _spec(
        "padic.slopes",
        "exact finite-precision Newton slopes",
        (
            "a verified FrobeniusOperator with its convention and linearized period",
            "optional saturated projectors bound to that exact operator",
        ),
        (
            "returns a Certified[SlopeDecomposition] when every polygon vertex is determined",
            "keeps Newton multiplicities distinct from supplied stable direct summands",
            "returns Unknown for an ambiguous finite-precision polygon",
        ),
        "Newton polygon replay plus optional exact projector identities",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "slopes(operator, projectors=projectors)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_NONCONCLUSION, PADIC_VERIFICATION),
        input_types=("FrobeniusOperator", "SlopeProjectorSequence | None"),
        input_bundles=(
            ("FrobeniusOperator",),
            ("FrobeniusOperator", "SlopeProjectorSequence"),
        ),
        output_type="Certified[SlopeDecomposition] | Unknown",
    ),
    _spec(
        "padic.ordinary_part",
        "certified slope-zero direct summand",
        (
            "a verified Frobenius operator or slope decomposition",
            "an exact saturated slope-zero projector when the decomposition does not contain one",
        ),
        (
            "returns only a Certified[SlopeProjector] of the full slope-zero multiplicity",
            "does not turn Newton multiplicity data alone into a p-adic submodule",
            "returns Unknown when the required projector is absent or the slope is ambiguous",
        ),
        "exact idempotence, stability, saturation, and slope replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "ordinary_part(decomposition, projector=projector)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_NONCONCLUSION, PADIC_VERIFICATION),
        input_types=(
            "FrobeniusOperator | SlopeDecomposition",
            "SlopeProjector | None",
        ),
        input_bundles=(
            ("FrobeniusOperator",),
            ("FrobeniusOperator", "SlopeProjector"),
            ("SlopeDecomposition",),
            ("SlopeDecomposition", "SlopeProjector"),
        ),
        output_type="Certified[SlopeProjector] | Unknown",
    ),
    _spec(
        "padic.inertia_action",
        "exact representation of a declared finite group presentation",
        (
            "an arithmetic source with a canonical identity",
            (
                "a fully enumerated finite group presentation, a declared group-theoretic series "
                "satisfying the listed tame/wild quotient identities, and a matrix action table"
            ),
            "an optional residue characteristic agreeing with the quotient",
        ),
        (
            "returns a Certified[InertiaRepresentation] after exhaustive finite group-law replay",
            "checks the Frobenius-inertia relation only when its exact datum is supplied",
            (
                "records arithmetic_origin_claimed=False and "
                "arithmetic_lower_numbering_claimed=False: no local-extension or valuation "
                "origin, and no complete lower-numbering theorem, is asserted"
            ),
            "does not claim the full continuous inertia or decomposition-group action",
        ),
        "quadratic in the finite quotient order times bounded matrix multiplication",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "inertia_action(source, p, datum=datum)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_NONCONCLUSION, PADIC_VERIFICATION),
        input_types=(
            "PAdicArithmeticObject",
            "int | None",
            "InertiaRepresentation | FiniteInertiaDatum | None",
        ),
        input_bundles=(
            ("PAdicArithmeticObject",),
            ("PAdicArithmeticObject", "int"),
            ("PAdicArithmeticObject", "InertiaRepresentation"),
            ("PAdicArithmeticObject", "FiniteInertiaDatum"),
            ("PAdicArithmeticObject", "int", "InertiaRepresentation"),
            ("PAdicArithmeticObject", "int", "FiniteInertiaDatum"),
        ),
        output_type="Certified[InertiaRepresentation] | Unknown",
    ),
    _spec(
        "padic.good_reduction",
        "bounded tame good reduction of a displayed three-point model",
        (
            "a strictly verified ThreePointCover and exact prime",
            "the displayed normalized model, with no implicit coordinate change or extension",
        ),
        (
            "certifies degree preservation and separated tame marked ramification",
            "returns Unknown when this sufficient displayed-model test fails",
            "never promotes failure to nonexistence of another good model",
        ),
        "bounded exact polynomial reduction and finite-field factor replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "good_reduction(cover, prime)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_NONCONCLUSION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=("ThreePointCover", "int", "GoodReductionWitness | None"),
        input_bundles=(
            ("ThreePointCover", "int"),
            ("ThreePointCover", "int", "GoodReductionWitness"),
        ),
        output_type="Certified[GoodReduction] | Unknown | Unsupported",
    ),
    _spec(
        "padic.semistable_reduction",
        "bounded one-component semistable reduction",
        (
            "a ThreePointCover with its prime or a Certified[GoodReduction]",
            "the tame one-component good-reduction lane or a bound exact witness",
        ),
        (
            "returns a Certified[SemistableReduction] with complete markings and incidence",
            "does not advertise automatic blow-ups, extensions, or non-good discovery",
            "returns Unsupported outside the one-component bounded lane",
        ),
        "exact replay of the complete marked one-component model",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "semistable_reduction(good)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=(
            "ThreePointCover | Certified[GoodReduction]",
            "int | None",
            "SemistableReductionWitness | None",
        ),
        input_bundles=(
            ("ThreePointCover", "int"),
            ("ThreePointCover", "int", "SemistableReductionWitness"),
            ("Certified[GoodReduction]",),
            ("Certified[GoodReduction]", "SemistableReductionWitness"),
        ),
        output_type="Certified[SemistableReduction] | Unsupported",
    ),
    _spec(
        "padic.stable_reduction",
        "bounded already-stable marked reduction",
        (
            "a ThreePointCover with its prime or a Certified[SemistableReduction]",
            "strictly positive marked stability indices for every component",
        ),
        (
            "returns a Certified[StableReduction] only for the supported already-stable model",
            "records that no unproved component contraction occurred",
            "returns Unsupported outside automatic one-component stable replay",
        ),
        "exact component, marking, node, and stability-inequality replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "stable_reduction(semistable)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=(
            "ThreePointCover | Certified[SemistableReduction]",
            "int | None",
            "StableReductionWitness | None",
        ),
        input_bundles=(
            ("ThreePointCover", "int"),
            ("ThreePointCover", "int", "StableReductionWitness"),
            ("Certified[SemistableReduction]",),
            ("Certified[SemistableReduction]", "StableReductionWitness"),
        ),
        output_type="Certified[StableReduction] | Unsupported",
    ),
    _spec(
        "padic.deformation_datum",
        "bounded Wewers deformation-datum boundary",
        (
            "a Certified[StableReduction]",
            "an explicit group action, differential extraction, and theorem-profile witness",
        ),
        (
            "keeps internal differential identities distinct from geometric origin",
            (
                "returns Unknown when extraction data are absent and Unsupported for the "
                "current stable profile"
            ),
            "certifies a DeformationDatum only when every origin and component relation replays",
        ),
        "finite-field differential, character, signature, and origin replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "deformation_datum(stable, witness=witness)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_NONCONCLUSION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=("Certified[StableReduction]", "DeformationDatumWitness | None"),
        input_bundles=(
            ("Certified[StableReduction]",),
            ("Certified[StableReduction]", "DeformationDatumWitness"),
        ),
        output_type="Certified[DeformationDatum] | Unknown | Unsupported",
    ),
    _spec(
        "padic.lift_set",
        "exact finite lift enumeration in one pinned chart",
        (
            "a DeformationDatum or Certified[DeformationDatum]",
            "one explicit finite chart and its complete exact root-exhaustion witness",
        ),
        (
            "returns a Certified[LiftSet] complete only inside the pinned chart",
            "deduplicates only literal labeled models, not unproved isomorphism classes",
            "returns a typed non-conclusion when the chart or exhaustion is absent or over budget",
        ),
        "exhaustive finite-field root replay within the declared work bound",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "lift_set(datum, chart=chart, witness=witness)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_NONCONCLUSION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=(
            "DeformationDatum | Certified[DeformationDatum]",
            "LiftChart | None",
            "LiftEnumerationWitness | None",
        ),
        input_bundles=(
            ("DeformationDatum",),
            ("Certified[DeformationDatum]",),
            ("DeformationDatum", "LiftChart", "LiftEnumerationWitness"),
            ("Certified[DeformationDatum]", "LiftChart", "LiftEnumerationWitness"),
        ),
        output_type="Certified[LiftSet] | Unknown | Unsupported",
    ),
    _spec(
        "padic.lift_galois_action",
        "exact arithmetic Galois action on a finite lift set",
        (
            "a Certified[LiftSet] and computed-complete FiniteGaloisQuotient",
            "one exact transport permutation for every quotient element",
        ),
        (
            (
                "returns a Certified[LiftGaloisAction] in 0.5 only for a computed-complete "
                "trivial quotient with an explicit identity model-coordinate transport for "
                "every lift"
            ),
            "keeps a declared set permutation without model maps as Unknown",
            (
                "returns Unknown for incomplete quotient evidence and Unsupported for a "
                "nontrivial complete quotient"
            ),
        ),
        "quadratic in the finite quotient order times the lift-set cardinality",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "lift_galois_action(lifts, quotient, witnesses=witnesses)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_NONCONCLUSION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=(
            "Certified[LiftSet]",
            "FiniteGaloisQuotient",
            "LiftTransportWitnessSequence",
        ),
        input_bundles=(
            ("Certified[LiftSet]", "FiniteGaloisQuotient", "LiftTransportWitnessSequence"),
        ),
        output_type="Certified[LiftGaloisAction] | Unknown | Unsupported",
    ),
    _spec(
        "padic.fixed_lifts",
        "exact fixed subset of a finite lift action",
        ("a complete FiniteLiftAction or Certified[LiftGaloisAction]",),
        (
            "returns a Certified[FixedLiftSet] by exhaustive finite permutation replay",
            "marks every fixed class explicitly and makes no effective-descent claim",
        ),
        "linear in the complete action table and lift-set cardinality",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "fixed_lifts(action)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_VERIFICATION),
        input_types=("FiniteLiftAction | Certified[LiftGaloisAction]",),
        input_bundles=(("FiniteLiftAction",), ("Certified[LiftGaloisAction]",)),
        output_type="Certified[FixedLiftSet]",
    ),
    _spec(
        "padic.effective_descent",
        "rigid effective descent of one fixed lift",
        (
            "a Certified[FixedLiftSet] carrying an arithmetic lift action",
            (
                "trivial automorphisms, a complete cocycle, explicit equations, and two-sided "
                "base change"
            ),
        ),
        (
            (
                "returns a Certified[DescendedModel] containing the exact coefficient vector "
                "of one rigid pinned F_p chart model only after every descent identity replays"
            ),
            "does not identify a fixed lift or field-of-moduli point with a descended model",
            "does not claim a characteristic-zero or number-field cover",
            "returns Unknown when the rigid descent witness is absent",
        ),
        "complete finite cocycle and explicit two-sided substitution replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "effective_descent(fixed, witness=witness)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_NONCONCLUSION, PADIC_VERIFICATION),
        input_types=("Certified[FixedLiftSet]", "RigidDescentWitness | None"),
        input_bundles=(
            ("Certified[FixedLiftSet]",),
            ("Certified[FixedLiftSet]", "RigidDescentWitness"),
        ),
        output_type="Certified[DescendedModel] | Unknown",
    ),
    _spec(
        "padic.local_factorization_fragment",
        "exact displayed finite-field factorization fragment",
        (
            "a canonical source identity, exact prime, displayed mod-p polynomial, and unit",
            "a complete ordered factorization into verified finite-field factors",
        ),
        (
            "returns a Certified[LocalFactorizationFragment] after exact product replay",
            "certifies only the displayed polynomial factorization over the named finite field",
            "does not infer a reduction model, global cover, or omitted local factor",
        ),
        "bounded exact finite-field multiplication and irreducibility replay",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "local_factorization_fragment(source_id, prime, polynomial, unit, factors)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_VERIFICATION),
        input_types=(
            "str",
            "int",
            "IntegerCoefficientSequence",
            "int",
            "FiniteFieldFactorSequence",
        ),
        input_bundles=(
            (
                "str",
                "int",
                "IntegerCoefficientSequence",
                "int",
                "FiniteFieldFactorSequence",
            ),
        ),
        output_type="Certified[LocalFactorizationFragment]",
    ),
    _spec(
        "padic.reduction_frontier",
        "typed bounded reduction frontier",
        (
            "a public M23 exact dataset or Certified[LocalFactorizationFragment]",
            "an exact prime matching the local fragment when one is supplied",
        ),
        (
            "returns Partial only with a certified local fragment and explicit proof obligations",
            (
                "returns Unsupported for the four-point M23 fixture, which has no pinned local "
                "equations"
            ),
            "never turns a bounded frontier into a global nonexistence conclusion",
        ),
        "finite receipt replay plus construction of a bounded obligation list",
        "arbogast.padic.PAdicReceipt nested in arbogast.cert.VerificationCertificate",
        "reduction_frontier(source, prime=prime)",
        failure_modes=(
            INVALID_INPUT,
            PADIC_PRESENTATION,
            PADIC_NONCONCLUSION,
            PADIC_UNSUPPORTED,
            PADIC_VERIFICATION,
        ),
        input_types=("M23ExactDataset | Certified[LocalFactorizationFragment]", "int"),
        input_bundles=(
            ("M23ExactDataset", "int"),
            ("Certified[LocalFactorizationFragment]", "int"),
        ),
        output_type="Partial | Unknown | Unsupported",
    ),
    _spec(
        "padic.verify_receipt",
        "portable finite-exact p-adic receipt replay",
        ("a PAdicReceipt from one of the two fixed verifier families",),
        (
            "replays strict canonical witnesses without a p-adic backend",
            "preserves Certified, Partial, Unknown, and Unsupported closure literally",
            "rejects altered dependencies, proof context, verifier family, or scope",
        ),
        "bounded by the canonical payload and dependency-closed finite evidence",
        None,
        "verify_receipt(receipt)",
        failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_VERIFICATION),
        input_types=("PAdicReceipt",),
        input_bundles=(("PAdicReceipt",),),
        output_type="tuple[str, ...]",
    ),
)

BUILTIN_OPERATION_SPECS += PADIC_OPERATION_SPECS


SEMANTIC_PROJECTION_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    *(
        _spec(
            f"galois.{projection}",
            "Galois arithmetic evidence projection",
            ("a substantial Galois result carrying a replayable central certificate",),
            (guarantee,),
            "linear in the bound finite receipt serialization",
            "arbogast.cert.VerificationCertificate",
            f"{implementation_name}(kummer_space)",
            failure_modes=(INVALID_INPUT, ARITHMETIC_VERIFICATION),
            input_types=(" | ".join(GALOIS_SEMANTIC_RESULT_TYPES),),
            output_type=output_type,
        )
        for projection, implementation_name, output_type, guarantee in (
            (
                "verification_certificate",
                "verification_certificate_for_result",
                "VerificationCertificate",
                "returns the central certificate bound to the exact result receipt",
            ),
            (
                "claim",
                "claim_for_result",
                "Claim",
                "returns the only mathematical claim justified by that exact receipt",
            ),
            (
                "claim_graph",
                "claim_graph_for_result",
                "ClaimGraph",
                "returns the result claim with its exact certificate dependencies",
            ),
        )
    ),
    *(
        _spec(
            f"deform.{projection}",
            "finite deformation evidence projection",
            ("a deformation result or receipt carrying replayable finite exact evidence",),
            (guarantee,),
            "linear in the bound deformation receipt serialization",
            "arbogast.cert.VerificationCertificate",
            f"{implementation_name}(deformation_result)",
            failure_modes=(INVALID_INPUT, DEFORMATION_VERIFICATION),
            input_types=(" | ".join(DEFORMATION_SEMANTIC_RESULT_TYPES),),
            output_type=output_type,
        )
        for projection, implementation_name, output_type, guarantee in (
            (
                "verification_certificate",
                "verification_certificate_for_result",
                "VerificationCertificate",
                "returns the central certificate bound to the exact deformation receipt",
            ),
            (
                "claim",
                "claim_for_result",
                "Claim",
                "returns only the mathematical claim justified by that exact finite receipt",
            ),
            (
                "claim_graph",
                "claim_graph_for_result",
                "ClaimGraph",
                "returns the result claim with its exact proving-certificate dependencies",
            ),
        )
    ),
    *(
        _spec(
            f"numeric.{projection}",
            "certified numeric-to-exact evidence projection",
            ("a numeric semantic result or receipt carrying replayable bounded evidence",),
            (guarantee,),
            "linear in the bounded numeric receipt and embedded finite dependencies",
            "arbogast.cert.VerificationCertificate",
            f"{implementation_name}(numeric_result)",
            failure_modes=(INVALID_INPUT, NUMERIC_PRESENTATION, NUMERIC_VERIFICATION),
            # Keep the agent-facing port compact.  The concrete result union is
            # enumerated once in ``NUMERIC_SEMANTIC_RESULT_TYPES`` for runtime
            # registration, while routing uses this stable semantic alias.
            input_types=("NumericSemanticResult | NumericReceipt",),
            output_type=output_type,
        )
        for projection, implementation_name, output_type, guarantee in (
            (
                "verification_certificate",
                "verification_certificate_for_result",
                "VerificationCertificate",
                (
                    "returns the central certificate bound to the exact receipt while preserving "
                    "NUMERICAL, EXACT, CONDITIONAL, or UNKNOWN status"
                ),
            ),
            (
                "claim",
                "claim_for_result",
                "Claim",
                "returns only the scoped claim justified by the numeric receipt",
            ),
            (
                "claim_graph",
                "claim_graph_for_result",
                "ClaimGraph",
                "returns the scoped result claim with its exact finite certificate dependencies",
            ),
        )
    ),
    *(
        _spec(
            f"padic.{projection}",
            "finite-exact p-adic evidence projection",
            ("a p-adic semantic result or receipt carrying replayable bounded evidence",),
            (guarantee,),
            "linear in the bounded p-adic receipt and embedded finite dependencies",
            "arbogast.cert.VerificationCertificate",
            f"{implementation_name}(padic_result)",
            failure_modes=(INVALID_INPUT, PADIC_PRESENTATION, PADIC_VERIFICATION),
            input_types=("PAdicSemanticResult | PAdicReceipt",),
            output_type=output_type,
        )
        for projection, implementation_name, output_type, guarantee in (
            (
                "verification_certificate",
                "verification_certificate",
                "VerificationCertificate",
                (
                    "returns the central certificate bound to one of exactly two fixed verifier "
                    "families while preserving closure, assumptions, and completeness"
                ),
            ),
            (
                "claim",
                "claim",
                "Claim",
                "returns only the scoped claim justified by the p-adic receipt",
            ),
            (
                "claim_graph",
                "claim_graph",
                "ClaimGraph",
                "returns the scoped result claim with every exact finite dependency",
            ),
        )
    ),
    *(
        _spec(
            f"arithmetic.{projection}",
            "certified arithmetic evidence projection",
            ("a substantial arithmetic result carrying one finite-linear receipt",),
            (guarantee,),
            "linear in the bound finite receipt serialization",
            "arbogast.cert.VerificationCertificate",
            f"{implementation_name}(selmer_result)",
            failure_modes=(INVALID_INPUT, ARITHMETIC_VERIFICATION),
            input_types=(" | ".join(ARITHMETIC_SEMANTIC_RESULT_TYPES),),
            output_type=output_type,
        )
        for projection, implementation_name, output_type, guarantee in (
            (
                "verification_certificate",
                "verification_certificate_for_result",
                "VerificationCertificate",
                "returns the central certificate bound to the exact arithmetic receipt",
            ),
            (
                "claim",
                "claim_for_result",
                "Claim",
                "returns the only mathematical claim justified by that exact receipt",
            ),
            (
                "claim_graph",
                "claim_graph_for_result",
                "ClaimGraph",
                "returns the result claim with its exact certificate dependencies",
            ),
        )
    ),
    _spec(
        "export.json",
        "stable semantic export",
        ("a central VerificationCertificate, Claim, or ClaimGraph",),
        ("returns deterministic canonical JSON without changing claim classification",),
        "linear in canonical semantic payload size",
        None,
        "export_json(claim_graph)",
        failure_modes=(INVALID_INPUT,),
        input_types=("VerificationCertificate | Claim | ClaimGraph",),
        output_type="JSONDocument",
    ),
)

BUILTIN_OPERATION_SPECS += SEMANTIC_PROJECTION_OPERATION_SPECS


FLEET_CERTIFICATE_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "fleet.plan_pari_arithmetic_task",
        "pinned external arithmetic fleet routing",
        (
            "central VerificationCertificate using arbogast.backends.pari.v1",
            "certificate witness pins one closed PARI operation and supported backend version",
        ),
        (
            "returns a TaskSpec requiring exactly the pinned PARI version and operation capability",
            "uses the distinct backends.pari.arithmetic.v1 trusted fleet task kind",
            "marks every success, failure, timeout, and scheduler outcome as non-closing",
        ),
        "constant-time canonical task construction; execution remains separately budgeted",
        None,
        "plan_pari_arithmetic_task(pari_certificate)",
        failure_modes=(INVALID_INPUT, ARITHMETIC_VERIFICATION, BACKEND_BUDGET),
        input_types=("VerificationCertificate",),
        output_type="PariArithmeticTask",
    ),
    _spec(
        "fleet.plan_python_certificate_replay_task",
        "portable certificate fleet routing",
        (
            "central VerificationCertificate naming an allowlisted portable Python verifier",
            "pinned external PARI certificates are explicitly excluded",
        ),
        (
            "returns a TaskSpec requiring Python certificate-verification capability",
            "uses the distinct cert.python.replay.v1 trusted fleet task kind",
            "the Python verifier decides receipt validity without scheduler-driven claim closure",
        ),
        "constant-time canonical task construction plus separately scheduled finite replay",
        None,
        "plan_python_certificate_replay_task(portable_certificate)",
        failure_modes=(INVALID_INPUT, ARITHMETIC_VERIFICATION),
        input_types=("VerificationCertificate",),
        output_type="PortableCertificateReplayTask",
    ),
)

BUILTIN_OPERATION_SPECS += FLEET_CERTIFICATE_OPERATION_SPECS


HURWITZ_AUXILIARY_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "hurwitz.plan_nielsen_class",
        "Hurwitz theory",
        (
            "finite concrete group and ordered explicit nonempty conjugacy classes",
            "positive shard count",
        ),
        (
            "returns deterministic disjoint shard specifications",
            "the plan exposes run, run_all, and fail-closed reduce methods",
            "planning alone makes no completeness claim",
        ),
        "finite group/context validation plus plan construction",
        None,
        "plan_nielsen_class(group, classes, shards=4)",
        failure_modes=(INVALID_INPUT, HURWITZ_UNSUPPORTED),
        input_types=("FiniteGroup", "ConjugacyClassVector", "int"),
        output_type="NielsenEnumerationPlan",
    ),
    _spec(
        "hurwitz.nielsen_tuple",
        "Hurwitz theory",
        (
            "finite concrete group",
            "entries in the ordered explicit classes that multiply to one and generate",
        ),
        (
            "returns one exactly validated Nielsen tuple",
            "does not assert that any surrounding representative list is exhaustive",
        ),
        "finite product, class-membership, and generation checks",
        None,
        "nielsen_tuple(group, entries, classes)",
        failure_modes=(INVALID_INPUT, HURWITZ_UNSUPPORTED, HURWITZ_VERIFICATION),
        input_types=("FiniteGroup", "Sequence[GroupElement]", "ConjugacyClassVector"),
        output_type="NielsenTuple",
    ),
    _spec(
        "hurwitz.verify_nielsen_certificate_payload",
        "portable Hurwitz verification",
        ("mapping purporting to be a v1 portable Nielsen enumeration payload",),
        (
            "returns true only after replaying the finite group law and exhaustive enumeration",
            "raises on malformed, tampered, or unsupported payloads rather than returning true",
        ),
        "cubic group-table validation plus exhaustive tuple enumeration",
        None,
        "verify_nielsen_certificate_payload(payload)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("Mapping[str, object]",),
        output_type="bool",
    ),
    _spec(
        "hurwitz.load_precomputed_nielsen_class",
        "imported Hurwitz data",
        (
            "strict typed JSON dataset",
            "pinned concrete group, ordered classes, and explicit element decoder when needed",
        ),
        (
            "validates every representative and all content fingerprints",
            "marks completeness as uncertified even if the file declares a cardinality",
            "never converts imported representatives into an enumeration certificate",
        ),
        "linear in file size plus exact representative validation",
        None,
        "load_precomputed_nielsen_class(path, group, classes)",
        failure_modes=(INVALID_INPUT, IO_OR_SCHEMA, IMPORTED_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("str | Path", "FiniteGroup", "ConjugacyClassVector"),
        output_type="ImportedNielsenDataset",
    ),
    _spec(
        "hurwitz.pure_braid_word",
        "braid groups and Hurwitz actions",
        ("zero-based strand indices satisfying 0 <= left < right",),
        ("returns the stated standard pure generator word A(left,right)",),
        "linear in right-left",
        None,
        "pure_braid_word(0, 2)",
        input_types=("int", "int"),
        output_type="BraidWord",
    ),
    _spec(
        "hurwitz.apply_braid_word_entries",
        "braid groups and Hurwitz actions",
        ("pinned concrete group context, entry sequence, and in-range braid word",),
        (
            "applies the pinned right Hurwitz convention exactly",
            "checks product preservation after every elementary move",
            "does not validate class membership or generation of the raw entry sequence",
        ),
        "linear in word length times finite-group operation cost",
        None,
        "apply_braid_word_entries(nielsen.context, nielsen[0].entries, word)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("ConcreteGroupContext", "Sequence[GroupElement]", "BraidWord"),
        output_type="tuple[GroupElement, ...]",
    ),
    _spec(
        "hurwitz.hurwitz_move",
        "braid groups and Hurwitz actions",
        ("validated Nielsen tuple and in-range adjacent braid-generator index",),
        (
            "applies one exact right Hurwitz generator or its inverse",
            "carries the ordered class vector through the adjacent swap",
        ),
        "one finite-group conjugation plus Nielsen validation",
        None,
        "hurwitz_move(nielsen[0], 0)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple", "int", "bool"),
        output_type="NielsenTuple",
    ),
    _spec(
        "hurwitz.apply_braid_word",
        "braid groups and Hurwitz actions",
        ("validated Nielsen tuple and braid word with in-range generators",),
        (
            "returns the exact iterated right Hurwitz action",
            "preserves product one and generation while carrying ordered classes",
        ),
        "linear in word length times Nielsen-tuple validation cost",
        None,
        "apply_braid_word(nielsen[0], word)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple", "BraidWord"),
        output_type="NielsenTuple",
    ),
    _spec(
        "hurwitz.braid_distance",
        "finite braid graphs",
        ("closed exact BraidAction and two vertices in one connected component",),
        (
            "returns a shortest unweighted path in the supplied finite braid graph",
            "the returned path verifies every named edge against that in-memory action",
        ),
        "breadth-first search in the finite braid graph",
        "arbogast.hurwitz.BraidPath (context-bound)",
        "braid_distance(action, source, target).verify()",
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE, HURWITZ_VERIFICATION),
        input_types=("BraidAction", "int | NielsenTuple", "int | NielsenTuple"),
        output_type="BraidPath",
    ),
    _spec(
        "hurwitz.weighted_braid_path",
        "finite weighted braid graphs",
        (
            "closed BraidAction and two vertices in one connected component",
            "finite nonnegative Python float cost for every traversed named edge",
        ),
        (
            "returns a minimum path under the supplied binary floating-point costs",
            "does not claim exact rational optimization or stability under alternate rounding",
        ),
        "Dijkstra search in the finite braid graph",
        None,
        "weighted_braid_path(action, source, target, costs)",
        exact=False,
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE),
        input_types=("BraidAction", "Vertex", "Vertex", "CostMapping | Callable"),
        output_type="BraidPath",
    ),
    _spec(
        "hurwitz.straight_real_transform",
        "real branch-cycle structures",
        ("pinned concrete group context and a product-one entry tuple",),
        (
            "returns the exact straight-bouquet complex-conjugation transform",
            "checks that the transformed tuple remains product one",
        ),
        "linear in tuple length times group-operation cost",
        None,
        "straight_real_transform(nielsen.context, nielsen[0].entries)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("ConcreteGroupContext", "tuple[GroupElement, ...]"),
        output_type="tuple[GroupElement, ...]",
    ),
    _spec(
        "hurwitz.signed_slot_transform",
        "explicit tuple transformations",
        ("one source index and inversion flag for each intended output slot",),
        (
            "returns a transform that permutes and optionally inverts explicit tuple slots",
            "validates arity and use of every source slot when the transform is applied",
        ),
        "linear in the number of slots",
        None,
        "signed_slot_transform(((1, True), (0, True)))",
        input_types=("Sequence[tuple[int, bool]]",),
        output_type="TupleTransform",
    ),
    _spec(
        "hurwitz.is_real_tuple",
        "real branch-cycle structures",
        ("validated Nielsen tuple and an element of its pinned concrete group",),
        (
            "returns whether the exact straight-bouquet real equations hold",
            "when requested, also requires the fiber conjugation to be an involution",
        ),
        "linear in tuple length times group-operation cost",
        None,
        "is_real_tuple(nielsen[0], nielsen.context.identity)",
        input_types=("NielsenTuple", "GroupElement", "bool"),
        output_type="bool",
    ),
    _spec(
        "hurwitz.is_totally_real",
        "real branch-cycle structures",
        ("validated Nielsen tuple",),
        (
            "returns whether the c=1 straight-bouquet criterion holds exactly",
            "does not infer coefficient-field reality",
        ),
        "is_real_tuple cost",
        None,
        "is_totally_real(nielsen[0])",
        input_types=("NielsenTuple",),
        output_type="bool",
    ),
    _spec(
        "hurwitz.real_witnesses",
        "real branch-cycle structures",
        ("finite Nielsen class and optional involution in its pinned concrete group",),
        (
            "returns at most one exact witness for each inner class satisfying the criterion",
            "each witness is verified against the live pinned group context",
            "does not assert coefficient-field reality",
        ),
        "finite scan of representatives, inner conjugators, and candidate involutions",
        "tuple[arbogast.hurwitz.RealPointWitness, ...] (context-bound)",
        "real_witnesses(nielsen)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenClass", "GroupElement | None", "bool"),
        input_bundles=(("NielsenClass",),),
        output_type="tuple[RealPointWitness, ...]",
    ),
    _spec(
        "hurwitz.real_structure",
        "real branch-cycle structures",
        (
            "finite Nielsen class",
            "at most one explicit exact tuple transform or signed-slot transform",
        ),
        (
            "exhaustively checks closure, bijectivity, and involutivity on supplied vertices",
            (
                "straight and signed-slot transforms are fresh-process promotable only with a "
                "computed-complete Nielsen source"
            ),
            "caller-supplied opaque transforms remain context-bound",
        ),
        "linear in Nielsen-class size times transform and canonicalization cost",
        (
            "arbogast.hurwitz.RealStructureCertificate; portable "
            "arbogast.hurwitz.HurwitzOperationCertificate for serializable transforms on "
            "computed-complete sources"
        ),
        "real_structure(nielsen)",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, BRAID_CLOSURE, HURWITZ_VERIFICATION),
        input_types=("NielsenClass", "TupleTransform | None"),
        input_bundles=(("NielsenClass",),),
        output_type="RealStructure",
    ),
    _spec(
        "hurwitz.source_genus_result",
        "branched-cover geometry",
        ("validated Nielsen tuple in an explicit positive-degree permutation representation",),
        (
            "computes the exact source-cover genus by Riemann-Hurwitz",
            "does not compute the genus of the Hurwitz parameter curve",
            "returns an in-memory receipt bound to the pinned tuple",
        ),
        "linear in total permutation degree across branch cycles",
        "arbogast.hurwitz.SourceGenusCertificate (context-bound)",
        "source_genus_result(nielsen[0]).verify(nielsen[0])",
        failure_modes=(INVALID_INPUT, HURWITZ_UNSUPPORTED, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple",),
        output_type="SourceGenusResult",
    ),
    _spec(
        "hurwitz.source_genus",
        "branched-cover geometry",
        ("validated Nielsen tuple in an explicit positive-degree permutation representation",),
        (
            "returns the exact source-cover genus by Riemann-Hurwitz",
            "does not compute the genus of the Hurwitz parameter curve",
        ),
        "source_genus_result cost",
        None,
        "source_genus(nielsen[0])",
        failure_modes=(INVALID_INPUT, HURWITZ_UNSUPPORTED, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple",),
        output_type="int",
    ),
    _spec(
        "hurwitz.symmetry_from_braid_word",
        "finite Hurwitz-component quotients",
        ("exact Hurwitz component and braid word preserving that component",),
        ("materializes the word as an exact permutation of component vertices",),
        "linear in component size times braid-word action and canonicalization",
        None,
        "symmetry_from_braid_word(component, word)",
        failure_modes=(INVALID_INPUT, BRAID_CLOSURE),
        input_types=("HurwitzComponent", "BraidWord"),
        output_type="ExplicitSymmetry",
    ),
    _spec(
        "hurwitz.collide",
        "Hurwitz boundary combinatorics",
        ("validated Nielsen tuple and an oriented cyclically adjacent collision",),
        (
            "merges the chosen monodromies in the declared orientation",
            "returns a product-one lower tuple without asserting generation or stability",
        ),
        "linear in tuple length plus one group multiplication",
        None,
        "collide(nielsen[0], (0, 1))",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("NielsenTuple", "Collision | tuple[int, int]"),
        output_type="BoundaryTuple",
    ),
    _spec(
        "hurwitz.boundary_incidence",
        "Hurwitz boundary combinatorics",
        ("exact Hurwitz component and one or more distinct valid oriented collisions",),
        (
            "returns exhaustive collision-to-stratum incidence counts for supplied vertices",
            "the v0.1 certificate is bound to the supplied in-memory component",
        ),
        "linear in component size times collisions and inner canonicalization",
        "arbogast.hurwitz.BoundaryIncidenceCertificate (context-bound)",
        "boundary_incidence(component, (0, 1)).verify()",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("HurwitzComponent", "Collision | Sequence[Collision]"),
        output_type="BoundaryIncidence",
    ),
    _spec(
        "hurwitz.claim",
        "mathematical claims",
        (
            "supported exact Hurwitz result with a self-contained portable receipt",
            "computed-complete Nielsen source and serializable operation definition where needed",
        ),
        (
            "returns exactly the computed proposition justified by the portable receipt",
            "derives its claim ID and statement from that receipt",
            "refuses imported sources, opaque transforms, and unsupported context-only results",
        ),
        "portable receipt replay plus semantic validation",
        "arbogast.cert.VerificationCertificate",
        "claim_for(nielsen)",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=PORTABLE_HURWITZ_CLAIM_TYPES,
        input_bundles=tuple((type_name,) for type_name in PORTABLE_HURWITZ_CLAIM_TYPES),
        output_type="Claim",
    ),
)

BUILTIN_OPERATION_SPECS += HURWITZ_AUXILIARY_OPERATION_SPECS


HURWITZ_PORTABLE_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "hurwitz.real_census",
        "real branch-cycle structures",
        ("finite Nielsen class and optional involution in its pinned concrete group",),
        (
            "exhaustively records the deterministic real witness policy on supplied vertices",
            "is fresh-process promotable only when backed by a computed-complete Nielsen receipt",
            "does not infer coefficient-field reality",
        ),
        "finite scan of representatives, inner conjugators, and candidate involutions",
        "arbogast.hurwitz.HurwitzOperationCertificate (computed-complete source only)",
        "real_census(nielsen).verification_certificate()",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=("NielsenClass", "GroupElement | None", "bool"),
        input_bundles=(("NielsenClass",),),
        output_type="RealCensus",
    ),
    _spec(
        "hurwitz.operation_certificate",
        "portable Hurwitz verification",
        (
            "supported exact Hurwitz result backed by a computed-complete Nielsen receipt",
            "serializable built-in transform when certifying a real structure",
        ),
        (
            "returns a self-contained content-addressed finite-table operation receipt",
            "fresh-process replay recomputes the advertised result from canonical inputs",
            "refuses imported Nielsen lists and caller-supplied opaque transforms",
        ),
        "portable Nielsen replay plus operation-specific exhaustive recomputation",
        "arbogast.hurwitz.HurwitzOperationCertificate",
        "operation_certificate_for(action).verify()",
        failure_modes=(INVALID_INPUT, PORTABILITY_BOUNDARY, HURWITZ_VERIFICATION),
        input_types=PORTABLE_HURWITZ_RESULT_TYPES,
        input_bundles=tuple((type_name,) for type_name in PORTABLE_HURWITZ_RESULT_TYPES),
        output_type="HurwitzOperationCertificate",
    ),
    _spec(
        "hurwitz.verify_operation_payload",
        "portable Hurwitz verification",
        ("canonical mapping purporting to be a supported portable operation payload",),
        (
            "returns true only after strict finite-table reconstruction and exact result replay",
            "rejects unknown fields, coercive values, unsupported operations, and tampering",
        ),
        "portable Nielsen replay plus operation-specific exhaustive recomputation",
        None,
        "verify_hurwitz_operation_payload(payload)",
        failure_modes=(INVALID_INPUT, HURWITZ_VERIFICATION),
        input_types=("Mapping[str, object]",),
        output_type="bool",
    ),
)

BUILTIN_OPERATION_SPECS += HURWITZ_PORTABLE_OPERATION_SPECS


M23_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    _spec(
        "hurwitz.load_m23_exact_dataset",
        "specialized exact M23 Hurwitz verification",
        (
            "strict v2 M23 manifest and dataset bound by exact paths, byte counts, and SHA-256",
            "pinned degree-23 generators and passport (2A,3A,6A,2A)",
        ),
        (
            (
                "returns only after replaying the compact stabilizer, class, completeness, "
                "braid, and real witnesses"
            ),
            "performs verification only; it does not invoke GAP or rerun a search",
            (
                "the result is specialized to the checked M23 v2 schema, not a generic "
                "group certificate"
            ),
        ),
        "finite specialized replay dominated by exact stabilizer and orbit witness checks",
        "arbogast.hurwitz.M23ExactCertificate",
        "load_m23_exact_dataset(manifest_path)",
        failure_modes=(INVALID_INPUT, IO_OR_SCHEMA, M23_EXACT_FAILURE),
        input_types=("str | Path",),
        output_type="M23ExactDataset",
    ),
    _spec(
        "hurwitz.m23_verification_certificate",
        "specialized exact M23 certificate projection",
        ("fully replayed M23ExactDataset and one of the six canonical M23 claim IDs",),
        (
            "returns the independently claim-bound certificate for exactly that canonical claim",
            "refuses unknown claim IDs or a dataset that does not establish the pinned value",
            "replay requires a verifier registry bound to the same fully checked dataset",
        ),
        "linear in the compact verification report serialization size",
        "arbogast.cert.VerificationCertificate (dataset-bound verifier)",
        "m23_verification_certificate_for(dataset, claim_id)",
        failure_modes=(INVALID_INPUT, M23_EXACT_FAILURE),
        input_types=("M23ExactDataset",),
        output_type="VerificationCertificate",
    ),
    _spec(
        "hurwitz.m23_certificates",
        "specialized exact M23 certificate projection",
        ("fully replayed M23ExactDataset",),
        (
            "returns exactly six canonical claim-bound certificates keyed by content address",
            "each certificate uses the dataset-bound hurwitz.m23_exact verifier",
        ),
        "six linear certificate projections from one checked report",
        "dict[str, arbogast.cert.VerificationCertificate] (dataset-bound verifier)",
        "m23_certificates_for(dataset)",
        failure_modes=(INVALID_INPUT, M23_EXACT_FAILURE),
        input_types=("M23ExactDataset",),
        output_type="dict[str, VerificationCertificate]",
    ),
    _spec(
        "hurwitz.m23_claim_graph",
        "specialized exact M23 semantic projection",
        ("fully replayed M23ExactDataset and optional provenance record identifier",),
        (
            "returns the canonical six-node computed and certified ClaimGraph",
            "preserves explicit dependencies, hypotheses, and contextual source references",
            "does not treat contextual sources as proof or generalize beyond the pinned fixture",
        ),
        "six certificate projections plus ClaimGraph validation",
        "arbogast.cert.VerificationCertificate (one dataset-bound receipt per claim)",
        "m23_claim_graph_for(dataset)",
        failure_modes=(INVALID_INPUT, M23_EXACT_FAILURE),
        input_types=("M23ExactDataset",),
        output_type="ClaimGraph",
    ),
)

BUILTIN_OPERATION_SPECS += M23_OPERATION_SPECS


BUILTIN_IMPLEMENTATIONS: dict[str, tuple[str, str]] = {
    "linalg.as_dense": ("arbogast.linalg", "as_dense"),
    "linalg.rref": ("arbogast.linalg", "rref"),
    "linalg.rank": ("arbogast.linalg", "rank"),
    "linalg.determinant": ("arbogast.linalg", "determinant"),
    "linalg.inverse": ("arbogast.linalg", "inverse"),
    "linalg.row_space": ("arbogast.linalg", "row_space"),
    "linalg.image": ("arbogast.linalg", "image"),
    "linalg.nullspace": ("arbogast.linalg", "nullspace"),
    "linalg.left_nullspace": ("arbogast.linalg", "left_nullspace"),
    "linalg.sum_subspaces": ("arbogast.linalg", "sum_subspaces"),
    "linalg.intersection": ("arbogast.linalg", "intersection"),
    "linalg.complement": ("arbogast.linalg", "complement"),
    "linalg.quotient_space": ("arbogast.linalg", "quotient_space"),
    "linalg.solve": ("arbogast.linalg", "solve"),
    "rep.symmetric_group": ("arbogast.rep", "symmetric_group"),
    "rep.cyclic_group": ("arbogast.rep", "cyclic_group"),
    "rep.representation": ("arbogast.rep", "representation"),
    "rep.fixed_part": ("arbogast.rep", "fixed_part"),
    "rep.semisimple": ("arbogast.rep", "semisimple"),
    "rep.weight_spaces": ("arbogast.rep", "weight_spaces"),
    "rep.projector": ("arbogast.rep", "projector"),
    "rep.isotypic": ("arbogast.rep", "isotypic"),
    "rep.decompose": ("arbogast.rep", "decompose"),
    "cohom.h0": ("arbogast.cohom", "h0"),
    "cohom.h1": ("arbogast.cohom", "h1"),
    "cohom.h2": ("arbogast.cohom", "h2"),
    "cohom.cochain_complex": ("arbogast.cohom", "cochain_complex"),
    "cohom.cohomology": ("arbogast.cohom", "cohomology"),
    "cohom.cocycles": ("arbogast.cohom", "cocycles"),
    "cohom.coboundaries": ("arbogast.cohom", "coboundaries"),
    "cohom.is_cocycle": ("arbogast.cohom", "is_cocycle"),
    "cohom.is_coboundary": ("arbogast.cohom", "is_coboundary"),
    "cohom.class_of": ("arbogast.cohom", "class_of"),
    "cohom.restrict": ("arbogast.cohom", "restrict"),
    "cohom.inflate": ("arbogast.cohom", "inflate"),
    "cohom.restriction_map": ("arbogast.cohom", "restriction_map"),
    "cohom.inflation_map": ("arbogast.cohom", "inflation_map"),
    "cohom.corestriction_map": ("arbogast.cohom", "corestriction_map"),
    "cohom.corestrict": ("arbogast.cohom", "corestrict"),
    "cohom.transgression": ("arbogast.cohom", "transgression"),
    "cohom.inflation_restriction": ("arbogast.cohom", "inflation_restriction"),
    "cohom.claim_graph": ("arbogast.cohom.semantic", "claim_graph_for_result"),
    "cohom.verification_certificate": (
        "arbogast.cohom.semantic",
        "verification_certificate_for_result",
    ),
    "galois.finite_galois_quotient": (
        "arbogast.galois",
        "finite_galois_quotient",
    ),
    "galois.galois_module": ("arbogast.galois", "galois_module"),
    "galois.finite_galois_quotient_certificate": (
        "arbogast.galois",
        "finite_galois_quotient_certificate",
    ),
    "galois.kummer_space": ("arbogast.galois", "kummer_space"),
    "galois.kummer_class": ("arbogast.galois", "kummer_class"),
    "galois.local_h1": ("arbogast.galois", "local_h1"),
    "galois.local_h1_class": ("arbogast.galois", "local_h1_class"),
    "galois.decomposition_quotient_h1": (
        "arbogast.galois",
        "decomposition_quotient_h1",
    ),
    "galois.localize": ("arbogast.galois", "localize"),
    "galois.nonabelian_h1": ("arbogast.galois", "nonabelian_h1"),
    "galois.twist_classes": ("arbogast.galois", "twist_classes"),
    "galois.verification_certificate": (
        "arbogast.galois.semantic",
        "verification_certificate_for_result",
    ),
    "galois.claim": ("arbogast.galois.semantic", "claim_for_result"),
    "galois.claim_graph": ("arbogast.galois.semantic", "claim_graph_for_result"),
    "arithmetic.cartier_dual": ("arbogast.arithmetic", "cartier_dual"),
    "arithmetic.local_condition": ("arbogast.arithmetic", "local_condition"),
    "arithmetic.local_pairing": ("arbogast.arithmetic", "local_pairing"),
    "arithmetic.selmer": ("arbogast.arithmetic", "selmer"),
    "arithmetic.dual_selmer": ("arbogast.arithmetic", "dual_selmer"),
    "arithmetic.aim": ("arbogast.arithmetic", "aim"),
    "arithmetic.unique": ("arbogast.arithmetic", "unique"),
    "arithmetic.elementary_descent": (
        "arbogast.arithmetic",
        "elementary_descent",
    ),
    "arithmetic.verification_certificate": (
        "arbogast.arithmetic.semantic",
        "verification_certificate_for_result",
    ),
    "arithmetic.claim": ("arbogast.arithmetic.semantic", "claim_for_result"),
    "arithmetic.claim_graph": (
        "arbogast.arithmetic.semantic",
        "claim_graph_for_result",
    ),
    "deform.deformation_problem": ("arbogast.deform", "deformation_problem"),
    "deform.gauge": ("arbogast.deform", "gauge"),
    "deform.tangent": ("arbogast.deform", "tangent"),
    "deform.obstructions": ("arbogast.deform", "obstructions"),
    "deform.frame": ("arbogast.deform", "frame"),
    "deform.equivariant": ("arbogast.deform", "equivariant"),
    "deform.invariant_deformations": ("arbogast.deform", "invariant_deformations"),
    "deform.equivariant_decomposition": (
        "arbogast.deform",
        "equivariant_decomposition",
    ),
    "deform.lift": ("arbogast.deform", "lift"),
    "deform.unique_lift": ("arbogast.deform", "unique_lift"),
    "deform.fixed_lift": ("arbogast.deform", "fixed_lift"),
    "deform.rigid": ("arbogast.deform", "rigid"),
    "deform.verification_certificate": (
        "arbogast.deform.semantic",
        "verification_certificate_for_result",
    ),
    "deform.claim": ("arbogast.deform.semantic", "claim_for_result"),
    "deform.claim_graph": ("arbogast.deform.semantic", "claim_graph_for_result"),
    "deform.verify_receipt": ("arbogast.deform", "verify_deformation_receipt"),
    "numeric.continue_path": ("arbogast.numeric", "continue_path"),
    "numeric.condition_number": ("arbogast.numeric", "condition_number"),
    "numeric.branch_cycles": ("arbogast.numeric", "branch_cycles"),
    "numeric.bind_vertex": ("arbogast.numeric", "bind_vertex"),
    "numeric.braid_continue": ("arbogast.numeric", "braid_continue"),
    "numeric.recognize": ("arbogast.numeric", "recognize"),
    "numeric.exactify": ("arbogast.numeric", "exactify"),
    "numeric.projection_degree": ("arbogast.numeric", "projection_degree"),
    "numeric.weighted_braid_plan": ("arbogast.numeric", "weighted_braid_plan"),
    "numeric.verification_certificate": (
        "arbogast.numeric.semantic",
        "verification_certificate_for_result",
    ),
    "numeric.claim": ("arbogast.numeric.semantic", "claim_for_result"),
    "numeric.claim_graph": ("arbogast.numeric.semantic", "claim_graph_for_result"),
    "numeric.verify_receipt": ("arbogast.numeric", "verify_numeric_receipt"),
    "padic.frobenius": ("arbogast.padic", "frobenius"),
    "padic.slopes": ("arbogast.padic", "slopes"),
    "padic.ordinary_part": ("arbogast.padic", "ordinary_part"),
    "padic.inertia_action": ("arbogast.padic", "inertia_action"),
    "padic.good_reduction": ("arbogast.padic", "good_reduction"),
    "padic.semistable_reduction": ("arbogast.padic", "semistable_reduction"),
    "padic.stable_reduction": ("arbogast.padic", "stable_reduction"),
    "padic.deformation_datum": ("arbogast.padic", "deformation_datum"),
    "padic.lift_set": ("arbogast.padic", "lift_set"),
    "padic.lift_galois_action": ("arbogast.padic", "lift_galois_action"),
    "padic.fixed_lifts": ("arbogast.padic", "fixed_lifts"),
    "padic.effective_descent": ("arbogast.padic", "effective_descent"),
    "padic.local_factorization_fragment": (
        "arbogast.padic",
        "local_factorization_fragment",
    ),
    "padic.reduction_frontier": ("arbogast.padic", "reduction_frontier"),
    "padic.verification_certificate": ("arbogast.padic", "verification_certificate"),
    "padic.claim": ("arbogast.padic", "claim"),
    "padic.claim_graph": ("arbogast.padic", "claim_graph"),
    "padic.verify_receipt": ("arbogast.padic", "verify_receipt"),
    "export.json": ("arbogast.export", "export_json"),
    "fleet.plan_pari_arithmetic_task": (
        "arbogast.fleet",
        "plan_pari_arithmetic_task",
    ),
    "fleet.plan_python_certificate_replay_task": (
        "arbogast.fleet",
        "plan_python_certificate_replay_task",
    ),
    "hurwitz.nielsen_class": ("arbogast.hurwitz", "nielsen_class"),
    "hurwitz.plan_nielsen_class": ("arbogast.hurwitz", "plan_nielsen_class"),
    "hurwitz.nielsen_tuple": ("arbogast.hurwitz", "nielsen_tuple"),
    "hurwitz.verify_nielsen_certificate_payload": (
        "arbogast.hurwitz",
        "verify_nielsen_certificate_payload",
    ),
    "hurwitz.load_precomputed_nielsen_class": (
        "arbogast.hurwitz",
        "load_precomputed_nielsen_class",
    ),
    "hurwitz.pure_braid_word": ("arbogast.hurwitz", "pure_braid_word"),
    "hurwitz.apply_braid_word_entries": (
        "arbogast.hurwitz",
        "apply_braid_word_entries",
    ),
    "hurwitz.hurwitz_move": ("arbogast.hurwitz", "hurwitz_move"),
    "hurwitz.apply_braid_word": ("arbogast.hurwitz", "apply_braid_word"),
    "hurwitz.braid_action": ("arbogast.hurwitz", "braid_action"),
    "hurwitz.components": ("arbogast.hurwitz", "components"),
    "hurwitz.braid_distance": ("arbogast.hurwitz", "braid_distance"),
    "hurwitz.weighted_braid_path": ("arbogast.hurwitz", "weighted_braid_path"),
    "hurwitz.straight_real_transform": (
        "arbogast.hurwitz",
        "straight_real_transform",
    ),
    "hurwitz.signed_slot_transform": ("arbogast.hurwitz", "signed_slot_transform"),
    "hurwitz.is_real_tuple": ("arbogast.hurwitz", "is_real_tuple"),
    "hurwitz.is_totally_real": ("arbogast.hurwitz", "is_totally_real"),
    "hurwitz.real_witnesses": ("arbogast.hurwitz", "real_witnesses"),
    "hurwitz.real_points": ("arbogast.hurwitz", "real_points"),
    "hurwitz.real_census": ("arbogast.hurwitz", "real_census"),
    "hurwitz.totally_real": ("arbogast.hurwitz", "totally_real"),
    "hurwitz.real_structure": ("arbogast.hurwitz", "real_structure"),
    "hurwitz.source_genus_result": ("arbogast.hurwitz", "source_genus_result"),
    "hurwitz.source_genus": ("arbogast.hurwitz", "source_genus"),
    "hurwitz.symmetry_from_braid_word": (
        "arbogast.hurwitz",
        "symmetry_from_braid_word",
    ),
    "hurwitz.reduced": ("arbogast.hurwitz", "reduced"),
    "hurwitz.cusps": ("arbogast.hurwitz", "cusps"),
    "hurwitz.collide": ("arbogast.hurwitz", "collide"),
    "hurwitz.boundary_incidence": ("arbogast.hurwitz", "boundary_incidence"),
    "hurwitz.boundary": ("arbogast.hurwitz", "boundary"),
    "hurwitz.claim": ("arbogast.hurwitz", "claim_for"),
    "hurwitz.claim_graph": ("arbogast.hurwitz", "claim_graph_for"),
    "hurwitz.verification_certificate": (
        "arbogast.hurwitz",
        "verification_certificate_for",
    ),
    "hurwitz.operation_certificate": ("arbogast.hurwitz", "operation_certificate_for"),
    "hurwitz.verify_operation_payload": (
        "arbogast.hurwitz",
        "verify_hurwitz_operation_payload",
    ),
    "hurwitz.load_m23_exact_dataset": (
        "arbogast.hurwitz",
        "load_m23_exact_dataset",
    ),
    "hurwitz.m23_verification_certificate": (
        "arbogast.hurwitz",
        "m23_verification_certificate_for",
    ),
    "hurwitz.m23_certificates": ("arbogast.hurwitz", "m23_certificates_for"),
    "hurwitz.m23_claim_graph": ("arbogast.hurwitz", "m23_claim_graph_for"),
}


# Public aliases share the exact same Python function object and therefore the same contract.
# Keeping this map explicit makes additions to any mathematical module fail the audit until a
# maintainer either supplies a contract or records a narrowly justified helper exception.
OPERATION_CONTRACT_MODULES = (
    "arbogast.linalg",
    "arbogast.rep",
    "arbogast.cohom",
    "arbogast.galois",
    "arbogast.arithmetic",
    "arbogast.deform",
    "arbogast.numeric",
    "arbogast.padic",
    "arbogast.fleet",
    "arbogast.hurwitz",
)

# Backend adapter methods are intentionally outside this surface: they are capability plumbing
# that yields discovery-only receipts.  The top-level mathematical wrappers above are the public
# operations whose mathematical guarantees are stable enough to advertise.
PUBLIC_FUNCTION_OPERATIONS: dict[str, dict[str, str]] = {
    "arbogast.linalg": {
        "as_dense": "linalg.as_dense",
        "column_space": "linalg.image",
        "complement": "linalg.complement",
        "determinant": "linalg.determinant",
        "image": "linalg.image",
        "intersection": "linalg.intersection",
        "inverse": "linalg.inverse",
        "kernel": "linalg.nullspace",
        "left_nullspace": "linalg.left_nullspace",
        "nullspace": "linalg.nullspace",
        "quotient": "linalg.quotient_space",
        "quotient_space": "linalg.quotient_space",
        "rank": "linalg.rank",
        "row_space": "linalg.row_space",
        "rref": "linalg.rref",
        "solve": "linalg.solve",
        "sum_subspaces": "linalg.sum_subspaces",
    },
    "arbogast.rep": {
        "cyclic_group": "rep.cyclic_group",
        "decompose": "rep.decompose",
        "fixed_part": "rep.fixed_part",
        "isotypic": "rep.isotypic",
        "projector": "rep.projector",
        "representation": "rep.representation",
        "semisimple": "rep.semisimple",
        "symmetric_group": "rep.symmetric_group",
        "weight_spaces": "rep.weight_spaces",
    },
    "arbogast.cohom": {
        "H0": "cohom.h0",
        "H1": "cohom.h1",
        "H2": "cohom.h2",
        "class_of": "cohom.class_of",
        "coboundaries": "cohom.coboundaries",
        "cochain_complex": "cohom.cochain_complex",
        "cocycles": "cohom.cocycles",
        "cohomology": "cohom.cohomology",
        "h0": "cohom.h0",
        "h1": "cohom.h1",
        "h2": "cohom.h2",
        "inflate": "cohom.inflate",
        "inflation_map": "cohom.inflation_map",
        "is_coboundary": "cohom.is_coboundary",
        "is_cocycle": "cohom.is_cocycle",
        "restrict": "cohom.restrict",
        "restriction_map": "cohom.restriction_map",
        "corestrict": "cohom.corestrict",
        "corestriction_map": "cohom.corestriction_map",
        "inflation_restriction": "cohom.inflation_restriction",
        "transgression": "cohom.transgression",
    },
    "arbogast.galois": {
        "decomposition_quotient_h1": "galois.decomposition_quotient_h1",
        "finite_galois_quotient": "galois.finite_galois_quotient",
        "finite_galois_quotient_certificate": ("galois.finite_galois_quotient_certificate"),
        "galois_module": "galois.galois_module",
        "kummer_class": "galois.kummer_class",
        "kummer_space": "galois.kummer_space",
        "local_h1": "galois.local_h1",
        "local_h1_class": "galois.local_h1_class",
        "localize": "galois.localize",
        "nonabelian_h1": "galois.nonabelian_h1",
        "twist_classes": "galois.twist_classes",
    },
    "arbogast.arithmetic": {
        "aim": "arithmetic.aim",
        "cartier_dual": "arithmetic.cartier_dual",
        "dual_selmer": "arithmetic.dual_selmer",
        "elementary_descent": "arithmetic.elementary_descent",
        "local_condition": "arithmetic.local_condition",
        "local_pairing": "arithmetic.local_pairing",
        "selmer": "arithmetic.selmer",
        "unique": "arithmetic.unique",
    },
    "arbogast.deform": {
        "deformation_problem": "deform.deformation_problem",
        "claim_for_result": "deform.claim",
        "claim_graph_for_result": "deform.claim_graph",
        "equivariant": "deform.equivariant",
        "equivariant_decomposition": "deform.equivariant_decomposition",
        "fixed_lift": "deform.fixed_lift",
        "frame": "deform.frame",
        "gauge": "deform.gauge",
        "invariant_deformations": "deform.invariant_deformations",
        "lift": "deform.lift",
        "obstructions": "deform.obstructions",
        "rigid": "deform.rigid",
        "tangent": "deform.tangent",
        "unique_lift": "deform.unique_lift",
        "verification_certificate_for_result": "deform.verification_certificate",
        "verify_deformation_receipt": "deform.verify_receipt",
    },
    "arbogast.numeric": {
        "bind_vertex": "numeric.bind_vertex",
        "braid_continue": "numeric.braid_continue",
        "branch_cycles": "numeric.branch_cycles",
        "claim_for_result": "numeric.claim",
        "claim_graph_for_result": "numeric.claim_graph",
        "condition_number": "numeric.condition_number",
        "continue_path": "numeric.continue_path",
        "exactify": "numeric.exactify",
        "projection_degree": "numeric.projection_degree",
        "recognize": "numeric.recognize",
        "verification_certificate_for_result": "numeric.verification_certificate",
        "verify_numeric_receipt": "numeric.verify_receipt",
        "weighted_braid_plan": "numeric.weighted_braid_plan",
    },
    "arbogast.padic": {
        "claim": "padic.claim",
        "claim_graph": "padic.claim_graph",
        "deformation_datum": "padic.deformation_datum",
        "effective_descent": "padic.effective_descent",
        "fixed_lifts": "padic.fixed_lifts",
        "frobenius": "padic.frobenius",
        "good_reduction": "padic.good_reduction",
        "inertia_action": "padic.inertia_action",
        "lift_galois_action": "padic.lift_galois_action",
        "lift_set": "padic.lift_set",
        "local_factorization_fragment": "padic.local_factorization_fragment",
        "ordinary_part": "padic.ordinary_part",
        "reduction_frontier": "padic.reduction_frontier",
        "semistable_reduction": "padic.semistable_reduction",
        "slopes": "padic.slopes",
        "stable_reduction": "padic.stable_reduction",
        "verification_certificate": "padic.verification_certificate",
        "verify_receipt": "padic.verify_receipt",
    },
    "arbogast.fleet": {
        "plan_pari_arithmetic_task": "fleet.plan_pari_arithmetic_task",
        "plan_python_certificate_replay_task": ("fleet.plan_python_certificate_replay_task"),
    },
    "arbogast.hurwitz": {
        attribute: operation
        for operation, (module_name, attribute) in BUILTIN_IMPLEMENTATIONS.items()
        if module_name == "arbogast.hurwitz"
    },
}

PUBLIC_NON_OPERATION_HELPERS: dict[str, dict[str, str]] = {
    "arbogast.padic": {
        "certified_result": (
            "constructs the proof-bearing result envelope used by documented exact fixtures"
        ),
    },
    "arbogast.fleet": {
        "automatic_local_worker_pool": "constructs runtime worker inventory, not mathematics",
        "default_fleet_operation_registry": "constructs the trusted runtime registry",
        "deterministic_plan": "low-level shard protocol helper",
        "execute_local": "runtime execution helper governed by registered task operations",
    },
    "arbogast.hurwitz": {
        "m23_verifier_registry": (
            "constructs a VerifierRegistry bound to an already replayed M23 dataset; it is "
            "certificate plumbing and computes no new mathematical result"
        ),
        "register_hurwitz_replay": (
            "idempotently installs a verifier in the central registry and optionally preflights "
            "a receipt; it computes no mathematical result"
        ),
    },
}

SHARD_PLANNERS: dict[str, tuple[str, str]] = {
    "arithmetic.selmer": ("arbogast.arithmetic.plans", "plan_selmer"),
    "galois.local_h1": ("arbogast.galois.plans", "plan_local_h1"),
    "galois.localize": ("arbogast.galois.plans", "plan_localize"),
    "hurwitz.nielsen_class": ("arbogast.hurwitz", "plan_nielsen_class"),
}


def register_builtin_operations(
    registry: OperationRegistry = default_operations,
) -> OperationRegistry:
    for spec in BUILTIN_OPERATION_SPECS:
        registry.register_spec(spec)
    return registry


def bind_builtin_implementations(
    registry: OperationRegistry = default_operations,
) -> OperationRegistry:
    """Bind contracts to public callables after lightweight module imports."""

    for name, (module_name, attribute) in BUILTIN_IMPLEMENTATIONS.items():
        module = import_module(module_name)
        function = getattr(module, attribute)
        if not callable(function):
            raise OperationSpecError(
                f"public implementation is not callable: {module_name}.{attribute}"
            )
        registry.bind(name, function)
    return registry


__all__ = [
    "BUILTIN_IMPLEMENTATIONS",
    "BUILTIN_OPERATION_SPECS",
    "OPERATION_CONTRACT_MODULES",
    "PUBLIC_FUNCTION_OPERATIONS",
    "PUBLIC_NON_OPERATION_HELPERS",
    "SHARD_PLANNERS",
    "bind_builtin_implementations",
    "register_builtin_operations",
]
