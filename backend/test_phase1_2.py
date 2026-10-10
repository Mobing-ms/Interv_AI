import httpx

base = "http://127.0.0.1:8000"

def run_tests():
    print("--- Starting Phase 1.2 End-to-End Test ---")

    # 1. Sign up a new user
    user_email = "onboarding.tester@example.com"
    signup_res = httpx.post(f"{base}/auth/signup", json={
        "name": "Onboarding Tester",
        "email": user_email,
        "password": "Password123!"
    })
    if signup_res.status_code == 201:
        tokens = signup_res.json()
    else:
        login_res = httpx.post(f"{base}/auth/login", json={"email": user_email, "password": "Password123!"})
        tokens = login_res.json()

    access_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    print("1. User authenticated. Initial onboarding_status:", tokens["user"].get("onboarding_status"))

    # 2. Check initial status
    st1 = httpx.get(f"{base}/profile/status", headers=headers).json()
    print("2. Current step before education:", st1["current_step"])

    # 3. Test invalid education (CGPA > 10 on 10.0 scale)
    bad_edu = httpx.put(f"{base}/profile/education", headers=headers, json={
        "degree": "Bachelor's degree",
        "branch": "Computer Science",
        "college": "MIT",
        "graduation_year": 2026,
        "cgpa": 11.5,
        "cgpa_scale": 10.0
    })
    print("3. Invalid CGPA rejected with status:", bad_edu.status_code)
    assert bad_edu.status_code == 422

    # 4. Save valid education profile
    good_edu = httpx.put(f"{base}/profile/education", headers=headers, json={
        "degree": "Bachelor's degree",
        "branch": "Computer Science",
        "college": "Stanford University",
        "graduation_year": 2026,
        "cgpa": 9.2,
        "cgpa_scale": 10.0
    })
    print("4. Valid education saved:", good_edu.status_code, good_edu.json()["college"])
    assert good_edu.status_code == 200

    # 5. Logout and login to test persistence & resume logic
    httpx.post(f"{base}/auth/logout")
    login_after_edu = httpx.post(f"{base}/auth/login", json={"email": user_email, "password": "Password123!"}).json()
    new_headers = {"Authorization": f"Bearer {login_after_edu['access_token']}"}

    st2 = httpx.get(f"{base}/profile/status", headers=new_headers).json()
    print("5. Onboarding resumed after relogin at step:", st2["current_step"], "(Status:", st2["onboarding_status"], ")")
    assert st2["current_step"] == 2
    assert st2["education_done"] is True

    # Check prefill for education
    prefill_edu = httpx.get(f"{base}/profile/education", headers=new_headers).json()
    assert prefill_edu["college"] == "Stanford University"
    assert prefill_edu["cgpa"] == 9.2
    print("6. Prefill verified: Education profile restored correctly.")

    # 7. Test invalid target profile
    bad_target = httpx.put(f"{base}/profile/target", headers=new_headers, json={
        "target_role": "Backend Engineer",
        "company_type": "InvalidType",
        "experience_level": "Fresher"
    })
    print("7. Invalid company type rejected with status:", bad_target.status_code)
    assert bad_target.status_code == 422

    # 8. Save valid target profile
    good_target = httpx.put(f"{base}/profile/target", headers=new_headers, json={
        "target_role": "Fullstack Engineer",
        "company_type": "Product",
        "experience_level": "0-2",
        "job_description": "Building fullstack TypeScript and Python apps"
    })
    print("8. Valid target profile saved:", good_target.status_code, good_target.json()["target_role"])
    assert good_target.status_code == 200

    # 9. Logout and login again to verify target resume logic
    httpx.post(f"{base}/auth/logout")
    login_after_target = httpx.post(f"{base}/auth/login", json={"email": user_email, "password": "Password123!"}).json()
    new_headers2 = {"Authorization": f"Bearer {login_after_target['access_token']}"}

    st3 = httpx.get(f"{base}/profile/status", headers=new_headers2).json()
    print("9. Onboarding resumed after relogin at step:", st3["current_step"], "(Status:", st3["onboarding_status"], ")")
    assert st3["current_step"] == 3
    assert st3["target_done"] is True

    # Check prefill for target
    prefill_target = httpx.get(f"{base}/profile/target", headers=new_headers2).json()
    assert prefill_target["target_role"] == "Fullstack Engineer"
    assert prefill_target["experience_level"] == "0-2"
    print("10. Prefill verified: Target profile restored correctly.")

    print("\nALL PHASE 1.2 ACCEPTANCE TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
