import hashlib,json
from fastapi.testclient import TestClient
from agent_graph import ShoppingAgent
from clients import PolicyClient
from fake_mall import FileMall
from server import create_app

PRODUCT={'id':'live-snack','name':'Crackers 100g','category':'Snacks','merchant':'HKTVmall',
         'price':20,'currency':'HKD','stock':None,'in_stock':True}

def call(name,args):
    return {'role':'assistant','content':'Compare the searched snack options.',
            'tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}

class LiveProfile:
    def get_profile(self,account):return {'per_order_cap':500,'monthly_cap':2000,'monthly_spent':0}
    def search_catalog(self,**kwargs):
        return {'products':[dict(PRODUCT)],'total_count':305 if kwargs.get('category')=='Snacks' else 1,
                'has_more':kwargs.get('category')=='Snacks','source':'mysql','offset':0}
    def catalog_categories(self):return [{'category':'Snacks','count':305}]
    def open_order(self,*args):return None
    def append_chat(self,*args):pass

class ToolModel:
    def __init__(self,fail=False):self.turn=0;self.fail=fail
    def __call__(self,*args):raise AssertionError('Legacy model planning must not run')
    def tool_chat(self,messages,tools):
        self.turn+=1
        assert {t['function']['name'] for t in tools}=={'search_catalog','optimize_basket','finish_plan'}
        if self.turn==1:return call('search_catalog',{'category':'Snacks','limit':1})
        if self.fail:return {'content':'I will stop here.'}
        if self.turn==2:return call('optimize_basket',{'intent':'buy snacks under HK$100','lines':[{'sku':'live-snack','qty':1}]})
        return call('finish_plan',{'lines':[{'sku':'live-snack','qty':1,'reason':'Chosen from the searched crackers.'}],
                                   'summary':'Selected crackers within your budget.'})


class RecordingPolicy(PolicyClient):
    def __init__(self):
        super().__init__(offline=True)
        self.logs=[]
    def log_event(self,event,status,reason):
        self.logs.append({'event':event,'status':status,'reason':reason})
        return {'stored':True}


def agent(tmp_path,fail=False):
    return ShoppingAgent(FileMall(),RecordingPolicy(),planner=ToolModel(fail),
                         profile=LiveProfile(),draft_path=str(tmp_path/'drafts.sqlite3'))


def verify_chain(entries):
    prev='0'*64
    for e in entries:
        assert e['prev_hash']==prev
        raw='|'.join(str(e[k]) for k in ['index','ts','event','status','reason','prev_hash'])
        assert hashlib.sha256(raw.encode()).hexdigest()==e['hash']
        prev=e['hash']


def test_model_chooses_tools_live_database_products_and_hashed_evidence(tmp_path):
    a=agent(tmp_path);api=TestClient(create_app(a))
    result=api.post('/agent/intent',json={'account_id':'alice','intent':'buy snacks under HK$100'}).json()
    assert result['status']=='READY',result
    assert result['lines'][0]['sku']=='live-snack'
    assert a.planner.turn==3
    events=[e for e in result['audit_log'] if e['event'] in {'MODEL_DECISION','TOOL_RESULT'}]
    assert len(events)==8
    search=next(e for e in events if e['result']['action']=='search_catalog')
    assert search['result']['result']['total_count']==305
    assert search['result']['account_id']=='alice'
    assert json.loads(search['reason'])==search['result']
    assert any(e['result']['action']=='finish_plan' for e in events)
    verify_chain(result['audit_log'])
    assert len(a.policy.logs)>=len(events)


def test_rejected_agent_candidate_is_replaced_without_halting_the_plan(tmp_path):
    bad={**PRODUCT,'id':'bad-snack','name':'Rejected Crackers 100g','category':'Blocked Food'}
    class Profile(LiveProfile):
        def search_catalog(self,**kwargs):
            return {'products':[bad,PRODUCT],'total_count':2,'has_more':False,'source':'mysql','offset':0}
    class Policy(RecordingPolicy):
        def check(self,merchant,category,amount,monthly_spent,**kwargs):
            result=super().check(merchant,category,amount,monthly_spent,**kwargs)
            if category=='Blocked Food':result.update(status='HALT',rule='category_blacklisted',reason='This food category is blocked')
            return result
    class Model(ToolModel):
        def tool_chat(self,messages,tools):
            self.turn+=1
            if self.turn==1:return call('search_catalog',{'category':'Snacks','limit':10})
            if self.turn==2:return call('optimize_basket',{'intent':'buy snacks under HK$100','lines':[{'sku':'bad-snack','qty':1}]})
            if self.turn==3:
                assert 'replace_candidate' in messages[-1]['content']
                return call('optimize_basket',{'intent':'buy snacks under HK$100','lines':[{'sku':'live-snack','qty':1}]})
            return call('finish_plan',{'lines':[{'sku':'live-snack','qty':1,'reason':'Replaced the blocked crackers with an allowed snack.'}],
                                     'summary':'Selected an allowed replacement because the original category was blocked.'})
    a=ShoppingAgent(FileMall(),Policy(),planner=Model(),profile=Profile(),draft_path=str(tmp_path/'drafts.sqlite3'))
    result=TestClient(create_app(a)).post('/agent/intent',json={'account_id':'alice','intent':'buy snacks under HK$100'}).json()
    assert result['status']=='READY'
    assert [line['sku'] for line in result['lines']]==['live-snack']
    rejected=[e for e in result['audit_log'] if (e.get('result') or {}).get('action')=='candidate_policy' and e['status']=='HALT']
    assert len(rejected)==1 and 'blocked' in rejected[0]['reason']
    verify_chain(result['audit_log'])


def test_user_added_blocked_product_is_returned_for_review_with_reason(tmp_path):
    bad={**PRODUCT,'id':'blocked-user-item','name':'User Selected Snack','category':'Blocked Food'}
    class Policy(RecordingPolicy):
        def check(self,merchant,category,amount,monthly_spent,**kwargs):
            result=super().check(merchant,category,amount,monthly_spent,**kwargs)
            if category=='Blocked Food':result.update(status='HALT',rule='category_blacklisted',reason='This category is blocked')
            return result
    a=ShoppingAgent(FileMall(products=[bad,PRODUCT]),Policy(),planner=lambda *args:{},draft_path=str(tmp_path/'drafts.sqlite3'))
    result=a.confirm_basket('buy my selected snack',[{'sku':'blocked-user-item','qty':1}],account_id='alice')
    assert result['status']=='NEEDS_INPUT'
    assert result['policy']['rule']=='category_blacklisted'
    assert result['lines'][0]['sku']=='blocked-user-item'
    assert result['payment_draft'] is None
    assert result['question']
    verify_chain(result['audit_log'])


def test_failed_model_turn_still_audits_prior_tool_results(tmp_path):
    a=agent(tmp_path,True)
    result=TestClient(create_app(a)).post('/agent/intent',json={'account_id':'alice','intent':'buy snacks under HK$100'}).json()
    assert result['status']=='FAILED'
    assert any(e.get('result',{}).get('action')=='search_catalog' for e in result['audit_log'] if e.get('result'))
    assert any(e.get('result',{}).get('action')=='planner_failed' for e in result['audit_log'] if e.get('result'))
    verify_chain(result['audit_log'])
