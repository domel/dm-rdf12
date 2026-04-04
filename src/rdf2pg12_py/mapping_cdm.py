from __future__ import annotations

from .mapping_common import literal_to_pg_value, requires_lifting
from .pg_model import BlankNodeValue, IriValue, PgEdge, PgEdgeType, PgGraph, PgNode, PgNodeType, PgSchema
from .rdf_model import (
    BlankNodeTerm,
    IriTerm,
    LiteralTerm,
    RDF_TYPE,
    RDFS_RESOURCE,
    Rdf12Dataset,
    TripleTerm,
    canonical_term_key,
    stable_id,
)
from .schema import SchemaModel, label_for_class, label_for_property


DEFAULT_GRAPH_MARKER = "@default"


def _append_property(properties: dict, key: str, value) -> None:
    current = properties.get(key)
    if current is None:
        properties[key] = value
        return
    if isinstance(current, list):
        current.append(value)
        return
    properties[key] = [current, value]


def _append_unique_property(properties: dict, key: str, value) -> None:
    current = properties.get(key)
    if current is None:
        properties[key] = [value]
        return
    if not isinstance(current, list):
        current = [current]
        properties[key] = current
    if value not in current:
        current.append(value)


def _graph_value(graph_name):
    if graph_name is None:
        return DEFAULT_GRAPH_MARKER
    if isinstance(graph_name, IriTerm):
        return IriValue(graph_name.iri)
    if isinstance(graph_name, BlankNodeTerm):
        return BlankNodeValue(graph_name.identifier)
    raise TypeError(graph_name)


def _literal_node_properties(literal: LiteralTerm) -> dict:
    properties = {
        "lexicalForm": literal.lexical_form,
        "datatype": IriValue(literal.datatype_iri),
    }
    if literal.language_tag is not None:
        properties["language"] = literal.language_tag
    if literal.base_direction is not None:
        properties["baseDirection"] = literal.base_direction
    return properties


