"""Build and serve a local HTML view of the Wizard evaluation cases."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from metis.core.console import console

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent
REPO = SUITE.parents[2]
CASES = SUITE / "cases"
OUTPUT = SUITE / ".reviewer"


def _file(root: Path, relative: str) -> dict[str, Any]:
    source = (root / relative).resolve()
    if not source.is_relative_to(root.resolve()):
        raise ValueError(f"File is outside its case: {relative}")
    result: dict[str, Any] = {"path": relative, "name": source.name}
    if not source.is_file():
        return {**result, "missing": True}
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    result["url"] = f"data:application/octet-stream;base64,{encoded}"
    result["bytes"] = source.stat().st_size
    result["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    result["text"] = source.read_text(encoding="utf-8")
    return result


def build() -> Path:
    """Write generated previews only to the ignored reviewer directory."""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    css = (HERE / "reviewer.css").read_text()
    for family, weight in (("lato", 400), ("lato", 700), ("jetbrains-mono", 400)):
        name = f"{family}-latin-{weight}-normal.woff2"
        source = REPO / "apps/web/node_modules/@fontsource" / family / "files" / name
        if source.exists():
            encoded = base64.b64encode(source.read_bytes()).decode("ascii")
            css = css.replace(
                f"url('fonts/{name}')", f"url('data:font/woff2;base64,{encoded}')"
            )
        else:
            css = css.replace(f"url('fonts/{name}')", "local('Arial')")
    config = yaml.safe_load((CASES / "config.yaml").read_text())
    cases = []
    for relative in config["cases"]:
        root = (CASES / relative).resolve()
        if not root.is_relative_to(CASES.resolve()) or root == CASES.resolve():
            raise ValueError(f"Case is outside the evaluation folder: {relative}")
        output = _file(root, "outputs/specification.yaml")
        spec = yaml.safe_load(output["text"])
        cases.append(
            {
                "id": root.name,
                "prompt": _file(root, "inputs/prompt.md"),
                "documents_url": quote(f"../cases/{relative}/inputs/"),
                "has_documents": any(
                    item.is_file()
                    and item.name != "prompt.md"
                    and not any(
                        part.startswith(".")
                        for part in item.relative_to(root / "inputs").parts
                    )
                    for item in (root / "inputs").rglob("*")
                ),
                "output": output,
                "specification": spec,
            }
        )
    data = json.dumps(
        {"id": config["id"], "version": config["version"], "cases": cases}
    )
    # Embedded document text must not terminate the JSON script element.
    data = data.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    script = (HERE / "reviewer.js").read_text()
    html = (HERE / "index.html").read_text()
    html = html.replace(
        '<link rel="stylesheet" href="reviewer.css">', f"<style>{css}</style>"
    )
    html = html.replace('<script src="reviewer.js" defer></script>', "")
    html = html.replace(
        "</body>",
        f'<script id="case-data" type="application/json">{data}</script>'
        f"<script>{script}</script></body>",
    )
    (OUTPUT / "wizard-review.html").write_text(html)
    (OUTPUT / "index.html").write_text(html)
    console.print(f"Built {len(cases)} cases: {OUTPUT / 'wizard-review.html'}")
    return OUTPUT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve", action="store_true", help="Serve the reviewer locally"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    build()
    if args.serve:
        handler = partial(SimpleHTTPRequestHandler, directory=str(SUITE))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            console.print(f"Reviewer: http://127.0.0.1:{args.port}/.reviewer/")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                console.print("Reviewer stopped.")


if __name__ == "__main__":
    main()
