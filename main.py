
from dotenv import load_dotenv
load_dotenv()
import os

from fastapi import FastAPI, Depends, HTTPException
from database import engine, SessionLocal
import models
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

models.Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =========================
# SEND OTP
# =========================
SMTP_HOST     = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER",     "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM",     SMTP_USER)

@app.post("/send-otp")
def send_otp(body: dict):
    to_email = body.get("to_email", "").strip()
    to_name  = body.get("to_name", "Pengguna")
    otp_code = body.get("otp_code", "")
    if not to_email or not otp_code:
        raise HTTPException(status_code=400, detail="to_email dan otp_code wajib diisi")
    html_body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;
                border:1px solid #e5e7eb;border-radius:12px;">
      <h2 style="color:#1d4ed8;">Kode OTP Anda</h2>
      <p>Halo <strong>{to_name}</strong>,</p>
      <p>Gunakan kode berikut untuk masuk ke <strong>Garage Garage Amat</strong>:</p>
      <div style="font-size:36px;font-weight:bold;letter-spacing:10px;
                  text-align:center;padding:16px;background:#f1f5f9;
                  border-radius:8px;margin:16px 0;">{otp_code}</div>
      <p style="color:#6b7280;font-size:13px;">Kode berlaku <strong>5 menit</strong>.</p>
    </div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Kode OTP Login Garage Garage Amat"
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html"))
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, to_email, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.ehlo(); server.starttls(); server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, to_email, msg.as_string())
        return {"success": True}
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="Autentikasi SMTP gagal.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal kirim email: {str(e)}")


# =========================
# PRODUCTS
# =========================
@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    return [{"id": p.id, "code": p.code, "name": p.name, "category": p.category,
             "modalPrice": p.modalPrice, "sellPrice": p.sellPrice, "stock": p.stock,
             "minStock": p.minStock, "unit": p.unit,
             "isAvailable": bool(p.isAvailable) if p.isAvailable is not None else True}
            for p in db.query(models.Product).all()]

@app.post("/products")
def add_product(product: dict, db: Session = Depends(get_db)):
    if not product.get("code"):
        import re, time
        base = re.sub(r'[^A-Z0-9]', '', product.get("name", "PROD").upper())[:6]
        product["code"] = f"{base}-{int(time.time()) % 100000}"
    new_product = models.Product(**product)
    db.add(new_product); db.commit(); db.refresh(new_product)
    return new_product

@app.put("/products/stock/{id}")
def update_stock(id: int, quantity: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == id).first()
    if not product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    if product.stock + quantity < 0: raise HTTPException(status_code=400, detail="Stok tidak cukup")
    product.stock += quantity
    db.commit(); db.refresh(product)
    return product

@app.put("/products/availability/{id}")
def update_availability(id: int, body: dict, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == id).first()
    if not product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    product.isAvailable = bool(body.get("isAvailable", True))
    db.commit(); db.refresh(product)
    return {"id": product.id, "code": product.code, "name": product.name, "category": product.category,
            "modalPrice": product.modalPrice, "sellPrice": product.sellPrice, "stock": product.stock,
            "minStock": product.minStock, "unit": product.unit, "isAvailable": bool(product.isAvailable)}

@app.put("/products/{id}")
def update_product(id: int, product: dict, db: Session = Depends(get_db)):
    db_product = db.query(models.Product).filter(models.Product.id == id).first()
    if not db_product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    for key, value in product.items(): setattr(db_product, key, value)
    db.commit(); db.refresh(db_product)
    return db_product

@app.delete("/products/{id}")
def delete_product(id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == id).first()
    if not product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    db.delete(product); db.commit()
    return {"message": "deleted"}


