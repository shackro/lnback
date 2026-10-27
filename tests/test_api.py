from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import get_password_hash
from app.db.session import get_db
from app.main import app
from app.models import AdminUser, Base
from app.seed import seed_database


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setattr(settings, "secret_key", "test-only-secret-key-with-at-least-32-bytes")
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=test_engine)
    with TestingSession() as db:
        seed_database(db)
        db.add(
            AdminUser(
                email="admin@example.test",
                hashed_password=get_password_hash("correct horse battery staple"),
                role="admin",
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        login_response = test_client.post(
            "/api/auth/login",
            data={"username": "admin@example.test", "password": "correct horse battery staple"},
        )
        assert login_response.status_code == 200
        test_client.headers.update({"Authorization": f"Bearer {login_response.json()['access_token']}"})
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_admin_login_rejects_bad_credentials_and_admin_routes_require_a_token(client: TestClient) -> None:
    invalid_login = client.post(
        "/api/auth/login",
        data={"username": "admin@example.test", "password": "wrong password"},
    )
    invalid_token = client.get("/api/admin/bootstrap", headers={"Authorization": "Bearer invalid"})

    assert invalid_login.status_code == 401
    assert invalid_token.status_code == 401


def test_admin_routes_reject_requests_without_a_bearer_token(client: TestClient) -> None:
    response = client.get("/api/admin/bootstrap", headers={"Authorization": ""})

    assert response.status_code == 401


def test_admin_auth_fails_closed_without_a_signing_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "")

    login_response = client.post(
        "/api/auth/login",
        data={"username": "admin@example.test", "password": "correct horse battery staple"},
    )
    admin_response = client.get("/api/admin/bootstrap")

    assert login_response.status_code == 503
    assert admin_response.status_code == 503


def test_bootstrap_returns_seeded_marketplace(client: TestClient) -> None:
    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["products"]) == 6
    assert payload["products"][0]["id"] == "RF-001"
    assert payload["monthlyRate"] is None


def test_public_bootstrap_does_not_expose_bidder_or_borrower_details(client: TestClient) -> None:
    client.post(
        "/api/loans",
        json={
            "id": "LOAN-private",
            "borrowerName": "Private Borrower",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 2,
        },
    )
    client.post(
        "/api/bids",
        json={
            "id": "BID-private",
            "productId": "RF-001",
            "bidderPhone": "0712345678",
            "amount": 45300,
        },
    )

    public_data = client.get("/api/bootstrap").json()
    admin_data = client.get("/api/admin/bootstrap").json()

    assert "loans" not in public_data
    assert "borrowerName" not in public_data
    assert "bidderPhone" not in public_data["bids"][0]
    assert admin_data["loans"][0]["borrowerName"] == "Private Borrower"
    assert admin_data["bids"][0]["bidderPhone"] == "254712345678"


def test_product_media_is_saved_and_returned(client: TestClient) -> None:
    response = client.post(
        "/api/admin/products",
        json={
            "id": "RF-media",
            "title": "Inspected camera",
            "category": "Cameras",
            "description": "A camera with additional inspection media.",
            "diagnosticNotes": "Sensor and shutter tested.",
            "originalValue": 50000,
            "price": 30000,
            "condition": "B",
            "status": "available",
            "location": "Nairobi CBD",
            "image": "https://example.test/camera-front.jpg",
            "images": ["https://example.test/camera-back.jpg"],
            "inspectionVideoUrl": "https://example.test/camera-inspection.mp4",
        },
    )

    assert response.status_code == 201
    assert response.json()["images"] == ["https://example.test/camera-back.jpg"]
    assert response.json()["inspectionVideoUrl"] == "https://example.test/camera-inspection.mp4"
    saved_product = next(
        product for product in client.get("/api/admin/bootstrap").json()["products"]
        if product["id"] == "RF-media"
    )
    assert saved_product["image"] == "https://example.test/camera-front.jpg"
    assert saved_product["images"] == ["https://example.test/camera-back.jpg"]
    assert saved_product["inspectionVideoUrl"] == "https://example.test/camera-inspection.mp4"


