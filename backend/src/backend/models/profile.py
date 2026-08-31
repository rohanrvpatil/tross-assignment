from pydantic import BaseModel, Field


class Experience(BaseModel):
    title: str | None = None
    company: str | None = None
    employment_type: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class VolunteerExperience(BaseModel):
    role: str | None = None
    organization: str | None = None
    cause: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None


class Education(BaseModel):
    school: str | None = None
    degree: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class SkillAssociation(BaseModel):
    title: str | None = None
    company: str | None = None


class Skill(BaseModel):
    name: str
    category: str | None = None
    associated_experiences: list[SkillAssociation] = Field(default_factory=list)


class Project(BaseModel):
    title: str | None = None
    description: str | None = None
    url: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    associated_with: str | None = None


class HonorAward(BaseModel):
    title: str | None = None
    issuer: str | None = None
    issue_date: str | None = None
    description: str | None = None


class TestScore(BaseModel):
    name: str | None = None
    score_summary: str | None = None
    score: str | None = None
    max_score: str | None = None
    date: str | None = None
    description: str | None = None


class Language(BaseModel):
    name: str
    proficiency: str | None = None


class LicenseCertification(BaseModel):
    name: str | None = None
    issuer: str | None = None
    issue_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    credential_url: str | None = None
    issuer_url: str | None = None
    issuer_logo_url: str | None = None
    skills_preview: str | None = None


class ContactInfo(BaseModel):
    profile_url: str | None = None
    email: str | None = None
    phone_numbers: list[str] = Field(default_factory=list)
    websites: list[str] = Field(default_factory=list)
    address: str | None = None
    birthday: str | None = None
    connected_on: str | None = None


class ProfileResponse(BaseModel):
    profile_url: str
    member_identity: str
    name: str | None = None
    headline: str | None = None
    location: str | None = None
    about: str | None = None
    profile_picture_url: str | None = None
    work_experience: list[Experience] = Field(default_factory=list)
    volunteer_experience: list[VolunteerExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    honors_awards: list[HonorAward] = Field(default_factory=list)
    test_scores: list[TestScore] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)
    licenses_certifications: list[LicenseCertification] = Field(
        default_factory=list
    )
    contact_info: ContactInfo = Field(default_factory=ContactInfo)
