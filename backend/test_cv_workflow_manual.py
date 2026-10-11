import io
import time
import zipfile
import pypdf
import docx
from PIL import Image, ImageDraw
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def create_sample_text_pdf() -> bytes:
    """Creates a valid text PDF with standard Helvetica font."""
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 210 >>\nstream\n"
        b"BT\n"
        b"/F1 14 Tf\n"
        b"50 700 Td\n"
        b"(ALEX KUMAR - SENIOR FRONTEND ENGINEER) Tj\n"
        b"0 -30 Td\n"
        b"(EXPERIENCE: 5 years in React, TypeScript, and Fullstack architecture.) Tj\n"
        b"0 -30 Td\n"
        b"(EDUCATION: Bachelor of Science in Computer Science, 2022) Tj\n"
        b"0 -30 Td\n"
        b"(SKILLS: React, Next.js, Node.js, Python, System Design) Tj\n"
        b"ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000507 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n585\n%%EOF"
    )
    return pdf_content


def create_encrypted_pdf() -> bytes:
    """Creates a password-protected encrypted PDF."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret_password")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_scanned_pdf() -> bytes:
    """Creates a PDF with an image containing drawn text simulating a scanned document."""
    img = Image.new('RGB', (600, 800), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50, 50), "SCANNED RESUME\nJOHN DOE\nSOFTWARE ENGINEER", fill=(0, 0, 0))
    
    buf = io.BytesIO()
    img.save(buf, format='PDF')
    return buf.getvalue()


def create_sample_docx() -> bytes:
    """Creates a valid DOCX with headings and tables."""
    doc = docx.Document()
    doc.add_heading("SARAH CONNOR - FULLSTACK DEVELOPER", level=0)
    
    p = doc.add_paragraph("SUMMARY: Experienced engineer building distributed systems.")
    
    doc.add_heading("WORK EXPERIENCE", level=1)
    doc.add_paragraph("Senior Engineer at Tech Corp (2021 - Present)")
    doc.add_paragraph("Designed high-throughput APIs using FastAPI and Python.")
    
    # Add a table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Level"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "Expert"

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


import unittest


class TestCVWorkflow(unittest.TestCase):
    def test_cv_workflow(self):
        print("--- Starting Phase 1.3 CV Tests ---")

    # 1. Authenticate user
    signup_data = {
        "name": "CV Test User",
        "email": "cv.tester@example.com",
        "password": "Password123!"
    }
    signup_res = client.post("/auth/signup", json=signup_data)
    if signup_res.status_code == 201:
        token = signup_res.json()["access_token"]
    else:
        login_res = client.post("/auth/login", json={"email": signup_data["email"], "password": signup_data["password"]})
        token = login_res.json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Test: Empty file -> UNREADABLE
    res_empty = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    print("Test 1 (Empty file):", res_empty.status_code, res_empty.json())
    assert res_empty.status_code == 400
    assert res_empty.json()["error_code"] == "UNREADABLE"

    # 3. Test: Oversized file (> 5 MB) -> TOO_LARGE
    oversized_bytes = b"%PDF-" + b"0" * (5 * 1024 * 1024 + 100)
    res_large = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("large.pdf", oversized_bytes, "application/pdf")}
    )
    print("Test 2 (Oversized file):", res_large.status_code, res_large.json())
    assert res_large.status_code == 400
    assert res_large.json()["error_code"] == "TOO_LARGE"

    # 4. Test: Wrong file type (e.g. .txt or .png) -> UNSUPPORTED_TYPE
    res_wrong = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("cv.txt", b"Hello text resume", "text/plain")}
    )
    print("Test 3 (Wrong extension):", res_wrong.status_code, res_wrong.json())
    assert res_wrong.status_code == 400
    assert res_wrong.json()["error_code"] == "UNSUPPORTED_TYPE"

    # 5. Test: Password-protected encrypted PDF -> ENCRYPTED
    encrypted_bytes = create_encrypted_pdf()
    res_enc = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("protected.pdf", encrypted_bytes, "application/pdf")}
    )
    print("Test 4 (Encrypted PDF):", res_enc.status_code, res_enc.json())
    assert res_enc.status_code == 400
    assert res_enc.json()["error_code"] == "ENCRYPTED"

    # 6. Test: Valid DOCX upload & text extraction
    docx_bytes = create_sample_docx()
    res_docx = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("resume.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    print("Test 5 (Valid DOCX Upload):", res_docx.status_code, res_docx.json())
    assert res_docx.status_code == 201
    docx_id = res_docx.json()["id"]

    # Poll status for DOCX
    time.sleep(0.5)
    st_docx = client.get(f"/cv/{docx_id}/status", headers=headers).json()
    print("DOCX extraction status:", st_docx["status"], "Text length:", st_docx.get("text_length"))
    assert st_docx["status"] in ("uploaded", "extracting", "extracted")
    if st_docx["status"] == "extracted":
        assert "SARAH CONNOR" in st_docx["raw_text"]
        assert "Python" in st_docx["raw_text"]

    # 7. Test: Valid Text PDF upload & text extraction
    pdf_bytes = create_sample_text_pdf()
    res_pdf = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("resume.pdf", pdf_bytes, "application/pdf")}
    )
    print("Test 6 (Valid PDF Upload):", res_pdf.status_code, res_pdf.json())
    assert res_pdf.status_code == 201
    pdf_id = res_pdf.json()["id"]

    # 8. Test: Scanned image PDF upload & extraction
    scanned_bytes = create_scanned_pdf()
    res_scan = client.post(
        "/cv/upload",
        headers=headers,
        files={"file": ("scanned.pdf", scanned_bytes, "application/pdf")}
    )
    print("Test 7 (Scanned PDF Upload):", res_scan.status_code, res_scan.json())
    assert res_scan.status_code == 201
    scan_id = res_scan.json()["id"]

    # 9. Verify GET /cv/latest
    latest_cv = client.get("/cv/latest", headers=headers)
    assert latest_cv.status_code == 200
    print("Latest CV filename:", latest_cv.json()["filename"])

    print("\nALL PHASE 1.3 BACKEND TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_cv_workflow()
