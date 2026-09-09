#!/usr/bin/env python3
"""Hash publicly linked report PDFs without credentials or storing PDF bytes.

An unchanged URL is not an unchanged document. This read-only observer writes a
URL -> SHA256 observation JSON outside the repository for the content detector.
Only explicitly trusted public origins are contacted, including redirects.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import ipaddress
import json
from pathlib import Path
import socket
import sys
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

TRUSTED_HOSTS = frozenset({"nthszgnbqgjfqnzgytym.supabase.co", "metanomia.org",
                           "www.metanomia.org", "metanomia-site.vercel.app"})
MAX_BYTES = 80 * 1024 * 1024


def validate_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in TRUSTED_HOSTS or parts.username
            or parts.password or parts.port not in {None, 443}):
        raise ValueError("PDF origin is not approved for credential-free observation: " + url)
    if not unquote(parts.path).lower().endswith(".pdf"):
        raise ValueError("External source must be a direct PDF URL: " + url)
    try:
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if exc.errno != socket.EAI_AGAIN:
            raise
        # Some cloud runtimes provide standard HTTPS transport without direct
        # DNS resolution. Keep the exact host/TLS/redirect rules and let the
        # existing urllib transport enforce its network policy; do not change
        # proxy, resolver, certificate, or authentication configuration.
        print("dns_preflight_unavailable: standard HTTPS transport will be attempted; IP preflight was not verified.",
              file=sys.stderr, flush=True)
        return url
    if not addresses:
        raise ValueError("External PDF DNS returned no addresses.")
    for item in addresses:
        if not ipaddress.ip_address(item[4][0]).is_global:
            raise ValueError("External PDF must resolve only to public IP addresses.")
    return url


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def observe(url, opener=None):
    validate_url(url)
    opener = opener or build_opener(SafeRedirects())
    request = Request(url, headers={"User-Agent": "Metanomia-Content-Observer/1.0",
                                   "Accept": "application/pdf", "Cache-Control": "no-cache"})
    digest = hashlib.sha256()
    count = 0
    prefix = b""
    with opener.open(request, timeout=45) as response:
        validate_url(response.geturl())
        while True:
            block = response.read(1024 * 1024)
            if not block: break
            if not prefix: prefix = block[:1024]
            count += len(block)
            if count > MAX_BYTES: raise ValueError("PDF exceeds the safe observation size limit.")
            digest.update(block)
    if b"%PDF-" not in prefix:
        raise ValueError("External URL did not return a PDF document: " + url)
    return digest.hexdigest()


def urls(repository):
    spec = importlib.util.spec_from_file_location("observed_content", Path(__file__).with_name("content-translation.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _sources, external = module.discover(repository)
    return sorted({entry["url"] for entry in external
                   if entry["kind"] == "pdf" and module.public_external_pdf(entry["url"])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repository.resolve(strict=True)
    output = args.output.resolve()
    try:
        if args.output.is_symlink() or output == repo or repo in output.parents:
            raise ValueError("PDF observations must be written outside the repository.")
        result = {}
        errors = {}
        for url in urls(repo):
            try:
                result[url] = observe(url)
            except Exception as exc:
                errors[url] = str(exc)
            print(f"Checked external PDF {len(result) + len(errors)}", file=sys.stderr, flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1.0", "observations": result, "errors": errors}
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"observed_count": len(result), "error_count": len(errors), "output": str(output)}))
        return 0
    except Exception as exc:
        print(f"External PDF observation blocked: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
