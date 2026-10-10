import io
import time
import httpx
import docx
from PIL import Image, ImageDraw
import pypdf

base = "http://127.0.0.1:8000"

def create_sample_text_pdf() -> bytes:
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

def create_scanned_pdf() -> bytes:
    img = Image.new('RGB', (600, 800), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((50, 50), "SCANNED RESUME\nMICHAEL BROWN\nDEVOPS ENGINEER", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PDF')
    return buf.getvalue()

def create_sample_docx() -> bytes:
    doc = docx.Document()
    doc.add_heading("SARAH CONNOR - FULLSTACK DEVELOPER", level=0)
    doc.add_paragraph("SUMMARY: Experienced engineer building distributed systems.")
    doc.add_heading("WORK EXPERIENCE", level=1)
    doc.add_paragraph("Senior Engineer at Tech Corp (2021 - Present)")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Level"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "Expert"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()

def create_encrypted_pdf() -> bytes:
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("mypassword")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

def run_tests():
    print("--- Starting Phase 1.3 Live End-to-End Acceptance Tests ---")

    # 1. Authenticate user
    user_email = "phase1.3.tester@example.com"
    signup_res = httpx.post(f"{base}/auth/signup", json={
        "name": "Phase1.3 Tester",
        "email": user_email,
        "password": "Password123!"
    })
    if signup_res.status_code == 201:
        token = signup_res.json()["access_token"]
    else:
        login_res = httpx.post(f"{base}/auth/login", json={"email": user_email, "password": "Password123!"})
        token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Failure Path 1: Oversized file (> 5 MB) -> TOO_LARGE
    oversized = b"%PDF-" + b"0" * (5 * 1024 * 1024 + 50)
    r_large = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("oversized.pdf", oversized, "application/pdf")}
    )
    print("Failure Path 1 (TOO_LARGE):", r_large.status_code, r_large.json())
    assert r_large.status_code == 400
    assert r_large.json()["error_code"] == "TOO_LARGE"

    # 3. Failure Path 2: Wrong type (.txt) -> UNSUPPORTED_TYPE
    r_type = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("notes.txt", b"plain text resume", "text/plain")}
    )
    print("Failure Path 2 (UNSUPPORTED_TYPE):", r_type.status_code, r_type.json())
    assert r_type.status_code == 400
    assert r_type.json()["error_code"] == "UNSUPPORTED_TYPE"

    # 4. Failure Path 3: Empty file -> UNREADABLE
    r_empty = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    print("Failure Path 3 (UNREADABLE):", r_empty.status_code, r_empty.json())
    assert r_empty.status_code == 400
    assert r_empty.json()["error_code"] == "UNREADABLE"

    # 5. Failure Path 4: Password-protected encrypted PDF -> ENCRYPTED
    r_enc = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("locked.pdf", create_encrypted_pdf(), "application/pdf")}
    )
    print("Failure Path 4 (ENCRYPTED):", r_enc.status_code, r_enc.json())
    assert r_enc.status_code == 400
    assert r_enc.json()["error_code"] == "ENCRYPTED"

    # 6. Success Path 1: Text PDF
    r_pdf = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("resume.pdf", create_sample_text_pdf(), "application/pdf")}
    )
    print("Success Path 1 (Text PDF Upload):", r_pdf.status_code, r_pdf.json())
    assert r_pdf.status_code == 201
    pdf_id = r_pdf.json()["id"]

    # Poll status
    time.sleep(1)
    st_pdf = httpx.get(f"{base}/cv/{pdf_id}/status", headers=headers).json()
    print("Text PDF Status:", st_pdf["status"], "Text length:", st_pdf.get("text_length"))
    assert st_pdf["status"] in ("uploaded", "extracting", "extracted")

    # 7. Success Path 2: DOCX
    r_docx = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("resume.docx", create_sample_docx(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    print("Success Path 2 (DOCX Upload):", r_docx.status_code, r_docx.json())
    assert r_docx.status_code == 201
    docx_id = r_docx.json()["id"]

    time.sleep(1)
    st_docx = httpx.get(f"{base}/cv/{docx_id}/status", headers=headers).json()
    print("DOCX Status:", st_docx["status"], "Text length:", st_docx.get("text_length"))
    assert st_docx["status"] in ("uploaded", "extracting", "extracted")
    if st_docx["status"] == "extracted":
        assert "SARAH CONNOR" in st_docx["raw_text"]

    # 8. Success Path 3: Scanned PDF
    r_scan = httpx.post(
        f"{base}/cv/upload",
        headers=headers,
        files={"file": ("scanned_resume.pdf", create_scanned_pdf(), "application/pdf")}
    )
    print("Success Path 3 (Scanned PDF Upload):", r_scan.status_code, r_scan.json())
    assert r_scan.status_code == 201

    print("\nALL PHASE 1.3 LIVE ACCEPTANCE TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
