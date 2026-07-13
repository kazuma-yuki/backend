"""
migrate_to_postgres.py
──────────────────────
Script untuk migrasi data dari SQLite (garage.db) ke PostgreSQL.

Cara pakai:
    1. Pastikan PostgreSQL sudah jalan dan database sudah dibuat:
         createdb garage_pi
       atau lewat psql:
         CREATE DATABASE garage_pi;

    2. Install dependencies:
         pip install sqlalchemy psycopg2-binary python-dotenv

    3. Set DATABASE_URL di .env atau langsung di terminal:
         export DATABASE_URL=postgresql://postgres:password@localhost:5432/garage_pi

    4. Jalankan script ini dari folder backend/:
         python migrate_to_postgres.py

    Script ini akan:
    - Buat semua tabel di PostgreSQL
    - Salin semua data dari garage.db ke PostgreSQL
    - Aman dijalankan berkali-kali (skip data yang sudah ada)
"""

import os
import json
import sqlite3
from dotenv import load_dotenv

load_dotenv()

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "garage.db")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/garage_pi")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Setup SQLAlchemy untuk PostgreSQL ─────────────────────────────────────────
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pg_engine = create_engine(DATABASE_URL)
PgSession = sessionmaker(bind=pg_engine)

import models
models.Base.metadata.create_all(bind=pg_engine)
print("✓ Tabel PostgreSQL siap")

# ── Buka koneksi SQLite ────────────────────────────────────────────────────────
if not os.path.exists(SQLITE_PATH):
    print(f"⚠  File SQLite tidak ditemukan di: {SQLITE_PATH}")
    print("   Tidak ada data lama yang perlu dipindahkan.")
    exit(0)

sqlite_conn = sqlite3.connect(SQLITE_PATH)
sqlite_conn.row_factory = sqlite3.Row
cursor = sqlite_conn.cursor()

pg_db = PgSession()

def table_exists(conn, table_name):
    r = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'").fetchone()
    return r is not None

