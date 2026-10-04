import json
import httpx
import pytest
from ollama_planner import OllamaPlanner, default_planner
from openrouter import PlannerError


def test_native_tools_round_trip_and_no_remote_credentials(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'must-not-send')
    def handle(request):
        assert request.url == 'http://local/api/chat'
        assert 'authorization' not in request.headers
        body=json.loads(request.content)
        assert body['model']=='qwen3:8b' and body['think'] is False and body['stream'] is False
        assert body['options']['num_predict']==2400
        assert body['options']['num_ctx']==32768
        assert body['messages'][1]['tool_calls'][0]['function']['arguments']=={'q':'rice'}
        assert body['messages'][2]['tool_name']=='search_catalog'
        return httpx.Response(200,json={'model':'qwen3:8b','message':{'role':'assistant','content':'Search snacks',
            'thinking':'private reasoning', 'tool_calls':[{'function':{'name':'search_catalog','arguments':{'q':'snacks'}}}]}})
    planner=OllamaPlanner(base_url='http://local',http=httpx.Client(transport=httpx.MockTransport(handle)))
    messages=[{'role':'user','content':'food'},{'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'search_catalog','arguments':'{"q":"rice"}'}}]},
              {'role':'tool','tool_call_id':'c1','content':'{"products":[]}'}]
    response=planner.tool_chat(messages,[])
    assert response['tool_calls'][0]['id']
    assert json.loads(response['tool_calls'][0]['function']['arguments'])=={'q':'snacks'}
    assert 'thinking' not in response
    assert messages[1]['tool_calls'][0]['function']['arguments']=='{"q":"rice"}'


def test_missing_model_error_explains_download():
    planner=OllamaPlanner(http=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(404,json={'error':'model missing'}))))
    with pytest.raises(PlannerError,match='ollama pull qwen3:8b'):planner.tool_chat([],[])


def test_default_provider_is_local(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER','ollama')
    monkeypatch.delenv('OLLAMA_MODEL',raising=False)
    assert isinstance(default_planner(),OllamaPlanner)
    assert default_planner().model=='qwen3:8b'
    assert default_planner().max_rounds==16
    assert default_planner().max_tool_calls==40


def test_local_limits_can_be_lowered_for_smaller_machines(monkeypatch):
    monkeypatch.setenv('OLLAMA_NUM_CTX', '16384')
    monkeypatch.setenv('OLLAMA_NUM_PREDICT', '1600')
    monkeypatch.setenv('OLLAMA_MAX_ROUNDS', '12')
    monkeypatch.setenv('OLLAMA_MAX_TOOL_CALLS', '24')
    planner=OllamaPlanner()
    assert (planner.context_tokens,planner.output_tokens,planner.max_rounds,planner.max_tool_calls)==(16384,1600,12,24)
    monkeypatch.setenv('OLLAMA_NUM_CTX', '999999')
    with pytest.raises(PlannerError,match='OLLAMA_NUM_CTX'):OllamaPlanner()


def test_local_transport_failure_never_falls_back():
    def fail(request):raise httpx.ConnectError('offline',request=request)
    planner=OllamaPlanner(http=httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(PlannerError,match='Local Ollama request failed'):planner.tool_chat([],[])
