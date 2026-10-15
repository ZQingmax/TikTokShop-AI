"""SQLAlchemy models package - register all models here."""

from app.models.base import Base
from app.models.user import User, Role  # noqa: F401
from app.models.product import Product, ProductSKU, ProductImage, Category, Supplier  # noqa: F401
from app.models.material import Material  # noqa: F401
from app.models.order import Order, OrderItem, OrderStatusHistory  # noqa: F401
from app.models.fulfillment import PurchaseOrder, Shipment, Forwarder  # noqa: F401
from app.models.finance import FinanceRecord, ExchangeRate  # noqa: F401
from app.models.customer_service import CSSession, CSMessage, Ticket  # noqa: F401
from app.models.mapping import SKUMapping, MatchRecord  # noqa: F401
from app.models.alert import Alert  # noqa: F401
from app.models.faq import FAQ  # noqa: F401
from app.models.sourcing import SourcingCandidate, SourcingSupplier, SourcingTask, SourcingEvaluation, SourcingReview, MiaoshouSyncTask  # noqa: F401
from app.models.discovery import DiscoveryTask, DiscoveryResult  # noqa: F401
from app.models.fastmoss import FastmossTask, FastmossCatalog  # noqa: F401
from app.models.collect_box import CollectBoxItem  # noqa: F401
from app.models.workbench import WorkbenchDraft, WorkbenchAsset, WorkbenchTask  # noqa: F401
from app.models.listing import ListingTask  # noqa: F401
from app.models.sync_state import MiaoshouSyncState  # noqa: F401
from app.models.system_settings import ModelSetting, ModelUsageLog  # noqa: F401

__all__ = [
    "Base",
    "User", "Role",
    "Product", "ProductSKU", "ProductImage", "Category", "Supplier", "Material",
    "Order", "OrderItem", "OrderStatusHistory",
    "PurchaseOrder", "Shipment", "Forwarder",
    "FinanceRecord", "ExchangeRate",
    "CSSession", "CSMessage", "Ticket",
    "SKUMapping", "MatchRecord",
    "Alert",
    "FAQ",
]
