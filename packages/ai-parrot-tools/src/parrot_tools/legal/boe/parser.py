"""BOE (Boletin Oficial del Estado) consolidated-legislation XML parser.

Turns one BOE "legislacion consolidada" open-data API response into flat,
dict-serialisable records: one norma record, N articulo records each
carrying a fully-built ``versions[]`` list, and the ``modifica``/``deroga``
relations declared in the norm's analisis metadata and per-article version
history.

Verified against the real BOE open-data API (``legislacion-consolidada``
endpoint) response shape for three norms during this task's Codebase
Contract verification — see TASK-2372's Completion Note for the
segmentation finding this docstring's structure is based on:

    <response>
      <data>
        <metadatos>
          <identificador>BOE-A-...</identificador>
          <rango codigo="...">Ley</rango>
          <fecha_disposicion>YYYYMMDD</fecha_disposicion>
          <titulo>...</titulo>
          <fecha_publicacion>YYYYMMDD</fecha_publicacion>
        </metadatos>
        <analisis>
          <referencias>
            <anteriores>
              <anterior>
                <id_norma>BOE-A-...</id_norma>
                <relacion codigo="210">DEROGA</relacion>
                <texto>...</texto>
              </anterior>
            </anteriores>
            <posteriores>...</posteriores>
          </referencias>
        </analisis>
        <texto>
          <bloque id="a50" tipo="precepto" titulo="Articulo 50">
            <version id_norma="BOE-A-..." fecha_publicacion="YYYYMMDD"
                     fecha_vigencia="YYYYMMDD">
              <p class="articulo">Articulo 50. ...</p>
              <p class="parrafo">...</p>
              <blockquote>
                <p class="nota_pie">Se modifica ... <a class="refPost">Ref. ...</a></p>
              </blockquote>
            </version>
          </bloque>
        </texto>
      </data>
    </response>

Tolerant: on parse failure, the error is collected in ``ParsedNorm.errors``
— never a silently empty record.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from itertools import pairwise
from xml.etree import ElementTree as ET

from parrot_tools.legal.ids import article_key, is_valid_boe_id, normalize_boe_id

from .models import ArticleVersion, ParsedNorm

logger = logging.getLogger(__name__)

# codigo attribute values on <relacion> for the analisis/referencias links.
_DEROGA_CODIGO = "210"

# nota_pie annotation keyword patterns used to classify a version's kind.
_SUPRESION_RE = re.compile(r"suprim", re.IGNORECASE)
_ADICION_RE = re.compile(r"a[ñn]ad", re.IGNORECASE)

# "Articulo N" / "Art. N" prefix, stripped to obtain the bare designator.
_ARTICULO_PREFIX_RE = re.compile(r"^art[íi]culo\s+", re.IGNORECASE)


class _BloqueParseError(Exception):
    """Raised internally when a <bloque> cannot be parsed into an articulo record."""


def parse_consolidated(xml: str | bytes) -> ParsedNorm:
    """Parse one BOE consolidated-legislation XML document.

    Args:
        xml: The raw XML document body, as returned by the BOE datos
            abiertos ``legislacion-consolidada`` API with
            ``Accept: application/xml``.

    Returns:
        A ``ParsedNorm`` with the norma record, articulo records (each
        with a fully-built ``versions[]`` list), ``modifica``/``deroga``
        relations, and any parse errors. Never raises — structural
        problems are reported via ``ParsedNorm.errors``.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return ParsedNorm(errors=[f"Invalid XML: {exc}"])

    data_el = root.find("data")
    metadatos_el = data_el.find("metadatos") if data_el is not None else None
    texto_el = data_el.find("texto") if data_el is not None else None

    if data_el is None or metadatos_el is None or texto_el is None:
        return ParsedNorm(
            errors=[
                "Malformed BOE consolidated document: missing <data>/<metadatos> or <texto>"
            ]
        )

    raw_boe_id = (metadatos_el.findtext("identificador") or "").strip()
    try:
        boe_id = normalize_boe_id(raw_boe_id)
    except ValueError as exc:
        return ParsedNorm(errors=[f"Invalid norma identifier {raw_boe_id!r}: {exc}"])

    norma = _parse_norma(metadatos_el, boe_id)

    articulos: list[dict] = []
    errors: list[str] = []
    for bloque_el in texto_el.findall("bloque"):
        if bloque_el.get("tipo") != "precepto":
            continue
        try:
            articulos.append(_parse_bloque(bloque_el, boe_id))
        except _BloqueParseError as exc:
            errors.append(str(exc))

    relations = _extract_deroga_relations(data_el, boe_id)
    relations.extend(_extract_modifica_relations(articulos))

    return ParsedNorm(norma=norma, articulos=articulos, relations=relations, errors=errors)


def _parse_fecha(raw: str | None) -> date | None:
    """Parse a BOE ``YYYYMMDD`` date string into a ``date``."""
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    try:
        return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return None


def _iso(value: date | None) -> str | None:
    """Serialise a date as an ISO ``YYYY-MM-DD`` string, or None."""
    return value.isoformat() if value else None


