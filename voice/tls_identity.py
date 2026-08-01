from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import os
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class TlsIdentity:
    certificate_path: Path
    private_key_path: Path
    fingerprint_sha256: str

    def server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(self.certificate_path), str(self.private_key_path))
        return context


def certificate_fingerprint(certificate_path: Path) -> str:
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def ensure_tls_identity(certificate_path: Path, private_key_path: Path) -> TlsIdentity:
    certificate_path.parent.mkdir(parents=True, exist_ok=True)
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    if certificate_path.exists() and private_key_path.exists():
        return TlsIdentity(certificate_path, private_key_path, certificate_fingerprint(certificate_path))

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DjGoo"),
            x509.NameAttribute(NameOID.COMMON_NAME, "DjGoo Voice Gateway"),
        ]
    )
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("djgoo.local"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    key_temp = private_key_path.with_suffix(".tmp")
    cert_temp = certificate_path.with_suffix(".tmp")
    key_temp.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_temp.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_temp.replace(private_key_path)
    cert_temp.replace(certificate_path)
    try:
        os.chmod(private_key_path, 0o600)
    except OSError:
        pass
    return TlsIdentity(certificate_path, private_key_path, certificate_fingerprint(certificate_path))
