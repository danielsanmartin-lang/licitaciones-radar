"""Temáticas del mercado: en qué cae cada licitación, case o no con los perfiles.

Los perfiles contestan «¿esto es para mí?» y por eso son estrechos a propósito: de las
705.000 fichas de la base casan unos cientos. Pero el radar descarga PLACSP entero, y
el resto del mercado IT —la ciberseguridad en sentido amplio, el cloud, la IA, las
redes— estaba dentro de la base sin que hubiera por dónde verlo. Esto lo ordena en
temáticas para la pestaña «Otras licitaciones» y para poder mirar la Analítica y los
Adjudicatarios de cada una.

Las temáticas son del programa y no de cada usuario, a diferencia de los perfiles: no
hay negocio de nadie en saber que 48730000 es software de seguridad. Por eso viven
aquí, versionadas, y no en `perfiles.json`.

Las reglas son más simples que las de los perfiles, y es deliberado. Una ficha entra
en una temática si lleva un CPV del grupo O si nombra un término propio de ella, y
`excluir` manda sobre las dos cosas. No hay términos débiles ni contexto: aquí no se
decide si algo merece la atención de un comercial, solo en qué estante se coloca, y
equivocarse de estante cuesta mucho menos que perderse un contrato.

Es multietiqueta —un CPD con licencias de virtualización es hardware, licencias y
cloud a la vez— y lo que no cae en ninguna va a `resto`, que se guarda explícitamente
para que filtrar por él sea una búsqueda por índice como cualquier otra.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import progreso
from .db import escribir_preferencia, leer_preferencia
from .matching import _casan, _preparar_terminos, prefijo_cpv
from .model import normalizar

# Se sube cada vez que cambian las reglas de abajo. Al detectar un valor distinto al
# guardado, `asegurar_al_dia` reclasifica la base entera: las fichas ya clasificadas no
# se enteran solas de que un término nuevo ahora las abarca.
VERSION_CATEGORIAS = "1"
CLAVE_VERSION = "version_categorias"

RESTO = "resto"
# La unión de todas las temáticas IT. No se guarda: se calcula al consultar.
TODA_LA_IT = "it"

LOTE = 5_000


@dataclass
class Categoria:
    clave: str
    nombre: str
    cpv_prefijos: tuple[str, ...] = ()
    # Códigos que solo cuentan enteros. 72000000 es la división completa de servicios
    # TI —«consultoría, desarrollo de software, Internet y apoyo»— y como prefijo
    # («72») se tragaría todas las demás temáticas.
    cpv_exactos: tuple[str, ...] = ()
    terminos: tuple[str, ...] = ()
    excluir: tuple[str, ...] = ()
    _prefijos: tuple[str, ...] = field(default=(), init=False, repr=False)
    _terminos: list = field(default_factory=list, init=False, repr=False)
    _excluir: list = field(default_factory=list, init=False, repr=False)

    def preparar(self) -> "Categoria":
        self._prefijos = tuple(prefijo_cpv(p) for p in self.cpv_prefijos)
        self._terminos = _preparar_terminos(list(self.terminos))
        self._excluir = _preparar_terminos(list(self.excluir))
        return self

    def casa(self, texto: str, cpvs: list[str]) -> bool:
        if self._excluir and next(_casan(self._excluir, texto), None):
            return False
        if self._prefijos and any(c.startswith(self._prefijos) for c in cpvs):
            return True
        if self.cpv_exactos and any(c in self.cpv_exactos for c in cpvs):
            return True
        return bool(self._terminos) and next(_casan(self._terminos, texto), None) is not None


# Los términos siguen las reglas de los perfiles (ver `matching.patron`): son RAÍCES,
# anclados solo a principio de palabra, y un espacio final exige además fin de palabra
# —«ia » no debe casar dentro de «iafectada» ni «cau » dentro de «caudal»—. Van
# normalizados, sin tildes, y con las lenguas cooficiales: media España publica en
# catalán, gallego o euskera.
#
# Se buscan sobre `texto_reglas_norm`, que NO lleva el nombre del órgano: sin eso, todo
# lo que contrata el Instituto Nacional de Ciberseguridad sería ciberseguridad, aunque
# fuera la limpieza de su sede.
CATEGORIAS: list[Categoria] = [
    Categoria(
        "ciberseguridad", "Ciberseguridad",
        # Software de seguridad (4873: de ficheros, de datos…), antivirus (4876) y
        # desarrollo de software de seguridad (72212730).
        cpv_prefijos=("4873", "4876", "72212730"),
        terminos=(
            "ciberseg", "ciber-seg", "ciber seg", "zibersegurtasun",
            "ciberataq", "ciberamenaz", "ciberinciden", "ciberresilien", "ciberdefens",
            "seguridad informatica", "seguretat informatica", "seguridade informatica",
            "seguridad de la informacion", "seguretat de la informacio",
            "seguridade da informacion", "seguridad de los sistemas de informacion",
            "seguridad tic", "seguridad de las tic", "seguridad de redes",
            "seguridad perimetral", "seguridad del correo", "seguridad en el correo",
            # «Cortafuegos» a secas son sobre todo las franjas de los montes —«mnto.
            # cortafuegos, viales y otras actuaciones»— y las puertas contra incendios.
            "equipos cortafuegos", "suministro de cortafuegos", "cortafuegos de red",
            "cortafuegos perimetral", "cortafuegos de nueva generacion",
            "plataforma de cortafuegos", "plataformas de cortafuegos",
            "licencias de cortafuegos", "licenciamiento cortafuegos",
            "renovacion de cortafuegos", "suscripciones de los cortafuegos",
            "dispositivos cortafuegos", "sistema de cortafuegos",
            "esquema nacional de seguridad", "esquema nacional de seguretat",
            "centro de operaciones de seguridad", "security operations cent",
            "siem ", "pentest", "test de intrusion", "pruebas de intrusion",
            "hacking etico", "firewall", "antivirus", "antimalware",
            "malware", "ransomware", "phishing", "ddos", "edr ", "xdr ",
            "gestion de vulnerabilidades", "analisis de vulnerabilidades",
            "auditoria de vulnerabilidades", "csirt", "autenticacion multifactor",
            "doble factor de autenticacion", "gestion de identidades",
        ),
    ),
    Categoria(
        "cloud", "Cloud y hosting",
        # Alojamiento web (72415), proveedores de aplicaciones —SaaS— (72416) y
        # almacenamiento de datos (72317).
        cpv_prefijos=("72415", "72416", "72317"),
        terminos=(
            "cloud", "en la nube", "a la nube", "de la nube", "nube publica",
            "nube privada", "nube hibrida", "servicios en nube", "al nuvol",
            "en el nuvol", "nuvol public", "nuvol privat", "na nube",
            # «paas» no: en los pliegos de Defensa es una sigla de aprovisionamiento.
            "saas ", "iaas ", "software como servicio",
            "infraestructura como servicio", "plataforma como servicio",
            "hosting", "alojamiento web", "alojamiento de servidores",
            "alojamiento de aplicaciones", "alojamiento de la plataforma",
            "allotjament web", "azure", "amazon web services", "aws ",
            "google cloud", "google workspace", "microsoft 365", "office 365",
        ),
        excluir=("nube de puntos", "nubes de puntos", "nuvol de punts"),
    ),
    Categoria(
        "ia", "IA y datos",
        # No hay un CPV de inteligencia artificial: solo se puede reconocer por el texto.
        terminos=(
            "inteligencia artificial", "intel·ligencia artificial",
            "intel.ligencia artificial", "intel-ligencia artificial",
            "intelixencia artificial", "adimen artifizial",
            # «IA» suelta no: en los pliegos también es «impacto ambiental».
            "ia generativa", "herramientas de ia ", "solucion de ia ", "soluciones de ia ",
            "basada en ia ", "basado en ia ", "basadas en ia ", "basados en ia ",
            "agentes de ia ", "modelos de ia ", "mediante ia ",
            "machine learning", "aprendizaje automatico", "deep learning",
            "aprendizaje profundo", "procesamiento del lenguaje natural",
            "modelos de lenguaje", "chatbot", "asistente virtual", "agente virtual",
            "vision artificial", "big data", "business intelligence",
            "inteligencia de negocio", "analitica de datos", "analitica avanzada",
            "ciencia de datos", "data science", "data lake", "lago de datos",
            "almacen de datos", "data warehouse", "gobierno del dato",
            "gobernanza del dato", "gobernanza de datos",
            # «Cuadro de mando» tampoco: casi siempre es el armario eléctrico del
            # alumbrado público, no un panel de indicadores.
            "automatizacion robotica de procesos", "rpa ",
        ),
    ),
    Categoria(
        "software", "Desarrollo y software",
        # 7221 programación de software empaquetado, 7223 desarrollo a medida, 7224
        # análisis y programación de sistemas, 7226 servicios relacionados con el
        # software y 72413 diseño de sitios web.
        cpv_prefijos=("7221", "7223", "7224", "7226", "72413"),
        terminos=(
            "software", "programari", "desarrollo de software",
            "desarrollo de aplicaciones", "desarrollo de una aplicacion",
            "desarrollo de la aplicacion", "desarrollo de un sistema de informacion",
            "desarrollo de una plataforma", "desarrollo de la plataforma",
            "desenvolupament d'aplicacions", "desenvolupament de l'aplicacio",
            "desenvolupament d'una aplicacio", "desenvolvemento de aplicacions",
            "aplicacion web", "aplicaciones web", "aplicacion movil",
            "aplicaciones moviles", "app movil", "mantenimiento evolutivo",
            "mantenimiento correctivo y evolutivo", "mantenimiento correctivo, evolutivo",
            "mantenimiento de aplicaciones", "manteniment d'aplicacions",
            "mantenimiento del software", "programacion informatica",
            # «Sede electrónica» y «administración electrónica» no: son la coletilla
            # de cualquier pliego que se tramita por la sede.
            "portal web", "pagina web", "sitio web", "erp ", "crm ",
            "gestor de expedientes", "gestion de expedientes electronica",
        ),
    ),
    Categoria(
        "licencias", "Licencias de software",
        # La división 48 entera: paquetes de software y sistemas de información.
        cpv_prefijos=("48",),
        terminos=(
            "licencias de software", "licencia de software", "licencias software",
            "licencias de uso de software", "licencias informaticas",
            "licencias de microsoft", "licencias microsoft", "licencias oracle",
            "licencias de oracle", "licencias vmware", "licencias de vmware",
            "licencias adobe", "licencias de adobe", "licencias sap",
            "licencias de sap", "licencias esri", "licencias de esri",
            "suscripcion de licencias", "suscripciones de licencias",
            "renovacion de licencias", "renovacion de las licencias",
            "llicencies de programari", "llicencies microsoft",
            "llicencies de microsoft", "licenzas de software",
        ),
    ),
    Categoria(
        "hardware", "Infraestructura y hardware",
        # Equipos informáticos (302), servidores (4882 —el CPV los mete en la división
        # del software—) y mantenimiento y reparación de equipos (5031, 5032).
        cpv_prefijos=("302", "4882", "5031", "5032"),
        terminos=(
            "servidores", "servidor de", "equipos informaticos",
            "equipamiento informatico", "material informatico", "equips informatics",
            "material informatic", "equipamento informatico", "ordenadores",
            # Ni «portátiles» (extintores, neveras, sanitarios), ni «impresoras» (cajas
            # de papel), ni «sistema de almacenamiento» (baterías fotovoltaicas).
            "ordinadors", "ordenadores portatiles", "ordinadors portatils",
            "microinformatica", "cabina de almacenamiento", "cabinas de almacenamiento",
            "almacenamiento de datos", "centro de proceso de datos",
            "centros de proceso de datos", "centro de datos", "centre de dades",
            "virtualizacion",
            "virtualitzacio", "hiperconverg", "pantallas interactivas",
            "paneles interactivos", "puesto de trabajo informatico",
            "puestos de trabajo informaticos", "copias de seguridad", "backup",
        ),
        excluir=("servidores publicos",),
    ),
    Categoria(
        "redes", "Redes y telecomunicaciones",
        # Aparatos de transmisión (322), redes (324), equipos de telecomunicaciones y
        # de telefonía (3252, 3255), servicios de telecomunicaciones (642), servicios
        # de red informática (727), su mantenimiento (5033) y el cableado (45314).
        cpv_prefijos=("322", "324", "3252", "3255", "642", "727", "5033", "45314"),
        terminos=(
            # «Telecomunicaciones» y «telefonía» a secas no: salen en la descripción de
            # cualquier obra que lleve su canalización, y en los nombres de las
            # consejerías.
            "servicios de telecomunicaciones", "servicio de telecomunicaciones",
            "serveis de telecomunicacions", "red de telecomunicaciones",
            "redes de telecomunicaciones", "xarxa de telecomunicacions",
            "infraestructura de telecomunicaciones", "sistemas de telecomunicaciones",
            "equipos de telecomunicaciones", "servicio de telefonia",
            "servicios de telefonia", "serveis de telefonia", "telefonia fija",
            "telefonia movil", "telefonia mobil", "telefonia ip", "comunicaciones moviles",
            "comunicacions mobils", "fibra optica", "red de datos", "redes de datos",
            "xarxa de dades", "red de comunicaciones", "redes de comunicaciones",
            "xarxa de comunicacions", "red corporativa", "red wan", "red lan",
            "redes lan", "wifi", "wi-fi", "sd-wan", "cableado estructurado",
            "electronica de red", "routers", "centralita telefonica",
            "centralitas telefonicas", "centraleta telefonica", "conectividad a internet",
            "servicios de conectividad", "acceso a internet", "radioenlace", "voip",
            "voz ip", "voz sobre ip", "5g ",
        ),
    ),
    Categoria(
        "consultoria", "Consultoría y soporte IT",
        # Consultoría de hardware (721), de sistemas (7222), servicios de sistemas y
        # apoyo (7225), servicios de datos (723), servicios informáticos (725), apoyo
        # informático (726), auditoría y pruebas (728) y copia y catalogación (729).
        cpv_prefijos=("721", "7222", "7225", "723", "725", "726", "728", "729"),
        cpv_exactos=("72000000",),
        terminos=(
            "soporte informatico", "suport informatic", "asistencia tecnica informatica",
            "asistencia informatica", "centro de atencion a usuarios",
            "centro de atencion al usuario", "cau ", "help desk", "helpdesk",
            "service desk", "mesa de ayuda", "soporte a usuarios", "soporte al usuario",
            "outsourcing informatico", "externalizacion de servicios informaticos",
            "servicios informaticos", "serveis informatics", "servizos informaticos",
            # «Transformación digital» no: es el apellido de media docena de consejerías.
            "consultoria tecnologica", "consultoria informatica", "consultoria tic",
            "mantenimiento de sistemas informaticos", "mantenimiento informatico",
            "manteniment informatic", "administracion de sistemas",
            "servicios tic", "serveis tic", "oficina tecnica tic",
        ),
    ),
]

for _c in CATEGORIAS:
    _c.preparar()

POR_CLAVE = {c.clave: c for c in CATEGORIAS}

# Las que se pueden pedir en la Analítica y en Adjudicatarios: las IT y su unión. El
# resto son unas 625.000 fichas —obras, limpieza, suministros— y analizarlas cuesta
# decenas de segundos para no decir nada del mercado que interesa aquí.
AMBITOS_ANALITICA = (TODA_LA_IT, *POR_CLAVE)

NOMBRES = {**{c.clave: c.nombre for c in CATEGORIAS}, RESTO: "Resto de licitaciones",
           TODA_LA_IT: "Toda la IT"}

# Criba: una sola alternancia con los literales DESNUDOS de todas las temáticas, como
# la de los perfiles (ver `Perfil.preparar`). Nueve de cada diez fichas no son IT, y
# así esas se despachan con una búsqueda en C en lugar de ocho.
_CRIBA = re.compile("|".join(sorted(
    {re.escape(normalizar(t).strip()) for c in CATEGORIAS for t in c.terminos},
    key=len, reverse=True,
)))
_TODOS_LOS_PREFIJOS = tuple(p for c in CATEGORIAS for p in c._prefijos)
_TODOS_LOS_EXACTOS = frozenset(e for c in CATEGORIAS for e in c.cpv_exactos)


def clasificar_ficha(texto: str, cpvs: list[str]) -> list[str]:
    """Las temáticas de una ficha. `texto` ya normalizado (`texto_reglas_norm`)."""
    if not (_CRIBA.search(texto)
            or any(c.startswith(_TODOS_LOS_PREFIJOS) for c in cpvs)
            or any(c in _TODOS_LOS_EXACTOS for c in cpvs)):
        return [RESTO]
    claves = [c.clave for c in CATEGORIAS if c.casa(texto, cpvs)]
    return claves or [RESTO]


def borrar(con: sqlite3.Connection, ids: list[int]) -> None:
    """Retira la clasificación de unas fichas antes de volver a escribirla."""
    if ids:
        con.executemany("DELETE FROM categorias WHERE licitacion_id = ?",
                        [(i,) for i in ids])


def escribir(con: sqlite3.Connection, filas: list[tuple[int, str]]) -> None:
    if filas:
        con.executemany(
            "INSERT OR IGNORE INTO categorias (licitacion_id, categoria) VALUES (?, ?)",
            filas,
        )


def clasificar_todo(con: sqlite3.Connection) -> dict:
    """Reclasifica la base entera y deja constancia de con qué reglas se hizo.

    No toca `licitaciones`: lo nuevo y lo modificado se clasifica dentro de la pasada
    incremental de los perfiles (`matching.reevaluar`), que ya sabe qué fichas han
    cambiado. Así no hace falta una segunda huella por fila, que en la primera pasada
    habría reescrito los 3,9 GB de la tabla solo para apuntarla.
    """
    progreso.fuente("clasificando por temática")
    progreso.fase("aplicando las temáticas")
    con.execute("DELETE FROM categorias")
    lote: list[tuple[int, str]] = []
    vistas = 0
    for fila in con.execute(
        "SELECT id, COALESCE(texto_reglas_norm, '') AS texto, cpv FROM licitaciones"
    ):
        vistas += 1
        progreso.fichas(vistas)
        lote.extend((fila["id"], c)
                    for c in clasificar_ficha(fila["texto"], (fila["cpv"] or "").split()))
        if len(lote) >= LOTE:
            escribir(con, lote)
            lote.clear()
    escribir(con, lote)
    escribir_preferencia(con, CLAVE_VERSION, VERSION_CATEGORIAS)
    con.commit()
    return {"clasificadas": vistas, "por_categoria": recuento(con)}


def al_dia(con: sqlite3.Connection) -> bool:
    """¿Está la base clasificada con las reglas de esta versión?

    Una base vacía está al día: no hay nada que clasificar, y la primera ficha que
    entre lo hará por la pasada incremental.
    """
    if leer_preferencia(con, CLAVE_VERSION) == VERSION_CATEGORIAS:
        return True
    return con.execute("SELECT 1 FROM licitaciones LIMIT 1").fetchone() is None


def asegurar_al_dia(con: sqlite3.Connection) -> dict | None:
    """Reclasifica todo si las reglas han cambiado desde la última vez. Si no, nada."""
    if al_dia(con):
        if leer_preferencia(con, CLAVE_VERSION) != VERSION_CATEGORIAS:
            escribir_preferencia(con, CLAVE_VERSION, VERSION_CATEGORIAS)
            con.commit()
        return None
    return clasificar_todo(con)


def recuento(con: sqlite3.Connection) -> dict[str, int]:
    return {
        f[0]: f[1]
        for f in con.execute(
            "SELECT categoria, COUNT(*) FROM categorias GROUP BY categoria")
    }
