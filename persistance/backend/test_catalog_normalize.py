from catalog_store import normalize_product


def test_normalize_keeps_a_shelf_row():
    row = normalize_product(
        {
            "id": "SKU00001",
            "name": "WATSONS BABY OIL",
            "price": 23,
            "currency": "HKD",
            "merchant": "Watsons",
            "category": "Baby",
            "stock": None,
            "in_stock": True,
            "image_url": "https://example.test/oil.jpg",
            "sell_point": "rated 4.7/5",
            "product_url": "https://example.test/oil",
        }
    )
    assert row["id"] == "SKU00001"
    assert row["price"] == 23.0
    assert row["currency"] == "HKD"
    assert row["stock"] is None
    assert row["sell_point"] == "rated 4.7/5"


def test_normalize_drops_a_row_without_a_price():
    assert normalize_product({"id": "SKU1", "name": "X", "merchant": "Watsons", "category": "Baby"}) is None
