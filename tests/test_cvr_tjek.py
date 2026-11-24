import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hjaelp  # noqa: F401  (repo-roden paa sys.path og nettet spaerret)

import datetime
import unittest
from unittest import mock

import cvr_tjek as C

IDAG = datetime.date(2026, 11, 24)


class TestAktivEnhed(unittest.TestCase):
    """En P-enhed med en KOMMENDE ophoersdato er aaben, til datoen er naaet (aabent punkt 20-10-2026; Matas
    Vestamager stod med ophoer 11-12-2026 i CVR fra efteraaret)."""

    def test_ophoersdatoen_afgoer(self):
        def e(status='aktiv', ophoer=None):
            return {'status': status, 'produktionsenhedOphoersdato': ophoer}
        self.assertTrue(C.aktiv_enhed(e(), IDAG))
        self.assertTrue(C.aktiv_enhed(e(ophoer='2026-12-11'), IDAG))
        self.assertTrue(C.aktiv_enhed(e(ophoer='2026-12-11T00:00:00.000+01:00'), IDAG))
        self.assertFalse(C.aktiv_enhed(e(ophoer='2026-11-24'), IDAG))       # ophoersdagen: lukket
        self.assertFalse(C.aktiv_enhed(e(ophoer='2025-06-01'), IDAG))
        self.assertFalse(C.aktiv_enhed(e(status='inaktiv'), IDAG))

    def test_p_enheder_beholder_en_station_med_kommende_ophoer(self):
        enheder = [{'id': 'a', 'pNummer': 1, 'status': 'aktiv', 'produktionsenhedOphoersdato': '2099-12-11',
                    'tilknyttetVirksomhedsCVRNummer': 9},
                   {'id': 'b', 'pNummer': 2, 'status': 'aktiv', 'produktionsenhedOphoersdato': '2020-01-31',
                    'tilknyttetVirksomhedsCVRNummer': 9}]

        def sider(entitet, where, felter):
            if entitet == 'CVR_Branche':
                return [{'CVREnhedsId': 'a'}, {'CVREnhedsId': 'b'}]
            if entitet == 'CVR_Produktionsenhed':
                return enheder if 'id:' in where else []
            if entitet == 'CVR_Navn':
                return [{'CVREnhedsId': i, 'vaerdi': f'Station {i}'} for i in ('a', 'b') if f'"{i}"' in where]
            if entitet == 'CVR_Adressering':
                return [{'CVREnhedsId': i, 'AdresseringAnvendelse': 'beliggenhedsadresse', 'CVRAdresse_vejnavn': 'Vej',
                         'CVRAdresse_husnummerFra': 1, 'CVRAdresse_postnummer': 2770} for i in ('a', 'b')
                        if f'"{i}"' in where]
            raise AssertionError(entitet)
        with mock.patch.object(C, '_sider', side_effect=sider), \
                mock.patch.object(C.dawa, '_q', return_value=[{'husnr': '1', 'y': 55.6, 'x': 12.6}]):
            ud = C.p_enheder()
        self.assertEqual([p['pnr'] for p in ud], [1])


if __name__ == '__main__':
    unittest.main()
