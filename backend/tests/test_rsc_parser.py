import json
import unittest

from backend.linkedin.parser import (
    merge_profile_enrichments,
    parse_certifications_rsc,
    parse_contact_rsc,
    parse_languages_rsc,
    parse_skills_rsc,
    parse_test_scores_rsc,
)
from backend.models.profile import Language, LicenseCertification, ProfileResponse


def _paragraph(text: str):
    return ["$", "p", None, {"children": [text]}]


def _item(*children):
    metadata = json.dumps(
        {
            "threadlineDecoration": None,
            "key": "fixture-item",
            "semanticId": "",
        }
    )
    return [
        metadata,
        ["$", "div", None, {"children": list(children)}],
        "$undefined",
    ]


def _rsc(*items) -> str:
    return "0:" + json.dumps([list(items)])


class RscParserTests(unittest.TestCase):
    def test_parses_captured_paginated_sections(self) -> None:
        certification_page = _rsc(
            _item(
                _paragraph("Cloud Certification"),
                _paragraph("Example Cloud"),
                _paragraph("Issued Apr 2024 · Expires Apr 2027"),
                _paragraph("Credential ID ABC-123"),
                _paragraph("Skills: Cloud Computing"),
                {
                    "url": "/company/123/",
                    "renderPayload": {
                        "rootUrl": "https://media.example/",
                        "imageRenditions": [
                            {"width": 100, "height": 100, "suffixUrl": "small.png"},
                            {"width": 400, "height": 400, "suffixUrl": "large.png"},
                        ],
                    },
                },
            )
        )
        language_page = _rsc(
            _item(
                _paragraph("English"),
                _paragraph("Native or bilingual proficiency"),
            )
        )
        score_page = _rsc(
            _item(
                _paragraph("SAT"),
                _paragraph("Score: 1520 / 1600 · Mar 2023"),
                {
                    "textProps": {
                        "children": [
                            "Reading: 750",
                            ["$", "br", None, {}],
                            "Mathematics: 770",
                        ]
                    }
                },
            )
        )

        certifications = parse_certifications_rsc([certification_page])
        languages = parse_languages_rsc([language_page])
        scores = parse_test_scores_rsc([score_page])

        self.assertEqual(len(certifications), 1)
        self.assertEqual(certifications[0].credential_id, "ABC-123")
        self.assertEqual(certifications[0].expiration_date, "Apr 2027")
        self.assertEqual(
            certifications[0].issuer_logo_url,
            "https://media.example/large.png",
        )
        self.assertEqual(languages[0].proficiency, "Native or bilingual proficiency")
        self.assertEqual(scores[0].score, "1520")
        self.assertEqual(scores[0].max_score, "1600")
        self.assertEqual(scores[0].date, "Mar 2023")
        self.assertIn("Mathematics: 770", scores[0].description or "")

    def test_parses_contact_and_structured_skills(self) -> None:
        contact = "0:" + json.dumps(
            [
                _paragraph("Email"),
                _paragraph("person@example.com"),
                _paragraph("Birthday"),
                _paragraph("January 5"),
                {"url": "mailto:person@example.com"},
                {"url": "tel:+1-555-0100"},
                {"url": "https://portfolio.example/"},
                {"url": "/in/example-user/"},
            ]
        )
        skills = _rsc(
            _item(
                _paragraph("Python"),
                _paragraph("Associated with Senior Engineer at Example Corp"),
            )
        )

        contact_info = parse_contact_rsc(
            contact,
            profile_url="https://www.linkedin.com/in/example-user/",
        )
        parsed_skills = parse_skills_rsc(skills)

        self.assertEqual(contact_info.email, "person@example.com")
        self.assertEqual(contact_info.phone_numbers, ["+1-555-0100"])
        self.assertEqual(contact_info.websites, ["https://portfolio.example/"])
        self.assertEqual(contact_info.birthday, "January 5")
        self.assertEqual(parsed_skills[0].name, "Python")
        self.assertEqual(
            parsed_skills[0].associated_experiences[0].title,
            "Senior Engineer",
        )
        self.assertEqual(
            parsed_skills[0].associated_experiences[0].company,
            "Example Corp",
        )

    def test_malformed_enrichment_keeps_decorated_fallbacks(self) -> None:
        profile = ProfileResponse(
            profile_url="https://www.linkedin.com/in/example-user/",
            member_identity="ACoATEST",
            languages=[Language(name="English")],
            licenses_certifications=[
                LicenseCertification(name="Existing Certification")
            ],
        )

        result = merge_profile_enrichments(
            profile,
            contact_response="not an RSC stream",
            certification_pages=["malformed"],
            language_pages=["malformed"],
            test_score_pages=["malformed"],
        )

        self.assertEqual(result.languages[0].name, "English")
        self.assertEqual(
            result.licenses_certifications[0].name,
            "Existing Certification",
        )
        self.assertEqual(result.contact_info.profile_url, profile.profile_url)


if __name__ == "__main__":
    unittest.main()
