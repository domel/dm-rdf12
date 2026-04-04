from __future__ import annotations

from pathlib import Path

from rdf2pg12_py.inverse_mapping import invert_cdm, invert_gdm
from rdf2pg12_py.io_rdf import read_rdf
from rdf2pg12_py.mapping_cdm import map_cdm
from rdf2pg12_py.mapping_common import requires_lifting
from rdf2pg12_py.mapping_gdm import map_gdm
from rdf2pg12_py.mapping_sdm import map_sdm
from rdf2pg12_py.pg_model import BlankNodeValue, IriValue
from rdf2pg12_py.rdf_model import IriTerm, TripleTerm, canonical_term_key
from rdf2pg12_py.schema import extract_schema


ROOT = Path(__file__).resolve().parents[1]


def _quad_key(quad) -> tuple[str, str, str, str | None]:
    return (
        canonical_term_key(quad.subject),
        canonical_term_key(quad.predicate),
        canonical_term_key(quad.object),
        canonical_term_key(quad.graph_name) if quad.graph_name is not None else None,
    )


def _assert_same_quads(left, right) -> None:
    assert sorted(_quad_key(quad) for quad in left.asserted_quads) == sorted(
        _quad_key(quad) for quad in right.asserted_quads
    )


def test_gdm_roundtrip_preserves_annotated_rdf12_input() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")

    graph, _ = map_gdm(dataset)
    recovered = invert_gdm(graph)

    _assert_same_quads(dataset, recovered)


def test_gdm_roundtrip_preserves_named_graph_dataset() -> None:
    dataset = read_rdf(ROOT / "testdata/dataset/named.trig", dataset_mode="native")

    graph, _ = map_gdm(dataset, dataset_mode="native")
    recovered = invert_gdm(graph)

    _assert_same_quads(dataset, recovered)


