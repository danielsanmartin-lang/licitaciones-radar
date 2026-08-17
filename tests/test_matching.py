"""Casos reales verificados contra las fuentes. Son el criterio de aceptación:
si estos dejan de pasar, el filtro se ha roto o se ha vuelto ruidoso."""
import unittest

from radar.matching import cargar_perfiles, evaluar, patron, prefijo_cpv

# (debe_casar, texto, cpv, importe, fuente, etiqueta)
CASOS = [
    # --- Deben entrar: casos reales comprobados en las fuentes -------------
    (True, "Servei integral de formació i conscienciació en ciberseguretat",
     ["80511000"], 180000, "catalunya", "CCMA formación+concienciación 180k"),
    (True, "900589/24 Conscienciació i formació en matèria de ciberseguretat per al "
           "personal de l'AMB i els seus ens dependents.",
     ["80510000"], 27600, "catalunya", "Àrea Metropolitana de Barcelona 27,6k"),
    (True, "Servei d'inserció de publicitat institucional al mitjà de comunicació ràdio "
           "per a la difusió de capsules informatives per conscienciar sobre les ciberestafes",
     ["79341000"], 329900, "catalunya", "Agència de Ciberseguretat 329,9k (verbo, no sustantivo)"),
    (True, "Subministrament en modalitat de subscripció d'una eina per la generació de "
           "campanyes de phising controlat amb formació pels usuaris.",
     [], 50000, "catalunya", "phishing SIN CPV y con errata 'phising'"),
    (True, "España – Servicios de formación informática – Servicio de oficina de "
           "concienciación en ciberseguridad",
     ["80533100"], 915000, "ted", "LANTIK 915k vía TED"),
    (True, "Implantación de DMARC y protección del correo electrónico institucional",
     ["72500000"], 60000, "placsp:licitaciones", "protección de correo"),
    # J260047, Junta de Contratación del Ministerio de Cultura, 1.031.857 € de valor
    # estimado. Durante un tiempo entró por accidente: "formacion" casaba dentro de
    # "sistemas de información" y el motivo guardado hablaba de una formación que el
    # pliego no menciona. Tiene que entrar por lo que es, un contrato de ciberseguridad.
    (True, "Servicio de oficina de ciberseguridad en el ministerio de cultura, en el "
           "ámbito de los sistemas de información gestionados por la División de "
           "Tecnologías de la Información",
     ["72514300"], 1031857, "placsp:licitaciones", "oficina de ciberseguridad Min. Cultura"),
    (True, "Servicios de seguridad de los sistemas de información de la Gerencia de "
           "Informática de la Seguridad Social",
     ["72500000"], 22925795, "placsp:licitaciones", "seguridad de la información Seg. Social"),
    (True, "Asistencia para la gestión del ENS y centro de operaciones de seguridad (SOC)",
     [], 328727, "placsp:licitaciones", "SOC + ENS"),

    # --- Deben quedar fuera: falsos positivos observados ------------------
    (False, "Campaña de concienciación medioambiental y gestión de residuos urbanos",
     ["79341000"], 200000, "placsp:licitaciones", "concienciación medioambiental"),
    (False, "Servicio de formación en prevención de riesgos laborales y seguridad y salud",
     ["80500000"], 90000, "placsp:licitaciones", "prevención de riesgos laborales"),
    (False, "F260000477_492_SERVEI PER A L'EXECUCIÓ DEL PROJECTE CONTRA LA FEMINITZACIÓ "
            "DE LA POBRESA",
     ["80500000", "80510000"], 118119, "catalunya", "feminización de la pobreza"),
    (False, "Servei de docència per impartir les accions formatives ADGD178PO",
     ["80500000"], 3945, "catalunya", "formación genérica de bajo importe"),
    (False, "Campaña de sensibilización sobre seguridad vial en centros escolares",
     ["79341000"], 150000, "placsp:licitaciones", "seguridad vial"),
    (False, "Servicio de formación informática en hojas de cálculo y ofimática",
     ["80533100"], 45000, "placsp:licitaciones", "ofimática: el CPV no basta como contexto"),
    (False, "Servicio de vigilancia y seguridad privada de edificios municipales",
     ["79417000"], 500000, "placsp:licitaciones", "seguridad privada"),
    (False, "Servicio integral de concienciación en ciberseguridad",
     ["80511000"], 4000, "placsp:licitaciones", "por debajo del importe mínimo"),
    (False, "Servicio postal de notificaciones y franqueo de correo electrónico certificado",
     ["48000000"], 80000, "placsp:licitaciones", "servicio postal, no seguridad de correo"),
    # El falso positivo que contaminaba 612 de 943 matches: "formacion" dentro de
    # "información". Sin nada de seguridad en el texto no debe entrar por ahí.
    (False, "Servicio de digitalización de los sistemas de información y del archivo "
            "documental del ayuntamiento",
     ["72500000"], 250000, "placsp:licitaciones", "«información» no es «formación»"),
    (False, "Servicios de transformación digital e innovación para los ens locales",
     [], 3184553, "catalunya", "«transformació» no es «formació»"),

    # --- SPF: la sigla choca con otras cosas reales ------------------------
    # Con «spf» como término fuerte entraban diez licitaciones absurdas. Ahora es
    # ambiguo y necesita contexto de seguridad.
    (False, "Serveis de vigilància, prevenció, salvament i socorrisme a les platges "
            "amb crema solar SPF 50",
     [], 300000, "catalunya", "SPF de protección solar en socorrismo"),
    (False, "AM material oficina DFB, Entidades SPF y aytos del THB adheridos 2025",
     [], 400000, "placsp:agregadas", "SPF = Sector Público Foral"),
    (False, "Ús intensiu de l'estabulari terrestre (ratolins SPF) per a l'estudi del mecanisme",
     [], 60000, "catalunya", "SPF en estabulario de ratones"),
    (True, "Implantación de registros SPF, DKIM y DMARC para la seguridad del correo "
           "electrónico corporativo",
     ["72500000"], 45000, "placsp:licitaciones", "SPF con contexto de seguridad sí entra"),

    # --- Seguridad física, que no es seguridad de la información -----------
    # 56 M€ de vigilantes entraban en el perfil de correo por «mensajería» (de
    # recaudación) más el contexto genérico «seguridad».
    (False, "Prestaciones de servicios de seguridad, vigilantes de seguridad y auxiliares "
            "de servicios-controladores de accesos, incluida la mensajería de recaudación "
            "y el correo electrónico de contacto",
     [], 56443596, "placsp:agregadas", "vigilantes de seguridad, no seguridad de correo"),
    (True, "Servei relay, antivirus i antispam perimetral pel correu electrònic",
     ["72500000"], 60000, "catalunya", "antispam de correo sí entra"),
    (True, "Servei de seguretat del correu electrònic per a Microsoft 365 en modalitat Cloud",
     ["48730000"], 90000, "catalunya", "seguridad de correo en M365 sí entra"),
]


