from __future__ import annotations

from .pg_model import BlankNodeValue, IriValue, PgValue
from .rdf_model import (
    BlankNodeTerm,
    IriTerm,
    LiteralTerm,
    RDF_REIFIES,
    RDF_TYPE,
    Rdf12Dataset,
    RdfQuad,
    TripleTerm,
    canonical_term_key,
    local_name,
)


def requires_lifting(dataset: Rdf12Dataset, quad: RdfQuad) -> bool:
    if dataset.is_referenced_in_graph(quad):
        return True
    if quad.predicate.iri == RDF_REIFIES and isinstance(quad.object, TripleTerm):
        return True
    if isinstance(quad.object, TripleTerm):
        return True
    if dataset.triple_has_annotations(quad):
        return True
    return False


def node_type_label(dataset: Rdf12Dataset, term_key: str, default_label: str, compact: bool) -> str:
    explicit_types = sorted(dataset.explicit_types.get(term_key, []))
    if explicit_types:
        selected = explicit_types[0]
        return local_name(selected) if compact else selected
    return default_label


def literal_to_pg_value(literal: LiteralTerm, lossless: bool) -> PgValue:
    if not lossless and literal.language_tag is None and literal.base_direction is None:
        return literal.lexical_form
    value: dict[str, PgValue] = {
        "lexicalForm": literal.lexical_form,
        "datatype": IriValue(literal.datatype_iri),
    }
    if literal.language_tag is not None:
        value["language"] = literal.language_tag
    if literal.base_direction is not None:
        value["baseDirection"] = literal.base_direction
    return value


def term_property_value(term):
    if isinstance(term, IriTerm):
        return IriValue(term.iri)
    if isinstance(term, BlankNodeTerm):
        return BlankNodeValue(term.identifier)
    if isinstance(term, LiteralTerm):
        return literal_to_pg_value(term, lossless=True)
    if isinstance(term, TripleTerm):
        return canonical_term_key(term)
    raise TypeError(term)
