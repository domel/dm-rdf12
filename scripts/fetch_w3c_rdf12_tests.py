from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen


PYTHON_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PYTHON_ROOT.parents[1]
OUTPUT_DIR = PROJECT_ROOT / "zbior_danych" / "w3c-rdf12"
DATA_EXTENSIONS = (".nt", ".ttl", ".nq", ".trig")

SUITE_BASES = [
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-n-triples/c14n/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-n-triples/syntax/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-turtle/eval/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-turtle/syntax/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-n-quads/c14n/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-n-quads/syntax/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-trig/eval/",
    "https://w3c.github.io/rdf-tests/rdf/rdf12/rdf-trig/syntax/",
]


class LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self.links.append(href)


def suite_parts(base_url: str) -> tuple[str, str]:
    path_parts = [part for part in urlparse(base_url).path.split("/") if part]
    return path_parts[-2], path_parts[-1]


def local_path_for(base_url: str, file_url: str) -> Path:
    suite, section = suite_parts(base_url)
    return OUTPUT_DIR / suite / section / Path(urlparse(file_url).path).name


def read_url(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def parse_manifest_tests(text: str, base_url: str) -> list[dict[str, object]]:
    suite, section = suite_parts(base_url)
    records: list[dict[str, object]] = []
    pattern = re.compile(
        r"\n(?:trs:|:)[^\s]+\s+rdf:type\s+rdft:([A-Za-z0-9]+)\s*;(.*?)(?=\n(?:trs:|:)[^\s]+\s+rdf:type|\Z)",
        re.S,
    )
    for index, match in enumerate(pattern.finditer(text), start=1):
        test_type = match.group(1)
        body = match.group(2)
        actions = re.findall(r"mf:action\s+<([^>]+)>", body)
        results = re.findall(r"mf:result\s+<([^>]+)>", body)
        records.append(
            {
                "id": f"{suite}/{section}/{index}",
                "suite": suite,
                "section": section,
                "type": test_type,
                "positive": "Negative" not in test_type,
                "actions": actions,
                "results": results,
            }
        )
    return records


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, str]] = []
    tests: list[dict[str, object]] = []

    for base_url in SUITE_BASES:
        page = read_url(base_url).decode("utf-8")
        collector = LinkCollector()
        collector.feed(page)

        manifest_url = urljoin(base_url, "manifest.ttl")
        manifest_path = local_path_for(base_url, manifest_url)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_text = read_url(manifest_url).decode("utf-8")
        manifest_path.write_text(manifest_text, encoding="utf-8")
        tests.extend(parse_manifest_tests(manifest_text, base_url))

        file_urls = sorted(
            {
                urljoin(base_url, href)
                for href in collector.links
                if href.endswith(DATA_EXTENSIONS) and not href.endswith("manifest.ttl")
            }
        )
        for file_url in file_urls:
            path = local_path_for(base_url, file_url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(read_url(file_url))
            downloaded.append(
                {
                    "suite": suite_parts(base_url)[0],
                    "section": suite_parts(base_url)[1],
                    "url": file_url,
                    "file": str(path.relative_to(PROJECT_ROOT)),
                }
            )

    manifest = {
        "source_bases": SUITE_BASES,
        "downloaded_files": downloaded,
        "tests": tests,
    }
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"downloaded_files": len(downloaded), "tests": len(tests)}, indent=2))


if __name__ == "__main__":
    main()
