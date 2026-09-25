"""Build a SYNTHETIC BBVA-like movements workbook (no real data)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import openpyxl

HEADER = ["Fecha", "F.Valor", "Concepto", "Movimiento", "Importe", "Divisa", "Disponible", "Observaciones"]


def build_bbva_workbook(path: Path, *, extra_rows: int = 0) -> Path:
    """Write the fixture to ``path`` and return it. ``extra_rows`` appends synthetic debits (load tests)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Movimientos"

    # 6 preamble rows before the movements table (holder, account, period, blanks) — invented data only.
    ws.append(["Titular: ACME TEST"])
    ws.append(["Cuenta: ES00 0000 0000 0000 0000 0000"])
    ws.append(["Periodo: 01/09/2026 - 30/09/2026"])
    ws.append([])
    ws.append([])
    ws.append([])

    ws.append(HEADER)

    # 5 synthetic debits.
    ws.append([dt.date(2026, 9, 1), dt.date(2026, 9, 1), "CUOTA RETA", "PAGO", -294.00, "EUR", 1500.00, ""])
    ws.append([dt.date(2026, 9, 2), dt.date(2026, 9, 2), "MOVISTAR", "RECIBO", "-45,50", "EUR", 1454.50, ""])
    ws.append([dt.date(2026, 9, 3), dt.date(2026, 9, 3), "REPSOL", "COMPRA TARJETA", -60.00, "EUR", 1394.50, ""])
    ws.append([dt.date(2026, 9, 4), dt.date(2026, 9, 4), "RESTAURANTE", "COMPRA TARJETA", -18.90, "EUR", 1375.60, ""])
    ws.append(
        [dt.date(2026, 9, 5), dt.date(2026, 9, 5), "TRASPASO A CUENTA PROPIA", "TRASPASO", -500.00, "EUR", 875.60, ""]
    )

    # 2 synthetic credits (skipped by the parser).
    ws.append(
        [dt.date(2026, 9, 6), dt.date(2026, 9, 6), "NOMINA TEST EMPRESA", "TRANSFERENCIA", 1500.00, "EUR", 2375.60, ""]
    )
    ws.append([dt.date(2026, 9, 7), dt.date(2026, 9, 7), "DEVOLUCION COMPRA", "ABONO", 25.00, "EUR", 2400.60, ""])

    for offset in range(extra_rows):
        day = 8 + offset
        ws.append(
            [
                dt.date(2026, 9, day),
                dt.date(2026, 9, day),
                f"EXTRA GASTO {offset}",
                "COMPRA TARJETA",
                -10.00 - offset,
                "EUR",
                2400.60 - (10.00 + offset),
                "",
            ]
        )

    wb.save(path)
    return path
