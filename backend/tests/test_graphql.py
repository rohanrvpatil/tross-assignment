import json
import unittest

from backend.linkedin.graphql import (
    _fetch_paginated_section,
    fetch_profile_enrichments,
)


def _page(item_count: int) -> str:
    items = []
    for index in range(item_count):
        metadata = json.dumps(
            {
                "threadlineDecoration": None,
                "key": f"item-{index}",
                "semanticId": "",
            }
        )
        items.append([metadata, ["$", "div", None, {"children": []}]])
    return "0:" + json.dumps([items])


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post_sdui(self, path, **kwargs):
        self.calls.append({"path": path, **kwargs})
        start = (
            kwargs.get("body", {})
            .get("clientArguments", {})
            .get("payload", {})
            .get("start")
        )
        if start is None:
            return _page(0)
        return _page(10 if start == 0 else 2)


class PartiallyFailingClient(RecordingClient):
    async def post_sdui(self, path, **kwargs):
        if path.endswith("/navigation"):
            raise RuntimeError("optional contact unavailable")
        return await super().post_sdui(path, **kwargs)


class GraphqlEnrichmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_paginated_section_advances_offset_until_short_page(self) -> None:
        client = RecordingClient()

        pages = await _fetch_paginated_section(
            client,
            section="languages",
            vanity="example-user",
            profile_id="ACoATEST",
            referer="https://www.linkedin.com/in/example-user/",
        )

        self.assertEqual(len(pages), 2)
        starts = [
            call["body"]["clientArguments"]["payload"]["start"]
            for call in client.calls
        ]
        self.assertEqual(starts, [0, 10])

    async def test_optional_enrichment_failure_is_section_local(self) -> None:
        client = PartiallyFailingClient()

        result = await fetch_profile_enrichments(
            client,
            vanity="example-user",
            profile_id="ACoATEST",
            referer="https://www.linkedin.com/in/example-user/",
            given_name="Example",
            family_name="User",
        )

        self.assertIsNone(result.contact)
        self.assertIsNotNone(result.skills)
        self.assertEqual(len(result.skill_pages), 2)
        self.assertEqual(len(result.certification_pages), 2)
        self.assertEqual(len(result.language_pages), 2)
        self.assertEqual(len(result.test_score_pages), 2)
        skill_page_calls = [
            call
            for call in client.calls
            if (
                call.get("body", {})
                .get("clientArguments", {})
                .get("payload", {})
                .get("filter")
                == "ProfileSkillCategory_ALL"
            )
        ]
        self.assertEqual(len(skill_page_calls), 2)


if __name__ == "__main__":
    unittest.main()
