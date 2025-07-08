import time
import random
from typing import Dict, Any


class MockOpenAIAPI:
    def __init__(self):
        self.request_count = 0

    def generate_response(self, payload: Dict[Any, Any]) -> Dict[Any, Any]:
        self.request_count += 1

        time.sleep(random.uniform(0.1, 0.5))

        return {
            "id": f"mock_response_{self.request_count}",
            "choices": [{
                "message": {
                    "content": f"Mock response for: {payload.get('prompt', 'No prompt')}"
                }
            }],
            "usage": {
                "prompt_tokens": len(payload.get('prompt', '')),
                "completion_tokens": 50,
                "total_tokens": len(payload.get('prompt', '')) + 50
            }
        }


mock_openai_api = MockOpenAIAPI()