def test_admin_can_edit_product_details_without_changing_its_status_or_creation_time(client: TestClient) -> None:
    original = next(
        product for product in client.get("/api/admin/bootstrap").json()["products"]
        if product["id"] == "RF-001"
    )
    response = client.put(
        "/api/admin/products/RF-001",
        json={
            "title": "Updated laptop",
            "category": "Laptops",
            "description": "Updated description",
            "diagnosticNotes": "Battery and keyboard retested.",
            "originalValue": 100000,
            "price": 47000,
            "condition": "A",
            "location": "Westlands",
            "image": "https://example.test/updated-laptop.jpg",
            "images": ["https://example.test/updated-laptop-back.jpg"],
            "inspectionVideoUrl": None,
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["title"] == "Updated laptop"
    assert updated["price"] == 47000
    assert updated["status"] == original["status"]
    assert updated["createdAt"] == original["createdAt"]
    assert updated["images"] == ["https://example.test/updated-laptop-back.jpg"]


def test_product_edit_requires_admin_authentication(client: TestClient) -> None:
    response = client.put(
        "/api/admin/products/RF-001",
        headers={"Authorization": ""},
        json={
            "title": "Updated laptop",
            "category": "Laptops",
            "description": "Updated description",
            "diagnosticNotes": "",
            "originalValue": 100000,
            "price": 47000,
            "condition": "A",
            "location": "Westlands",
            "image": "https://example.test/updated-laptop.jpg",
            "images": [],
            "inspectionVideoUrl": None,
        },
    )

    assert response.status_code == 401


def test_admin_product_edit_rejects_invalid_price_and_unknown_product(client: TestClient) -> None:
    invalid_price = client.put(
        "/api/admin/products/RF-001",
        json={
            "title": "Updated laptop",
            "category": "Laptops",
            "description": "Updated description",
            "diagnosticNotes": "",
            "originalValue": 40000,
            "price": 47000,
            "condition": "A",
            "location": "Westlands",
            "image": "https://example.test/updated-laptop.jpg",
            "images": [],
            "inspectionVideoUrl": None,
        },
    )
    missing_product = client.put(
        "/api/admin/products/not-found",
        json={
            "title": "Updated laptop",
            "category": "Laptops",
            "description": "Updated description",
            "diagnosticNotes": "",
            "originalValue": 100000,
            "price": 47000,
            "condition": "A",
            "location": "Westlands",
            "image": "https://example.test/updated-laptop.jpg",
            "images": [],
            "inspectionVideoUrl": None,
        },
    )

    assert invalid_price.status_code == 422
    assert missing_product.status_code == 404


def test_bid_rules_are_enforced_by_api(client: TestClient) -> None:
    invalid = client.post(
        "/api/bids",
        json={
            "id": "BID-invalid",
            "productId": "RF-001",
            "bidderPhone": "0712345678",
            "amount": 45200,
        },
    )
    valid = client.post(
        "/api/bids",
        json={
            "id": "BID-valid",
            "productId": "RF-001",
            "bidderPhone": "0712345678",
            "amount": 45300,
            "referralCode": "RF345678",
        },
    )

    assert invalid.status_code == 422
    assert "must be between KSh 45,300 and KSh 45,500" in invalid.json()["detail"]
    assert valid.status_code == 201
    assert valid.json()["bidderPhone"] == "254712345678"


def test_public_bid_cannot_set_admin_status(client: TestClient) -> None:
    response = client.post(
        "/api/bids",
        json={
            "id": "BID-forged",
            "productId": "RF-001",
            "bidderPhone": "0712345678",
            "amount": 45300,
            "status": "confirmed",
        },
    )

    assert response.status_code == 422


def test_confirming_bid_reserves_product_and_rejects_other_bids(client: TestClient) -> None:
    for bid_id, amount in (("BID-one", 45300), ("BID-two", 45600)):
        response = client.post(
            "/api/bids",
            json={
                "id": bid_id,
                "productId": "RF-001",
                "bidderPhone": "0712345678",
                "amount": amount,
            },
        )
        assert response.status_code == 201

    response = client.patch("/api/admin/bids/BID-two/resolve", json={"action": "confirm"})
    assert response.status_code == 200
    data = client.get("/api/admin/bootstrap").json()

    assert next(product for product in data["products"] if product["id"] == "RF-001")["status"] == "reserved"
    assert {bid["id"]: bid["status"] for bid in data["bids"]} == {
        "BID-two": "confirmed",
        "BID-one": "rejected",
    }


def test_sale_queues_item_commission_for_confirmed_bid_referrer(client: TestClient) -> None:
    bid = client.post(
        "/api/bids",
        json={
            "id": "BID-affiliate",
            "productId": "RF-001",
            "bidderPhone": "0712345678",
            "amount": 45300,
            "referralCode": "RF345678",
        },
    )
    assert bid.status_code == 201

    confirmed = client.patch("/api/admin/bids/BID-affiliate/resolve", json={"action": "confirm"})
    assert confirmed.status_code == 200
    assert client.get("/api/referrals/RF345678").json() == []

    sold = client.patch("/api/admin/products/RF-001/sell", json={})
    assert sold.status_code == 200
    referrals = client.get("/api/referrals/RF345678").json()

    assert len(referrals) == 1
    assert referrals[0]["kind"] == "buy"
    assert referrals[0]["referenceId"] == "RF-001"
    assert referrals[0]["amount"] == 1500
    assert referrals[0]["status"] == "pending"

    duplicate_sale = client.patch("/api/admin/products/RF-001/sell", json={})
    assert duplicate_sale.status_code == 409
    assert len(client.get("/api/referrals/RF345678").json()) == 1


def test_direct_sale_can_record_partner_referral_code(client: TestClient) -> None:
    sold = client.patch(
        "/api/admin/products/RF-001/sell",
        json={"referralCode": "RF345678"},
    )

    assert sold.status_code == 200
    referrals = client.get("/api/referrals/RF345678").json()
    assert len(referrals) == 1
    assert referrals[0]["referenceId"] == "RF-001"
    assert referrals[0]["amount"] == 1500


def test_direct_sale_rejects_invalid_partner_referral_code(client: TestClient) -> None:
    response = client.patch(
        "/api/admin/products/RF-001/sell",
        json={"referralCode": "not-a-partner-code"},
    )

    assert response.status_code == 422


def test_disbursed_referred_loan_creates_single_commission(client: TestClient) -> None:
    application = client.post(
        "/api/loans",
        json={
            "id": "LOAN-one",
            "borrowerName": "Amina Otieno",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 2,
            "referralCode": "RF345678",
        },
    )
    assert application.status_code == 201

    for next_status in ("reviewing", "approved", "disbursed"):
        response = client.patch(f"/api/admin/loans/LOAN-one", json={"status": next_status})
        assert response.status_code == 200

    data = client.get("/api/admin/bootstrap").json()
    assert len(data["referrals"]) == 1
    assert data["referrals"][0]["kind"] == "loan"
    assert data["referrals"][0]["amount"] == 600