# ── 1. Products ────────────────────────────────────────────────────────────────
if table_exists(cursor, "products"):
    rows = cursor.execute("SELECT * FROM products").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.Product).filter(models.Product.id == r["id"]).first()
        if not exists:
            pg_db.add(models.Product(
                id=r["id"], code=r["code"], name=r["name"], category=r["category"],
                modalPrice=r["modalPrice"], sellPrice=r["sellPrice"], stock=r["stock"],
                minStock=r["minStock"], unit=r["unit"],
                isAvailable=bool(r["isAvailable"]) if r["isAvailable"] is not None else True,
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Products: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 2. Transactions ────────────────────────────────────────────────────────────
if table_exists(cursor, "transactions"):
    rows = cursor.execute("SELECT * FROM transactions").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.Transaction).filter(models.Transaction.id == r["id"]).first()
        if not exists:
            pg_db.add(models.Transaction(
                id=r["id"],
                invoiceNumber=r["invoiceNumber"] or "",
                date=r["date"] or "",
                items=r["items"] or "[]",
                subtotal=float(r["subtotal"] or 0),
                discount=float(r["discount"] or 0),
                discountPct=float(r["discountPct"] or 0),
                total=float(r["total"] or 0),
                profit=float(r["profit"] or 0),
                paymentMethod=r["paymentMethod"] or "cash",
                customerName=r["customerName"] or "",
                customerPhone=r["customerPhone"] or "",
                nomorPolisi=r["nomorPolisi"] or "",
                uangBayar=float(r["uangBayar"] or 0),
                notes=r["notes"] or "",
                createdBy=r["createdBy"] or "",
                createdAt=r["createdAt"] or "",
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Transactions: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 3. Stock Movements ─────────────────────────────────────────────────────────
if table_exists(cursor, "stock_movements"):
    rows = cursor.execute("SELECT * FROM stock_movements").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.StockMovement).filter(models.StockMovement.id == r["id"]).first()
        if not exists:
            pg_db.add(models.StockMovement(
                id=r["id"],
                productId=str(r["productId"] or ""),
                productName=r["productName"] or "",
                type=r["type"] or "in",
                quantity=int(r["quantity"] or 0),
                previousStock=int(r["previousStock"] or 0),
                newStock=int(r["newStock"] or 0),
                reason=r["reason"] or "",
                transactionId=str(r["transactionId"]) if r["transactionId"] else None,
                createdBy=r["createdBy"] or "",
                createdAt=r["createdAt"] or "",
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Stock Movements: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 4. Jasa Cat Jobs ───────────────────────────────────────────────────────────
if table_exists(cursor, "jasa_cat_jobs"):
    rows = cursor.execute("SELECT * FROM jasa_cat_jobs").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.JasaCatJob).filter(models.JasaCatJob.id == r["id"]).first()
        if not exists:
            pg_db.add(models.JasaCatJob(
                id=r["id"],
                date=r["date"] or "",
                customer=r["customer"] or "",
                motorType=r["motorType"] or "",
                selling=float(r["selling"] or r.get("sellingPrice", 0) or 0),
                cost=float(r["cost"] or r.get("totalCost", 0) or 0),
                profit=float(r["profit"] or 0),
                notes=r["notes"] or "",
                createdAt=r["createdAt"] or "",
                data=r["data"] or "{}",
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Jasa Cat Jobs: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 5. Paint Batches ───────────────────────────────────────────────────────────
if table_exists(cursor, "paint_batches"):
    rows = cursor.execute("SELECT * FROM paint_batches").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.PaintBatch).filter(models.PaintBatch.id == r["id"]).first()
        if not exists:
            pg_db.add(models.PaintBatch(
                id=r["id"], name=r["name"],
                cost=float(r["cost"] or 0),
                remainingUses=int(r["remainingUses"] or 4),
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Paint Batches: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 6. Categories ──────────────────────────────────────────────────────────────
if table_exists(cursor, "categories"):
    rows = cursor.execute("SELECT * FROM categories").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.Category).filter(models.Category.name == r["name"]).first()
        if not exists:
            pg_db.add(models.Category(
                id=r["id"], name=r["name"], color=r["color"] or "#14B8A6",
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Categories: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 7. Service Types ───────────────────────────────────────────────────────────
if table_exists(cursor, "service_types"):
    rows = cursor.execute("SELECT * FROM service_types").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.ServiceType).filter(models.ServiceType.id == r["id"]).first()
        if not exists:
            pg_db.add(models.ServiceType(
                id=r["id"], name=r["name"], color=r["color"] or "#14B8A6",
                prices=r["prices"] or "{}",
                modal=r["modal"] or "{}",
                linkedCategory=r["linkedCategory"] if "linkedCategory" in r.keys() else None,
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Service Types: {count} baris dipindahkan (dari {len(rows)} total)")

# ── 8. Users ───────────────────────────────────────────────────────────────────
if table_exists(cursor, "users"):
    rows = cursor.execute("SELECT * FROM users").fetchall()
    count = 0
    for r in rows:
        exists = pg_db.query(models.User).filter(models.User.id == r["id"]).first()
        if not exists:
            pg_db.add(models.User(
                id=r["id"], username=r["username"], password=r["password"],
                name=r["name"], role=r["role"] or "staff",
                email=r["email"] or "", createdAt=r["createdAt"] or "",
            ))
            count += 1
    pg_db.commit()
    print(f"✓ Users: {count} baris dipindahkan (dari {len(rows)} total)")

# ── Sinkronisasi sequence ID PostgreSQL ───────────────────────────────────────
# Penting! Supaya auto-increment ID tidak bentrok dengan data yang baru dipindahkan
print("\nSinkronisasi sequence ID...")
tables_with_int_pk = [
    ("products", "products_id_seq"),
    ("transactions", "transactions_id_seq"),
    ("stock_movements", "stock_movements_id_seq"),
    ("jasa_cat_jobs", "jasa_cat_jobs_id_seq"),
    ("paint_batches", "paint_batches_id_seq"),
    ("categories", "categories_id_seq"),
    ("users", "users_id_seq"),
]
with pg_engine.connect() as conn:
    for table, seq in tables_with_int_pk:
        try:
            conn.execute(text(
                f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1))"
            ))
            conn.commit()
            print(f"  ✓ {seq} diperbarui")
        except Exception as e:
            print(f"  ⚠  {seq}: {e}")

sqlite_conn.close()
pg_db.close()
print("\n✅ Migrasi selesai!")
