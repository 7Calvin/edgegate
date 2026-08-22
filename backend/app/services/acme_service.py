"""
ACME DNS-01 Challenge Service

Implements the ACME protocol (RFC 8555) directly using httpx + cryptography.
No external ACME library needed.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple, List
from uuid import UUID

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding, utils
from cryptography.x509 import CertificateSigningRequestBuilder, Name, NameAttribute
from cryptography.x509.oid import NameOID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.acme_challenge import ACMEChallenge, ACMEChallengeStatus

logger = logging.getLogger(__name__)


def _b64url(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """Base64url decode with padding."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


class ACMEService:
    """Manages ACME DNS-01 challenges for manual certificate issuance."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._directory: Optional[dict] = None
        self._account_kid: Optional[str] = None
        self._nonce: Optional[str] = None

    # ==================== Account Key Management ====================

    def _get_account_key_path(self) -> Path:
        return Path(settings.ACME_ACCOUNT_DIR) / "account_key.pem"

    def _get_or_create_account_key(self) -> rsa.RSAPrivateKey:
        """Load or generate the ACME account RSA key."""
        key_path = self._get_account_key_path()
        key_path.parent.mkdir(parents=True, exist_ok=True)

        if key_path.exists():
            pem_data = key_path.read_bytes()
            return serialization.load_pem_private_key(pem_data, password=None)

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        os.chmod(key_path, 0o600)
        logger.info("Generated new ACME account key")
        return key

    # ==================== ACME Protocol Helpers ====================

    def _get_jwk(self, key: rsa.RSAPrivateKey) -> dict:
        """Get JWK public key representation."""
        pub = key.public_key().public_numbers()
        e_bytes = pub.e.to_bytes((pub.e.bit_length() + 7) // 8, "big")
        n_bytes = pub.n.to_bytes((pub.n.bit_length() + 7) // 8, "big")
        return {
            "kty": "RSA",
            "e": _b64url(e_bytes),
            "n": _b64url(n_bytes),
        }

    def _compute_key_thumbprint(self, key: rsa.RSAPrivateKey) -> str:
        """Compute JWK Thumbprint (RFC 7638)."""
        jwk = self._get_jwk(key)
        # Canonical JSON with sorted keys, no spaces
        thumbprint_input = json.dumps(
            {"e": jwk["e"], "kty": jwk["kty"], "n": jwk["n"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(thumbprint_input).digest()
        return _b64url(digest)

    def _jws_sign(
        self,
        url: str,
        payload: Optional[dict],
        key: rsa.RSAPrivateKey,
        kid: Optional[str] = None,
        nonce: Optional[str] = None,
    ) -> dict:
        """Create a JWS (JSON Web Signature) for ACME request."""
        protected = {"alg": "RS256", "url": url}
        if nonce:
            protected["nonce"] = nonce

        if kid:
            protected["kid"] = kid
        else:
            protected["jwk"] = self._get_jwk(key)

        protected_b64 = _b64url(json.dumps(protected).encode("utf-8"))

        if payload is None:
            # POST-as-GET
            payload_b64 = ""
        elif payload == "":
            payload_b64 = ""
        else:
            payload_b64 = _b64url(json.dumps(payload).encode("utf-8"))

        signing_input = f"{protected_b64}.{payload_b64}".encode("ascii")

        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())

        return {
            "protected": protected_b64,
            "payload": payload_b64,
            "signature": _b64url(signature),
        }

    async def _get_directory(self, client: httpx.AsyncClient) -> dict:
        """Fetch ACME directory."""
        if self._directory:
            return self._directory
        resp = await client.get(settings.ACME_DIRECTORY_URL)
        resp.raise_for_status()
        self._directory = resp.json()
        return self._directory

    async def _get_nonce(self, client: httpx.AsyncClient, directory: dict) -> str:
        """Get a fresh nonce."""
        if self._nonce:
            nonce = self._nonce
            self._nonce = None
            return nonce
        resp = await client.head(directory["newNonce"])
        return resp.headers["Replay-Nonce"]

    async def _acme_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: Optional[dict],
        key: rsa.RSAPrivateKey,
        kid: Optional[str] = None,
    ) -> httpx.Response:
        """Send a signed ACME request."""
        directory = await self._get_directory(client)
        nonce = await self._get_nonce(client, directory)

        body = self._jws_sign(url, payload, key, kid=kid, nonce=nonce)
        resp = await client.post(
            url,
            json=body,
            headers={"Content-Type": "application/jose+json"},
        )

        # Save nonce for next request
        if "Replay-Nonce" in resp.headers:
            self._nonce = resp.headers["Replay-Nonce"]

        return resp

    async def _register_account(
        self, client: httpx.AsyncClient, key: rsa.RSAPrivateKey
    ) -> str:
        """Register or retrieve ACME account. Returns account KID."""
        acme_email = settings.TRAEFIK_ACME_EMAIL
        if not acme_email or "@" not in acme_email or "." not in acme_email.split("@")[-1]:
            raise Exception(
                f"Invalid ACME email: '{acme_email}'. "
                "Set TRAEFIK_ACME_EMAIL to a valid email (e.g. admin@example.com) "
                "in your .env or docker-compose environment."
            )

        directory = await self._get_directory(client)

        payload = {
            "termsOfServiceAgreed": True,
            "contact": [f"mailto:{acme_email}"],
        }

        resp = await self._acme_request(
            client, directory["newAccount"], payload, key
        )

        if resp.status_code not in (200, 201):
            raise Exception(f"ACME account registration failed: {resp.status_code} {resp.text}")

        kid = resp.headers["Location"]
        logger.info(f"ACME account registered/retrieved: {kid}")
        return kid

    def _compute_dns_challenge_value(self, token: str, thumbprint: str) -> str:
        """Compute the DNS TXT record value for a dns-01 challenge."""
        key_authorization = f"{token}.{thumbprint}"
        digest = hashlib.sha256(key_authorization.encode("utf-8")).digest()
        return _b64url(digest)

    # ==================== Business Logic ====================

    async def request_dns_challenge(
        self,
        domain: str,
        route_id: Optional[UUID],
        admin,
    ) -> Tuple[Optional[ACMEChallenge], Optional[str]]:
        """
        Start a DNS-01 ACME challenge for a domain.
        Returns (challenge, error).
        """
        try:
            # Check for existing pending challenge
            result = await self.db.execute(
                select(ACMEChallenge).where(
                    ACMEChallenge.domain == domain,
                    ACMEChallenge.status == ACMEChallengeStatus.PENDING,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                return existing, None

            key = self._get_or_create_account_key()
            thumbprint = self._compute_key_thumbprint(key)

            async with httpx.AsyncClient(timeout=30.0) as client:
                # Register/get account
                logger.info(f"Requesting ACME account from {settings.ACME_DIRECTORY_URL}")
                kid = await self._register_account(client, key)

                # Create order
                directory = await self._get_directory(client)
                order_payload = {
                    "identifiers": [{"type": "dns", "value": domain}],
                }
                resp = await self._acme_request(
                    client, directory["newOrder"], order_payload, key, kid=kid
                )

                if resp.status_code not in (200, 201):
                    error_body = resp.text[:500]
                    logger.error(f"ACME newOrder failed: {resp.status_code} {error_body}")
                    return None, f"Failed to create ACME order: {resp.status_code} - {error_body}"

                order = resp.json()
                order_url = resp.headers.get("Location", "")
                finalize_url = order.get("finalize", "")

                # Get authorization
                authz_url = order["authorizations"][0]
                authz_resp = await self._acme_request(
                    client, authz_url, None, key, kid=kid
                )
                authz = authz_resp.json()

                # Find dns-01 challenge
                dns_challenge = None
                for ch in authz.get("challenges", []):
                    if ch["type"] == "dns-01":
                        dns_challenge = ch
                        break

                if not dns_challenge:
                    return None, "No dns-01 challenge found in authorization"

                token = dns_challenge["token"]
                challenge_url = dns_challenge["url"]
                txt_value = self._compute_dns_challenge_value(token, thumbprint)
                txt_name = f"_acme-challenge.{domain}"

                # Calculate expiry (challenges typically expire in 7 days)
                expires_str = order.get("expires")
                expires_at = None
                if expires_str:
                    try:
                        expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
                else:
                    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

                # Save to database
                challenge = ACMEChallenge(
                    domain=domain,
                    proxy_route_id=route_id,
                    status=ACMEChallengeStatus.PENDING,
                    txt_record_name=txt_name,
                    txt_record_value=txt_value,
                    acme_order_url=order_url,
                    acme_challenge_url=challenge_url,
                    acme_finalize_url=finalize_url,
                    acme_key_thumbprint=thumbprint,
                    acme_token=token,
                    expires_at=expires_at,
                    created_by_id=admin.id,
                )
                self.db.add(challenge)
                await self.db.commit()
                await self.db.refresh(challenge)

                logger.info(f"DNS-01 challenge created for {domain}: TXT {txt_name} = {txt_value}")
                return challenge, None

        except httpx.ConnectError as e:
            logger.error(f"Cannot reach ACME server: {e}")
            return None, f"Cannot reach ACME server ({settings.ACME_DIRECTORY_URL}). Check network connectivity from the container."
        except httpx.TimeoutException as e:
            logger.error(f"ACME server timeout: {e}")
            return None, f"ACME server request timed out after 30s. Try again later."
        except Exception as e:
            logger.error(f"Failed to create DNS-01 challenge for {domain}: {e}", exc_info=True)
            return None, f"ACME challenge failed: {str(e)}"

    def _load_domain_key(self, pem: str) -> rsa.RSAPrivateKey:
        """Load a domain private key from PEM string."""
        return serialization.load_pem_private_key(pem.encode("utf-8"), password=None)

    def _generate_domain_key(self) -> Tuple[rsa.RSAPrivateKey, str]:
        """Generate a new domain RSA key. Returns (key, pem_string)."""
        domain_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_pem = domain_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        return domain_key, key_pem

    async def verify_and_issue(self, challenge_id: UUID) -> Tuple[bool, str]:
        """
        Verify DNS record and issue certificate.
        Returns (success, message).

        The domain private key is saved to the DB BEFORE finalization so that
        retries can reuse the same key if finalization succeeded but cert save failed.
        """
        result = await self.db.execute(
            select(ACMEChallenge).where(ACMEChallenge.id == challenge_id)
        )
        challenge = result.scalar_one_or_none()
        if not challenge:
            return False, "Challenge not found"

        if challenge.status == ACMEChallengeStatus.ISSUED:
            return True, "Certificate already issued"

        if challenge.status not in (ACMEChallengeStatus.PENDING, ACMEChallengeStatus.VERIFIED, ACMEChallengeStatus.FAILED):
            return False, f"Challenge in unexpected state: {challenge.status}"

        try:
            key = self._get_or_create_account_key()

            # Load or generate domain key EARLY and persist to DB before finalization.
            # This ensures retries can reuse the same key if finalization succeeded
            # but the subsequent cert download/save failed.
            if challenge.private_key_pem:
                logger.info(f"Reusing saved domain key for {challenge.domain}")
                domain_key = self._load_domain_key(challenge.private_key_pem)
                key_pem = challenge.private_key_pem
            else:
                logger.info(f"Generating new domain key for {challenge.domain}")
                domain_key, key_pem = self._generate_domain_key()
                # Save key to DB immediately so it survives failures
                challenge.private_key_pem = key_pem
                await self.db.commit()

            async with httpx.AsyncClient(timeout=30.0) as client:
                kid = await self._register_account(client, key)

                # Check current order status first
                order_resp = await self._acme_request(
                    client, challenge.acme_order_url, None, key, kid=kid
                )
                order_data = order_resp.json()
                order_status = order_data.get("status")
                cert_url = order_data.get("certificate")

                logger.info(f"Order status for {challenge.domain}: {order_status}")

                # If order is already valid with a cert URL, skip verification & finalization
                if order_status == "valid" and cert_url:
                    logger.info(f"Order already valid for {challenge.domain}, downloading certificate")
                    challenge.status = ACMEChallengeStatus.VERIFIED
                    await self.db.commit()
                else:
                    # Need to verify DNS challenge if not already done
                    if challenge.status != ACMEChallengeStatus.VERIFIED:
                        # Tell ACME server to verify the challenge
                        resp = await self._acme_request(
                            client, challenge.acme_challenge_url, {}, key, kid=kid
                        )

                        if resp.status_code not in (200, 201):
                            error_msg = f"Challenge response failed: {resp.status_code} {resp.text}"
                            challenge.error_message = error_msg
                            challenge.status = ACMEChallengeStatus.FAILED
                            await self.db.commit()
                            return False, error_msg

                        # Poll authorization status
                        authz_url = order_data["authorizations"][0]

                        verified = False
                        for _ in range(12):  # max 60 seconds
                            await asyncio.sleep(5)

                            authz_resp = await self._acme_request(
                                client, authz_url, None, key, kid=kid
                            )
                            authz = authz_resp.json()
                            authz_status = authz.get("status")

                            if authz_status == "valid":
                                verified = True
                                break
                            elif authz_status == "invalid":
                                error_detail = ""
                                for ch in authz.get("challenges", []):
                                    if ch.get("type") == "dns-01" and ch.get("error"):
                                        error_detail = ch["error"].get("detail", "")
                                error_msg = f"DNS verification failed: {error_detail or 'Invalid authorization'}"
                                challenge.error_message = error_msg
                                challenge.status = ACMEChallengeStatus.FAILED
                                await self.db.commit()
                                return False, error_msg

                        if not verified:
                            challenge.error_message = "DNS verification timed out (60s). Ensure the TXT record is properly configured and DNS has propagated."
                            challenge.status = ACMEChallengeStatus.FAILED
                            await self.db.commit()
                            return False, challenge.error_message

                        challenge.status = ACMEChallengeStatus.VERIFIED
                        await self.db.commit()

                    # Re-check order status after verification
                    order_resp = await self._acme_request(
                        client, challenge.acme_order_url, None, key, kid=kid
                    )
                    order_data = order_resp.json()
                    order_status = order_data.get("status")
                    cert_url = order_data.get("certificate")

                    if order_status == "valid" and cert_url:
                        logger.info(f"Order valid after verification for {challenge.domain}")
                    elif order_status in ("ready", "pending"):
                        # Finalize order with CSR
                        csr = (
                            CertificateSigningRequestBuilder()
                            .subject_name(
                                Name([NameAttribute(NameOID.COMMON_NAME, challenge.domain)])
                            )
                            .sign(domain_key, hashes.SHA256())
                        )
                        csr_der = csr.public_bytes(serialization.Encoding.DER)

                        finalize_payload = {"csr": _b64url(csr_der)}
                        resp = await self._acme_request(
                            client, challenge.acme_finalize_url, finalize_payload, key, kid=kid
                        )

                        if resp.status_code not in (200, 201):
                            error_msg = f"Order finalization failed: {resp.status_code} {resp.text}"
                            challenge.error_message = error_msg
                            challenge.status = ACMEChallengeStatus.FAILED
                            await self.db.commit()
                            return False, error_msg

                        # Poll order until certificate is ready
                        order_data = resp.json()
                        cert_url = order_data.get("certificate")

                        if not cert_url:
                            for _ in range(12):
                                await asyncio.sleep(5)
                                order_resp = await self._acme_request(
                                    client, challenge.acme_order_url, None, key, kid=kid
                                )
                                order_data = order_resp.json()
                                if order_data.get("status") == "valid" and order_data.get("certificate"):
                                    cert_url = order_data["certificate"]
                                    break
                                elif order_data.get("status") == "invalid":
                                    error_msg = "Order became invalid after finalization"
                                    challenge.error_message = error_msg
                                    challenge.status = ACMEChallengeStatus.FAILED
                                    await self.db.commit()
                                    return False, error_msg
                    else:
                        error_msg = f"Order in unexpected state: {order_status}"
                        challenge.error_message = error_msg
                        challenge.status = ACMEChallengeStatus.FAILED
                        await self.db.commit()
                        return False, error_msg

                if not cert_url:
                    challenge.error_message = "Timed out waiting for certificate"
                    challenge.status = ACMEChallengeStatus.FAILED
                    await self.db.commit()
                    return False, challenge.error_message

                # Download certificate
                cert_resp = await self._acme_request(
                    client, cert_url, None, key, kid=kid
                )
                cert_pem = cert_resp.text

                # Save to filesystem
                cert_dir = Path(settings.ACME_CERTS_DIR) / challenge.domain
                cert_dir.mkdir(parents=True, exist_ok=True)

                (cert_dir / "fullchain.pem").write_text(cert_pem)
                (cert_dir / "privkey.pem").write_text(key_pem)
                os.chmod(cert_dir / "privkey.pem", 0o600)

                # Update database
                challenge.certificate_pem = cert_pem
                challenge.status = ACMEChallengeStatus.ISSUED
                challenge.error_message = None
                await self.db.commit()

                # Apply Traefik config so it picks up the new cert
                from app.services.traefik_service import TraefikService
                traefik_service = TraefikService(self.db)
                await traefik_service.apply_config()

                logger.info(f"Certificate issued for {challenge.domain}")
                return True, "Certificate issued successfully"

        except Exception as e:
            logger.error(f"Failed to verify/issue certificate for challenge {challenge_id}: {e}")
            challenge.error_message = str(e)
            challenge.status = ACMEChallengeStatus.FAILED
            await self.db.commit()
            return False, str(e)

    # ==================== CRUD ====================

    async def get_challenge(self, challenge_id: UUID) -> Optional[ACMEChallenge]:
        result = await self.db.execute(
            select(ACMEChallenge).where(ACMEChallenge.id == challenge_id)
        )
        return result.scalar_one_or_none()

    async def list_challenges(
        self,
        status: Optional[ACMEChallengeStatus] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[ACMEChallenge], int]:
        query = select(ACMEChallenge)
        count_query = select(func.count()).select_from(ACMEChallenge)

        if status:
            query = query.where(ACMEChallenge.status == status)
            count_query = count_query.where(ACMEChallenge.status == status)

        query = query.order_by(ACMEChallenge.created_at.desc()).offset(skip).limit(limit)

        result = await self.db.execute(query)
        challenges = list(result.scalars().all())

        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        return challenges, total

    async def delete_challenge(self, challenge_id: UUID) -> Tuple[bool, Optional[str]]:
        challenge = await self.get_challenge(challenge_id)
        if not challenge:
            return False, "Challenge not found"

        await self.db.delete(challenge)
        await self.db.commit()
        return True, None
