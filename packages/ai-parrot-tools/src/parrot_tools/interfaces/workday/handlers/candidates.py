# candidate_type.py

from typing import Dict, Any, List
import asyncio
import math
import pandas as pd

from ..models.candidate import Candidate
from ..parsers.candidate_parsers import (
    parse_candidate_reference,
    parse_candidate_personal_data,
    parse_candidate_contact_data,
    parse_candidate_recruitment_data,   # opcional: campos "planos" de 1 postulación
    parse_candidate_status_data,
    parse_candidate_prospect_data,
    parse_candidate_education_data,
    parse_candidate_experience_data,
    parse_candidate_skills_data,
    parse_candidate_language_data,
    parse_candidate_document_data,
    parse_candidate_applications,        # << NUEVO: TODAS las postulaciones
)
from ..utils import safe_serialize
from .base import WorkdayTypeBase


class CandidateType(WorkdayTypeBase):
    """
    Handler para la operación Get_Candidates del Workday Recruiting API (v45.0).
    Devuelve información de candidatos en el pipeline de recruiting.
    """

    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Payload por defecto para Get_Candidates.

        Nota: Adjuntos incluidos por defecto (CVs), Include_Reference=True.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Exclude_All_Attachments": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Ejecuta Get_Candidates y devuelve un DataFrame.

        Args (opcional):
            candidate_id: ID específico de candidato
            job_requisition_id: filtrar por requisición
            applied_from_date: filtrar aplicaciones desde fecha
            applied_to_date: filtrar aplicaciones hasta fecha
            created_from_date: filtrar creados desde fecha
            created_to_date: filtrar creados hasta fecha
            pdf_directory: ruta base donde guardar PDFs (si hay adjuntos)
            exclude_all_attachments: excluir todos los adjuntos (CVs, etc.) por defecto False
        """
        candidate_id = kwargs.pop("candidate_id", None)
        job_requisition_id = kwargs.pop("job_requisition_id", None)
        applied_from_date = kwargs.pop("applied_from_date", None)
        applied_to_date = kwargs.pop("applied_to_date", None)
        created_from_date = kwargs.pop("created_from_date", None)
        created_to_date = kwargs.pop("created_to_date", None)
        pdf_directory = kwargs.pop("pdf_directory", None)
        exclude_all_attachments = kwargs.pop("exclude_all_attachments", False)

        if pdf_directory:
            self._logger.info(f"📁 PDFs will be saved to: {pdf_directory}")

        payload = {**self.request_payload}

        # Update Exclude_All_Attachments based on parameter
        if "Response_Group" not in payload:
            payload["Response_Group"] = {}
        payload["Response_Group"]["Exclude_All_Attachments"] = exclude_all_attachments

        # Construcción de Request_References / Request_Criteria
        if candidate_id:
            payload["Request_References"] = {
                "Candidate_Reference": [
                    {
                        "ID": [
                            {"_value_1": candidate_id, "type": "Candidate_ID"}
                        ]
                    }
                ]
            }
            self._logger.info(f"Fetching specific candidate: {candidate_id}")
        else:
            criteria: Dict[str, Any] = {}

            if job_requisition_id:
                criteria["Job_Requisition_Reference"] = [
                    {
                        "ID": [
                            {
                                "_value_1": job_requisition_id,
                                "type": "Job_Requisition_ID",
                            }
                        ]
                    }
                ]

            # Rangos de fechas de aplicación
            if applied_from_date:
                criteria["Applied_From"] = applied_from_date

            if applied_to_date:
                criteria["Applied_Through"] = applied_to_date

            # Rangos de fechas de creación
            if created_from_date:
                criteria["Created_From"] = created_from_date
            if created_to_date:
                criteria["Created_Through"] = created_to_date

            if criteria:
                payload["Request_Criteria"] = criteria

            self._logger.info("Fetching all candidates")

        # Llamadas y paginación
        try:
            if candidate_id:
                # Sin paginación para un candidato específico
                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._logger.info(
                            f"📡 Fetching candidate {candidate_id} (attempt {attempt}/{self.max_retries})..."
                        )
                        response = await self.service.call_operation(
                            operation="Get_Candidates", **payload
                        )
                        self._logger.info(f"✅ Successfully fetched candidate {candidate_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Candidates] Error fetching candidate {candidate_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Candidates] Failed to fetch candidate {candidate_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data", {})
                if "Candidate" in response_data:
                    candidate_data = response_data["Candidate"]
                    candidates_raw = [candidate_data] if isinstance(candidate_data, dict) else candidate_data
                else:
                    candidates_raw = []

                self._logger.info(f"Retrieved {len(candidates_raw)} candidate(s)")
            else:
                # Paginado para traer todos los candidatos
                self._logger.info("🔍 Fetching first page to determine totals...")

                first_payload = {
                    **payload,
                    "Response_Filter": {
                        **payload.get("Response_Filter", {}),
                        "Page": 1,
                        "Count": 100,
                    },
                }

                raw1 = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._logger.info(f"📡 Attempting to fetch first page (attempt {attempt}/{self.max_retries})...")
                        raw1 = await self.service.call_operation(operation="Get_Candidates", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Candidates] Error on first page (attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Candidates] Failed first page after {self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                data1 = self.service.serialize_object(raw1)

                page1 = data1.get("Response_Data", {}).get("Candidate", [])
                if isinstance(page1, dict):
                    page1 = [page1]

                results = data1.get("Response_Results", {})
                total_pages = int(float(results.get("Total_Pages", 1)))
                total_results = int(float(results.get("Total_Results", 0)))
                page_results = int(float(results.get("Page_Results", 0)))

                self._logger.info(
                    f"📊 Pagination: Total={total_results}, Pages={total_pages}, PageSize={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} candidates")

                all_candidates: List[dict] = list(page1)

                # Si hay más páginas, traer en batches
                max_parallel = 10
                if total_pages > 1:
                    pages = list(range(2, total_pages + 1))
                    num_batches = math.ceil(len(pages) / max_parallel)
                    batches = self.service.split_parts(pages, num_parts=num_batches)

                    for batch in batches:
                        self._logger.info(f"🔄 Processing batch of {len(batch)} pages: {batch}")
                        tasks = [self._fetch_candidate_page(p, payload) for p in batch]
                        results_list = await asyncio.gather(*tasks, return_exceptions=True)
                        for res in results_list:
                            if isinstance(res, Exception):
                                self._logger.error(f"❌ Error fetching page: {res}")
                            else:
                                all_candidates.extend(res)

                        self._logger.info(
                            f"✅ Progress: {len(all_candidates)}/{total_results} candidates "
                            f"({(len(all_candidates)/total_results*100 if total_results else 0):.1f}%)"
                        )

                candidates_raw = all_candidates
                self._logger.info(
                    f"✨ Completed: {len(candidates_raw)} candidates retrieved (Expected: {total_results})"
                )
                self.service.add_metric("EXPECTED_CANDIDATES", total_results)
                self.service.add_metric("TOTAL_PAGES", total_pages)
                if total_results and len(candidates_raw) != total_results:
                    self._logger.warning(
                        f"⚠️ Mismatch: Expected {total_results} but got {len(candidates_raw)}"
                    )

        except Exception as e:
            self._logger.error(f"Error fetching candidates: {e}")
            import traceback
            self._logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        # Parseo -> Pydantic -> DataFrame
        parsed: List[Candidate] = []
        for candidate_raw in candidates_raw:
            try:
                candidate_data = candidate_raw.get("Candidate_Data", {}) if isinstance(candidate_raw, dict) else {}

                # Referencias primero (para candidate_id -> guardar PDFs)
                reference_data = parse_candidate_reference(candidate_raw, candidate_data)
                current_candidate_id = reference_data.get("candidate_id")

                record: Dict[str, Any] = {
                    **reference_data,
                    **parse_candidate_personal_data(candidate_data),
                    **parse_candidate_contact_data(candidate_data),

                    # TODAS las postulaciones
                    **parse_candidate_applications(candidate_data),

                    # Opcional: mantener campos "planos" de reclutamiento
                    **parse_candidate_recruitment_data(candidate_data),

                    **parse_candidate_status_data(candidate_data),
                    **parse_candidate_prospect_data(candidate_data),
                    **parse_candidate_education_data(candidate_data),
                    **parse_candidate_experience_data(candidate_data),
                    **parse_candidate_skills_data(candidate_data),
                    **parse_candidate_language_data(candidate_data),
                    **parse_candidate_document_data(candidate_data, current_candidate_id, pdf_directory),
                }

                parsed.append(Candidate(**record))

            except Exception as e:
                self._logger.warning(f"Error parsing candidate: {e}")
                import traceback
                self._logger.warning(f"Traceback: {traceback.format_exc()}")
                continue

        if parsed:
            df = pd.DataFrame([c.dict() for c in parsed])

            # Serializar columnas complejas (listas y dicts) a JSON para PostgreSQL JSONB
            complex_cols = [
                "emails", "phones", "schools", "degrees", "education_history", "previous_employers",
                "work_experience", "skills", "competencies",
                "languages", "documents", "applications", "attachments",
                # agrega aquí más listas cuando integres más parsers
            ]
            for col in complex_cols:
                if col in df.columns:
                    df[col] = df[col].apply(safe_serialize)

            self.service.add_metric("NUM_CANDIDATES", len(parsed))
            self._logger.info(f"Successfully parsed {len(parsed)} candidates")
            return df
        else:
            self._logger.warning("No candidates found or processed successfully")
            return pd.DataFrame(
                columns=[
                    "candidate_id",
                    "candidate_wid",
                    "first_name",
                    "last_name",
                    "email",
                    "candidate_status",
                    "job_requisition_id",
                ]
            )

    async def _fetch_candidate_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Trae una página de Get_Candidates. Devuelve la lista de dicts 'Candidate'.
        """
        self._logger.debug(f"📄 Starting fetch for page {page_num}")

        payload = {
            **base_payload,
            "Response_Filter": {
                **base_payload.get("Response_Filter", {}),
                "Page": page_num,
                "Count": 100,
            },
        }

        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_Candidates", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Candidates] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Candidates] Failed page {page_num} after {self.max_retries} attempts."
                    )
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        data = self.service.serialize_object(raw)
        items = data.get("Response_Data", {}).get("Candidate", [])
        if isinstance(items, dict):
            items = [items]

        self._logger.debug(f"✅ Page {page_num} completed: {len(items) if items else 0} candidates fetched")
        return items or []
