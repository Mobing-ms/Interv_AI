from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

client = TestClient(app)

def test_profile_endpoints():
    # 1. Create a test user and get access token
    signup_data = {
        "name": "Alex Profile Tester",
        "email": "alex.profile@example.com",
        "password": "Password123!"
    }
    signup_res = client.post("/auth/signup", json=signup_data)
    if signup_res.status_code == 400:
        login_res = client.post("/auth/login", json={"email": signup_data["email"], "password": signup_data["password"]})
        token = login_res.json()["access_token"]
    else:
        token = signup_res.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check initial onboarding status
    status_res = client.get("/profile/status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["current_step"] in (1, 2, 3)

    # 3. Test invalid education (CGPA > scale)
    bad_edu = {
        "degree": "Bachelor of Technology",
        "branch": "Computer Science",
        "college": "Tech Institute",
        "graduation_year": 2026,
        "cgpa": 11.5,
        "cgpa_scale": 10.0
    }
    res_bad = client.put("/profile/education", json=bad_edu, headers=headers)
    assert res_bad.status_code == 422, "Should reject CGPA > scale"

    # 4. Save valid education profile
    good_edu = {
        "degree": "Bachelor's degree",
        "branch": "Computer Science",
        "college": "MIT",
        "graduation_year": 2026,
        "cgpa": 8.9,
        "cgpa_scale": 10.0
    }
    res_edu = client.put("/profile/education", json=good_edu, headers=headers)
    assert res_edu.status_code == 200, res_edu.text
    edu_data = res_edu.json()
    assert edu_data["degree"] == "Bachelor's degree"
    assert edu_data["cgpa"] == 8.9

    # 5. Get saved education profile
    get_edu = client.get("/profile/education", headers=headers)
    assert get_edu.status_code == 200
    assert get_edu.json()["college"] == "MIT"

    # 6. Check status progressed to step 2 (education_done)
    status_res2 = client.get("/profile/status", headers=headers)
    assert status_res2.status_code == 200
    assert status_res2.json()["education_done"] is True

    # 7. Test invalid target profile (invalid company type)
    bad_target = {
        "target_role": "Frontend Engineer",
        "company_type": "UnknownCorp",
        "experience_level": "Fresher"
    }
    res_bad_target = client.put("/profile/target", json=bad_target, headers=headers)
    assert res_bad_target.status_code == 422

    # 8. Save valid target profile
    good_target = {
        "target_role": "Frontend Engineer",
        "company_type": "Product",
        "experience_level": "Fresher",
        "job_description": "Building scalable React apps"
    }
    res_target = client.put("/profile/target", json=good_target, headers=headers)
    assert res_target.status_code == 200, res_target.text
    target_data = res_target.json()
    assert target_data["target_role"] == "Frontend Engineer"
    assert target_data["company_type"] == "Product"

    # 9. Get saved target profile
    get_target = client.get("/profile/target", headers=headers)
    assert get_target.status_code == 200
    assert get_target.json()["target_role"] == "Frontend Engineer"

    # 10. Get suggestions
    suggestions = client.get("/profile/target/suggestions")
    assert suggestions.status_code == 200
    assert "Frontend Engineer" in suggestions.json()["suggestions"]

    # 11. Final status check (target_done -> current_step == 3)
    final_status = client.get("/profile/status", headers=headers)
    assert final_status.status_code == 200
    assert final_status.json()["target_done"] is True
    assert final_status.json()["current_step"] == 3

    print("All profile backend tests passed successfully!")

if __name__ == "__main__":
    test_profile_endpoints()
