"""Confirm Prometheus has loaded alerting rules."""
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    response = json.load(handle)

assert response["status"] == "success"
assert any(group["rules"] for group in response["data"]["groups"])
print("Prometheus alert rules loaded")
