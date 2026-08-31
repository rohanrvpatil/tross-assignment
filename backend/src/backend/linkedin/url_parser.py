import re
from urllib.parse import urlparse

LINKEDIN_PROFILE_PATH_RE = re.compile(r"^/in/([A-Za-z0-9\-_%]+)/?$")


class InvalidLinkedInUrlError(ValueError):
    """Raised when the provided URL is not a valid LinkedIn profile URL."""


def parse_linkedin_profile_url(url: str) -> str:
    """Extract the vanity slug from a LinkedIn profile URL."""
    parsed = urlparse(url.strip())

    if parsed.netloc not in {"linkedin.com", "www.linkedin.com"}:
        raise InvalidLinkedInUrlError("URL must be a linkedin.com profile link")

    match = LINKEDIN_PROFILE_PATH_RE.match(parsed.path)
    if not match:
        raise InvalidLinkedInUrlError("URL must point to a /in/<vanity> profile path")

    vanity = match.group(1).rstrip("/")
    if not vanity:
        raise InvalidLinkedInUrlError("Profile vanity slug is empty")

    return vanity


def build_profile_url(vanity: str) -> str:
    return f"https://www.linkedin.com/in/{vanity}/"
