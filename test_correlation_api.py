import requests
import json

url = "http://127.0.0.1:8050/api/analyze"
payload = {
    "stock_ids": ["2002.TW", "2330.TW"],
    "metal": "Copper",
    "start_date": "2023-01-01",
    "end_date": "2023-12-31"
}

try:
    print(f"Sending request to {url}...")
    response = requests.post(url, json=payload)
    print(f"Status Code: {response.status_code}")
    print("Response Body:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