def _parse_norma(metadatos_el: ET.Element, boe_id: str) -> dict:
    """Build the flat norma record from <metadatos>."""
    rango_el = metadatos_el.find("rango")
    rango = rango_el.text.strip() if rango_el is not None and rango_el.text else None
    return {
        "boe_id": boe_id,
        "titulo": (metadatos_el.findtext("titulo") or "").strip() or None,
        "rango": rango,
        "fecha_disposicion": _iso(_parse_fecha(metadatos_el.findtext("fecha_disposicion"))),
        "fecha_publicacion": _iso(_parse_fecha(metadatos_el.findtext("fecha_publicacion"))),
    }


def _extract_numero(titulo: str) -> str:
    """Strip the leading 'Articulo ' prefix to obtain the bare designator."""
    return _ARTICULO_PREFIX_RE.sub("", titulo).strip()


def _extract_notas(version_el: ET.Element) -> list[str]:
    """Collect nota_pie annotation texts for a <version>, in document order."""
    return [
        (p.text or "").strip()
        for p in version_el.findall("./blockquote/p[@class='nota_pie']")
        if (p.text or "").strip()
    ]


def _extract_body_text(version_el: ET.Element) -> str | None:
    """Concatenate the non-annotation <p> elements of a <version>."""
    paragraphs = [
        (p.text or "").strip()
        for p in version_el.findall("p")
        if p.get("class") != "nota_pie" and (p.text or "").strip()
    ]
    if not paragraphs:
        return None
    return "\n".join(paragraphs)


def _classify_kind(notas: list[str]) -> str:
    """Classify a version's kind from its nota_pie annotation text(s).

    The first (most recent) nota_pie for a version conventionally
    describes what changed in that version. Falls back to "redaccion"
    (a wording change) when no adicion/supresion keyword is present.
    """
    for text in notas:
        if _SUPRESION_RE.search(text):
            return "supresion"
        if _ADICION_RE.search(text):
            return "adicion"
    return "redaccion"


def _parse_bloque(bloque_el: ET.Element, norma_boe_id: str) -> dict:
    """Parse one <bloque tipo="precepto"> into an articulo record.

    Raises:
        _BloqueParseError: If the bloque has no title/id, no <version>
            elements, or a version is missing its fecha_vigencia.
    """
    titulo = (bloque_el.get("titulo") or "").strip()
    numero = _extract_numero(titulo) if titulo else (bloque_el.get("id") or "").strip()
    if not numero:
        raise _BloqueParseError(f"Bloque '{bloque_el.get('id')}' has no titulo/id")

    version_els = bloque_el.findall("version")
    if not version_els:
        raise _BloqueParseError(f"Bloque '{numero}' has no <version> elements")

    versions: list[ArticleVersion] = []
    for idx, version_el in enumerate(version_els):
        valid_from = _parse_fecha(version_el.get("fecha_vigencia"))
        if valid_from is None:
            raise _BloqueParseError(
                f"Bloque '{numero}' version {idx} is missing fecha_vigencia"
            )

        if idx == 0:
            kind = "redaccion"
            modified_by = None
        else:
            notas = _extract_notas(version_el)
            kind = _classify_kind(notas)
            modified_by = version_el.get("id_norma")

        text = None if kind == "supresion" else _extract_body_text(version_el)

        versions.append(
            ArticleVersion(
                n=idx,
                text=text,
                valid_from=valid_from,
                valid_to=None,  # chained below
                modified_by=modified_by,
                kind=kind,
                source="boe_consolidada",
                derived=False,
            )
        )

    # Chain valid_to: version[k].valid_to = version[k+1].valid_from (exclusive
    # upper bound); the last version is currently in force (valid_to=None).
    for current, following in pairwise(versions):
        current.valid_to = following.valid_from
    versions[-1].valid_to = None

    return {
        "articulo_key": article_key(norma_boe_id, numero),
        "norma_ref": norma_boe_id,
        "numero": numero,
        "versions": [v.model_dump(mode="json") for v in versions],
    }


def _extract_deroga_relations(data_el: ET.Element, norma_boe_id: str) -> list[dict]:
    """Extract deroga (Norma -> Norma) relations from analisis/referencias.

    Only 'anteriores' entries are used: this norma is the acting subject
    ("this norma DEROGA prior_norma"). The symmetric edge for a later
    norma that derogates THIS one is created when that later norma is
    itself ingested and its own 'anteriores' section is parsed.
    """
    relations: list[dict] = []
    for entry in data_el.findall("analisis/referencias/anteriores/anterior"):
        relacion_el = entry.find("relacion")
        if relacion_el is None or relacion_el.get("codigo") != _DEROGA_CODIGO:
            continue
        target_raw = (entry.findtext("id_norma") or "").strip()
        if not is_valid_boe_id(target_raw):
            continue
        relations.append(
            {
                "type": "deroga",
                "from": norma_boe_id,
                "to": normalize_boe_id(target_raw),
            }
        )
    return relations


def _extract_modifica_relations(articulos: list[dict]) -> list[dict]:
    """Extract modifica (Norma -> Articulo) relations from per-version id_norma.

    Each non-original version (n >= 1) records which norma amended that
    specific article — the article-level granularity the ontology's
    `modifica` relation requires, which the coarser norma-level analisis
    metadata alone cannot provide.
    """
    relations: list[dict] = []
    for articulo in articulos:
        for version in articulo["versions"]:
            amending = version.get("modified_by")
            if not amending or not is_valid_boe_id(amending):
                continue
            relations.append(
                {
                    "type": "modifica",
                    "from": normalize_boe_id(amending),
                    "to": articulo["articulo_key"],
                }
            )
    return relations
