from __future__ import annotations

from pathlib import Path

import pytest

from rdf2pg12_py.io_rdf import read_rdf
from rdf2pg12_py.rdf_model import BlankNodeTerm, IriTerm, LiteralTerm, RDF_DIR_LANG_STRING, RDF_REIFIES, TripleTerm
from rdf2pg12_py.rdf12_parser import parse_rdf_file


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str, *, dataset_mode: str = "reject"):
    return read_rdf(ROOT / rel_path, dataset_mode=dataset_mode)


def test_triple_term_object_is_preserved() -> None:
    dataset = _read("testdata/rdf12/unasserted-triple-term.ttl")

    assert len(dataset.asserted_quads) == 1
    quad = dataset.asserted_quads[0]
    assert quad.subject == IriTerm("http://example.com/alice")
    assert quad.predicate == IriTerm("http://example.com/says")
    assert isinstance(quad.object, TripleTerm)
    assert quad.object.subject == IriTerm("http://example.com/bob")
    assert quad.object.predicate == IriTerm("http://example.com/knows")
    assert quad.object.object == IriTerm("http://example.com/carol")


def test_reified_triple_shorthand_expands_to_reifier_triple() -> None:
    dataset = _read("testdata/rdf12/reified-triple.ttl")

    assert len(dataset.asserted_quads) == 3
    reifies = [quad for quad in dataset.asserted_quads if quad.predicate.iri == RDF_REIFIES]
    assert len(reifies) == 1
    assert isinstance(reifies[0].object, TripleTerm)
    assert reifies[0].subject == IriTerm("http://example.com/id")

    according_to = [quad for quad in dataset.asserted_quads if quad.predicate == IriTerm("http://example.com/accordingTo")]
    assert len(according_to) == 1
    assert according_to[0].subject == IriTerm("http://example.com/id")
    assert according_to[0].object == IriTerm("http://example.com/employee22")


def test_annotation_syntax_expands_to_asserted_and_reifier_triples() -> None:
    dataset = _read("testdata/rdf12/annotated-short.ttl")

    assert len(dataset.asserted_quads) == 4
    assert any(
        quad.subject == IriTerm("http://example.com/a")
        and quad.predicate == IriTerm("http://example.com/name")
        and quad.object == LiteralTerm("Alice", "http://www.w3.org/2001/XMLSchema#string")
        for quad in dataset.asserted_quads
    )
    reifies = [quad for quad in dataset.asserted_quads if quad.predicate.iri == RDF_REIFIES]
    assert len(reifies) == 1
    assert reifies[0].subject == IriTerm("http://example.com/t")
    assert isinstance(reifies[0].object, TripleTerm)
    assert any(quad.predicate == IriTerm("http://example.com/statedBy") for quad in dataset.asserted_quads)
    assert any(quad.predicate == IriTerm("http://example.com/recorded") for quad in dataset.asserted_quads)


def test_invalid_triple_term_subject_is_rejected() -> None:
    with pytest.raises(ValueError, match="Triple terms in subject position"):
        _read("testdata/invalid/triple-term-subject.ttl")


def test_directional_language_tagged_literal_keeps_direction() -> None:
    dataset = _read("testdata/rdf12/dirlang.ttl")

    literal = dataset.asserted_quads[0].object
    assert isinstance(literal, LiteralTerm)
    assert literal.datatype_iri == RDF_DIR_LANG_STRING
    assert literal.language_tag == "ar"
    assert literal.base_direction == "rtl"


def test_named_graph_is_preserved_for_native_dataset_mode() -> None:
    dataset = _read("testdata/dataset/named.trig", dataset_mode="native")

    assert len(dataset.asserted_quads) == 2
    named = [quad for quad in dataset.asserted_quads if quad.graph_name is not None]
    assert len(named) == 1
    assert named[0].graph_name == IriTerm("http://example.com/g1")
    assert isinstance(named[0].object, TripleTerm)


def test_blank_node_named_graph_is_preserved_for_native_dataset_mode(tmp_path: Path) -> None:
    path = tmp_path / "named-bnode.trig"
    path.write_text(
        "\n".join(
            [
                'VERSION "1.2"',
                "PREFIX ex: <http://example.com/>",
                "",
                "_:g {",
                "  ex:a ex:related ex:b .",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    dataset = read_rdf(path, dataset_mode="native")

    assert len(dataset.asserted_quads) == 1
    assert dataset.asserted_quads[0].graph_name == BlankNodeTerm("g")


def test_blank_node_subject_in_nt_is_not_misparsed_as_prefixed_name(tmp_path: Path) -> None:
    path = tmp_path / "sample.nt"
    path.write_text(
        '\n'.join(
            [
                'VERSION "1.2"',
                '_:r1 <http://schema.org/startDate> "2009"^^<http://www.w3.org/2001/XMLSchema#gYear> .',
                '_:r1 <http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies> <<( <http://example.com/a> <http://example.com/p> <http://example.com/b> )>> .',
                "",
            ]
        ),
        encoding="utf-8",
    )

    quads = parse_rdf_file(path)

    assert len(quads) == 2
    assert quads[0].subject.identifier == "r1"
    assert quads[1].predicate.iri == RDF_REIFIES


def test_nquads_line_graph_label_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "sample.nq"
    path.write_text(
        '\n'.join(
            [
                'VERSION "1.2"',
                '<http://example.com/s> <http://example.com/p> <<( <http://example.com/a> <http://example.com/b> "c" )>> <http://example.com/g> .',
                "",
            ]
        ),
        encoding="utf-8",
    )

    dataset = read_rdf(path, dataset_mode="native")

    assert len(dataset.asserted_quads) == 1
    quad = dataset.asserted_quads[0]
    assert quad.graph_name == IriTerm("http://example.com/g")
    assert isinstance(quad.object, TripleTerm)
