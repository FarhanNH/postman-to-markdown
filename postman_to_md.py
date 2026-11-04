"""
Postman Documenter to Markdown Converter (v2 - API Intercept)
Intercepts Postman's internal API calls via Playwright to get full collection data.

Usage:
    python postman_to_md.py <postman_url> [output_file.md]
    python postman_to_md.py --json collection.json [output_file.md]
"""

import sys
import re
import json
import argparse
from pathlib import Path

def _ensure(pkg, import_name=None):
    import importlib, subprocess
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"[*] Installing {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pkg])

_ensure("requests")
_ensure("beautifulsoup4", "bs4")
_ensure("playwright")

import requests
from bs4 import BeautifulSoup


# ─── Postman internal API fetch ───────────────────────────────────────────────

def fetch_collection_via_playwright(url: str) -> tuple[dict | None, dict | None]:
    """
    Open the Postman Documenter page in a headless browser,
    intercept the two internal API calls:
      - /api/collections/...  -> collection JSON
      - /api/examples/...     -> examples JSON
    Returns (collection_data, examples_data).
    """
    from playwright.sync_api import sync_playwright

    collection_data = None
    examples_data = None

    print("[*] Launching headless browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):
            nonlocal collection_data, examples_data
            r_url = response.url
            try:
                if "/api/collections/" in r_url and "versionTag" in r_url:
                    body = response.body()
                    if body:
                        collection_data = json.loads(body.decode("utf-8"))
                        print(f"  [+] Captured collection API: {r_url[:80]}...")
                elif "/api/examples/" in r_url:
                    body = response.body()
                    if body:
                        examples_data = json.loads(body.decode("utf-8"))
                        print(f"  [+] Captured examples API: {r_url[:80]}...")
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(4000)
        browser.close()

    return collection_data, examples_data


# ─── Markdown generator ───────────────────────────────────────────────────────

def slug(text: str) -> str:
    return re.sub(r"[^\w\s-]", "", text).strip().lower().replace(" ", "-")


def build_examples_map(examples_data: dict | None) -> dict:
    """Build a map of item_id -> list of example responses."""
    if not examples_data or "data" not in examples_data:
        return {}
    mapping = {}
    for entry in examples_data.get("data", []):
        iid = entry.get("item_id")
        if iid:
            mapping[iid] = entry.get("example", [])
    return mapping


def collection_to_markdown(collection: dict, examples_map: dict, source_url: str) -> str:
    info = collection.get("info", {})
    title = info.get("name", "API Documentation")
    description = info.get("description", "")

    lines = [f"# {title}\n"]
    if description:
        lines.append(f"{description}\n")
    lines.append(f"> Source: {source_url}\n")
    lines.append("---\n")

    toc: list[str] = []
    body: list[str] = []

    def process_item(item: dict, depth: int = 2):
        name = item.get("name", "Unnamed")
        sub_items = item.get("item", [])
        item_id = item.get("id", "")

        if sub_items:
            indent = "  " * (depth - 2)
            toc.append(f"{indent}- [{name}](#{slug(name)})")
            body.append(f"\n{'#' * depth} {name}\n")
            desc = item.get("description", "")
            if desc:
                body.append(f"{desc}\n")
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
            query_params = []
        elif isinstance(url_obj, dict):
            url_raw = url_obj.get("raw", "")
            if not url_raw:
                host = ".".join(url_obj.get("host", []))
                path = "/".join(
                    p if isinstance(p, str) else p.get("value", str(p))
                    for p in url_obj.get("path", [])
                )
                url_raw = f"{host}/{path}" if host else f"/{path}"
            query_params = url_obj.get("query", [])
        else:
            url_raw = ""
            query_params = []

        req_desc = request.get("description", "")
        headers = request.get("header", [])
        req_body = request.get("body", {})

        indent = "  " * (depth - 2)
        toc.append(f"{indent}- [{name}](#{slug(name)})")

        body.append(f"\n{'#' * depth} {name}\n")
        body.append(f"**Method:** `{method}`  ")
        body.append(f"**URL:** `{url_raw}`\n")

        if req_desc:
            body.append(f"\n{req_desc}\n")

        # Auth
        auth = request.get("auth")
        if auth and isinstance(auth, dict):
            auth_type = auth.get("type", "")
            body.append(f"\n**Auth:** `{auth_type}`\n")

        # Query params
        active_params = [q for q in query_params if not q.get("disabled")]
        if active_params:
            body.append("\n**Query Parameters:**\n")
            body.append("| Key | Value | Description |")
            body.append("|-----|-------|-------------|")
            for q in active_params:
                body.append(
                    f"| `{q.get('key','')}` | `{q.get('value','')}` | {q.get('description','')} |"
                )
            body.append("")

        # Headers
        active_headers = [h for h in headers if not h.get("disabled")]
        if active_headers:
            body.append("\n**Headers:**\n")
            body.append("| Key | Value |")
            body.append("|-----|-------|")
            for h in active_headers:
                body.append(f"| `{h.get('key','')}` | `{h.get('value','')}` |")
            body.append("")

        # Request body
        if req_body and isinstance(req_body, dict):
            mode = req_body.get("mode", "")
            if mode == "raw":
                raw = req_body.get("raw", "").strip()
                lang = req_body.get("options", {}).get("raw", {}).get("language", "json")
                if raw:
                    body.append(f"\n**Request Body ({mode}):**\n")
                    body.append(f"```{lang}")
                    body.append(raw)
                    body.append("```\n")
            elif mode == "formdata":
                fds = [f for f in req_body.get("formdata", []) if not f.get("disabled")]
                if fds:
                    body.append("\n**Request Body (form-data):**\n")
                    body.append("| Key | Value | Type |")
                    body.append("|-----|-------|------|")
                    for fd in fds:
                        body.append(
                            f"| `{fd.get('key','')}` | `{fd.get('value','')}` | {fd.get('type','text')} |"
                        )
                    body.append("")
            elif mode == "urlencoded":
                ues = [u for u in req_body.get("urlencoded", []) if not u.get("disabled")]
                if ues:
                    body.append("\n**Request Body (x-www-form-urlencoded):**\n")
                    body.append("| Key | Value |")
                    body.append("|-----|-------|")
                    for ue in ues:
                        body.append(f"| `{ue.get('key','')}` | `{ue.get('value','')}` |")
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

        # Example responses (from intercepted examples API)
        examples = examples_map.get(item_id, [])
        # Also check inline responses
        inline_responses = item.get("response", [])
        all_responses = examples + inline_responses

        if all_responses:
            body.append("\n**Example Responses:**\n")
            for ex in all_responses:
                if "response" in ex:  # from examples API
                    resp = ex["response"]
                    ex_name = ex.get("name", "Response")
                    resp_body_text = resp.get("body", "")
                    resp_code = resp.get("code", "")
                    resp_status = resp.get("status", "")
                else:  # inline response
                    ex_name = ex.get("name", "Response")
                    resp_body_text = ex.get("body", "")
                    resp_code = ex.get("code", "")
                    resp_status = ex.get("status", "")

                body.append(f"**{ex_name}**" + (f" — `{resp_code} {resp_status}`" if resp_code else "") + "\n")
                if resp_body_text:
                    # Try to detect if it's JSON
                    lang = "json"
                    try:
                        json.loads(resp_body_text)
                    except Exception:
                        lang = "text"
                    body.append(f"```{lang}")
                    body.append(resp_body_text.strip())
                    body.append("```\n")

    for item in collection.get("item", []):
        process_item(item, depth=2)

    # Assemble
    if toc:
        lines.append("## Table of Contents\n")
        lines.extend(toc)
        lines.append("")
    lines.extend(body)
    return "\n".join(lines)


# ─── entry points ─────────────────────────────────────────────────────────────

def convert(url: str, output_path: str) -> None:
    collection_data, examples_data = fetch_collection_via_playwright(url)

    if not collection_data:
        print("[ERROR] Could not capture collection data from Postman API.")
        print("  Make sure the collection is publicly visible.")
        sys.exit(1)

    # The collection API may return {"collection": {...}} or the collection directly
    if "collection" in collection_data:
        collection = collection_data["collection"]
    elif "info" in collection_data:
        collection = collection_data
    else:
        # Try to find it
        for v in collection_data.values():
            if isinstance(v, dict) and "info" in v:
                collection = v
                break
        else:
            print("[ERROR] Unexpected collection JSON structure.")
            print(json.dumps(collection_data, indent=2)[:500])
            sys.exit(1)

    print(f"[*] Collection: {collection.get('info', {}).get('name', '(unknown)')}")
    print(f"[*] Items: {len(collection.get('item', []))}")

    examples_map = build_examples_map(examples_data)
    print(f"[*] Example responses mapped: {len(examples_map)} endpoints")

    markdown = collection_to_markdown(collection, examples_map, url)

    out = Path(output_path)
    out.write_text(markdown, encoding="utf-8")
    print(f"[OK] Saved to: {out.resolve()}")


def convert_from_json(json_path: str, output_path: str, source_url: str = "") -> None:
    print(f"[*] Reading: {json_path}")
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    if "collection" in data:
        collection = data["collection"]
    elif "info" in data:
        collection = data
    else:
        collection = data
    markdown = collection_to_markdown(collection, {}, source_url or json_path)
    out = Path(output_path)
    out.write_text(markdown, encoding="utf-8")
    print(f"[OK] Saved to: {out.resolve()}")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert a public Postman Documenter URL to Markdown."
    )
    parser.add_argument("input", help="Postman Documenter URL or Collection JSON path (--json)")
    parser.add_argument("output", nargs="?", default="api_docs.md", help="Output .md file")
    parser.add_argument("--json", action="store_true", help="Input is a local Postman Collection JSON file")
    args = parser.parse_args()

    if args.json:
        convert_from_json(args.input, args.output)
    else:
        convert(args.input, args.output)


if __name__ == "__main__":
    main()
