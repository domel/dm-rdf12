from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IriValue:
    iri: str


@dataclass(frozen=True, slots=True)
class BlankNodeValue:
    identifier: str


PgScalar = str | bool | int | float | IriValue | BlankNodeValue
PgValue = PgScalar | list["PgValue"] | dict[str, "PgValue"]


@dataclass(slots=True)
class PgNode:
    id: str
    labels: list[str]
    properties: dict[str, PgValue] = field(default_factory=dict)


@dataclass(slots=True)
class PgEdge:
    source: str
    target: str
    labels: list[str]
    properties: dict[str, PgValue] = field(default_factory=dict)
    edge_id: str | None = None
    directed: bool = True


@dataclass(slots=True)
class PgGraph:
    nodes: list[PgNode] = field(default_factory=list)
    edges: list[PgEdge] = field(default_factory=list)


@dataclass(slots=True)
class PgNodeType:
    id: str
    labels: list[str]
    properties: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PgEdgeType:
    source_type: str
    target_type: str
    labels: list[str]
    properties: dict[str, str] = field(default_factory=dict)
    directed: bool = True


@dataclass(slots=True)
class PgSchema:
    node_types: list[PgNodeType] = field(default_factory=list)
    edge_types: list[PgEdgeType] = field(default_factory=list)


def to_jsonable(value: PgValue) -> Any:
    if isinstance(value, IriValue):
        return {"kind": "iri", "value": value.iri}
    if isinstance(value, BlankNodeValue):
        return {"kind": "bnode", "value": value.identifier}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    return value

