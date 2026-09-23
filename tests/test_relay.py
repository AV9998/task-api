import unittest

from app.relay import alert_text


class RelayTest(unittest.TestCase):
    def test_alertmanager_event_becomes_email_text(self):
        result = alert_text({"status": "firing", "alerts": [{"labels": {"alertname": "TaskApiDown", "severity": "critical"}, "annotations": {"summary": "API unavailable"}}]})
        self.assertIn("TaskApiDown (critical): API unavailable", result)
        self.assertIn("FIRING", result)


if __name__ == "__main__":
    unittest.main()