def map_cdm(
    dataset: Rdf12Dataset,
    schema_model: SchemaModel,
    literal_mode: str = "lossless",
    dataset_mode: str = "reject",
) -> tuple[PgGraph, PgSchema]:
    graph = PgGraph()
    schema = PgSchema()
    all_classes = set(schema_model.classes)
    all_classes.add(RDFS_RESOURCE)
    class_type_ids = {class_iri: stable_id("s", class_iri) for class_iri in sorted(all_classes)}
    inferred_types: dict[str, set[str]] = {}
    for quad in dataset.asserted_quads:
        prop_shape = schema_model.properties.get(quad.predicate.iri)
        if prop_shape is None:
            continue
        inferred_types.setdefault(canonical_term_key(quad.subject), set()).add(prop_shape.preferred_domain())
        if isinstance(quad.object, (IriTerm, BlankNodeTerm)) and not prop_shape.is_datatype_property(schema_model.datatypes):
            inferred_types.setdefault(canonical_term_key(quad.object), set()).add(prop_shape.preferred_range())
    node_type_props = {
        class_iri: {"iri": "STRING", "id": "STRING", "rdfTypeAssertions": "LIST"}
        for class_iri in all_classes
    }
    for prop in schema_model.properties.values():
        if prop.is_datatype_property(schema_model.datatypes):
            node_type_props.setdefault(
                prop.preferred_domain(),
                {"iri": "STRING", "id": "STRING", "rdfTypeAssertions": "LIST"},
            )[
                label_for_property(prop.iri, compact=False)
            ] = "VALUE"
    schema.node_types.append(
        PgNodeType(
            "RDFResource",
            ["RDFResource"],
            {"iri": "STRING", "id": "STRING", "rdfTypeAssertions": "LIST"},
        )
    )
    for class_iri in sorted(all_classes):
        schema.node_types.append(
            PgNodeType(
                class_type_ids[class_iri],
                [label_for_class(class_iri, compact=False)],
                node_type_props[class_iri],
            )
        )
    schema.node_types.extend(
        [
            PgNodeType(
                "RDFTripleTerm",
                ["RDFTripleTerm"],
                {"tripleKey": "STRING", "asserted": "BOOL", "graphs": "LIST"},
            ),
            PgNodeType(
                "RDFLiteral",
                ["RDFLiteral"],
                {
                    "lexicalForm": "STRING",
                    "datatype": "STRING",
                    "language": "STRING",
                    "baseDirection": "STRING",
                },
            ),
        ]
    )
    for prop in sorted(schema_model.properties.values(), key=lambda p: p.iri):
        if not prop.is_datatype_property(schema_model.datatypes):
            schema.edge_types.append(
                PgEdgeType(
                    class_type_ids[prop.preferred_domain()],
                    class_type_ids.get(prop.preferred_range(), class_type_ids[RDFS_RESOURCE]),
                    [label_for_property(prop.iri, compact=False)],
                    {},
                )
            )
    schema.edge_types.extend(
        [
            PgEdgeType("RDFTripleTerm", "RDFResource", ["TT_SUBJECT"], {}),
            PgEdgeType("RDFTripleTerm", "RDFResource", ["TT_OBJECT"], {}),
            PgEdgeType("RDFTripleTerm", "RDFResource", ["TT_PREDICATE"], {}),
            PgEdgeType("RDFTripleTerm", "RDFLiteral", ["TT_OBJECT"], {}),
            PgEdgeType("RDFTripleTerm", "RDFTripleTerm", ["TT_OBJECT"], {}),
        ]
    )

    resource_terms: dict[str, IriTerm | BlankNodeTerm] = {}
    for key, term in dataset.all_terms().items():
        if isinstance(term, (IriTerm, BlankNodeTerm)):
            resource_terms[key] = term
    visible_labels_by_term: dict[str, list[str]] = {}
    for key in sorted(resource_terms):
        explicit_types = sorted(
            type_iri for type_iri in dataset.explicit_types.get(key, set()) if type_iri in all_classes
        )
        derived_types = sorted(type_iri for type_iri in inferred_types.get(key, set()) if type_iri in all_classes)
        visible_labels: list[str] = []
        for type_iri in explicit_types + derived_types:
            if type_iri not in visible_labels:
                visible_labels.append(type_iri)
        if not visible_labels:
            visible_labels.append(RDFS_RESOURCE)
        visible_labels_by_term[key] = visible_labels
    node_ids = {key: stable_id("n", key) for key in sorted(resource_terms)}
    nodes_by_id: dict[str, PgNode] = {}
    triple_edge_keys: set[tuple[str, str, str]] = set()

    def register_node(node: PgNode) -> PgNode:
        existing = nodes_by_id.get(node.id)
        if existing is None:
            nodes_by_id[node.id] = node
            graph.nodes.append(node)
            return node
        for label in node.labels:
            if label not in existing.labels:
                existing.labels.append(label)
        for key, value in node.properties.items():
            existing.properties.setdefault(key, value)
        return existing

    def ensure_resource_node(term_key: str) -> str:
        term = resource_terms[term_key]
        labels = list(visible_labels_by_term[term_key])
        labels.append("RDFResource")
        props = {"iri": term.iri} if isinstance(term, IriTerm) else {"id": term.identifier}
        register_node(PgNode(node_ids[term_key], labels, props))
        return node_ids[term_key]

    def ensure_literal_node(term: LiteralTerm) -> str:
        term_key = canonical_term_key(term)
        node_id = stable_id("lit", term_key)
        register_node(PgNode(node_id, ["RDFLiteral"], _literal_node_properties(term)))
        return node_id

    def ensure_term_node(term) -> str:
        if isinstance(term, (IriTerm, BlankNodeTerm)):
            return ensure_resource_node(canonical_term_key(term))
        if isinstance(term, LiteralTerm):
            return ensure_literal_node(term)
        if isinstance(term, TripleTerm):
            return ensure_triple_term_node(term)
        raise TypeError(term)

    def ensure_triple_term_node(term: TripleTerm) -> str:
        term_key = canonical_term_key(term)
        node_id = stable_id("tt", term_key)
        node = register_node(
            PgNode(
                node_id,
                ["RDFTripleTerm"],
                {"tripleKey": term_key, "asserted": False},
            )
        )
        for edge_label, component in (
            ("TT_SUBJECT", term.subject),
            ("TT_PREDICATE", term.predicate),
            ("TT_OBJECT", term.object),
        ):
            target_id = ensure_term_node(component)
            edge_key = (node_id, edge_label, target_id)
            if edge_key not in triple_edge_keys:
                triple_edge_keys.add(edge_key)
                graph.edges.append(PgEdge(node_id, target_id, [edge_label]))
        return node_id

    def add_type_assertion(subject_node: PgNode, type_iri: str, graph_name) -> None:
        assertion = {"iri": IriValue(type_iri)}
        if dataset_mode in {"named-graph-property", "native"} and graph_name is not None:
            assertion["graph"] = _graph_value(graph_name)
        _append_unique_property(subject_node.properties, "rdfTypeAssertions", assertion)

    def add_asserted_graph_membership(node_id: str, graph_name) -> None:
        node = nodes_by_id[node_id]
        node.properties["asserted"] = True
        _append_unique_property(node.properties, "graphs", _graph_value(graph_name))

    def should_use_user_path(quad) -> bool:
        if requires_lifting(dataset, quad):
            return False
        if dataset_mode in {"named-graph-property", "native"} and quad.graph_name is not None:
            return False
        if quad.predicate.iri == RDF_TYPE and isinstance(quad.object, IriTerm):
            return False
        prop_shape = schema_model.properties.get(quad.predicate.iri)
        if prop_shape is None:
            return False
        subject_labels = set(visible_labels_by_term[canonical_term_key(quad.subject)])
        if prop_shape.preferred_domain() not in subject_labels:
            return False
        if isinstance(quad.object, (IriTerm, BlankNodeTerm)):
            if prop_shape.is_datatype_property(schema_model.datatypes):
                return False
            object_labels = set(visible_labels_by_term[canonical_term_key(quad.object)])
            return prop_shape.preferred_range() in object_labels
        if isinstance(quad.object, LiteralTerm):
            return prop_shape.is_datatype_property(schema_model.datatypes)
        return False

    for key in sorted(resource_terms):
        ensure_resource_node(key)

    for quad in dataset.asserted_quads:
        if quad.predicate.iri == RDF_TYPE and isinstance(quad.object, IriTerm) and not requires_lifting(dataset, quad):
            subject_id = ensure_resource_node(canonical_term_key(quad.subject))
            add_type_assertion(nodes_by_id[subject_id], quad.object.iri, quad.graph_name)
            continue
        if not should_use_user_path(quad):
            triple_node_id = ensure_triple_term_node(TripleTerm(quad.subject, quad.predicate, quad.object))
            add_asserted_graph_membership(triple_node_id, quad.graph_name)
            continue

        subject_id = node_ids[canonical_term_key(quad.subject)]
        if isinstance(quad.object, (IriTerm, BlankNodeTerm)):
            graph.edges.append(PgEdge(subject_id, node_ids[canonical_term_key(quad.object)], [quad.predicate.iri]))
        elif isinstance(quad.object, LiteralTerm):
            subject_node = nodes_by_id[subject_id]
            _append_property(
                subject_node.properties,
                quad.predicate.iri,
                literal_to_pg_value(
                    quad.object,
                    lossless=literal_mode == "lossless",
                ),
            )

    return graph, schema
