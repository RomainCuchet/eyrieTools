# Supabase Endpoint Scanner

A small Python CLI tool that scans a Supabase REST/OpenAPI schema and tests discovered endpoints.

It:
- Requests the OpenAPI schema from your Supabase REST base URL
- Iterates through all paths in the schema
- Tries `GET` first
- Optionally falls back to `POST` for eligible endpoints
- Saves schema and scan results to a timestamped JSON file

## File

- `scanner.py`: Main scanner script

## Requirements

- Python 3.8+
- `requests`

Install dependency:

```bash
pip install requests
```

## Usage

Run from this directory:

```bash
python scanner.py --base-url "https://<project-ref>.supabase.co/rest/v1/" --api-key "<SUPABASE_API_KEY>"
```

### Arguments

- `--base-url` (required): Supabase REST base URL
- `--api-key` (required): Supabase anon or service role API key
- `--aggresive` (optional): Enables wider POST fallback behavior

Notes:
- Without `--aggresive`, POST fallback is mainly attempted for RPC paths.

## Output

Scan results are written to:

- `output/<project-ref>-<UTC timestamp>.json`

The output JSON includes:
- `schema`: Raw OpenAPI schema payload
- `results`: Per-endpoint scan results with path, method, status code, and response snippet

## Example

```bash
python scanner.py \
  --base-url "https://abcd1234.supabase.co/rest/v1/" \
  --api-key "eyJhbGciOi..." \
  --aggresive
```

## Security Notes

- Treat API keys as secrets.
- Prefer least-privilege keys when scanning.
- Do not commit real API keys or scan outputs containing sensitive data.
