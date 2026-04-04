from __future__ import annotations

from .mapping_common import literal_to_pg_value, node_type_label, requires_lifting, term_property_value
from .pg_model import PgEdge, PgEdgeType, PgGraph, PgNode, PgNodeType, PgSchema
from .rdf_model import (
    BlankNodeTerm,
    IriTerm,
    LiteralTerm,
    RDF_TYPE,
    RDFS_RESOURCE,
    Rdf12Dataset,
    TripleTerm,
    canonical_term_key,
    canonical_triple_key,
    local_name,
    stable_id,
)


def map_sdm(dataset: Rdf12Dataset, literal_mode: str = "lossless") -> tuple[PgGraph, PgSchema]:
    graph = PgGraph()
    schema = PgSchema(
        node_types=[
            PgNodeType("Resource", ["Resource"], {"iri": "STRING", "id": "STRING"}),
            PgNodeType("Statement", ["Statement"], {"predicate": "STRING", "asserted": "BOOL"}),
            PgNodeType("StatementObject", ["StatementObject"], {"value": "STRING"}),
        ],
        edge_types=[
            PgEdgeType("Resource", "Resource", ["RELATED_TO"], {"predicate": "STRING"}),
            PgEdgeType("Statement", "Resource", ["SUBJECT"], {}),
            PgEdgeType("Statement", "Resource", ["OBJECT"], {}),
            PgEdgeType("Statement", "Statement", ["OBJECT"], {}),
            PgEdgeType("Statement", "StatementObject", ["OBJECT"], {}),
        ],
    )

    resource_terms: dict[str, IriTerm | BlankNodeTerm] = {}
    for key, term in dataset.all_terms().items():
        if isinstance(term, (IriTerm, BlankNodeTerm)):
            resource_terms[key] = term

    node_ids = {key: stable_id("n", key) for key in sorted(resource_terms)}
    for key, term in sorted(resource_terms.items()):
        label = node_type_label(dataset, key, "Resource", compact=True)
        properties = {}
        if isinstance(term, IriTerm):
            properties["iri"] = term.iri
        else:
            properties["id"] = term.identifier
        graph.nodes.append(PgNode(node_ids[key], [label], properties))

    for quad in dataset.asserted_quads:
        if quad.predicate.iri == RDF_TYPE and isinstance(quad.object, IriTerm) and not requires_lifting(dataset, quad):
            continue
        if requires_lifting(dataset, quad):
            statement_key = canonical_triple_key(quad.subject, quad.predicate, quad.object)
            statement_id = stable_id("stmt", statement_key)
            graph.nodes.append(
                PgNode(
                    statement_id,
                    ["Statement"],
                    {"predicate": local_name(quad.predicate.iri), "asserted": True},
                )
            )
            graph.edges.append(PgEdge(statement_id, node_ids[canonical_term_key(quad.subject)], ["SUBJECT"]))
            if isinstance(quad.object, (IriTerm, BlankNodeTerm)):
                graph.edges.append(PgEdge(statement_id, node_ids[canonical_term_key(quad.object)], ["OBJECT"]))
            else:
                object_statement_id = stable_id("obj", canonical_term_key(quad.object))
                graph.nodes.append(
                    PgNode(
                        object_statement_id,
                        ["StatementObject"],
                        {"value": term_property_value(quad.object)},
                    )
                )
                graph.edges.append(PgEdge(statement_id, object_statement_id, ["OBJECT"]))
            continue

        subject_id = node_ids[canonical_term_key(quad.subject)]
        predicate_label = local_name(quad.predicate.iri)
        if isinstance(quad.object, (IriTerm, BlankNodeTerm)):
            graph.edges.append(
                PgEdge(subject_id, node_ids[canonical_term_key(quad.object)], [predicate_label])
            )
        elif isinstance(quad.object, LiteralTerm):
            subject_node = next(node for node in graph.nodes if node.id == subject_id)
            subject_node.properties[predicate_label] = literal_to_pg_value(
                quad.object,
                lossless=literal_mode == "lossless",
            )
        elif isinstance(quad.object, TripleTerm):
            statement_id = stable_id("stmt", canonical_triple_key(quad.subject, quad.predicate, quad.object))
            graph.nodes.append(PgNode(statement_id, ["Statement"], {"predicate": predicate_label, "asserted": True}))

    return graph, schema
