from __future__ import annotations

from pathlib import Path

from .rdf12_parser import parse_rdf_file
from .rdf_model import (
    Rdf12Dataset,
    RdfQuad,
    TripleTerm,
)


def read_rdf(
    path: Path,
    *,
    triple_term_mode: str = "native",
    dataset_mode: str = "reject",
) -> Rdf12Dataset:
    if triple_term_mode == "reject":
        raise NotImplementedError("Custom parser currently supports only --triple-term-mode=native")

    dataset = Rdf12Dataset.from_asserted_quads(parse_rdf_file(path))
    for quad in dataset.asserted_quads:
        if isinstance(quad.subject, TripleTerm):
            raise ValueError("Triple terms in subject position are invalid in native RDF 1.2 mode")
    if dataset.has_named_graphs() and dataset_mode == "reject":
        raise ValueError("Named graphs present but --dataset-mode=reject")
    if dataset_mode == "flatten" and dataset.has_named_graphs():
        flattened = [RdfQuad(q.subject, q.predicate, q.object, None) for q in dataset.asserted_quads]
        dataset = Rdf12Dataset.from_asserted_quads(flattened)
    return dataset
