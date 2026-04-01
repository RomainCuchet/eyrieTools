import requests
import json
import argparse
import base64
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timezone

# Ensure the parent directory of this script is in sys.path for imports
web_dir = Path(__file__).resolve().parent.parent
if str(web_dir) not in sys.path:
    sys.path.insert(0, str(web_dir))

from utils.approval import require_approval


def extract_ref_from_api_key(api_key):
    try:
        parts = api_key.split(".")
        if len(parts) < 2:
            return "unknown_ref"

        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload + padding)
        payload_json = json.loads(decoded.decode("utf-8"))
        return payload_json.get("ref", "unknown_ref")
    except Exception:
        return "unknown_ref"


def extract_instance_from_base_url(base_url):
    match = re.search(r"//([^.]+)\.supabase", base_url)
    if match:
        return match.group(1)
    return "unknown_instance"


def parse_response_payload(response):
    try:
        return response.json()
    except ValueError:
        return response.text


def is_empty_payload(payload):
    if payload is None:
        return True
    if isinstance(payload, (list, dict)):
        return len(payload) == 0
    if isinstance(payload, str):
        return payload.strip() == ""
    return False


def looks_like_jwt(token):
    parts = token.split(".")
    return len(parts) == 3


def infer_api_key_type(api_key):
    if api_key.startswith("sb_publishable_"):
        return "sb_publishable"
    if api_key.startswith("sb_secret_"):
        return "sb_secret"
    if looks_like_jwt(api_key):
        return "jwt"
    return "unknown"


def build_options_metadata(base_url, api_key, aggresive, evil, seed_paths):
    used_flags = ["--base-url", "--api-key"]
    options_with_values = {
        "--base-url": base_url,
    }
    options_without_values = []
    api_key_type = infer_api_key_type(api_key)

    if api_key:
        options_without_values.append("--api-key")
    if aggresive:
        used_flags.append("--aggresive")
        options_without_values.append("--aggresive")
    if evil:
        used_flags.append("--evil")
        options_without_values.append("--evil")
    if seed_paths:
        used_flags.append("--paths")
        options_with_values["--paths"] = seed_paths

    return {
        "used_flags": used_flags,
        "api_key_type": api_key_type,
        "with_values": options_with_values,
        "without_values": options_without_values,
    }


@require_approval(["aggresive", "evil"], message=None)
def crawl_supabase(base_url, api_key, aggresive=False, evil=False, seed_paths=None):
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json",
    }
    if looks_like_jwt(api_key):
        headers["Authorization"] = f"Bearer {api_key}"

    results = []
    ref = extract_ref_from_api_key(api_key)
    instance = extract_instance_from_base_url(base_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    if ref != "unknown_ref" and ref != instance:
        result_prefix = f"{instance}-{ref}"
    else:
        result_prefix = instance

    result_file = os.path.join(output_dir, f"{result_prefix}-{timestamp}.json")
    options_metadata = build_options_metadata(
        base_url, api_key, aggresive, evil, seed_paths
    )

    rest_base_url = base_url.strip().rstrip("/")
    schema_url = f"{rest_base_url}/"

    print(f"[*] Fetching schema from: {schema_url}")
    schema = {}
    paths = {}
    try:
        # 1. Get the Swagger/OpenAPI Schema
        schema_response = requests.get(schema_url, headers=headers)
        schema_response.raise_for_status()
        schema = schema_response.json()
        # 2. Extract paths (Tables and RPCs)
        paths = schema.get("paths", {})
    except requests.exceptions.RequestException as e:
        if "/rest/v1" not in rest_base_url:
            print(
                "[!] Warning: request failed. If this is a Supabase REST API, you may be missing '/rest/v1' in --base-url."
            )
        if seed_paths:
            print(
                "[!] OpenAPI schema is not accessible with this key. Falling back to provided paths."
            )
            paths = {p: {} for p in seed_paths}
        else:
            print(
                f"[!] Critical Error: {e}. Use --paths users,table2,... to scan known paths without schema."
            )
            return

    try:
        for path in paths.keys():
            # Skip the root path itself
            if path == "/":
                continue

            path_spec = paths.get(path, {})
            can_post = "post" in path_spec
            full_path = f"{rest_base_url.rstrip('/')}{path}"
            print(f"[*] Testing: {path}")

            try:
                # Start with GET. Retry with POST when GET errors/empty and POST is available.
                method_used = "GET"
                params = {}
                if "/rpc/" not in path:
                    params["select"] = "*"
                if not evil:
                    params["limit"] = 1
                resp = requests.get(
                    full_path,
                    headers=headers,
                    params=params,
                )

                payload = parse_response_payload(resp)
                can_fallback_for_path = can_post and (aggresive or "/rpc/" in path)
                should_fallback_to_post = can_fallback_for_path and (
                    (not resp.ok) or is_empty_payload(payload)
                )

                if should_fallback_to_post:
                    method_used = "POST"
                    resp = requests.post(full_path, headers=headers, json={})
                    payload = parse_response_payload(resp)

                results.append(
                    {
                        "path": path,
                        "full_url": full_path,
                        "method": method_used,
                        "status_code": resp.status_code,
                        "response": (
                            payload if resp.status_code == 200 else str(payload)[:200]
                        ),
                    }
                )
            except Exception as e:
                results.append({"path": path, "error": str(e)})

        # 3. Final Output
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "instance": instance,
                    "schema": schema,
                    "options_used": options_metadata,
                    "results": results,
                },
                f,
                indent=4,
            )
        print(
            f"[+] Scan complete. Schema + {len(results)} endpoints logged to {result_file}"
        )

    except requests.exceptions.RequestException as e:
        print(f"[!] Critical Error: {e}")


def parse_args():
    parser = argparse.ArgumentParser(description="Scan Supabase REST/OpenAPI endpoints")
    parser.add_argument("--base-url", default=None, help="Supabase REST base URL")
    parser.add_argument("--api-key", default=None, help="Supabase anon/service API key")
    parser.add_argument(
        "--aggresive",
        action="store_true",
        help="Try POST fallback on all POST-capable endpoints (default is RPC-only) [WARNING: May be illegal without authorization]",
    )
    parser.add_argument(
        "--evil",
        action="store_true",
        help="Fetch all data from all endpoints (default is only one element per endpoint) [WARNING: Illegal without explicit authorization]",
    )
    parser.add_argument(
        "--paths",
        default=None,
        help="Comma-separated REST paths to scan when schema is unavailable, e.g. users,orders,/rpc/my_fn",
    )
    args = parser.parse_args()

    base_url = args.base_url
    api_key = args.api_key

    if not base_url or not api_key:
        parser.error("Both --base-url and --api-key are required.")

    seed_paths = None
    if args.paths:
        seed_paths = []
        for p in args.paths.split(","):
            cleaned = p.strip()
            if not cleaned:
                continue
            if not cleaned.startswith("/"):
                cleaned = f"/{cleaned}"
            seed_paths.append(cleaned)

    return base_url, api_key, args.aggresive, args.evil, seed_paths


if __name__ == "__main__":
    base_url_arg, api_key_arg, aggresive_arg, evil_arg, seed_paths_arg = parse_args()
    crawl_supabase(base_url_arg, api_key_arg, aggresive_arg, evil_arg, seed_paths_arg)
