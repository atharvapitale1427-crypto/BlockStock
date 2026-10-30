
import json
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"


def post(path, data):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            print(response.status, response.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode())


# 1. Add material with opening stock
post("/inventory", {
    "name": "Cement",
    "qty": 100,
    "unit": "bags",
    "cost": 350,
    "reorderLevel": 10
})

# 2. Receive 20 more bags
post("/transactions", {
    "type": "IN",
    "material": "Cement",
    "qty": 20,
    "unit": "bags",
    "cost": 350,
    "ref": "INV-TEST-001",
    "supplier": "Test Supplier",
    "approval": "Approved"
})

# 3. Issue 15 bags
post("/transactions", {
    "type": "OUT",
    "material": "Cement",
    "qty": 15,
    "unit": "bags",
    "purpose": "Construction",
    "approval": "Approved"
})

print("\nTest complete. Check /inventory in your browser.")
