# Discovery-only generator for the exact M23 Hurwitz fixture.
#
# Run from the Arbogast repository root with GAP 4.16 or later:
#
#   gap -A -q examples/hurwitz/m23_real_component/generate.g
#
# This is deliberately not an installation-time or CI dependency.  The checked-in
# dataset is verified by verify.py using only Python and the finite witnesses.

outputPath := "examples/hurwitz/m23_real_component/expected/dataset.json";;

G := MathieuGroup(23);;
degree := 23;;
identity := One(G);;

ImageList := p -> List([1..degree], i -> i^p);;
TupleImageLists := t -> List(t, ImageList);;
TupleKey := t -> Flat(TupleImageLists(t));;

classes := ConjugacyClasses(G);;
ClassByOrder := n -> First(classes, cl -> Order(Representative(cl)) = n);;
class2 := ClassByOrder(2);;
class3 := ClassByOrder(3);;
class6 := ClassByOrder(6);;
classRepresentatives := [
  Representative(class2),
  Representative(class3),
  Representative(class6),
  Representative(class2)
];;

# Pin the first entry and then lexicographically minimize the second entry under
# its full centralizer and the third entry under the residual stabilizer.  GAP's
# permutation order agrees with one-line lexicographic order on these orbits;
# the independent verifier reconstructs the two finite orbits and checks this.
r2 := classRepresentatives[1];;
a := r2;;
C := Centralizer(G, r2);;

CanonWithWitness := function(t)
  local g, u, orbitB, bmin, h, v, D, orbitC, cmin, k, total, result;
  g := RepresentativeAction(G, t[1], r2, OnPoints);
  if g = fail then Error("first entry is not in the pinned 2A class"); fi;
  u := List(t, x -> x^g);
  orbitB := Orbit(C, u[2], OnPoints);
  bmin := Minimum(orbitB);
  h := RepresentativeAction(C, u[2], bmin, OnPoints);
  v := List(u, x -> x^h);
  D := Centralizer(C, bmin);
  orbitC := Orbit(D, v[3], OnPoints);
  cmin := Minimum(orbitC);
  k := RepresentativeAction(D, v[3], cmin, OnPoints);
  total := g * h * k;
  result := List(t, x -> x^total);
  if result <> List(v, x -> x^k) then Error("canonical conjugator mismatch"); fi;
  return [result, total];
end;;

HurwitzMove := function(t, signedGenerator)
  local i, a, b, result;
  i := AbsInt(signedGenerator);
  result := ShallowCopy(t);
  a := t[i];
  b := t[i+1];
  if signedGenerator > 0 then
    # Right Hurwitz action: (a,b)^sigma = (a*b*a^-1,a).
    result[i] := a * b * a^-1;
    result[i+1] := a;
  else
    result[i] := b;
    result[i+1] := b^-1 * a * b;
  fi;
  return result;
end;;

ApplyWord := function(t, word)
  local result, signedGenerator;
  result := t;
  for signedGenerator in word do
    result := HurwitzMove(result, signedGenerator);
  od;
  return result;
end;;

InverseWord := word -> List(Reversed(word), x -> -x);;

# Haefner, arXiv:2202.08222v3, pure generators beta_ij in the right
# convention.  Braid indices 1,2,3 here correspond to beta_2,beta_3,beta_4
# in the paper's displayed B_4 formulas.
pureWords := [
  [1,1],
  [-1,2,2,1],
  [-1,-2,3,3,2,1],
  [2,2],
  [-2,3,3,2],
  [3,3]
];;
pureNames := ["beta12", "beta13", "beta14", "beta23", "beta24", "beta34"];;
searchWords := Concatenation(pureWords, List(pureWords, InverseWord));;

# This generating tuple was found after 4,387 trials with
# Reset(GlobalMersenneTwister, 20260828).  Fixing it makes regeneration
# deterministic and keeps random search out of verification.
seedRaw := List([
  [14,2,17,6,5,4,12,8,22,11,10,7,13,1,21,18,3,16,19,20,15,9,23],
  [16,2,17,4,5,6,13,8,1,11,23,7,12,22,21,9,20,14,15,3,19,18,10],
  [21,17,4,10,14,20,7,13,18,23,19,8,15,16,11,5,2,9,12,3,22,1,6],
  [1,17,3,20,14,10,7,13,9,6,19,15,8,5,12,16,2,18,11,4,22,21,23]
], PermList);;
if List(seedRaw, Order) <> [2,3,6,2] then Error("seed passport mismatch"); fi;
if Product(seedRaw) <> identity then Error("seed is not product one"); fi;
if Size(Group(seedRaw)) <> Size(G) then Error("seed does not generate M23"); fi;

