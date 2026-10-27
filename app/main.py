from contextlib import asynccontextmanager
from uuid import uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, require_secret_key, verify_password
from app.db.session import SessionLocal, engine, ensure_product_media_columns, get_db
from app.models import AdminUser, Base, Bid, Loan, Product, Referral, SettingsRecord
from app.schemas import (
    BidResolveRequest,
    BidCreateRequest,
    BidSchema,
    LoanCreateRequest,
    LoanSchema,
    LoanStatusRequest,
    ProductSchema,
    ProductUpdateRequest,
    PublicBidSchema,
    PublicStoreSchema,
    ReferralSchema,
    SettingsRequest,
    SellProductRequest,
    StoreSchema,
)
from app.seed import seed_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_product_media_columns(engine)
    with SessionLocal() as db:
        seed_database(db)
    yield


app = FastAPI(
    title="A+ Loans & Investments API",
    description="API for the A+ Loans & Investments liquidation marketplace and asset finance demo.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def require_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> AdminUser:
    secret_key = require_secret_key()
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.InvalidTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    email = payload.get("sub")
    if payload.get("role") != "admin" or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    admin = db.query(AdminUser).filter(AdminUser.email == email, AdminUser.role == "admin").first()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate admin credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return admin


@app.post("/api/auth/login")
def admin_login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    require_secret_key()
    email = form_data.username.strip().lower()
    admin = db.query(AdminUser).filter(AdminUser.email == email, AdminUser.role == "admin").first()
    if admin is None or len(form_data.password) > 256 or not verify_password(form_data.password, admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": create_access_token(admin.email), "token_type": "bearer"}


def get_settings(db: Session) -> SettingsRecord:
    record = db.get(SettingsRecord, 1)
    if record is None:
        record = SettingsRecord(id=1, monthly_rate=None, whatsapp_number="254700000000")
        db.add(record)
        db.flush()
    return record


def make_store(db: Session) -> StoreSchema:
    config = get_settings(db)
    return StoreSchema(
        products=db.query(Product).order_by(desc(Product.created_at)).all(),
        bids=db.query(Bid).order_by(desc(Bid.created_at)).all(),
        loans=db.query(Loan).order_by(desc(Loan.created_at)).all(),
        referrals=db.query(Referral).order_by(desc(Referral.created_at)).all(),
        monthly_rate=config.monthly_rate,
        whatsapp_number=config.whatsapp_number,
    )


def make_public_store(db: Session) -> PublicStoreSchema:
    config = get_settings(db)
    return PublicStoreSchema(
        products=db.query(Product).order_by(desc(Product.created_at)).all(),
        bids=db.query(Bid).order_by(desc(Bid.created_at)).all(),
        monthly_rate=config.monthly_rate,
        whatsapp_number=config.whatsapp_number,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bootstrap", response_model=PublicStoreSchema)
def bootstrap(db: Session = Depends(get_db)) -> PublicStoreSchema:
    return make_public_store(db)


@app.get("/api/admin/bootstrap", response_model=StoreSchema, dependencies=[Depends(require_admin)])
def admin_bootstrap(db: Session = Depends(get_db)) -> StoreSchema:
    return make_store(db)


@app.get("/api/referrals/{referral_code}", response_model=list[ReferralSchema])
def list_partner_referrals(referral_code: str, db: Session = Depends(get_db)) -> list[Referral]:
    return (
        db.query(Referral)
        .filter(Referral.referral_code == referral_code)
        .order_by(desc(Referral.created_at))
        .all()
    )


@app.get("/api/products", response_model=list[ProductSchema])
def list_products(db: Session = Depends(get_db)) -> list[Product]:
    return db.query(Product).order_by(desc(Product.created_at)).all()


@app.get("/api/products/{product_id}", response_model=ProductSchema)
def get_product(product_id: str, db: Session = Depends(get_db)) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/api/bids/{product_id}", response_model=list[PublicBidSchema])
def list_bids(product_id: str, db: Session = Depends(get_db)) -> list[Bid]:
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return db.query(Bid).filter(Bid.product_id == product_id).order_by(desc(Bid.amount)).all()


@app.post("/api/bids", response_model=BidSchema, status_code=status.HTTP_201_CREATED)
def create_bid(payload: BidCreateRequest, db: Session = Depends(get_db)) -> Bid:
    if db.get(Bid, payload.id):
        raise HTTPException(status_code=409, detail="Bid ID already exists")
    product = db.query(Product).filter(Product.id == payload.product_id).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.status != "available":
        raise HTTPException(status_code=409, detail="Product is no longer available for bidding")

    latest_bid = (
        db.query(Bid)
        .filter(Bid.product_id == product.id, Bid.status != "rejected")
        .order_by(desc(Bid.amount))
        .first()
    )
    current_amount = latest_bid.amount if latest_bid else product.price
    minimum, maximum = current_amount + 300, current_amount + 500
    if not minimum <= payload.amount <= maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Bid must be between KSh {minimum:,.0f} and KSh {maximum:,.0f}",
        )

    bid = Bid(**payload.model_dump(exclude={"created_at"}))
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


@app.post("/api/loans", response_model=LoanSchema, status_code=status.HTTP_201_CREATED)
def create_loan(payload: LoanCreateRequest, db: Session = Depends(get_db)) -> Loan:
    if db.get(Loan, payload.id):
        raise HTTPException(status_code=409, detail="Application ID already exists")
    loan = Loan(**payload.model_dump())
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


@app.get("/api/admin/bids/{product_id}", response_model=list[BidSchema], dependencies=[Depends(require_admin)])
def get_product_bids(product_id: str, db: Session = Depends(get_db)) -> list[Bid]:
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return db.query(Bid).filter(Bid.product_id == product_id).order_by(desc(Bid.amount)).all()


@app.patch("/api/admin/bids/{bid_id}/resolve", dependencies=[Depends(require_admin)])
def resolve_bid(
    bid_id: str,
    payload: BidResolveRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    bid = db.query(Bid).filter(Bid.id == bid_id).with_for_update().first()
    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found")
    product = db.query(Product).filter(Product.id == bid.product_id).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if bid.status != "pending":
        raise HTTPException(status_code=409, detail="This bid has already been resolved")

    if payload.action == "confirm":
        if product.status != "available":
            raise HTTPException(status_code=409, detail="Product is no longer available")
        bid.status = "confirmed"
        product.status = "reserved"
        db.query(Bid).filter(
            Bid.product_id == product.id,
            Bid.id != bid.id,
            Bid.status == "pending",
        ).update({"status": "rejected"}, synchronize_session="fetch")
    else:
        bid.status = "rejected"

    db.commit()
    return {"message": f"Bid {payload.action}ed successfully", "bidId": bid.id}


@app.patch("/api/admin/products/{product_id}/sell", dependencies=[Depends(require_admin)])
def sell_product(
    product_id: str,
    payload: SellProductRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.status == "sold":
        raise HTTPException(status_code=409, detail="Product is already sold")

    product.status = "sold"
    winner = db.query(Bid).filter(Bid.product_id == product.id, Bid.status == "confirmed").first()
    referral_code = winner.referral_code if winner and winner.referral_code else (
        payload.referral_code if payload else None
    )
    if referral_code:
        exists = db.query(Referral).filter(
            Referral.kind == "buy",
            Referral.reference_id == product.id,
        ).first()
        if not exists:
            db.add(Referral(
                id=f"REF-{uuid4().hex[:8]}",
                referral_code=referral_code,
                kind="buy",
                reference_id=product.id,
                amount=1500,
                status="pending",
            ))
    db.commit()
    return {"message": "Product marked sold", "productId": product.id}


@app.patch("/api/admin/loans/{loan_id}", dependencies=[Depends(require_admin)])
def update_loan(
    loan_id: str,
    payload: LoanStatusRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    loan = db.query(Loan).filter(Loan.id == loan_id).with_for_update().first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    allowed = {
        "submitted": {"reviewing", "declined"},
        "reviewing": {"approved", "declined"},
        "approved": {"disbursed", "declined"},
        "disbursed": {"settled"},
        "declined": set(),
        "settled": set(),
    }
    if payload.status not in allowed[loan.status]:
        raise HTTPException(status_code=409, detail=f"Cannot change loan from {loan.status} to {payload.status}")

    loan.status = payload.status
    if payload.status == "disbursed" and loan.referral_code:
        exists = db.query(Referral).filter(
            Referral.kind == "loan",
            Referral.reference_id == loan.id,
        ).first()
        if not exists:
            db.add(Referral(
                id=f"REF-{uuid4().hex[:8]}",
                referral_code=loan.referral_code,
                kind="loan",
                reference_id=loan.id,
                amount=round(loan.principal * 0.03),
                status="pending",
            ))
    db.commit()
    return {"message": "Loan status updated", "loanId": loan.id}


@app.post("/api/admin/products", response_model=ProductSchema, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
def create_product(payload: ProductSchema, db: Session = Depends(get_db)) -> Product:
    if db.get(Product, payload.id):
        raise HTTPException(status_code=409, detail="Product ID already exists")
    product = Product(**payload.model_dump(exclude={"created_at"}))
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.put(
    "/api/admin/products/{product_id}",
    response_model=ProductSchema,
    dependencies=[Depends(require_admin)],
)
def update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    db: Session = Depends(get_db),
) -> Product:
    product = db.query(Product).filter(Product.id == product_id).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    for field, value in payload.model_dump().items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product


@app.put("/api/admin/settings", dependencies=[Depends(require_admin)])
def update_settings(payload: SettingsRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    record = get_settings(db)
    record.monthly_rate = payload.monthly_rate
    record.whatsapp_number = payload.whatsapp_number
    db.commit()
    return {"monthlyRate": record.monthly_rate, "whatsappNumber": record.whatsapp_number}


@app.patch("/api/admin/referrals/{referral_id}/pay", response_model=ReferralSchema, dependencies=[Depends(require_admin)])
def pay_referral(referral_id: str, db: Session = Depends(get_db)) -> Referral:
    referral = db.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    if referral.status != "pending":
        raise HTTPException(status_code=409, detail="Referral has already been paid")
    referral.status = "paid"
    db.commit()
    db.refresh(referral)
    return referral


@app.post("/api/admin/reset-demo", dependencies=[Depends(require_admin)])
def reset_demo(db: Session = Depends(get_db)) -> StoreSchema:
    for model in (Referral, Bid, Loan, Product):
        db.query(model).delete()
    db.query(SettingsRecord).delete()
    db.commit()
    seed_database(db)
    return make_store(db)