# =========================
# TRANSACTIONS
# =========================
@app.get("/transactions")
def get_transactions(db: Session = Depends(get_db)):
    result = []
    for t in db.query(models.Transaction).order_by(models.Transaction.createdAt.desc()).all():
        result.append({
            "id": str(t.id), "invoiceNumber": t.invoiceNumber, "date": t.date,
            "items": json.loads(t.items) if t.items else [],
            "subtotal": t.subtotal, "discount": t.discount, "discountPct": t.discountPct,
            "total": t.total, "profit": t.profit, "paymentMethod": t.paymentMethod,
            "customerName": t.customerName, "customerPhone": t.customerPhone,
            "nomorPolisi": t.nomorPolisi, "uangBayar": t.uangBayar,
            "notes": t.notes, "createdBy": t.createdBy, "createdAt": t.createdAt,
        })
    return result

@app.post("/transactions")
def add_transaction(body: dict, db: Session = Depends(get_db)):
    t = models.Transaction(
        invoiceNumber=body.get("invoiceNumber", ""),
        date=body.get("date", ""),
        items=json.dumps(body.get("items", [])),
        subtotal=body.get("subtotal", 0),
        discount=body.get("discount", 0),
        discountPct=body.get("discountPct", 0),
        total=body.get("total", 0),
        profit=body.get("profit", 0),
        paymentMethod=body.get("paymentMethod", "cash"),
        customerName=body.get("customerName", ""),
        customerPhone=body.get("customerPhone", ""),
        nomorPolisi=body.get("nomorPolisi", ""),
        uangBayar=body.get("uangBayar", 0),
        notes=body.get("notes", ""),
        createdBy=body.get("createdBy", ""),
        createdAt=body.get("createdAt", ""),
    )
    db.add(t); db.commit(); db.refresh(t)
    return {"id": str(t.id), **body}

@app.delete("/transactions/{id}")
def delete_transaction(id: int, db: Session = Depends(get_db)):
    t = db.query(models.Transaction).filter(models.Transaction.id == id).first()
    if not t: raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    db.delete(t); db.commit()
    return {"message": "deleted"}


# =========================
# STOCK MOVEMENTS
# =========================
@app.get("/stock-movements")
def get_stock_movements(db: Session = Depends(get_db)):
    return [{"id": str(s.id), "productId": s.productId, "productName": s.productName,
             "type": s.type, "quantity": s.quantity, "previousStock": s.previousStock,
             "newStock": s.newStock, "reason": s.reason, "transactionId": s.transactionId,
             "createdBy": s.createdBy, "createdAt": s.createdAt}
            for s in db.query(models.StockMovement).order_by(models.StockMovement.createdAt.desc()).all()]

@app.post("/stock-movements")
def add_stock_movement(body: dict, db: Session = Depends(get_db)):
    s = models.StockMovement(
        productId=str(body.get("productId", "")),
        productName=body.get("productName", ""),
        type=body.get("type", "in"),
        quantity=body.get("quantity", 0),
        previousStock=body.get("previousStock", 0),
        newStock=body.get("newStock", 0),
        reason=body.get("reason", ""),
        transactionId=str(body.get("transactionId", "")) if body.get("transactionId") else None,
        createdBy=body.get("createdBy", ""),
        createdAt=body.get("createdAt", ""),
    )
    db.add(s); db.commit(); db.refresh(s)
    return {"id": str(s.id), **body}

@app.delete("/stock-movements/transaction/{transaction_id}")
def delete_movements_by_transaction(transaction_id: str, db: Session = Depends(get_db)):
    db.query(models.StockMovement).filter(models.StockMovement.transactionId == transaction_id).delete()
    db.commit()
    return {"message": "deleted"}


# =========================
# JASA CAT JOBS
# =========================
@app.get("/jasa-cat-jobs")
def get_jasa_cat_jobs(db: Session = Depends(get_db)):
    return [{"id": str(j.id), "date": j.date, "customer": j.customer,
             "motorType": j.motorType, "selling": j.selling, "cost": j.cost,
             "profit": j.profit, "notes": j.notes, "createdAt": j.createdAt,
             "data": json.loads(j.data) if j.data else {}}
            for j in db.query(models.JasaCatJob).order_by(models.JasaCatJob.createdAt.desc()).all()]