canonicalSeedAndWitness := CanonWithWitness(seedRaw);;
canonicalSeed := canonicalSeedAndWitness[1];;
key := TupleKey(canonicalSeed);;
dictionary := NewDictionary(key, true);;
AddDictionary(dictionary, key, 1);;
vertices := [canonicalSeed];;
head := 1;;
started := Runtime();;

while head <= Length(vertices) do
  current := vertices[head];
  for word in searchWords do
    canonical := CanonWithWitness(ApplyWord(current, word))[1];
    key := TupleKey(canonical);
    target := LookupDictionary(dictionary, key);
    if target = fail then
      target := Length(vertices) + 1;
      AddDictionary(dictionary, key, target);
      Add(vertices, canonical);
    fi;
  od;
  head := head + 1;
  if RemInt(head - 1, 200) = 0 then
    Print("processed=", head-1, " vertices=", Length(vertices),
          " runtime_ms=", Runtime()-started, "\n");
  fi;
od;

transitions := [];;
for current in vertices do
  row := [];
  for word in pureWords do
    canonicalAndWitness := CanonWithWitness(ApplyWord(current, word));
    target := LookupDictionary(dictionary, TupleKey(canonicalAndWitness[1]));
    if target = fail then Error("pure edge leaves enumerated component"); fi;
    Add(row, [target - 1, ImageList(canonicalAndWitness[2])]);
  od;
  Add(transitions, row);
od;

classConjugators := [];;
for current in vertices do
  row := [];
  for slot in [1..4] do
    witness := RepresentativeAction(
      G, classRepresentatives[slot], current[slot], OnPoints
    );
    if witness = fail or classRepresentatives[slot]^witness <> current[slot] then
      Error("class conjugacy witness failure");
    fi;
    Add(row, ImageList(witness));
  od;
  Add(classConjugators, row);
od;

StraightTransform := function(t)
  local prefix, result, entry;
  prefix := identity;
  result := [];
  for entry in t do
    Add(result, prefix * entry^-1 * prefix^-1);
    prefix := prefix * entry;
  od;
  if Product(result) <> identity then Error("real transform lost product one"); fi;
  return result;
end;;

# Exhaustive completeness witness.  After fixing a=r2 and a C_G(a)-orbit
# representative b, every product-one tuple has the uniquely forced form
#
#   c = (a*b)^-1*d,  d in 2A.
#
# Thus only 35 * 3795 candidates are needed.  Each accepted c carries an
# explicit M23 conjugator from the pinned 6A representative.  The independent
# verifier reconstructs the full 2A and 3A conjugacy orbits, repeats this
# enumeration, and quotients by D=C_C(b).
class2Elements := ShallowCopy(AsList(class2));;
Sort(class2Elements, function(x, y) return ImageList(x) < ImageList(y); end);;
dDictionary := NewDictionary(ImageList(class2Elements[1]), true);;
for index in [1..Length(class2Elements)] do
  AddDictionary(dDictionary, ImageList(class2Elements[index]), index);
od;

class3Elements := AsList(class3);;
class3Orbits := Orbits(C, class3Elements, OnPoints);;
bOrbitRecords := List(class3Orbits, orbit -> [Minimum(orbit), Length(orbit)]);;
Sort(bOrbitRecords, function(x, y) return ImageList(x[1]) < ImageList(y[1]); end);;

completenessRows := [];;
fixedARawCount := 0;;
innerOrbitCount := 0;;
componentOrbitCount := 0;;
nongeneratingOrbitCount := 0;;
nongeneratingC1Count := 0;;
componentC1CompletenessCount := 0;;
class6WitnessCount := 0;;
weightedMass := 0;;
componentKeysSeen := NewDictionary(TupleKey(vertices[1]), true);;

