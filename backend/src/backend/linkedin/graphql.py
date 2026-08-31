import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.linkedin.client import LinkedInClient

logger = logging.getLogger(__name__)

CONTACT_SCREEN_ID = (
    "com.linkedin.sdui.flagshipnav.profile.ProfileContactDetailsOverlay"
)
SKILLS_SCREEN_ID = "com.linkedin.sdui.flagshipnav.profile.ProfileSkillDetails"
PAGINATION_PATH = "/flagship-web/rsc-action/actions/pagination"
MAX_SECTION_PAGES = 20

SECTION_CONFIG = {
    "skills": (
        "com.linkedin.sdui.pagers.profile.details.skills",
        "com.linkedin.sdui.flagshipnav.profile.ProfileSkillDetails",
        "d_flagship3_profile_view_base_skills_details",
    ),
    "certifications": (
        "com.linkedin.sdui.pagers.profile.details.certifications",
        "com.linkedin.sdui.flagshipnav.profile.ProfileCertificationDetails",
        "d_flagship3_profile_view_base_certifications_details",
    ),
    "languages": (
        "com.linkedin.sdui.pagers.profile.details.languages",
        "com.linkedin.sdui.flagshipnav.profile.ProfileLanguageDetails",
        "d_flagship3_profile_view_base_languages_details",
    ),
    "testscores": (
        "com.linkedin.sdui.pagers.profile.details.testscores",
        "com.linkedin.sdui.flagshipnav.profile.ProfileTestScoreDetails",
        "d_flagship3_profile_view_base_test_score_details",
    ),
}


@dataclass
class ProfileEnrichments:
    contact: str | None = None
    skills: str | None = None
    skill_pages: list[str] = field(default_factory=list)
    certification_pages: list[str] = field(default_factory=list)
    language_pages: list[str] = field(default_factory=list)
    test_score_pages: list[str] = field(default_factory=list)


async def fetch_decorated_profile(
    client: LinkedInClient,
    vanity: str,
    *,
    referer: str,
) -> dict:
    """Fetch the decorated profile payload rather than the GraphQL identity stub."""
    return await client.get_profile(vanity, referer=referer)


def _requested_arguments(payload: dict[str, Any], screen_id: str) -> dict[str, Any]:
    return {
        "$type": "proto.sdui.actions.requests.RequestedArguments",
        "requestedStateKeys": [],
        "payload": payload,
        "requestMetadata": {
            "$type": "proto.sdui.common.RequestMetadata",
        },
        "states": [],
        "screenId": screen_id,
        "knownTemplateIds": [],
    }


def _count_rsc_items(response_text: str) -> int:
    count = 0

    def walk(value: Any) -> None:
        nonlocal count
        if isinstance(value, list):
            if len(value) >= 2 and isinstance(value[0], str):
                try:
                    metadata = json.loads(value[0])
                except (json.JSONDecodeError, TypeError):
                    metadata = None
                if isinstance(metadata, dict) and "threadlineDecoration" in metadata:
                    count += 1
            for nested in value:
                walk(nested)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)

    for line in response_text.splitlines():
        _, separator, payload = line.partition(":")
        if not separator or not payload.lstrip().startswith(("[", "{")):
            continue
        try:
            walk(json.loads(payload))
        except json.JSONDecodeError:
            sanitized = re.sub(
                r'\\(?!["\\/bfnrtu])',
                "",
                payload,
            )
            try:
                walk(json.loads(sanitized))
            except json.JSONDecodeError:
                continue

    return count


async def _fetch_contact(
    client: LinkedInClient,
    *,
    vanity: str,
    given_name: str | None,
    family_name: str | None,
    referer: str,
) -> str:
    payload = {
        "vanityName": vanity,
        "givenName": given_name or "",
        "familyName": family_name or "",
        "isVanityNameResolved": True,
    }
    return await client.post_sdui(
        "/flagship-web/rsc-action/actions/navigation",
        params={
            "screenId": CONTACT_SCREEN_ID,
            "sduiid": CONTACT_SCREEN_ID,
        },
        body={
            "clientArguments": _requested_arguments(payload, CONTACT_SCREEN_ID),
            "isModal": True,
        },
        referer=f"{referer}overlay/contact-info/",
        page_key="d_flagship3_profile_view_base",
    )


