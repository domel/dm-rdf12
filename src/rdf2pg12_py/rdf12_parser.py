from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from .rdf_model import (
    BlankNodeTerm,
    IriTerm,
    LiteralTerm,
    RDF_DIR_LANG_STRING,
    RDF_LANG_STRING,
    RDF_REIFIES,
    RDF_TYPE,
    RdfQuad,
    TripleTerm,
)

RDF_FIRST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#first"
RDF_REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest"
RDF_NIL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"
XSD_BOOLEAN = "http://www.w3.org/2001/XMLSchema#boolean"
XSD_DECIMAL = "http://www.w3.org/2001/XMLSchema#decimal"
XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
XSD_INTEGER = "http://www.w3.org/2001/XMLSchema#integer"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

_DELIMITERS = set(" \t\r\n.;,{}()[]<>\"'|~")


class ParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ObjectTemplate:
    predicate: IriTerm
    object: object
    annotations: tuple["_ObjectTemplate", ...] = ()


class Rdf12Parser:
    def __init__(
        self,
        text: str,
        *,
        source: str,
        base_iri: str | None = None,
        allow_graph_blocks: bool = False,
        line_quads: bool = False,
    ) -> None:
        self.text = text
        self.source = source
        self.base_iri = base_iri
        self.allow_graph_blocks = allow_graph_blocks
        self.line_quads = line_quads
        self.pos = 0
        self.line = 1
        self.column = 1
        self.prefixes: dict[str, str] = {}
        self.quads: list[RdfQuad] = []
        self._bnode_counter = 0
        self._current_graph: IriTerm | BlankNodeTerm | None = None
        self._graph_block_depth = 0
        self._last_parsed_reified_triple = False

    def parse(self) -> list[RdfQuad]:
        while True:
            self._skip_ws_and_comments()
            if self._eof():
                return self.quads

            if self._consume_keyword("VERSION"):
                self._parse_version()
                continue
            if self._consume_keyword("version"):
                self._parse_version()
                continue
            if self._consume_keyword("@version"):
                self._parse_version()
                continue
            if self._consume_keyword("PREFIX"):
                self._parse_prefix_directive(require_dot=False)
                continue
            if self._consume_keyword("@prefix"):
                self._parse_prefix_directive(require_dot=True)
                continue
            if self._consume_keyword("BASE"):
                self._parse_base_directive(require_dot=False)
                continue
            if self._consume_keyword("@base"):
                self._parse_base_directive(require_dot=True)
                continue

            self._parse_statement()

    def _parse_version(self) -> None:
        self._skip_ws_and_comments()
        version = self._parse_string_literal_value()
        if version not in {"1.2", "1.2-basic"}:
            self._error(f'Unsupported RDF VERSION "{version}"')
        self._consume_char(".")

    def _parse_prefix_directive(self, *, require_dot: bool) -> None:
        self._skip_ws_and_comments()
        prefix = self._parse_prefix_label()
        self._skip_ws_and_comments()
        iri = self._parse_iriref()
        self.prefixes[prefix] = iri
        if require_dot:
            self._skip_ws_and_comments()
            self._expect_char(".")
        else:
            self._consume_char(".")

    def _parse_base_directive(self, *, require_dot: bool) -> None:
        self._skip_ws_and_comments()
        self.base_iri = self._parse_iriref()
        if require_dot:
            self._skip_ws_and_comments()
            self._expect_char(".")
        else:
            self._consume_char(".")

    def _parse_statement(self) -> None:
        self._skip_ws_and_comments()
        if self.allow_graph_blocks and self._peek() == "{":
            self._parse_graph_block(None)
            return

        self._last_parsed_reified_triple = False
        subject = self._parse_subject_term()
        subject_was_reified_triple = self._last_parsed_reified_triple
        self._skip_ws_and_comments()

        if self.allow_graph_blocks and self._peek() == "{":
            if not isinstance(subject, (IriTerm, BlankNodeTerm)):
                self._error("Graph labels must be IRIs or blank nodes")
            self._parse_graph_block(subject)
            return

        if self.line_quads:
            predicate = self._parse_verb()
            object_term = self._parse_object_term()
            self._skip_ws_and_comments()
            graph_name = None
            if self._peek() != ".":
                graph_name = self._parse_iri_or_blank_node()
                if graph_name is None:
                    self._error("Expected N-Quads graph label")
            self.quads.append(RdfQuad(subject, predicate, object_term, graph_name))
            self._skip_ws_and_comments()
            self._expect_char(".")
            return

        if subject_was_reified_triple and (
            self._peek() == "." or (self._graph_block_depth > 0 and self._peek() == "}")
        ):
            self._consume_char(".")
            return

        self._parse_predicate_object_list(subject)
        self._skip_ws_and_comments()
        if self._graph_block_depth > 0 and self._peek() == "}":
            return
        self._expect_char(".")

    def _parse_graph_block(self, graph_name: IriTerm | BlankNodeTerm | None) -> None:
        previous_graph = self._current_graph
        self._current_graph = graph_name
        self._graph_block_depth += 1
        self._expect_char("{")
        while True:
            self._skip_ws_and_comments()
            if self._consume_char("}"):
                self._current_graph = previous_graph
                self._graph_block_depth -= 1
                return
            self._parse_statement()

    def _parse_predicate_object_list(self, subject: object) -> None:
        while True:
            predicate = self._parse_verb()
            self._parse_object_list(subject, predicate)
            self._skip_ws_and_comments()
            if not self._consume_char(";"):
                return
            while True:
                self._skip_ws_and_comments()
                if not self._consume_char(";"):
                    break
            self._skip_ws_and_comments()
            if self._peek() in ".|}]":
                return

    def _parse_object_list(self, subject: object, predicate: IriTerm) -> None:
        while True:
            self._parse_object_item(subject, predicate)
            self._skip_ws_and_comments()
            if not self._consume_char(","):
                return

    def _parse_object_item(self, subject: object, predicate: IriTerm) -> None:
        object_term = self._parse_object_term()
        self.quads.append(RdfQuad(subject, predicate, object_term, self._current_graph))

        triple_term = TripleTerm(subject, predicate, object_term)

        while True:
            self._skip_ws_and_comments()
            if self._starts_with("{|"):
                reifier = self._fresh_blank_node()
                self.quads.append(
                    RdfQuad(reifier, IriTerm(RDF_REIFIES), triple_term, self._current_graph)
                )
                self._emit_annotation_templates(reifier, self._parse_annotation_block())
                continue

            if not self._consume_char("~"):
                return

            self._skip_ws_and_comments()
            if self._starts_with("{|") or self._peek() in ",;.]}" or self._peek() == "":
                reifier = self._fresh_blank_node()
            else:
                reifier = self._parse_iri_or_blank_node()
                if reifier is None:
                    self._error("Expected IRI or blank node after '~'")

            self.quads.append(
                RdfQuad(reifier, IriTerm(RDF_REIFIES), triple_term, self._current_graph)
            )
            self._skip_ws_and_comments()
            while self._starts_with("{|"):
                self._emit_annotation_templates(reifier, self._parse_annotation_block())
                self._skip_ws_and_comments()

    def _emit_annotation_templates(
        self,
        reifier: IriTerm | BlankNodeTerm,
        templates: list[_ObjectTemplate],
    ) -> None:
        for template in templates:
            self.quads.append(
                RdfQuad(reifier, template.predicate, template.object, self._current_graph)
            )
            if template.annotations:
                nested_reifier = self._fresh_blank_node()
                self.quads.append(
                    RdfQuad(
                        nested_reifier,
                        IriTerm(RDF_REIFIES),
                        TripleTerm(reifier, template.predicate, template.object),
                        self._current_graph,
                    )
                )
                self._emit_annotation_templates(nested_reifier, list(template.annotations))

    def _parse_annotation_block(self) -> list[_ObjectTemplate]:
        self._expect_string("{|")
        templates: list[_ObjectTemplate] = []
        while True:
            self._skip_ws_and_comments()
            predicate = self._parse_verb()
            while True:
                object_term = self._parse_object_term()
                self._skip_ws_and_comments()
                nested_annotations: list[_ObjectTemplate] = []
                while self._starts_with("{|"):
                    nested_annotations.extend(self._parse_annotation_block())
                    self._skip_ws_and_comments()
                templates.append(
                    _ObjectTemplate(predicate, object_term, tuple(nested_annotations))
                )
                if not self._consume_char(","):
                    break
            self._skip_ws_and_comments()
            if not self._consume_char(";"):
                break
            while True:
                self._skip_ws_and_comments()
                if not self._consume_char(";"):
                    break
            self._skip_ws_and_comments()
            if self._starts_with("|}"):
                break
        self._expect_string("|}")
        return templates

    def _parse_subject_term(self) -> object:
        term = self._parse_resourceish_term()
        if term is None:
            self._error("Expected RDF subject")
        return term

    def _parse_verb(self) -> IriTerm:
        self._skip_ws_and_comments()
        if self._consume_keyword("a"):
            return IriTerm(RDF_TYPE)
        term = self._parse_iri_term()
        if term is None:
            self._error("Expected RDF predicate")
        return term

    def _parse_object_term(self) -> object:
        term = self._parse_term()
        if term is None:
            self._error("Expected RDF object")
        return term

    def _parse_term(self) -> object | None:
        self._skip_ws_and_comments()
        if self._starts_with("<<("):
            return self._parse_triple_term()
        if self._starts_with("<<"):
            return self._parse_reified_triple()
        iri = self._parse_iri_term()
        if iri is not None:
            return iri
        bnode = self._parse_blank_node()
        if bnode is not None:
            return bnode
        bnode_list = self._parse_blank_node_property_list()
        if bnode_list is not None:
            return bnode_list
        collection = self._parse_collection()
        if collection is not None:
            return collection
        literal = self._parse_literal()
        if literal is not None:
            return literal
        return None

    def _parse_resourceish_term(self) -> object | None:
        self._skip_ws_and_comments()
        if self._starts_with("<<("):
            return self._parse_triple_term()
        if self._starts_with("<<"):
            return self._parse_reified_triple()
        iri = self._parse_iri_term()
        if iri is not None:
            return iri
        bnode = self._parse_blank_node()
        if bnode is not None:
            return bnode
        bnode_list = self._parse_blank_node_property_list()
        if bnode_list is not None:
            return bnode_list
        return self._parse_collection()

    def _parse_triple_term(self) -> TripleTerm:
        self._expect_string("<<(")
        self._skip_ws_and_comments()
        subject = self._parse_resourceish_term()
        if not isinstance(subject, (IriTerm, BlankNodeTerm)):
            self._error("Triple term subject must be an IRI or blank node")
        self._skip_ws_and_comments()
        predicate = self._parse_iri_term()
        if predicate is None:
            self._error("Triple term predicate must be an IRI")
        self._skip_ws_and_comments()
        object_term = self._parse_object_term()
        self._skip_ws_and_comments()
        self._expect_string(")>>")
        return TripleTerm(subject, predicate, object_term)

    def _parse_reified_triple(self) -> IriTerm | BlankNodeTerm:
        self._expect_string("<<")
        self._skip_ws_and_comments()
        subject = self._parse_resourceish_term()
        if not isinstance(subject, (IriTerm, BlankNodeTerm)):
            self._error("Reified triple subject must be an IRI or blank node")
        self._skip_ws_and_comments()
        predicate = self._parse_verb()
        self._skip_ws_and_comments()
        object_term = self._parse_object_term()
        self._skip_ws_and_comments()

        reifier: IriTerm | BlankNodeTerm | None = None
        if self._consume_char("~"):
            self._skip_ws_and_comments()
            reifier = self._parse_iri_or_blank_node()
            self._skip_ws_and_comments()

        self._expect_string(">>")
        if reifier is None:
            reifier = self._fresh_blank_node()
        self.quads.append(
            RdfQuad(
                reifier,
                IriTerm(RDF_REIFIES),
                TripleTerm(subject, predicate, object_term),
                self._current_graph,
            )
        )
        self._last_parsed_reified_triple = True
        return reifier

    def _parse_blank_node_property_list(self) -> BlankNodeTerm | None:
        self._skip_ws_and_comments()
        if self._peek() != "[":
            return None
        self._advance(1)
        blank_node = self._fresh_blank_node()
        self._skip_ws_and_comments()
        if self._consume_char("]"):
            return blank_node
        self._parse_predicate_object_list(blank_node)
        self._skip_ws_and_comments()
        self._expect_char("]")
        return blank_node

    def _parse_collection(self) -> IriTerm | BlankNodeTerm | None:
        self._skip_ws_and_comments()
        if self._peek() != "(":
            return None
        self._advance(1)
        self._skip_ws_and_comments()
        if self._consume_char(")"):
            return IriTerm(RDF_NIL)

        head: BlankNodeTerm | None = None
        previous: BlankNodeTerm | None = None
        while True:
            self._skip_ws_and_comments()
            if self._peek() == ")":
                self._advance(1)
                if previous is not None:
                    self.quads.append(
                        RdfQuad(previous, IriTerm(RDF_REST), IriTerm(RDF_NIL), self._current_graph)
                    )
                return head if head is not None else IriTerm(RDF_NIL)

            item = self._parse_object_term()
            cell = self._fresh_blank_node()
            if head is None:
                head = cell
            if previous is not None:
                self.quads.append(RdfQuad(previous, IriTerm(RDF_REST), cell, self._current_graph))
            self.quads.append(RdfQuad(cell, IriTerm(RDF_FIRST), item, self._current_graph))
            previous = cell

    def _parse_iri_or_blank_node(self) -> IriTerm | BlankNodeTerm | None:
        iri = self._parse_iri_term()
        if iri is not None:
            return iri
        return self._parse_blank_node()

    def _parse_iri_term(self) -> IriTerm | None:
        self._skip_ws_and_comments()
        if self._starts_with("_:"):
            return None
        if self._peek() == "<" and not self._starts_with("<<"):
            return IriTerm(self._parse_iriref())

        prefix, local = self._try_prefixed_name()
        if prefix is None:
            return None
        if prefix not in self.prefixes:
            self._error(f"Unknown prefix '{prefix}:'")
        return IriTerm(self.prefixes[prefix] + local)

    def _parse_blank_node(self) -> BlankNodeTerm | None:
        self._skip_ws_and_comments()
        if not self._starts_with("_:"):
            return None
        self._advance(2)
        identifier = self._read_while(self._is_blank_node_char)
        if not identifier:
            self._error("Blank node label cannot be empty")
        return BlankNodeTerm(identifier)

    def _parse_literal(self) -> LiteralTerm | None:
        self._skip_ws_and_comments()
        if self._peek() == '"':
            lexical = self._parse_string_literal_value()
            datatype = XSD_STRING
            language = None
            direction = None
            if self._consume_char("@"):
                language = self._parse_langtag()
                if self._starts_with("--"):
                    self._advance(2)
                    direction = self._parse_direction()
                    datatype = RDF_DIR_LANG_STRING
                else:
                    datatype = RDF_LANG_STRING
            elif self._starts_with("^^"):
                self._advance(2)
                datatype_term = self._parse_iri_term()
                if datatype_term is None:
                    self._error("Expected datatype IRI after '^^'")
                datatype = datatype_term.iri
            return LiteralTerm(lexical, datatype, language, direction)

        token = self._peek_bare_token()
        if token == "true" or token == "false":
            self._advance(len(token))
            return LiteralTerm(token, XSD_BOOLEAN)
        if token and self._looks_numeric(token):
            self._advance(len(token))
            datatype = XSD_DOUBLE if "e" in token.lower() else XSD_DECIMAL if "." in token else XSD_INTEGER
            return LiteralTerm(token, datatype)
        return None

    def _parse_iriref(self) -> str:
        self._expect_char("<")
        value: list[str] = []
        while not self._eof():
            ch = self._peek()
            if ch == ">":
                self._advance(1)
                iri = "".join(value)
                return urljoin(self.base_iri, iri) if self.base_iri else iri
            if ch == "\\":
                self._advance(1)
                escaped = self._peek()
                if escaped in {'\\', '"', '>', '<'}:
                    value.append(escaped)
                    self._advance(1)
                    continue
                if escaped in {"u", "U"}:
                    value.append(self._parse_unicode_escape())
                    continue
                self._error("Unsupported IRI escape sequence")
            value.append(ch)
            self._advance(1)
        self._error("Unterminated IRI reference")

    def _parse_string_literal_value(self) -> str:
        quote = self._peek()
        if quote not in {"'", '"'}:
            self._error('Expected \'"\'')
        self._advance(1)
        value: list[str] = []
        while not self._eof():
            ch = self._peek()
            if ch == quote:
                self._advance(1)
                return "".join(value)
            if ch == "\\":
                self._advance(1)
                escaped = self._peek()
                escapes = {
                    "t": "\t",
                    "b": "\b",
                    "n": "\n",
                    "r": "\r",
                    "f": "\f",
                    '"': '"',
                    "'": "'",
                    "\\": "\\",
                }
                if escaped in escapes:
                    value.append(escapes[escaped])
                    self._advance(1)
                    continue
                if escaped in {"u", "U"}:
                    value.append(self._parse_unicode_escape())
                    continue
                self._error("Unsupported string escape sequence")
            value.append(ch)
            self._advance(1)
        self._error("Unterminated string literal")

    def _parse_unicode_escape(self) -> str:
        kind = self._peek()
        if kind not in {"u", "U"}:
            self._error("Expected unicode escape")
        self._advance(1)
        length = 4 if kind == "u" else 8
        digits = self.text[self.pos:self.pos + length]
        if len(digits) != length or any(ch not in "0123456789abcdefABCDEF" for ch in digits):
            self._error("Malformed unicode escape")
        self._advance(length)
        return chr(int(digits, 16))

    def _parse_prefix_label(self) -> str:
        if self._peek() == ":":
            self._advance(1)
            return ""
        prefix = self._read_while(self._is_prefix_char)
        if not prefix or not self._consume_char(":"):
            self._error("Expected PREFIX label")
        return prefix

    def _try_prefixed_name(self) -> tuple[str | None, str]:
        self._skip_ws_and_comments()
        start = (self.pos, self.line, self.column)

        prefix = ""
        if self._peek() == ":":
            self._advance(1)
        else:
            prefix = self._read_while(self._is_prefix_char)
            if not prefix or not self._consume_char(":"):
                self._restore(start)
                return None, ""

        local = self._read_while(self._is_local_char)
        return prefix, local

    def _parse_langtag(self) -> str:
        parts: list[str] = []
        first = self._read_while(str.isalpha)
        if not first:
            self._error("Malformed language tag")
        parts.append(first)
        while self._peek() == "-" and not self._starts_with("--"):
            self._advance(1)
            subtag = self._read_while(str.isalnum)
            if not subtag:
                self._error("Malformed language tag")
            parts.append(subtag)
        return "-".join(parts)

    def _parse_direction(self) -> str:
        token = self._peek_bare_token()
        if token not in {"ltr", "rtl"}:
            self._error("Directional language tag must use ltr or rtl")
        self._advance(len(token))
        return token

    def _peek_bare_token(self) -> str:
        end = self.pos
        while end < len(self.text):
            ch = self.text[end]
            if ch in _DELIMITERS:
                break
            if ch == "#" and (end == self.pos or self.text[end - 1].isspace()):
                break
            end += 1
        return self.text[self.pos:end]

    def _looks_numeric(self, token: str) -> bool:
        if not token:
            return False
        if token[0] in "+-":
            body = token[1:]
        else:
            body = token
        if not body:
            return False
        if body.count("e") + body.count("E") > 1:
            return False
        if "e" in body.lower():
            mantissa, exponent = body.lower().split("e", 1)
            return self._looks_decimalish(mantissa) and self._looks_signed_integer(exponent)
        return self._looks_decimalish(body)

    def _looks_decimalish(self, token: str) -> bool:
        if token.count(".") > 1:
            return False
        if "." in token:
            left, right = token.split(".", 1)
            return (left.isdigit() or left == "") and (right.isdigit() or right == "") and (left + right) != ""
        return token.isdigit()

    def _looks_signed_integer(self, token: str) -> bool:
        if not token:
            return False
        if token[0] in "+-":
            return token[1:].isdigit()
        return token.isdigit()

    def _fresh_blank_node(self) -> BlankNodeTerm:
        self._bnode_counter += 1
        return BlankNodeTerm(f"genid{self._bnode_counter}")

    def _consume_keyword(self, keyword: str) -> bool:
        self._skip_ws_and_comments()
        if not self._starts_with(keyword):
            return False
        next_char = self._peek(len(keyword))
        prev_char = self.text[self.pos - 1] if self.pos > 0 else None
        if prev_char is not None and not prev_char.isspace():
            return False
        if next_char and (next_char.isalnum() or next_char in {"_", "-"}):
            return False
        self._advance(len(keyword))
        return True

    def _skip_ws_and_comments(self) -> None:
        while not self._eof():
            ch = self._peek()
            if ch.isspace():
                self._advance(1)
                continue
            if ch == "#":
                while not self._eof() and self._peek() not in "\r\n":
                    self._advance(1)
                continue
            break

    def _expect_char(self, expected: str) -> None:
        if not self._consume_char(expected):
            self._error(f"Expected '{expected}'")

    def _consume_char(self, expected: str) -> bool:
        self._skip_ws_and_comments()
        if self._peek() != expected:
            return False
        self._advance(1)
        return True

    def _expect_string(self, text: str) -> None:
        self._skip_ws_and_comments()
        if not self._starts_with(text):
            self._error(f"Expected '{text}'")
        self._advance(len(text))

    def _starts_with(self, value: str) -> bool:
        return self.text.startswith(value, self.pos)

    def _peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        if index >= len(self.text):
            return ""
        return self.text[index]

    def _eof(self) -> bool:
        return self.pos >= len(self.text)

    def _advance(self, count: int) -> None:
        for _ in range(count):
            if self._eof():
                return
            ch = self.text[self.pos]
            self.pos += 1
            if ch == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1

    def _restore(self, snapshot: tuple[int, int, int]) -> None:
        self.pos, self.line, self.column = snapshot

    def _read_while(self, predicate) -> str:
        start = self.pos
        while not self._eof() and predicate(self._peek()):
            self._advance(1)
        return self.text[start:self.pos]

    def _error(self, message: str) -> None:
        raise ParseError(f"{self.source}:{self.line}:{self.column}: {message}")

    @staticmethod
    def _is_prefix_char(ch: str) -> bool:
        return ch.isalnum() or ch in {"_", "-"}

    @staticmethod
    def _is_local_char(ch: str) -> bool:
        return ch not in _DELIMITERS and ch != "#"

    @staticmethod
    def _is_blank_node_char(ch: str) -> bool:
        return ch.isalnum() or ch in {"_", "-", "."}

def parse_rdf_file(path: Path) -> list[RdfQuad]:
    suffix = path.suffix.lower()
    if suffix not in {".ttl", ".trig", ".nt", ".nq"}:
        raise ValueError(f"Unsupported RDF file extension: {path.suffix}")
    parser = Rdf12Parser(
        path.read_text(encoding="utf-8"),
        source=str(path),
        base_iri=path.resolve().as_uri(),
        allow_graph_blocks=suffix in {".trig", ".nq"},
        line_quads=suffix == ".nq",
    )
    return parser.parse()
