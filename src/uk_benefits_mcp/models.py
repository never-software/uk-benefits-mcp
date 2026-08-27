"""Typed tool results shared by the source clients and MCP server."""

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    """Reject accidental output fields so source schema drift is visible."""

    model_config = ConfigDict(extra="forbid")


AuthorityLevel = Literal["legislation", "case_law", "dwp_guidance", "hmrc_guidance"]


class SourceProvenance(Model):
    """Where retrieved evidence came from and how to verify it."""

    source_name: str
    authority: AuthorityLevel
    source_url: str
    retrieved_at: datetime
    source_updated_at: datetime | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    licence: str
    licence_url: str
    caveats: list[str] = Field(default_factory=list)


DataT = TypeVar("DataT")


class Evidence(Model, Generic[DataT]):
    """A typed result plus response-level provenance."""

    source: SourceProvenance
    data: DataT


class GuidanceItem(Model):
    title: str
    url: str
    description: str = ""
    document_type: str = ""
    updated_at: datetime | None = None


class GuidanceSearch(Model):
    query: str
    organisation: Literal["dwp", "hmrc"]
    count: int
    results: list[GuidanceItem]


class AdmDocument(Model):
    title: str
    url: str
    content_type: str


class AdmCatalogue(Model):
    query: str
    count: int
    documents: list[AdmDocument]


class TextHit(Model):
    locator: str
    excerpt: str


class AdmSearch(Model):
    document: AdmDocument
    query: str
    pages: int
    count: int
    hits: list[TextHit]


class HmrcManual(Model):
    manual: str
    section: str | None
    title: str
    description: str
    text: str
    truncated: bool


class LegislationItem(Model):
    title: str
    url: str
    document_type: str
    year: int | None = None
    number: str | None = None
    updated_at: datetime | None = None
    summary: str = ""


class LegislationSearch(Model):
    query: str
    count: int
    results: list[LegislationItem]


class LegislationProvision(Model):
    document_type: str
    year: int
    number: str
    provision: str | None
    as_of: str | None
    title: str
    text: str
    truncated: bool


class CaseLawItem(Model):
    title: str
    slug: str
    url: str
    citation: str | None = None
    court: str | None = None
    handed_down_at: datetime | None = None
    updated_at: datetime | None = None


class CaseLawSearch(Model):
    query: str
    court: str
    page: int
    count: int
    results: list[CaseLawItem]


class CaseTextSearch(Model):
    slug: str
    title: str
    query: str
    count: int
    hits: list[TextHit]
