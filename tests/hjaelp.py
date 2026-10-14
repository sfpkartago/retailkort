"""Faelles for testene: repo-roden paa sys.path og nettet SPAERRET.

Hver testfil starter med
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import hjaelp
Testene maa aldrig kalde nettet: de skal give samme svar hver gang, koere paa et minut og
ikke belaste kildernes servere (robots.txt-reglerne gaelder ogsaa her). Et kald, der slipper
igennem en stub, fejler derfor hoejt med NetSpaerret i stedet for at ramme en vaert.
"""
import os
import socket
import sys

ROD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROD not in sys.path:
    sys.path.insert(0, ROD)


class NetSpaerret(RuntimeError):
    pass


def _spaerret(*a, **k):
    raise NetSpaerret('testene maa ikke bruge nettet - stub kaldet (tests/hjaelp.py)')


# Testene kalder main() med stubbe; de maa aldrig vente paa (eller tage) DAR-laasen.
import dawa  # noqa: E402
AEGTE_TAG_DAR_LAAS = dawa.tag_dar_laas      # til testen af selve laasen (tests/test_net.py)
dawa.tag_dar_laas = lambda navn: None

socket.socket.connect = _spaerret
socket.socket.connect_ex = _spaerret
socket.create_connection = _spaerret
socket.getaddrinfo = _spaerret
