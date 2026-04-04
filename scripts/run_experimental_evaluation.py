from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Callable

from rdf2pg12_py.inverse_mapping import invert_cdm, invert_gdm
from rdf2pg12_py.io_rdf import read_rdf
from rdf2pg12_py.mapping_cdm import map_cdm
from rdf2pg12_py.mapping_gdm import map_gdm
from rdf2pg12_py.mapping_sdm import map_sdm
from rdf2pg12_py.rdf_model import canonical_term_key
from rdf2pg12_py.schema import extract_schema


ROOT = Path(__file__).resolve().parents[1]
SYN_DIR = ROOT / "datasets" / "synthetic"
PAPER_GENERATED = ROOT / "generated"
YAGO_FULL = ROOT / "datasets" / "yago-wd-annotated-facts-full.nt"
YAGO_SLICE_SIZES = [1000, 5000, 20000]
TIMING_REPETITIONS = 3


def _asserted_quad_key(quad) -> tuple[str, str, str, str | None]:
    return (
        canonical_term_key(quad.subject),
        canonical_term_key(quad.predicate),
        canonical_term_key(quad.object),
        canonical_term_key(quad.graph_name) if quad.graph_name is not None else None,
    )


def exact_roundtrip(left, right) -> bool:
    return {_asserted_quad_key(quad) for quad in left.asserted_quads} == {
        _asserted_quad_key(quad) for quad in right.asserted_quads
    }


def count_properties(graph) -> int:
    return sum(len(node.properties) for node in graph.nodes) + sum(len(edge.properties) for edge in graph.edges)


def count_auxiliary_nodes(graph) -> int:
    aux_labels = {"Statement", "StatementObject", "TripleTerm", "RDFTripleTerm", "RDFLiteral"}
    return sum(1 for node in graph.nodes if any(label in aux_labels for label in node.labels))


def parse_dataset(path: Path):
    dataset_mode = "native" if path.suffix.lower() in {".trig", ".nq"} else "reject"
    t0 = perf_counter()
    dataset = read_rdf(path, dataset_mode=dataset_mode)
    t1 = perf_counter()
    return dataset, dataset_mode, t1 - t0


def map_with_timing(fn, *args, **kwargs):
    t0 = perf_counter()
    result = fn(*args, **kwargs)
    t1 = perf_counter()
    return result, t1 - t0


def summarize_times(prefix: str, runs: list[float]) -> dict[str, object]:
    rounded_runs = [round(value, 4) for value in runs]
    return {
        f"{prefix}_time_s": round(median(runs), 4),
        f"{prefix}_runs_s": rounded_runs,
        f"{prefix}_min_s": round(min(runs), 4),
        f"{prefix}_max_s": round(max(runs), 4),
    }


def dataset_summary(dataset) -> dict[str, object]:
    return {
        "asserted_quads": len(dataset.asserted_quads),
        "triple_terms": len(dataset.triple_terms),
        "referenced_triples": len(dataset.referenced_triple_keys),
        "asserted_triples": len(dataset.asserted_triple_keys),
        "reifiers": sum(len(values) for values in dataset.reifiers.values()),
        "annotations": sum(len(values) for values in dataset.annotations_by_reifier.values()),
        "explicit_type_resources": len(dataset.explicit_types),
        "named_graphs": dataset.has_named_graphs(),
    }


def graph_summary(graph) -> dict[str, int]:
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "properties": count_properties(graph),
        "aux_nodes": count_auxiliary_nodes(graph),
    }


def parse_with_repetitions(path: Path) -> tuple[object, str, dict[str, object]]:
    runs: list[float] = []
    dataset = None
    dataset_mode = "reject"
    summary = None
    for _ in range(TIMING_REPETITIONS):
        current_dataset, current_mode, duration = parse_dataset(path)
        current_summary = dataset_summary(current_dataset)
        if summary is None:
            summary = current_summary
        elif summary != current_summary:
            raise RuntimeError(f"Inconsistent parse summary across repetitions for {path}")
        dataset = current_dataset
        dataset_mode = current_mode
        runs.append(duration)
    return dataset, dataset_mode, summarize_times("parse", runs)


