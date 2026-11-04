"""
Postman Documenter to Markdown Converter (v3 - Cross-platform)
Intercepts Postman's internal API via Playwright headless browser.

Supports: Windows, macOS, Linux | Python 3.8+

Usage:
    python postman_to_md.py <postman_url> [output_file.md]
    python postman_to_md.py --json collection.json [output_file.md]

Example:
    python postman_to_md.py "https://documenter.getpostman.com/view/17351666/2sBYHSzgaB" api_docs.md
"""

import sys
import re
import json
import argparse
from pathlib import Path
from typing import Optional, Tuple

# ── Python version check ──────────────────────────────────────────────────────
if sys.version_info < (3, 8):
    sys.exit("[ERROR] Python 3.8 or higher is required.")


# ── Dependency bootstrap ──────────────────────────────────────────────────────
def _ensure(pkg: str, import_name: Optional[str] = None) -> None:
    import importlib
    import subprocess
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print("[*] Installing {}...".format(pkg))
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg]
        )


_ensure("requests")
_ensure("beautifulsoup4", "bs4")
_ensure("playwright")

import requests
from bs4 import BeautifulSoup


# ── Playwright fetch + API intercept ─────────────────────────────────────────

def fetch_collection_via_playwright(url: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Open the Postman Documenter page in a headless browser and intercept
    two internal API calls:
      - /api/collections/...  -> full collection structure
      - /api/examples/...     -> example responses per endpoint

    Returns (collection_data, examples_data).
    """
    from playwright.sync_api import sync_playwright

    collection_data: Optional[dict] = None
    examples_data: Optional[dict] = None

    print("[*] Launching headless browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):  # type: ignore
            nonlocal collection_data, examples_data
            r_url = response.url
            try:
                if "/api/collections/" in r_url and "versionTag" in r_url:
                    body = response.body()
                    if body:
                        collection_data = json.loads(body.decode("utf-8"))
                        print("  [+] Captured collection: {}...".format(r_url[:80]))
                elif "/api/examples/" in r_url:
                    body = response.body()
                    if body:
                        examples_data = json.loads(body.decode("utf-8"))
                        print("  [+] Captured examples:   {}...".format(r_url[:80]))
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4000)
        browser.close()

    return collection_data, examples_data


# ── Helpers ───────────────────────────────────────────────────────────────────

def slug(text: str) -> str:
    """Convert text to a GitHub-compatible Markdown anchor slug."""
    return re.sub(r"[^\w\s-]", "", text).strip().lower().replace(" ", "-")


def build_examples_map(examples_data: Optional[dict]) -> dict:
    """Build a map of item_id -> list of example responses."""
    if not examples_data or "data" not in examples_data:
        return {}
    mapping: dict = {}
    for entry in examples_data.get("data", []):
        iid = entry.get("item_id")
        if iid:
            mapping[iid] = entry.get("example", [])
    return mapping


def resolve_collection(raw: dict) -> Optional[dict]:
    """Find the collection object inside various possible JSON wrappers."""
    if "collection" in raw:
        col = raw["collection"]
        if isinstance(col, dict) and "info" in col:
            return col
    if "info" in raw and "item" in raw:
        return raw
    # Deep search
    for v in raw.values():
        if isinstance(v, dict) and "info" in v and "item" in v:
            return v
    return None


# ── Markdown generator ────────────────────────────────────────────────────────

def collection_to_markdown(
    collection: dict, examples_map: dict, source_url: str
) -> str:
    info = collection.get("info", {})
    title = info.get("name", "API Documentation")
    description = info.get("description", "")

    lines = ["# {}\n".format(title)]
    if description:
        lines.append("{}\n".format(description))
    lines.append("> Source: {}\n".format(source_url))
    lines.append("---\n")

    toc: list = []
    body: list = []

    def process_item(item: dict, depth: int = 2) -> None:
        name = item.get("name", "Unnamed")
        sub_items = item.get("item", [])
        item_id = item.get("id", "")

        if sub_items:
            indent = "  " * (depth - 2)
            toc.append("{}- [{}](#{})".format(indent, name, slug(name)))
            body.append("\n{} {}\n".format("#" * depth, name))
            desc = item.get("description", "")
            if desc:
                body.append("{}\n".format(desc))
            for sub in sub_items:
                process_item(sub, depth + 1)
            return

        # ── Request item ──────────────────────────────────────────────────────
        request = item.get("request", {})
        if isinstance(request, str):
            request = {"method": "GET", "url": {"raw": request}}

        method = request.get("method", "GET").upper()
        url_obj = request.get("url", {})

        if isinstance(url_obj, str):
            url_raw = url_obj
            query_params: list = []
        elif isinstance(url_obj, dict):
            url_raw = url_obj.get("raw", "")
            if not url_raw:
                host = ".".join(url_obj.get("host", []))
                path = "/".join(
                    p if isinstance(p, str) else p.get("value", str(p))
                    for p in url_obj.get("path", [])
                )
                url_raw = "{}/{}".format(host, path) if host else "/{}".format(path)
            query_params = url_obj.get("query", [])
        else:
            url_raw = ""
            query_params = []

        req_desc = request.get("description", "")
        headers = request.get("header", [])
        req_body = request.get("body", {})

        indent = "  " * (depth - 2)
        toc.append("{}- [{}](#{})".format(indent, name, slug(name)))
        body.append("\n{} {}\n".format("#" * depth, name))
        body.append("**Method:** `{}`  ".format(method))
        body.append("**URL:** `{}`\n".format(url_raw))

        if req_desc:
            body.append("\n{}\n".format(req_desc))

        # Auth
        auth = request.get("auth")
        if auth and isinstance(auth, dict):
            body.append("\n**Auth:** `{}`\n".format(auth.get("type", "")))

        # Query params
        active_params = [q for q in query_params if not q.get("disabled")]
        if active_params:
            body.append("\n**Query Parameters:**\n")
            body.append("| Key | Value | Description |")
            body.append("|-----|-------|-------------|")
            for q in active_params:
                body.append("| `{}` | `{}` | {} |".format(
                    q.get("key", ""), q.get("value", ""), q.get("description", "")
                ))
            body.append("")

        # Headers
        active_headers = [h for h in headers if not h.get("disabled")]
        if active_headers:
            body.append("\n**Headers:**\n")
            body.append("| Key | Value |")
            body.append("|-----|-------|")
            for h in active_headers:
                body.append("| `{}` | `{}` |".format(
                    h.get("key", ""), h.get("value", "")
                ))
            body.append("")

        # Request body
        if req_body and isinstance(req_body, dict):
            mode = req_body.get("mode", "")
            if mode == "raw":
                raw = req_body.get("raw", "").strip()
                lang = (
                    req_body.get("options", {})
                    .get("raw", {})
                    .get("language", "json")
                )
                if raw:
                    body.append("\n**Request Body ({}):**\n".format(mode))
                    body.append("```{}".format(lang))
                    body.append(raw)
                    body.append("```\n")
            elif mode == "formdata":
                fds = [f for f in req_body.get("formdata", []) if not f.get("disabled")]
                if fds:
                    body.append("\n**Request Body (form-data):**\n")
                    body.append("| Key | Value | Type |")
                    body.append("|-----|-------|------|")
                    for fd in fds:
                        body.append("| `{}` | `{}` | {} |".format(
                            fd.get("key", ""), fd.get("value", ""), fd.get("type", "text")
                        ))
                    body.append("")
            elif mode == "urlencoded":
                ues = [u for u in req_body.get("urlencoded", []) if not u.get("disabled")]
                if ues:
                    body.append("\n**Request Body (x-www-form-urlencoded):**\n")
                    body.append("| Key | Value |")
                    body.append("|-----|-------|")
                    for ue in ues:
                        body.append("| `{}` | `{}` |".format(
                            ue.get("key", ""), ue.get("value", "")
                        ))
                    body.append("")
            elif mode == "graphql":
                gql = req_body.get("graphql", {})
                if gql.get("query"):
                    body.append("\n**GraphQL Query:**\n")
                    body.append("```graphql")
                    body.append(gql["query"].strip())
                    body.append("```\n")
                if gql.get("variables"):
                    body.append("\n**GraphQL Variables:**\n")
                    body.append("```json")
                    body.append(gql["variables"].strip())
                    body.append("```\n")

        # Example responses
        examples = examples_map.get(item_id, [])
        inline_responses = item.get("response", [])
        all_responses = examples + inline_responses

        if all_responses:
            body.append("\n**Example Responses:**\n")
            for ex in all_responses:
                if "response" in ex:
                    resp = ex["response"]
                    ex_name = ex.get("name", "Response")
                    resp_body_text = resp.get("body", "")
                    resp_code = resp.get("code", "")
                    resp_status = resp.get("status", "")
                else:
                    ex_name = ex.get("name", "Response")
                    resp_body_text = ex.get("body", "")
                    resp_code = ex.get("code", "")
                    resp_status = ex.get("status", "")

                label = "**{}**".format(ex_name)
                if resp_code:
                    label += " -- `{} {}`".format(resp_code, resp_status)
                body.append("{}\n".format(label))

                if resp_body_text:
                    lang = "json"
                    try:
                        json.loads(resp_body_text)
                    except Exception:
                        lang = "text"
                    body.append("```{}".format(lang))
                    body.append(resp_body_text.strip())
                    body.append("```\n")

    for item in collection.get("item", []):
        process_item(item, depth=2)

    if toc:
        lines.append("## Table of Contents\n")
        lines.extend(toc)
        lines.append("")

    lines.extend(body)
    return "\n".join(lines)


# ── Entry points ──────────────────────────────────────────────────────────────

def convert(url: str, output_path: str) -> None:
    collection_data, examples_data = fetch_collection_via_playwright(url)

    if not collection_data:
        sys.exit(
            "[ERROR] Could not capture collection data.\n"
            "Make sure the collection is publicly accessible."
        )

    collection = resolve_collection(collection_data)
    if not collection:
        sys.exit(
            "[ERROR] Unexpected collection JSON structure:\n"
            + json.dumps(collection_data, indent=2)[:400]
        )

    print("[*] Collection : {}".format(collection.get("info", {}).get("name", "(unknown)")))
    print("[*] Top-level items: {}".format(len(collection.get("item", []))))

    examples_map = build_examples_map(examples_data)
    print("[*] Example responses mapped: {} endpoints".format(len(examples_map)))

    markdown = collection_to_markdown(collection, examples_map, url)
    out = Path(output_path)
    out.write_text(markdown, encoding="utf-8")
    print("[OK] Saved to: {}".format(out.resolve()))


def convert_from_json(json_path: str, output_path: str, source_url: str = "") -> None:
    print("[*] Reading: {}".format(json_path))
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    collection = resolve_collection(data) or data
    markdown = collection_to_markdown(collection, {}, source_url or json_path)
    out = Path(output_path)
    out.write_text(markdown, encoding="utf-8")
    print("[OK] Saved to: {}".format(out.resolve()))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a public Postman Documenter URL to Markdown."
    )
    parser.add_argument(
        "input",
        help="Postman Documenter URL  OR  path to Postman Collection JSON (use --json)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="api_docs.md",
        help="Output Markdown file (default: api_docs.md)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Treat INPUT as a local Postman Collection JSON file",
    )
    args = parser.parse_args()

    if args.json:
        convert_from_json(args.input, args.output)
    else:
        convert(args.input, args.output)


if __name__ == "__main__":
    main()
