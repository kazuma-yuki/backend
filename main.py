
from dotenv import load_dotenv
load_dotenv()
import os

from fastapi import FastAPI, Depends, HTTPException, Header
from database import engine, SessionLocal
import models
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import smtplib
import os
import json
import socket
import secrets
import time
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Force IPv4 only — Railway container sering tidak punya route IPv6
# yang bikin koneksi ke smtp.gmail.com gagal dengan "Network is unreachable"
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4

models.Base.metadata.create_all(bind=engine)


def _seed_default_users():
    """Safety net: kalau tabel users kosong, buat akun default supaya tidak terkunci."""
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            import datetime
            now = datetime.datetime.utcnow().isoformat()
            db.add_all([
                models.User(username="admin", password="admin123", name="Administrator",
                            role="admin", email="ggat.kasir1@yopmail.com", createdAt=now),
                models.User(username="staff", password="staff123", name="Staff Bengkel",
                            role="staff", email="ggat.kasir1@yopmail.com", createdAt=now),
            ])
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


_seed_default_users()

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

# --- Penyimpanan sementara di server (in-memory) ---
# Login yang menunggu verifikasi OTP:
#   { token: {"user_id": int, "otp": str, "expires": float, "attempts": int} }
_PENDING_LOGINS: dict = {}
# Session aktif setelah OTP terverifikasi: { session_token: user_id }
_SESSIONS: dict = {}
_auth_lock = threading.Lock()

OTP_TTL_SECONDS  = 5 * 60   # OTP berlaku 5 menit
OTP_MAX_ATTEMPTS = 5        # maksimal percobaan OTP salah per sesi login


def _send_otp_email(to_email: str, to_name: str, otp_code: str):
    """Kirim email OTP dari sisi server. Raise HTTPException bila gagal."""
    if not to_email:
        raise HTTPException(status_code=400, detail="Email pengguna belum diatur, hubungi admin.")
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
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="Autentikasi SMTP gagal.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal kirim email: {str(e)}")


def _mask_email(email: str) -> str:
    """Samarkan email untuk ditampilkan di halaman OTP, mis. a****z@gmail.com."""
    if not email or "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = (name[0] if name else "") + "*"
    else:
        masked = name[0] + ("*" * (len(name) - 2)) + name[-1]
    return f"{masked}@{domain}"


def _new_otp() -> str:
    """OTP 6 digit, digenerate di server."""
    return f"{secrets.randbelow(1_000_000):06d}"


def get_session_user(authorization: str = Header(default=""),
                     db: Session = Depends(get_db)):
    """Ambil user dari sessionToken (header: Authorization: Bearer <token>).
    Sumber kebenaran otorisasi ada di server, bukan di localStorage client."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    with _auth_lock:
        user_id = _SESSIONS.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Sesi tidak valid. Silakan login ulang.")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Sesi tidak valid. Silakan login ulang.")
    return user


def require_admin(user=Depends(get_session_user)):
    """Role dicek di server, jadi tidak bisa dipalsukan lewat localStorage."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak. Fitur ini khusus admin.")
    return user


# =========================
# ACTIVITY LOG (riwayat aktivitas)
# =========================
def _fmt_rp(v) -> str:
    try:
        return "Rp" + f"{int(float(v)):,}".replace(",", ".")
    except Exception:
        return str(v)


