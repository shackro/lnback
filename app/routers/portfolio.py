import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import require_portfolio_admin
from app.db.session import get_db
from app.models import (
    AdminUser,
    Loan,
    PortfolioCapitalEntry,
    PortfolioCoupon,
    PortfolioCouponRedemption,
    PortfolioLoan,
    PortfolioNotification,
    PortfolioTransaction,
    Referral,
)
from app.schemas import (
    PortfolioAcceptanceRequest,
    PortfolioAdminLoanResponse,
    PortfolioCapitalInjectionRequest,
    PortfolioCollateralSaleRequest,
    PortfolioCouponRequest,
    PortfolioDisbursementConfirmationRequest,
    PortfolioExtensionRequest,
    PortfolioOfferRequest,
    PortfolioQuoteResponse,
    PortfolioReceiptRequest,
    PortfolioSaleAssessmentRequest,
    PortfolioSettlementRequest,
)
from app.services.portfolio import calculate_buyout_price, calculate_period_interest, calculate_payoff

router = APIRouter(
    prefix="/api/admin/portfolio",
    tags=["portfolio"],
    dependencies=[Depends(require_portfolio_admin)],
)
system_router = APIRouter(tags=["system"])

CORPORATE_CASH_INFLOW_KINDS = (
    "interest_payment",
    "full_payoff",
    "collateral_buyout",
    "collateral_sale",
    "savings_applied_interest",
    "savings_applied_payoff",
    "savings_applied_buyout",
)


def _find_portfolio_loan(db: Session, portfolio_loan_id: str, *, lock: bool = False) -> PortfolioLoan:
    query = db.query(PortfolioLoan).filter(PortfolioLoan.id == portfolio_loan_id)
    if lock:
        query = query.with_for_update()
    portfolio_loan = query.first()
    if portfolio_loan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio loan not found")
    return portfolio_loan


def _quote(
    portfolio_loan: PortfolioLoan,
    db: Session,
    *,
    apply_savings: bool = False,
    coupon_code: str | None = None,
) -> PortfolioQuoteResponse:
    period_interest = calculate_period_interest(
        Decimal(portfolio_loan.principal),
        Decimal(portfolio_loan.interest_rate_percent),
    )
    full_due = calculate_payoff(Decimal(portfolio_loan.outstanding_principal), period_interest)
    savings_used = min(Decimal(portfolio_loan.savings_balance), full_due) if apply_savings else Decimal("0.00")
    remaining_due = full_due - savings_used
    coupon_discount = _coupon_discount(db, portfolio_loan, coupon_code, remaining_due)
    buyout_price = (
        calculate_buyout_price(Decimal(portfolio_loan.assessed_sale_price))
        if portfolio_loan.assessed_sale_price is not None
        else None
    )
    return PortfolioQuoteResponse(
        portfolio_loan_id=portfolio_loan.id,
        status=portfolio_loan.status,
        principal=portfolio_loan.principal,
        outstanding_principal=portfolio_loan.outstanding_principal,
        interest_rate_percent=portfolio_loan.interest_rate_percent,
        term_days=portfolio_loan.term_days,
        period_interest_due=period_interest,
        full_payoff_before_savings_or_coupon=full_due,
        savings_balance=portfolio_loan.savings_balance,
        extensions_remaining=max(0, portfolio_loan.max_extensions - portfolio_loan.extensions_used),
        assessed_sale_price=portfolio_loan.assessed_sale_price,
        buyout_price_before_savings=buyout_price,
        maturity_at=portfolio_loan.maturity_at,
        coupon_discount=coupon_discount,
        payoff_after_savings_and_coupon=max(Decimal("0.00"), remaining_due - coupon_discount),
    )


