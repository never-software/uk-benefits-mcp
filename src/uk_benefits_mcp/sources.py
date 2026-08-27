"""Strict clients and parsers for the official public evidence sources."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, cast

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as DefusedET
from pypdf import PdfReader

from .models import (
    AdmCatalogue,
    AdmDocument,
    AdmSearch,
    CaseLawItem,
    CaseLawSearch,
    CaseTextSearch,
    Evidence,
    GuidanceItem,
    GuidanceSearch,
    HmrcManual,
    LegislationItem,
    LegislationProvision,
    LegislationSearch,
    SourceProvenance,
    TextHit,
)

OGL_NAME = "Open Government Licence v3.0"
OGL_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
OJL_NAME = "Open Justice Licence v2.0"
OJL_URL = "https://caselaw.nationalarchives.gov.uk/open-justice-licence/version/2"

GOVUK_SEARCH_URL = "https://www.gov.uk/api/search.json"
ADM_COLLECTION_URL = "https://www.gov.uk/api/content/government/publications/advice-for-decision-making-staff-guide"
LEGISLATION_SEARCH_URL = "https://www.legislation.gov.uk/all/data.feed"
CASELAW_SEARCH_URL = "https://caselaw.nationalarchives.gov.uk/atom.xml"

ALLOWED_HOSTS = frozenset(
    {
        "www.gov.uk",
        "assets.publishing.service.gov.uk",
        "www.legislation.gov.uk",
        "caselaw.nationalarchives.gov.uk",
    }
)
MAX_DEFAULT_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_TEXT_CHARS = 40_000
MAX_REDIRECTS = 4

MANUAL_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CASE_SLUG = re.compile(
    r"^(?:tna\.[a-z0-9]+|(?:ukut/aac|ewca/civ|uksc)/[0-9]{4}/[0-9]+)$",
    re.IGNORECASE,
)
PROVISION_PATH = re.compile(
    r"^(?:(?:regulation|section|article|rule|schedule|part|chapter|paragraph)/[A-Za-z0-9-]+)"
    r"(?:/(?:regulation|section|article|rule|schedule|part|chapter|paragraph)/[A-Za-z0-9-]+)*$"
)

ORGANISATIONS = {
    "dwp": "department-for-work-pensions",
    "hmrc": "hm-revenue-customs",
}
DOCUMENT_TYPES = frozenset({"ukpga", "uksi", "ukla", "asp", "anaw", "mwa", "nia", "nisi", "ssi", "wsi", "nisr"})
COURTS = frozenset({"ukut/aac", "ewca/civ", "uksc"})


class SourceError(RuntimeError):
    """A safe, source-specific failure suitable for returning as an MCP error."""


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    body: bytes
    headers: httpx.Headers


def _normalise_space(value: str) -> str:
    return " ".join(value.split())


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _header_datetime(headers: httpx.Headers) -> datetime | None:
    value = headers.get("last-modified")
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _https(value: str) -> str:
    return re.sub(r"^http://", "https://", value)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_text(root: Any, local_name: str) -> str:
    for element in root.iter():
        if _local_name(cast(str, element.tag)) == local_name:
            return _normalise_space("".join(element.itertext()))
    return ""


def _first_attribute(root: Any, local_name: str, attribute: str) -> str:
    for element in root.iter():
        if _local_name(cast(str, element.tag)) == local_name:
            value = element.get(attribute, "")
            if value:
                return _normalise_space(value)
    return ""


def _snippet(text: str, query: str, radius: int = 180) -> str:
    folded_text = text.lower()
    index = folded_text.find(query.lower())
    if index < 0:
        return _normalise_space(text[: radius * 2])
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    value = _normalise_space(text[start:end])
    return f"{'…' if start else ''}{value}{'…' if end < len(text) else ''}"


def _bounded_text(value: str) -> tuple[str, bool]:
    value = _normalise_space(value)
    if len(value) <= MAX_TEXT_CHARS:
        return value, False
    return value[:MAX_TEXT_CHARS].rstrip() + "…", True


def _as_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceError(f"{label} returned an unexpected JSON shape")
    return cast(dict[str, Any], value)


def _as_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise SourceError(f"{label} returned an unexpected JSON shape")
    return cast(list[Any], value)


class OfficialHttpClient:
    """Fetch only allowlisted official HTTPS URLs, validating every redirect."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @staticmethod
    def _validate_url(url: httpx.URL) -> None:
        if url.scheme != "https" or url.host not in ALLOWED_HOSTS or url.username or url.password:
            raise SourceError(f"Refused non-official source URL: {url.copy_with(query=None)}")

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
        max_bytes: int = MAX_DEFAULT_BYTES,
    ) -> Fetched:
        current = httpx.URL(url, params=params)
        for _ in range(MAX_REDIRECTS + 1):
            self._validate_url(current)
            request = self._client.build_request("GET", current)
            try:
                response = await self._client.send(request, stream=True, follow_redirects=False)
            except httpx.HTTPError as exc:
                raise SourceError(f"Official source request failed: {type(exc).__name__}") from exc

            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceError("Official source returned a redirect without a location")
                    current = response.url.join(location)
                    continue

                if response.status_code == 404:
                    raise SourceError(f"Official source did not contain the requested record: {response.url}")
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SourceError(f"Official source returned HTTP {response.status_code}: {response.url}") from exc

                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise SourceError(f"Official source response exceeds the {max_bytes} byte limit")

                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise SourceError(f"Official source response exceeds the {max_bytes} byte limit")
                    chunks.append(chunk)
                return Fetched(url=str(response.url), body=b"".join(chunks), headers=response.headers)
            finally:
                await response.aclose()
        raise SourceError(f"Official source exceeded the {MAX_REDIRECTS} redirect limit")