for bRecord in bOrbitRecords do
  b := bRecord[1];
  bOrbitSize := bRecord[2];
  D := Centralizer(C, b);
  ab := a * b;
  accepted := [];
  for d in class2Elements do
    c := ab^-1 * d;
    if c in class6 then
      witness := RepresentativeAction(G, classRepresentatives[3], c, OnPoints);
      if witness = fail or classRepresentatives[3]^witness <> c then
        Error("completeness 6A witness failure");
      fi;
      dIndex := LookupDictionary(dDictionary, ImageList(d));
      Add(accepted, [dIndex - 1, ImageList(witness)]);
      class6WitnessCount := class6WitnessCount + 1;

      if c = Minimum(Orbit(D, c, OnPoints)) then
        tuple := [a, b, c, d];
        if Product(tuple) <> identity then Error("completeness tuple is not product one"); fi;
        innerOrbitCount := innerOrbitCount + 1;
        stabilizerSize := Size(Centralizer(D, c));
        weightedMass := weightedMass + 1 / stabilizerSize;
        componentIndex := LookupDictionary(dictionary, TupleKey(tuple));
        if componentIndex = fail then
          if IsTransitive(Group(tuple), [1..23]) then
            Error("transitive generating candidate missing from pure component");
          fi;
          nongeneratingOrbitCount := nongeneratingOrbitCount + 1;
          if StraightTransform(tuple) = tuple then
            nongeneratingC1Count := nongeneratingC1Count + 1;
          fi;
        else
          componentOrbitCount := componentOrbitCount + 1;
          if StraightTransform(tuple) = tuple then
            componentC1CompletenessCount := componentC1CompletenessCount + 1;
          fi;
          AddDictionary(componentKeysSeen, TupleKey(tuple), true);
        fi;
      fi;
    fi;
  od;
  fixedARawCount := fixedARawCount + bOrbitSize * Length(accepted);
  Add(completenessRows, [
    ImageList(b), bOrbitSize, Size(D), accepted
  ]);
od;

if Length(bOrbitRecords) <> 35 then Error("unexpected number of C-orbits on 3A"); fi;
if class6WitnessCount <> 12465 then Error("unexpected forced-c acceptance count"); fi;
if fixedARawCount <> 18553024 then Error("fixed-a product-one mass mismatch"); fi;
if innerOrbitCount <> 7114 then Error("unexpected full inner-orbit count"); fi;
if componentOrbitCount <> 1428 then Error("unexpected generating inner-orbit count"); fi;
if nongeneratingOrbitCount <> 5686 then Error("unexpected nongenerating count"); fi;
if componentC1CompletenessCount <> 20 then Error("unexpected generating c=1 count"); fi;
if nongeneratingC1Count <> 212 then Error("unexpected nongenerating c=1 guardrail"); fi;
if weightedMass <> 41413/6 then Error("weighted inner-orbit mass mismatch"); fi;
for current in vertices do
  if LookupDictionary(componentKeysSeen, TupleKey(current)) = fail then
    Error("pure component vertex absent from exhaustive completeness enumeration");
  fi;
od;

realTransitions := [];;
c1Indices := [];;
innerFixedIndices := [];;
realMapping := [];;
for index in [1..Length(vertices)] do
  transformed := StraightTransform(vertices[index]);
  if transformed = vertices[index] then Add(c1Indices, index - 1); fi;
  canonicalAndWitness := CanonWithWitness(transformed);
  target := LookupDictionary(dictionary, TupleKey(canonicalAndWitness[1]));
  if target = fail then Error("real transform leaves enumerated component"); fi;
  Add(realMapping, target - 1);
  Add(realTransitions, [target - 1, ImageList(canonicalAndWitness[2])]);
  if target = index then Add(innerFixedIndices, index - 1); fi;
od;

if Length(vertices) <> 1428 then Error("unexpected component cardinality"); fi;
if Length(c1Indices) <> 20 then Error("unexpected c=1 count"); fi;
if Length(innerFixedIndices) <> 70 then Error("unexpected inner real fixed count"); fi;
if Set(realMapping) <> [0..Length(vertices)-1] then Error("real map is not a permutation"); fi;
if not ForAll([1..Length(vertices)], i -> realMapping[realMapping[i]+1] = i-1) then
  Error("real map is not an involution");
fi;

