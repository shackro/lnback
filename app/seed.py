from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Product, SettingsRecord

SAMPLE_PRODUCTS = [
    {
        "id": "RF-001",
        "title": "HP EliteBook 840 G8",
        "category": "Laptops",
        "description": "A dependable business laptop, professionally inspected and ready for its next chapter.",
        "diagnostic_notes": "Intel Core i5 · 16 GB RAM · 512 GB SSD. Keyboard, ports, webcam and battery tested. Light cosmetic wear on the lid.",
        "original_value": 98000,
        "price": 45000,
        "condition": "B",
        "status": "available",
        "location": "Nairobi CBD",
        "image": "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=1200&q=85",
    },
    {
        "id": "RF-002",
        "title": "Canon EOS 250D Kit",
        "category": "Cameras",
        "description": "Lightweight DSLR kit for a first-time creator or a seasoned photographer.",
        "diagnostic_notes": "24.1 MP sensor · 18–55 mm lens included. Shutter, autofocus and flash tested. Includes one battery and charger.",
        "original_value": 82000,
        "price": 39800,
        "condition": "A",
        "status": "available",
        "location": "Westlands",
        "image": "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=1200&q=85",
    },
    {
        "id": "RF-003",
        "title": "Samsung Galaxy Tab S8",
        "category": "Phones & tablets",
        "description": "A crisp display and powerful performance in a slim, versatile tablet.",
        "diagnostic_notes": "128 GB · Wi-Fi. Screen and S Pen tested. Includes USB-C cable. Small mark on the rear cover; screen is clean.",
        "original_value": 94000,
        "price": 51500,
        "condition": "B",
        "status": "available",
        "location": "Nairobi CBD",
        "image": "https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?auto=format&fit=crop&w=1200&q=85",
    },
    {
        "id": "RF-004",
        "title": "Sony WH-1000XM4",
        "category": "Audio",
        "description": "A much-loved pair of noise-cancelling headphones, checked by our team.",
        "diagnostic_notes": "Noise cancellation, Bluetooth, microphone and both drivers tested. Includes carry case and charging cable.",
        "original_value": 42000,
        "price": 21900,
        "condition": "A",
        "status": "available",
        "location": "Mombasa",
        "image": "https://images.unsplash.com/photo-1546435770-a3e426bf472b?auto=format&fit=crop&w=1200&q=85",
    },
    {
        "id": "RF-005",
        "title": "Apple iPhone 13 · 128 GB",
        "category": "Phones & tablets",
        "description": "A carefully checked iPhone with plenty of life left in it.",
        "diagnostic_notes": "Face ID, cameras, speakers and charging tested. Battery health 87%. Unlocked; handset only.",
        "original_value": 105000,
        "price": 68900,
        "condition": "B",
        "status": "reserved",
        "location": "Nairobi CBD",
        "image": "https://images.unsplash.com/photo-1592750475338-74b7b21085ab?auto=format&fit=crop&w=1200&q=85",
    },
    {
        "id": "RF-006",
        "title": "JBL Flip 6 Speaker",
        "category": "Audio",
        "description": "Big sound in a compact, splash-proof package. Great for the weekend.",
        "diagnostic_notes": "Both drivers and USB-C charging tested. Bluetooth pairing verified. Minor scuffs from normal use.",
        "original_value": 19500,
        "price": 9900,
        "condition": "C",
        "status": "available",
        "location": "Kisumu",
        "image": "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?auto=format&fit=crop&w=1200&q=85",
    },
]


def seed_database(db: Session) -> None:
    if db.query(Product.id).first() is None:
        timestamp = datetime.now(timezone.utc)
        db.add_all([Product(**product, created_at=timestamp) for product in SAMPLE_PRODUCTS])
    if db.get(SettingsRecord, 1) is None:
        db.add(SettingsRecord(id=1, monthly_rate=None, whatsapp_number="254700000000"))
    db.commit()
