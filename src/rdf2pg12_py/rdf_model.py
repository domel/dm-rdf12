from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from typing import Iterable


RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDF_REIFIES = "http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies"
RDF_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
RDF_DIR_LANG_STRING = "http://www.w3.org/1999/02/22-rdf-syntax-ns#dirLangString"
RDFS_RESOURCE = "http://www.w3.org/2000/01/rdf-schema#Resource"
DEFAULT_GRAPH_KEY = "@default"


@dataclass(frozen=True, slots=True)
class IriTerm:
    iri: str


@dataclass(frozen=True, slots=True)
class BlankNodeTerm:
    identifier: str


@dataclass(frozen=True, slots=True)
class LiteralTerm:
    lexical_form: str
    datatype_iri: str
    language_tag: str | None = None
    base_direction: str | None = None


@dataclass(frozen=True, slots=True)
class TripleTerm:
    subject: "RdfTerm"
    predicate: IriTerm
    object: "RdfTerm"


RdfTerm = IriTerm | BlankNodeTerm | LiteralTerm | TripleTerm


@dataclass(frozen=True, slots=True)
class RdfQuad:
    subject: RdfTerm
    predicate: IriTerm
    object: RdfTerm
    graph_name: RdfTerm | None = None


def canonical_term_key(term: RdfTerm) -> str:
    if isinstance(term, IriTerm):
        return f"iri<{term.iri}>"
    if isinstance(term, BlankNodeTerm):
        return f"bnode<{term.identifier}>"
    if isinstance(term, LiteralTerm):
        lang = term.language_tag or ""
        direction = term.base_direction or ""
        return (
            "lit<"
            f"{term.lexical_form}|{term.datatype_iri}|{lang}|{direction}"
            ">"
        )
    if isinstance(term, TripleTerm):
        return (
            "triple<<"
            f"{canonical_term_key(term.subject)}|"
            f"{canonical_term_key(term.predicate)}|"
            f"{canonical_term_key(term.object)}"
            ">>"
        )
    raise TypeError(f"Unsupported term: {term!r}")


def canonical_triple_key(subject: RdfTerm, predicate: IriTerm, object_: RdfTerm) -> str:
    return (
        "triple<<"
        f"{canonical_term_key(subject)}|"
        f"{canonical_term_key(predicate)}|"
        f"{canonical_term_key(object_)}"
        ">>"
    )


def canonical_graph_key(graph_name: RdfTerm | None) -> str:
    if graph_name is None:
        return DEFAULT_GRAPH_KEY
    return canonical_term_key(graph_name)


def stable_id(prefix: str, value: str) -> str:
    digest = sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def iter_nested_triple_terms(term: RdfTerm) -> Iterable[TripleTerm]:
    if isinstance(term, TripleTerm):
        yield term
        yield from iter_nested_triple_terms(term.subject)
        yield from iter_nested_triple_terms(term.object)


def iter_all_terms(term: RdfTerm) -> Iterable[RdfTerm]:
    yield term
    if isinstance(term, TripleTerm):
        yield from iter_all_terms(term.subject)
        yield from iter_all_terms(term.predicate)
        yield from iter_all_terms(term.object)


def iter_all_terms_in_quad(quad: RdfQuad) -> Iterable[RdfTerm]:
    yield from iter_all_terms(quad.subject)
    yield from iter_all_terms(quad.predicate)
    yield from iter_all_terms(quad.object)
    if quad.graph_name is not None:
        yield from iter_all_terms(quad.graph_name)


def term_display_name(term: RdfTerm) -> str:
    if isinstance(term, IriTerm):
        return term.iri
    if isinstance(term, BlankNodeTerm):
        return f"_:{term.identifier}"
    if isinstance(term, LiteralTerm):
        return term.lexical_form
    if isinstance(term, TripleTerm):
        return canonical_term_key(term)
    raise TypeError(term)


def local_name(value: str) -> str:
    if "#" in value:
        return value.rsplit("#", 1)[1]
    if "/" in value:
        return value.rstrip("/").rsplit("/", 1)[1]
    if ":" in value:
        return value.rsplit(":", 1)[1]
    return value


