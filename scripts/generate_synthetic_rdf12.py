from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "datasets" / "synthetic"


@dataclass(frozen=True, slots=True)
class WorkloadConfig:
    name: str
    file_name: str
    entity_count: int
    relation_count: int
    annotated_ratio: float = 0.0
    quoted_ratio: float = 0.0
    nested_ratio: float = 0.0
    dirlang_ratio: float = 0.0
    named_graph_count: int = 0


PREFIXES = [
    'VERSION "1.2"',
    "PREFIX ex: <http://example.com/data/>",
    "PREFIX voc: <http://example.com/voc/>",
    "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>",
    "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
    "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>",
]


WORKLOADS = [
    WorkloadConfig("S0-Plain", "s0-plain.ttl", entity_count=120, relation_count=240),
    WorkloadConfig("S1-Lift10", "s1-lift10.ttl", entity_count=120, relation_count=240, annotated_ratio=0.10, quoted_ratio=0.10),
    WorkloadConfig("S2-Lift50", "s2-lift50.ttl", entity_count=120, relation_count=240, annotated_ratio=0.50, quoted_ratio=0.20),
    WorkloadConfig("S3-Nested20", "s3-nested20.ttl", entity_count=120, relation_count=240, quoted_ratio=0.20, nested_ratio=0.20),
    WorkloadConfig("S4-DirLang20", "s4-dirlang20.ttl", entity_count=120, relation_count=240, annotated_ratio=0.20, dirlang_ratio=0.20),
    WorkloadConfig("S5-Named10", "s5-named10.trig", entity_count=120, relation_count=240, annotated_ratio=0.20, quoted_ratio=0.20, named_graph_count=10),
]

SCALING_ENTITY_COUNTS = [250, 1000, 5000]
ANNOTATED_SWEEP_RATIOS = [0.0, 0.25, 0.50, 0.75, 1.0]
SCHEMA_PROPERTY_ORDER = [
    "voc:name",
    "voc:text",
    "voc:since",
    "voc:knows",
    "voc:relatedTo",
    "voc:worksWith",
    "voc:locatedIn",
    "voc:claims",
    "voc:mentions",
    "voc:confidence",
    "voc:source",
]

SCALING_WORKLOADS = [
    WorkloadConfig(
        name=f"Scale-Plain-{entity_count}",
        file_name=f"scale-plain-{entity_count}.ttl",
        entity_count=entity_count,
        relation_count=entity_count * 2,
    )
    for entity_count in SCALING_ENTITY_COUNTS
]
SCALING_WORKLOADS.extend(
    [
        WorkloadConfig(
            name=f"Scale-Lift50-{entity_count}",
            file_name=f"scale-lift50-{entity_count}.ttl",
            entity_count=entity_count,
            relation_count=entity_count * 2,
            annotated_ratio=0.50,
            quoted_ratio=0.20,
        )
        for entity_count in SCALING_ENTITY_COUNTS
    ]
)

ANNOTATED_SWEEP_WORKLOADS = [
    WorkloadConfig(
        name=f"Ann-{int(ratio * 100):03d}",
        file_name=f"ann-{int(ratio * 100):03d}.ttl",
        entity_count=1000,
        relation_count=2000,
        annotated_ratio=ratio,
    )
    for ratio in ANNOTATED_SWEEP_RATIOS
]

SCHEMA_VARIANTS = {
    "full": tuple(SCHEMA_PROPERTY_ORDER),
    "partial": (
        "voc:name",
        "voc:text",
        "voc:since",
        "voc:knows",
        "voc:relatedTo",
        "voc:worksWith",
        "voc:locatedIn",
        "voc:claims",
    ),
    "half": (
        "voc:name",
        "voc:since",
        "voc:knows",
        "voc:relatedTo",
        "voc:worksWith",
    ),
    "none": (),
}


def ex(name: str) -> str:
    return f"ex:{name}"


def entity_name(index: int) -> str:
    return f"e{index:04d}"


def graph_name(index: int) -> str:
    return f"g{index:02d}"


def relation_predicate(index: int) -> str:
    predicates = ["voc:knows", "voc:relatedTo", "voc:worksWith", "voc:locatedIn"]
    return predicates[index % len(predicates)]


