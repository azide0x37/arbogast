"""Built-in v0.1 mathematical contracts, independent of backend imports."""

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
)

BUILTIN_OPERATION_SPECS += COHOM_OPERATION_SPECS


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
    "cohom.claim_graph": ("arbogast.cohom.semantic", "claim_graph_for_result"),
    "cohom.verification_certificate": (
        "arbogast.cohom.semantic",
        "verification_certificate_for_result",
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
        "is_coboundary": "cohom.is_coboundary",
        "is_cocycle": "cohom.is_cocycle",
        "restrict": "cohom.restrict",
    },
    "arbogast.hurwitz": {
        attribute: operation
        for operation, (module_name, attribute) in BUILTIN_IMPLEMENTATIONS.items()
        if module_name == "arbogast.hurwitz"
    },
}

PUBLIC_NON_OPERATION_HELPERS: dict[str, dict[str, str]] = {
    "arbogast.hurwitz": {
        "m23_verifier_registry": (
            "constructs a VerifierRegistry bound to an already replayed M23 dataset; it is "
            "certificate plumbing and computes no new mathematical result"
        ),
        "register_hurwitz_replay": (
            "idempotently installs a verifier in the central registry and optionally preflights "
            "a receipt; it computes no mathematical result"
        ),
    }
}

SHARD_PLANNERS: dict[str, tuple[str, str]] = {
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
    """Bind contracts to the v0.1 public callables after lightweight module imports."""

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
