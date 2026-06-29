from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean, median, pstdev
from time import perf_counter
from typing import Callable

from rdf2pg12_py.inverse_mapping import invert_cdm, invert_gdm
from rdf2pg12_py.io_rdf import read_rdf
from rdf2pg12_py.mapping_cdm import map_cdm
from rdf2pg12_py.mapping_gdm import map_gdm
from rdf2pg12_py.mapping_sdm import map_sdm
from rdf2pg12_py.rdf_model import canonical_term_key
from rdf2pg12_py.schema import SchemaModel, extract_schema


PYTHON_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PYTHON_ROOT.parents[1]
SYN_DIR = PROJECT_ROOT / "zbior_danych" / "synthetic"
W3C_DIR = PROJECT_ROOT / "zbior_danych" / "w3c-rdf12"
PAPER_GENERATED = PROJECT_ROOT / "artykul" / "generated"
YAGO_FULL = PROJECT_ROOT / "zbior_danych" / "yago-wd-annotated-facts-full.nt"
YAGO_SLICE_SIZES = [1000, 5000, 20000]
WARMUP_REPETITIONS = 1
TIMING_REPETITIONS = 10


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
        f"{prefix}_mean_s": round(mean(runs), 4),
        f"{prefix}_stdev_s": round(pstdev(runs), 4),
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
    for _ in range(WARMUP_REPETITIONS):
        parse_dataset(path)
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
    for _ in range(WARMUP_REPETITIONS):
        map_sdm(dataset, literal_mode="lossless")
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
    for _ in range(WARMUP_REPETITIONS):
        graph, _ = map_fn(dataset, *args, **kwargs)
        invert_fn(graph)
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
        path = PROJECT_ROOT / record["file"]
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
    path = PROJECT_ROOT / workload["file"]
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
            "partial": schema_models["partial"],
            "half": schema_models["half"],
            "none": schema_models["none"],
        },
        include_sdm=False,
        include_gdm=False,
    )
    result["schema_variants"] = {
        name: schema_metadata[name]
        for name in ("full", "partial", "half", "none")
    }
    return result


def prepare_yago_slices() -> list[Path]:
    created = [
        PROJECT_ROOT / "zbior_danych" / f"yago-wd-annotated-facts-{size}.nt"
        for size in YAGO_SLICE_SIZES
    ]
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
                "file": str(path.relative_to(PROJECT_ROOT)),
                "source_triples": len(dataset.asserted_quads),
                "input": dataset_summary(dataset),
                **parse_payload,
                "gdm": gdm_payload,
            }
        )
    return results


def w3c_manifest_references() -> tuple[list[dict[str, object]], dict[str, object]]:
    manifest_path = W3C_DIR / "manifest.json"
    if not manifest_path.exists():
        return [], {"available": False}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files_by_suite_section_name = {
        (
            record["suite"],
            record["section"],
            Path(record["file"]).name,
        ): PROJECT_ROOT / record["file"]
        for record in manifest["downloaded_files"]
    }
    references: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    negative_actions = 0
    for test in manifest["tests"]:
        suite = test["suite"]
        section = test["section"]
        if not test["positive"]:
            negative_actions += len(test["actions"])
            continue
        for role, names in (("action", test["actions"]), ("result", test["results"])):
            for name in names:
                key = (suite, section, Path(name).name)
                path = files_by_suite_section_name.get(key)
                if path is None or key in seen:
                    continue
                seen.add(key)
                references.append(
                    {
                        "suite": suite,
                        "section": section,
                        "role": role,
                        "file": str(path.relative_to(PROJECT_ROOT)),
                        "path": path,
                    }
                )
    metadata = {
        "available": True,
        "downloaded_files": len(manifest["downloaded_files"]),
        "positive_references": len(references),
        "negative_action_files": negative_actions,
    }
    return references, metadata


