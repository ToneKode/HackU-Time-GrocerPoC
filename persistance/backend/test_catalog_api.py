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
