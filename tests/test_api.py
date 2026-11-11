from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.dependencies import ADMIN_PERMISSIONS
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
                role="super_admin",
                permissions=sorted(ADMIN_PERMISSIONS),
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


def test_asset_finance_inquiry_is_saved_before_whatsapp_handoff(client: TestClient) -> None:
    response = client.post(
        "/api/inquiries",
        json={
            "kind": "asset_finance",
            "contactName": "  Amina Otieno ",
            "phone": "0712 345 678",
            "consent": True,
            "assetCategory": "Phones & tablets",
            "assetDetails": {"Brand and model": "Test phone"},
            "conditionGrade": "B",
            "conditionNotes": "Screen is intact",
            "estimatedAmount": 12000,
            "preferredInspectionTime": "Weekday afternoon",
            "referralCode": "RF123456",
        },
    )

    assert response.status_code == 201
    inquiry = response.json()
    assert inquiry["id"].startswith("REQ-")
    assert inquiry["contactName"] == "Amina Otieno"
    assert inquiry["phone"] == "254712345678"
    assert inquiry["status"] == "new"
    assert inquiry["consentedAt"]
    assert inquiry["context"]["assetDetails"] == {"Brand and model": "Test phone"}
    assert client.get("/api/bootstrap").json().get("inquiries") is None

    admin_data = client.get("/api/admin/bootstrap").json()
    assert admin_data["inquiries"][0]["id"] == inquiry["id"]
    updated = client.patch(f"/api/admin/inquiries/{inquiry['id']}", json={"status": "contacted"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "contacted"


def test_product_inquiries_snapshot_listings_and_require_admin_for_follow_up(client: TestClient) -> None:
    response = client.post(
        "/api/inquiries",
        json={
            "kind": "product",
            "contactName": "Buyer",
            "phone": "0712345678",
            "consent": True,
            "productId": "RF-001",
            "referralCode": "RF123456",
        },
    )

    assert response.status_code == 201
    inquiry = response.json()
    assert inquiry["kind"] == "product"
    assert inquiry["context"]["productId"] == "RF-001"
    assert inquiry["context"]["title"]
    assert inquiry["context"]["price"] > 0
    assert inquiry["context"]["referralCode"] == "RF123456"
    assert client.patch(
        f"/api/admin/inquiries/{inquiry['id']}",
        json={"status": "closed"},
        headers={"Authorization": ""},
    ).status_code == 401
    assert client.post(
        "/api/inquiries",
        json={
            "kind": "product",
            "contactName": "Buyer",
            "phone": "0712345678",
            "consent": True,
            "productId": "MISSING",
        },
    ).status_code == 404


def test_public_inquiries_require_contact_consent_and_valid_phone(client: TestClient) -> None:
    payload = {
        "kind": "asset_finance",
        "contactName": "Amina",
        "phone": "not-a-phone",
        "consent": True,
        "assetCategory": "Phones",
        "conditionGrade": "B",
    }

    assert client.post("/api/inquiries", json=payload).status_code == 422
    payload["phone"] = "0712345678"
    payload["consent"] = False
    assert client.post("/api/inquiries", json=payload).status_code == 422


def test_portfolio_offer_uses_admin_configured_terms(client: TestClient) -> None:
    application = client.post(
        "/api/loans",
        json={
            "id": "LOAN-portfolio",
            "borrowerName": "Test Borrower",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 1,
        },
    )
    assert application.status_code == 201
    assert client.patch("/api/admin/loans/LOAN-portfolio", json={"status": "reviewing"}).status_code == 200
    assert client.patch("/api/admin/loans/LOAN-portfolio", json={"status": "approved"}).status_code == 200

    offer_response = client.post(
        "/api/admin/portfolio/applications/LOAN-portfolio/offer",
        json={
            "principal": "3000.00",
            "interestRatePercent": "20",
            "termDays": 14,
            "maxExtensions": 2,
            "buyoutWindowDays": 7,
        },
    )
    assert offer_response.status_code == 201
    offer = offer_response.json()
    assert offer["principal"] == "3000.00"
    assert offer["periodInterestDue"] == "600.00"
    assert offer["fullPayoffBeforeSavingsOrCoupon"] == "3600.00"
    assert offer["status"] == "offer"

    acceptance = client.post(
        f"/api/admin/portfolio/loans/{offer['portfolioLoanId']}/inspection-acceptance",
        json={"inspectionConfirmed": True, "borrowerAccepted": True},
    )
    assert acceptance.status_code == 200
    assert acceptance.json()["status"] == "ready_to_disburse"
    capital = client.post(
        "/api/admin/portfolio/capital-injections",
        json={"amount": "5000.00", "providerReference": "CAPITAL-OFFER-001"},
    )
    assert capital.status_code == 201
    assert capital.json()["available_cash"] == "5000.00"
    disbursement = client.post(
        f"/api/admin/portfolio/loans/{offer['portfolioLoanId']}/disbursement-confirmed",
        json={"providerReference": "DISBURSE-OFFER-001"},
    )
    assert disbursement.status_code == 200
    transactions = client.get("/api/admin/portfolio/transactions")
    assert transactions.status_code == 200
    assert transactions.json()[0]["kind"] == "loan_disbursement"
    assert transactions.json()[0]["providerReference"] == "DISBURSE-OFFER-001"
    assert transactions.json()[0]["borrowerName"] == "Test Borrower"
    assert client.post("/api/admin/reset-demo").status_code == 409

    changed_offer = client.post(
        "/api/admin/portfolio/applications/LOAN-portfolio/offer",
        json={
            "principal": "5000.00",
            "interestRatePercent": "20",
            "termDays": 14,
            "maxExtensions": 2,
            "buyoutWindowDays": 7,
        },
    )
    assert changed_offer.status_code == 409


def test_admin_creation_scopes_api_access_and_audits_permission_changes(client: TestClient) -> None:
    created = client.post(
        "/api/admin/users",
        json={
            "email": "  clerk@example.test ",
            "password": "a different secure password",
            "permissions": ["dashboard.read", "inquiries.manage"],
        },
    )
    assert created.status_code == 201
    account = created.json()
    assert account["email"] == "clerk@example.test"
    assert account["role"] == "admin"
    assert account["permissions"] == ["dashboard.read", "inquiries.manage"]
    assert "hashedPassword" not in account

    login = client.post(
        "/api/auth/login",
        data={"username": "clerk@example.test", "password": "a different secure password"},
    )
    assert login.status_code == 200
    delegated_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    identity = client.get("/api/admin/me", headers=delegated_headers)
    assert identity.status_code == 200
    assert identity.json()["role"] == "admin"
    assert identity.json()["permissions"] == ["dashboard.read", "inquiries.manage"]
    store = client.get("/api/admin/bootstrap", headers=delegated_headers)
    assert store.status_code == 200
    assert store.json()["products"] == []
    assert store.json()["loans"] == []
    assert client.get("/api/admin/portfolio/loans", headers=delegated_headers).status_code == 403
    assert client.get("/api/admin/users", headers=delegated_headers).status_code == 403
    assert client.post(
        "/api/admin/users",
        json={
            "email": "escalation@example.test",
            "password": "another secure password",
            "permissions": ["dashboard.read"],
        },
        headers=delegated_headers,
    ).status_code == 403
    assert client.put(
        "/api/admin/settings",
        json={"monthlyRate": 10, "whatsappNumber": "0712345678"},
        headers=delegated_headers,
    ).status_code == 403

    updated = client.put(
        f"/api/admin/users/{account['id']}/permissions",
        json={"permissions": ["dashboard.read", "settings.manage"]},
    )
    assert updated.status_code == 200
    assert updated.json()["permissions"] == ["dashboard.read", "settings.manage"]
    allowed_settings = client.put(
        "/api/admin/settings",
        json={"monthlyRate": 10, "whatsappNumber": "254712345678"},
        headers=delegated_headers,
    )
    assert allowed_settings.status_code == 200
    assert client.get("/api/admin/portfolio/loans", headers=delegated_headers).status_code == 403
    audit = client.get("/api/admin/audit-log")
    assert audit.status_code == 200
    actions = [event["action"] for event in audit.json()]
    assert "admin_created" in actions
    assert "admin_permissions_updated" in actions
    assert client.put(
        "/api/admin/users/1/permissions",
        json={"permissions": ["dashboard.read"]},
    ).status_code == 409


def test_admin_management_rejects_escalation_and_requires_super_admin(client: TestClient) -> None:
    invalid_permissions = client.post(
        "/api/admin/users",
        json={
            "email": "staff@example.test",
            "password": "another secure password",
            "permissions": ["inventory.manage"],
        },
    )
    assert invalid_permissions.status_code == 422

    created = client.post(
        "/api/admin/users",
        json={
            "email": "staff@example.test",
            "password": "another secure password",
            "permissions": ["dashboard.read"],
        },
    )
    token = client.post(
        "/api/auth/login",
        data={"username": "staff@example.test", "password": "another secure password"},
    ).json()["access_token"]
    response = client.get("/api/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert created.status_code == 201
    assert response.status_code == 403


def test_admin_password_change_revokes_existing_sessions(client: TestClient) -> None:
    created = client.post(
        "/api/admin/users",
        json={
            "email": "secure-staff@example.test",
            "password": "initial secure password",
            "permissions": ["dashboard.read"],
        },
    )
    assert created.status_code == 201
    old_token = client.post(
        "/api/auth/login",
        data={"username": "secure-staff@example.test", "password": "initial secure password"},
    ).json()["access_token"]
    old_headers = {"Authorization": f"Bearer {old_token}"}

    changed = client.post(
        "/api/admin/me/password",
        json={
            "currentPassword": "initial secure password",
            "newPassword": "replacement secure password",
        },
        headers=old_headers,
    )
    assert changed.status_code == 200
    new_token = changed.json()["access_token"]
    assert client.get("/api/admin/me", headers=old_headers).status_code == 401
    assert client.get("/api/admin/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    assert client.post(
        "/api/auth/login",
        data={"username": "secure-staff@example.test", "password": "initial secure password"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        data={"username": "secure-staff@example.test", "password": "replacement secure password"},
    ).status_code == 200


def test_portfolio_tracks_savings_interest_extensions_coupons_and_payoff(
    client: TestClient,
) -> None:
    client.post(
        "/api/loans",
        json={
            "id": "LOAN-ledger-flow",
            "borrowerName": "Test Borrower",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 1,
        },
    )
    client.patch("/api/admin/loans/LOAN-ledger-flow", json={"status": "reviewing"})
    client.patch("/api/admin/loans/LOAN-ledger-flow", json={"status": "approved"})
    offer = client.post(
        "/api/admin/portfolio/applications/LOAN-ledger-flow/offer",
        json={
            "principal": "3000.00",
            "interestRatePercent": "20",
            "termDays": 14,
            "maxExtensions": 1,
            "buyoutWindowDays": 7,
        },
    ).json()
    portfolio_loan_id = offer["portfolioLoanId"]
    client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/inspection-acceptance",
        json={"inspectionConfirmed": True, "borrowerAccepted": True},
    )
    client.post(
        "/api/admin/portfolio/capital-injections",
        json={"amount": "3000.00", "providerReference": "CAPITAL-LEDGER-FLOW"},
    )
    disbursement = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/disbursement-confirmed",
        json={"providerReference": "B2C-LOAN-001"},
    )
    assert disbursement.status_code == 200
    assert disbursement.json()["maturityAt"] is not None

    savings = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/savings-deposits",
        json={"amount": "600.00", "providerReference": "C2B-SAVE-001"},
    )
    assert savings.status_code == 200
    assert savings.json()["savingsBalance"] == "600.00"

    extension = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/interest-extensions",
        json={"source": "savings"},
    )
    assert extension.status_code == 200
    assert extension.json()["extensionsRemaining"] == 0
    assert extension.json()["savingsBalance"] == "0.00"

    coupon = client.post(
        "/api/admin/portfolio/coupons",
        json={"code": "SAVE100", "discountType": "fixed", "discountValue": "100.00"},
    )
    assert coupon.status_code == 201
    quote = client.get(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/quote?coupon_code=SAVE100"
    )
    assert quote.status_code == 200
    assert quote.json()["fullPayoffBeforeSavingsOrCoupon"] == "3600.00"
    assert quote.json()["couponDiscount"] == "100.00"
    assert quote.json()["payoffAfterSavingsAndCoupon"] == "3500.00"

    payoff = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/full-payoff",
        json={
            "amount": "3500.00",
            "couponCode": "SAVE100",
            "providerReference": "C2B-PAYOFF-001",
        },
    )
    assert payoff.status_code == 200
    assert payoff.json()["status"] == "ready_for_pickup"
    assert payoff.json()["outstandingPrincipal"] == "0.00"

    duplicate_receipt = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/savings-deposits",
        json={"amount": "50.00", "providerReference": "C2B-SAVE-001"},
    )
    assert duplicate_receipt.status_code == 409