def w3c_group_name(record: dict[str, object]) -> str:
    suite = str(record["suite"])
    section = str(record["section"])
    labels = {
        "rdf-n-triples": "N-Triples",
        "rdf-n-quads": "N-Quads",
        "rdf-turtle": "Turtle",
        "rdf-trig": "TriG",
    }
    return f"{labels.get(suite, suite)} {section}"


def evaluate_w3c_file(path: Path) -> dict[str, object]:
    dataset, dataset_mode, parse_time = parse_dataset(path)
    sdm_graph, _ = map_sdm(dataset, literal_mode="lossless")
    gdm_graph, _ = map_gdm(dataset, dataset_mode=dataset_mode)
    cdm_graph, _ = map_cdm(
        dataset,
        SchemaModel(),
        literal_mode="lossless",
        dataset_mode=dataset_mode,
    )
    gdm_roundtrip = invert_gdm(gdm_graph)
    cdm_roundtrip = invert_cdm(cdm_graph)
    return {
        "parse_time_s": round(parse_time, 4),
        "input": dataset_summary(dataset),
        "sdm": graph_summary(sdm_graph),
        "gdm": {
            **graph_summary(gdm_graph),
            "roundtrip_exact": exact_roundtrip(dataset, gdm_roundtrip),
        },
        "cdm": {
            **graph_summary(cdm_graph),
            "roundtrip_exact": exact_roundtrip(dataset, cdm_roundtrip),
        },
    }


def w3c_evaluation() -> dict[str, object]:
    references, metadata = w3c_manifest_references()
    if not metadata.get("available"):
        return metadata

    groups: dict[str, dict[str, object]] = {}
    failures: list[dict[str, str]] = []
    for reference in references:
        group_name = w3c_group_name(reference)
        group = groups.setdefault(
            group_name,
            {
                "files": 0,
                "quads": 0,
                "triple_terms": 0,
                "named_graph_files": 0,
                "sdm_success": 0,
                "gdm_roundtrip": 0,
                "cdm_roundtrip": 0,
            },
        )
        path = reference["path"]
        try:
            payload = evaluate_w3c_file(path)
        except Exception as exc:  # pragma: no cover - reported in JSON for external suites
            failures.append({"file": str(path.relative_to(PROJECT_ROOT)), "error": str(exc)})
            continue
        group["files"] += 1
        group["quads"] += payload["input"]["asserted_quads"]
        group["triple_terms"] += payload["input"]["triple_terms"]
        if payload["input"]["named_graphs"]:
            group["named_graph_files"] += 1
        group["sdm_success"] += 1
        if payload["gdm"]["roundtrip_exact"]:
            group["gdm_roundtrip"] += 1
        if payload["cdm"]["roundtrip_exact"]:
            group["cdm_roundtrip"] += 1

    totals = {
        "files": sum(group["files"] for group in groups.values()),
        "quads": sum(group["quads"] for group in groups.values()),
        "triple_terms": sum(group["triple_terms"] for group in groups.values()),
        "named_graph_files": sum(group["named_graph_files"] for group in groups.values()),
        "sdm_success": sum(group["sdm_success"] for group in groups.values()),
        "gdm_roundtrip": sum(group["gdm_roundtrip"] for group in groups.values()),
        "cdm_roundtrip": sum(group["cdm_roundtrip"] for group in groups.values()),
    }
    return {
        **metadata,
        "groups": groups,
        "totals": totals,
        "failures": failures,
    }


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
    w3c = w3c_evaluation()
    payload = {
        "timing": {
            "repetitions": TIMING_REPETITIONS,
            "warmup_repetitions": WARMUP_REPETITIONS,
            "aggregation": "median",
        },
        "synthetic": synthetic,
        "scaling": scaling,
        "annotated_sweep": annotated_sweep,
        "schema_sweep": schema_sweep,
        "w3c": w3c,
        "yago": yago,
    }
    (PAPER_GENERATED / "experimental-results.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
