"""Local Ollama adapter for the existing audited tool-planning loop."""
from __future__ import annotations
import json
import os
from copy import deepcopy
import httpx
from openrouter import OpenRouterPlanner, PlannerError


class OllamaPlanner(OpenRouterPlanner):
    def __init__(self, model=None, http=None, base_url=None):
        super().__init__(model=model or os.environ.get('OLLAMA_MODEL', 'qwen3:8b'), http=http)
        self.base_url = (base_url or os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.context_tokens = self._limit('OLLAMA_NUM_CTX', 32768, 4096, 32768)
        self.output_tokens = self._limit('OLLAMA_NUM_PREDICT', 2400, 256, 8192)
        self.max_rounds = self._limit('OLLAMA_MAX_ROUNDS', 16, 1, 16)
        self.max_tool_calls = self._limit('OLLAMA_MAX_TOOL_CALLS', 40, 1, 40)

    @staticmethod
    def _limit(name, default, minimum, maximum):
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError as exc:
            raise PlannerError(f'{name} must be an integer') from exc
        if not minimum <= value <= maximum:
            raise PlannerError(f'{name} must be between {minimum} and {maximum}')
        return value

    @staticmethod
    def _messages(messages):
        converted = []
        names = {}
        for original in messages:
            message = deepcopy(original)
            calls = message.get('tool_calls') or []
            for call in calls:
                function = call.get('function') or {}
                names[call.get('id')] = function.get('name')
                arguments = function.get('arguments', {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError as exc:
                        raise PlannerError('Invalid tool arguments in local conversation history') from exc
                function['arguments'] = arguments
            if message.get('role') == 'tool':
                message['tool_name'] = names.get(message.pop('tool_call_id', None), '')
            if message.get('content') is None:
                message['content'] = ''
            converted.append(message)
        return converted

    def _request(self, messages, *, tools=None, max_tokens=1200, json_format=False):
        payload = {'model': self.model, 'messages': self._messages(messages),
                   'stream': False, 'think': False, 'keep_alive': '10m',
                   'options': {'num_predict': max_tokens, 'num_ctx': self.context_tokens, 'temperature': 0.2}}
        if tools is not None:
            payload['tools'] = tools
        if json_format:
            payload['format'] = 'json'
        client = self.http or httpx.Client(timeout=httpx.Timeout(300.0, connect=5.0))
        try:
            response = client.post(self.base_url + '/api/chat', json=payload)
            response.raise_for_status()
            body = response.json()
            if body.get('error'):
                raise PlannerError(f"Ollama: {body['error']}")
            message = body.get('message')
            if not isinstance(message, dict):
                raise PlannerError('Ollama returned no assistant message')
            message = {key: deepcopy(message[key]) for key in ('role', 'content', 'tool_calls') if key in message}
            message.setdefault('role', 'assistant')
            message['model'] = body.get('model') or self.model
            for index, call in enumerate(message.get('tool_calls') or []):
                call.setdefault('id', f"ollama_{len(messages)}_{index}")
                call.setdefault('type', 'function')
                function = call.get('function') or {}
                if isinstance(function.get('arguments'), dict):
                    function['arguments'] = json.dumps(function['arguments'], ensure_ascii=False)
            return message
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise PlannerError(f'Ollama model {self.model} is unavailable. Finish downloading it with ollama pull {self.model}.') from exc
            raise PlannerError(f'Ollama HTTP {exc.response.status_code}: {exc.response.text[:200]}') from exc
        except httpx.RequestError as exc:
            raise PlannerError('Local Ollama request failed. Make sure Ollama is running and the model has enough memory.') from exc
        except ValueError as exc:
            raise PlannerError('Ollama returned invalid JSON') from exc
        finally:
            if self.http is None:
                client.close()

    def tool_chat(self, messages, tools):
        return self._request(messages, tools=tools, max_tokens=self.output_tokens)

    def _chat(self, system, user, max_tokens):
        message = self._request([{'role': 'system', 'content': system},
                                 {'role': 'user', 'content': user}],
                                max_tokens=max_tokens, json_format=True)
        text = message.get('content') or ''
        if not text.strip():
            raise PlannerError('Ollama returned no JSON content')
        return text, message['model']


def default_planner():
    provider = os.environ.get('LLM_PROVIDER', 'vsakura').strip().lower()
    if provider == 'vsakura':
        from gateway_planner import GatewayPlanner
        return GatewayPlanner()
    if provider == 'ollama':
        return OllamaPlanner()
    if provider == 'openrouter':
        return OpenRouterPlanner()
    raise PlannerError(f'Unsupported LLM_PROVIDER: {provider}')