def _write_blank_node_graph_fixture(tmp_path: Path) -> tuple[Path, Path]:
    dataset_path = tmp_path / "named-bnode.trig"
    dataset_path.write_text(
        "\n".join(
            [
                'VERSION "1.2"',
                "PREFIX ex: <http://example.com/>",
                "",
                "_:g {",
                "  ex:a a ex:Thing ;",
                '      ex:name "Alice" ;',
                "      ex:related ex:b .",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    schema_path = tmp_path / "schema.ttl"
    schema_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
                "",
                "ex:Thing rdf:type rdfs:Class .",
                "ex:related rdf:type rdf:Property ;",
                "    rdfs:domain ex:Thing ;",
                "    rdfs:range ex:Thing .",
                "ex:name rdf:type rdf:Property ;",
                "    rdfs:domain ex:Thing ;",
                "    rdfs:range xsd:string .",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return dataset_path, schema_path


def test_gdm_roundtrip_preserves_blank_node_named_graph_dataset(tmp_path: Path) -> None:
    dataset_path, _ = _write_blank_node_graph_fixture(tmp_path)
    dataset = read_rdf(dataset_path, dataset_mode="native")

    graph, _ = map_gdm(dataset, dataset_mode="native")
    recovered = invert_gdm(graph)

    assert all(edge.properties.get("graph") == "g" for edge in graph.edges if edge.labels == ["AssertedTriple"])
    _assert_same_quads(dataset, recovered)


def test_gdm_triple_term_nodes_do_not_store_global_asserted_flag() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")

    graph, _ = map_gdm(dataset)

    triple_term_nodes = [node for node in graph.nodes if "TripleTerm" in node.labels]
    assert triple_term_nodes
    assert all("asserted" not in node.properties for node in triple_term_nodes)


def test_cdm_roundtrip_preserves_annotated_fragment_with_auxiliary_layer() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")
    schema_dataset = read_rdf(ROOT / "testdata/rdf12/annotated-schema.ttl", dataset_mode="flatten")

    graph, _ = map_cdm(dataset, extract_schema(schema_dataset), literal_mode="lossless")
    recovered = invert_cdm(graph)

    _assert_same_quads(dataset, recovered)


def test_cdm_roundtrip_preserves_named_graph_fragment_in_native_mode() -> None:
    dataset = read_rdf(ROOT / "testdata/dataset/named.trig", dataset_mode="native")
    schema_dataset = read_rdf(ROOT / "testdata/dataset/named-schema.ttl", dataset_mode="flatten")

    graph, _ = map_cdm(
        dataset,
        extract_schema(schema_dataset),
        literal_mode="lossless",
        dataset_mode="native",
    )
    recovered = invert_cdm(graph)

    _assert_same_quads(dataset, recovered)


def test_cdm_roundtrip_preserves_blank_node_named_graph_fragment_in_native_mode(tmp_path: Path) -> None:
    dataset_path, schema_path = _write_blank_node_graph_fixture(tmp_path)
    dataset = read_rdf(dataset_path, dataset_mode="native")
    schema_dataset = read_rdf(schema_path, dataset_mode="flatten")

    graph, _ = map_cdm(
        dataset,
        extract_schema(schema_dataset),
        literal_mode="lossless",
        dataset_mode="native",
    )
    recovered = invert_cdm(graph)

    subject = next(node for node in graph.nodes if node.properties.get("iri") == "http://example.com/a")
    assert subject.properties["rdfTypeAssertions"] == [
        {"iri": IriValue("http://example.com/Thing"), "graph": BlankNodeValue("g")}
    ]
    asserted_nodes = [node for node in graph.nodes if "RDFTripleTerm" in node.labels and node.properties.get("asserted")]
    assert asserted_nodes
    assert all(node.properties.get("graphs") == [BlankNodeValue("g")] for node in asserted_nodes)
    _assert_same_quads(dataset, recovered)


def test_cdm_routes_undeclared_predicates_to_auxiliary_layer() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")
    schema_dataset = read_rdf(ROOT / "testdata/rdf11/simple-schema.ttl", dataset_mode="flatten")

    graph, _ = map_cdm(dataset, extract_schema(schema_dataset), literal_mode="lossless")

    ordinary_edge_labels = {edge.labels[0] for edge in graph.edges if edge.labels and not edge.labels[0].startswith("TT_")}
    assert "http://example.com/statedBy" not in ordinary_edge_labels
    resource_properties = {
        key
        for node in graph.nodes
        if "RDFResource" in node.labels
        for key in node.properties
    }
    assert "http://example.com/recorded" not in resource_properties
    assert any("RDFTripleTerm" in node.labels and node.properties.get("asserted") for node in graph.nodes)


def test_cdm_does_not_treat_arbitrary_rdf_namespace_ranges_as_literal_properties(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.ttl"
    schema_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                "",
                "ex:Thing rdf:type rdfs:Class .",
                "ex:related rdf:type rdf:Property ;",
                "    rdfs:domain ex:Thing ;",
                "    rdfs:range rdf:Property .",
                "",
            ]
        ),
        encoding="utf-8",
    )
    data_path = tmp_path / "data.ttl"
    data_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "",
                "ex:a ex:related ex:b .",
                "",
            ]
        ),
        encoding="utf-8",
    )

    schema = extract_schema(read_rdf(schema_path, dataset_mode="flatten"))
    graph, _ = map_cdm(read_rdf(data_path), schema, literal_mode="lossless")

    assert not schema.properties["http://example.com/related"].is_datatype_property(schema.datatypes)
    assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property" in schema.classes
    ordinary_edge_labels = {edge.labels[0] for edge in graph.edges if edge.labels and not edge.labels[0].startswith("TT_")}
    assert "http://example.com/related" in ordinary_edge_labels
    resource_properties = {
        key
        for node in graph.nodes
        if "RDFResource" in node.labels
        for key in node.properties
    }
    assert "http://example.com/related" not in resource_properties


