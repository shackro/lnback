from sqlalchemy import create_engine, inspect, text

from app.db.session import ensure_admin_security_columns, ensure_portfolio_audit_columns, ensure_product_media_columns


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


def test_portfolio_audit_migration_adds_legacy_actor_to_existing_loans() -> None:
    test_engine = create_engine("sqlite://")
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE portfolio_loans "
                "(id VARCHAR(40) PRIMARY KEY, principal NUMERIC(12, 2) NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO portfolio_loans (id, principal) VALUES ('legacy-loan', 3000.00)")
        )

    ensure_portfolio_audit_columns(test_engine)
    ensure_portfolio_audit_columns(test_engine)

    with test_engine.connect() as connection:
        assert connection.execute(
            text("SELECT offered_by FROM portfolio_loans WHERE id = 'legacy-loan'")
        ).scalar_one() == "legacy"
    test_engine.dispose()


def test_admin_security_migration_adds_permissions_without_changing_existing_accounts() -> None:
    test_engine = create_engine("sqlite://")
    with test_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE admin_users "
                "(id INTEGER PRIMARY KEY, email VARCHAR(254) NOT NULL, "
                "hashed_password VARCHAR(512) NOT NULL, role VARCHAR(20) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO admin_users (id, email, hashed_password, role) "
                "VALUES (1, 'original@example.test', 'unchanged-hash', 'admin')"
            )
        )

    ensure_admin_security_columns(test_engine)
    ensure_admin_security_columns(test_engine)

    with test_engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT email, hashed_password, role, permissions, token_version "
                "FROM admin_users WHERE id = 1"
            )
        ).one() == ("original@example.test", "unchanged-hash", "admin", "[]", 0)
    test_engine.dispose()
