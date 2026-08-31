from fastapi import APIRouter, HTTPException, Query

from backend.linkedin.client import (
    LinkedInBadResponseError,
    LinkedInClient,
    LinkedInProfileNotFoundError,
    LinkedInRateLimitError,
    LinkedInSessionExpiredError,
)
from backend.linkedin.graphql import (
    fetch_decorated_profile,
    fetch_profile_enrichments,
)
from backend.linkedin.parser import (
    ProfilePayloadError,
    merge_profile_enrichments,
    parse_profile_response,
)
from backend.linkedin.url_parser import (
    InvalidLinkedInUrlError,
    build_profile_url,
    parse_linkedin_profile_url,
)
from backend.models.profile import ProfileResponse

router = APIRouter(tags=["profile"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    url: str = Query(..., description="LinkedIn profile URL"),
) -> ProfileResponse:
    try:
        vanity = parse_linkedin_profile_url(url)
    except InvalidLinkedInUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    client = LinkedInClient()
    profile_url = build_profile_url(vanity)

    try:
        profile_payload = await fetch_decorated_profile(
            client,
            vanity,
            referer=profile_url,
        )
    except LinkedInSessionExpiredError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except LinkedInProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LinkedInRateLimitError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LinkedInBadResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        profile = parse_profile_response(
            vanity=vanity,
            profile_payload=profile_payload,
        )
    except ProfilePayloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    name_parts = (profile.name or "").split(maxsplit=1)
    enrichments = await fetch_profile_enrichments(
        client,
        vanity=vanity,
        profile_id=profile.member_identity,
        referer=profile_url,
        given_name=name_parts[0] if name_parts else None,
        family_name=name_parts[1] if len(name_parts) > 1 else None,
    )
    return merge_profile_enrichments(
        profile,
        contact_response=enrichments.contact,
        skills_response=enrichments.skills,
        skill_pages=enrichments.skill_pages,
        certification_pages=enrichments.certification_pages,
        language_pages=enrichments.language_pages,
        test_score_pages=enrichments.test_score_pages,
    )