def test_cdm_accepts_explicit_rdfs_datatype_ranges_in_rdf12_schema(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.ttl"
    schema_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                "",
                "ex:Thing rdf:type rdfs:Class .",
                "ex:customLiteral rdf:type rdf:Property ;",
                "    rdfs:domain ex:Thing ;",
                "    rdfs:range ex:Token .",
                "ex:Token rdf:type rdfs:Datatype .",
                "",
            ]
        ),
        encoding="utf-8",
    )
    data_path = tmp_path / "data.ttl"
    data_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "",
                'ex:a ex:customLiteral "abc"^^ex:Token .',
                "",
            ]
        ),
        encoding="utf-8",
    )

    schema = extract_schema(read_rdf(schema_path, dataset_mode="flatten"))
    graph, _ = map_cdm(read_rdf(data_path), schema, literal_mode="lossless")

    assert schema.properties["http://example.com/customLiteral"].is_datatype_property(schema.datatypes)
    assert "http://example.com/Token" in schema.datatypes
    assert "http://example.com/Token" not in schema.classes
    ordinary_edge_labels = {edge.labels[0] for edge in graph.edges if edge.labels and not edge.labels[0].startswith("TT_")}
    assert "http://example.com/customLiteral" not in ordinary_edge_labels
    subject = next(node for node in graph.nodes if node.properties.get("iri") == "http://example.com/a")
    assert "http://example.com/customLiteral" in subject.properties


def test_cdm_resource_nodes_carry_compatible_inferred_labels_for_user_visible_path(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.ttl"
    schema_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                "",
                "ex:Person rdf:type rdfs:Class .",
                "ex:Place rdf:type rdfs:Class .",
                "ex:worksWith rdf:type rdf:Property ;",
                "    rdfs:domain ex:Person ;",
                "    rdfs:range ex:Person .",
                "",
            ]
        ),
        encoding="utf-8",
    )
    data_path = tmp_path / "data.ttl"
    data_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "",
                "ex:a a ex:Place ;",
                "    ex:worksWith ex:b .",
                "ex:b a ex:Place .",
                "",
            ]
        ),
        encoding="utf-8",
    )

    schema = extract_schema(read_rdf(schema_path, dataset_mode="flatten"))
    graph, _ = map_cdm(read_rdf(data_path), schema, literal_mode="lossless")

    ordinary_edge_labels = {edge.labels[0] for edge in graph.edges if edge.labels and not edge.labels[0].startswith("TT_")}
    assert "http://example.com/worksWith" in ordinary_edge_labels

    node_a = next(node for node in graph.nodes if node.properties.get("iri") == "http://example.com/a")
    node_b = next(node for node in graph.nodes if node.properties.get("iri") == "http://example.com/b")
    assert "http://example.com/Place" in node_a.labels
    assert "http://example.com/Person" in node_a.labels
    assert "http://example.com/Person" in node_b.labels


