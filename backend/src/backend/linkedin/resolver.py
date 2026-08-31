import re

from backend.linkedin.client import LinkedInClient
from backend.linkedin.url_parser import build_profile_url

PROFILE_URN_RE = re.compile(r"urn:li:fsd_profile:(ACo[A-Za-z0-9_-]+)")
PUBLIC_IDENTIFIER_RE = re.compile(
    r'"publicIdentifier"\s*:\s*"(?P<vanity>[^"]+)".*?'
    r'"entityUrn"\s*:\s*"urn:li:fsd_profile:(?P<member_id>ACo[A-Za-z0-9_-]+)"',
    re.DOTALL,
)


class ProfileNotFoundError(Exception):
    """Raised when a vanity slug cannot be resolved to a member identity."""


async def resolve_member_identity(client: LinkedInClient, vanity: str) -> str:
    """Resolve a vanity slug to a LinkedIn memberIdentity via profile page HTML."""
    profile_url = build_profile_url(vanity)
    response = await client.get(profile_url, referer=profile_url)

    if response.status_code == 404:
        raise ProfileNotFoundError(f"Profile not found for vanity slug: {vanity}")

    if response.status_code != 200:
        raise ProfileNotFoundError(
            f"Unable to load profile page for vanity slug: {vanity} "
            f"(status {response.status_code})"
        )

    html = response.text

    for match in PUBLIC_IDENTIFIER_RE.finditer(html):
        if match.group("vanity") == vanity:
            return match.group("member_id")

    matches = PROFILE_URN_RE.findall(html)
    if not matches:
        raise ProfileNotFoundError(
            f"Could not extract member identity for vanity slug: {vanity}"
        )

    return matches[0]
