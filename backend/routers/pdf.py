from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from services import search_service

router = APIRouter()


@router.get("/api/pdf/{year}/{case_id}")
async def download_pdf(
    year: int,
    case_id: str,
    download: int = Query(0, description="1 = force save dialog, 0 = open inline"),
):
    case_data = search_service.load_case_json(case_id, year)
    if not case_data:
        raise HTTPException(status_code=404, detail="Case not found")

    pdf_path_str = case_data.get("pdf_path") or ""
    if not pdf_path_str:
        raise HTTPException(status_code=404, detail="No PDF available for this case")

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF missing on disk: {pdf_path.name}")

    citation = (case_data.get("case_id") or "judgment").replace(" ", "_").replace("/", "-")
    filename = f"{citation}.pdf"
    disposition = "attachment" if download else "inline"

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