@dataclass(slots=True)
class Rdf12Dataset:
    asserted_quads: list[RdfQuad]
    triple_terms: dict[str, TripleTerm]
    referenced_triple_keys: set[tuple[str, str]]
    asserted_triple_keys: set[tuple[str, str]]
    asserted_graphs_by_triple: dict[str, set[str]]
    reifiers: dict[tuple[str, str], list[RdfTerm]]
    annotations_by_reifier: dict[tuple[str, str], list[RdfQuad]]
    explicit_types: dict[str, set[str]]

    @classmethod
    def from_asserted_quads(cls, asserted_quads: list[RdfQuad]) -> "Rdf12Dataset":
        triple_terms: dict[str, TripleTerm] = {}
        referenced_triple_keys: set[tuple[str, str]] = set()
        asserted_triple_keys: set[tuple[str, str]] = set()
        asserted_graphs_by_triple: dict[str, set[str]] = {}
        reifiers: dict[tuple[str, str], list[RdfTerm]] = {}
        annotations_by_reifier: dict[tuple[str, str], list[RdfQuad]] = {}
        explicit_types: dict[str, set[str]] = {}

        for quad in asserted_quads:
            graph_key = canonical_graph_key(quad.graph_name)
            triple_key = canonical_triple_key(quad.subject, quad.predicate, quad.object)
            asserted_triple_keys.add((graph_key, triple_key))
            asserted_graphs_by_triple.setdefault(triple_key, set()).add(graph_key)
            if (
                quad.predicate.iri == RDF_TYPE
                and isinstance(quad.object, IriTerm)
                and not isinstance(quad.subject, TripleTerm)
            ):
                explicit_types.setdefault(canonical_term_key(quad.subject), set()).add(
                    quad.object.iri
                )

            for triple_term in iter_nested_triple_terms(quad.subject):
                key = canonical_term_key(triple_term)
                triple_terms[key] = triple_term
                referenced_triple_keys.add((graph_key, key))

            for triple_term in iter_nested_triple_terms(quad.object):
                key = canonical_term_key(triple_term)
                triple_terms[key] = triple_term
                referenced_triple_keys.add((graph_key, key))

            if quad.predicate.iri == RDF_REIFIES and isinstance(quad.object, TripleTerm):
                key = canonical_term_key(quad.object)
                reifiers.setdefault((graph_key, key), []).append(quad.subject)

        reifier_term_keys = {
            (graph_key, canonical_term_key(reifier))
            for (graph_key, _), values in reifiers.items()
            for reifier in values
        }
        for quad in asserted_quads:
            scoped_subject_key = (canonical_graph_key(quad.graph_name), canonical_term_key(quad.subject))
            if scoped_subject_key in reifier_term_keys and quad.predicate.iri != RDF_REIFIES:
                annotations_by_reifier.setdefault(scoped_subject_key, []).append(quad)

        return cls(
            asserted_quads=asserted_quads,
            triple_terms=triple_terms,
            referenced_triple_keys=referenced_triple_keys,
            asserted_triple_keys=asserted_triple_keys,
            asserted_graphs_by_triple=asserted_graphs_by_triple,
            reifiers=reifiers,
            annotations_by_reifier=annotations_by_reifier,
            explicit_types=explicit_types,
        )

    def has_named_graphs(self) -> bool:
        return any(quad.graph_name is not None for quad in self.asserted_quads)

    def all_terms(self) -> dict[str, RdfTerm]:
        terms: dict[str, RdfTerm] = {}
        for quad in self.asserted_quads:
            for term in iter_all_terms_in_quad(quad):
                terms[canonical_term_key(term)] = term
        return terms

    def is_asserted_anywhere(self, triple_term: TripleTerm) -> bool:
        return canonical_term_key(triple_term) in self.asserted_graphs_by_triple

    def is_asserted_in_graph(self, triple_term: TripleTerm, graph_name: RdfTerm | None) -> bool:
        triple_key = canonical_term_key(triple_term)
        return canonical_graph_key(graph_name) in self.asserted_graphs_by_triple.get(triple_key, set())

    def is_referenced_in_graph(self, quad: RdfQuad) -> bool:
        return (
            canonical_graph_key(quad.graph_name),
            canonical_triple_key(quad.subject, quad.predicate, quad.object),
        ) in self.referenced_triple_keys

    def triple_has_annotations(self, quad: RdfQuad) -> bool:
        graph_key = canonical_graph_key(quad.graph_name)
        triple_key = canonical_triple_key(quad.subject, quad.predicate, quad.object)
        for reifier in self.reifiers.get((graph_key, triple_key), []):
            reifier_key = (graph_key, canonical_term_key(reifier))
            if self.annotations_by_reifier.get(reifier_key):
                return True
        return False
