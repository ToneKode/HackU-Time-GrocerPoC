"""OpenAI-compatible primary endpoint with request-scoped local fallback."""
import os
import threading
import httpx
from openrouter import OpenRouterPlanner, PlannerError
from ollama_planner import OllamaPlanner


class GatewayPlanner(OpenRouterPlanner):
    def __init__(self, api_key=None, http=None, fallback=None):
        super().__init__(api_key=api_key, model=os.environ.get('GATEWAY_MODEL', 'gpt-6.1-sol'), http=http)
        self.url = os.environ.get('GATEWAY_BASE_URL', 'https://apisub.vsakura.top').rstrip('/')
        self.endpoint = self.url + ('/chat/completions' if self.url.endswith('/v1') else '/v1/chat/completions')
        self.fallback = fallback or OllamaPlanner()
        self.max_rounds = self.fallback.max_rounds
        self.max_tool_calls = self.fallback.max_tool_calls
        self._state = threading.local()

    def _remote(self, messages, tools=None, max_tokens=2400, json_format=False):
        key = self.api_key if self.api_key is not None else os.environ.get('OPENROUTER_API_KEY', '')
        if not key.strip():
            raise PlannerError('OPENROUTER_API_KEY is not set for the primary gateway')
        payload = {'model': self.model, 'messages': messages, 'max_tokens': max_tokens, 'stream': False}
        if tools is not None:
            payload.update(tools=tools, tool_choice='auto')
        if json_format:
            payload['response_format'] = {'type': 'json_object'}
        client = self.http or httpx.Client(timeout=httpx.Timeout(60, connect=10))
        try:
            response = client.post(self.endpoint, json=payload, headers={'Authorization': 'Bearer ' + key.strip()})
            response.raise_for_status()
            body = response.json()
            message = (body.get('choices') or [{}])[0].get('message')
            if not isinstance(message, dict):
                raise PlannerError('Primary gateway returned no assistant message')
            if tools is not None:
                calls = message.get('tool_calls')
                if not isinstance(calls, list) or not calls:
                    raise PlannerError('Primary gateway returned no tool calls')
                for call in calls:
                    if not isinstance(call, dict) or not isinstance(call.get('function'), dict) or not call['function'].get('name'):
                        raise PlannerError('Primary gateway returned malformed tool calls')
            elif not isinstance(message.get('content'), str) or not message['content'].strip():
                raise PlannerError('Primary gateway returned empty content')
            return {**message, 'model': body.get('model') or self.model}
        except httpx.HTTPStatusError as exc:
            # Keep provider response bodies and credentials out of fallback evidence.
            raise PlannerError(f'Primary gateway HTTP {exc.response.status_code}') from exc
        except (httpx.RequestError, ValueError, TypeError, IndexError) as exc:
            raise PlannerError('Primary gateway request or response failed') from exc
        finally:
            if self.http is None:
                client.close()

    def tool_chat(self, messages, tools):
        if not any(m.get('role') == 'assistant' for m in messages):
            self._state.local = False
        if getattr(self._state, 'local', False):
            return self.fallback.tool_chat(messages, tools)
        try:
            return self._remote(messages, tools, self.fallback.output_tokens)
        except PlannerError as exc:
            self._state.local = True
            event = {'from_provider': 'vsakura', 'from_model': self.model,
                     'to_provider': 'ollama', 'to_model': self.fallback.model, 'reason': str(exc)}
            try:
                message = self.fallback.tool_chat(messages, tools)
            except PlannerError as local:
                raise PlannerError(f'{exc}; local fallback failed: {local}') from local
            return {**message, 'provider_events': [event]}

    def _chat(self, system, user, max_tokens):
        try:
            message = self._remote([{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                                   max_tokens=max_tokens, json_format=True)
            return message['content'], message['model']
        except PlannerError:
            return self.fallback._chat(system, user, max_tokens)
