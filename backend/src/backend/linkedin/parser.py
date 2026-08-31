import logging
import json
import re
from typing import Any
from urllib.parse import urljoin

from backend.linkedin.url_parser import build_profile_url
from backend.models.profile import (
    ContactInfo,
    Education,
    Experience,
    HonorAward,
    Language,
    LicenseCertification,
    ProfileResponse,
    Project,
    Skill,
    SkillAssociation,
    TestScore,
    VolunteerExperience,
)

logger = logging.getLogger(__name__)

PROFILE_URN_RE = re.compile(r"urn:li:fsd_profile:(?P<member_id>[^,?]+)")
MONTH_NAMES = (
    "",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class ProfilePayloadError(ValueError):
    """Raised when LinkedIn returns a profile stub without decorated fields."""


DATE_RANGE_RE = re.compile(
    r"^(?P<start>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})"
    r"(?:\s*-\s*(?P<end>(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})))?$"
)


def _extract_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, dict):
        for key in (
            "text",
            "accessibilityText",
            "name",
            "localizedName",
            "defaultLocalizedName",
        ):
            if key in value:
                return _extract_text(value[key])
        string_values = [
            item.strip()
            for item in value.values()
            if isinstance(item, str) and item.strip()
        ]
        if string_values:
            return string_values[0]
        if "attributesV2" in value and isinstance(value["attributesV2"], list):
            parts = [_extract_text(item) for item in value["attributesV2"]]
            joined = "".join(part for part in parts if part)
            return joined or None
        return None
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        joined = " ".join(part for part in parts if part)
        return joined or None
    return str(value) if isinstance(value, (int, float)) else None


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_dicts(nested)


def _collect_payload_entities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    seen: set[int] = set()

    for item in payload.get("included", []):
        if isinstance(item, dict) and id(item) not in seen:
            seen.add(id(item))
            entities.append(item)

    for item in _walk_dicts(payload):
        if ("entityUrn" in item or "$type" in item) and id(item) not in seen:
            seen.add(id(item))
            entities.append(item)

    return entities