async def _fetch_skills(
    client: LinkedInClient,
    *,
    vanity: str,
    referer: str,
) -> str:
    path = f"/flagship-web/in/{vanity}/details/skills/"
    return await client.post_sdui(
        path,
        body={
            "$type": "proto.sdui.actions.core.NavigateToScreen",
            "screenId": SKILLS_SCREEN_ID,
            "pageKey": "profile_view_base_skills_details",
            "presentationStyle": "PresentationStyle_FULL_PAGE",
            "presentation": {
                "$case": "fullPage",
                "fullPage": {
                    "$type": (
                        "proto.sdui.actions.core.presentation."
                        "FullPagePresentation"
                    )
                },
            },
            "title": "",
            "url": f"/in/{vanity}/details/skills/",
            "inheritActor": False,
            "replaceCurrentScreen": False,
            "requestedArguments": _requested_arguments(
                {"vanityName": vanity},
                "",
            ),
        },
        referer=referer,
        page_key="d_flagship3_profile_view_base",
    )


def _pagination_body(
    *,
    pager_id: str,
    screen_id: str,
    vanity: str,
    profile_id: str,
    start: int,
    count: int,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "vanityName": vanity,
        "profileId": profile_id,
        "start": start,
        "count": count,
    }
    payload.update(extra_payload or {})
    pagination_request = {
        "$type": "proto.sdui.actions.requests.PaginationRequest",
        "pagerId": pager_id,
        "trigger": {
            "$case": "itemDistanceTrigger",
            "itemDistanceTrigger": {
                "$type": (
                    "proto.sdui.actions.requests.ItemDistanceTrigger"
                ),
                "preloadDistance": 3,
                "preloadLength": 250,
            },
        },
        "retryCount": 2,
        "requestedArguments": _requested_arguments(payload, ""),
    }
    return {
        "pagerId": pager_id,
        "clientArguments": _requested_arguments(payload, screen_id),
        "paginationRequest": pagination_request,
    }


async def _fetch_paginated_section(
    client: LinkedInClient,
    *,
    section: str,
    vanity: str,
    profile_id: str,
    referer: str,
    count: int = 10,
    extra_payload: dict[str, Any] | None = None,
) -> list[str]:
    pager_id, screen_id, page_key = SECTION_CONFIG[section]
    pages: list[str] = []

    for page_number in range(MAX_SECTION_PAGES):
        start = page_number * count
        response_text = await client.post_sdui(
            PAGINATION_PATH,
            params={"sduiid": pager_id},
            body=_pagination_body(
                pager_id=pager_id,
                screen_id=screen_id,
                vanity=vanity,
                profile_id=profile_id,
                start=start,
                count=count,
                extra_payload=extra_payload,
            ),
            referer=referer,
            page_key=page_key,
        )
        pages.append(response_text)
        item_count = _count_rsc_items(response_text)
        if item_count < count:
            break

    return pages


async def _optional(coroutine, *, section: str, default):
    try:
        return await coroutine
    except Exception as exc:
        logger.warning("LinkedIn %s enrichment failed: %s", section, exc)
        return default


async def fetch_profile_enrichments(
    client: LinkedInClient,
    *,
    vanity: str,
    profile_id: str,
    referer: str,
    given_name: str | None = None,
    family_name: str | None = None,
) -> ProfileEnrichments:
    (
        contact,
        skills,
        skill_pages,
        certifications,
        languages,
        test_scores,
    ) = await asyncio.gather(
        _optional(
            _fetch_contact(
                client,
                vanity=vanity,
                given_name=given_name,
                family_name=family_name,
                referer=referer,
            ),
            section="contact",
            default=None,
        ),
        _optional(
            _fetch_skills(client, vanity=vanity, referer=referer),
            section="skills",
            default=None,
        ),
        _optional(
            _fetch_paginated_section(
                client,
                section="skills",
                vanity=vanity,
                profile_id=profile_id,
                referer=referer,
                extra_payload={"filter": "ProfileSkillCategory_ALL"},
            ),
            section="skills pagination",
            default=[],
        ),
        _optional(
            _fetch_paginated_section(
                client,
                section="certifications",
                vanity=vanity,
                profile_id=profile_id,
                referer=referer,
            ),
            section="certifications",
            default=[],
        ),
        _optional(
            _fetch_paginated_section(
                client,
                section="languages",
                vanity=vanity,
                profile_id=profile_id,
                referer=referer,
            ),
            section="languages",
            default=[],
        ),
        _optional(
            _fetch_paginated_section(
                client,
                section="testscores",
                vanity=vanity,
                profile_id=profile_id,
                referer=referer,
            ),
            section="test scores",
            default=[],
        ),
    )
    return ProfileEnrichments(
        contact=contact,
        skills=skills,
        skill_pages=skill_pages,
        certification_pages=certifications,
        language_pages=languages,
        test_score_pages=test_scores,
    )