def entity_class(index: int) -> str:
    classes = ["voc:Person", "voc:Organisation", "voc:Place"]
    return classes[index % len(classes)]


def base_name(index: int) -> str:
    return f'"Entity {index}"'


def confidence_literal(index: int) -> str:
    whole = 70 + (index % 25)
    return f'"0.{whole}"^^xsd:decimal'


def year_literal(index: int) -> str:
    year = 2000 + (index % 20)
    return f'"{year}"^^xsd:gYear'


def normal_text_literal(index: int) -> str:
    return f'"text-{index}"'


def dirlang_literal(index: int) -> str:
    return f'"مرحبا-{index}"@ar--rtl'


def triple_term(subject: str, predicate: str, object_: str) -> str:
    return f"<<( {subject} {predicate} {object_} )>>"


def nested_triple_term(index: int, entity_count: int) -> str:
    inner_s = ex(entity_name((index + 7) % entity_count))
    inner_p = relation_predicate(index + 1)
    inner_o = ex(entity_name((index + 13) % entity_count))
    outer_s = ex(entity_name((index + 3) % entity_count))
    return triple_term(outer_s, "voc:claims", triple_term(inner_s, inner_p, inner_o))


def schema_lines(property_iris: Iterable[str]) -> list[str]:
    selected_properties = set(property_iris)
    lines = PREFIXES[1:]
    lines.extend(
        [
            "",
            "voc:Entity rdf:type rdfs:Class .",
            "voc:Person rdf:type rdfs:Class .",
            "voc:Organisation rdf:type rdfs:Class .",
            "voc:Place rdf:type rdfs:Class .",
            "",
        ]
    )
    property_blocks = {
        "voc:name": [
            "voc:name rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range xsd:string .",
        ],
        "voc:text": [
            "voc:text rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range rdf:dirLangString .",
        ],
        "voc:since": [
            "voc:since rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range xsd:gYear .",
        ],
        "voc:knows": [
            "voc:knows rdf:type rdf:Property ;",
            "  rdfs:domain voc:Person ;",
            "  rdfs:range voc:Person .",
        ],
        "voc:relatedTo": [
            "voc:relatedTo rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range voc:Entity .",
        ],
        "voc:worksWith": [
            "voc:worksWith rdf:type rdf:Property ;",
            "  rdfs:domain voc:Person ;",
            "  rdfs:range voc:Person .",
        ],
        "voc:locatedIn": [
            "voc:locatedIn rdf:type rdf:Property ;",
            "  rdfs:domain voc:Organisation ;",
            "  rdfs:range voc:Place .",
        ],
        "voc:claims": [
            "voc:claims rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range voc:Entity .",
        ],
        "voc:mentions": [
            "voc:mentions rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range voc:Entity .",
        ],
        "voc:confidence": [
            "voc:confidence rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range xsd:decimal .",
        ],
        "voc:source": [
            "voc:source rdf:type rdf:Property ;",
            "  rdfs:domain voc:Entity ;",
            "  rdfs:range voc:Entity .",
        ],
    }
    for property_iri in SCHEMA_PROPERTY_ORDER:
        if property_iri not in selected_properties:
            continue
        lines.append("")
        lines.extend(property_blocks[property_iri])
    return lines


