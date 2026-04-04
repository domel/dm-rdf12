from __future__ import annotations

import argparse
from pathlib import Path

from .io_rdf import read_rdf
from .mapping_cdm import map_cdm
from .mapping_gdm import map_gdm
from .mapping_sdm import map_sdm
from .schema import extract_schema
from .writer_yarspg import write_graph, write_json, write_schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rdf2pg12-py")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("-gdm", dest="gdm", metavar="RDF_FILE")
    mode.add_argument("-sdm", dest="sdm", metavar="RDF_FILE")
    mode.add_argument("-cdm", nargs=2, dest="cdm", metavar=("RDF_FILE", "RDFS_FILE"))

    parser.add_argument("--rdf-version-mode", default="auto", choices=["auto", "1.1", "1.2-basic", "1.2"])
    parser.add_argument("--triple-term-mode", default="native", choices=["native", "basic-encode", "reject"])
    parser.add_argument("--bnode-mode", default="preserve", choices=["preserve", "skolemize"])
    parser.add_argument("--literal-mode", default="lossless", choices=["lossless", "flattened"])
    parser.add_argument(
        "--dataset-mode",
        default="reject",
        choices=["reject", "flatten", "named-graph-property", "native"],
    )
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--output-format", default="yarspg", choices=["yarspg", "json"])
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.bnode_mode == "skolemize":
        raise NotImplementedError("Skolemization is intentionally explicit but not implemented yet")
    if args.triple_term_mode == "basic-encode":
        raise NotImplementedError("basic-encode mode is not implemented yet")

    if args.gdm:
        dataset = read_rdf(Path(args.gdm), triple_term_mode=args.triple_term_mode, dataset_mode=args.dataset_mode)
        graph, schema = map_gdm(dataset, dataset_mode=args.dataset_mode)
    elif args.sdm:
        dataset = read_rdf(Path(args.sdm), triple_term_mode=args.triple_term_mode, dataset_mode=args.dataset_mode)
        graph, schema = map_sdm(dataset, literal_mode=args.literal_mode)
    else:
        rdf_path, schema_path = args.cdm
        dataset = read_rdf(Path(rdf_path), triple_term_mode=args.triple_term_mode, dataset_mode=args.dataset_mode)
        schema_dataset = read_rdf(Path(schema_path), triple_term_mode="native", dataset_mode="flatten")
        graph, schema = map_cdm(
            dataset,
            extract_schema(schema_dataset),
            literal_mode=args.literal_mode,
            dataset_mode=args.dataset_mode,
        )

    if args.output_format == "json":
        write_json(graph, schema, output_dir / "instance.json", output_dir / "schema.json")
    else:
        write_graph(graph, output_dir / "instance.ypg")
        if schema.node_types or schema.edge_types:
            write_schema(schema, output_dir / "schema.ypg")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
