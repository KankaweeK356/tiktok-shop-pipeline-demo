"""Optional Google Drive snapshot storage for Colab; no auto-mount or deletion.

No shared service account and no external Drive URL are needed. Each Colab user
mounts their own Drive, and only their own demo snapshot area is used.
"""
from __future__ import annotations
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

DRIVE_FOLDER = 'TikTok_Shop_Demo'
MARKER = '_THIS_FOLDER_IS_MANAGED_BY_TIKTOK_DEMO.txt'
CONFIRMATION = 'CLEAR_TIKTOK_SHOP_DEMO'


def _root(my_drive: Path) -> Path:
    my_drive = Path(my_drive).resolve()
    if my_drive.name not in ('MyDrive', 'My Drive'):
        raise ValueError('โปรดระบุ MyDrive ที่ Mount จาก Google Colab โดยตรง')
    return my_drive/DRIVE_FOLDER


def save_to_drive(project_root: Path, my_drive: Path) -> dict:
    """Copy finished main pipeline state to a timestamped Drive snapshot.
    Additional reports, test summaries and performance summary are copied if present.
    Run 2 can later be resumed from *restored* main/ folder if desired.
    """
    project_root=Path(project_root).resolve()
    original=project_root/'output'/'main'
    if not (original/'er1.sqlite').is_file() or not (original/'er2.duckdb').is_file():
        raise FileNotFoundError('ยังไม่มีฐานข้อมูล ER 1/ER 2 — รัน Run 1 ให้สำเร็จก่อนบันทึก Drive')
    base=_root(my_drive)
    base.mkdir(parents=True,exist_ok=True)
    if base.is_symlink():
        raise ValueError('ไม่รองรับโฟลเดอร์ Drive Demo ที่เป็น symbolic link')
    marker=base/MARKER
    if not marker.exists():
        # Never adopt a pre-existing non-empty directory that was not created by this tool.
        if any(base.iterdir()):
            raise ValueError('มีโฟลเดอร์ชื่อ TikTok_Shop_Demo เดิมที่ระบบไม่ได้สร้างไว้ — โปรดตรวจสอบก่อน')
        marker.write_text('Managed snapshots for TikTok Shop educational demo only.\n',encoding='utf-8')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    target=base/'snapshots'/stamp
    target.mkdir(parents=True)
    shutil.copytree(original,target/'main',dirs_exist_ok=False)
    copied=['main/']
    optional={
        'error_recovery.csv':project_root/'output'/'test'/'error_suite_summary.csv',
        'performance.csv':project_root/'output'/'performance'/'performance_summary.csv',
        'github_report_upload.zip':project_root/'output'/'github_report_upload.zip',
    }
    extra=target/'supporting_reports'
    for name,src in optional.items():
        if src.is_file():
            extra.mkdir(exist_ok=True)
            shutil.copy2(src,extra/name)
            copied.append('supporting_reports/'+name)
    meta={'saved_at_utc':stamp,'files':copied,'source':str(original), 'data':'simulated'}
    (target/'manifest.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
    return {'path':str(target),'files':copied}


def clear_drive_outputs(my_drive: Path, confirmation: str) -> dict:
    """Remove only snapshots inside the known demo folder; explicit confirmation required."""
    if confirmation != CONFIRMATION:
        raise ValueError(f'การลบไม่ได้รับการยืนยัน — พิมพ์ {CONFIRMATION} ให้ตรงก่อน')
    base=_root(my_drive)
    if base.is_symlink():
        raise ValueError('ไม่รองรับ symbolic link')
    if not (base/MARKER).is_file():
        raise ValueError('ไม่พบ Marker ของระบบในโฟลเดอร์ Demo — ยกเลิกการลบเพื่อความปลอดภัย')
    snapshots=base/'snapshots'
    if snapshots.is_symlink():
        raise ValueError('ไม่รองรับ symbolic link ของ Snapshots')
    # This never deletes MyDrive or any folder outside <MyDrive>/TikTok_Shop_Demo/snapshots
    count=len(list(snapshots.iterdir())) if snapshots.exists() else 0
    if snapshots.exists():
        shutil.rmtree(snapshots)
    return {'cleared_snapshots':count,'folder_kept':str(base),'deleted_area':str(snapshots)}
