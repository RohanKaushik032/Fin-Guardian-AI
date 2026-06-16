import urllib.request
import json

payload = {
    "account_id": "C_SENDER_TEST_HOLD",
    "recipient_id": "C_RECIPIENT_TEST_HOLD",
    "amount": 2000000.0,
    "transaction_type": "TRANSFER",
    "timestamp": "2026-01-15T12:00:00Z",
    "device_id": "dev_test_device",
    "ip_address": "127.0.0.1",
    "latitude": 12.9716,
    "longitude": 77.5946,
    "account_age_days": 180,
    "account_balance_before": 2100000.0,
    "is_new_recipient": False,
    "sender_tx_count": 0
}

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/transactions/evaluate",
    data=data,
    headers={'Content-Type': 'application/json', 'X-API-Key': 'dev-key-local-only'}
)

try:
    with urllib.request.urlopen(req) as response:
        res_body = response.read().decode('utf-8')
        print("Success! Status code:", response.status)
        print("Response body:")
        print(json.dumps(json.loads(res_body), indent=2))
except Exception as e:
    print("Error occurred:")
    print(e)
