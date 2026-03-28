import requests
import json
import argparse
import base64
import os
from datetime import datetime, timezone


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


def crawl_supabase(base_url, api_key, aggresive=False):
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    results = []
    ref = extract_ref_from_api_key(api_key)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    result_file = os.path.join(output_dir, f"{ref}-{timestamp}.json")

    print(f"[*] Fetching schema from: {base_url}")
    try:
        # 1. Get the Swagger/OpenAPI Schema
        schema_response = requests.get(base_url, headers=headers)
        schema_response.raise_for_status()
        schema = schema_response.json()

        # 2. Extract paths (Tables and RPCs)
        paths = schema.get("paths", {})

        for path in paths.keys():
            # Skip the root path itself
            if path == "/":
                continue

            path_spec = paths.get(path, {})
            can_post = "post" in path_spec
            full_path = f"{base_url.rstrip('/')}{path}"
            print(f"[*] Testing: {path}")

            try:
                # Start with GET. Retry with POST when GET errors/empty and POST is available.
                method_used = "GET"
                resp = requests.get(
                    full_path,
                    headers=headers,
                    params={"select": "*"} if "/rpc/" not in path else {},
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
            json.dump({"schema": schema, "results": results}, f, indent=4)
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
        help="Try POST fallback on all POST-capable endpoints (default is RPC-only)",
    )
    args = parser.parse_args()

    base_url = args.base_url
    api_key = args.api_key

    if not base_url or not api_key:
        parser.error("Both --base-url and --api-key are required.")

    return base_url, api_key, args.aggresive


if __name__ == "__main__":
    base_url_arg, api_key_arg, aggresive_arg = parse_args()
    crawl_supabase(base_url_arg, api_key_arg, aggresive_arg)
