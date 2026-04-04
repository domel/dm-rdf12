from __future__ import annotations

from dataclasses import dataclass, field

from .rdf_model import IriTerm, RDF_DIR_LANG_STRING, RDF_LANG_STRING, RDF_TYPE, RDFS_RESOURCE, Rdf12Dataset, local_name

RDFS_CLASS = "http://www.w3.org/2000/01/rdf-schema#Class"
RDFS_DATATYPE = "http://www.w3.org/2000/01/rdf-schema#Datatype"
RDFS_LITERAL = "http://www.w3.org/2000/01/rdf-schema#Literal"
RDF_PROPERTY = "http://www.w3.org/1999/02/22-rdf-syntax-ns#Property"
RDFS_DOMAIN = "http://www.w3.org/2000/01/rdf-schema#domain"
RDFS_RANGE = "http://www.w3.org/2000/01/rdf-schema#range"
XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"
RDF_BUILTIN_DATATYPES = {
    RDF_LANG_STRING,
    RDF_DIR_LANG_STRING,
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#HTML",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#JSON",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#XMLLiteral",
}


@dataclass(slots=True)
class PropertyShape:
    iri: str
    domains: set[str] = field(default_factory=set)
    ranges: set[str] = field(default_factory=set)

    def preferred_domain(self) -> str:
        return sorted(self.domains)[0] if self.domains else RDFS_RESOURCE

    def preferred_range(self) -> str:
        return sorted(self.ranges)[0] if self.ranges else RDFS_RESOURCE

    def is_datatype_property(self, datatypes: set[str]) -> bool:
        preferred = self.preferred_range()
        return (
            preferred == RDFS_LITERAL
            or preferred.startswith(XSD_NAMESPACE)
            or preferred in RDF_BUILTIN_DATATYPES
            or preferred in datatypes
        )


@dataclass(slots=True)
class SchemaModel:
    classes: set[str] = field(default_factory=set)
    datatypes: set[str] = field(default_factory=set)
    properties: dict[str, PropertyShape] = field(default_factory=dict)


def extract_schema(dataset: Rdf12Dataset) -> SchemaModel:
    schema = SchemaModel()
    for quad in dataset.asserted_quads:
        if not isinstance(quad.subject, IriTerm):
            continue
        if not isinstance(quad.object, IriTerm):
            continue

        if quad.predicate.iri == RDF_TYPE and quad.object.iri == RDFS_CLASS:
            schema.classes.add(quad.subject.iri)
            continue

        if quad.predicate.iri == RDF_TYPE and quad.object.iri == RDFS_DATATYPE:
            schema.datatypes.add(quad.subject.iri)
            continue

        if quad.predicate.iri == RDFS_DOMAIN:
            shape = schema.properties.setdefault(quad.subject.iri, PropertyShape(iri=quad.subject.iri))
            shape.domains.add(quad.object.iri)
            continue

        if quad.predicate.iri == RDFS_RANGE:
            shape = schema.properties.setdefault(quad.subject.iri, PropertyShape(iri=quad.subject.iri))
            shape.ranges.add(quad.object.iri)
            continue

        if quad.predicate.iri == RDF_TYPE and quad.object.iri == RDF_PROPERTY:
            schema.properties.setdefault(quad.subject.iri, PropertyShape(iri=quad.subject.iri))

    for shape in schema.properties.values():
        schema.classes.update(shape.domains)
        if shape.ranges and not shape.is_datatype_property(schema.datatypes):
            schema.classes.add(shape.preferred_range())

    return schema


def label_for_class(class_iri: str, compact: bool) -> str:
    return local_name(class_iri) if compact else class_iri


def label_for_property(property_iri: str, compact: bool) -> str:
    return local_name(property_iri) if compact else property_iri
