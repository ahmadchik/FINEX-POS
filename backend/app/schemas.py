from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RegisterIn(BaseModel):
    company_name: str
    store_name: str = "Asosiy do'kon"
    full_name: str
    username: str
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    full_name: str
    username: str
    role: str
    company_id: int
    company_name: str
    store_id: Optional[int]
    store_name: Optional[str]
    plan: str
    account_no: Optional[int] = None
    permissions: list[str]
    currency: str = "UZS"
    locale: str = "uz"
    vat_percent: float = 0
    company_status: str = "TRIAL"
    trial_ends_at: Optional[str] = None
    paid_until: Optional[str] = None
    writable: bool = True
    stores: list[dict] = []


class TokenOut(BaseModel):
    access: str
    user: UserOut


class ProductIn(BaseModel):
    name: str = Field(min_length=1)
    sku: str = ""
    barcode: str = Field(min_length=1)
    category_id: Optional[int] = None
    unit: str = "dona"
    buy_price: float = 0
    sell_price: float = 0
    stock: float = 0
    min_stock: float = 0
    manufacturer: str = ""
    vat_rate: Optional[float] = None
    is_active: bool = True

    @model_validator(mode="after")
    def check_prices(self):
        if self.sell_price < self.buy_price:
            raise ValueError("Sotuv narxi xarid narxidan kam bo'lmasin")
        return self


class ProductOut(BaseModel):
    id: int
    name: str
    sku: str
    barcode: str
    category_id: Optional[int]
    category_name: Optional[str] = None
    unit: str
    buy_price: float
    sell_price: float
    stock: float
    min_stock: float
    manufacturer: str
    vat_rate: Optional[float] = None
    is_active: bool


class CategoryIn(BaseModel):
    name: str


class StockInItemIn(BaseModel):
    product_id: int
    qty: float
    buy_price: float = 0


class StockInCreate(BaseModel):
    supplier: str = ""
    note: str = ""
    items: list[StockInItemIn]


class CartItemIn(BaseModel):
    product_id: int
    qty: float
    price: Optional[float] = None


class SaleCreate(BaseModel):
    items: list[CartItemIn]
    discount: float = 0
    paid_cash: float = 0
    paid_card: float = 0
    paid_online: float = 0
    payment_type: str = "CASH"
    customer_id: Optional[int] = None
    allow_credit: bool = False
    idempotency_key: Optional[str] = None


class ReturnItemIn(BaseModel):
    id: int
    qty: float


class ReturnIn(BaseModel):
    items: list[ReturnItemIn] = []


class StoreIn(BaseModel):
    name: str = Field(min_length=1)
    address: str = ""
    phone: str = ""


class SupplierIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str = ""
    note: str = ""


class TransferItemIn(BaseModel):
    product_id: int
    qty: float


class TransferCreate(BaseModel):
    from_store_id: int
    to_store_id: int
    note: str = ""
    items: list[TransferItemIn]


class CustomerPatch(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None
    credit_limit: Optional[float] = None


class ShiftOpenIn(BaseModel):
    opening_cash: float = 0
    note: str = ""


class ShiftCloseIn(BaseModel):
    closing_cash: float = 0
    note: str = ""


class CustomerIn(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    email: str = ""
    note: str = ""
    credit_limit: float = 0

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, v: str) -> str:
        s = "".join((v or "").split())
        if not s.isdigit():
            raise ValueError("Telefon faqat raqamlardan iborat bo'lsin")
        return s


class DebtPayIn(BaseModel):
    amount: float
    method: str = "CASH"


EXPENSE_CATEGORIES = ("Ijara", "Kommunal", "Oylik", "Transport", "Boshqa")


class ExpenseIn(BaseModel):
    category: str = "Boshqa"
    amount: float
    note: str = ""

    @field_validator("category")
    @classmethod
    def category_ok(cls, v: str) -> str:
        s = (v or "").strip() or "Boshqa"
        if s not in EXPENSE_CATEGORIES:
            raise ValueError("Noto'g'ri kategoriya")
        return s

    @field_validator("amount")
    @classmethod
    def amount_ok(cls, v: float) -> float:
        if v is None or v <= 0:
            raise ValueError("Summa faqat musbat raqam bo'lsin")
        return v


class SettingsIn(BaseModel):
    company_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    inn: Optional[str] = None
    store_name: Optional[str] = None
    store_address: Optional[str] = None
    store_phone: Optional[str] = None
    currency: Optional[str] = None
    vat_percent: Optional[float] = None
    locale: Optional[str] = None

    @field_validator("inn")
    @classmethod
    def inn_digits(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = "".join(ch for ch in str(v) if ch.isdigit())[:9]
        return s


class CashCreate(BaseModel):
    kind: str  # IN or OUT
    amount: float
    note: str = ""


class StaffIn(BaseModel):
    full_name: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: str = Field(min_length=4)
    role: str = "CASHIER"
    store_id: Optional[int] = None


class StaffPatch(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    store_id: Optional[int] = None
