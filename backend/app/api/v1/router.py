"""API v1 router aggregation."""

from fastapi import APIRouter

api_router = APIRouter()

# Register module routers
from app.api.v1.auth import router as auth_router
from app.api.v1.products import router as products_router
from app.api.v1.orders import router as orders_router
from app.api.v1.materials import router as materials_router
from app.api.v1.modules import (
    pricing_router,
    listing_router,
    fulfillment_router,
    finance_router,
)
from app.api.v1.customer_service import router as customer_service_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.sourcing import router as sourcing_router
from app.api.v1.miaoshou import router as miaoshou_router
from app.api.v1.discovery import router as discovery_router
from app.api.v1.alibaba1688 import router as alibaba1688_router
from app.api.v1.market_reports import router as market_reports_router
from app.api.v1.fastmoss import router as fastmoss_router
from app.api.v1.collect_box import router as collect_box_router
from app.api.v1.workbench import router as workbench_router
from app.api.v1.listing import router as listing_tasks_router
from app.api.v1.exchange_rates import router as exchange_rates_router
from app.api.v1.system_settings import router as system_settings_router

api_router.include_router(auth_router)
api_router.include_router(products_router)
api_router.include_router(orders_router)
api_router.include_router(materials_router)
api_router.include_router(pricing_router)
api_router.include_router(listing_router)
api_router.include_router(fulfillment_router)
api_router.include_router(customer_service_router, tags=["CustomerService"])
api_router.include_router(finance_router)
api_router.include_router(exchange_rates_router)
api_router.include_router(system_settings_router)
api_router.include_router(dashboard_router)
api_router.include_router(sourcing_router)
api_router.include_router(miaoshou_router)
api_router.include_router(discovery_router)
api_router.include_router(alibaba1688_router)
api_router.include_router(market_reports_router)
api_router.include_router(fastmoss_router)
api_router.include_router(collect_box_router)
api_router.include_router(workbench_router)
api_router.include_router(listing_tasks_router)
