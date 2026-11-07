"""网络辅助工具：本机 IP 探测 + 自签名证书生成（HTTPS）。

- local_ipv4()：取本机在局域网中的主 IPv4 地址，用于提示其他电脑的访问地址。
- default_cert_paths()：返回默认的私钥 / 证书路径（数据目录下的 certs/）。
- ensure_self_signed_cert()：证书不存在时用 cryptography 生成自签名证书。

cryptography 为惰性导入：仅在真正需要生成证书时加载，避免影响启动速度；
未安装时抛出带安装提示的 RuntimeError。
"""
import datetime
import ipaddress
import os
import socket
import tempfile


def _is_ascii(text):
    try:
        str(text).encode("ascii")
        return True
    except (UnicodeEncodeError, AttributeError):
        return False


def local_ipv4():
    """返回本机在局域网中的主 IPv4 地址；探测失败返回 127.0.0.1。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不真正发包，只为让系统选出到外部网络所用的本地地址。
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


def all_local_ipv4():
    """枚举本机所有 IPv4 地址（用于写进证书的 SAN，保证局域网 IP 可访问）。"""
    ips = {"127.0.0.1"}
    primary = local_ipv4()
    if primary:
        ips.add(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ":" not in ip:
                ips.add(ip)
    except Exception:
        pass
    return sorted(ips)


def cert_dir(data_dir=""):
    """返回存放 HTTPS 证书的目录。

    llama-server 无法打开路径含非 ASCII 字符（中文等）的 --ssl-key-file /
    --ssl-cert-file，会误报 "couldn't bind HTTP server socket" 而启动失败。
    因此当数据目录含非 ASCII 字符时，自动回退到纯英文的系统目录。
    """
    primary = os.path.join(data_dir, "certs") if data_dir else ""
    candidates = [primary]
    for env in ("LOCALAPPDATA", "APPDATA", "ProgramData"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "LLamaLauncher", "certs"))
    candidates.append(os.path.join(tempfile.gettempdir(), "LLamaLauncher", "certs"))
    for c in candidates:
        if c and _is_ascii(c):
            return c
    return primary or candidates[-1]


def default_cert_paths(data_dir):
    """返回 (私钥路径, 证书路径)，位于 cert_dir() 下。"""
    d = cert_dir(data_dir)
    return (os.path.join(d, "llama-server.key"),
            os.path.join(d, "llama-server.crt"))


def ensure_self_signed_cert(key_path, cert_path, common_name="llama-server"):
    """确保证书存在：缺失时生成自签名证书（PEM 私钥 + PEM 证书）。

    返回 (key_path, cert_path)。cryptography 未安装时抛出 RuntimeError。
    """
    if os.path.isfile(key_path) and os.path.isfile(cert_path):
        return key_path, cert_path

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as e:  # pragma: no cover - 依赖缺失时的友好提示
        raise RuntimeError(
            "生成 HTTPS 证书需要 cryptography 库，请先安装：\n"
            "    pip install cryptography") from e

    try:
        os.makedirs(os.path.dirname(key_path) or ".", exist_ok=True)
    except Exception:
        pass

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    san = [x509.DNSName("localhost")]
    for ip in all_local_ipv4():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return key_path, cert_path