out := OutputTextFile(outputPath, false);;
SetPrintFormattingStatus(out, false);;
PrintTo(out, "{\n");
AppendTo(out, "  \"schema_version\": \"arbogast.example.m23-real-component.dataset/v2\",\n");
AppendTo(out, "  \"permutation_convention\": \"one-based one-line images; products act left-to-right; x^g = g^-1*x*g\",\n");
AppendTo(out, "  \"group\": {\n");
AppendTo(out, "    \"name\": \"M23\", \"degree\": 23, \"order\": 10200960,\n");
AppendTo(out, "    \"generators\": ", List(GeneratorsOfGroup(G), ImageList), ",\n");
AppendTo(out, "    \"class_representatives\": {\"2A\": ", ImageList(classRepresentatives[1]),
  ", \"3A\": ", ImageList(classRepresentatives[2]), ", \"6A\": ",
  ImageList(classRepresentatives[3]), "},\n");
AppendTo(out, "    \"centralizer_2A_generators\": ",
  List(GeneratorsOfGroup(C), ImageList), "\n  },\n");
AppendTo(out, "  \"passport\": [\"2A\", \"3A\", \"6A\", \"2A\"],\n");
AppendTo(out, "  \"pure_braid_generators\": [\n");
for index in [1..Length(pureWords)] do
  AppendTo(out, "    {\"name\": \"", pureNames[index], "\", \"word\": ",
    pureWords[index], "}");
  if index < Length(pureWords) then AppendTo(out, ","); fi;
  AppendTo(out, "\n");
od;
AppendTo(out, "  ],\n");
AppendTo(out, "  \"seed\": {\"discovery_seed\": 20260828, \"trial\": 4387, ",
  "\"raw_tuple\": ", TupleImageLists(seedRaw), ", \"canonical_vertex\": 0, ",
  "\"canonicalization_conjugator\": ", ImageList(canonicalSeedAndWitness[2]), "},\n");
AppendTo(out, "  \"vertices\": ", List(vertices, TupleImageLists), ",\n");
AppendTo(out, "  \"class_conjugators\": ", classConjugators, ",\n");
AppendTo(out, "  \"transitions\": ", transitions, ",\n");
AppendTo(out, "  \"real\": {\n");
AppendTo(out, "    \"convention\": \"kappa_i=(g_1...g_(i-1))*g_i^-1*(g_1...g_(i-1))^-1\",\n");
AppendTo(out, "    \"transitions\": ", realTransitions, ",\n");
AppendTo(out, "    \"mapping\": ", realMapping, ",\n");
AppendTo(out, "    \"inner_fixed_indices\": ", innerFixedIndices, ",\n");
AppendTo(out, "    \"c1_indices\": ", c1Indices, "\n  },\n");
AppendTo(out, "  \"completeness\": {\n");
AppendTo(out, "    \"method\": \"fix a in 2A; quotient b in 3A by C_G(a); enumerate d in 2A; force c=(a*b)^-1*d; quotient by C_C(b)\",\n");
AppendTo(out, "    \"sorted_2A_count\": ", Length(class2Elements), ",\n");
AppendTo(out, "    \"b_orbits\": ", completenessRows, ",\n");
AppendTo(out, "    \"counts\": {\"b_orbits\": ", Length(bOrbitRecords),
  ", \"accepted_forced_c\": ", class6WitnessCount,
  ", \"fixed_a_product_one_tuples\": ", fixedARawCount,
  ", \"all_inner_orbits\": ", innerOrbitCount,
  ", \"generating_inner_orbits\": ", componentOrbitCount,
  ", \"nongenerating_inner_orbits\": ", nongeneratingOrbitCount,
  ", \"generating_c1\": ", componentC1CompletenessCount,
  ", \"nongenerating_c1\": ", nongeneratingC1Count,
  ", \"weighted_mass_numerator\": 41413, \"weighted_mass_denominator\": 6}\n  },\n");
AppendTo(out, "  \"counts\": {\"vertices\": ", Length(vertices),
  ", \"pure_generators\": 6, \"directed_transitions\": ",
  Length(vertices)*6, ", \"inner_real_fixed\": ", Length(innerFixedIndices),
  ", \"c1_fixed\": ", Length(c1Indices), "}\n");
AppendTo(out, "}\n");
CloseStream(out);;

Print("BFS_DONE vertices=", Length(vertices), " directed_edges=", Length(vertices)*6,
      " c1=", Length(c1Indices), " inner_real_fixed=", Length(innerFixedIndices),
      " runtime_ms=", Runtime()-started, " output=", outputPath, "\n");
quit;
