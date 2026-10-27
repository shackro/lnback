from sqlalchemy import create_engine, inspect, text

from app.db.session import ensure_product_media_columns


def test_product_media_migration_adds_columns_to_existing_database() -> None:
    test_engine = create_engine("sqlite://")
    with test_engine.begin() as connection:
        connection.execute(text("CREATE TABLE products (id VARCHAR(40) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO products (id) VALUES ('legacy-product')"))

    ensure_product_media_columns(test_engine)
    columns = {column["name"]: column for column in inspect(test_engine).get_columns("products")}

    assert "images" in columns
    assert "inspection_video_url" in columns
    with test_engine.connect() as connection:
        assert connection.execute(
            text("SELECT images, inspection_video_url FROM products WHERE id = 'legacy-product'")
        ).one() == ("[]", None)
    test_engine.dispose()
