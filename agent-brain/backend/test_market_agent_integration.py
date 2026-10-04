import json
from fastapi.testclient import TestClient
from agent_graph import ShoppingAgent
from clients import PolicyClient
from fake_mall import FileMall

ROWS=[{'id':'rice-w','name':'Rice 1kg','price':100,'merchant':'Watsons','category':'Rice & Noodles','currency':'HKD','in_stock':True,'stock':None},
      {'id':'rice-p','name':'Rice 1kg','price':110,'merchant':'PARKnSHOP','category':'Rice & Noodles','currency':'HKD','in_stock':True,'stock':None}]
INTENT='buy one Rice 1kg under HK$200'

def call(name,args):
    return {'content':'Compare current offers for the requested rice.', 'tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}

class Profile:
    def __init__(self):self.rules={'version':1,'promotions':[]}
    def market_rules(self):return self.rules
    def get_profile(self,*args):return {'monthly_cap':2000,'monthly_spent':0,'per_order_cap':500}
    def search_catalog(self,**args):return {'products':ROWS,'total_count':2,'has_more':False,'source':'mysql'}
    def catalog_categories(self):return [{'category':'Rice & Noodles','count':2}]
    def open_order(self,*args):return None
    def append_chat(self,*args):pass

class Model:
    def tool_chat(self,messages,tools):
        results=[json.loads(m['content']) for m in messages if m['role']=='tool']
        if not results:return call('search_catalog',{'q':'Rice','limit':20})
        optimizations=[r for r in results if 'optimization' in r]
        if not optimizations:return call('optimize_basket',{'intent':INTENT,'lines':[{'sku':'rice-w','qty':1}]})
        selected=[{'sku':line['sku'],'qty':line['qty']} for line in optimizations[-1]['lines'] if not line.get('is_gift')]
        if len(optimizations)==1:return call('optimize_basket',{'intent':INTENT,'lines':selected})
        return call('finish_plan',{'lines':selected,'summary':'Selected the lower effective cost for the current shared offers.'})


def test_same_prompt_uses_live_market_changes_without_agent_restart(tmp_path):
    profile=Profile()
    agent=ShoppingAgent(FileMall(products=ROWS),PolicyClient(offline=True),planner=Model(),profile=profile,
                        draft_path=str(tmp_path/'drafts.sqlite3'))
    first=agent.run(INTENT,0,None,account_id='demo')
    assert first['status']=='READY'
    assert first['lines'][0]['sku']=='rice-w'
    profile.rules={'version':2,'promotions':[{'id':'park-live','kind':'percent','merchant':'PARKnSHOP','threshold':100,'rate':.5,'enabled':True}]}
    second=agent.run(INTENT,0,None,account_id='demo')
    assert second['status']=='READY',second
    assert second['lines'][0]['sku']=='rice-p'
    assert second['settlement']['rules_version']==2
    assert second['settlement']['discount']==55
    assert second['settlement']['total']<first['settlement']['total']
    context=next(e['result']['result'] for e in second['audit_log'] if (e.get('result') or {}).get('action')=='catalog_context')
    assert context['market_rules']['version']==2
