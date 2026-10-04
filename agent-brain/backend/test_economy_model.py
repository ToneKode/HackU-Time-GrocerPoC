import httpx
from openrouter import OpenRouterPlanner
from tool_planner import _model_result
import json


def test_paid_model_configuration_routes_to_free_by_default(monkeypatch):
    monkeypatch.delenv('OPENROUTER_FREE_ONLY', raising=False)
    def handle(request):
        body=json.loads(request.content)
        assert body['model']=='openrouter/free'
        assert body['max_tokens']==1200
        assert 'reasoning' not in body
        return httpx.Response(200,json={'choices':[{'message':{'content':'Search','tool_calls':[]}}]})
    planner=OpenRouterPlanner(api_key='mock',model='paid/example',http=httpx.Client(transport=httpx.MockTransport(handle)))
    planner.tool_chat([{'role':'user','content':'food'}],[])


def test_model_search_context_omits_long_urls_but_retains_count():
    result={'total_count':305,'has_more':True,'products':[{'id':'p','name':'Snack','price':10,'product_url':'x'*10000,'image_url':'y'*10000}]}
    compact=json.loads(_model_result('search_catalog',result))
    assert compact['total_count']==305
    assert compact['products']==[{'id':'p','name':'Snack','price':10}]
    assert len(result['products'][0]['product_url'])==10000
