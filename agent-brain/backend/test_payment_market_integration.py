from agent_graph import ShoppingAgent
from fake_mall import FileMall
from clients import PolicyClient


ROWS=[{'id':'snack','name':'Crackers 100g','price':100,'currency':'HKD','category':'Snacks','merchant':'HKTVmall','stock':100,'in_stock':True}]

class Profile:
    def __init__(self):
        self.rules={'version':1,'promotions':[], 'payment_promotions':[
            {'route':'mastercard','kind':'cash','rate':.02,'merchant':'','enabled':True},
            {'route':'visa','kind':'cash','rate':.01,'merchant':'','enabled':True}]}
    def market_rules(self):return self.rules
    def get_profile(self,*args):
        return {'monthly_cap':2000,'monthly_spent':0,'per_order_cap':500,
                'payment_methods':[{'route':'mastercard','connected':True},{'route':'visa','connected':True}],
                'benefit_rank':['cash','asiamiles']}
    def open_order(self,*args):return None
    def append_chat(self,*args):pass


def test_live_payment_rate_changes_tender_without_restart(tmp_path):
    profile=Profile()
    agent=ShoppingAgent(FileMall(products=ROWS),PolicyClient(offline=True),profile=profile,
                        planner=lambda *args:{},draft_path=str(tmp_path/'drafts.sqlite3'))
    first=agent.confirm_basket('buy crackers under HK$200',[{'sku':'snack','qty':1}],account_id='alice')
    assert first['settlement']['merchants'][0]['payment']['route']=='mastercard'
    assert first['settlement']['benefits'][0]['amount']==2
    profile.rules={'version':2,'promotions':[],'payment_promotions':[
        {'route':'mastercard','kind':'cash','rate':.005,'merchant':'','enabled':True},
        {'route':'visa','kind':'cash','rate':.05,'merchant':'','enabled':True},
        {'route':'visa','kind':'asiamiles','rate':.5,'merchant':'','enabled':True}]}
    second=agent.confirm_basket('buy crackers under HK$200',[{'sku':'snack','qty':1}],account_id='alice')
    assert second['settlement']['merchants'][0]['payment']['route']=='visa'
    benefits={b['kind']:b['amount'] for b in second['settlement']['benefits']}
    assert benefits=={'cash':5,'asiamiles':50}
    assert second['settlement']['total']==130
    assert second['settlement']['rules_version']==2
    profile.rules={'version':3,'promotions':[], 'payment_promotions':[]}
    third=agent.confirm_basket('buy crackers under HK$200',[{'sku':'snack','qty':1}],account_id='alice')
    assert third['settlement']['benefits']==[]