def test_scheduled_sweep_queues_one_day_reminder_idempotently(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "cron_secret", "test-cron-secret-that-is-at-least-32-bytes")
    client.post(
        "/api/loans",
        json={
            "id": "LOAN-reminder",
            "borrowerName": "Test Borrower",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 1,
        },
    )
    client.patch("/api/admin/loans/LOAN-reminder", json={"status": "reviewing"})
    client.patch("/api/admin/loans/LOAN-reminder", json={"status": "approved"})
    offer = client.post(
        "/api/admin/portfolio/applications/LOAN-reminder/offer",
        json={
            "principal": "3000.00",
            "interestRatePercent": "20",
            "termDays": 1,
            "maxExtensions": 1,
            "buyoutWindowDays": 7,
        },
    ).json()
    portfolio_loan_id = offer["portfolioLoanId"]
    client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/inspection-acceptance",
        json={"inspectionConfirmed": True, "borrowerAccepted": True},
    )
    client.post(
        "/api/admin/portfolio/capital-injections",
        json={"amount": "3000.00", "providerReference": "CAPITAL-REMINDER"},
    )
    client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/disbursement-confirmed",
        json={"providerReference": "B2C-REMINDER-001"},
    )

    denied = client.post("/api/system/portfolio/sweep-reminders")
    assert denied.status_code == 401

    sweep = client.post(
        "/api/system/portfolio/sweep-reminders",
        headers={"X-Cron-Secret": "test-cron-secret-that-is-at-least-32-bytes"},
    )
    assert sweep.status_code == 200
    assert sweep.json()["queued"] == 1

    repeated_sweep = client.post(
        "/api/system/portfolio/sweep-reminders",
        headers={"X-Cron-Secret": "test-cron-secret-that-is-at-least-32-bytes"},
    )
    assert repeated_sweep.status_code == 200
    assert repeated_sweep.json()["queued"] == 0

    notifications = client.get("/api/admin/portfolio/notifications")
    assert notifications.status_code == 200
    assert len(notifications.json()) == 1
    assert notifications.json()[0]["borrowerPhone"] == "254712345678"
    assert "KSh 600.00" in notifications.json()[0]["message"]


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


