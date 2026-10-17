import httpx
import json

client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=90.0)

print("=== STARTING FRESH LIVE SESSION ===")
r1 = client.post("/api/coach/sessions", json={"user_id": 13, "problem_id": 1})
assert r1.status_code == 201, f"Create session failed: {r1.text}"
session_data = r1.json()
session_id = session_data["id"]
print(f"Session ID created: {session_id}")

print("\n=== TURN 2: Student responds to L0 Diagnostic ===")
payload2 = {
    "user_message": (
        "I understand the interactive rules: the array is hidden, N <= 2e5, and we are allowed up to 2e5 queries. "
        "Each query ? l r returns the sum in that range. We cannot inspect elements directly. "
        "Because elements are non-negative, queried prefix values are monotonically non-decreasing."
    ),
    "request_escalation": False
}
r2 = client.post(f"/api/coach/sessions/{session_id}/message", json=payload2)
assert r2.status_code == 200, f"Turn 2 failed: {r2.text}"
print(f"Turn 2 status: {r2.status_code}, current_level: {r2.json()['current_level']}")

print("\n=== TURN 3: Student requests escalation to L2 ===")
payload3 = {
    "user_message": "I see the monotonicity. What standard algorithm paradigm fits this? Please give me the next level hint.",
    "request_escalation": True
}
r3 = client.post(f"/api/coach/sessions/{session_id}/message", json=payload3)
assert r3.status_code == 200, f"Turn 3 failed: {r3.text}"
print(f"Turn 3 status: {r3.status_code}, current_level: {r3.json()['current_level']}")

print("\n=== TURN 4: Student requests escalation to L3 ===")
payload4 = {
    "user_message": "I understand that we divide into halves and test which half holds the condition, but how do we recurse and combine? Please give me the next level hint.",
    "request_escalation": True
}
r4 = client.post(f"/api/coach/sessions/{session_id}/message", json=payload4)
assert r4.status_code == 200, f"Turn 4 failed: {r4.text}"
print(f"Turn 4 status: {r4.status_code}, current_level: {r4.json()['current_level']}")

print(f"\n=== LIVE TEST TURNS FINISHED FOR SESSION {session_id} ===")
