import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.linkedin.graphql import ProfileEnrichments
from backend.main import app


class ProfileRouterTests(unittest.TestCase):
    def test_profile_endpoint_returns_stable_expanded_contract(self) -> None:
        decorated_payload = {
            "data": {
                "elements": [
                    {
                        "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                        "entityUrn": "urn:li:fsd_profile:ACoAROUTER",
                        "publicIdentifier": "example-user",
                        "firstName": "Example",
                        "lastName": "User",
                        "headline": "Engineer",
                    }
                ]
            },
            "included": [
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Skill",
                    "entityUrn": "urn:li:fsd_skill:1",
                    "name": "Python",
                }
            ],
        }

        with (
            patch(
                "backend.routers.profile.fetch_decorated_profile",
                new=AsyncMock(return_value=decorated_payload),
            ),
            patch(
                "backend.routers.profile.fetch_profile_enrichments",
                new=AsyncMock(return_value=ProfileEnrichments()),
            ),
        ):
            response = TestClient(app).get(
                "/profile",
                params={
                    "url": "https://www.linkedin.com/in/example-user/",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["member_identity"], "ACoAROUTER")
        self.assertEqual(body["skills"][0]["name"], "Python")
        for field in (
            "projects",
            "honors_awards",
            "test_scores",
            "languages",
            "licenses_certifications",
        ):
            self.assertEqual(body[field], [])
        for removed_field in (
            "causes",
            "recent_activity",
            "featured",
            "highlights",
            "connections_count",
        ):
            self.assertNotIn(removed_field, body)
        self.assertEqual(
            body["contact_info"]["profile_url"],
            "https://www.linkedin.com/in/example-user/",
        )


if __name__ == "__main__":
    unittest.main()