def test_disbursed_referred_loan_creates_single_commission(
    client: TestClient,
) -> None:
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

    for next_status in ("reviewing", "approved"):
        response = client.patch(f"/api/admin/loans/LOAN-one", json={"status": next_status})
        assert response.status_code == 200

    offer = client.post(
        "/api/admin/portfolio/applications/LOAN-one/offer",
        json={
            "principal": "20000.00",
            "interestRatePercent": "20",
            "termDays": 14,
            "maxExtensions": 1,
            "buyoutWindowDays": 7,
        },
    )
    assert offer.status_code == 201
    portfolio_loan_id = offer.json()["portfolioLoanId"]
    acceptance = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/inspection-acceptance",
        json={"inspectionConfirmed": True, "borrowerAccepted": True},
    )
    assert acceptance.status_code == 200
    capital = client.post(
        "/api/admin/portfolio/capital-injections",
        json={"amount": "25000.00", "providerReference": "CAPITAL-REFERRAL"},
    )
    assert capital.status_code == 201
    disbursement = client.post(
        f"/api/admin/portfolio/loans/{portfolio_loan_id}/disbursement-confirmed",
        json={"providerReference": "B2C-REFERRAL-001"},
    )
    assert disbursement.status_code == 200

    data = client.get("/api/admin/bootstrap").json()
    assert len(data["referrals"]) == 1
    assert data["referrals"][0]["kind"] == "loan"
    assert data["referrals"][0]["amount"] == 600


def test_legacy_admin_route_cannot_bypass_portfolio_disbursement(client: TestClient) -> None:
    client.post(
        "/api/loans",
        json={
            "id": "LOAN-no-bypass",
            "borrowerName": "Test Borrower",
            "nationalId": "12345678",
            "phone": "0712345678",
            "collateral": "Inspected laptop",
            "principal": 20000,
            "termMonths": 1,
        },
    )

    response = client.patch("/api/admin/loans/LOAN-no-bypass", json={"status": "disbursed"})

    assert response.status_code == 409