def evaluate_sdm_mapping(dataset) -> dict[str, object]:
    runs: list[float] = []
    summary = None
    for _ in range(TIMING_REPETITIONS):
        (graph, _), duration = map_with_timing(map_sdm, dataset, literal_mode="lossless")
        current_summary = graph_summary(graph)
        if summary is None:
            summary = current_summary
        elif summary != current_summary:
            raise RuntimeError("SDM* graph structure changed across repetitions")
        runs.append(duration)
    return {
        **summarize_times("map", runs),
        **summary,
    }


def evaluate_roundtrip_mapping(
    dataset,
    map_fn: Callable,
    invert_fn: Callable,
    *args,
    **kwargs,
) -> dict[str, object]:
    map_runs: list[float] = []
    inverse_runs: list[float] = []
    summary = None
    roundtrip_exact = True
    for _ in range(TIMING_REPETITIONS):
        (graph, _), map_duration = map_with_timing(map_fn, dataset, *args, **kwargs)
        current_summary = graph_summary(graph)
        if summary is None:
            summary = current_summary
        elif summary != current_summary:
            raise RuntimeError(f"{map_fn.__name__} graph structure changed across repetitions")
        roundtrip, inverse_duration = map_with_timing(invert_fn, graph)
        roundtrip_exact = roundtrip_exact and exact_roundtrip(dataset, roundtrip)
        map_runs.append(map_duration)
        inverse_runs.append(inverse_duration)
    return {
        **summarize_times("map", map_runs),
        **summarize_times("inverse", inverse_runs),
        "roundtrip_exact": roundtrip_exact,
        **summary,
    }


def load_manifest() -> dict[str, object]:
    return json.loads((SYN_DIR / "manifest.json").read_text(encoding="utf-8"))


