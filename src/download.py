from pathlib import Path
import os
import re
import tempfile
import hashlib
from typing import Tuple, Callable, Optional

import requests
from tqdm import tqdm
from logger import get_logger

logger = get_logger(__name__)


def get_server_filename(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        return Path(m.group(1)).name
    return Path(url).name or "episode.zip"


def probe_remote_metadata(url: str) -> Tuple[str, str]:
    """Best-effort lightweight probe to get (name, size) without downloading.

    Returns size as string; may be "unknown".
    """
    logger.debug(f"Probing remote metadata for: {url}")
    r = requests.head(url, allow_redirects=True, timeout=20)
    if r.status_code >= 400 or "Content-Length" not in r.headers:
        logger.debug("HEAD request failed or no Content-Length, trying GET")
        r = requests.get(url, stream=True, timeout=20)
    r.raise_for_status()
    name = get_server_filename(r, url)
    size = r.headers.get("Content-Length", "unknown")
    logger.info(f"Remote file: {name}, size: {size} bytes")
    return name, size


def download_zip(url: str, on_progress: Optional[Callable[[int, int], None]] = None) -> tuple[Path, str, str]:
    # Generic HTTP download (works for CDN/GitHub/etc.)
    # Has to be a direct download link, not a page that serves the file.
    logger.info(f"Starting download from: {url}")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        server_name = get_server_filename(r, url)
        total = int(r.headers.get("Content-Length", 0))
        logger.info(f"Downloading {server_name}, size: {total} bytes")
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="dl_", suffix=".zip")
        os.close(tmp_fd)
        logger.debug(f"Temporary file: {tmp_path}")
        h = hashlib.sha256()
        downloaded = 0
        with open(tmp_path, "wb") as f, tqdm(
            total=total if total > 0 else None,
            unit="B", unit_scale=True, desc="Downloading"
        ) as bar:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                if total:
                    bar.update(len(chunk))
                downloaded += len(chunk)
                if on_progress:
                    try:
                        on_progress(downloaded, total)
                    except Exception as e:
                        logger.warning(f"Progress callback failed: {e}")
    
    sha_hash = h.hexdigest()
    logger.info(f"Download complete. SHA256: {sha_hash}")
    return Path(tmp_path), server_name, sha_hash