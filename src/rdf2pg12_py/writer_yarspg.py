from __future__ import annotations

import json
from pathlib import Path

from .pg_model import BlankNodeValue, IriValue, PgEdge, PgEdgeType, PgGraph, PgNode, PgNodeType, PgSchema, PgValue, to_jsonable


def _escape(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_value(value: PgValue) -> str:
    if isinstance(value, IriValue):
        return _escape(value.iri)
    if isinstance(value, BlankNodeValue):
        return _escape(f"_:{value.identifier}")
    if isinstance(value, bool):
        return _escape("true" if value else "false")
    if isinstance(value, (int, float)):
        return _escape(str(value))
    if isinstance(value, str):
        return _escape(value)
    if isinstance(value, list):
        return "[" + ",".join(_render_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ",".join(f"{_escape(key)}:{_render_value(item)}" for key, item in value.items())
        return "{" + items + "}"
    raise TypeError(f"Unsupported YARS-PG value: {value!r}")


def _render_labels(labels: list[str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(_escape(label) for label in labels) + "}"


def _render_props(properties: dict[str, PgValue]) -> str:
    if not properties:
        return ""
    body = ",".join(f"{_escape(key)}:{_render_value(value)}" for key, value in properties.items())
    return "[" + body + "]"


def _render_schema_props(properties: dict[str, str]) -> str:
    if not properties:
        return ""
    body = ",".join(f"{_escape(key)}:{value}" for key, value in properties.items())
    return "[" + body + "]"


def _render_node(node: PgNode) -> str:
    return f"({node.id}{_render_labels(node.labels)}{_render_props(node.properties)})"


def _render_edge(edge: PgEdge) -> str:
    middle = f"({edge.edge_id or ''}{_render_labels(edge.labels)}{_render_props(edge.properties)})"
    arrow = "->" if edge.directed else "-"
    return f"({edge.source})-{middle}{arrow}({edge.target})"


def _render_node_type(node_type: PgNodeType) -> str:
    return f"S({node_type.id}{_render_labels(node_type.labels)}{_render_schema_props(node_type.properties)})"


def _render_edge_type(edge_type: PgEdgeType) -> str:
    arrow = "->" if edge_type.directed else "-"
    return (
        f"S({edge_type.source_type})-"
        f"({_render_labels(edge_type.labels)}{_render_schema_props(edge_type.properties)})"
        f"{arrow}({edge_type.target_type})"
    )


def write_graph(graph: PgGraph, path: Path) -> None:
    lines = [_render_node(node) for node in graph.nodes]
    lines.extend(_render_edge(edge) for edge in graph.edges)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_schema(schema: PgSchema, path: Path) -> None:
    lines = [_render_node_type(node_type) for node_type in schema.node_types]
    lines.extend(_render_edge_type(edge_type) for edge_type in schema.edge_types)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(graph: PgGraph, schema: PgSchema | None, instance_path: Path, schema_path: Path | None = None) -> None:
    instance_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": node.id, "labels": node.labels, "properties": to_jsonable(node.properties)}
                    for node in graph.nodes
                ],
                "edges": [
                    {
                        "source": edge.source,
                        "target": edge.target,
                        "labels": edge.labels,
                        "properties": to_jsonable(edge.properties),
                        "edgeId": edge.edge_id,
                        "directed": edge.directed,
                    }
                    for edge in graph.edges
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if schema is not None and schema_path is not None:
        schema_path.write_text(
            json.dumps(
                {
                    "nodeTypes": [
                        {"id": nt.id, "labels": nt.labels, "properties": nt.properties}
                        for nt in schema.node_types
                    ],
                    "edgeTypes": [
                        {
                            "sourceType": et.source_type,
                            "targetType": et.target_type,
                            "labels": et.labels,
                            "properties": et.properties,
                            "directed": et.directed,
                        }
                        for et in schema.edge_types
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
