def test_catalog_round_trip_survives_demo_reset(c):
    from catalog_store import CatalogStore
    from config import settings

    store = CatalogStore(settings()["database_url"])
    store.upsert_many(
        [
            {
                "id": "SKU90001",
                "name": "Demo Baby Oil",
                "price": 23,
                "currency": "HKD",
                "merchant": "Watsons",
                "category": "Baby",
                "in_stock": True,
                "sell_point": "rated 4.7/5",
            }
        ]
    )
    listed = c.get("/catalog/products", params={"q": "Demo Baby Oil", "limit": 10}).json()
    assert listed[0]["id"] == "SKU90001"
    assert listed[0]["price"] == 23.0
    assert c.get("/catalog/products/SKU90001").json()["merchant"] == "Watsons"
    assert c.post("/demo/reset").json()["reset"] is True
    assert c.get("/catalog/products/SKU90001").status_code == 200


def test_catalog_search_returns_matching_total_and_pagination(c):
    from catalog_store import CatalogStore
    from config import settings
    store = CatalogStore(settings()['database_url'])
    store.upsert_many([{'id':f'PAGED{i}', 'name':f'Unique QA Snack {i}', 'price':10,
                        'merchant':'HKTVmall','category':'QA Snacks'} for i in range(3)])
    page = c.get('/catalog/search',params={'category':'QA Snacks','limit':1,'offset':0}).json()
    assert page['source']=='mysql' and page['total_count']==3
    assert len(page['products'])==1 and page['has_more'] is True
    last = c.get('/catalog/search',params={'category':'QA Snacks','limit':1,'offset':2}).json()
    assert last['total_count']==3 and last['has_more'] is False
    none = c.get('/catalog/search',params={'q':'QA%Snack_NOT_PRESENT','limit':1}).json()
    assert none['total_count']==0 and none['products']==[]