def generate_workload(config: WorkloadConfig) -> tuple[str, dict[str, int]]:
    statements_by_graph: dict[str | None, list[str]] = {None: []}
    for graph_index in range(config.named_graph_count):
        statements_by_graph[ex(graph_name(graph_index))] = []

    stats = {
        "typed_resources": config.entity_count,
        "name_literals": config.entity_count,
        "dirlang_literals": 0,
        "ordinary_relations": 0,
        "annotated_relations": 0,
        "quoted_mentions": 0,
        "nested_mentions": 0,
        "named_graphs": config.named_graph_count,
    }

    def target_graph(index: int) -> str | None:
        if config.named_graph_count == 0:
            return None
        return ex(graph_name(index % config.named_graph_count))

    def emit(statement: str, graph: str | None) -> None:
        statements_by_graph.setdefault(graph, []).append(statement)

    for index in range(config.entity_count):
        subject = ex(entity_name(index))
        emit(f"{subject} a {entity_class(index)} .", None)
        emit(f"{subject} voc:name {base_name(index)} .", None)
        emit(f"{subject} voc:since {year_literal(index)} .", None)
        if index < int(config.entity_count * config.dirlang_ratio):
            emit(f"{subject} voc:text {dirlang_literal(index)} .", None)
            stats["dirlang_literals"] += 1
        else:
            emit(f"{subject} voc:text {normal_text_literal(index)} .", None)

    annotated_limit = int(config.relation_count * config.annotated_ratio)
    quoted_limit = int(config.relation_count * config.quoted_ratio)
    nested_limit = int(config.relation_count * config.nested_ratio)

    for index in range(config.relation_count):
        subject = ex(entity_name(index % config.entity_count))
        obj = ex(entity_name((index * 7 + 11) % config.entity_count))
        predicate = relation_predicate(index)
        graph = target_graph(index)

        if index < annotated_limit:
            reifier = ex(f"stmt{index:04d}")
            emit(
                f"{subject} {predicate} {obj} ~ {reifier} "
                f"{{| voc:confidence {confidence_literal(index)} ; voc:source {ex(entity_name((index * 5 + 3) % config.entity_count))} |}} .",
                graph,
            )
            stats["annotated_relations"] += 1
            continue

        emit(f"{subject} {predicate} {obj} .", graph)
        stats["ordinary_relations"] += 1

        if index < annotated_limit + quoted_limit:
            emit(
                f"{subject} voc:mentions {triple_term(subject, predicate, obj)} .",
                graph,
            )
            stats["quoted_mentions"] += 1

        if index < nested_limit:
            emit(
                f"{subject} voc:mentions {nested_triple_term(index, config.entity_count)} .",
                graph,
            )
            stats["nested_mentions"] += 1

    lines = PREFIXES[:]
    if config.file_name.endswith(".ttl"):
        lines.append("")
        for statement in statements_by_graph[None]:
            lines.append(statement)
    else:
        lines.append("")
        default_graph = statements_by_graph.get(None, [])
        if default_graph:
            lines.append("{")
            lines.extend(f"  {statement}" for statement in default_graph)
            lines.append("}")
            lines.append("")
        for graph, graph_statements in statements_by_graph.items():
            if graph is None or not graph_statements:
                continue
            lines.append(f"{graph} {{")
            lines.extend(f"  {statement}" for statement in graph_statements)
            lines.append("}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n", stats


def workload_record(config: WorkloadConfig, path: Path, stats: dict[str, int]) -> dict[str, object]:
    return {
        "name": config.name,
        "file": str(path.relative_to(ROOT)),
        "entity_count": config.entity_count,
        "relation_count": config.relation_count,
        "annotated_ratio": config.annotated_ratio,
        "quoted_ratio": config.quoted_ratio,
        "nested_ratio": config.nested_ratio,
        "dirlang_ratio": config.dirlang_ratio,
        "named_graph_count": config.named_graph_count,
        "stats": stats,
    }


def write_workload_section(
    manifest: dict[str, object],
    section_name: str,
    configs: Iterable[WorkloadConfig],
) -> None:
    section: list[dict[str, object]] = []
    for config in configs:
        text, stats = generate_workload(config)
        path = DATASET_DIR / config.file_name
        path.write_text(text, encoding="utf-8")
        section.append(workload_record(config, path, stats))
    manifest[section_name] = section


def main() -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "generator": "generate_synthetic_rdf12.py",
        "workloads": [],
        "scaling_workloads": [],
        "annotated_sweep_workloads": [],
        "schema_files": [],
    }

    for schema_name, property_iris in SCHEMA_VARIANTS.items():
        path = DATASET_DIR / f"schema-{schema_name}.ttl"
        path.write_text("\n".join(schema_lines(property_iris)).rstrip() + "\n", encoding="utf-8")
        manifest["schema_files"].append(
            {
                "name": schema_name,
                "file": str(path.relative_to(ROOT)),
                "declared_properties": len(property_iris),
                "property_coverage": round(len(property_iris) / len(SCHEMA_PROPERTY_ORDER), 3),
            }
        )

    write_workload_section(manifest, "workloads", WORKLOADS)
    write_workload_section(manifest, "scaling_workloads", SCALING_WORKLOADS)
    write_workload_section(manifest, "annotated_sweep_workloads", ANNOTATED_SWEEP_WORKLOADS)

    (DATASET_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
