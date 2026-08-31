import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
PROFILE_DECORATION_ID = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"
)
DEFAULT_X_LI_TRACK = json.dumps(
    {
        "clientVersion": "1.13.42372",
        "mpVersion": "1.13.42372",
        "osName": "web",
        "timezoneOffset": -330,
        "deviceFormFactor": "DESKTOP",
        "mpName": "voyager-web",
        "displayDensity": 1,
        "displayWidth": 1920,
        "displayHeight": 1080,
    },
    separators=(",", ":"),
)
SDUI_APPLICATION_VERSION = "0.2.7003"


class LinkedInError(Exception):
    """Base error for LinkedIn API interactions."""


class LinkedInSessionExpiredError(LinkedInError):
    """Raised when LinkedIn redirects to login or authwall."""


class LinkedInRateLimitError(LinkedInError):
    """Raised when LinkedIn rate-limits requests."""


class LinkedInBadResponseError(LinkedInError):
    """Raised when LinkedIn returns an unexpected response."""


class LinkedInProfileNotFoundError(LinkedInError):
    """Raised when LinkedIn cannot find the requested vanity profile."""


def _normalize_jsessionid(value: str) -> str:
    jsessionid = value.strip().strip('"')
    if jsessionid.startswith("ajax:"):
        return jsessionid
    return f"ajax:{jsessionid}"


class LinkedInClient:
    VOYAGER_BASE = "https://www.linkedin.com/voyager/api"

    def _cookie_header(self) -> str:
        jsessionid = _normalize_jsessionid(os.environ["LINKEDIN_JSESSIONID"])
        return (
            f'li_at={os.environ["LINKEDIN_LI_AT"]}; '
            f'JSESSIONID="{jsessionid}"'
        )

    def _headers(self, referer: str | None = None) -> dict[str, str]:
        jsessionid = _normalize_jsessionid(os.environ["LINKEDIN_JSESSIONID"])
        return {
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "accept-language": "en-US,en;q=0.9",
            "cookie": self._cookie_header(),
            "csrf-token": jsessionid,
            "user-agent": os.environ.get("LINKEDIN_USER_AGENT", DEFAULT_USER_AGENT),
            "x-li-lang": "en_US",
            "x-li-track": os.environ.get("LINKEDIN_X_LI_TRACK", DEFAULT_X_LI_TRACK),
            "x-restli-protocol-version": "2.0.0",
            "referer": referer or "https://www.linkedin.com/feed/",
        }

    def _sdui_headers(
        self,
        *,
        referer: str,
        page_key: str,
    ) -> dict[str, str]:
        headers = self._headers(referer=referer)
        headers.pop("x-restli-protocol-version", None)
        headers.update(
            {
                "accept": "*/*",
                "content-type": "application/json",
                "origin": "https://www.linkedin.com",
                "x-li-anchor-page-key": page_key,
                "x-li-application-version": SDUI_APPLICATION_VERSION,
                "x-li-rsc-stream": "true",
            }
        )
        return headers

    def _check_response(self, response) -> None:
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "")
            if (
                "login" in location
                or "authwall" in location
                or "checkpoint" in location
                or location == str(response.request.url)
            ):
                raise LinkedInSessionExpiredError(
                    "LinkedIn session expired. Refresh li_at and JSESSIONID cookies."
                )
            raise LinkedInBadResponseError(
                f"Unexpected redirect from LinkedIn: {location or response.status_code}"
            )

        if response.status_code in {401, 403}:
            raise LinkedInSessionExpiredError(
                f"LinkedIn rejected the request ({response.status_code}). "
                "Refresh li_at and JSESSIONID cookies."
            )

        if response.status_code == 429:
            raise LinkedInRateLimitError("LinkedIn rate limit exceeded")

        if response.status_code >= 500:
            raise LinkedInBadResponseError(
                f"LinkedIn server error: {response.status_code}"
            )

    async def get(self, url: str, *, referer: str | None = None):
        import httpx

        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            response = await client.get(url, headers=self._headers(referer=referer))
            self._check_response(response)
            return response

    async def get_profile(self, vanity: str, *, referer: str) -> dict:
        import httpx

        params = {
            "q": "memberIdentity",
            "memberIdentity": vanity,
            "decorationId": PROFILE_DECORATION_ID,
        }
        url = f"{self.VOYAGER_BASE}/identity/dash/profiles"

        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            response = await client.get(
                url,
                params=params,
                headers=self._headers(referer=referer),
            )
            self._check_response(response)

            if response.status_code == 404:
                raise LinkedInProfileNotFoundError(
                    f"LinkedIn profile not found for vanity slug: {vanity}"
                )

            if response.status_code != 200:
                raise LinkedInBadResponseError(
                    "LinkedIn decorated profile request failed with status "
                    f"{response.status_code}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise LinkedInBadResponseError(
                    "LinkedIn decorated profile response was not valid JSON"
                ) from exc

    async def post_sdui(
        self,
        path: str,
        *,
        body: dict,
        referer: str,
        page_key: str,
        params: dict[str, str] | None = None,
    ) -> str:
        import httpx

        url = f"https://www.linkedin.com{path}"
        async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
            response = await client.post(
                url,
                params=params,
                json=body,
                headers=self._sdui_headers(
                    referer=referer,
                    page_key=page_key,
                ),
            )
            self._check_response(response)

            if response.status_code != 200:
                raise LinkedInBadResponseError(
                    f"LinkedIn SDUI request failed with status {response.status_code}"
                )

            return response.text
