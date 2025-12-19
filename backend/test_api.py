import requests
import json

url = "http://127.0.0.1:8000/compare"

payload = {
    "old_text": "We collect your email address.",
    "new_text": "We collect your email address and phone number.",
    "mode": "semantic",
    "max_changes": 5
}

r = requests.post(url, json=payload)
print("Status:", r.status_code)
print(json.dumps(r.json(), indent=2))
