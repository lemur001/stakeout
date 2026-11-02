"""Connect mail adapters only to validated public addresses, without a second DNS lookup."""
import socket
from .core import DomainError, is_public_address


def public_socket(host,port,timeout):
    records=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    addresses=list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not is_public_address(address) for address in addresses):
        raise DomainError('Mail providers must resolve exclusively to public IP addresses.')
    last=None
    for address in addresses:
        try:return socket.create_connection((address,port),timeout)
        except OSError as exc:last=exc
    raise last