@app.post("/jasa-cat-jobs")
def add_jasa_cat_job(body: dict, db: Session = Depends(get_db)):
    j = models.JasaCatJob(
        date=body.get("date", body.get("tanggal", "")),
        customer=body.get("customer", body.get("customerName", body.get("namaCustomer", ""))),
        motorType=body.get("motorType", body.get("jenisMotor", "")),
        selling=float(body.get("selling", body.get("sellingPrice", body.get("hargaJual", 0))) or 0),
        cost=float(body.get("cost", body.get("totalCost", body.get("biaya", 0))) or 0),
        profit=float(body.get("profit", 0) or 0),
        notes=body.get("notes", body.get("catatan", "")),
        createdAt=body.get("createdAt", ""),
        data=json.dumps(body),
    )
    db.add(j); db.commit(); db.refresh(j)
    return {"id": str(j.id), **body}

@app.put("/jasa-cat-jobs/{id}")
def update_jasa_cat_job(id: int, body: dict, db: Session = Depends(get_db)):
    j = db.query(models.JasaCatJob).filter(models.JasaCatJob.id == id).first()
    if not j: raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    j.date = body.get("date", body.get("tanggal", j.date))
    j.customer = body.get("customer", body.get("customerName", j.customer))
    j.motorType = body.get("motorType", body.get("jenisMotor", j.motorType))
    j.selling = float(body.get("selling", body.get("sellingPrice", j.selling)) or 0)
    j.cost = float(body.get("cost", body.get("totalCost", j.cost)) or 0)
    j.profit = float(body.get("profit", j.profit) or 0)
    j.notes = body.get("notes", j.notes)
    j.data = json.dumps(body)
    db.commit(); db.refresh(j)
    return {"id": str(j.id), **body}

@app.delete("/jasa-cat-jobs/{id}")
def delete_jasa_cat_job(id: int, db: Session = Depends(get_db)):
    j = db.query(models.JasaCatJob).filter(models.JasaCatJob.id == id).first()
    if not j: raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    db.delete(j); db.commit()
    return {"message": "deleted"}



# =========================
# SERVICE TYPES
# =========================
DEFAULT_SERVICE_TYPES = [
    {"id": "cat", "name": "Service Cat", "color": "#14B8A6",
     "prices": {"bebek": 650000, "matic": 700000, "sport": 1200000},
     "modal": {"bebek": 0, "matic": 0, "sport": 0}},
    {"id": "oli", "name": "Ganti Oli", "color": "#F97316",
     "prices": {"bebek": 0, "matic": 0, "sport": 0},
     "modal": {"bebek": 0, "matic": 0, "sport": 0}},
]

def ensure_default_service_types(db: Session):
    if db.query(models.ServiceType).count() == 0:
        for s in DEFAULT_SERVICE_TYPES:
            db.add(models.ServiceType(
                id=s["id"], name=s["name"], color=s["color"],
                prices=json.dumps(s["prices"]), modal=json.dumps(s["modal"]),
            ))
        db.commit()

@app.get("/service-types")
def get_service_types(db: Session = Depends(get_db)):
    ensure_default_service_types(db)
    return [{"id": s.id, "name": s.name, "color": s.color,
             "prices": json.loads(s.prices or "{}"),
             "modal": json.loads(s.modal or "{}"),
             "linkedCategory": s.linkedCategory}
            for s in db.query(models.ServiceType).all()]

@app.post("/service-types")
def add_service_type(body: dict, db: Session = Depends(get_db)):
    s = models.ServiceType(
        id=body.get("id", f"custom_{int(__import__('time').time()*1000)}"),
        name=body["name"],
        color=body.get("color", "#14B8A6"),
        prices=json.dumps(body.get("prices", {})),
        modal=json.dumps(body.get("modal", {})),
        linkedCategory=body.get("linkedCategory") or None,
    )
    db.add(s); db.commit(); db.refresh(s)
    return {"id": s.id, "name": s.name, "color": s.color,
            "prices": json.loads(s.prices), "modal": json.loads(s.modal),
            "linkedCategory": s.linkedCategory}

