from __future__ import annotations

from collections import defaultdict

from .pg_model import BlankNodeValue, IriValue, PgGraph
from .rdf_model import BlankNodeTerm, IriTerm, LiteralTerm, RDF_TYPE, Rdf12Dataset, RdfQuad, TripleTerm


DEFAULT_GRAPH_MARKER = "@default"
RESERVED_RESOURCE_KEYS = {"iri", "id", "rdfTypeAssertions"}
RESERVED_AUX_EDGE_LABELS = {"TT_SUBJECT", "TT_PREDICATE", "TT_OBJECT"}


def _as_iri(value) -> IriTerm:
    if isinstance(value, IriValue):
        return IriTerm(value.iri)
    if isinstance(value, str):
        return IriTerm(value)
    raise TypeError(value)


def _as_graph_name(value):
    if value is None or value == DEFAULT_GRAPH_MARKER:
        return None
    if isinstance(value, IriValue):
        return IriTerm(value.iri)
    if isinstance(value, BlankNodeValue):
        return BlankNodeTerm(value.identifier)
    if isinstance(value, str):
        return BlankNodeTerm(value)
    raise TypeError(value)


def _literal_from_properties(properties: dict) -> LiteralTerm:
    datatype = properties.get("datatype")
    if datatype is None:
        raise ValueError("Missing datatype in lossless literal encoding")
    language = properties.get("language")
    direction = properties.get("baseDirection")
    return LiteralTerm(
        lexical_form=properties["lexicalForm"],
        datatype_iri=datatype.iri if isinstance(datatype, IriValue) else datatype,
        language_tag=language,
        base_direction=direction,
    )


def _literal_values(value) -> list[LiteralTerm]:
    if isinstance(value, list):
        result: list[LiteralTerm] = []
        for item in value:
            result.extend(_literal_values(item))
        return result
    if isinstance(value, dict) and "lexicalForm" in value and "datatype" in value:
        return [_literal_from_properties(value)]
    raise ValueError("Literal-valued PG properties can be inverted only in lossless mode")


class _TermDecoder:
    def __init__(self, graph: PgGraph):
        self.node_by_id = {node.id: node for node in graph.nodes}
        self.edges_by_source: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for edge in graph.edges:
            label = edge.labels[0] if edge.labels else ""
            self.edges_by_source[edge.source][label].append(edge.target)
        self.cache: dict[str, object] = {}

    def decode(self, node_id: str):
        cached = self.cache.get(node_id)
        if cached is not None:
            return cached

        node = self.node_by_id[node_id]
        labels = set(node.labels)
        properties = node.properties

        if "TripleTerm" in labels or "RDFTripleTerm" in labels:
            subject_targets = self.edges_by_source[node_id]["TT_SUBJECT"]
            predicate_targets = self.edges_by_source[node_id]["TT_PREDICATE"]
            object_targets = self.edges_by_source[node_id]["TT_OBJECT"]
            if len(subject_targets) != 1 or len(predicate_targets) != 1 or len(object_targets) != 1:
                raise ValueError(f"Malformed triple-term node: {node_id}")
            subject = self.decode(subject_targets[0])
            predicate = self.decode(predicate_targets[0])
            object_ = self.decode(object_targets[0])
            if not isinstance(predicate, IriTerm):
                raise ValueError("Triple-term predicate is not an IRI")
            term = TripleTerm(subject, predicate, object_)
            self.cache[node_id] = term
            return term

        if "Literal" in labels or "RDFLiteral" in labels:
            if "lexicalForm" not in properties:
                raise ValueError(f"Malformed literal node: {node_id}")
            literal = _literal_from_properties(properties)
            self.cache[node_id] = literal
            return literal

        if "iri" in properties:
            term = IriTerm(properties["iri"].iri if isinstance(properties["iri"], IriValue) else properties["iri"])
            self.cache[node_id] = term
            return term
        if "id" in properties:
            term = BlankNodeTerm(properties["id"].identifier if isinstance(properties["id"], BlankNodeValue) else properties["id"])
            self.cache[node_id] = term
            return term

        raise ValueError(f"Unsupported node encoding: {node_id}")


def invert_gdm(graph: PgGraph) -> Rdf12Dataset:
    decoder = _TermDecoder(graph)
    quads: list[RdfQuad] = []
    for edge in graph.edges:
        label = edge.labels[0] if edge.labels else ""
        if label != "AssertedTriple":
            continue
        predicate_value = edge.properties.get("predicate")
        if predicate_value is None:
            raise ValueError("AssertedTriple edge without predicate property")
        graph_name = _as_graph_name(edge.properties.get("graph"))
        quads.append(
            RdfQuad(
                subject=decoder.decode(edge.source),
                predicate=_as_iri(predicate_value),
                object=decoder.decode(edge.target),
                graph_name=graph_name,
            )
        )
    return Rdf12Dataset.from_asserted_quads(quads)


def invert_cdm(graph: PgGraph) -> Rdf12Dataset:
    decoder = _TermDecoder(graph)
    quads: list[RdfQuad] = []

    for node in graph.nodes:
        labels = set(node.labels)
        if "RDFTripleTerm" in labels and node.properties.get("asserted"):
            triple_term = decoder.decode(node.id)
            graphs = node.properties.get("graphs", [DEFAULT_GRAPH_MARKER])
            if not isinstance(graphs, list):
                graphs = [graphs]
            for graph_value in graphs:
                quads.append(
                    RdfQuad(
                        subject=triple_term.subject,
                        predicate=triple_term.predicate,
                        object=triple_term.object,
                        graph_name=_as_graph_name(graph_value),
                    )
                )

    for node in graph.nodes:
        properties = node.properties
        if "iri" not in properties and "id" not in properties:
            continue
        subject = decoder.decode(node.id)
        type_assertions = properties.get("rdfTypeAssertions", [])
        if not isinstance(type_assertions, list):
            type_assertions = [type_assertions]
        for assertion in type_assertions:
            if not isinstance(assertion, dict) or "iri" not in assertion:
                raise ValueError("Malformed rdfTypeAssertions payload")
            quads.append(
                RdfQuad(
                    subject=subject,
                    predicate=IriTerm(RDF_TYPE),
                    object=_as_iri(assertion["iri"]),
                    graph_name=_as_graph_name(assertion.get("graph")),
                )
            )
        for key, value in properties.items():
            if key in RESERVED_RESOURCE_KEYS:
                continue
            for literal in _literal_values(value):
                quads.append(
                    RdfQuad(
                        subject=subject,
                        predicate=IriTerm(key),
                        object=literal,
                        graph_name=None,
                    )
                )

    for edge in graph.edges:
        label = edge.labels[0] if edge.labels else ""
        if label in RESERVED_AUX_EDGE_LABELS or label == "AssertedTriple":
            continue
        quads.append(
            RdfQuad(
                subject=decoder.decode(edge.source),
                predicate=IriTerm(label),
                object=decoder.decode(edge.target),
                graph_name=None,
            )
        )

    return Rdf12Dataset.from_asserted_quads(quads)
