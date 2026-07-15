"""
Pydantic models with camelCase aliases for frontend compatibility.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


def to_camel(s: str) -> str:
    """Convert snake_case to camelCase."""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


class CamelModel(BaseModel):
    """Base model with camelCase alias generation."""

    model_config = {
        "alias_generator": to_camel,
        "populate_by_name": True,
        "from_attributes": True,
    }


# ---------- Fund ----------

class FundCreate(CamelModel):
    code: str
    name: str
    shares: float = 0
    cost_price: float = 0
    current_price: float = 0


class FundUpdate(CamelModel):
    code: Optional[str] = None
    name: Optional[str] = None
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    current_price: Optional[float] = None


class FundResponse(CamelModel):
    id: int
    code: str
    name: str
    shares: float
    cost_price: float
    current_price: float
    update_time: str


# ---------- Strategy ----------

class StrategyCreate(CamelModel):
    fund_id: int = Field(alias="fundId")
    name: str
    strategy_type: str = Field(alias="type")
    params: Dict[str, Any] = {}

    @field_validator("strategy_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("ma", "grid"):
            raise ValueError("strategy_type must be 'ma' or 'grid'")
        return v


class StrategyUpdate(CamelModel):
    name: Optional[str] = None
    fund_id: Optional[int] = Field(None, alias="fundId")
    strategy_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class StrategyResponse(CamelModel):
    id: int
    fund_id: int = Field(alias="fundId")
    name: str
    strategy_type: str = Field(alias="type")
    params: Dict[str, Any]
    enabled: bool
    created_at: str
    updated_at: str


# ---------- Trade ----------

class TradeCreate(CamelModel):
    fund_id: int = Field(alias="fundId")
    direction: str
    price: float
    shares: float
    strategy: Optional[str] = None
    strategy_id: Optional[int] = None

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("direction must be 'buy' or 'sell'")
        return v


class TradeResponse(CamelModel):
    id: int
    fund_id: int = Field(alias="fundId")
    direction: str
    price: float
    shares: float
    amount: float
    strategy: Optional[str] = None
    strategy_id: Optional[int] = None
    time: str
    status: str


# ---------- Daily Value ----------

class DailyValueResponse(CamelModel):
    id: int
    fund_id: int = Field(alias="fundId")
    date: str
    total_value: float


# ---------- Generic ----------

class ListResponse(BaseModel):
    data: List[Any]
    total: int


class MessageResponse(BaseModel):
    message: str


class SignalResponse(BaseModel):
    signals: List[Dict[str, Any]]
    total: int
