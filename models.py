from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from database import Base

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String)
    name = Column(String)
    category = Column(String)
    modalPrice = Column(Float)
    sellPrice = Column(Float)
    stock = Column(Integer)
    minStock = Column(Integer)
    unit = Column(String)
    isAvailable = Column(Boolean, default=True)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    invoiceNumber = Column(String)
    date = Column(String)
    items = Column(Text)  # JSON string
    subtotal = Column(Float, default=0)
    discount = Column(Float, default=0)
    discountPct = Column(Float, default=0)
    total = Column(Float, default=0)
    profit = Column(Float, default=0)
    paymentMethod = Column(String, default="cash")
    customerName = Column(String, default="")
    customerPhone = Column(String, default="")
    nomorPolisi = Column(String, default="")
    uangBayar = Column(Float, default=0)
    notes = Column(String, default="")
    createdBy = Column(String, default="")
    createdAt = Column(String)

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True, index=True)
    productId = Column(String)
    productName = Column(String)
    type = Column(String)  # in / out / adjustment
    quantity = Column(Integer)
    previousStock = Column(Integer)
    newStock = Column(Integer)
    reason = Column(String)
    transactionId = Column(String, nullable=True)
    createdBy = Column(String)
    createdAt = Column(String)

class JasaCatJob(Base):
    __tablename__ = "jasa_cat_jobs"
    id = Column(Integer, primary_key=True, index=True)
    date = Column(String)
    customer = Column(String)
    motorType = Column(String)
    selling = Column(Float, default=0)
    cost = Column(Float, default=0)
    profit = Column(Float, default=0)
    notes = Column(String, default="")
    createdAt = Column(String)
    data = Column(Text)  # JSON lengkap asli

class PaintBatch(Base):
    __tablename__ = "paint_batches"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    cost = Column(Float, default=0)
    remainingUses = Column(Integer, default=4)

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    color = Column(String, default="#14B8A6")

class ServiceType(Base):
    __tablename__ = "service_types"
    id = Column(String, primary_key=True)  # e.g. 'cat', 'oli', 'custom_1234'
    name = Column(String, unique=True)
    color = Column(String, default="#14B8A6")
    prices = Column(Text, default="{}")    # JSON: { bebek, matic, sport }
    modal = Column(Text, default="{}")     # JSON: { bebek, matic, sport }
    linkedCategory = Column(String, nullable=True, default=None)  # kategori produk terhubung

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True)
    password = Column(String)
    name = Column(String)
    role = Column(String, default="staff")
    email = Column(String)
    createdAt = Column(String)