@app.put("/service-types/{id}")
def update_service_type(id: str, body: dict, db: Session = Depends(get_db)):
    s = db.query(models.ServiceType).filter(models.ServiceType.id == id).first()
    if not s: raise HTTPException(status_code=404, detail="Service type tidak ditemukan")
    s.name = body.get("name", s.name)
    s.color = body.get("color", s.color)
    if "prices" in body: s.prices = json.dumps(body["prices"])
    if "modal" in body: s.modal = json.dumps(body["modal"])
    s.linkedCategory = body.get("linkedCategory") or None
    db.commit(); db.refresh(s)
    return {"id": s.id, "name": s.name, "color": s.color,
            "prices": json.loads(s.prices), "modal": json.loads(s.modal),
            "linkedCategory": s.linkedCategory}

@app.delete("/service-types/{id}")
def delete_service_type(id: str, db: Session = Depends(get_db)):
    s = db.query(models.ServiceType).filter(models.ServiceType.id == id).first()
    if not s: raise HTTPException(status_code=404, detail="Service type tidak ditemukan")
    db.delete(s); db.commit()
    return {"message": "deleted"}


# =========================
# CATEGORIES
# =========================
@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    return [{"name": c.name, "color": c.color}
            for c in db.query(models.Category).order_by(models.Category.id).all()]

@app.post("/categories")
def add_category(body: dict, db: Session = Depends(get_db)):
    existing = db.query(models.Category).filter(models.Category.name == body.get("name")).first()
    if existing: raise HTTPException(status_code=400, detail="Kategori sudah ada")
    c = models.Category(name=body.get("name", ""), color=body.get("color", "#14B8A6"))
    db.add(c); db.commit(); db.refresh(c)
    return {"name": c.name, "color": c.color}

@app.put("/categories/{name:path}")
def update_category(name: str, body: dict, db: Session = Depends(get_db)):
    from urllib.parse import unquote
    name = unquote(name)
    c = db.query(models.Category).filter(models.Category.name == name).first()
    if not c: raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    c.name = body.get("name", c.name)
    c.color = body.get("color", c.color)
    db.commit()
    return {"name": c.name, "color": c.color}

@app.delete("/categories/{name:path}")
def delete_category(name: str, db: Session = Depends(get_db)):
    from urllib.parse import unquote
    name = unquote(name)
    c = db.query(models.Category).filter(models.Category.name == name).first()
    if not c: raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    db.delete(c); db.commit()
    return {"message": "deleted"}


# =========================
# USERS
# =========================
@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    return [{"id": str(u.id), "username": u.username, "password": u.password,
             "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}
            for u in db.query(models.User).all()]

@app.post("/users")
def add_user(body: dict, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.username == body.get("username")).first()
    if existing: raise HTTPException(status_code=400, detail="Username sudah dipakai")
    u = models.User(username=body.get("username"), password=body.get("password"),
                    name=body.get("name"), role=body.get("role", "staff"),
                    email=body.get("email"), createdAt=body.get("createdAt", ""))
    db.add(u); db.commit(); db.refresh(u)
    return {"id": str(u.id), "username": u.username, "password": u.password,
            "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}

@app.put("/users/{id}")
def update_user(id: int, body: dict, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.id == id).first()
    if not u: raise HTTPException(status_code=404, detail="User tidak ditemukan")
    existing = db.query(models.User).filter(
        models.User.username == body.get("username"), models.User.id != id).first()
    if existing: raise HTTPException(status_code=400, detail="Username sudah dipakai")
    u.username = body.get("username", u.username)
    u.name = body.get("name", u.name)
    u.role = body.get("role", u.role)
    u.email = body.get("email", u.email)
    if body.get("password"): u.password = body["password"]
    db.commit(); db.refresh(u)
    return {"id": str(u.id), "username": u.username, "password": u.password,
            "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}

@app.delete("/users/{id}")
def delete_user(id: int, db: Session = Depends(get_db)):
    u = db.query(models.User).filter(models.User.id == id).first()
    if not u: raise HTTPException(status_code=404, detail="User tidak ditemukan")
    db.delete(u); db.commit()
    return {"message": "deleted"}