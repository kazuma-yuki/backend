"""
Jalankan script ini di folder backend/:
  python import_products.py

Pastikan backend sudah jalan (uvicorn main:app --reload)
"""
import urllib.request, json

BASE = "http://localhost:8000"

def post(path, data):
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 400:  # sudah ada, skip
            return True
        print(f"  ERROR {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

# =====================
# CATEGORIES
# =====================
categories = [
    {"name": "Spare Part", "color": "#F97316"},
    {"name": "Oli",        "color": "#EC4899"},
    {"name": "Ban",        "color": "#14B8A6"},
    {"name": "Velg",       "color": "#6366F1"},
    {"name": "oli",        "color": "#EC4899"},
    {"name": "knalpot",    "color": "#8B5CF6"},
]

print("=== Import Kategori ===")
for c in categories:
    ok = post("/categories", c)
    print(f"{'OK' if ok else 'GAGAL'}: {c['name']}")

# =====================
# PRODUCTS
# =====================
products = [
  {"code": "125 body mw", "name": "body motor wave 125", "category": "Spare Part", "modalPrice": 2500000.0, "sellPrice": 3300000.0, "stock": 4, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "", "name": "behel", "category": "Spare Part", "modalPrice": 200000.0, "sellPrice": 280000.0, "stock": 4, "minStock": 2, "unit": "Pcs", "isAvailable": True},
  {"code": "sb", "name": "spakbor belakang", "category": "Spare Part", "modalPrice": 170000.0, "sellPrice": 185000.0, "stock": 4, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "st", "name": "stang", "category": "Spare Part", "modalPrice": 190000.0, "sellPrice": 280000.0, "stock": 3, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "lhs", "name": "lighsil", "category": "Spare Part", "modalPrice": 150000.0, "sellPrice": 250000.0, "stock": 3, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "dm", "name": "dasi depan", "category": "Spare Part", "modalPrice": 100000.0, "sellPrice": 180000.0, "stock": 4, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "bth", "name": "breket tree hole", "category": "Spare Part", "modalPrice": 100000.0, "sellPrice": 130000.0, "stock": 2, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "sl", "name": "stoplamp", "category": "Spare Part", "modalPrice": 170000.0, "sellPrice": 270000.0, "stock": 2, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "sypl", "name": "sayap luar", "category": "Spare Part", "modalPrice": 250000.0, "sellPrice": 430000.0, "stock": 3, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "sypd", "name": "sayap dalam", "category": "Spare Part", "modalPrice": 250000.0, "sellPrice": 430000.0, "stock": 5, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "bp", "name": "batok kepala", "category": "Spare Part", "modalPrice": 250000.0, "sellPrice": 375000.0, "stock": 3, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "ld", "name": "Lampu depan", "category": "Spare Part", "modalPrice": 370000.0, "sellPrice": 480000.0, "stock": 4, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "sbs", "name": "spionn", "category": "Spare Part", "modalPrice": 150000.0, "sellPrice": 250000.0, "stock": 5, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "", "name": "ban", "category": "Ban", "modalPrice": 110000.0, "sellPrice": 350000.0, "stock": 5, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "ol", "name": "oli", "category": "oli", "modalPrice": 50000.0, "sellPrice": 100000.0, "stock": 4, "minStock": 1, "unit": "Botol", "isAvailable": True},
  {"code": "knp", "name": "knalpot", "category": "knalpot", "modalPrice": 200000.0, "sellPrice": 350000.0, "stock": 4, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "", "name": "ban motor", "category": "Ban", "modalPrice": 300000.0, "sellPrice": 400000.0, "stock": 5, "minStock": 1, "unit": "Pcs", "isAvailable": True},
  {"code": "STANGD-865", "name": "stang depan", "category": "Spare Part", "modalPrice": 250000.0, "sellPrice": 400000.0, "stock": 5, "minStock": 1, "unit": "Pcs", "isAvailable": True},
]

print("\n=== Import Produk ===")
for p in products:
    ok = post("/products", p)
    print(f"{'OK' if ok else 'GAGAL'}: {p['name']}")

print("\nSelesai! Refresh browser.")
