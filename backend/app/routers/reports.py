"""Weekly reports as clients see them: the list, one report, and its PDF. (Reports are made by the weekly job.)"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app.config import WebsiteConfig
from app.deps import DbSession, require_feature
from app.models import Client, Report, Website
from app.reports.service import render_report_pdf, report_dict

router = APIRouter(prefix="/api/websites/{website_id}/reports", tags=["reports"])

# The report pages need the plan to include "weekly_reports" (admins always pass).
ReportsAccess = Annotated[WebsiteConfig, Depends(require_feature("weekly_reports"))]


def _find(db, site: WebsiteConfig, report_id: uuid.UUID) -> Report:
    report = db.get(Report, report_id)
    if report is None or str(report.website_id) != site.website_id:  # a report of another website is simply "not found"
        raise HTTPException(status_code=404, detail="Report not found.")
    return report


@router.get("", summary="This website's weekly reports, newest first")
def list_reports(site: ReportsAccess, db: DbSession):
    website = db.get(Website, uuid.UUID(site.website_id))
    client = db.get(Client, website.client_id)
    reports = db.scalars(select(Report).where(Report.website_id == website.id).order_by(Report.period_end.desc()).limit(104)).all()
    return {"results": [report_dict(r, website_name=website.name, client_name=client.name, with_data=False) for r in reports]}


@router.get("/{report_id}", summary="One report with all its numbers")
def get_report(report_id: uuid.UUID, site: ReportsAccess, db: DbSession):
    report = _find(db, site, report_id)
    website = db.get(Website, report.website_id)
    return report_dict(report, website_name=website.name, client_name=db.get(Client, report.client_id).name)


@router.get("/{report_id}/pdf", summary="A report as a PDF")
def report_pdf(report_id: uuid.UUID, site: ReportsAccess, db: DbSession):
    report = _find(db, site, report_id)
    return Response(
        content=render_report_pdf(db, report),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="weekly-report-{report.period_end.isoformat()}.pdf"'},
    )
