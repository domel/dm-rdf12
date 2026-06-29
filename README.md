# rdf2pg12-py

Python implementation of the RDF 1.2-aware `rdf2pg` prototype.

This repository is distributed under the MIT License. See `LICENSE`.

This implementation:

- parses RDF 1.1 and RDF 1.2 inputs natively,
- normalizes graph syntaxes such as Turtle or N-Triples to the internal dataset model, i.e. asserted triples become asserted quads with `graph_name=None`,
- does not depend on `pyoxigraph`,
- supports the `-gdm`, `-sdm`, and `-cdm` mappings,
- writes YARS-PG or JSON debug output.

## Requirements

- Python 3.12+

## Installation

From the repository root:

```bash
python3 -m pip install -e .
```

For development work, install the test dependency set:

```bash
python3 -m pip install -e .[dev]
```

If you do not want to install the package, you can run it directly with `PYTHONPATH`:

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli --help
```

## Command line interface

The CLI supports exactly one mapping mode at a time:

```text
-gdm RDF_FILE
-sdm RDF_FILE
-cdm RDF_FILE RDFS_FILE
```

Useful options:

- `--output-dir DIR`
- `--output-format yarspg|json`
- `--dataset-mode reject|flatten|named-graph-property|native`
- `--triple-term-mode native|basic-encode|reject`
- `--literal-mode lossless|flattened`
- `--rdf-version-mode auto|1.1|1.2-basic|1.2`
- `--verbose`
- `--fail-on-warning`

Current explicit non-implementations:

- `--triple-term-mode basic-encode`
- `--bnode-mode skolemize`

## Output files

For YARS-PG output:

- `instance.ypg`
- `schema.ypg` when the selected mapping produces schema output

For JSON output:

- `instance.json`
- `schema.json`

## Examples

All commands below assume they are run from the repository root.

### 1. Generic mapping for a simple RDF 1.1 graph

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -gdm testdata/rdf11/simple.ttl \
  --output-dir /tmp/rdf2pg12-py-gdm-simple
```

### 2. Generic mapping for RDF 1.2 annotated statements

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -gdm testdata/rdf12/annotated-short.ttl \
  --dataset-mode native \
  --output-dir /tmp/rdf2pg12-py-gdm-annotated
```

### 3. Generic mapping with JSON debug output

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -gdm testdata/rdf12/reified-triple.ttl \
  --output-format json \
  --output-dir /tmp/rdf2pg12-py-gdm-json
```

### 4. Generic mapping for named graphs

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -gdm testdata/dataset/named.trig \
  --dataset-mode native \
  --output-dir /tmp/rdf2pg12-py-gdm-dataset
```

Use `--dataset-mode flatten` if you want to ignore graph names.

### 5. Simple mapping with lossless literal representation

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -sdm testdata/rdf12/dirlang.ttl \
  --literal-mode lossless \
  --output-dir /tmp/rdf2pg12-py-sdm-lossless
```

### 6. Simple mapping with flattened literals

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -sdm testdata/rdf11/simple.ttl \
  --literal-mode flattened \
  --output-dir /tmp/rdf2pg12-py-sdm-flat
```

### 7. Complete mapping with an RDF schema

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -cdm testdata/rdf11/simple.ttl testdata/rdf11/simple-schema.ttl \
  --output-dir /tmp/rdf2pg12-py-cdm
```

### 8. Force rejection of triple terms

```bash
PYTHONPATH=src python3 -m rdf2pg12_py.cli \
  -gdm testdata/rdf12/unasserted-triple-term.ttl \
  --triple-term-mode reject \
  --output-dir /tmp/rdf2pg12-py-reject
```

This command is expected to fail because the input contains RDF 1.2 triple terms.

### 9. Show generated files

```bash
find /tmp/rdf2pg12-py-gdm-simple -maxdepth 1 -type f | sort
sed -n '1,12p' /tmp/rdf2pg12-py-gdm-simple/instance.ypg
```

### 10. Run the Python tests

```bash
PYTHONPATH=src pytest -q tests
```

## Paper experiment tooling

The `scripts/` directory contains the tooling used to generate and evaluate the paper workloads:

- `generate_synthetic_rdf12.py` creates the synthetic RDF 1.2 workloads and schema variants.
- `fetch_w3c_rdf12_tests.py` downloads the positive W3C RDF 1.2 test-suite material used by the evaluation.
- `run_experimental_evaluation.py` runs the synthetic, W3C, and YAGO-derived evaluations and writes the machine-readable results consumed by the paper.

These scripts are intended to run from this package inside the larger paper workspace, where the sibling data and article paths exist. The YAGO-derived evaluation also requires the full `yago-wd-annotated-facts-full.nt` source file to be present.

Typical command sequence:

```bash
PYTHONPATH=src python3 scripts/generate_synthetic_rdf12.py
PYTHONPATH=src python3 scripts/fetch_w3c_rdf12_tests.py
PYTHONPATH=src python3 scripts/run_experimental_evaluation.py
```

## RDF 1.2 notes

The Python parser is the reference implementation for the most recent concrete syntax used in this repository, including:

- triple terms such as `<<( :s :p :o )>>`,
- reification shortcut forms such as `<< :s :p :o >>`,
- explicit reifier shortcut `~`,
- annotation blocks `{| ... |}`,
- nested annotation blocks,
- directional language-tagged strings,
- RDF collections and blank-node property lists,
- TriG graph blocks and N-Quads graph labels.

The parser normalizes concrete syntax to the internal RDF 1.2 term model before mapping.

## Troubleshooting

If you see `Named graphs present but --dataset-mode=reject`, rerun with one of:

- `--dataset-mode flatten`
- `--dataset-mode named-graph-property`
- `--dataset-mode native`

If you see `Triple terms in subject position are invalid in native RDF 1.2 mode`, the input is intentionally rejected because RDF 1.2 does not allow triple terms in subject position.