def _entity_map(included: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    entities: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(included):
        urn = item.get("entityUrn")
        key = urn or f"__embedded_entity_{index}"
        existing = entities.get(key)
        if existing is None or len(item) > len(existing):
            entities[key] = item
    return entities


def _resolve_ref(value: Any, entities: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str) and value in entities:
        return entities[value]
    return value


def _resolve_elements(value: Any, entities: dict[str, dict[str, Any]]) -> list[Any]:
    if not isinstance(value, dict):
        return []
    elements = value.get("*elements") or value.get("elements") or []
    return [_resolve_ref(element, entities) for element in elements]


def _resolve_collection(
    value: Any, entities: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    if isinstance(value, list):
        resolved = [_resolve_ref(item, entities) for item in value]
    else:
        collection = _resolve_ref(value, entities)
        resolved = _resolve_elements(collection, entities)
    return [item for item in resolved if isinstance(item, dict)]


def _find_profile_entity(
    entities: list[dict[str, Any]], vanity: str
) -> dict[str, Any] | None:
    candidates = [
        item
        for item in entities
        if item.get("$type", "").endswith(".Profile")
        or any(key in item for key in ("firstName", "lastName", "headline"))
    ]
    if not candidates:
        return None

    detail_keys = {
        "firstName",
        "lastName",
        "headline",
        "summary",
        "profilePicture",
        "geoLocationName",
    }

    def candidate_score(item: dict[str, Any]) -> int:
        score = sum(key in item for key in detail_keys)
        if item.get("publicIdentifier", "").lower() == vanity.lower():
            score += len(detail_keys)
        return score

    return max(candidates, key=candidate_score)


def _member_identity(profile: dict[str, Any]) -> str:
    urn = profile.get("entityUrn") or profile.get("profileUrn") or ""
    match = PROFILE_URN_RE.search(urn)
    if not match:
        raise ProfilePayloadError("LinkedIn profile response did not include a profile URN")
    return match.group("member_id")


def _format_partial_date(value: Any) -> str | None:
    if not isinstance(value, dict):
        return _extract_text(value)
    year = value.get("year")
    month = value.get("month")
    if not year:
        return None
    if isinstance(month, int) and 0 < month < len(MONTH_NAMES):
        return f"{MONTH_NAMES[month]} {year}"
    return str(year)


def _parse_structured_date_range(
    item: dict[str, Any], *, ongoing_when_missing_end: bool = False
) -> tuple[str | None, str | None]:
    date_range = item.get("dateRange") or item.get("timePeriod") or {}
    if not isinstance(date_range, dict):
        return None, None
    start = date_range.get("start") or date_range.get("startDate")
    end = date_range.get("end") or date_range.get("endDate")
    start_date = _format_partial_date(start)
    end_date = _format_partial_date(end)
    if start_date and not end_date and ongoing_when_missing_end:
        end_date = "Present"
    return start_date, end_date


def _parse_date_range(caption: str | None) -> tuple[str | None, str | None]:
    if not caption:
        return None, None
    match = DATE_RANGE_RE.match(caption.strip())
    if not match:
        return caption, None
    return match.group("start"), match.group("end")


def _ordered_work_entities(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str | int] = set()

    def append_position(item: dict[str, Any]) -> None:
        if item.get("$type", "").rsplit(".", 1)[-1] != "Position":
            return
        identity = item.get("entityUrn") or id(item)
        if identity not in seen:
            seen.add(identity)
            ordered.append(item)

    groups = _resolve_collection(profile.get("*profilePositionGroups"), entities)
    for group in groups:
        positions = _resolve_collection(
            group.get("*profilePositionInPositionGroup"),
            entities,
        )
        for position in positions:
            append_position(position)

    # Append any positions omitted from LinkedIn's ordering collections so the
    # response remains complete if the decoration shape changes.
    for item in entities.values():
        append_position(item)

    return ordered


def _parse_experience_entities(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[Experience]:
    experiences: list[Experience] = []

    for item in _ordered_work_entities(profile, entities):
        title = _extract_text(item.get("title")) or _extract_text(
            item.get("multiLocaleTitle")
        )
        company = _extract_text(item.get("companyName")) or _extract_text(
            item.get("multiLocaleCompanyName")
        )
        if not company:
            company_entity = _resolve_ref(
                item.get("*company") or item.get("company"), entities
            )
            company = _extract_text(company_entity)

        employment_type_entity = _resolve_ref(
            item.get("*employmentType") or item.get("employmentTypeUrn"),
            entities,
        )
        employment_type = _extract_text(employment_type_entity)

        location = (
            _extract_text(item.get("geoLocationName"))
            or _extract_text(item.get("multiLocaleGeoLocationName"))
            or _extract_text(item.get("locationName"))
            or _extract_text(item.get("multiLocaleLocationName"))
        )
        if not location:
            geo_entity = _resolve_ref(
                item.get("*geo") or item.get("geoUrn"),
                entities,
            )
            location = _extract_text(geo_entity)

        start_date, end_date = _parse_structured_date_range(
            item, ongoing_when_missing_end=True
        )
        caption = _extract_text(item.get("caption"))
        if not start_date and caption:
            start_date, end_date = _parse_date_range(caption)

        description = _extract_text(item.get("description")) or _extract_text(
            item.get("multiLocaleDescription")
        )
        if title or company:
            experiences.append(
                Experience(
                    title=title,
                    company=company,
                    employment_type=employment_type,
                    location=location,
                    start_date=start_date,
                    end_date=end_date,
                    description=description,
                )
            )

    return experiences


def _parse_volunteer_entities(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[VolunteerExperience]:
    ordered = _resolve_collection(
        profile.get("*profileVolunteerExperiences"),
        entities,
    )
    seen: set[str | int] = set()
    volunteers: list[VolunteerExperience] = []

    candidates = ordered + list(entities.values())
    for item in candidates:
        if item.get("$type", "").rsplit(".", 1)[-1] != "VolunteerExperience":
            continue

        identity = item.get("entityUrn") or id(item)
        if identity in seen:
            continue
        seen.add(identity)

        role = _extract_text(item.get("role")) or _extract_text(
            item.get("multiLocaleRole")
        )
        organization = _extract_text(item.get("companyName")) or _extract_text(
            item.get("multiLocaleCompanyName")
        )
        if not organization:
            company_entity = _resolve_ref(
                item.get("*company") or item.get("companyUrn"),
                entities,
            )
            organization = _extract_text(company_entity)

        cause = _extract_text(item.get("cause"))
        if cause:
            cause = cause.replace("_", " ").title()

        start_date, end_date = _parse_structured_date_range(
            item, ongoing_when_missing_end=True
        )
        description = _extract_text(item.get("description")) or _extract_text(
            item.get("multiLocaleDescription")
        )

        if role or organization:
            volunteers.append(
                VolunteerExperience(
                    role=role,
                    organization=organization,
                    cause=cause,
                    start_date=start_date,
                    end_date=end_date,
                    description=description,
                )
            )

    return volunteers


def _parse_education_entities(
    entities: dict[str, dict[str, Any]],
) -> list[Education]:
    education_items: list[Education] = []
    seen: set[str] = set()

    for item in entities.values():
        item_type = item.get("$type", "")
        type_name = item_type.rsplit(".", 1)[-1]
        if "Education" not in type_name:
            continue

        urn = item.get("entityUrn")
        if urn and urn in seen:
            continue
        if urn:
            seen.add(urn)

        school = _extract_text(item.get("schoolName")) or _extract_text(
            item.get("multiLocaleSchoolName")
        )
        if not school:
            school = _extract_text(
                _resolve_ref(item.get("*school") or item.get("school"), entities)
            )

        degree = (
            _extract_text(item.get("degreeName"))
            or _extract_text(item.get("multiLocaleDegreeName"))
            or _extract_text(item.get("fieldOfStudy"))
            or _extract_text(item.get("multiLocaleFieldOfStudy"))
        )

        start_date, end_date = _parse_structured_date_range(item)
        caption = _extract_text(item.get("caption"))
        if not start_date and caption:
            start_date, end_date = _parse_date_range(caption)

        if school or degree:
            education_items.append(
                Education(
                    school=school,
                    degree=degree,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

    return education_items


def _type_name(item: dict[str, Any]) -> str:
    return item.get("$type", "").rsplit(".", 1)[-1]


def _ordered_section_entities(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
    *,
    collection_keys: tuple[str, ...],
    type_matches,
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str | int] = set()

    def append(item: dict[str, Any]) -> None:
        if not type_matches(_type_name(item)):
            return
        identity = item.get("entityUrn") or id(item)
        if identity not in seen:
            seen.add(identity)
            ordered.append(item)

    for key in collection_keys:
        for item in _resolve_collection(profile.get(key), entities):
            append(item)
    for item in entities.values():
        append(item)
    return ordered


def _position_associations(
    skill: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[SkillAssociation]:
    candidates: list[dict[str, Any]] = []
    skill_urn = skill.get("entityUrn")
    for key in (
        "*profileSkillAssociations",
        "*skillAssociations",
        "associations",
        "profileSkillAssociations",
    ):
        candidates.extend(_resolve_collection(skill.get(key), entities))

    if skill_urn:
        for item in entities.values():
            if "SkillAssociation" in _type_name(item) and skill_urn in str(item):
                candidates.append(item)

    positions: list[dict[str, Any]] = []
    for candidate in candidates:
        for value in _walk_dicts(candidate):
            if _type_name(value) == "Position":
                positions.append(value)
            for nested in value.values():
                resolved = _resolve_ref(nested, entities)
                if isinstance(resolved, dict) and _type_name(resolved) == "Position":
                    positions.append(resolved)

    associations: list[SkillAssociation] = []
    seen: set[tuple[str | None, str | None]] = set()
    for position in positions:
        title = _extract_text(position.get("title")) or _extract_text(
            position.get("multiLocaleTitle")
        )
        company = _extract_text(position.get("companyName")) or _extract_text(
            position.get("multiLocaleCompanyName")
        )
        if not company:
            company = _extract_text(
                _resolve_ref(
                    position.get("*company") or position.get("company"),
                    entities,
                )
            )
        identity = (title, company)
        if identity != (None, None) and identity not in seen:
            seen.add(identity)
            associations.append(SkillAssociation(title=title, company=company))
    return associations


def _parse_skill_entities(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[Skill]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileSkills", "*skills"),
        type_matches=lambda name: name in {"Skill", "ProfileSkill"},
    )
    skills: list[Skill] = []
    seen: set[str] = set()

    for item in items:
        name = _extract_text(item.get("name")) or _extract_text(
            item.get("multiLocaleName")
        )
        normalized = name.casefold() if name else ""
        if not name or normalized in seen:
            continue
        seen.add(normalized)
        category = _extract_text(item.get("category")) or _extract_text(
            item.get("localizedCategory")
        )
        skills.append(
            Skill(
                name=name,
                category=category,
                associated_experiences=_position_associations(item, entities),
            )
        )
    return skills


def _parse_projects(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[Project]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileProjects", "*projects"),
        type_matches=lambda name: name in {"Project", "ProfileProject"},
    )
    projects: list[Project] = []
    for item in items:
        start_date, end_date = _parse_structured_date_range(item)
        title = _extract_text(item.get("title")) or _extract_text(item.get("name"))
        description = _extract_text(item.get("description"))
        url = _extract_text(
            item.get("url")
            or item.get("projectUrl")
            or item.get("externalUrl")
        )
        associated_with = _extract_text(
            item.get("associatedWith")
            or item.get("occupation")
            or item.get("companyName")
        )
        if title or description:
            projects.append(
                Project(
                    title=title,
                    description=description,
                    url=url,
                    start_date=start_date,
                    end_date=end_date,
                    associated_with=associated_with,
                )
            )
    return projects


def _parse_honors(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[HonorAward]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileHonors", "*honors"),
        type_matches=lambda name: "Honor" in name or name.endswith("Award"),
    )
    honors: list[HonorAward] = []
    for item in items:
        title = _extract_text(item.get("title")) or _extract_text(item.get("name"))
        issuer = _extract_text(
            item.get("issuer") or item.get("issuerName") or item.get("occupation")
        )
        issue_date = _format_partial_date(
            item.get("issuedOn")
            or item.get("issueDate")
            or item.get("date")
        )
        description = _extract_text(item.get("description"))
        if title or issuer:
            honors.append(
                HonorAward(
                    title=title,
                    issuer=issuer,
                    issue_date=issue_date,
                    description=description,
                )
            )
    return honors


def _split_score_summary(
    summary: str | None,
) -> tuple[str | None, str | None, str | None]:
    if not summary:
        return None, None, None
    value = re.sub(r"^\s*Score:\s*", "", summary, flags=re.IGNORECASE)
    score_part, separator, date = value.partition("·")
    score_part = score_part.strip()
    date = date.strip() if separator else None
    score, slash, maximum = score_part.partition("/")
    return (
        score.strip() or None,
        maximum.strip() if slash and maximum.strip() else None,
        date or None,
    )


def _parse_test_scores(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[TestScore]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileTestScores", "*testScores"),
        type_matches=lambda name: "TestScore" in name,
    )
    scores: list[TestScore] = []
    for item in items:
        name = _extract_text(item.get("name")) or _extract_text(item.get("title"))
        raw_score = _extract_text(item.get("score"))
        date = _format_partial_date(item.get("date") or item.get("testDate"))
        score_summary = raw_score
        if raw_score and not raw_score.lower().startswith("score:"):
            score_summary = f"Score: {raw_score}"
            if date:
                score_summary += f" · {date}"
        score, maximum, parsed_date = _split_score_summary(score_summary)
        if name or raw_score:
            scores.append(
                TestScore(
                    name=name,
                    score_summary=score_summary,
                    score=score,
                    max_score=maximum,
                    date=parsed_date or date,
                    description=_extract_text(item.get("description")),
                )
            )
    return scores


def _parse_languages(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[Language]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileLanguages", "*languages"),
        type_matches=lambda name: name in {"Language", "ProfileLanguage"},
    )
    languages: list[Language] = []
    for item in items:
        name = _extract_text(item.get("name")) or _extract_text(
            item.get("language")
        )
        proficiency = _extract_text(
            item.get("proficiency")
            or item.get("proficiencyName")
            or item.get("localizedProficiency")
        )
        if name:
            languages.append(Language(name=name, proficiency=proficiency))
    return languages


def _parse_certifications(
    profile: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> list[LicenseCertification]:
    items = _ordered_section_entities(
        profile,
        entities,
        collection_keys=("*profileCertifications", "*certifications"),
        type_matches=lambda name: "Certification" in name,
    )
    certifications: list[LicenseCertification] = []
    for item in items:
        start_date, end_date = _parse_structured_date_range(item)
        name = _extract_text(item.get("name")) or _extract_text(item.get("title"))
        issuer = _extract_text(
            item.get("authority")
            or item.get("issuer")
            or item.get("companyName")
        )
        if not issuer:
            issuer = _extract_text(
                _resolve_ref(
                    item.get("*company") or item.get("*school"),
                    entities,
                )
            )
        if name or issuer:
            certifications.append(
                LicenseCertification(
                    name=name,
                    issuer=issuer,
                    issue_date=start_date,
                    expiration_date=end_date,
                    credential_id=_extract_text(
                        item.get("licenseNumber")
                        or item.get("credentialId")
                    ),
                    credential_url=_extract_text(
                        item.get("url") or item.get("credentialUrl")
                    ),
                )
            )
    return certifications


def _parse_location(profile: dict[str, Any], entities: dict[str, dict[str, Any]]) -> str | None:
    direct_location = (
        _extract_text(profile.get("geoLocationName"))
        or _extract_text(profile.get("locationName"))
    )
    if direct_location:
        return direct_location

    geo = profile.get("geoLocation") or profile.get("location")
    if isinstance(geo, dict):
        nested_geo = geo.get("geo") or geo.get("*geo") or geo
        nested_geo = _resolve_ref(nested_geo, entities)
        return _extract_text(nested_geo)
    if isinstance(geo, str):
        resolved = _resolve_ref(geo, entities)
        if isinstance(resolved, dict):
            return _extract_text(
                resolved.get("defaultLocalizedName") or resolved.get("localizedName")
            )
    return _extract_text(geo)


def _find_vector_image(
    value: Any,
    entities: dict[str, dict[str, Any]],
    visited: set[int] | None = None,
) -> dict[str, Any] | None:
    if isinstance(value, str):
        resolved = _resolve_ref(value, entities)
        if resolved == value:
            return None
        return _find_vector_image(resolved, entities, visited)
    if not isinstance(value, (dict, list)):
        return None

    visited = visited or set()
    if id(value) in visited:
        return None
    visited.add(id(value))

    if isinstance(value, dict):
        if value.get("rootUrl") and isinstance(value.get("artifacts"), list):
            return value
        for nested in value.values():
            vector_image = _find_vector_image(nested, entities, visited)
            if vector_image:
                return vector_image
    else:
        for nested in value:
            vector_image = _find_vector_image(nested, entities, visited)
            if vector_image:
                return vector_image
    return None


def _parse_profile_picture(
    profile: dict[str, Any], entities: dict[str, dict[str, Any]]
) -> str | None:
    picture = profile.get("profilePicture") or profile.get("picture")
    vector_image = _find_vector_image(picture, entities)
    if vector_image:
        artifacts = vector_image.get("artifacts") or []
        artifacts_with_paths = [
            artifact
            for artifact in artifacts
            if artifact.get("fileIdentifyingUrlPathSegment")
        ]
        if artifacts_with_paths:
            largest = max(
                artifacts_with_paths,
                key=lambda artifact: artifact.get("width", 0)
                * artifact.get("height", 0),
            )
            return (
                f"{vector_image.get('rootUrl', '')}"
                f"{largest['fileIdentifyingUrlPathSegment']}"
            )
    return None


def _parse_rsc_chunks(response_text: str | None) -> list[Any]:
    if not response_text:
        return []
    chunks: dict[str, Any] = {}
    for line in response_text.splitlines():
        chunk_id, separator, payload = line.partition(":")
        if not separator or not payload.lstrip().startswith(("[", "{")):
            continue
        try:
            chunks[chunk_id.strip()] = json.loads(payload)
        except json.JSONDecodeError:
            # Captured React Flight streams can contain a backslash before
            # non-JSON-special class-name characters (for example ``\_``).
            sanitized = re.sub(r'\\(?!["\\/bfnrtu])', "", payload)
            try:
                chunks[chunk_id.strip()] = json.loads(sanitized)
            except json.JSONDecodeError:
                continue

    reference_re = re.compile(r"^\$L?([0-9a-f]+)$", re.IGNORECASE)

    def resolve(value: Any, resolving: set[str]) -> Any:
        if isinstance(value, str):
            match = reference_re.match(value)
            if not match:
                return value
            reference = match.group(1)
            if reference not in chunks or reference in resolving:
                return value
            return resolve(chunks[reference], resolving | {reference})
        if isinstance(value, list):
            return [resolve(nested, resolving) for nested in value]
        if isinstance(value, dict):
            return {
                key: resolve(nested, resolving)
                for key, nested in value.items()
            }
        return value

    return [resolve(value, {chunk_id}) for chunk_id, value in chunks.items()]


def _rsc_items(response_text: str | None) -> list[Any]:
    items: list[Any] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            if len(value) >= 2 and isinstance(value[0], str):
                try:
                    metadata = json.loads(value[0])
                except (json.JSONDecodeError, TypeError):
                    metadata = None
                if isinstance(metadata, dict) and "threadlineDecoration" in metadata:
                    items.append(value[1])
                    return
            for nested in value:
                walk(nested)
        elif isinstance(value, dict):
            for nested in value.values():
                walk(nested)

    for chunk in _parse_rsc_chunks(response_text):
        walk(chunk)
    return items


def _react_nodes(value: Any, tag: str):
    if isinstance(value, list):
        if len(value) >= 4 and value[0] == "$" and value[1] == tag:
            yield value
        for nested in value:
            yield from _react_nodes(nested, tag)
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _react_nodes(nested, tag)


def _react_text(value: Any) -> str | None:
    if isinstance(value, str):
        if value.startswith("$"):
            return None
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        if len(value) >= 4 and value[0] == "$" and isinstance(value[3], dict):
            return _react_text(value[3].get("children"))
        parts = [_react_text(nested) for nested in value]
        return " ".join(part for part in parts if part) or None
    if isinstance(value, dict):
        return _react_text(value.get("children"))
    return None


def _rsc_item_texts(item: Any) -> list[str]:
    texts: list[str] = []

    def append(text: str | None) -> None:
        if text and text not in texts:
            texts.append(text)

    for node in _react_nodes(item, "p"):
        props = node[3] if len(node) >= 4 and isinstance(node[3], dict) else {}
        append(_react_text(props.get("children")))
    for value in _walk_dicts(item):
        text_props = value.get("textProps")
        if isinstance(text_props, dict):
            append(_react_text(text_props.get("children")))
    return texts


def _rsc_links(value: Any) -> list[str]:
    links: list[str] = []
    for item in _walk_dicts(value):
        for key in ("url", "actionUrl", "href"):
            link = item.get(key)
            if (
                isinstance(link, str)
                and link
                and not link.startswith(("$", "javascript:"))
                and link not in links
            ):
                links.append(link)
    return links


def _largest_rsc_image(value: Any) -> str | None:
    best: tuple[int, str] | None = None
    for item in _walk_dicts(value):
        root_url = item.get("rootUrl")
        renditions = item.get("imageRenditions")
        if not isinstance(root_url, str) or not isinstance(renditions, list):
            continue
        for rendition in renditions:
            if not isinstance(rendition, dict) or not rendition.get("suffixUrl"):
                continue
            area = int(rendition.get("width") or 0) * int(
                rendition.get("height") or 0
            )
            suffix = rendition["suffixUrl"]
            candidate = (
                suffix
                if str(suffix).startswith(("http://", "https://"))
                else f"{root_url}{suffix}"
            )
            if best is None or area > best[0]:
                best = (area, candidate)
    return best[1] if best else None


def parse_certifications_rsc(pages: list[str]) -> list[LicenseCertification]:
    certifications: list[LicenseCertification] = []
    seen: set[tuple[str | None, str | None]] = set()
    for page in pages:
        for item in _rsc_items(page):
            texts = _rsc_item_texts(item)
            if not texts:
                continue
            name = texts[0]
            if name.casefold() in {"licenses & certifications", "certifications"}:
                continue
            issuer = next(
                (
                    text
                    for text in texts[1:]
                    if not text.startswith(("Issued ", "Credential ID", "Skills:"))
                    and text.lower() not in {"show credential", "show all"}
                ),
                None,
            )
            issued = next(
                (text for text in texts if text.startswith("Issued ")),
                None,
            )
            issue_date = expiration_date = None
            if issued:
                date_parts = [part.strip() for part in issued.split("·")]
                issue_date = re.sub(r"^Issued\s+", "", date_parts[0]).strip()
                if len(date_parts) > 1:
                    expiration_date = re.sub(
                        r"^Expires\s+",
                        "",
                        date_parts[1],
                    ).strip()
            credential_id = next(
                (
                    re.sub(r"^Credential ID\s*", "", text).strip()
                    for text in texts
                    if text.startswith("Credential ID")
                ),
                None,
            )
            skills_preview = next(
                (text for text in texts if text.startswith("Skills:")),
                None,
            )
            links = _rsc_links(item)
            issuer_url = next(
                (
                    urljoin("https://www.linkedin.com", link)
                    for link in links
                    if "/company/" in link or "/school/" in link
                ),
                None,
            )
            credential_url = next(
                (
                    link
                    for link in links
                    if link.startswith(("http://", "https://"))
                    and "linkedin.com/company/" not in link
                    and "linkedin.com/school/" not in link
                ),
                None,
            )
            identity = (name, issuer)
            if identity in seen:
                continue
            seen.add(identity)
            certifications.append(
                LicenseCertification(
                    name=name,
                    issuer=issuer,
                    issue_date=issue_date,
                    expiration_date=expiration_date,
                    credential_id=credential_id,
                    credential_url=credential_url,
                    issuer_url=issuer_url,
                    issuer_logo_url=_largest_rsc_image(item),
                    skills_preview=skills_preview,
                )
            )
    return certifications


def parse_languages_rsc(pages: list[str]) -> list[Language]:
    languages: list[Language] = []
    seen: set[str] = set()
    for page in pages:
        for item in _rsc_items(page):
            texts = _rsc_item_texts(item)
            if not texts:
                continue
            name = texts[0]
            if name.casefold() == "languages":
                continue
            normalized = name.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            languages.append(
                Language(
                    name=name,
                    proficiency=texts[1] if len(texts) > 1 else None,
                )
            )
    return languages


def parse_test_scores_rsc(pages: list[str]) -> list[TestScore]:
    test_scores: list[TestScore] = []
    seen: set[tuple[str, str | None]] = set()
    for page in pages:
        for item in _rsc_items(page):
            texts = _rsc_item_texts(item)
            if not texts:
                continue
            name = texts[0]
            if name.casefold() == "test scores":
                continue
            summary = next(
                (text for text in texts[1:] if text.startswith("Score:")),
                None,
            )
            score, maximum, date = _split_score_summary(summary)
            description_parts = [
                text
                for text in texts[1:]
                if text != summary
                and text.lower() not in {"show more", "show less"}
            ]
            identity = (name, summary)
            if identity in seen:
                continue
            seen.add(identity)
            test_scores.append(
                TestScore(
                    name=name,
                    score_summary=summary,
                    score=score,
                    max_score=maximum,
                    date=date,
                    description="\n".join(description_parts) or None,
                )
            )
    return test_scores


def parse_skills_rsc(response_text: str | None) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[str] = set()
    for item in _rsc_items(response_text):
        texts = _rsc_item_texts(item)
        if not texts:
            continue
        name = texts[0]
        if name.casefold() == "skills":
            continue
        normalized = name.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        associations: list[SkillAssociation] = []
        for text in texts[1:]:
            cleaned = re.sub(r"^(?:Used|Associated with)\s+", "", text).strip()
            title, separator, company = cleaned.partition(" at ")
            if separator:
                associations.append(
                    SkillAssociation(title=title or None, company=company or None)
                )
        skills.append(Skill(name=name, associated_experiences=associations))
    return skills


def parse_contact_rsc(
    response_text: str | None,
    *,
    profile_url: str,
) -> ContactInfo:
    chunks = _parse_rsc_chunks(response_text)
    texts: list[str] = []
    for chunk in chunks:
        for node in _react_nodes(chunk, "p"):
            props = node[3] if len(node) >= 4 and isinstance(node[3], dict) else {}
            text = _react_text(props.get("children"))
            if text and text not in texts:
                texts.append(text)
    links: list[str] = []
    for chunk in chunks:
        for link in _rsc_links(chunk):
            if link not in links:
                links.append(link)

    email = next(
        (
            match.group(0)
            for text in texts
            if (match := re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text))
        ),
        None,
    )
    if not email:
        email = next(
            (link.removeprefix("mailto:") for link in links if link.startswith("mailto:")),
            None,
        )
    phone_numbers = [
        link.removeprefix("tel:") for link in links if link.startswith("tel:")
    ]
    websites = [
        link
        for link in links
        if link.startswith(("http://", "https://"))
        and "linkedin.com/in/" not in link
        and "media.licdn.com/" not in link
    ]

    def after_label(*labels: str) -> str | None:
        for index, text in enumerate(texts[:-1]):
            normalized = text.strip().rstrip(":").casefold()
            if normalized in labels:
                return texts[index + 1]
        return None

    captured_profile_url = next(
        (
            urljoin("https://www.linkedin.com", link)
            for link in links
            if "linkedin.com/in/" in link or link.startswith("/in/")
        ),
        profile_url,
    )
    return ContactInfo(
        profile_url=captured_profile_url,
        email=email,
        phone_numbers=list(dict.fromkeys(phone_numbers)),
        websites=list(dict.fromkeys(websites)),
        address=after_label("address"),
        birthday=after_label("birthday"),
        connected_on=after_label("connected", "connected on"),
    )


def merge_profile_enrichments(
    profile: ProfileResponse,
    *,
    contact_response: str | None = None,
    skills_response: str | None = None,
    skill_pages: list[str] | None = None,
    certification_pages: list[str] | None = None,
    language_pages: list[str] | None = None,
    test_score_pages: list[str] | None = None,
) -> ProfileResponse:
    skills_by_name = {skill.name.casefold(): skill for skill in profile.skills}
    enriched_skills = parse_skills_rsc(skills_response)
    for page in skill_pages or []:
        enriched_skills.extend(parse_skills_rsc(page))
    for skill in enriched_skills:
        existing = skills_by_name.get(skill.name.casefold())
        if existing:
            existing_associations = {
                (association.title, association.company)
                for association in existing.associated_experiences
            }
            for association in skill.associated_experiences:
                identity = (association.title, association.company)
                if identity not in existing_associations:
                    existing.associated_experiences.append(association)
        else:
            profile.skills.append(skill)
            skills_by_name[skill.name.casefold()] = skill

    certifications = parse_certifications_rsc(certification_pages or [])
    languages = parse_languages_rsc(language_pages or [])
    test_scores = parse_test_scores_rsc(test_score_pages or [])
    if certifications:
        profile.licenses_certifications = certifications
    if languages:
        profile.languages = languages
    if test_scores:
        profile.test_scores = test_scores
    profile.contact_info = parse_contact_rsc(
        contact_response,
        profile_url=profile.profile_url,
    )
    return profile


def parse_profile_response(
    *,
    vanity: str,
    profile_payload: dict[str, Any],
) -> ProfileResponse:
    payload_entities = _collect_payload_entities(profile_payload)
    entities = _entity_map(payload_entities)
    profile = _find_profile_entity(payload_entities, vanity)
    if profile is None:
        raise ProfilePayloadError(
            "LinkedIn decorated response did not contain a profile entity"
        )

    detail_keys = {
        "firstName",
        "lastName",
        "headline",
        "summary",
        "profilePicture",
        "geoLocationName",
    }
    if not any(key in profile for key in detail_keys):
        raise ProfilePayloadError(
            "LinkedIn returned only a profile stub. The profile decoration may be stale."
        )

    member_identity = _member_identity(profile)

    first_name = _extract_text(profile.get("firstName")) or _extract_text(
        profile.get("multiLocaleFirstName")
    )
    last_name = _extract_text(profile.get("lastName")) or _extract_text(
        profile.get("multiLocaleLastName")
    )
    name = " ".join(part for part in (first_name, last_name) if part) or None

    about = (
        _extract_text(profile.get("summary"))
        or _extract_text(profile.get("multiLocaleSummary"))
        or _extract_text(profile.get("about"))
    )

    experience = _parse_experience_entities(profile, entities)
    volunteer_experience = _parse_volunteer_entities(profile, entities)
    education = _parse_education_entities(entities)
    skills = _parse_skill_entities(profile, entities)
    projects = _parse_projects(profile, entities)
    honors_awards = _parse_honors(profile, entities)
    test_scores = _parse_test_scores(profile, entities)
    languages = _parse_languages(profile, entities)
    licenses_certifications = _parse_certifications(profile, entities)

    for item in payload_entities:
        item_type = item.get("$type", "")
        if item_type and not any(
            token in item_type
            for token in (
                "Profile",
                "Position",
                "Education",
                "Skill",
                "Geo",
                "Company",
                "School",
                "Project",
                "Honor",
                "Award",
                "TestScore",
                "Language",
                "Certification",
            )
        ):
            logger.debug("Unmapped LinkedIn entity type: %s", item_type)

    return ProfileResponse(
        profile_url=build_profile_url(vanity),
        member_identity=member_identity,
        name=name,
        headline=_extract_text(profile.get("headline"))
        or _extract_text(profile.get("multiLocaleHeadline")),
        location=_parse_location(profile, entities),
        about=about,
        profile_picture_url=_parse_profile_picture(profile, entities),
        work_experience=experience,
        volunteer_experience=volunteer_experience,
        education=education,
        projects=projects,
        skills=skills,
        honors_awards=honors_awards,
        test_scores=test_scores,
        languages=languages,
        licenses_certifications=licenses_certifications,
        contact_info=ContactInfo(profile_url=build_profile_url(vanity)),
    )
