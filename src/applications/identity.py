"""Stable portal identities, including old Ashby URL-based records."""
from urllib.parse import urlparse

def canonical_id(portal: str, value: str) -> str:
    if portal == 'ashby':
        url = urlparse(value)
        parts = url.path.strip('/').split('/')
        if url.hostname == 'jobs.ashbyhq.com' and len(parts) >= 2:
            return parts[1]
    return value
