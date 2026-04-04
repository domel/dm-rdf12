from __future__ import annotations

from .pg_model import IriValue, PgEdge, PgEdgeType, PgGraph, PgNode, PgNodeType, PgSchema
from .rdf_model import (
    BlankNodeTerm,
    IriTerm,
    LiteralTerm,
    Rdf12Dataset,
    TripleTerm,
    canonical_term_key,
    stable_id,
)


def _term_node(term) -> PgNode:
    key = canonical_term_key(term)
    node_id = stable_id("n", key)
    if isinstance(term, IriTerm):
        return PgNode(node_id, ["IRI"], {"iri": IriValue(term.iri)})
    if isinstance(term, BlankNodeTerm):
        return PgNode(node_id, ["BlankNode"], {"id": term.identifier})
    if isinstance(term, LiteralTerm):
        props = {
            "lexicalForm": term.lexical_form,
            "datatype": IriValue(term.datatype_iri),
        }
        if term.language_tag is not None:
            props["language"] = term.language_tag
        if term.base_direction is not None:
            props["baseDirection"] = term.base_direction
        return PgNode(node_id, ["Literal"], props)
    if isinstance(term, TripleTerm):
        return PgNode(node_id, ["TripleTerm"], {"tripleKey": key})
    raise TypeError(term)


def map_gdm(dataset: Rdf12Dataset, dataset_mode: str = "reject") -> tuple[PgGraph, PgSchema]:
    graph = PgGraph()
    schema = PgSchema(
        node_types=[
            PgNodeType("IRI", ["IRI"], {"iri": "STRING"}),
            PgNodeType("BlankNode", ["BlankNode"], {"id": "STRING"}),
            PgNodeType(
                "Literal",
                ["Literal"],
                {
                    "lexicalForm": "STRING",
                    "datatype": "STRING",
                    "language": "STRING",
                    "baseDirection": "STRING",
                },
            ),
            PgNodeType("TripleTerm", ["TripleTerm"], {"tripleKey": "STRING"}),
        ],
        edge_types=[
            PgEdgeType("IRI", "IRI", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("IRI", "BlankNode", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("IRI", "Literal", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("IRI", "TripleTerm", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("BlankNode", "IRI", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("BlankNode", "BlankNode", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("BlankNode", "Literal", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("BlankNode", "TripleTerm", ["AssertedTriple"], {"predicate": "STRING", "graph": "STRING"}),
            PgEdgeType("TripleTerm", "IRI", ["TT_SUBJECT"], {}),
            PgEdgeType("TripleTerm", "BlankNode", ["TT_SUBJECT"], {}),
            PgEdgeType("TripleTerm", "IRI", ["TT_PREDICATE"], {}),
            PgEdgeType("TripleTerm", "IRI", ["TT_OBJECT"], {}),
            PgEdgeType("TripleTerm", "BlankNode", ["TT_OBJECT"], {}),
            PgEdgeType("TripleTerm", "Literal", ["TT_OBJECT"], {}),
            PgEdgeType("TripleTerm", "TripleTerm", ["TT_OBJECT"], {}),
        ],
    )

    all_terms = dataset.all_terms()
    term_ids = {key: stable_id("n", key) for key in sorted(all_terms)}
    for key in sorted(all_terms):
        graph.nodes.append(_term_node(all_terms[key]))

    for key in sorted(dataset.triple_terms):
        triple_term = dataset.triple_terms[key]
        triple_term_id = term_ids[key]
        graph.edges.append(PgEdge(triple_term_id, term_ids[canonical_term_key(triple_term.subject)], ["TT_SUBJECT"]))
        graph.edges.append(PgEdge(triple_term_id, term_ids[canonical_term_key(triple_term.predicate)], ["TT_PREDICATE"]))
        graph.edges.append(PgEdge(triple_term_id, term_ids[canonical_term_key(triple_term.object)], ["TT_OBJECT"]))

    for quad in dataset.asserted_quads:
        properties = {"predicate": IriValue(quad.predicate.iri)}
        if quad.graph_name is not None and dataset_mode in {"named-graph-property", "native"}:
            if isinstance(quad.graph_name, IriTerm):
                properties["graph"] = IriValue(quad.graph_name.iri)
            elif isinstance(quad.graph_name, BlankNodeTerm):
                properties["graph"] = quad.graph_name.identifier
        graph.edges.append(
            PgEdge(
                term_ids[canonical_term_key(quad.subject)],
                term_ids[canonical_term_key(quad.object)],
                ["AssertedTriple"],
                properties,
            )
        )

    return graph, schema
