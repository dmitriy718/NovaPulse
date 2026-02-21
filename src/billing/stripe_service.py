"""
Stripe Service - Create customers, subscriptions, and handle webhooks.

Enables clients (tenants) via Stripe Checkout; webhooks update tenant status
so access can be gated by subscription (active / past_due / canceled).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.core.logger import get_logger

logger = get_logger("stripe")


class StripeService:
    """
    Stripe integration for SaaS billing.
    - Create customer + Checkout Session (monthly subscription)
    - Verify webhook signature and update tenant status
    """

    def __init__(
        self,
        secret_key: str = "",
        webhook_secret: str = "",
        price_id: str = "",
        price_id_pro: str = "",
        price_id_premium: str = "",
        currency: str = "usd",
        db=None,
    ):
        self.secret_key = secret_key or os.getenv("STRIPE_SECRET_KEY", "")
        self.webhook_secret = webhook_secret or os.getenv("STRIPE_WEBHOOK_SECRET", "")
        legacy_price = price_id or os.getenv("STRIPE_PRICE_ID", "")
        self.price_id_pro = price_id_pro or os.getenv("STRIPE_PRICE_ID_PRO", "") or legacy_price
        self.price_id_premium = price_id_premium or os.getenv("STRIPE_PRICE_ID_PREMIUM", "")
        self.price_id = self.price_id_pro  # Backward-compatible alias.
        self.currency = currency
        self._db = db
        self._price_ids: Dict[str, str] = {
            "pro": self.price_id_pro,
            "premium": self.price_id_premium,
        }
        self._enabled = bool(self.secret_key and any(self._price_ids.values()))
        self._stripe = None  # cached module ref after one-time init

    @property
    def enabled(self) -> bool:
        return self._enabled

    def has_plan(self, plan: str) -> bool:
        """Return True when a plan is available for checkout."""
        plan_name = (plan or "pro").strip().lower()
        if plan_name == "free":
            return True
        return bool(self._price_ids.get(plan_name, ""))

    def set_db(self, db) -> None:
        """Inject database for tenant updates."""
        self._db = db

    def _api(self):
        """Lazy import Stripe and set api_key once (thread-safe after first call)."""
        if self._stripe is None:
            import stripe
            stripe.api_key = self.secret_key
            self._stripe = stripe
        return self._stripe

    # -------------------------------------------------------------------------
    # Create customer and checkout
    # -------------------------------------------------------------------------

    def create_customer(self, tenant_id: str, name: str, email: Optional[str] = None) -> Optional[str]:
        """
        Create a Stripe Customer for the tenant. Returns customer id (cus_...) or None.
        """
        if not self._enabled:
            return None
        try:
            stripe = self._api()
            params = {"name": name, "metadata": {"tenant_id": tenant_id}}
            if email:
                params["email"] = email
            customer = stripe.Customer.create(**params)
            return customer.id
        except Exception as e:
            logger.error("Stripe create_customer failed", tenant_id=tenant_id, error=str(e))
            return None

    def create_checkout_session(
        self,
        tenant_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
        customer_id: Optional[str] = None,
        plan: str = "pro",
    ) -> Optional[Dict[str, Any]]:
        """
        Create a Stripe Checkout Session for subscription.
        Returns { "url": checkout_url, "session_id": ... } or None.
        """
        if not self._enabled:
            return None
        try:
            plan_name = (plan or "pro").strip().lower()
            price_id = self._price_ids.get(plan_name, "")
            if not price_id:
                logger.warning(
                    "Stripe checkout rejected: plan not configured",
                    plan=plan_name,
                )
                return None
            stripe = self._api()
            params = {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {"tenant_id": tenant_id, "plan": plan_name},
                "subscription_data": {"metadata": {"tenant_id": tenant_id, "plan": plan_name}},
            }
            if customer_id:
                params["customer"] = customer_id
            elif customer_email:
                params["customer_email"] = customer_email
            session = stripe.checkout.Session.create(**params)
            return {
                "url": session.url,
                "session_id": session.id,
                "plan": plan_name,
                "price_id": price_id,
                "customer_id": getattr(session, "customer", None) or (session.customer if hasattr(session, "customer") else None),
            }
        except Exception as e:
            logger.error("Stripe create_checkout_session failed", tenant_id=tenant_id, error=str(e))
            return None

    def create_billing_portal_session(
        self, customer_id: str, return_url: str
    ) -> Optional[str]:
        """Create a Stripe Customer Portal session URL (manage subscription, payment method)."""
        if not self._enabled:
            return None
        try:
            stripe = self._api()
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return session.url
        except Exception as e:
            logger.error("Stripe create_billing_portal_session failed", error=str(e))
            return None

    # -------------------------------------------------------------------------
    # Webhook: verify and handle events
    # -------------------------------------------------------------------------

    def verify_webhook(self, payload: bytes, signature_header: str) -> bool:
        """Verify Stripe webhook signature. Returns True if valid."""
        if not self.webhook_secret:
            return False
        try:
            stripe = self._api()
            stripe.Webhook.construct_event(
                payload, signature_header, self.webhook_secret
            )
            return True
        except Exception as e:
            logger.warning("Stripe webhook verification failed", error=str(e))
            return False

    async def handle_webhook_event(self, event: Dict[str, Any]) -> None:
        """
        Handle Stripe webhook event: update tenant status.
        Events: checkout.session.completed, customer.subscription.updated/deleted,
        invoice.paid, invoice.payment_failed.
        """
        if not self._db:
            logger.warning("Stripe webhook: no db, skipping tenant update")
            return
        kind = event.get("type") or ""
        data = event.get("data", {}).get("object", {})

        if kind == "checkout.session.completed":
            await self._on_checkout_completed(data)
        elif kind == "customer.subscription.updated":
            await self._on_subscription_updated(data)
        elif kind == "customer.subscription.deleted":
            await self._on_subscription_deleted(data)
        elif kind == "invoice.paid":
            await self._on_invoice_paid(data)
        elif kind == "invoice.payment_failed":
            await self._on_invoice_payment_failed(data)
        else:
            logger.debug("Stripe webhook unhandled event", type=kind)

    async def _on_checkout_completed(self, session: Dict[str, Any]) -> None:
        tenant_id = (session.get("metadata") or {}).get("tenant_id")
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        if not tenant_id:
            logger.warning("Stripe checkout.session.completed missing tenant_id in metadata")
            return
        await self._db.upsert_tenant(
            tenant_id,
            name=tenant_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            status="active",
        )
        logger.info("Tenant enabled via Stripe checkout", tenant_id=tenant_id)

    async def _on_subscription_updated(self, subscription: Dict[str, Any]) -> None:
        tenant_id = (subscription.get("metadata") or {}).get("tenant_id")
        if not tenant_id and self._db:
            tenant = await self._db.get_tenant_by_stripe_subscription(subscription.get("id", ""))
            tenant_id = tenant["id"] if tenant else None
        if not tenant_id:
            return
        status = subscription.get("status")
        _STATUS_MAP = {
            "active": "active",
            "trialing": "active",
            "past_due": "past_due",
            "canceled": "canceled",
            "unpaid": "canceled",
        }
        our_status = _STATUS_MAP.get(status, status)
        await self._db.set_tenant_status(tenant_id, our_status)
        logger.info("Tenant subscription updated", tenant_id=tenant_id, status=our_status)

    async def _on_subscription_deleted(self, subscription: Dict[str, Any]) -> None:
        tenant_id = (subscription.get("metadata") or {}).get("tenant_id")
        if not tenant_id and self._db:
            tenant = await self._db.get_tenant_by_stripe_subscription(subscription.get("id", ""))
            tenant_id = tenant["id"] if tenant else None
        if not tenant_id:
            return
        await self._db.set_tenant_status(tenant_id, "canceled")
        logger.info("Tenant subscription canceled", tenant_id=tenant_id)

    async def _on_invoice_paid(self, invoice: Dict[str, Any]) -> None:
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        # Optionally extend subscription_metadata to tenant; for now subscription.updated handles it
        logger.debug("Stripe invoice.paid", subscription=subscription_id)

    async def _on_invoice_payment_failed(self, invoice: Dict[str, Any]) -> None:
        subscription_id = invoice.get("subscription")
        if not subscription_id:
            return
        # Find tenant by subscription_id and set past_due (or leave to subscription.updated)
        logger.warning("Stripe invoice.payment_failed", subscription=subscription_id)
