import unittest

from backend.linkedin.parser import ProfilePayloadError, parse_profile_response


class ProfileParserTests(unittest.TestCase):
    def test_parses_all_supported_profile_fields(self) -> None:
        payload = {
            "data": {
                "elements": [
                    {
                        "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                        "entityUrn": "urn:li:fsd_profile:ACoAATEST123",
                        "publicIdentifier": "sample-user",
                        "firstName": "Sample",
                        "lastName": "User",
                        "headline": "Backend Engineer",
                        "geoLocationName": "Pune, Maharashtra, India",
                        "multiLocaleSummary": {
                            "en_US": "Builds reliable backend systems."
                        },
                        "profilePicture": {
                            "displayImageReference": "urn:li:digitalmediaAsset:photo"
                        },
                        "*profilePositionGroups": "urn:li:fsd_collectionResponse:groups",
                        "*profileVolunteerExperiences": (
                            "urn:li:fsd_collectionResponse:volunteers"
                        ),
                    }
                ]
            },
            "included": [
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:fsd_collectionResponse:groups",
                    "*elements": ["urn:li:fsd_profilePositionGroup:1"],
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.PositionGroup",
                    "entityUrn": "urn:li:fsd_profilePositionGroup:1",
                    "*profilePositionInPositionGroup": (
                        "urn:li:fsd_collectionResponse:positions"
                    ),
                },
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:fsd_collectionResponse:positions",
                    "*elements": ["urn:li:fsd_profilePosition:1"],
                },
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:fsd_collectionResponse:volunteers",
                    "*elements": ["urn:li:fsd_profileVolunteerExperience:1"],
                },
                {
                    "$type": "com.linkedin.common.VectorImage",
                    "entityUrn": "urn:li:digitalmediaAsset:photo",
                    "rootUrl": "https://media.example/",
                    "artifacts": [
                        {
                            "width": 100,
                            "height": 100,
                            "fileIdentifyingUrlPathSegment": "small.jpg",
                        },
                        {
                            "width": 800,
                            "height": 800,
                            "fileIdentifyingUrlPathSegment": "large.jpg",
                        },
                    ],
                },
                {
                    "$type": "com.linkedin.voyager.dash.organization.Company",
                    "entityUrn": "urn:li:fsd_company:1",
                    "name": "Example Corp",
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.EmploymentType",
                    "entityUrn": "urn:li:fsd_employmentType:1",
                    "localizedName": "Full-time",
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Position",
                    "entityUrn": "urn:li:fsd_profilePosition:1",
                    "title": "Senior Engineer",
                    "*company": "urn:li:fsd_company:1",
                    "*employmentType": "urn:li:fsd_employmentType:1",
                    "geoLocationName": "Pune, Maharashtra, India",
                    "description": "Designed APIs.",
                    "dateRange": {
                        "start": {"month": 1, "year": 2023},
                        "end": {"month": 8, "year": 2026},
                    },
                },
                {
                    "$type": (
                        "com.linkedin.voyager.dash.identity.profile."
                        "VolunteerExperience"
                    ),
                    "entityUrn": "urn:li:fsd_profileVolunteerExperience:1",
                    "role": "Teaching Volunteer",
                    "companyName": "Anybody Can Help",
                    "cause": "EDUCATION",
                    "description": "Taught English concepts.",
                    "dateRange": {
                        "start": {"month": 2, "year": 2021},
                        "end": {"month": 7, "year": 2021},
                    },
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Education",
                    "entityUrn": "urn:li:fsd_profileEducation:1",
                    "schoolName": "Example University",
                    "degreeName": "B.Tech, Computer Science",
                    "dateRange": {
                        "start": {"year": 2018},
                        "end": {"year": 2022},
                    },
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Skill",
                    "entityUrn": "urn:li:fsd_skill:1",
                    "name": "Python",
                },
            ],
        }

        result = parse_profile_response(
            vanity="sample-user",
            profile_payload=payload,
        )

        self.assertEqual(result.member_identity, "ACoAATEST123")
        self.assertEqual(result.name, "Sample User")
        self.assertEqual(result.headline, "Backend Engineer")
        self.assertEqual(result.location, "Pune, Maharashtra, India")
        self.assertEqual(result.about, "Builds reliable backend systems.")
        self.assertEqual(result.profile_picture_url, "https://media.example/large.jpg")
        self.assertEqual(len(result.work_experience), 1)
        self.assertEqual(result.work_experience[0].company, "Example Corp")
        self.assertEqual(result.work_experience[0].employment_type, "Full-time")
        self.assertEqual(
            result.work_experience[0].location,
            "Pune, Maharashtra, India",
        )
        self.assertEqual(result.work_experience[0].start_date, "Jan 2023")
        self.assertEqual(result.work_experience[0].end_date, "Aug 2026")
        self.assertEqual(len(result.volunteer_experience), 1)
        self.assertEqual(
            result.volunteer_experience[0].role,
            "Teaching Volunteer",
        )
        self.assertEqual(
            result.volunteer_experience[0].organization,
            "Anybody Can Help",
        )
        self.assertEqual(result.volunteer_experience[0].cause, "Education")
        self.assertEqual(len(result.education), 1)
        self.assertEqual(result.education[0].school, "Example University")
        self.assertEqual(result.education[0].start_date, "2018")
        self.assertEqual([skill.name for skill in result.skills], ["Python"])
        self.assertEqual(result.contact_info.profile_url, result.profile_url)

    def test_parses_expanded_sections_and_skill_associations(self) -> None:
        payload = {
            "data": {
                "elements": [
                    {
                        "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                        "entityUrn": "urn:li:fsd_profile:ACoAEXPANDED",
                        "publicIdentifier": "expanded-user",
                        "firstName": "Expanded",
                        "lastName": "User",
                        "headline": "Engineer",
                        "*profileSkills": "urn:li:collection:skills",
                        "*profileProjects": "urn:li:collection:projects",
                    }
                ]
            },
            "included": [
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:collection:skills",
                    "*elements": ["urn:li:fsd_skill:python"],
                },
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:collection:projects",
                    "*elements": ["urn:li:fsd_project:1"],
                },
                {
                    "$type": "com.linkedin.restli.common.CollectionResponse",
                    "entityUrn": "urn:li:collection:associations",
                    "*elements": ["urn:li:fsd_skillAssociation:1"],
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Skill",
                    "entityUrn": "urn:li:fsd_skill:python",
                    "name": "Python",
                    "category": "Tools & Technologies",
                    "*profileSkillAssociations": "urn:li:collection:associations",
                },
                {
                    "$type": (
                        "com.linkedin.voyager.dash.identity.profile.SkillAssociation"
                    ),
                    "entityUrn": "urn:li:fsd_skillAssociation:1",
                    "*skill": "urn:li:fsd_skill:python",
                    "*position": "urn:li:fsd_profilePosition:1",
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Position",
                    "entityUrn": "urn:li:fsd_profilePosition:1",
                    "title": "Senior Engineer",
                    "*company": "urn:li:fsd_company:1",
                },
                {
                    "$type": "com.linkedin.voyager.dash.organization.Company",
                    "entityUrn": "urn:li:fsd_company:1",
                    "name": "Example Corp",
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Project",
                    "entityUrn": "urn:li:fsd_project:1",
                    "title": "Profile API",
                    "description": "Built a profile service.",
                    "url": "https://example.com/project",
                    "dateRange": {
                        "start": {"month": 1, "year": 2025},
                        "end": {"month": 6, "year": 2025},
                    },
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Honor",
                    "entityUrn": "urn:li:fsd_honor:1",
                    "title": "Engineering Award",
                    "issuer": "Example Org",
                    "issueDate": {"month": 5, "year": 2024},
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.TestScore",
                    "entityUrn": "urn:li:fsd_testScore:1",
                    "name": "SAT",
                    "score": "1520 / 1600",
                    "date": {"month": 3, "year": 2023},
                    "description": "Score breakdown",
                },
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Language",
                    "entityUrn": "urn:li:fsd_language:1",
                    "name": "English",
                    "proficiency": "Native or bilingual proficiency",
                },
                {
                    "$type": (
                        "com.linkedin.voyager.dash.identity.profile.Certification"
                    ),
                    "entityUrn": "urn:li:fsd_certification:1",
                    "name": "Cloud Certification",
                    "authority": "Cloud Org",
                    "licenseNumber": "ABC123",
                    "dateRange": {"start": {"month": 4, "year": 2024}},
                },
            ],
        }

        result = parse_profile_response(
            vanity="expanded-user",
            profile_payload=payload,
        )

        self.assertEqual(result.skills[0].category, "Tools & Technologies")
        self.assertEqual(
            result.skills[0].associated_experiences[0].title,
            "Senior Engineer",
        )
        self.assertEqual(
            result.skills[0].associated_experiences[0].company,
            "Example Corp",
        )
        self.assertEqual(result.projects[0].title, "Profile API")
        self.assertEqual(result.honors_awards[0].issuer, "Example Org")
        self.assertEqual(result.test_scores[0].score, "1520")
        self.assertEqual(result.test_scores[0].max_score, "1600")
        self.assertEqual(result.languages[0].name, "English")
        self.assertEqual(
            result.licenses_certifications[0].credential_id,
            "ABC123",
        )

    def test_rejects_an_undecorated_profile_stub(self) -> None:
        payload = {
            "included": [
                {
                    "$type": "com.linkedin.voyager.dash.identity.profile.Profile",
                    "entityUrn": "urn:li:fsd_profile:ACoAATEST123",
                    "versionTag": "1",
                }
            ]
        }

        with self.assertRaises(ProfilePayloadError):
            parse_profile_response(
                vanity="sample-user",
                profile_payload=payload,
            )


if __name__ == "__main__":
    unittest.main()