def _admin_loan_response(db: Session, portfolio_loan: PortfolioLoan) -> PortfolioAdminLoanResponse:
    application = db.get(Loan, portfolio_loan.application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Linked loan application is missing")
    return PortfolioAdminLoanResponse(
        **_quote(portfolio_loan, db).model_dump(),
        application_id=application.id,
        borrower_name=application.borrower_name,
        borrower_phone=application.phone,
        collateral=application.collateral,
        max_extensions=portfolio_loan.max_extensions,
        buyout_window_days=portfolio_loan.buyout_window_days,
        inspection_confirmed_at=portfolio_loan.inspection_confirmed_at,
        borrower_accepted_at=portfolio_loan.borrower_accepted_at,
    )


def _capital_summary(db: Session) -> dict[str, Decimal]:
    capital_injected = sum(
        (Decimal(amount) for (amount,) in db.query(PortfolioCapitalEntry.amount).all()),
        Decimal("0.00"),
    )
    cash_received = sum(
        (
            Decimal(amount)
            for (amount,) in db.query(PortfolioTransaction.amount)
            .filter(
                PortfolioTransaction.status == "confirmed",
                PortfolioTransaction.kind.in_(CORPORATE_CASH_INFLOW_KINDS),
            )
            .all()
        ),
        Decimal("0.00"),
    )
    funds_disbursed = sum(
        (
            Decimal(amount)
            for (amount,) in db.query(PortfolioTransaction.amount)
            .filter(
                PortfolioTransaction.status == "confirmed",
                PortfolioTransaction.kind == "loan_disbursement",
            )
            .all()
        ),
        Decimal("0.00"),
    )
    outstanding_principal = sum(
        (
            Decimal(amount)
            for (amount,) in db.query(PortfolioLoan.outstanding_principal)
            .filter(PortfolioLoan.status.in_(("active", "overdue", "buyout_window")))
            .all()
        ),
        Decimal("0.00"),
    )
    savings_liability = sum(
        (Decimal(amount) for (amount,) in db.query(PortfolioLoan.savings_balance).all()),
        Decimal("0.00"),
    )
    return {
        "capital_injected": capital_injected,
        "cash_received": cash_received,
        "funds_disbursed": funds_disbursed,
        "available_cash": capital_injected + cash_received - funds_disbursed,
        "outstanding_principal": outstanding_principal,
        "customer_savings_liability": savings_liability,
    }


@router.get("/capital")
def get_capital_summary(db: Session = Depends(get_db)) -> dict[str, Decimal]:
    return _capital_summary(db)


@router.post("/capital-injections", status_code=status.HTTP_201_CREATED)
def record_capital_injection(
    payload: PortfolioCapitalInjectionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> dict[str, object]:
    if db.query(PortfolioCapitalEntry.id).filter(
        PortfolioCapitalEntry.provider_reference == payload.provider_reference
    ).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Capital receipt has already been recorded")
    entry = PortfolioCapitalEntry(
        id=f"PC-{uuid4().hex[:16].upper()}",
        amount=payload.amount,
        provider_reference=payload.provider_reference,
        actor_email=admin.email,
        note=payload.note,
    )
    db.add(entry)
    _commit(db)
    summary = _capital_summary(db)
    return {"message": "Capital injection recorded", "entryId": entry.id, **summary}


@router.get("/loans", response_model=list[PortfolioAdminLoanResponse])
def list_portfolio_loans(db: Session = Depends(get_db)) -> list[PortfolioAdminLoanResponse]:
    records = db.query(PortfolioLoan).order_by(PortfolioLoan.created_at.desc()).all()
    return [_admin_loan_response(db, record) for record in records]


@router.get("/transactions")
def list_portfolio_transactions(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = (
        db.query(PortfolioTransaction, PortfolioLoan, Loan)
        .join(PortfolioLoan, PortfolioTransaction.portfolio_loan_id == PortfolioLoan.id)
        .join(Loan, PortfolioLoan.application_id == Loan.id)
        .order_by(PortfolioTransaction.created_at.desc())
        .all()
    )
    return [
        {
            "id": transaction.id,
            "portfolioLoanId": portfolio_loan.id,
            "borrowerName": application.borrower_name,
            "kind": transaction.kind,
            "amount": transaction.amount,
            "providerReference": transaction.provider_reference,
            "status": transaction.status,
            "actorEmail": transaction.actor_email,
            "note": transaction.note,
            "createdAt": transaction.created_at,
        }
        for transaction, portfolio_loan, application in rows
    ]


@router.post(
    "/applications/{application_id}/offer",
    response_model=PortfolioAdminLoanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_or_update_offer(
    application_id: str,
    payload: PortfolioOfferRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    application = db.query(Loan).filter(Loan.id == application_id).with_for_update().first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan application not found")
    if application.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The loan application must be approved before an offer can be prepared",
        )

    portfolio_loan = (
        db.query(PortfolioLoan)
        .filter(PortfolioLoan.application_id == application.id)
        .with_for_update()
        .first()
    )
    created = portfolio_loan is None
    if created:
        portfolio_loan = PortfolioLoan(
            id=f"RF-LN-{uuid4().hex[:12].upper()}",
            application_id=application.id,
            principal=payload.principal,
            outstanding_principal=payload.principal,
            interest_rate_percent=payload.interest_rate_percent,
            term_days=payload.term_days,
            max_extensions=payload.max_extensions,
            buyout_window_days=payload.buyout_window_days,
            offered_by=admin.email,
            status="offer",
        )
        db.add(portfolio_loan)
    else:
        if portfolio_loan.status != "offer" or portfolio_loan.borrower_accepted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The offer can no longer be changed after acceptance or disbursement",
            )
        portfolio_loan.principal = payload.principal
        portfolio_loan.outstanding_principal = payload.principal
        portfolio_loan.interest_rate_percent = payload.interest_rate_percent
        portfolio_loan.term_days = payload.term_days
        portfolio_loan.max_extensions = payload.max_extensions
        portfolio_loan.buyout_window_days = payload.buyout_window_days
        portfolio_loan.offered_by = admin.email

    db.commit()
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/inspection-acceptance", response_model=PortfolioAdminLoanResponse)
def confirm_inspection_and_acceptance(
    portfolio_loan_id: str,
    payload: PortfolioAcceptanceRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    if portfolio_loan.status != "offer":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Inspection and borrower acceptance can only be recorded for an open offer",
        )
    now = datetime.now(timezone.utc)
    portfolio_loan.inspection_confirmed_at = now
    portfolio_loan.inspection_confirmed_by = admin.email
    portfolio_loan.borrower_accepted_at = now
    portfolio_loan.borrower_accepted_by = admin.email
    portfolio_loan.status = "ready_to_disburse"
    db.commit()
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.put("/loans/{portfolio_loan_id}/sale-assessment", response_model=PortfolioAdminLoanResponse)
def assess_collateral_sale_price(
    portfolio_loan_id: str,
    payload: PortfolioSaleAssessmentRequest,
    db: Session = Depends(get_db),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    if portfolio_loan.status not in {"active", "overdue", "buyout_window"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collateral can only be assessed for an active or overdue funded loan",
        )
    portfolio_loan.assessed_sale_price = payload.assessed_sale_price
    db.commit()
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.get("/loans/{portfolio_loan_id}/quote", response_model=PortfolioQuoteResponse)
def get_portfolio_quote(
    portfolio_loan_id: str,
    apply_savings: bool = False,
    coupon_code: str | None = None,
    db: Session = Depends(get_db),
) -> PortfolioQuoteResponse:
    return _quote(
        _find_portfolio_loan(db, portfolio_loan_id),
        db,
        apply_savings=apply_savings,
        coupon_code=coupon_code,
    )


def _coupon_discount(
    db: Session,
    portfolio_loan: PortfolioLoan,
    coupon_code: str | None,
    amount_due: Decimal,
) -> Decimal:
    if not coupon_code:
        return Decimal("0.00")
    coupon = db.query(PortfolioCoupon).filter(PortfolioCoupon.code == coupon_code.strip().upper()).first()
    if coupon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    now = datetime.now(timezone.utc)
    expires_at = coupon.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at <= now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon has expired")
    if coupon.max_redemptions is not None and coupon.redemption_count >= coupon.max_redemptions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon redemption limit has been reached")
    already_redeemed = (
        db.query(PortfolioCouponRedemption)
        .filter(PortfolioCouponRedemption.portfolio_loan_id == portfolio_loan.id)
        .first()
    )
    if already_redeemed is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A coupon has already been used for this loan")
    if coupon.discount_type == "percent":
        return calculate_payoff(
            Decimal("0.00"),
            amount_due * Decimal(coupon.discount_value) / Decimal("100"),
        )
    return min(Decimal(coupon.discount_value), amount_due)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conflicting or duplicate portfolio ledger entry was submitted",
        ) from error


def _record_transaction(
    db: Session,
    portfolio_loan: PortfolioLoan,
    *,
    kind: str,
    amount: Decimal,
    admin: AdminUser | None,
    provider_reference: str | None = None,
    status_value: str = "confirmed",
    note: str | None = None,
) -> PortfolioTransaction:
    if provider_reference and db.query(PortfolioTransaction).filter(
        PortfolioTransaction.provider_reference == provider_reference
    ).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment reference has already been recorded")
    transaction = PortfolioTransaction(
        id=f"PT-{uuid4().hex[:16].upper()}",
        portfolio_loan_id=portfolio_loan.id,
        kind=kind,
        amount=amount,
        provider_reference=provider_reference,
        actor_email=admin.email if admin else None,
        status=status_value,
        note=note,
    )
    db.add(transaction)
    return transaction


def _refresh_lifecycle(portfolio_loan: PortfolioLoan, now: datetime) -> None:
    maturity_at = portfolio_loan.maturity_at
    if maturity_at is None or portfolio_loan.status not in {"active", "overdue"}:
        return
    if maturity_at.tzinfo is None:
        maturity_at = maturity_at.replace(tzinfo=timezone.utc)
    if now < maturity_at:
        return
    if portfolio_loan.extensions_used < portfolio_loan.max_extensions:
        portfolio_loan.status = "overdue"
        return
    portfolio_loan.status = "buyout_window"
    if portfolio_loan.buyout_deadline is None:
        portfolio_loan.buyout_deadline = maturity_at + timedelta(days=portfolio_loan.buyout_window_days)


def _require_payment_window(portfolio_loan: PortfolioLoan, now: datetime) -> None:
    _refresh_lifecycle(portfolio_loan, now)
    if portfolio_loan.status not in {"active", "overdue", "buyout_window"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payments cannot be applied while this account is {portfolio_loan.status}",
        )
    deadline = portfolio_loan.buyout_deadline
    if portfolio_loan.status == "buyout_window" and deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The collateral buyout window has ended",
            )


def _apply_coupon(
    db: Session,
    portfolio_loan: PortfolioLoan,
    coupon_code: str | None,
    discount_amount: Decimal,
    admin: AdminUser,
) -> None:
    if not coupon_code or discount_amount <= 0:
        return
    code = coupon_code.strip().upper()
    coupon = db.query(PortfolioCoupon).filter(PortfolioCoupon.code == code).with_for_update().first()
    if coupon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found")
    expiry = coupon.expires_at
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry is not None and expiry <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon has expired")
    if coupon.max_redemptions is not None and coupon.redemption_count >= coupon.max_redemptions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon redemption limit has been reached")
    if (
        db.query(PortfolioCouponRedemption)
        .filter(PortfolioCouponRedemption.portfolio_loan_id == portfolio_loan.id)
        .first()
        is not None
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A coupon has already been used for this loan")
    coupon.redemption_count += 1
    db.add(
        PortfolioCouponRedemption(
            id=f"PCR-{uuid4().hex[:16].upper()}",
            coupon_code=code,
            portfolio_loan_id=portfolio_loan.id,
            discount_amount=discount_amount,
        )
    )
    _record_transaction(
        db,
        portfolio_loan,
        kind="coupon_credit",
        amount=discount_amount,
        admin=admin,
        note=f"Coupon {code}",
    )


@router.post("/loans/{portfolio_loan_id}/disbursement-confirmed", response_model=PortfolioAdminLoanResponse)
def confirm_disbursement(
    portfolio_loan_id: str,
    payload: PortfolioDisbursementConfirmationRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    if portfolio_loan.status != "ready_to_disburse":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disbursement requires an accepted offer and confirmed collateral inspection",
        )
    application = db.query(Loan).filter(Loan.id == portfolio_loan.application_id).with_for_update().first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Linked loan application is missing")
    available_cash = _capital_summary(db)["available_cash"]
    if available_cash < Decimal(portfolio_loan.principal):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient corporate capital; available KSh {available_cash}",
        )
    now = datetime.now(timezone.utc)
    _record_transaction(
        db,
        portfolio_loan,
        kind="loan_disbursement",
        amount=Decimal(portfolio_loan.principal),
        admin=admin,
        provider_reference=payload.provider_reference,
        note="Disbursement must be confirmed by the payment provider before recording",
    )
    portfolio_loan.disbursed_at = now
    portfolio_loan.maturity_at = now + timedelta(days=portfolio_loan.term_days)
    portfolio_loan.status = "active"
    application.status = "disbursed"
    if application.referral_code:
        referral_exists = (
            db.query(Referral)
            .filter(Referral.kind == "loan", Referral.reference_id == application.id)
            .first()
        )
        if referral_exists is None:
            db.add(
                Referral(
                    id=f"REF-{uuid4().hex[:8]}",
                    referral_code=application.referral_code,
                    kind="loan",
                    reference_id=application.id,
                    amount=round(float(portfolio_loan.principal) * 0.03),
                    status="pending",
                )
            )
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/savings-deposits", response_model=PortfolioAdminLoanResponse)
def record_savings_deposit(
    portfolio_loan_id: str,
    payload: PortfolioReceiptRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    now = datetime.now(timezone.utc)
    _require_payment_window(portfolio_loan, now)
    _record_transaction(
        db,
        portfolio_loan,
        kind="savings_deposit",
        amount=payload.amount,
        admin=admin,
        provider_reference=payload.provider_reference,
        note="Customer funds are tracked separately from corporate lending capital",
    )
    portfolio_loan.savings_balance += payload.amount
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/interest-extensions", response_model=PortfolioAdminLoanResponse)
def apply_interest_extension(
    portfolio_loan_id: str,
    payload: PortfolioExtensionRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    now = datetime.now(timezone.utc)
    _require_payment_window(portfolio_loan, now)
    if portfolio_loan.extensions_used >= portfolio_loan.max_extensions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No interest-only extensions remain")
    interest_due = calculate_period_interest(
        Decimal(portfolio_loan.principal),
        Decimal(portfolio_loan.interest_rate_percent),
    )
    if payload.source == "savings":
        if payload.provider_reference or payload.amount is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Savings-funded extensions do not accept an external receipt or amount",
            )
        if portfolio_loan.savings_balance < interest_due:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Insufficient saved balance for interest")
        portfolio_loan.savings_balance -= interest_due
        _record_transaction(
            db,
            portfolio_loan,
            kind="savings_applied_interest",
            amount=interest_due,
            admin=admin,
            note="Borrower-directed use of saved funds to pay the current interest period",
        )
    else:
        if payload.provider_reference is None or payload.amount != interest_due:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Record the exact interest due of KSh {interest_due}",
            )
        _record_transaction(
            db,
            portfolio_loan,
            kind="interest_payment",
            amount=interest_due,
            admin=admin,
            provider_reference=payload.provider_reference,
        )

    maturity_at = portfolio_loan.maturity_at
    if maturity_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The loan has no maturity date")
    if maturity_at.tzinfo is None:
        maturity_at = maturity_at.replace(tzinfo=timezone.utc)
    portfolio_loan.maturity_at = max(maturity_at, now) + timedelta(days=portfolio_loan.term_days)
    portfolio_loan.extensions_used += 1
    portfolio_loan.status = "active"
    portfolio_loan.buyout_deadline = None
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/full-payoff", response_model=PortfolioAdminLoanResponse)
def record_full_payoff(
    portfolio_loan_id: str,
    payload: PortfolioSettlementRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    now = datetime.now(timezone.utc)
    _require_payment_window(portfolio_loan, now)
    base_due = calculate_payoff(
        Decimal(portfolio_loan.outstanding_principal),
        calculate_period_interest(Decimal(portfolio_loan.principal), Decimal(portfolio_loan.interest_rate_percent)),
    )
    savings_used = min(Decimal(portfolio_loan.savings_balance), base_due) if payload.apply_savings else Decimal("0.00")
    discount = _coupon_discount(db, portfolio_loan, payload.coupon_code, base_due - savings_used)
    expected_external_amount = base_due - savings_used - discount
    if payload.amount != expected_external_amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Expected confirmed payment amount KSh {expected_external_amount}",
        )
    if expected_external_amount > 0 and not payload.provider_reference:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A verified payment receipt is required")
    if expected_external_amount == 0 and payload.provider_reference:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No external payment is due")

    if expected_external_amount:
        _record_transaction(
            db,
            portfolio_loan,
            kind="full_payoff",
            amount=expected_external_amount,
            admin=admin,
            provider_reference=payload.provider_reference,
        )
    if savings_used:
        _record_transaction(
            db,
            portfolio_loan,
            kind="savings_applied_payoff",
            amount=savings_used,
            admin=admin,
            note="Borrower-directed application of saved funds to full payoff",
        )
        portfolio_loan.savings_balance -= savings_used
    _apply_coupon(db, portfolio_loan, payload.coupon_code, discount, admin)
    portfolio_loan.outstanding_principal = Decimal("0.00")
    portfolio_loan.status = "ready_for_pickup"
    application = db.get(Loan, portfolio_loan.application_id)
    if application is not None:
        application.status = "settled"
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/buyout", response_model=PortfolioAdminLoanResponse)
def record_collateral_buyout(
    portfolio_loan_id: str,
    payload: PortfolioSettlementRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    now = datetime.now(timezone.utc)
    _require_payment_window(portfolio_loan, now)
    if portfolio_loan.status != "buyout_window" or portfolio_loan.assessed_sale_price is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The 50% collateral buyout is available only during the assessed buyout window",
        )
    buyout_price = calculate_buyout_price(Decimal(portfolio_loan.assessed_sale_price))
    savings_used = min(Decimal(portfolio_loan.savings_balance), buyout_price) if payload.apply_savings else Decimal("0.00")
    discount = _coupon_discount(db, portfolio_loan, payload.coupon_code, buyout_price - savings_used)
    expected_external_amount = buyout_price - savings_used - discount
    if payload.amount != expected_external_amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Expected confirmed buyout payment amount KSh {expected_external_amount}",
        )
    if expected_external_amount > 0 and not payload.provider_reference:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A verified payment receipt is required")
    if expected_external_amount == 0 and payload.provider_reference:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No external payment is due")

    if expected_external_amount:
        _record_transaction(
            db,
            portfolio_loan,
            kind="collateral_buyout",
            amount=expected_external_amount,
            admin=admin,
            provider_reference=payload.provider_reference,
        )
    if savings_used:
        _record_transaction(
            db,
            portfolio_loan,
            kind="savings_applied_buyout",
            amount=savings_used,
            admin=admin,
            note="Borrower-directed application of saved funds to the disclosed buyout price",
        )
        portfolio_loan.savings_balance -= savings_used
    _apply_coupon(db, portfolio_loan, payload.coupon_code, discount, admin)
    portfolio_loan.outstanding_principal = Decimal("0.00")
    portfolio_loan.status = "ready_for_pickup"
    application = db.get(Loan, portfolio_loan.application_id)
    if application is not None:
        application.status = "settled"
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/collateral-sold", response_model=PortfolioAdminLoanResponse)
def close_after_collateral_sale(
    portfolio_loan_id: str,
    payload: PortfolioCollateralSaleRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    now = datetime.now(timezone.utc)
    _refresh_lifecycle(portfolio_loan, now)
    deadline = portfolio_loan.buyout_deadline
    if portfolio_loan.status != "buyout_window" or deadline is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The collateral is not eligible for closeout")
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if now <= deadline:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The disclosed buyout window is still open")
    _record_transaction(
        db,
        portfolio_loan,
        kind="collateral_sale",
        amount=payload.amount,
        admin=admin,
        provider_reference=payload.provider_reference,
        note="Sale closes the contract; outstanding balances are not carried forward",
    )
    portfolio_loan.outstanding_principal = Decimal("0.00")
    portfolio_loan.status = "forfeited"
    application = db.get(Loan, portfolio_loan.application_id)
    if application is not None:
        application.status = "settled"
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/loans/{portfolio_loan_id}/savings-refund", response_model=PortfolioAdminLoanResponse)
def record_savings_refund(
    portfolio_loan_id: str,
    payload: PortfolioReceiptRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> PortfolioAdminLoanResponse:
    portfolio_loan = _find_portfolio_loan(db, portfolio_loan_id, lock=True)
    if portfolio_loan.status not in {"ready_for_pickup", "forfeited", "refund_pending"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Saved funds can only be refunded after payoff, buyout, or collateral sale",
        )
    if payload.amount > portfolio_loan.savings_balance:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Refund exceeds the saved balance")
    _record_transaction(
        db,
        portfolio_loan,
        kind="savings_refund",
        amount=payload.amount,
        admin=admin,
        provider_reference=payload.provider_reference,
    )
    portfolio_loan.savings_balance -= payload.amount
    _commit(db)
    db.refresh(portfolio_loan)
    return _admin_loan_response(db, portfolio_loan)


@router.post("/coupons", status_code=status.HTTP_201_CREATED)
def create_coupon(
    payload: PortfolioCouponRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_portfolio_admin),
) -> dict[str, object]:
    code = payload.code.strip().upper()
    if db.get(PortfolioCoupon, code) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Coupon code already exists")
    if payload.expires_at is not None:
        expiry = payload.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Coupon expiry must be in the future")
    coupon = PortfolioCoupon(
        code=code,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        max_redemptions=payload.max_redemptions,
        created_by=admin.email,
        expires_at=payload.expires_at,
    )
    db.add(coupon)
    _commit(db)
    return {
        "code": coupon.code,
        "discountType": coupon.discount_type,
        "discountValue": coupon.discount_value,
        "maxRedemptions": coupon.max_redemptions,
        "redemptionCount": coupon.redemption_count,
        "expiresAt": coupon.expires_at,
    }


@router.get("/coupons")
def list_coupons(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    coupons = db.query(PortfolioCoupon).order_by(PortfolioCoupon.created_at.desc()).all()
    return [
        {
            "code": coupon.code,
            "discountType": coupon.discount_type,
            "discountValue": coupon.discount_value,
            "maxRedemptions": coupon.max_redemptions,
            "redemptionCount": coupon.redemption_count,
            "expiresAt": coupon.expires_at,
        }
        for coupon in coupons
    ]


@router.get("/notifications")
def list_pending_notifications(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    rows = (
        db.query(PortfolioNotification, PortfolioLoan, Loan)
        .join(PortfolioLoan, PortfolioNotification.portfolio_loan_id == PortfolioLoan.id)
        .join(Loan, PortfolioLoan.application_id == Loan.id)
        .filter(PortfolioNotification.status == "pending")
        .order_by(PortfolioNotification.created_at.asc())
        .all()
    )
    return [
        {
            "id": notification.id,
            "portfolioLoanId": portfolio_loan.id,
            "borrowerName": application.borrower_name,
            "borrowerPhone": application.phone,
            "message": notification.message,
            "whatsappLink": f"https://wa.me/{application.phone}?text={quote(notification.message)}",
            "createdAt": notification.created_at,
        }
        for notification, portfolio_loan, application in rows
    ]


@router.post("/notifications/{notification_id}/sent")
def mark_notification_sent(
    notification_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    notification = (
        db.query(PortfolioNotification)
        .filter(PortfolioNotification.id == notification_id)
        .with_for_update()
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found")
    if notification.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reminder is no longer pending")
    notification.status = "sent"
    notification.sent_at = datetime.now(timezone.utc)
    _commit(db)
    return {"message": "Reminder marked as sent"}


def _queue_due_reminders(db: Session, now: datetime) -> int:
    due_before = now + timedelta(hours=24)
    loans = (
        db.query(PortfolioLoan)
        .filter(
            PortfolioLoan.status.in_(("active", "overdue", "buyout_window")),
            PortfolioLoan.maturity_at.is_not(None),
            PortfolioLoan.maturity_at <= due_before,
        )
        .with_for_update()
        .all()
    )
    queued = 0
    for portfolio_loan in loans:
        _refresh_lifecycle(portfolio_loan, now)
        application = db.get(Loan, portfolio_loan.application_id)
        if application is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Portfolio loan {portfolio_loan.id} has no linked application",
            )
        period_number = portfolio_loan.extensions_used + 1
        kind = "buyout_reminder" if portfolio_loan.status == "buyout_window" else "due_reminder"
        exists = (
            db.query(PortfolioNotification.id)
            .filter(
                PortfolioNotification.portfolio_loan_id == portfolio_loan.id,
                PortfolioNotification.period_number == period_number,
                PortfolioNotification.kind == kind,
            )
            .first()
        )
        if exists is not None:
            continue

        interest_due = calculate_period_interest(
            Decimal(portfolio_loan.principal),
            Decimal(portfolio_loan.interest_rate_percent),
        )
        if kind == "buyout_reminder":
            buyout = (
                calculate_buyout_price(Decimal(portfolio_loan.assessed_sale_price))
                if portfolio_loan.assessed_sale_price is not None
                else None
            )
            option = (
                f"The disclosed collateral buyout amount is KSh {buyout:,.2f}."
                if buyout is not None
                else "Contact the lending team to confirm the collateral buyout amount."
            )
            message = (
                f"Hello {application.borrower_name}, your A+ Loans account {portfolio_loan.id} is in its "
                f"collateral buyout window. Your saved balance is KSh {portfolio_loan.savings_balance:,.2f}. "
                f"{option} If no option is completed by the disclosed deadline, the collateral process "
                "described in your agreement will continue. Contact us if you need help."
            )
        else:
            payoff = calculate_payoff(Decimal(portfolio_loan.outstanding_principal), interest_due)
            extension = (
                f"Pay the current period interest of KSh {interest_due:,.2f} to request one of "
                f"{portfolio_loan.max_extensions - portfolio_loan.extensions_used} available extensions."
                if portfolio_loan.extensions_used < portfolio_loan.max_extensions
                else "No interest-only extensions remain; contact the lending team before the due date."
            )
            message = (
                f"Hello {application.borrower_name}, your A+ Loans account {portfolio_loan.id} is due soon. "
                f"The current payoff amount is KSh {payoff:,.2f}, including KSh {interest_due:,.2f} "
                f"interest for this period. Your separately tracked savings are KSh "
                f"{portfolio_loan.savings_balance:,.2f}. {extension} Saved funds are used only when you "
                "confirm their application."
            )
        db.add(
            PortfolioNotification(
                id=f"PN-{uuid4().hex[:16].upper()}",
                portfolio_loan_id=portfolio_loan.id,
                period_number=period_number,
                kind=kind,
                message=message,
                status="pending",
            )
        )
        queued += 1
    return queued


@system_router.post("/api/system/portfolio/sweep-reminders")
def system_sweep_due_reminders(
    x_cron_secret: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    configured_secret = settings.cron_secret
    if len(configured_secret.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configure CRON_SECRET before enabling scheduled portfolio reminders",
        )
    if not secrets.compare_digest(x_cron_secret, configured_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid scheduler secret")
    queued = _queue_due_reminders(db, datetime.now(timezone.utc))
    _commit(db)
    return {"queued": queued}
