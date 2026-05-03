"""
M-Pesa Daraja API client.

Handles OAuth token management and C2B URL registration.
All network calls use httpx with timeouts.

Required settings:
    MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET,
    MPESA_SHORTCODE, MPESA_ENV (sandbox|production),
    MPESA_CONFIRM_URL, MPESA_VALIDATE_URL
"""
import base64
import logging
from datetime import UTC, datetime, timedelta

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Safaricom's known production + sandbox callback IP ranges.
SAFARICOM_IPS = {
    "196.201.214.200", "196.201.214.206", "196.201.213.114",
    "196.201.214.207", "196.201.214.208", "196.201.213.44",
    "196.201.212.127", "196.201.212.138", "196.201.212.129",
    "196.201.212.136", "196.201.212.74",  "196.201.212.69",
}


class DarajaClient:
    """Safaricom M-Pesa Daraja API client with automatic token refresh."""

    _instance = None

    def __new__(cls):
        # Singleton so the cached token is shared across requests in one process.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._token: str | None = None
            cls._instance._token_expiry: datetime | None = None
        return cls._instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        env = getattr(settings, "MPESA_ENV", "sandbox")
        return (
            "https://api.safaricom.co.ke"
            if env == "production"
            else "https://sandbox.safaricom.co.ke"
        )

    @property
    def _auth_header(self) -> str:
        key = getattr(settings, "MPESA_CONSUMER_KEY", "")
        secret = getattr(settings, "MPESA_CONSUMER_SECRET", "")
        encoded = base64.b64encode(f"{key}:{secret}".encode()).decode()
        return f"Basic {encoded}"

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """Return valid OAuth2 token, refreshing 1 minute before expiry."""
        now = datetime.now(tz=UTC)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        url = f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials"
        try:
            resp = httpx.get(
                url, headers={"Authorization": self._auth_header}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expiry = now + timedelta(seconds=3540)
            logger.info("Daraja: OAuth token refreshed successfully.")
            return self._token
        except httpx.HTTPError as exc:
            logger.error("Daraja: OAuth token refresh failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # C2B URL Registration
    # ------------------------------------------------------------------

    def register_c2b_urls(self) -> dict:
        """Register Validation and Confirmation URLs with Daraja."""
        token = self.get_access_token()
        url = f"{self.base_url}/mpesa/c2b/v1/registerurl"
        payload = {
            "ShortCode": getattr(settings, "MPESA_SHORTCODE", ""),
            "ResponseType": "Completed",
            "ConfirmationURL": getattr(settings, "MPESA_CONFIRM_URL", ""),
            "ValidationURL": getattr(settings, "MPESA_VALIDATE_URL", ""),
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Daraja: C2B URLs registered: %s", data)
            return data
        except httpx.HTTPError as exc:
            logger.error("Daraja: C2B URL registration failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # STK Push (Lipa Na M-Pesa Online)
    # ------------------------------------------------------------------

    def stk_push(self, phone: str, amount: int, reference: str, description: str = "") -> dict:
        """Trigger an STK Push (Lipa Na M-Pesa Online) request."""
        token = self.get_access_token()
        url = f"{self.base_url}/mpesa/stkpush/v1/processrequest"

        shortcode = getattr(settings, "MPESA_SHORTCODE", "")
        passkey = getattr(settings, "MPESA_PASSKEY", "")
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")

        password_str = f"{shortcode}{passkey}{timestamp}"
        password = base64.b64encode(password_str.encode()).decode()

        # Phone must be 2547XXXXXXXX
        formatted_phone = phone.replace("+", "").strip()
        if formatted_phone.startswith("0"):
            formatted_phone = f"254{formatted_phone[1:]}"

        payload = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": formatted_phone,
            "PartyB": shortcode,
            "PhoneNumber": formatted_phone,
            "CallBackURL": getattr(settings, "MPESA_STK_CALLBACK_URL", ""),
            "AccountReference": reference[:12],
            "TransactionDesc": description[:20] or "Rent Payment",
        }

        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("Daraja: STK Push triggered for %s: %s", phone, data)
            return data
        except httpx.HTTPError as exc:
            logger.error("Daraja: STK Push failed: %s", exc)
            raise


# Module-level singleton — import this everywhere.

daraja = DarajaClient()
