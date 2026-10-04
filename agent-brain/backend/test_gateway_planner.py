import httpx
import json
from gateway_planner import GatewayPlanner
from ollama_planner import OllamaPlanner, default_planner


def test_primary_model_and_auth_are_exact(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY','mock-key')
    def remote(request):
        assert str(request.url)=='https://apisub.vsakura.top/v1/chat/completions'
        assert request.headers['authorization']=='Bearer mock-key'
        assert json.loads(request.content)['model']=='gpt-6.1-sol'
        return httpx.Response(200,json={'choices':[{'message':{'tool_calls':[{'id':'s1','function':{'name':'search_catalog','arguments':'{}'}}]}}]})
    p=GatewayPlanner(http=httpx.Client(transport=httpx.MockTransport(remote)))
    assert p.tool_chat([{'role':'user','content':'food'}],[])['model']=='gpt-6.1-sol'


def test_primary_error_falls_back_for_remainder_of_request_and_retries_next():
    primary=[];local=[]
    def remote(request):primary.append(request);return httpx.Response(500,text='not logged')
    def ollama(request):
        local.append(json.loads(request.content))
        assert 'authorization' not in request.headers
        return httpx.Response(200,json={'message':{'tool_calls':[{'function':{'name':'search_catalog','arguments':{'q':'rice'}}}]}})
    fallback=OllamaPlanner(http=httpx.Client(transport=httpx.MockTransport(ollama)))
    p=GatewayPlanner(api_key='mock',http=httpx.Client(transport=httpx.MockTransport(remote)),fallback=fallback)
    first=p.tool_chat([{'role':'user','content':'food'}],[])
    assert first['provider_events'][0]['reason']=='Primary gateway HTTP 500'
    messages=[{'role':'user','content':'food'},first,{'role':'tool','tool_call_id':first['tool_calls'][0]['id'],'content':'{}'}]
    p.tool_chat(messages,[])
    assert len(primary)==1 and len(local)==2
    p.tool_chat([{'role':'user','content':'new request'}],[])
    assert len(primary)==2


def test_default_provider_uses_requested_gateway(monkeypatch):
    monkeypatch.delenv('LLM_PROVIDER',raising=False)
    assert isinstance(default_planner(),GatewayPlanner)
