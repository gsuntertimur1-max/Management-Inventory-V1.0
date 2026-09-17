from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.server import db, require_master_write
from backend.integrity_lots import integrity_control as base_integrity_control

router = APIRouter(prefix="/api")


@router.get("/integrity-control")
async def integrity_control(user: dict = Depends(require_master_write)):
    data = await base_integrity_control(user)
    open_issues = await db.operational_postcommit_issues.find(
        {"status": "OPEN"},
        {"_id": 0},
    ).sort("updatedAt", -1).to_list(1000)

    if open_issues:
        issues = list(data.get("systemIssues") or [])
        issues.append({
            "severity": "ERROR",
            "code": "POSTCOMMIT_REPAIR_REQUIRED",
            "message": f"Ada {len(open_issues)} proses selesai yang membutuhkan repair metadata/Surat Jalan/FEFO.",
        })
        data["systemIssues"] = issues

    data["postCommitRepairIssues"] = open_issues
    summary = dict(data.get("summary") or {})
    summary["postCommitRepairIssues"] = len(open_issues)
    summary["systemErrors"] = sum(1 for issue in data.get("systemIssues", []) if str(issue.get("severity") or "") == "ERROR")
    summary["systemWarnings"] = sum(1 for issue in data.get("systemIssues", []) if str(issue.get("severity") or "") == "WARNING")
    data["summary"] = summary
    return data
