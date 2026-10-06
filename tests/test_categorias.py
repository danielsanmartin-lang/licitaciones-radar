"""Las temáticas del mercado: en qué estante cae cada licitación.

Tres cosas se protegen aquí.

Las reglas, contra los falsos positivos que ya se vieron en la base real al escribirlas:
los cortafuegos de los montes, los extintores «portátiles», el «cuadro de mando» del
alumbrado público y el nombre del órgano regalando la temática.

Que la clasificación viaje con la pasada de los perfiles: lo nuevo y lo modificado se
clasifica sin una segunda lectura de la tabla, y una pasada completa lo reescribe todo.

Y que un cambio de reglas en una versión nueva reclasifique la base entera sola, sin
que haga falta acordarse de lanzar nada.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radar import categorias, db, matching
from radar.model import Licitacion, normalizar


def temas(texto: str, cpv: str = "") -> list[str]:
    return categorias.clasificar_ficha(normalizar(texto), cpv.split())


class TestReglas(unittest.TestCase):
    def test_lo_que_no_es_it_va_a_resto(self):
        self.assertEqual(temas("Obras de reurbanización de la plaza mayor", "45233000"),
                         [categorias.RESTO])

    def test_un_cpv_del_grupo_basta(self):
        self.assertEqual(temas("Suministro", "48760000"),
                         ["ciberseguridad", "licencias"])

    def test_un_termino_basta(self):
        self.assertEqual(temas("Servicio de centro de operaciones de ciberseguridad"),
                         ["ciberseguridad"])

    def test_es_multietiqueta(self):
        t = temas("Licencias de software y alojamiento en la nube del CPD", "48000000")
        self.assertIn("licencias", t)
        self.assertIn("cloud", t)
        self.assertNotIn(categorias.RESTO, t)

    def test_las_lenguas_cooficiales_cuentan(self):
        self.assertEqual(temas("Servei de ciberseguretat per a l'Ajuntament"),
                         ["ciberseguridad"])
        self.assertEqual(temas("Contracte de llicències de programari"),
                         ["software", "licencias"])

    def test_los_prefijos_cpv_son_prefijos(self):
        """72514300 (gestión de instalaciones informáticas) cae en 725: consultoría."""
        self.assertEqual(temas("Servicio", "72514300"), ["consultoria"])

    def test_la_division_72_entera_solo_cuenta_como_codigo_exacto(self):
        """72000000 es «servicios TI» a secas. Como prefijo («72») se tragaría todas las
        temáticas; como código exacto, va a consultoría y no a las demás."""
        self.assertEqual(temas("Servicio", "72000000"), ["consultoria"])

    def test_excluir_manda_sobre_los_terminos(self):
        self.assertEqual(temas("Levantamiento con nube de puntos LiDAR en la nube"),
                         [categorias.RESTO])

    def test_falsos_positivos_vistos_en_la_base_real(self):
        for texto in (
            "Mantenimiento cortafuegos, viales y otras actuaciones del monte",
            "Mantenimiento de extintores portátiles de incendios",
            "Adecuación del cuadro de mando del alumbrado público",
            "Suministro de cajas de papel para fotocopiadoras e impresoras",
            "Marquesinas fotovoltaicas con sistema de almacenamiento",
            "Estudio de impacto ambiental (EIA) y anexo IA del proyecto",
            "Suministro de centralita para los autobuses de la flota",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(temas(texto), [categorias.RESTO])

    def test_la_ia_se_reconoce_sin_cpv(self):
        self.assertEqual(temas("Plataforma de inteligencia artificial generativa"), ["ia"])
        self.assertEqual(temas("Herramientas de IA para la atención ciudadana"), ["ia"])


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.con = db.conectar(Path(self.dir.name) / "t.db")
        self.addCleanup(self.con.close)
        self.perfiles = [matching.Perfil(nombre="Prueba",
                                         terminos_fuertes=["phishing"]).preparar()]

    def guardar(self, n: int, **kw) -> int:
        base = {"fuente": "placsp:licitaciones", "id_externo": f"x:{n}",
                "objeto": "Obras de la plaza", "organo": "Ayuntamiento"}
        base.update(kw)
        db.guardar(self.con, Licitacion(**base))
        self.con.commit()
        return self.con.execute(
            "SELECT id FROM licitaciones WHERE id_externo = ?", (f"x:{n}",)).fetchone()[0]

    def temas_de(self, lic_id: int) -> list[str]:
        return sorted(f[0] for f in self.con.execute(
            "SELECT categoria FROM categorias WHERE licitacion_id = ?", (lic_id,)))


class TestClasificacionEnLaPasada(Base):
    def test_lo_nuevo_se_clasifica_en_la_pasada_incremental(self):
        uno = self.guardar(1)
        dos = self.guardar(2, objeto="Servicio de ciberseguridad")
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.assertEqual(self.temas_de(uno), [categorias.RESTO])
        self.assertEqual(self.temas_de(dos), ["ciberseguridad"])

    def test_una_ficha_modificada_se_reclasifica_y_no_acumula(self):
        lic = self.guardar(1)
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.guardar(1, objeto="Renovación del cortafuegos perimetral corporativo")
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.assertEqual(self.temas_de(lic), ["ciberseguridad"])

    def test_lo_ya_clasificado_no_se_toca_en_la_incremental(self):
        lic = self.guardar(1)
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        # Se cambia a mano para ver si la pasada lo pisa: no debe, la ficha no ha cambiado.
        self.con.execute("UPDATE categorias SET categoria = 'ia' WHERE licitacion_id = ?",
                         (lic,))
        self.guardar(2)
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.assertEqual(self.temas_de(lic), ["ia"])

    def test_una_pasada_completa_lo_reescribe_todo(self):
        lic = self.guardar(1)
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.con.execute("UPDATE categorias SET categoria = 'ia' WHERE licitacion_id = ?",
                         (lic,))
        matching.reevaluar(self.con, self.perfiles)
        self.assertEqual(self.temas_de(lic), [categorias.RESTO])

    def test_una_base_nueva_queda_al_dia_sin_otra_pasada(self):
        """La primera carga lo clasifica todo en la incremental; si no lo apuntara, el
        final de la carga repetiría el trabajo con otra pasada completa."""
        self.guardar(1)
        self.assertFalse(categorias.al_dia(self.con))
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.assertTrue(categorias.al_dia(self.con))


class TestCambioDeReglas(Base):
    def test_una_version_nueva_reclasifica_la_base_entera(self):
        lic = self.guardar(1, objeto="Servicio de ciberseguridad")
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.con.execute("DELETE FROM categorias")
        db.escribir_preferencia(self.con, categorias.CLAVE_VERSION, "0")
        self.con.commit()

        self.assertFalse(categorias.al_dia(self.con))
        resultado = categorias.asegurar_al_dia(self.con)
        self.assertEqual(resultado["clasificadas"], 1)
        self.assertEqual(self.temas_de(lic), ["ciberseguridad"])
        self.assertTrue(categorias.al_dia(self.con))
        self.assertIsNone(categorias.asegurar_al_dia(self.con), "no repite si ya está")

    def test_una_base_vacia_esta_al_dia(self):
        self.assertTrue(categorias.al_dia(self.con))
        self.assertIsNone(categorias.asegurar_al_dia(self.con))

    def test_borrar_una_ficha_se_lleva_su_clasificacion(self):
        lic = self.guardar(1)
        matching.reevaluar(self.con, self.perfiles, incremental=True)
        self.con.execute("DELETE FROM licitaciones WHERE id = ?", (lic,))
        self.assertEqual(self.temas_de(lic), [])


if __name__ == "__main__":
    unittest.main()
