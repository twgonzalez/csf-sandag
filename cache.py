"""Download-once caching with checksums.

Raw downloads land in ``data/raw/`` and are never modified afterwards. Every fetch records
the URL, the SHA-256 of what came back, the byte count, and the fetch time in
``data/raw/manifest.json``.
That manifest is what lets a reader confirm that the run they are looking at used the
same bytes as the run in the report (Hard constraint 7).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import requests

from config import RAW, Source

MANIFEST = RAW / "manifest.json"

#: A polite, identifiable user agent. Several federal file servers reject the default one.
USER_AGENT = "sandag-rhna-open-pipeline/0.1 (+https://github.com/; public-data reproducibility)"

_CHUNK = 1 << 20  # 1 MiB


class ChecksumMismatch(RuntimeError):
    """Raised when a downloaded file does not match the checksum pinned in ``config.SOURCES``.

    This is a hard failure, not a warning. A publisher silently reissuing a file under the same
    URL is exactly the situation Hard constraint 7 exists to catch.
    """


def _load_manifest() -> dict[str, dict]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def _save_manifest(manifest: dict[str, dict]) -> None:
    # sort_keys so the manifest itself is byte-stable across runs.
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in chunks so large files fit in memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _filename_for(source: Source) -> str:
    """Derive a stable cache filename from a source key and its URL suffix.

    The source key, not the URL basename, leads the filename so that two sources that happen to
    publish a file of the same name cannot collide.
    """
    tail = source.url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    suffix = ""
    for ext in (".csv.gz", ".zip", ".pdf", ".dat", ".txt", ".json", ".csv", ".gz"):
        if tail.endswith(ext):
            suffix = ext
            break
    if not suffix:
        suffix = ".json" if "$limit=" in source.url or source.url.endswith(".json") else ".bin"
    return f"{source.key}{suffix}"


def fetch(source: Source, *, refresh: bool = False, timeout: int = 120) -> Path:
    """Download ``source`` into the raw cache if it is not already there, and verify it.

    Args:
        source: The pinned source to fetch.
        refresh: Re-download even if a cached copy exists. Use when a publisher has issued a
            correction and you have updated the pinned checksum to match.
        timeout: Per-request timeout in seconds. Some Census bulk files are large but slow to
            start, so this is generous.

    Returns:
        Path to the cached raw file.

    Raises:
        ChecksumMismatch: If ``source.sha256`` is set and the bytes do not match it.
        requests.HTTPError: If the server does not return 200.
    """
    dest = RAW / _filename_for(source)
    manifest = _load_manifest()

    if dest.exists() and not refresh:
        recorded = manifest.get(source.key)
        if recorded and recorded.get("sha256") == sha256_of(dest):
            return dest
        # Cached file present but unrecorded or altered: re-verify from scratch.

    tmp = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": USER_AGENT}
    with requests.get(source.url, stream=True, timeout=timeout, headers=headers) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(_CHUNK):
                fh.write(chunk)

    digest = sha256_of(tmp)
    if source.sha256 is not None and digest != source.sha256:
        tmp.unlink(missing_ok=True)
        raise ChecksumMismatch(
            f"{source.key}: expected sha256 {source.sha256}, got {digest}.\n"
            f"URL: {source.url}\n"
            "The publisher has reissued this file. Review the change, then update the pinned "
            "checksum in config.SOURCES and note the vintage change in docs/status.md."
        )

    tmp.replace(dest)
    manifest[source.key] = {
        "url": source.url,
        "vintage": source.vintage,
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "fetched_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": dest.name,
    }
    _save_manifest(manifest)
    return dest


def fetch_url(key: str, url: str, *, refresh: bool = False, timeout: int = 120) -> Path:
    """Fetch a URL that is not in the pinned source registry.

    Used for the ACS table files, where one registry entry would have to become one entry per
    table. The manifest entry is identical in shape, so these files are just as auditable.
    """
    return fetch(
        Source(
            key=key,
            url=url,
            vintage="see config.ACS_VINTAGE",
            publisher="U.S. Census Bureau",
            title=key,
            landing="",
            verified="2026-08-27",
        ),
        refresh=refresh,
        timeout=timeout,
    )


def record_assembled(key: str, path: Path, *, url: str, vintage: str, notes: str = "") -> None:
    """Record a file assembled from multiple requests (e.g. a paginated ArcGIS query).

    ``fetch`` handles single-URL downloads; a feature service answers in pages, so the fetcher
    assembles them into one file and records the result here. The manifest entry has the same
    shape either way, so an assembled file is exactly as auditable as a plain download: URL
    template, vintage, SHA-256 of the assembled bytes, size, and fetch time.
    """
    manifest = _load_manifest()
    manifest[key] = {
        "url": url,
        "vintage": vintage,
        "sha256": sha256_of(path),
        "bytes": path.stat().st_size,
        "fetched_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "path": path.name,
        "notes": notes or "assembled from paginated requests; sha256 is of the assembled file",
    }
    _save_manifest(manifest)


def unzip(path: Path, *, into: Path | None = None) -> Path:
    """Extract a cached zip archive once, into a sibling directory named after it.

    Returns the directory holding the extracted files. Extraction is skipped if the directory
    already exists, so this is safe to call on every run.
    """
    target = into or path.with_suffix("")
    if target.exists() and any(target.iterdir()):
        return target
    target.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as zf:
            zf.extractall(target)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def manifest_rows() -> list[dict]:
    """Return the manifest as a list of rows, for the run log and the methodology appendix."""
    manifest = _load_manifest()
    return [dict(key=k, **v) for k, v in sorted(manifest.items())]