def resolve_actor(authorization: str, db: Session, fallback: str = "Sistem"):
    """Tentukan pelaku dari sessionToken (server-side, tak bisa dipalsukan client)."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    with _auth_lock:
        uid = _SESSIONS.get(token)
    if uid:
        u = db.query(models.User).filter(models.User.id == uid).first()
        if u:
            return str(u.id), u.username
    return "", fallback


ACTIVITY_RETENTION_DAYS = 30  # riwayat hanya disimpan 1 bulan, selebihnya dihapus


def _purge_old_logs(db):
    """Hapus riwayat yang lebih tua dari batas retensi (1 bulan)."""
    try:
        import datetime
        cutoff = (datetime.datetime.now()
                  - datetime.timedelta(days=ACTIVITY_RETENTION_DAYS)).isoformat(timespec="seconds")
        db.query(models.ActivityLog).filter(models.ActivityLog.createdAt < cutoff).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()


def log_activity(db, actor, action, entity, entity_id, entity_name, description):
    """Simpan satu baris riwayat. Tidak boleh mengganggu operasi utama bila gagal."""
    try:
        import datetime
        actor_id, actor_name = actor
        db.add(models.ActivityLog(
            userId=actor_id or "",
            username=actor_name or "Sistem",
            action=action,
            entity=entity,
            entityId=str(entity_id or ""),
            entityName=entity_name or "",
            description=description or "",
            createdAt=datetime.datetime.now().isoformat(timespec="seconds"),
        ))
        db.commit()
        _purge_old_logs(db)
    except Exception:
        db.rollback()


@app.get("/activity-logs")
def get_activity_logs(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """Riwayat aktivitas, khusus admin. Hanya 1 bulan terakhir, terbaru di atas."""
    _purge_old_logs(db)
    rows = (db.query(models.ActivityLog)
              .order_by(models.ActivityLog.id.desc())
              .limit(1000).all())
    return [{"id": str(r.id), "userId": r.userId, "username": r.username,
             "action": r.action, "entity": r.entity, "entityId": r.entityId,
             "entityName": r.entityName, "description": r.description,
             "createdAt": r.createdAt} for r in rows]


# =========================
# AUTH (login + OTP di server)
# =========================
@app.post("/login")
def login(body: dict, db: Session = Depends(get_db)):
    """Langkah 1: validasi username & password, lalu kirim OTP dari server.
    Client hanya menerima token + data minimal, TIDAK menerima OTP/password."""
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username dan password wajib diisi.")

    user = db.query(models.User).filter(models.User.username == username).first()
    # Pesan sengaja disamakan supaya tidak membocorkan apakah username terdaftar.
    if not user or user.password != password:
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    otp_code = _new_otp()
    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _PENDING_LOGINS[token] = {
            "user_id": user.id,
            "otp": otp_code,
            "expires": time.time() + OTP_TTL_SECONDS,
            "attempts": 0,
        }
    # OTP dikirim dari server; kalau email gagal, batalkan sesi login.
    try:
        _send_otp_email(user.email, user.name or user.username, otp_code)
    except HTTPException:
        with _auth_lock:
            _PENDING_LOGINS.pop(token, None)
        raise

    # Hanya 1 blok minimal — tanpa password, tanpa OTP.
    return {"token": token, "username": user.username, "email": _mask_email(user.email)}


@app.post("/resend-otp")
def resend_otp(body: dict, db: Session = Depends(get_db)):
    """Kirim ulang OTP untuk sesi login yang sedang menunggu verifikasi."""
    token = body.get("token") or ""
    with _auth_lock:
        pending = _PENDING_LOGINS.get(token)
        if not pending:
            raise HTTPException(status_code=400, detail="Sesi login tidak valid. Silakan login ulang.")
        otp_code = _new_otp()
        pending["otp"] = otp_code
        pending["expires"] = time.time() + OTP_TTL_SECONDS
        pending["attempts"] = 0
        user_id = pending["user_id"]
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Pengguna tidak ditemukan.")
    _send_otp_email(user.email, user.name or user.username, otp_code)
    return {"success": True}


@app.post("/verify-otp")
def verify_otp(body: dict, db: Session = Depends(get_db)):
    """Langkah 2: verifikasi OTP di server. Client cukup kirim token + otp."""
    token = body.get("token") or ""
    otp_input = (body.get("otp") or "").strip()
    with _auth_lock:
        pending = _PENDING_LOGINS.get(token)
        if not pending:
            raise HTTPException(status_code=400, detail="Sesi login tidak valid. Silakan login ulang.")
        if time.time() > pending["expires"]:
            _PENDING_LOGINS.pop(token, None)
            raise HTTPException(status_code=400, detail="Kode OTP kedaluwarsa. Silakan login ulang.")
        if pending["attempts"] >= OTP_MAX_ATTEMPTS:
            _PENDING_LOGINS.pop(token, None)
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Silakan login ulang.")
        if otp_input != pending["otp"]:
            pending["attempts"] += 1
            raise HTTPException(status_code=401, detail="Kode OTP salah.")
        # OTP benar → buat session, hapus pending.
        user_id = pending["user_id"]
        _PENDING_LOGINS.pop(token, None)
        session_token = secrets.token_urlsafe(32)
        _SESSIONS[session_token] = user_id

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Pengguna tidak ditemukan.")
    return {
        "sessionToken": session_token,
        "user": {
            "id": str(user.id),
            "username": user.username,
            "name": user.name,
            "role": user.role,
            "email": user.email,
        },
    }


@app.get("/me")
def me(user=Depends(get_session_user)):
    """Sumber kebenaran identitas & role pengguna yang sedang login.
    Client wajib memanggil ini untuk menentukan hak akses, bukan localStorage."""
    return {
        "id": str(user.id),
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "email": user.email,
    }


# =========================
# LUPA SANDI (reset password via OTP, semua di server)
# =========================
_PENDING_RESETS: dict = {}   # { token: {"user_id","otp","expires","attempts"} }
_RESET_TOKENS: dict = {}     # { reset_token: {"user_id","expires"} }


@app.post("/forgot-password")
def forgot_password(body: dict, db: Session = Depends(get_db)):
    """Langkah 1: cari username, kirim OTP reset ke email dari server."""
    username = (body.get("username") or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username wajib diisi.")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Username tidak ditemukan.")
    if not user.email:
        raise HTTPException(status_code=400, detail="Akun ini tidak memiliki email terdaftar.")

    otp_code = _new_otp()
    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _PENDING_RESETS[token] = {
            "user_id": user.id, "otp": otp_code,
            "expires": time.time() + OTP_TTL_SECONDS, "attempts": 0,
        }
    try:
        _send_otp_email(user.email, user.name or user.username, otp_code)
    except HTTPException:
        with _auth_lock:
            _PENDING_RESETS.pop(token, None)
        raise
    return {"token": token, "email": _mask_email(user.email)}


@app.post("/forgot-password/resend")
def forgot_password_resend(body: dict, db: Session = Depends(get_db)):
    token = body.get("token") or ""
    with _auth_lock:
        pending = _PENDING_RESETS.get(token)
        if not pending:
            raise HTTPException(status_code=400, detail="Sesi tidak valid. Silakan ulangi.")
        otp_code = _new_otp()
        pending["otp"] = otp_code
        pending["expires"] = time.time() + OTP_TTL_SECONDS
        pending["attempts"] = 0
        user_id = pending["user_id"]
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Pengguna tidak ditemukan.")
    _send_otp_email(user.email, user.name or user.username, otp_code)
    return {"success": True}


@app.post("/forgot-password/verify")
def forgot_password_verify(body: dict):
    """Langkah 2: verifikasi OTP reset. Balikin resetToken (bukan langsung ganti password)."""
    token = body.get("token") or ""
    otp_input = (body.get("otp") or "").strip()
    with _auth_lock:
        pending = _PENDING_RESETS.get(token)
        if not pending:
            raise HTTPException(status_code=400, detail="Sesi tidak valid. Silakan ulangi.")
        if time.time() > pending["expires"]:
            _PENDING_RESETS.pop(token, None)
            raise HTTPException(status_code=400, detail="Kode OTP kedaluwarsa. Silakan ulangi.")
        if pending["attempts"] >= OTP_MAX_ATTEMPTS:
            _PENDING_RESETS.pop(token, None)
            raise HTTPException(status_code=429, detail="Terlalu banyak percobaan. Silakan ulangi.")
        if otp_input != pending["otp"]:
            pending["attempts"] += 1
            raise HTTPException(status_code=401, detail="Kode OTP salah.")
        user_id = pending["user_id"]
        _PENDING_RESETS.pop(token, None)
        reset_token = secrets.token_urlsafe(32)
        _RESET_TOKENS[reset_token] = {"user_id": user_id, "expires": time.time() + OTP_TTL_SECONDS}
    return {"resetToken": reset_token}


@app.post("/forgot-password/reset")
def forgot_password_reset(body: dict, db: Session = Depends(get_db)):
    """Langkah 3: ganti password menggunakan resetToken yang sah."""
    reset_token = body.get("resetToken") or ""
    new_password = body.get("newPassword") or ""
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter.")
    with _auth_lock:
        entry = _RESET_TOKENS.get(reset_token)
        if not entry or time.time() > entry["expires"]:
            _RESET_TOKENS.pop(reset_token, None)
            raise HTTPException(status_code=400, detail="Sesi reset tidak valid atau kedaluwarsa. Silakan ulangi.")
        user_id = entry["user_id"]
        _RESET_TOKENS.pop(reset_token, None)
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Pengguna tidak ditemukan.")
    user.password = new_password
    db.commit()
    return {"success": True}


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
def add_product(product: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    if not product.get("code"):
        import re, time
        base = re.sub(r'[^A-Z0-9]', '', product.get("name", "PROD").upper())[:6]
        product["code"] = f"{base}-{int(time.time()) % 100000}"
    new_product = models.Product(**product)
    db.add(new_product); db.commit(); db.refresh(new_product)
    log_activity(db, resolve_actor(authorization, db), "create", "product",
                 new_product.id, new_product.name,
                 f"Tambah produk {new_product.name} (stok {new_product.stock}, jual {_fmt_rp(new_product.sellPrice)})")
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
def update_product(id: int, product: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    db_product = db.query(models.Product).filter(models.Product.id == id).first()
    if not db_product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    _labels = {"name": "nama", "category": "kategori", "modalPrice": "harga modal",
               "sellPrice": "harga jual", "stock": "stok", "minStock": "stok min", "unit": "satuan"}
    _before = {k: getattr(db_product, k) for k in _labels}
    for key, value in product.items(): setattr(db_product, key, value)
    db.commit(); db.refresh(db_product)
    _changes = []
    for k, lbl in _labels.items():
        if k in product and str(_before[k]) != str(getattr(db_product, k)):
            nv = getattr(db_product, k)
            _changes.append(f"{lbl} {_fmt_rp(_before[k])}→{_fmt_rp(nv)}"
                            if k in ("modalPrice", "sellPrice")
                            else f"{lbl} {_before[k]}→{nv}")
    _desc = f"Ubah produk {db_product.name}" + (": " + ", ".join(_changes) if _changes else "")
    log_activity(db, resolve_actor(authorization, db), "update", "product", db_product.id, db_product.name, _desc)
    return db_product

@app.delete("/products/{id}")
def delete_product(id: int, db: Session = Depends(get_db), authorization: str = Header(default="")):
    product = db.query(models.Product).filter(models.Product.id == id).first()
    if not product: raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    _name = product.name
    db.delete(product); db.commit()
    log_activity(db, resolve_actor(authorization, db), "delete", "product", id, _name, f"Hapus produk {_name}")
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
def add_transaction(body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
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
    _who = (f"No. HP {t.customerPhone}" if t.customerPhone
            else (f"a.n. {t.customerName}" if t.customerName else f"#{t.id}"))
    log_activity(db, resolve_actor(authorization, db), "create", "transaction",
                 t.id, t.customerPhone or t.customerName or str(t.id),
                 f"Buat transaksi penjualan {_who} total {_fmt_rp(t.total)}")
    return {"id": str(t.id), **body}

@app.delete("/transactions/{id}")
def delete_transaction(id: int, db: Session = Depends(get_db), authorization: str = Header(default="")):
    t = db.query(models.Transaction).filter(models.Transaction.id == id).first()
    if not t: raise HTTPException(status_code=404, detail="Transaksi tidak ditemukan")
    _who = (f"No. HP {t.customerPhone}" if t.customerPhone
            else (f"a.n. {t.customerName}" if t.customerName else f"#{id}"))
    _ident = t.customerPhone or t.customerName or str(id); _total = t.total
    db.delete(t); db.commit()
    log_activity(db, resolve_actor(authorization, db), "delete", "transaction", id, _ident,
                 f"Hapus transaksi penjualan {_who} (total {_fmt_rp(_total)})")
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
def add_jasa_cat_job(body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
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
    log_activity(db, resolve_actor(authorization, db), "create", "jasa_service",
                 j.id, j.customer, f"Buat transaksi jasa servis {j.customer} ({_fmt_rp(j.selling)})")
    return {"id": str(j.id), **body}

@app.put("/jasa-cat-jobs/{id}")
def update_jasa_cat_job(id: int, body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    j = db.query(models.JasaCatJob).filter(models.JasaCatJob.id == id).first()
    if not j: raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    _before = {"customer": j.customer, "selling": j.selling, "cost": j.cost}
    j.date = body.get("date", body.get("tanggal", j.date))
    j.customer = body.get("customer", body.get("customerName", j.customer))
    j.motorType = body.get("motorType", body.get("jenisMotor", j.motorType))
    j.selling = float(body.get("selling", body.get("sellingPrice", j.selling)) or 0)
    j.cost = float(body.get("cost", body.get("totalCost", j.cost)) or 0)
    j.profit = float(body.get("profit", j.profit) or 0)
    j.notes = body.get("notes", j.notes)
    j.data = json.dumps(body)
    db.commit(); db.refresh(j)
    _ch = []
    if j.customer != _before["customer"]: _ch.append(f"customer {_before['customer']}→{j.customer}")
    if float(j.selling) != float(_before["selling"]): _ch.append(f"harga jual {_fmt_rp(_before['selling'])}→{_fmt_rp(j.selling)}")
    if float(j.cost) != float(_before["cost"]): _ch.append(f"modal {_fmt_rp(_before['cost'])}→{_fmt_rp(j.cost)}")
    _desc = f"Ubah transaksi jasa servis {j.customer}" + (": " + ", ".join(_ch) if _ch else "")
    log_activity(db, resolve_actor(authorization, db), "update", "jasa_service", j.id, j.customer, _desc)
    return {"id": str(j.id), **body}

@app.delete("/jasa-cat-jobs/{id}")
def delete_jasa_cat_job(id: int, db: Session = Depends(get_db), authorization: str = Header(default="")):
    j = db.query(models.JasaCatJob).filter(models.JasaCatJob.id == id).first()
    if not j: raise HTTPException(status_code=404, detail="Job tidak ditemukan")
    _name = j.customer
    db.delete(j); db.commit()
    log_activity(db, resolve_actor(authorization, db), "delete", "jasa_service", id, _name,
                 f"Hapus transaksi jasa servis {_name}")
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
def add_service_type(body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    s = models.ServiceType(
        id=body.get("id", f"custom_{int(__import__('time').time()*1000)}"),
        name=body["name"],
        color=body.get("color", "#14B8A6"),
        prices=json.dumps(body.get("prices", {})),
        modal=json.dumps(body.get("modal", {})),
        linkedCategory=body.get("linkedCategory") or None,
    )
    db.add(s); db.commit(); db.refresh(s)
    log_activity(db, resolve_actor(authorization, db), "create", "service_type", s.id, s.name,
                 f"Tambah jenis service {s.name}")
    return {"id": s.id, "name": s.name, "color": s.color,
            "prices": json.loads(s.prices), "modal": json.loads(s.modal),
            "linkedCategory": s.linkedCategory}

@app.put("/service-types/{id}")
def update_service_type(id: str, body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    s = db.query(models.ServiceType).filter(models.ServiceType.id == id).first()
    if not s: raise HTTPException(status_code=404, detail="Service type tidak ditemukan")
    _before_name, _before_prices = s.name, s.prices
    s.name = body.get("name", s.name)
    s.color = body.get("color", s.color)
    if "prices" in body: s.prices = json.dumps(body["prices"])
    if "modal" in body: s.modal = json.dumps(body["modal"])
    s.linkedCategory = body.get("linkedCategory") or None
    db.commit(); db.refresh(s)
    _ch = []
    if s.name != _before_name: _ch.append(f"nama {_before_name}→{s.name}")
    if s.prices != _before_prices: _ch.append("harga diperbarui")
    _desc = f"Ubah jenis service {s.name}" + (": " + ", ".join(_ch) if _ch else "")
    log_activity(db, resolve_actor(authorization, db), "update", "service_type", s.id, s.name, _desc)
    return {"id": s.id, "name": s.name, "color": s.color,
            "prices": json.loads(s.prices), "modal": json.loads(s.modal),
            "linkedCategory": s.linkedCategory}

@app.delete("/service-types/{id}")
def delete_service_type(id: str, db: Session = Depends(get_db), authorization: str = Header(default="")):
    s = db.query(models.ServiceType).filter(models.ServiceType.id == id).first()
    if not s: raise HTTPException(status_code=404, detail="Service type tidak ditemukan")
    _name = s.name
    db.delete(s); db.commit()
    log_activity(db, resolve_actor(authorization, db), "delete", "service_type", id, _name,
                 f"Hapus jenis service {_name}")
    return {"message": "deleted"}


# =========================
# CATEGORIES
# =========================
@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    return [{"name": c.name, "color": c.color}
            for c in db.query(models.Category).order_by(models.Category.id).all()]

@app.post("/categories")
def add_category(body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    existing = db.query(models.Category).filter(models.Category.name == body.get("name")).first()
    if existing: raise HTTPException(status_code=400, detail="Kategori sudah ada")
    c = models.Category(name=body.get("name", ""), color=body.get("color", "#14B8A6"))
    db.add(c); db.commit(); db.refresh(c)
    log_activity(db, resolve_actor(authorization, db), "create", "category", c.name, c.name,
                 f"Tambah kategori {c.name}")
    return {"name": c.name, "color": c.color}

@app.put("/categories/{name:path}")
def update_category(name: str, body: dict, db: Session = Depends(get_db), authorization: str = Header(default="")):
    from urllib.parse import unquote
    name = unquote(name)
    c = db.query(models.Category).filter(models.Category.name == name).first()
    if not c: raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    _before_name, _before_color = c.name, c.color
    c.name = body.get("name", c.name)
    c.color = body.get("color", c.color)
    db.commit()
    _ch = []
    if c.name != _before_name: _ch.append(f"nama {_before_name}→{c.name}")
    if c.color != _before_color: _ch.append(f"warna {_before_color}→{c.color}")
    _desc = f"Ubah kategori {c.name}" + (": " + ", ".join(_ch) if _ch else "")
    log_activity(db, resolve_actor(authorization, db), "update", "category", c.name, c.name, _desc)
    return {"name": c.name, "color": c.color}

@app.delete("/categories/{name:path}")
def delete_category(name: str, db: Session = Depends(get_db), authorization: str = Header(default="")):
    from urllib.parse import unquote
    name = unquote(name)
    c = db.query(models.Category).filter(models.Category.name == name).first()
    if not c: raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    _name = c.name
    db.delete(c); db.commit()
    log_activity(db, resolve_actor(authorization, db), "delete", "category", _name, _name,
                 f"Hapus kategori {_name}")
    return {"message": "deleted"}


# =========================
# USERS
# =========================
@app.get("/users")
def get_users(db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return [{"id": str(u.id), "username": u.username, "password": u.password,
             "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}
            for u in db.query(models.User).all()]

@app.post("/users")
def add_user(body: dict, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    existing = db.query(models.User).filter(models.User.username == body.get("username")).first()
    if existing: raise HTTPException(status_code=400, detail="Username sudah dipakai")
    u = models.User(username=body.get("username"), password=body.get("password"),
                    name=body.get("name"), role=body.get("role", "staff"),
                    email=body.get("email"), createdAt=body.get("createdAt", ""))
    db.add(u); db.commit(); db.refresh(u)
    log_activity(db, (str(_admin.id), _admin.username), "create", "user", u.id, u.username,
                 f"Tambah pengguna {u.username} (role {u.role})")
    return {"id": str(u.id), "username": u.username, "password": u.password,
            "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}

@app.put("/users/{id}")
def update_user(id: int, body: dict, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    u = db.query(models.User).filter(models.User.id == id).first()
    if not u: raise HTTPException(status_code=404, detail="User tidak ditemukan")
    existing = db.query(models.User).filter(
        models.User.username == body.get("username"), models.User.id != id).first()
    if existing: raise HTTPException(status_code=400, detail="Username sudah dipakai")
    _before = {"username": u.username, "name": u.name, "role": u.role, "email": u.email}
    _pw_changed = bool(body.get("password"))
    u.username = body.get("username", u.username)
    u.name = body.get("name", u.name)
    u.role = body.get("role", u.role)
    u.email = body.get("email", u.email)
    if body.get("password"): u.password = body["password"]
    db.commit(); db.refresh(u)
    _ch = []
    if u.username != _before["username"]: _ch.append(f"username {_before['username']}→{u.username}")
    if u.name != _before["name"]: _ch.append(f"nama {_before['name']}→{u.name}")
    if u.role != _before["role"]: _ch.append(f"role {_before['role']}→{u.role}")
    if u.email != _before["email"]: _ch.append("email diperbarui")
    if _pw_changed: _ch.append("password diubah")
    _desc = f"Ubah pengguna {u.username}" + (": " + ", ".join(_ch) if _ch else "")
    log_activity(db, (str(_admin.id), _admin.username), "update", "user", u.id, u.username, _desc)
    return {"id": str(u.id), "username": u.username, "password": u.password,
            "name": u.name, "role": u.role, "email": u.email, "createdAt": u.createdAt}

@app.delete("/users/{id}")
def delete_user(id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    u = db.query(models.User).filter(models.User.id == id).first()
    if not u: raise HTTPException(status_code=404, detail="User tidak ditemukan")
    _name = u.username
    db.delete(u); db.commit()
    log_activity(db, (str(_admin.id), _admin.username), "delete", "user", id, _name,
                 f"Hapus pengguna {_name}")
    return {"message": "deleted"}