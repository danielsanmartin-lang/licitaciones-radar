"""Capa de red. Sin acceso a internet: solo se comprueba el bundle de CAs.

Es el fallo más probable de todo el proyecto: si el bundle pierde las raíces de la
FNMT, PLACSP deja de responder con un error de TLS que no se parece en nada a
"faltan certificados".
"""

import ssl
import unittest

from radar import net


class TestBundleCA(unittest.TestCase):
    def test_el_bundle_existe(self):
        self.assertTrue(
            net.BUNDLE_CA.exists(),
            f"falta {net.BUNDLE_CA}: regenéralo con herramientas/regenerar_ca_bundle.py",
        )

    def test_contiene_las_raices_de_la_administracion_espanola(self):
        huellas = net._huellas_del_bundle(net.BUNDLE_CA)
        faltan = net.HUELLAS_ESPERADAS - huellas
        self.assertEqual(
            faltan, set(),
            "sin estas raíces (FNMT-RCM / Izenpe) PLACSP falla el handshake TLS",
        )

    def test_el_bundle_trae_tambien_las_ca_comerciales(self):
        """Se empaqueta el almacén completo: los Python de python.org vienen sin
        raíces cargadas y, si solo lleváramos las españolas, TED y Socrata
        fallarían."""
        huellas = net._huellas_del_bundle(net.BUNDLE_CA)
        self.assertGreater(len(huellas), 80, "el bundle parece recortado")

    def test_el_contexto_verifica_de_verdad(self):
        ctx = net.contexto_ssl()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(ctx.cert_store_stats()["x509_ca"], 80)


if __name__ == "__main__":
    unittest.main()
