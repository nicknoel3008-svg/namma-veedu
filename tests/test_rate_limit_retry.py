import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from agent_runtime import request_with_backoff, retry_delay


class RateLimitRetryTests(unittest.TestCase):
    def error(self, delay):
        error = type("RateLimitError", (Exception,), {"status_code": 429})()
        error.response = SimpleNamespace(headers={"retry-after": delay})
        return error

    def test_retries_exact_request_and_recovers(self):
        request = Mock(side_effect=[self.error("2"), self.error("3"), "answer"])
        with patch("agent_runtime.time.sleep") as sleep, patch("agent_runtime.time.monotonic", return_value=0):
            self.assertEqual(request_with_backoff(request, 30, [10]), "answer")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 3])
        self.assertEqual(request.call_count, 3)

    def test_long_header_falls_back_immediately(self):
        error = self.error("120")
        request = Mock(side_effect=error)
        with patch("agent_runtime.time.sleep") as sleep, patch("agent_runtime.time.monotonic", return_value=0):
            with self.assertRaises(type(error)):
                request_with_backoff(request, 30, [10])
        sleep.assert_not_called()
        self.assertEqual(retry_delay(error), 120)

    def test_other_errors_are_not_retried(self):
        request = Mock(side_effect=ValueError("test"))
        with self.assertRaises(ValueError):
            request_with_backoff(request, 30, [10])
        self.assertEqual(request.call_count, 1)
