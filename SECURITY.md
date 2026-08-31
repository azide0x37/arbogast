# Security and integrity policy

Arbogast processes mathematical certificates and may invoke separately installed computer
algebra systems. A defect can therefore affect both ordinary software security and the integrity
of a claimed computation.

## Supported versions

Security and certificate-integrity fixes target the latest released 0.x version. Arbogast 0.6.0
is currently supported. Old certificate schema versions may be unsupported.

## Reporting a vulnerability

Private vulnerability reporting is not currently enabled for this repository, and no
repository-provided private inbox is advertised. For a non-sensitive integrity bug, open a
[public issue](https://github.com/azide0x37/arbogast/issues/new). For a sensitive report, open an
issue titled **Security contact request** with contact information but no exploit details, then
wait for the maintainer to establish a private channel. If no private channel is established, do
not post the sensitive report publicly. Never put a reproducer, credential, or embargoed detail
in the contact-request issue.

Include, when possible:

- affected version and platform;
- a minimal certificate, input, or reproducer;
- expected and observed behavior;
- whether the issue crosses a theorem boundary or changes a verified claim;
- any backend executable and version involved.

Response and remediation times depend on maintainer availability, severity, and whether
published mathematical artifacts require re-verification.

## Trust boundary

Treat certificates, manifests, claim graphs, and imported datasets as untrusted input. Arbogast
verifiers are expected to validate schema versions, sizes, canonical encodings, hashes,
references, and all mathematical witnesses needed for the stated claim.

Arbogast does not sandbox external backends. GAP, PARI/GP, SageMath, Magma, and other executables
run with the permissions of the invoking user. Only use trusted installations and trusted
backend scripts. Never place secrets in task specifications, provenance records, or certificates;
these artifacts are designed to be shareable.

## Out of scope

Incorrect conjectures, disputed imported theorems, and unsupported mathematical generalizations
are not software vulnerabilities unless Arbogast misrepresents their status or a verifier accepts
evidence that does not establish the recorded claim. Ordinary mathematical corrections are still
very welcome as public issues.