def load_schema_variants(manifest: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    schema_models: dict[str, object] = {}
    schema_metadata: dict[str, object] = {}
    for record in manifest["schema_files"]:
        path = ROOT / record["file"]
        schema_models[record["name"]] = extract_schema(read_rdf(path))
        schema_metadata[record["name"]] = record
    return schema_models, schema_metadata


def evaluate_workload(
    workload: dict[str, object],
    *,
    schema_variants: dict[str, object],
    include_sdm: bool = True,
    include_gdm: bool = True,
) -> dict[str, object]:
    path = ROOT / workload["file"]
    dataset, dataset_mode, parse_payload = parse_with_repetitions(path)
    result = {
        "name": workload["name"],
        "file": workload["file"],
        "config": {
            "entity_count": workload["entity_count"],
            "relation_count": workload["relation_count"],
            "annotated_ratio": workload["annotated_ratio"],
            "quoted_ratio": workload["quoted_ratio"],
            "nested_ratio": workload["nested_ratio"],
            "dirlang_ratio": workload["dirlang_ratio"],
            "named_graph_count": workload["named_graph_count"],
        },
        "input": dataset_summary(dataset),
        **parse_payload,
    }

    if include_sdm:
        result["sdm"] = evaluate_sdm_mapping(dataset)
    if include_gdm:
        result["gdm"] = evaluate_roundtrip_mapping(dataset, map_gdm, invert_gdm, dataset_mode=dataset_mode)

    for name, schema_model in schema_variants.items():
        result[f"cdm_{name}"] = evaluate_roundtrip_mapping(
            dataset,
            map_cdm,
            invert_cdm,
            schema_model,
            literal_mode="lossless",
            dataset_mode=dataset_mode,
        )
    return result


def synthetic_evaluation(manifest: dict[str, object], schema_models: dict[str, object]) -> list[dict[str, object]]:
    return [
        evaluate_workload(
            workload,
            schema_variants={
                "full": schema_models["full"],
                "partial": schema_models["partial"],
            },
        )
        for workload in manifest["workloads"]
    ]


def scaling_evaluation(manifest: dict[str, object], schema_models: dict[str, object]) -> list[dict[str, object]]:
    return [
        evaluate_workload(
            workload,
            schema_variants={"full": schema_models["full"]},
        )
        for workload in manifest["scaling_workloads"]
    ]


def annotated_sweep_evaluation(manifest: dict[str, object], schema_models: dict[str, object]) -> list[dict[str, object]]:
    return [
        evaluate_workload(
            workload,
            schema_variants={"full": schema_models["full"]},
        )
        for workload in manifest["annotated_sweep_workloads"]
    ]


def schema_sweep_evaluation(
    manifest: dict[str, object],
    schema_models: dict[str, object],
    schema_metadata: dict[str, object],
) -> dict[str, object]:
    workload = next(item for item in manifest["workloads"] if item["name"] == "S2-Lift50")
    result = evaluate_workload(
        workload,
        schema_variants={
            "full": schema_models["full"],
            "half": schema_models["half"],
            "none": schema_models["none"],
        },
        include_sdm=False,
        include_gdm=False,
    )
    result["schema_variants"] = {
        name: schema_metadata[name]
        for name in ("full", "half", "none")
    }
    return result


def prepare_yago_slices() -> list[Path]:
    created = [ROOT / "datasets" / f"yago-wd-annotated-facts-{size}.nt" for size in YAGO_SLICE_SIZES]
    handles = {size: path.open("w", encoding="utf-8") for size, path in zip(YAGO_SLICE_SIZES, created)}
    try:
        for handle in handles.values():
            handle.write('VERSION "1.2"\n')
        with YAGO_FULL.open("r", encoding="utf-8") as source:
            next(source)
            for index, line in enumerate(source, start=1):
                for size in YAGO_SLICE_SIZES:
                    if index <= size:
                        handles[size].write(line)
                if index >= YAGO_SLICE_SIZES[-1]:
                    break
    finally:
        for handle in handles.values():
            handle.close()
    return created


def yago_full_stats() -> dict[str, object]:
    lines = 0
    reifies = 0
    annotations = 0
    predicates = Counter()
    with YAGO_FULL.open("r", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            lines += 1
            if "<http://www.w3.org/1999/02/22-rdf-syntax-ns#reifies>" in line:
                reifies += 1
            else:
                annotations += 1
                parts = line.split(" ", 2)
                if len(parts) > 1:
                    predicates[parts[1]] += 1
    return {
        "source_triples": lines,
        "reifies_triples": reifies,
        "annotation_triples": annotations,
        "top_annotation_predicates": predicates.most_common(8),
    }


def yago_slice_evaluation(paths: list[Path]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for path in paths:
        dataset, dataset_mode, parse_payload = parse_with_repetitions(path)
        gdm_payload = evaluate_roundtrip_mapping(dataset, map_gdm, invert_gdm, dataset_mode=dataset_mode)
        results.append(
            {
                "file": str(path.relative_to(ROOT)),
                "source_triples": len(dataset.asserted_quads),
                "input": dataset_summary(dataset),
                **parse_payload,
                "gdm": gdm_payload,
            }
        )
    return results


def main() -> None:
    PAPER_GENERATED.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    schema_models, schema_metadata = load_schema_variants(manifest)
    synthetic = synthetic_evaluation(manifest, schema_models)
    scaling = scaling_evaluation(manifest, schema_models)
    annotated_sweep = annotated_sweep_evaluation(manifest, schema_models)
    schema_sweep = schema_sweep_evaluation(manifest, schema_models, schema_metadata)
    yago_slices = prepare_yago_slices()
    yago = {
        "full": yago_full_stats(),
        "slices": yago_slice_evaluation(yago_slices),
    }
    payload = {
        "timing": {
            "repetitions": TIMING_REPETITIONS,
            "aggregation": "median",
        },
        "synthetic": synthetic,
        "scaling": scaling,
        "annotated_sweep": annotated_sweep,
        "schema_sweep": schema_sweep,
        "yago": yago,
    }
    (PAPER_GENERATED / "experimental-results.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
