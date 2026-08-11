import unittest
import json
import time
import concurrent.futures
import requests

BASE_URL = "http://127.0.0.1:8899"

class TestAntigravityBridge(unittest.TestCase):

    def test_01_health_check(self):
        resp = requests.get(f"{BASE_URL}/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("mode"), "antigravity-local-daemon")
        self.assertIsNotNone(data.get("daemon_pid"))
        self.assertIsNotNone(data.get("daemon_port"))

    def test_02_list_models(self):
        resp = requests.get(f"{BASE_URL}/v1/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("object"), "list")
        model_ids = [m["id"] for m in data.get("data", [])]
        self.assertIn("antigravity", model_ids)
        self.assertIn("gemini-3.6-flash", model_ids)
        self.assertIn("gemini-3.1-pro", model_ids)

    def test_03_non_streaming_chat(self):
        payload = {
            "model": "gemini-3.6-flash",
            "messages": [
                {"role": "system", "content": "You are a helpful coding assistant."},
                {"role": "user", "content": "Respond with the word SUCCESS."}
            ],
            "stream": False
        }
        resp = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("object"), "chat.completion")
        self.assertEqual(data.get("model"), "Gemini 3.6 Flash")
        content = data["choices"][0]["message"]["content"]
        self.assertTrue(len(content) > 0)
        self.assertIn("token_estimation_note", data["usage"])

    def test_04_streaming_chat(self):
        payload = {
            "model": "gemini-3.1-pro",
            "messages": [
                {"role": "user", "content": "Say Hello World."}
            ],
            "stream": True
        }
        resp = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, stream=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue("text/event-stream" in resp.headers.get("Content-Type", ""))
        
        lines = [line.decode('utf-8') for line in resp.iter_lines() if line]
        self.assertTrue(any("data: [DONE]" in l for l in lines))
        self.assertTrue(any("chat.completion.chunk" in l for l in lines))

    def test_05_multi_turn_messages(self):
        payload = {
            "model": "gemini-3.6-flash",
            "messages": [
                {"role": "system", "content": "You are a test bot."},
                {"role": "user", "content": "My favorite color is Blue."},
                {"role": "assistant", "content": "Got it! Your favorite color is Blue."},
                {"role": "user", "content": "What is my favorite color?"}
            ],
            "stream": False
        }
        resp = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 200)
        content = resp.json()["choices"][0]["message"]["content"]
        self.assertIn("Blue", content)

    def test_06_concurrency(self):
        def send_req(i):
            payload = {
                "model": "gemini-3.6-flash",
                "messages": [{"role": "user", "content": f"Req #{i}: Return 'ACK_{i}'."}]
            }
            res = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload, timeout=20)
            return res.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(send_req, i) for i in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertEqual(results, [200] * 5)

    def test_07_payload_safety_limit(self):
        huge_prompt = "x" * 2500000 # 2.5MB > 2MB limit
        payload = {
            "model": "gemini-3.6-flash",
            "messages": [{"role": "user", "content": huge_prompt}]
        }
        resp = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("safety limit", resp.json().get("detail", ""))

if __name__ == "__main__":
    unittest.main()
