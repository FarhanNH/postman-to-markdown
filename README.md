# postman-to-markdown

Convert a **public Postman Documenter URL** into a clean, structured **Markdown file** — automatically, using a headless browser to intercept Postman's internal API.

> Works with any public collection at `https://documenter.getpostman.com/view/...`

---

## How It Works

The script launches a headless Chromium browser (via Playwright) and intercepts two internal Postman API calls made when the page loads:

- `documenter.gw.postman.com/api/collections/...` — full collection structure (folders, endpoints, headers, bodies)
- `documenter.gw.postman.com/api/examples/...` — example responses per endpoint

This approach is more reliable than HTML scraping because the data comes directly from the structured API response.

---

## Requirements

- **Python** 3.10 or higher
- **pip** (bundled with Python)
- Internet connection
- A **public** Postman Documenter URL

### Python packages

| Package | Version | Purpose |
|---------|---------|---------|
| `requests` | ≥ 2.28 | HTTP fetching fallback |
| `beautifulsoup4` | ≥ 4.12 | HTML parsing fallback |
| `playwright` | ≥ 1.40 | Headless browser / JS rendering |

> The script will auto-install missing packages on first run. See manual install below.

---

## Installation

### 1. Clone this repository

```bash
git clone https://github.com/FarhanNH/postman-to-markdown.git
cd postman-to-markdown
```

### 2. (Recommended) Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright's Chromium browser

```bash
python -m playwright install chromium
```

That's it — no API keys or authentication required.

---

## Usage

### Convert from a Postman Documenter URL

```bash
python postman_to_md.py "https://documenter.getpostman.com/view/YOUR_ID/YOUR_COLLECTION" output.md
```

**Example:**

```bash
python postman_to_md.py "https://documenter.getpostman.com/view/17351666/2sBYHSzgaB" api_docs.md
```

### Convert from a local Postman Collection JSON export

If you have exported your collection as a `.json` file from Postman:

```bash
python postman_to_md.py --json MyCollection.json output.md
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `input` | Yes | Postman Documenter URL **or** path to a JSON file (with `--json`) |
| `output` | No | Output filename (default: `api_docs.md`) |
| `--json` | No | Treat `input` as a local Postman Collection JSON file |

---

## Output Format

The generated Markdown file contains:

- **Title** and description of the collection
- **Table of Contents** with anchor links
- For each endpoint:
  - HTTP method and full URL
  - Description
  - Auth type (if specified)
  - Query parameters (table)
  - Request headers (table)
  - Request body (`raw`, `form-data`, `x-www-form-urlencoded`, or `graphql`)
  - Example responses with status codes and JSON body

**Example output structure:**

```
# My API Collection

> Source: https://documenter.getpostman.com/...

---

## Table of Contents
- [Auth](#auth)
  - [Login](#login)
- [Users](#users)
  - [Get All Users](#get-all-users)

## Auth

### Login

**Method:** `POST`
**URL:** `https://api.example.com/auth/login`

**Request Body (raw):**
```json
{
  "username": "admin",
  "password": "secret"
}
```

**Example Responses:**

**200 - OK**
```json
{ "token": "eyJ..." }
```
```

---

## Limitations

- Only works with **publicly accessible** Postman collections (no login required to view).
- Postman renders its documentation via JavaScript — a headless browser is required. Pure HTTP fetch is attempted first as a faster fallback.
- Rate limiting by Postman may apply if many requests are made in a short time.

---

## License

MIT