def hay_perfiles_propios() -> bool:
    """¿Están los términos de verdad, o solo la plantilla genérica?

    `config/perfiles.json` no se versiona: es de cada uno. Los casos de abajo son
    licitaciones reales contrastadas contra una configuración afinada durante meses, así
    que en un clon recién descargado —donde solo hay `perfiles.ejemplo.json`— no dicen
    nada: fallarían por lo que NO está configurado, no por un fallo del motor. Se saltan,
    en lugar de recibir a un compañero con diez tests en rojo el primer día.
    """
    from radar import matching

    propio, ejemplo = matching.PERFILES_POR_DEFECTO, matching.PERFILES_EJEMPLO
    if not propio.exists():
        return False
    if not ejemplo.exists():
        return True
    return propio.read_text(encoding="utf-8") != ejemplo.read_text(encoding="utf-8")


class TestMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.perfiles = cargar_perfiles()

    @unittest.skipUnless(
        hay_perfiles_propios(),
        "los casos reales se comprueban contra config/perfiles.json, que no se versiona; "
        "con la plantilla de ejemplo no aplican",
    )
    def test_casos_reales(self):
        for esperado, texto, cpv, importe, fuente, etiqueta in CASOS:
            with self.subTest(caso=etiqueta):
                aciertos = [
                    (p.nombre, evaluar(p, texto, cpv, importe, None, fuente))
                    for p in self.perfiles
                ]
                casa = [(n, r) for n, r in aciertos if r.casa]
                if esperado:
                    self.assertTrue(casa, f"debía casar y no casó: {etiqueta}")
                else:
                    self.assertFalse(
                        casa,
                        f"no debía casar: {etiqueta} -> "
                        + "; ".join(f"{n}: {r.motivo}" for n, r in casa),
                    )

    def test_todo_match_explica_su_motivo(self):
        """Sin traza no se puede afinar el ruido."""
        for esperado, texto, cpv, importe, fuente, etiqueta in CASOS:
            if not esperado:
                continue
            for p in self.perfiles:
                r = evaluar(p, texto, cpv, importe, None, fuente)
                if r.casa:
                    with self.subTest(caso=etiqueta, perfil=p.nombre):
                        self.assertTrue(r.motivo.strip(), "motivo vacío")
                        self.assertGreater(r.puntuacion, 0)

    def test_los_terminos_casan_a_principio_de_palabra_pero_siguen_siendo_raices(self):
        """Las dos mitades del contrato de `patron()`, que se contrapesan.

        Anclar solo el INICIO no es un detalle de implementación: cerrar también el
        final con `\\b` haría fallar la segunda mitad de estos casos, que es el diseño
        de raíces del que depende media configuración.
        """
        no_casa = [("formacion", "sistemas de informacion"),
                   ("formacio", "transformacio digital"),
                   ("formacio", "conformacio del expediente"),
                   ("ens ", "ensayo clinico"),
                   ("ens ", "bienes y servicios")]
        for termino, texto in no_casa:
            with self.subTest(termino=termino, texto=texto):
                self.assertIsNone(patron(termino).search(texto),
                                  "casa dentro de otra palabra")

        casa = [("conscienci", "conscienciacio del personal"),
                ("concienci", "campana de concienciacion"),
                ("sensibiliza", "sensibilizacion de usuarios"),
                ("ciberdelinc", "ciberdelincuencia organizada"),
                ("formacio", "servei de formacio"),
                ("formacion", "la formacion del personal"),
                ("ens ", "categoria media del ens incluido"),
                ("ens ", "els seus ens dependents")]
        for termino, texto in casa:
            with self.subTest(termino=termino, texto=texto):
                self.assertIsNotNone(patron(termino).search(texto),
                                     "la raíz debería seguir casando")

    def test_los_cpv_se_comparan_como_familia_no_como_codigo_exacto(self):
        """`cpv_prefijos` se declara con ceros de relleno y debe acotar la familia.

        Con la comparación literal, "72500000" solo casaba consigo mismo y la oficina
        de ciberseguridad del Ministerio de Cultura (72514300) no recibía puntos del
        grupo 725 al que pertenece.
        """
        self.assertEqual(prefijo_cpv("72500000"), "725")
        self.assertEqual(prefijo_cpv("80533100"), "805331")
        self.assertEqual(prefijo_cpv("48730000"), "4873")
        self.assertEqual(prefijo_cpv("72514300"), "725143")
        # Nunca por debajo de dos dígitos: "3" acotaría media taxonomía, mientras que
        # "30" es exactamente la división que declara 30000000.
        self.assertEqual(prefijo_cpv("30000000"), "30")
        self.assertEqual(prefijo_cpv("72"), "72")

        self.assertTrue("72514300".startswith(prefijo_cpv("72500000")))
        self.assertFalse("72514300".startswith("72500000"), "el bug original")
        # Y no debe colarse una familia distinta.
        self.assertFalse("80533100".startswith(prefijo_cpv("72500000")))

    def test_perfiles_bien_formados(self):
        for p in self.perfiles:
            with self.subTest(perfil=p.nombre):
                self.assertTrue(p.terminos_fuertes or p.terminos_debiles,
                                "un perfil sin términos acepta o rechaza todo")
                if p.terminos_debiles:
                    self.assertTrue(
                        p.contexto_requerido,
                        "los términos ambiguos necesitan contexto o generan ruido",
                    )


if __name__ == "__main__":
    unittest.main()
