from pathlib import Path
import os
import re
import tempfile
import hashlib
from typing import Tuple

import requests
from tqdm import tqdm


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
    r = requests.head(url, allow_redirects=True, timeout=20)
    if r.status_code >= 400 or "Content-Length" not in r.headers:
        r = requests.get(url, stream=True, timeout=20)
    r.raise_for_status()
    name = get_server_filename(r, url)
    size = r.headers.get("Content-Length", "unknown")
    return name, size


def download_zip(url: str) -> tuple[Path, str, str]:
    # Generic HTTP download (works for CDN/GitHub/etc.)
    # Has to be a direct download link, not a page that serves the file.
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        server_name = get_server_filename(r, url)
        total = int(r.headers.get("Content-Length", 0))
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="dl_", suffix=".zip")
        os.close(tmp_fd)
        h = hashlib.sha256()
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
    return Path(tmp_path), server_name, h.hexdigest()