def test_cross_graph_reification_does_not_create_local_annotation_for_default_graph_assertion(tmp_path: Path) -> None:
    dataset_path = tmp_path / "cross-graph-annotation.trig"
    dataset_path.write_text(
        "\n".join(
            [
                'VERSION "1.2"',
                "PREFIX ex: <http://example.com/>",
                "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>",
                "",
                "{",
                "  ex:a ex:related ex:b .",
                "}",
                "",
                "ex:g {",
                "  ex:r rdf:reifies <<( ex:a ex:related ex:b )>> .",
                "  ex:r ex:source ex:c .",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    dataset = read_rdf(dataset_path, dataset_mode="native")
    asserted = next(
        quad
        for quad in dataset.asserted_quads
        if quad.graph_name is None and quad.predicate == IriTerm("http://example.com/related")
    )

    assert not dataset.triple_has_annotations(asserted)
    assert not requires_lifting(dataset, asserted)


def test_cdm_keeps_cross_graph_quoted_default_triple_on_compact_path(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.ttl"
    schema_path.write_text(
        "\n".join(
            [
                "@prefix ex: <http://example.com/> .",
                "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
                "",
                "ex:related rdf:type rdf:Property ;",
                "    rdfs:domain rdfs:Resource ;",
                "    rdfs:range rdfs:Resource .",
                "ex:mentions rdf:type rdf:Property ;",
                "    rdfs:domain rdfs:Resource ;",
                "    rdfs:range rdfs:Resource .",
                "",
            ]
        ),
        encoding="utf-8",
    )
    dataset_path = tmp_path / "dataset.trig"
    dataset_path.write_text(
        "\n".join(
            [
                'VERSION "1.2"',
                "PREFIX ex: <http://example.com/>",
                "",
                "{",
                "  ex:a ex:related ex:b .",
                "}",
                "",
                "ex:g {",
                "  ex:root ex:mentions <<( ex:a ex:related ex:b )>> .",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    dataset = read_rdf(dataset_path, dataset_mode="native")
    schema = extract_schema(read_rdf(schema_path, dataset_mode="flatten"))
    graph, _ = map_cdm(dataset, schema, literal_mode="lossless", dataset_mode="native")
    recovered = invert_cdm(graph)

    ordinary_edge_labels = {edge.labels[0] for edge in graph.edges if edge.labels and not edge.labels[0].startswith("TT_")}
    assert "http://example.com/related" in ordinary_edge_labels

    quoted_triple_key = canonical_term_key(
        TripleTerm(
            IriTerm("http://example.com/a"),
            IriTerm("http://example.com/related"),
            IriTerm("http://example.com/b"),
        )
    )
    quoted_triple_node = next(
        node
        for node in graph.nodes
        if "RDFTripleTerm" in node.labels and node.properties.get("tripleKey") == quoted_triple_key
    )
    assert quoted_triple_node.properties.get("asserted") is False
    assert "graphs" not in quoted_triple_node.properties

    _assert_same_quads(dataset, recovered)


def test_sdm_materializes_lifted_literal_objects_as_statement_object_nodes() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")

    graph, _ = map_sdm(dataset, literal_mode="lossless")

    statement_object = next(
        node
        for node in graph.nodes
        if "StatementObject" in node.labels and isinstance(node.properties.get("value"), dict)
    )
    assert statement_object.properties["value"]["lexicalForm"] == "Alice"
    assert statement_object.properties["value"]["datatype"].iri == "http://www.w3.org/2001/XMLSchema#string"
    assert any(edge.labels == ["OBJECT"] and edge.target == statement_object.id for edge in graph.edges)


def test_sdm_materializes_lifted_triple_term_objects_as_statement_object_nodes() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/reified-triple.ttl")

    graph, _ = map_sdm(dataset, literal_mode="lossless")

    reifies_quad = next(
        quad
        for quad in dataset.asserted_quads
        if quad.predicate == IriTerm("http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies")
    )
    assert isinstance(reifies_quad.object, TripleTerm)
    quoted_triple_key = canonical_term_key(reifies_quad.object)

    statement_object = next(
        node
        for node in graph.nodes
        if "StatementObject" in node.labels and node.properties.get("value") == quoted_triple_key
    )
    assert any(edge.labels == ["OBJECT"] and edge.target == statement_object.id for edge in graph.edges)


def test_cdm_reifiers_remain_regular_resources_without_dedicated_aux_type() -> None:
    dataset = read_rdf(ROOT / "testdata/rdf12/annotated-short.ttl")
    schema_dataset = read_rdf(ROOT / "testdata/rdf12/annotated-schema.ttl", dataset_mode="flatten")

    graph, schema = map_cdm(dataset, extract_schema(schema_dataset), literal_mode="lossless")

    schema_type_ids = {node_type.id for node_type in schema.node_types}
    assert "RDFReifier" not in schema_type_ids
    assert all("RDFReifier" not in node.labels for node in graph.nodes)

    reifier_node = next(node for node in graph.nodes if node.properties.get("iri") == "http://example.com/t")
    assert "RDFResource" in reifier_node.labels
