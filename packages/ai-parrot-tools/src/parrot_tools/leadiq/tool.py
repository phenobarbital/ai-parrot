"""
LeadIQToolkit - Agent-usable toolkit for the LeadIQ GraphQL API.

Ports the GraphQL query logic and response transforms from flowtask's
``LeadIQ`` ETL component
(``flowtask/components/LeadIQ.py``) into an ``AbstractToolkit`` exposing
three discrete tools:

- ``search_company``   -> structured company information (single company)
- ``search_employees`` -> people grouped under a company
- ``search_flat``      -> flat list of people at a company

Unlike the flowtask component, this toolkit does NOT inherit ``HTTPService``
(no ``FlowComponent`` coupling, no pandas DataFrame return). Transport is a
composed ``HTTPService`` member, and every tool returns a structured
``ToolResult``.
"""
import json
from typing import Any, Callable, Dict, List, Optional
from navconfig import config
from pydantic import Field
from parrot.interfaces.http import HTTPService
from ..abstract import AbstractToolArgsSchema, ToolResult
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema


class LeadIQSearchInput(AbstractToolArgsSchema):
    """Input schema shared by all LeadIQ search tools."""
    company_name: str = Field(
        ..., description="Company name to search for on LeadIQ"
    )
    limit: int = Field(
        100,
        ge=1,
        le=100,
        description="Max people to return (employees/flat searches)",
    )