class OfficialSources:
    """Benefits-specific operations over official public sources."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.http = OfficialHttpClient(client)

    @staticmethod
    def _provenance(
        fetched: Fetched,
        *,
        source_name: str,
        authority: Literal["legislation", "case_law", "dwp_guidance", "hmrc_guidance"],
        source_updated_at: datetime | None,
        licence: str = OGL_NAME,
        licence_url: str = OGL_URL,
        caveats: list[str] | None = None,
    ) -> SourceProvenance:
        return SourceProvenance(
            source_name=source_name,
            authority=authority,
            source_url=fetched.url,
            retrieved_at=datetime.now(UTC),
            source_updated_at=source_updated_at or _header_datetime(fetched.headers),
            content_sha256=_sha256(fetched.body),
            licence=licence,
            licence_url=licence_url,
            caveats=caveats or [],
        )

    async def search_guidance(
        self, query: str, organisation: Literal["dwp", "hmrc"], limit: int
    ) -> Evidence[GuidanceSearch]:
        fetched = await self.http.get(
            GOVUK_SEARCH_URL,
            params={"q": query, "filter_organisations": ORGANISATIONS[organisation], "count": limit},
        )
        try:
            payload = _as_dict(json.loads(fetched.body), "GOV.UK Search")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError("GOV.UK Search returned invalid JSON") from exc
        raw_results = _as_list(payload.get("results"), "GOV.UK Search")
        results: list[GuidanceItem] = []
        for raw in raw_results[:limit]:
            item = _as_dict(raw, "GOV.UK Search result")
            title = item.get("title")
            link = item.get("link")
            if not isinstance(title, str) or not isinstance(link, str):
                raise SourceError("GOV.UK Search result omitted its title or link")
            results.append(
                GuidanceItem(
                    title=_normalise_space(title),
                    url=f"https://www.gov.uk{link}" if link.startswith("/") else _https(link),
                    description=_normalise_space(item.get("description", ""))
                    if isinstance(item.get("description", ""), str)
                    else "",
                    document_type=item.get("content_store_document_type", "")
                    if isinstance(item.get("content_store_document_type", ""), str)
                    else "",
                    updated_at=_parse_datetime(item.get("public_timestamp")),
                )
            )
        authority = "dwp_guidance" if organisation == "dwp" else "hmrc_guidance"
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="GOV.UK Search API",
                authority=authority,
                source_updated_at=None,
                caveats=["Search results are official guidance, not legislation, and may change after retrieval."],
            ),
            data=GuidanceSearch(query=query, organisation=organisation, count=len(results), results=results),
        )

    async def _adm_catalogue(self) -> tuple[Fetched, datetime | None, list[AdmDocument]]:
        fetched = await self.http.get(ADM_COLLECTION_URL)
        try:
            payload = _as_dict(json.loads(fetched.body), "DWP ADM collection")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError("DWP ADM collection returned invalid JSON") from exc
        details = _as_dict(payload.get("details"), "DWP ADM collection")
        attachments = _as_list(details.get("attachments"), "DWP ADM collection")
        documents: list[AdmDocument] = []
        for raw in attachments:
            attachment = _as_dict(raw, "DWP ADM attachment")
            title = attachment.get("title")
            url = attachment.get("url")
            content_type = attachment.get("content_type")
            if isinstance(title, str) and isinstance(url, str) and isinstance(content_type, str):
                candidate = httpx.URL(url)
                if candidate.scheme == "https" and candidate.host == "assets.publishing.service.gov.uk":
                    documents.append(AdmDocument(title=_normalise_space(title), url=url, content_type=content_type))
        if not documents:
            raise SourceError("DWP ADM collection contained no official attachments")
        updated = _parse_datetime(payload.get("public_updated_at")) or _parse_datetime(payload.get("updated_at"))
        return fetched, updated, documents

    async def list_adm(self, query: str, limit: int) -> Evidence[AdmCatalogue]:
        fetched, updated, documents = await self._adm_catalogue()
        folded = query.lower().strip()
        matches = [item for item in documents if not folded or folded in item.title.lower()][:limit]
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="DWP Advice for Decision Making collection",
                authority="dwp_guidance",
                source_updated_at=updated,
                caveats=[
                    "ADM is decision-maker guidance, not legislation, and individual PDFs may be updated separately."
                ],
            ),
            data=AdmCatalogue(query=query, count=len(matches), documents=matches),
        )

    async def search_adm(self, document: str, query: str, max_hits: int) -> Evidence[AdmSearch]:
        _, collection_updated, documents = await self._adm_catalogue()
        exact = [item for item in documents if item.title.lower() == document.lower().strip()]
        matches = exact or [item for item in documents if document.lower().strip() in item.title.lower()]
        if not matches:
            raise SourceError("No ADM document title matched; call list_adm_documents first")
        if len(matches) > 1:
            candidates = "; ".join(item.title for item in matches[:8])
            raise SourceError(f"ADM document title is ambiguous; use one exact title. Candidates: {candidates}")
        selected = matches[0]
        fetched = await self.http.get(selected.url, max_bytes=MAX_PDF_BYTES)
        content_type = fetched.headers.get("content-type", "").lower()
        if "pdf" not in content_type and not fetched.body.startswith(b"%PDF-"):
            raise SourceError("The selected ADM attachment was not a PDF")
        try:
            reader = PdfReader(io.BytesIO(fetched.body))
            if reader.is_encrypted:
                raise SourceError("The selected ADM PDF is encrypted")
            hits: list[TextHit] = []
            extracted_any = False
            for page_number, page in enumerate(reader.pages, start=1):
                text = _normalise_space(page.extract_text() or "")
                extracted_any = extracted_any or bool(text)
                offset = 0
                folded = text.lower()
                needle = query.lower()
                while len(hits) < max_hits:
                    index = folded.find(needle, offset)
                    if index < 0:
                        break
                    hits.append(TextHit(locator=f"page {page_number}", excerpt=_snippet(text, query)))
                    offset = index + max(1, len(needle))
                if len(hits) >= max_hits:
                    break
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(f"Could not extract the selected ADM PDF: {type(exc).__name__}") from exc
        if not extracted_any:
            raise SourceError("The selected ADM PDF contained no extractable text")
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="DWP Advice for Decision Making PDF",
                authority="dwp_guidance",
                source_updated_at=_header_datetime(fetched.headers) or collection_updated,
                caveats=[
                    "ADM is DWP staff guidance, not legislation. Verify important conclusions against current law."
                ],
            ),
            data=AdmSearch(
                document=selected,
                query=query,
                pages=len(reader.pages),
                count=len(hits),
                hits=hits,
            ),
        )

    async def get_hmrc_manual(self, manual: str, section: str | None) -> Evidence[HmrcManual]:
        if not MANUAL_SLUG.fullmatch(manual) or (section is not None and not MANUAL_SLUG.fullmatch(section)):
            raise SourceError("HMRC manual and section must be lowercase GOV.UK slugs")
        path = f"hmrc-internal-manuals/{manual}"
        if section:
            path += f"/{section}"
        fetched = await self.http.get(f"https://www.gov.uk/api/content/{path}")
        try:
            payload = _as_dict(json.loads(fetched.body), "HMRC manual")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError("HMRC manual returned invalid JSON") from exc
        details = _as_dict(payload.get("details", {}), "HMRC manual")
        body = details.get("body", "")
        if not isinstance(body, str):
            raise SourceError("HMRC manual returned an unexpected body")
        text, truncated = _bounded_text(BeautifulSoup(body, "html.parser").get_text(" "))
        title = payload.get("title")
        if not isinstance(title, str):
            raise SourceError("HMRC manual omitted its title")
        description = payload.get("description", "")
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="GOV.UK HMRC internal manual",
                authority="hmrc_guidance",
                source_updated_at=_parse_datetime(payload.get("public_updated_at"))
                or _parse_datetime(payload.get("updated_at")),
                caveats=["HMRC manuals describe HMRC practice but do not replace legislation or binding case law."],
            ),
            data=HmrcManual(
                manual=manual,
                section=section,
                title=_normalise_space(title),
                description=_normalise_space(description) if isinstance(description, str) else "",
                text=text,
                truncated=truncated,
            ),
        )

    async def search_legislation(self, query: str, limit: int) -> Evidence[LegislationSearch]:
        fetched = await self.http.get(LEGISLATION_SEARCH_URL, params={"text": query})
        try:
            root = DefusedET.fromstring(fetched.body)
        except Exception as exc:
            raise SourceError("legislation.gov.uk returned invalid XML") from exc
        atom = "{http://www.w3.org/2005/Atom}"
        metadata = "{http://www.legislation.gov.uk/namespaces/metadata}"
        results: list[LegislationItem] = []
        for entry in root.findall(f"{atom}entry")[:limit]:
            title = _normalise_space(entry.findtext(f"{atom}title", default=""))
            identifier = _https(entry.findtext(f"{atom}id", default=""))
            if not title or not identifier:
                raise SourceError("legislation.gov.uk search result omitted its title or identifier")
            canonical = re.sub(r"/id/", "/", identifier, count=1)
            doc_type_element = entry.find(f"{metadata}DocumentMainType")
            year_element = entry.find(f"{metadata}Year")
            number_element = entry.find(f"{metadata}Number")
            year_value = year_element.get("Value") if year_element is not None else None
            number_value = number_element.get("Value") if number_element is not None else None
            results.append(
                LegislationItem(
                    title=title,
                    url=canonical,
                    document_type=doc_type_element.get("Value", "") if doc_type_element is not None else "",
                    year=int(year_value) if year_value and year_value.isdigit() else None,
                    number=number_value,
                    updated_at=_parse_datetime(entry.findtext(f"{atom}updated")),
                    summary=_normalise_space(entry.findtext(f"{atom}summary", default="")),
                )
            )
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="legislation.gov.uk",
                authority="legislation",
                source_updated_at=_parse_datetime(root.findtext(f"{atom}updated")),
                caveats=[
                    "Search results may point to a revised view. Retrieve the provision and specify as_of "
                    "when date matters."
                ],
            ),
            data=LegislationSearch(query=query, count=len(results), results=results),
        )

    async def get_legislation(
        self,
        document_type: str,
        year: int,
        number: str,
        provision: str | None,
        as_of: str | None,
    ) -> Evidence[LegislationProvision]:
        if document_type not in DOCUMENT_TYPES:
            raise SourceError(f"Unsupported legislation document type: {document_type}")
        if not re.fullmatch(r"[0-9]+", number):
            raise SourceError("Legislation number must contain digits only")
        if provision is not None and not PROVISION_PATH.fullmatch(provision.strip("/")):
            raise SourceError("Unsupported legislation provision path")
        if as_of is not None:
            try:
                datetime.strptime(as_of, "%Y-%m-%d")
            except ValueError as exc:
                raise SourceError("as_of must be a real date in YYYY-MM-DD form") from exc
        parts = ["https://www.legislation.gov.uk", document_type, str(year), number]
        if provision:
            parts.extend(provision.strip("/").split("/"))
        if as_of:
            parts.append(as_of)
        url = "/".join(parts) + "/data.xml"
        fetched = await self.http.get(url)
        try:
            root = DefusedET.fromstring(fetched.body)
        except Exception as exc:
            raise SourceError("legislation.gov.uk returned invalid CLML XML") from exc
        title = _first_text(root, "title") or _first_text(root, "Title")
        body_elements = [element for element in root.iter() if _local_name(element.tag) == "Body"]
        target = body_elements[0] if body_elements else root
        text, truncated = _bounded_text(" ".join(target.itertext()))
        if not text:
            raise SourceError("legislation.gov.uk returned no extractable provision text")
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="legislation.gov.uk CLML",
                authority="legislation",
                source_updated_at=_header_datetime(fetched.headers),
                caveats=[
                    "Check the source page for outstanding effects and territorial extent.",
                    "A point-in-time request never falls back silently to the current text.",
                ],
            ),
            data=LegislationProvision(
                document_type=document_type,
                year=year,
                number=number,
                provision=provision.strip("/") if provision else None,
                as_of=as_of,
                title=title,
                text=text,
                truncated=truncated,
            ),
        )

    async def search_case_law(self, query: str, court: str, page: int, limit: int) -> Evidence[CaseLawSearch]:
        if court not in COURTS:
            raise SourceError(f"Unsupported court: {court}")
        fetched = await self.http.get(CASELAW_SEARCH_URL, params={"query": query, "court": court, "page": page})
        try:
            root = DefusedET.fromstring(fetched.body)
        except Exception as exc:
            raise SourceError("Find Case Law returned invalid Atom XML") from exc
        atom = "{http://www.w3.org/2005/Atom}"
        tna = "{https://caselaw.nationalarchives.gov.uk}"
        results: list[CaseLawItem] = []
        for entry in root.findall(f"{atom}entry")[:limit]:
            title = _normalise_space(entry.findtext(f"{atom}title", default=""))
            html_url = ""
            for link in entry.findall(f"{atom}link"):
                if link.get("rel") == "alternate" and not link.get("type"):
                    html_url = _https(link.get("href", ""))
                    break
            identifiers = entry.findall(f"{tna}identifier")
            neutral = next((item for item in identifiers if item.get("type") == "ukncn"), None)
            fallback = next((item for item in identifiers if item.get("type") == "fclid"), None)
            selected = neutral if neutral is not None else fallback
            slug = selected.get("slug", "") if selected is not None else ""
            if not title or not html_url or not CASE_SLUG.fullmatch(slug):
                raise SourceError("Find Case Law result omitted a supported identifier or canonical URL")
            citation_text = _normalise_space("".join(neutral.itertext())) if neutral is not None else None
            author = entry.find(f"{atom}author")
            court_name = author.findtext(f"{atom}name") if author is not None else None
            results.append(
                CaseLawItem(
                    title=title,
                    slug=slug,
                    url=html_url,
                    citation=citation_text,
                    court=_normalise_space(court_name) if court_name else None,
                    handed_down_at=_parse_datetime(entry.findtext(f"{atom}published")),
                    updated_at=_parse_datetime(entry.findtext(f"{atom}updated")),
                )
            )
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="Find Case Law",
                authority="case_law",
                source_updated_at=_parse_datetime(root.findtext(f"{atom}updated")),
                licence=OJL_NAME,
                licence_url=OJL_URL,
                caveats=[
                    "Find Case Law does not contain every relevant historical judgment.",
                    "This tool is for targeted search only; bulk computational analysis requires separate permission.",
                ],
            ),
            data=CaseLawSearch(query=query, court=court, page=page, count=len(results), results=results),
        )

    async def search_case_text(self, slug: str, query: str, max_hits: int) -> Evidence[CaseTextSearch]:
        if not CASE_SLUG.fullmatch(slug):
            raise SourceError("Unsupported Find Case Law slug")
        url = f"https://caselaw.nationalarchives.gov.uk/{slug}/data.xml"
        fetched = await self.http.get(url)
        try:
            root = DefusedET.fromstring(fetched.body)
        except Exception as exc:
            raise SourceError("Find Case Law returned invalid judgment XML") from exc
        title = (
            _first_text(root, "docTitle")
            or _first_text(root, "FRBRname")
            or _first_attribute(root, "FRBRname", "value")
            or slug
        )
        hits: list[TextHit] = []
        for element in root.iter():
            if _local_name(element.tag) != "paragraph":
                continue
            locator = element.get("eId", "")
            if locator and not locator.startswith("para_"):
                continue
            text = _normalise_space("".join(element.itertext()))
            if query.lower() in text.lower():
                hits.append(TextHit(locator=locator or "unnumbered paragraph", excerpt=_snippet(text, query)))
                if len(hits) >= max_hits:
                    break
        return Evidence(
            source=self._provenance(
                fetched,
                source_name="Find Case Law judgment XML",
                authority="case_law",
                source_updated_at=_header_datetime(fetched.headers),
                licence=OJL_NAME,
                licence_url=OJL_URL,
                caveats=[
                    "Read the full judgment and verify later appellate treatment before relying on an excerpt.",
                    "This tool reads one judgment at a time and must not be automated for bulk computational analysis.",
                ],
            ),
            data=CaseTextSearch(slug=slug, title=title, query=query, count=len(hits), hits=hits),
        )
