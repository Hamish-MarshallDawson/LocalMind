"""Deciding how the web UI is exposed, and on which addresses other devices can reach it."""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from pathlib import Path

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class UnsafeExposure(RuntimeError):
    pass


@dataclass
class ServePlan:
    host: str
    port: int
    auth: tuple[str, str] | None
    urls: list[str]
    lan: bool
    https: bool = False


def is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def lan_addresses() -> list[str]:
    """Private IPv4 addresses of this machine that other devices on the network can use."""
    found: set[str] = set()
    try:
        import psutil

        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    found.add(addr.address)
    except ImportError:
        try:
            found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
        except OSError:
            pass
    usable = []
    for address in found:
        ip = ipaddress.ip_address(address)
        if ip.is_private and not ip.is_loopback and not ip.is_link_local:
            usable.append(address)
    # 192.168.x.x first: that's the home Wi-Fi address people expect, not a VPN or WSL adapter.
    return sorted(usable, key=lambda a: (not a.startswith("192.168."), not a.startswith("10."), a))


def plan(server_config, lan: bool = False, env: dict | None = None) -> ServePlan:
    env = os.environ if env is None else env
    host = "0.0.0.0" if lan else server_config.host
    password = env.get("LOCALMIND_PASSWORD") or server_config.password
    exposed = not is_loopback(host)

    if exposed and not password and not server_config.allow_lan_without_password:
        raise UnsafeExposure(
            "Refusing to open LocalMind to your network without a password: anyone on the same Wi-Fi "
            "could use its tools, which can run Python and read files on this PC.\n"
            "Set one first, e.g. in PowerShell:  $env:LOCALMIND_PASSWORD = \"choose-a-password\""
        )

    auth = (server_config.username, password) if password else None
    port = server_config.port
    mode = getattr(server_config, "https", "auto")
    https = mode == "on" or (mode == "auto" and exposed)
    scheme = "https" if https else "http"
    if exposed:
        urls = [f"{scheme}://{address}:{port}" for address in lan_addresses()] or [f"{scheme}://<this-pc's-ip>:{port}"]
    else:
        urls = [f"{scheme}://127.0.0.1:{port}"]
    return ServePlan(host=host, port=port, auth=auth, urls=urls, lan=exposed, https=https)


def ensure_certificate(directory: str | Path, addresses: list[str]) -> tuple[Path, Path]:
    """A self-signed certificate covering this PC's addresses, made once and reused.

    Browsers only grant microphone access on https:// (or localhost), so a phone on the LAN needs
    one to use voice. It's remade when the PC's LAN address changes, since the certificate names
    the addresses it's valid for.
    """
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    directory = Path(directory)
    cert_path, key_path = directory / "localmind.crt", directory / "localmind.key"
    wanted = {"127.0.0.1", *addresses}
    if cert_path.exists() and key_path.exists():
        try:
            existing = x509.load_pem_x509_certificate(cert_path.read_bytes())
            names = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            covered = {str(ip) for ip in names.get_values_for_type(x509.IPAddress)}
            if wanted <= covered and existing.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
                return cert_path, key_path
        except Exception:  # noqa: BLE001 - unreadable or odd: just make a new one
            pass

    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LocalMind on " + socket.gethostname())])
    now = dt.datetime.now(dt.timezone.utc)
    alt_names = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    alt_names += [x509.IPAddress(ipaddress.ip_address(address)) for address in sorted(wanted)]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))  # the longest Apple devices accept
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