class LeadIQToolkit(AbstractToolkit):
    """
    Toolkit for querying the LeadIQ GraphQL API for company and people data.

    Each public async method is automatically converted into a tool by
    ``AbstractToolkit`` (prefixed with ``leadiq_``). Methods:

    1. Resolve ``LEADIQ_API_KEY`` (already Base64-encoded) and build the
       ``Authorization: Basic <key>`` header.
    2. Build the GraphQL payload from the ported query constant + variables.
    3. POST to ``https://api.leadiq.com/graphql`` via the composed
       ``HTTPService`` member.
    4. Flatten the response using the ported ``_process_*_response``
       transforms.
    5. Return a structured ``ToolResult``.
    """

    tool_prefix: str = "leadiq"
    base_url: str = "https://api.leadiq.com"

    # ===========================
    # GraphQL Queries (ported verbatim from flowtask LeadIQ.py)
    # ===========================

    COMPANY_SEARCH_QUERY = """
    query SearchCompany($input: SearchCompanyInput!) {
        searchCompany(input: $input) {
            totalResults
            hasMore
            results {
                source
                name
                alternativeNames
                domain
                description
                emailDomains
                type
                phones
                country
                address
                locationInfo {
                    formattedAddress
                    street1
                    street2
                    city
                    areaLevel1
                    country
                    postalCode
                }
                logoUrl
                linkedinId
                linkedinUrl
                numberOfEmployees
                industry
                specialities
                fundingInfo {
                    fundingRounds
                    fundingTotalUsd
                    lastFundingOn
                    lastFundingType
                    lastFundingUsd
                }
                technologies {
                    name
                    category
                    parentCategory
                }
                revenue
                revenueRange {
                    start
                    end
                    description
                }
                sicCode {
                    code
                    description
                }
                naicsCode {
                    code
                    description
                }
                employeeRange
                foundedYear
            }
        }
    }
    """

    EMPLOYEE_SEARCH_QUERY = """
    query GroupedAdvancedSearch($input: GroupedSearchInput!) {
        groupedAdvancedSearch(input: $input) {
            totalCompanies
            companies {
                company {
                    id
                    name
                    industry
                    companyDescription: description
                    linkedinId
                    domain
                    employeeCount
                    city
                    country
                    state
                    postalCode
                    score
                    companyTechnologies
                    companyTechnologyCategories
                    revenueRange {
                        ...RevenueRangeFragment
                    }
                    fundingInfo {
                        ...FundingInfoFragment
                    }
                    naicsCode {
                        ...NAICSCodeFragment
                    }
                }
                people {
                    id
                    companyId
                    name
                    linkedinId
                    linkedinUrl
                    title
                    role
                    state
                    country
                    seniority
                    workEmails
                    verifiedWorkEmails
                    verifiedLikelyWorkEmails
                    workPhones
                    personalEmails
                    personalPhones
                    score
                    firstName
                    middleName
                    lastName
                    updatedAt
                    currentPositionStartDate
                    company {
                        id
                        name
                        industry
                        companyDescription: description
                        linkedinId
                        domain
                        employeeCount
                        city
                        country
                        state
                        postalCode
                        score
                        companyTechnologies
                        companyTechnologyCategories
                        revenueRange {
                            ...RevenueRangeFragment
                        }
                        fundingInfo {
                            ...FundingInfoFragment
                        }
                        naicsCode {
                            ...NAICSCodeFragment
                        }
                    }
                    picture
                }
                totalContactsInCompany
            }
        }
    }

    fragment RevenueRangeFragment on RevenueRange {
        start
        end
        description
    }

    fragment FundingInfoFragment on FundingInfo {
        fundingRounds
        fundingTotalUsd
        lastFundingOn
        lastFundingType
        lastFundingUsd
    }

    fragment NAICSCodeFragment on NAICSCode {
        code
        naicsDescription: description
    }
    """

    FLAT_SEARCH_QUERY = """
    query FlatAdvancedSearch($input: FlatSearchInput!) {
        flatAdvancedSearch(input: $input) {
            totalPeople
            people {
                id
                companyId
                name
                linkedinId
                linkedinUrl
                title
                role
                state
                country
                seniority
                workEmails
                verifiedWorkEmails
                verifiedLikelyWorkEmails
                workPhones
                personalEmails
                personalPhones
                score
                firstName
                middleName
                lastName
                updatedAt
                currentPositionStartDate
                company {
                    id
                    name
                    industry
                    companyDescription: description
                    linkedinId
                    domain
                    employeeCount
                    city
                    country
                    state
                    postalCode
                    score
                    companyTechnologies
                    companyTechnologyCategories
                    revenueRange {
                        ...RevenueRangeFragment
                    }
                    fundingInfo {
                        ...FundingInfoFragment
                    }
                    naicsCode {
                        ...NAICSCodeFragment
                    }
                }
                picture
            }
        }
    }

    fragment RevenueRangeFragment on RevenueRange {
        start
        end
        description
    }

    fragment FundingInfoFragment on FundingInfo {
        fundingRounds
        fundingTotalUsd
        lastFundingOn
        lastFundingType
        lastFundingUsd
    }

    fragment NAICSCodeFragment on NAICSCode {
        code
        naicsDescription: description
    }
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """
        Initialize the LeadIQToolkit.

        Args:
            api_key: LeadIQ API key (already Base64-encoded). If not
                provided, resolved lazily per-call from the
                ``LEADIQ_API_KEY`` environment variable via ``navconfig``.
            **kwargs: Additional arguments passed to ``AbstractToolkit``
                and the composed ``HTTPService``.
        """
        super().__init__(**kwargs)
        self._api_key = api_key
        # NOTE: HTTPService itself has no concept of `base_url` (it never
        # reads that kwarg) — the toolkit builds full URLs from its own
        # `self.base_url` class attribute in `_execute_query`. Only
        # `accept` and any HTTPService-specific kwargs are meaningful here.
        self.http = HTTPService(accept="application/json", **kwargs)

    # ===========================
    # Internal helpers
    # ===========================

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the LeadIQ API key.

        Prefers the key passed explicitly to ``__init__``; falls back to
        ``navconfig`` ``config.get("LEADIQ_API_KEY")``. Centralized so the
        key is looked up consistently (and only via this single path) by
        both the up-front "is it configured" check in each tool method and
        by ``_build_headers()``.
        """
        return self._api_key or config.get("LEADIQ_API_KEY")

    def _build_headers(self) -> Dict[str, str]:
        """Build the LeadIQ auth/content headers.

        The API key is already Base64-encoded — it is injected verbatim
        into the ``Authorization`` header, never re-encoded.
        """
        api_key = self._resolve_api_key()
        return {
            "Authorization": f"Basic {api_key}",
            "Content-Type": "application/json",
            "apollo-require-preflight": "true",
        }

    async def _execute_query(
        self, payload: Dict[str, Any], company_name: str
    ) -> Optional[Dict[str, Any]]:
        """Execute a GraphQL query against the LeadIQ API and return the raw dict.

        Returns ``None`` on transport error (logged, never raised).
        """
        headers = self._build_headers()
        self.logger.info("Searching LeadIQ for company: %s", company_name)

        result, error = await self.http.session(
            url=self.base_url + "/graphql",
            method="post",
            data=json.dumps(payload),
            headers=headers,
        )

        if error:
            self.logger.error(
                "Error searching LeadIQ for %s: %s", company_name, error
            )
            return None

        return result

    def _process_company_response(
        self, result: dict, company_name: str
    ) -> Optional[Dict[str, Any]]:
        """Process company search response (ported verbatim from flowtask LeadIQ.py)."""
        if "data" in result and "searchCompany" in result["data"]:
            search_data = result["data"]["searchCompany"]

            if search_data["results"]:
                company_data = search_data["results"][0]  # Tomamos el primer resultado

                # Crear un diccionario con los datos procesados
                processed_data = {
                    "search_term": company_name,  # Término de búsqueda original
                    "found": True,
                    "total_results": search_data["totalResults"],
                    "name": company_data["name"],
                    "domain": company_data["domain"],
                    "industry": company_data["industry"],
                    "country": company_data["country"],
                    "address": company_data["address"],
                    "linkedin_id": company_data["linkedinId"],
                    "linkedin_url": company_data["linkedinUrl"],
                    "employee_count": company_data["numberOfEmployees"],
                    "employee_range": company_data["employeeRange"],
                    "founded_year": company_data["foundedYear"],
                }

                # Procesar locationInfo
                if loc := company_data.get("locationInfo"):
                    processed_data.update({
                        "street": loc.get("street1"),
                        "city": loc.get("city"),
                        "state": loc.get("areaLevel1"),
                        "postal_code": loc.get("postalCode")
                    })

                # Procesar NAICS
                if naics := company_data.get("naicsCode"):
                    processed_data.update({
                        "naics_code": naics["code"],
                        "naics_description": naics["description"]
                    })

                # Procesar technologies como listas
                if techs := company_data.get("technologies"):
                    tech_names = []
                    tech_categories = []
                    for tech in techs:
                        if tech.get("name"):
                            tech_names.append(tech["name"])
                        if tech.get("category"):
                            tech_categories.append(tech["category"])

                    processed_data.update({
                        "technologies": tech_names,
                        "tech_categories": list(set(tech_categories))  # Eliminar duplicados
                    })

                # Procesar specialities si existe
                if specs := company_data.get("specialities"):
                    processed_data["specialities"] = specs

                return processed_data
            else:
                # Si no se encontraron resultados
                return {
                    "search_term": company_name,
                    "found": False,
                    "total_results": 0
                }

        self.logger.warning("Unexpected response structure for %s", company_name)
        return None

    def _process_employee_response(
        self, result: dict, company_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Process employee search response (ported verbatim from flowtask LeadIQ.py)."""
        if "data" in result and "groupedAdvancedSearch" in result["data"]:
            search_data = result["data"]["groupedAdvancedSearch"]

            if search_data["companies"]:
                company_data = search_data["companies"][0]
                company_info = company_data["company"]
                employees = company_data["people"]

                # Extraer solo la información básica de la empresa
                basic_company_info = {
                    "company_id": company_info["id"],
                    "company_name": company_info["name"],
                    "company_industry": company_info["industry"],
                    "company_domain": company_info["domain"],
                    "company_employee_count": company_info["employeeCount"],
                    "company_city": company_info["city"],
                    "company_country": company_info["country"],
                    "company_state": company_info["state"]
                }

                # Crear una fila por cada empleado
                processed_rows = []
                for employee in employees:
                    # Remover la información duplicada de la empresa del empleado
                    employee_copy = employee.copy()
                    employee_copy.pop('company', None)  # Eliminar la información duplicada de la empresa

                    # Combinar información básica de la empresa con datos del empleado
                    row = {
                        **basic_company_info,
                        **employee_copy
                    }
                    processed_rows.append(row)

                return processed_rows

            self.logger.warning("No company data found for %s", company_name)
        else:
            self.logger.warning("Unexpected response structure for %s", company_name)

        return None

    def _process_flat_response(
        self, result: dict, company_name: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Process flat search response (ported verbatim from flowtask LeadIQ.py)."""
        if "data" in result and "flatAdvancedSearch" in result["data"]:
            search_data = result["data"]["flatAdvancedSearch"]

            if search_data["people"]:
                processed_rows = []
                for person in search_data["people"]:
                    # Extraer información básica de la empresa
                    company_info = person.pop('company', {})
                    basic_company_info = {
                        "company_id": company_info.get("id"),
                        "company_name": company_info.get("name"),
                        "company_industry": company_info.get("industry"),
                        "company_domain": company_info.get("domain"),
                        "company_employee_count": company_info.get("employeeCount"),
                        "company_city": company_info.get("city"),
                        "company_country": company_info.get("country"),
                        "company_state": company_info.get("state")
                    }

                    # Combinar información de la empresa con datos del empleado
                    row = {
                        **basic_company_info,
                        **person
                    }
                    processed_rows.append(row)

                return processed_rows

            self.logger.warning("No people found for %s", company_name)
        else:
            self.logger.warning("Unexpected response structure for %s", company_name)

        return None

    # ===========================
    # Shared search pipeline
    # ===========================

    async def _run_search(
        self,
        *,
        search_type: str,
        query: str,
        variables: Dict[str, Any],
        company_name: str,
        process_fn: Callable[[dict, str], Any],
        result_kind: str,
    ) -> ToolResult:
        """Shared execute-query -> process -> ``ToolResult`` pipeline.

        Used by all three ``search_*`` tools so the API-key guard,
        transport-error handling, and exception-to-``ToolResult`` mapping
        live in exactly one place.

        Args:
            search_type: Value recorded in ``metadata["search_type"]``
                (``"company"``, ``"employees"``, or ``"flat"``).
            query: The GraphQL query constant to send.
            variables: The GraphQL ``variables`` payload for this query.
            company_name: Original search term, for logging/error messages.
            process_fn: One of ``_process_company_response``,
                ``_process_employee_response``, ``_process_flat_response`` —
                flattens the raw GraphQL dict, or returns ``None`` on an
                unexpected/empty shape (see ``result_kind`` handling below).
            result_kind: ``"single"`` for ``search_company`` (result is a
                dict, or an error ``ToolResult`` when ``process_fn`` returns
                ``None``), or ``"list"`` for ``search_employees``/
                ``search_flat`` (result is always a list — ``None`` from
                ``process_fn`` becomes an empty list flagged
                ``metadata["ambiguous_empty"]``, ported verbatim from
                flowtask, which conflates "nothing found" with "unexpected
                response shape").

        Returns:
            A structured ``ToolResult`` — never raises.
        """
        api_key = self._resolve_api_key()
        if not api_key:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error="LEADIQ_API_KEY not configured",
            )

        payload = {"query": query, "variables": variables}

        try:
            result = await self._execute_query(payload, company_name)
            processed = (
                process_fn(result, company_name) if result is not None else None
            )
        except Exception as e:  # noqa: BLE001 - never raise unhandled from a tool
            self.logger.error(
                "Error in %s search for %s: %s", search_type, company_name, e
            )
            return ToolResult(
                success=False, status="error", result=None, error=str(e)
            )

        if result is None:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"LeadIQ {search_type} search failed for {company_name}",
            )

        if result_kind == "single":
            if processed is None:
                return ToolResult(
                    success=False,
                    status="error",
                    result=None,
                    error=f"Unexpected LeadIQ response structure for {company_name}",
                )
            count = 1 if processed.get("found") else 0
            return ToolResult(
                success=True,
                status="success",
                result=processed,
                metadata={
                    "search_type": search_type,
                    "count": count,
                    "source": "LeadIQ",
                },
            )

        # result_kind == "list"
        rows = processed if processed is not None else []
        metadata = {
            "search_type": search_type,
            "count": len(rows),
            "source": "LeadIQ",
        }
        if processed is None:
            # `_process_employee_response`/`_process_flat_response` return
            # None both when LeadIQ genuinely found nothing and when the
            # response shape was unexpected (ported verbatim from flowtask,
            # which conflates the two). Flag it so downstream
            # consumers/observability can tell an empty result apart from a
            # possible upstream contract break, without treating it as a
            # hard error.
            metadata["ambiguous_empty"] = True
        return ToolResult(
            success=True,
            status="success",
            result=rows,
            metadata=metadata,
        )

    # ===========================
    # Tools
    # ===========================

    @tool_schema(LeadIQSearchInput)
    async def search_company(self, company_name: str, **kwargs) -> ToolResult:
        """Search LeadIQ for a company and return structured company information."""
        return await self._run_search(
            search_type="company",
            query=self.COMPANY_SEARCH_QUERY,
            variables={"input": {"name": company_name}},
            company_name=company_name,
            process_fn=self._process_company_response,
            result_kind="single",
        )

    @tool_schema(LeadIQSearchInput)
    async def search_employees(
        self, company_name: str, limit: int = 100, **kwargs
    ) -> ToolResult:
        """Search LeadIQ for employees grouped under a company."""
        return await self._run_search(
            search_type="employees",
            query=self.EMPLOYEE_SEARCH_QUERY,
            variables={
                "input": {
                    "companyFilter": {"names": company_name},
                    "limit": limit,
                }
            },
            company_name=company_name,
            process_fn=self._process_employee_response,
            result_kind="list",
        )

    @tool_schema(LeadIQSearchInput)
    async def search_flat(
        self, company_name: str, limit: int = 100, **kwargs
    ) -> ToolResult:
        """Flat search LeadIQ for people at a company (one record per person)."""
        return await self._run_search(
            search_type="flat",
            query=self.FLAT_SEARCH_QUERY,
            variables={
                "input": {
                    "companyFilter": {"names": company_name},
                    "limit": limit,
                }
            },
            company_name=company_name,
            process_fn=self._process_flat_response,
            result_kind="list",
        )
