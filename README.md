# Radar de Licitaciones

Busca licitaciones y pliegos de la administración pública española relacionados con
**concienciación en ciberseguridad, formación, phishing simulado y protección del
correo electrónico**, más la **ciberseguridad en sentido amplio** —oficinas de
ciberseguridad, SOC, seguridad de la información, adecuación al ENS—, y los deja en
una bandeja para trabajarlos.

No se conecta a ningún CRM ni a las notas de nadie. Todo vive en esta carpeta, así
que puedes copiarla, pasársela a un compañero por AirDrop o subirla a un repositorio
y funciona igual en cualquier Mac.

---

## Arranque en 30 segundos

Doble clic en **`start.command`**.

Descarga las novedades y abre la bandeja en el navegador. Un día normal tarda unos
segundos. La primera vez es distinta y merece su propio apartado, justo abajo.

Mientras descarga, la terminal muestra una línea que se va actualizando con la
fuente, la página, los megas que llevan llegados y el tiempo transcurrido:

```
⠹ etapa 3/4 · placsp:agregadas · el histórico de 2025 (año 2 de 3) · descargando 84,2 MB/133,0 MB (63%) a 1,4 MB/s · 2.950 fichas · 1m 12s
```

Si esa línea se mueve, está trabajando. PLACSP contesta lento a ratos y cada
intento espera hasta dos minutos antes de reintentar, así que un tramo largo en
"conectando" es normal y no hay que cerrar nada.

Y si se corta a mitad, reintenta hasta cuatro veces con esperas crecientes en lugar de
rendirse a la primera, que es lo que antes dejaba un año entero marcado como fallido por
un solo timeout. Lo que **no** se puede es reanudar: medido contra la plataforma, PLACSP
ignora la cabecera `Range` y vuelve a mandar el fichero entero, así que un corte en el
ZIP de la Plataforma del Estado significa repetir esa descarga. El programa lo pide de
todas formas y aprovecharía lo ya bajado el día que la plataforma lo permita; mientras
tanto se asegura de lo importante, que es no coser nunca dos mitades de ficheros
distintos.

Si prefieres la terminal:

```bash
python3 radar.py ingest && python3 radar.py serve
```

Requisitos: **Python 3.9 o superior**. Ojo, que macOS ya no lo trae: Apple lo retiró
del sistema en Catalina, así que en un Mac recién estrenado hay que instalarlo una vez
desde [python.org](https://www.python.org/downloads/macos) —`start.command` lo detecta
y lo explica—. Aparte de eso no hay que instalar nada más: ni librerías, ni base de
datos, ni cuentas.

---

## La primera vez

Una base recién creada no se llena sola, y esto es lo que hay que saber para no pensar
que la herramienta está rota.

El motivo es cómo publica PLACSP: no hay una consulta que devuelva «todo lo de los
últimos dos años». Hay un **feed diario** que encadena snapshots hacia atrás, y unos
**ZIP anuales** con el histórico. La ingesta de cada mañana solo necesita la primera
página del feed, así que eso es lo que pide cuando no sabe por dónde se quedó; y en
cuanto anota por dónde va, lo que hay más atrás ya no lo vuelve a mirar. Con un
`ingest` a secas te quedarías con unas **50 coincidencias** y ninguna forma de
recuperar el resto.

Por eso `start.command` detecta que la base está vacía y construye el histórico en
cuatro etapas, de la más barata a la más cara:

| | qué trae | cuánto cuesta |
|---|---|---|
| 1 | anuncios europeos (TED) y de Cataluña | unos minutos, apenas ocupa |
| 2 | histórico de plataformas agregadas y consultas previas | ~360 MB + ~4 min de proceso |
| 3 | histórico de la Plataforma del Estado | ~5 GB + ~15 min de proceso |
| 4 | lo publicado desde la fecha de corte de los ZIP | unos minutos |

Los tiempos de descarga no están porque no se pueden prometer: dependen de tu conexión y
de lo que dé PLACSP ese día. Medido aquí, esos 5 GB han tardado desde unos minutos
hasta casi dos horas. Lo que sí es predecible es el proceso —abrir los ZIP y volcar el
millón y pico de fichas en la base—, porque solo depende de tu máquina.

**La aplicación se abre en cuanto termina la etapa 1**, ya con unos mil expedientes que
encajan. Las demás siguen descargando por detrás mientras trabajas: arriba aparece
un aviso con la etapa, los megas que van llegando y una barra, y los contadores de la
cabecera van subiendo solos sin recargar la página.

Las etapas 2 y 3 son las que llenan **Vencimientos** y **Adjudicatarios**, que
necesitan histórico de adjudicaciones. Y la 3 es la que trae las diez comunidades que
no tienen plataforma propia (Valencia, Castilla y León, Aragón, Murcia…).

Mientras la carga inicial esté en marcha, «Buscar ahora» y la tarea de cada mañana se
esperan: dos ingestas a la vez se pelean por el bloqueo de escritura de SQLite. Es
normal y la aplicación lo dice en el botón.

Desde la terminal, si quieres controlarlo tú:

```bash
python3 radar.py ingest --primera-carga              # las cuatro etapas seguidas
python3 radar.py ingest --primera-carga --etapas 1   # solo la rápida
python3 radar.py ingest --primera-carga --etapas 2 3 4
```

---

## Cómo se usa

Hay cinco pestañas arriba: Bandeja, Vencimientos, Adjudicatarios, Analítica y
Términos de búsqueda.

### Los números de la cabecera

Cada cifra es un botón: al pulsarlo la lista muestra exactamente esas licitaciones.
Todas cuentan **expedientes**, no anuncios, igual que la lista.

| Contador | Qué es |
|---|---|
| abiertas | han pasado el filtro, siguen vivas y el plazo no ha vencido |
| cierran ≤7d | de las anteriores, las que se acaban esta semana |
| sin revisar | no les has dado ni Seguir ni Descartar |
| siguiendo | las que has marcado para trabajar |
| coincidencias | todas las que han pasado el filtro, sin filtrar por plazo ni triaje |

Debajo de la lista pone «110 de 2.716 coincidencias» y qué filtros están puestos, porque
el desplegable de triaje y la casilla **«Solo abiertas» se combinan**: elegir «todo
menos descartadas» sin desmarcar la casilla sigue mostrando solo las abiertas.

### Bandeja

Lo que ha pasado el filtro, con **los días que quedan para presentar** bien grandes
a la derecha. De cada licitación se ve el órgano, el importe, el plazo y los enlaces
a los pliegos oficiales.

Al pulsar una licitación se abre el panel de detalle, donde está lo importante:
**«Por qué ha entrado»**, que dice exactamente qué palabra o qué CPV la ha hecho
aparecer. Si algo no debería estar ahí, eso te dice qué afinar.

Cada licitación se marca como **Seguir**, **Presentada** o **Descartar**, y se le
pueden poner notas. Al descartar te pregunta el motivo (fuera de nicho, importe
bajo, incumbente atado…); esos motivos se acumulan y sirven para ajustar los
perfiles con datos en vez de a ojo. El triaje se conserva aunque la licitación
cambie de estado o cambies los perfiles.

Un mismo expediente genera varios anuncios a lo largo de su vida (licitación,
corrección, adjudicación por lotes). La bandeja los agrupa en una sola fila y lo
indica con una etiqueta «N anuncios», mostrando el estado más avanzado.

El triaje es del **expediente**, no del anuncio: lo que marcas se aplica a todos los
anuncios del grupo, y los que se publiquen después heredan la decisión. Eso es lo que
hace que **descartar aguante las siguientes descargas**. Ojo con la palabra: descartar
no impide que la licitación se siga descargando —así se ve si acaba adjudicada y a
quién—, lo que hace es sacarla de la bandeja, de los vencimientos y de las novedades.

Eso incluye el anuncio de TED: todo lo que supera el umbral europeo se publica dos
veces, y las dos filas se unen aunque no compartan ni expediente ni idioma —TED
numera cada anuncio por su cuenta y traduce el título al castellano—, emparejándolas
por importe exacto y día de cierre. Cuando esa pareja es ambigua (dos licitaciones
distintas con el mismo importe redondo y el mismo cierre, que se midieron 10 casos
sobre 629) **no se fusiona nada**: mejor dos filas separadas que mezclar el triaje de
dos expedientes.

Cuando entran licitaciones nuevas desde tu última visita aparece una pestaña verde
**«N nuevas»** para ver solo esas.

### Vencimientos

Contratos **ya adjudicados** cuyo plazo termina pronto, con el incumbente y el
importe. Los botones de ventana (3, 6, 12, 24 meses) muestran cuántos vencen en cada
plazo y por cuánto importe, para poder comparar de un vistazo. Es la lista para llamar *antes* de que salga el pliego, cuando todavía se
puede influir. Solo aparecen los que publican fecha de fin o duración: si la fuente
no la da, la licitación no se lista en lugar de estimarla a ojo.

### Adjudicatarios

Quién se está llevando estos contratos, agrupando las variantes de razón social
(«S2 GRUPO …, S.L.U.» y «S2 Grupo … S.L.» son la misma empresa). Al pulsar una
empresa se despliegan sus contratos.

### Analítica

Las preguntas que no son «qué hay hoy». Siete bloques, cada uno con una pregunta de venta
delante:

| Bloque | Contesta a |
|---|---|
| Cuándo sale el trabajo | en qué meses hay que estar preparado. Diciembre publica el doble que agosto, y eso se planifica en septiembre |
| A cuánto tengo que ir | de qué tamaño son estas operaciones de verdad |
| Con qué precio entro | cuánto por debajo del presupuesto se están cerrando |
| Cuándo entra en el forecast | cuántos días pasan de la publicación a la adjudicación |
| A quién llamo antes del pliego | cuántos contratos se acaban en seis meses, con incumbente conocido |
| Qué compran exactamente | en qué CPV cae tu producto, con enlace para afinar los términos |
| Qué tengo de verdad hoy | si esto es un pipeline o un archivo histórico |

Se filtra por perfil y por uno de tres rangos (este año, últimos 24 meses, todo desde
2024). Los dos bloques que hablan de *ahora* —renovaciones y cartera— ignoran el rango a
propósito y lo dicen, porque un filtro que se ignora en silencio es peor que uno que falta.

Y hay tres cosas que esta pestaña **no** hace, todas por el mismo motivo:

- **No da ninguna cifra de dinero total.** La clave que agrupa los anuncios de un mismo
  expediente no cruza fuentes, así que 126 expedientes están repetidos entre PLACSP y TED y
  arrastran casi 1.000 M€ de aire. Solo medianas, tramos y recuentos.
- **No da medias de importe.** La media son 4 millones y la mediana 169.000: cinco
  contratos son la mitad del total. Esos cinco salen con nombre y órgano, y ahí se ve que
  tres son el mismo acuerdo marco repetido.
- **No esconde lo que descarta.** En la baja de adjudicación, la mitad de la muestra no
  sirve —la fuente repitió el presupuesto en lugar del precio, o compara un lote contra el
  total del marco— y sale en pantalla con su recuento, no en un asterisco.

Cada bloque tiene además un mínimo por debajo del cual no se pinta: una mediana de doce
casos presentada como una mediana es peor que un hueco.

Y en cualquier vista, **Exportar CSV** baja lo que estés viendo con los filtros
aplicados, listo para Excel.

### Comandos

```bash
python3 radar.py ingest                       # descarga las novedades
python3 radar.py ingest --primera-carga       # instalación nueva: trae el histórico
python3 radar.py ingest --backfill 2024,2025  # trae el histórico de esos años
python3 radar.py match                        # reevalúa los perfiles sin descargar
python3 radar.py serve                        # abre la aplicación
python3 radar.py vencimientos --meses 6       # contratos que vencen pronto
python3 radar.py adjudicatarios               # quién gana estos contratos
python3 radar.py export salida.csv            # exporta a CSV
python3 radar.py programar                    # descarga automática cada mañana
python3 radar.py estado                       # cifras y salud de las fuentes
python3 radar.py doctor                       # ¿está todo en su sitio?
python3 radar.py actualizar --solo-comprobar  # ¿hay una versión nueva del programa?
python3 radar.py actualizar                   # la instala
```

`ingest` solo reevalúa los perfiles sobre lo que acaba de traer, que es lo que hace que
la descarga de cada mañana termine en segundos en vez de repasar las 673.755 fichas de
la base. Si cambias los términos de búsqueda, lo detecta y repasa todo igualmente; y
`match` siempre lo mira todo, para eso está.

### Actualizar el programa

La aplicación mira al abrirse si hay una versión publicada más nueva que la instalada y,
si la hay, ofrece un botón para traerla. Se puede hacer también desde la terminal con los
dos comandos de arriba.

Sustituye el código —`radar/`, `web/`, `radar.py`, `start.command` y los certificados— y
guarda lo anterior al lado como `.anterior` para poder volver atrás. **No toca `data/`**,
donde están tu base, tu triaje y tus notas, **ni `config/perfiles.json`**, que son tus
términos de búsqueda. Si hay una descarga en marcha, se niega: cambiar el código por
debajo de una carga que dura horas es pedir problemas.

Después hay que cerrar la aplicación y volver a abrirla con `start.command`, porque el
proceso que está corriendo ya tiene en memoria la versión vieja. Los cambios en la base de
datos que traiga la versión nueva se aplican solos en ese siguiente arranque.

### Publicar una versión

Lo que mira el actualizador es la **última release publicada en GitHub**, así que subir
código al repositorio no actualiza a nadie. Para publicar una:

1. Sube `__version__` en `radar/__init__.py`.
2. Etiqueta la release con ese mismo número. Si no coinciden, el actualizador se niega a
   instalarla —que es lo que se quiere cuando el paquete no es lo que dice ser—.
3. Pega el SHA-256 del zip en las notas de la release. Es opcional, pero si está se
   comprueba, y así una descarga corrompida a medio camino no llega a sustituir nada:

```bash
shasum -a 256 licitaciones-radar-1.0.2.zip
```

### Que se actualice solo

```bash
python3 radar.py programar --hora 8 --minuto 30
```

Crea una tarea de macOS (`~/Library/LaunchAgents/com.licitaciones-radar.ingesta.plist`)
que descarga las novedades cada mañana. Es **el único fichero que este proyecto
escribe fuera de su carpeta**, y el comando te dice cuál es antes de crearlo. El
registro queda en `data/ingest.log`. Para quitarlo:

```bash
python3 radar.py programar --desinstalar
```

Si prefieres hacerlo a mano, `start.command` descarga y abre la bandeja de una vez.

---

## Afinar la búsqueda

Desde la pestaña **«Términos de búsqueda»** de la aplicación. Cada perfil tiene una
caja por tipo de término, una palabra por línea. Antes de guardar, **«Ver qué
cambiaría»** te dice cuántas licitaciones entran y salen con los términos nuevos, con
ejemplos: cambiar una palabra a ciegas sobre más de cien mil registros es la forma más
rápida de llenar la bandeja de ruido.

Al guardar se reevalúa todo lo descargado sin volver a bajar nada. Se guarda una copia
del fichero anterior en `config/perfiles.anterior.json`.

También se puede editar **`config/perfiles.json`** a mano y lanzar
`python3 radar.py match`; es el mismo fichero.

Ese fichero **no se versiona**: se crea solo la primera vez copiando
`config/perfiles.ejemplo.json`, que es genérico a propósito. Los términos con los que
buscas de verdad —las raíces, las erratas que aparecen en los pliegos, las variantes en
las lenguas cooficiales— son tu trabajo y el que marca la diferencia entre encontrar un
contrato y no verlo. Se quedan en tu equipo, no viajan al repositorio y ninguna
actualización los toca.

Hay tres niveles de términos, y la distinción es la que hace que la herramienta sea
usable en lugar de un vertedero:

| Campo | Para qué |
|---|---|
| `terminos_fuertes` | Se bastan solos: `phishing`, `dmarc`, `ingenieria social`. |
| `terminos_debiles` | Ambiguos (`concienci`, `formacion`). Solo entran si además aparece algo de `contexto_requerido`. |
| `contexto_requerido` | Lo que confirma que va de seguridad: `ciberseguridad`, `malware`, `iso 27001`… |
| `cpv_prefijos` | Suman puntos, pero **nunca** aceptan por sí solos. Acotan la familia: `72500000` cubre todo el grupo `725*`, incluido `72514300`. |
| `excluir` | Manda sobre todo lo demás. |
| `importe_minimo` | Solo descarta cuando el importe se conoce. |
| `terminos_consulta` | Lo que se le pregunta a TED y Cataluña, que filtran en su servidor. |

Cinco cosas aprendidas peleando con los datos reales, y que conviene respetar al
editar:

1. **Usa raíces, no palabras completas.** `conscienci` cubre *conscienciar*,
   *conscienciació* y *concienciación*. Los pliegos usan tanto el verbo como el
   sustantivo. Cada término casa **a principio de palabra y crece hacia la
   derecha**: la raíz sigue funcionando, pero `formacion` ya no aparece dentro de
   «sistemas de in**formación**». Ese detalle no es cosmético — cuando se comparaba
   con un simple «está contenido en», 612 de 943 coincidencias de una base real
   habían entrado por ahí, y el panel «Por qué ha entrado» citaba una formación que
   el pliego no mencionaba.
2. **Deja las erratas.** `phising` con una sola s aparece tal cual en pliegos
   publicados; sin esa variante se pierde negocio real.
3. **Los textos de Cataluña están en catalán.** Incluye las dos formas
   (*ciberseguridad* y *ciberseguretat*). Los acentos son indiferentes.
4. **El espacio final cuenta.** `ens ` con espacio final exige la sigla suelta: casa
   en «del ens incluido» y en «els seus ens dependents», pero no en «ensayo» ni
   «enseñanza». Sin ese espacio sería una raíz y sí entraría en «ensayo» (aunque ya
   no en «defensa» ni «bienes», porque ahí la sigla va en medio de la palabra). La
   pantalla no recorta los espacios, y avisa cuando un término de tres letras o menos
   va sin él.
5. **Cuidado con las siglas cortas.** `spf` parecía inofensivo y colaba diez
   licitaciones absurdas: protección solar en socorrismo de playas, ratones SPF de
   laboratorio y «Entidades SPF» (Sector Público Foral). Está como término ambiguo,
   así que solo entra con contexto de seguridad.

Y un aviso: no metas palabras genéricas (`seguridad`, `email`) en
`terminos_consulta`. Se probó, y hacía que TED devolviera más de 12.000 avisos para
quedarse en los mismos 200 buenos.

---

## Qué cubre

| Fuente | Qué aporta |
|---|---|
| **PLACSP – licitaciones** | La mayor parte de España: Estado, comunidades, ayuntamientos. |
| **PLACSP – plataformas agregadas** | Las comunidades con plataforma propia, que PLACSP recoge por agregación: **País Vasco, Navarra y Galicia**, además de Cataluña, Andalucía, Madrid y La Rioja. |
| **PLACSP – consultas preliminares de mercado** | La administración preguntando al mercado **antes** de escribir el pliego. Es donde todavía se puede influir; en el anuncio ya solo se compite. |
| **TED (Unión Europea)** | Lo que supera el umbral europeo, más los anuncios de adjudicación (quién ganó y por cuánto). |
| **Cataluña** | Su plataforma propia, con más detalle que lo que llega agregado: duración del contrato, lotes y adjudicatario. |

También están los **contratos menores** de PLACSP, sin activar por defecto:

```bash
python3 radar.py ingest --fuente placsp:menores
```

No los recomendamos, y ahora con una medida en vez de una intuición: sobre una
muestra de **6.572 contratos menores reales solo 2 pasaban el filtro** (0,03%), y uno
de ellos venía con el importe mal puesto. Aquí se decía que ahí vivían los pilotos de
concienciación; los datos no lo sostienen. Es mucho volumen para casi nada, y además
la mayoría cae de todas formas por `importe_minimo`.

### Lo que NO cubre

- **El contenido de los PDF de los pliegos.** Se busca en el título, el objeto y la
  descripción de los lotes, no dentro de los documentos. Es la mejora que más
  precisión daría y la primera candidata para una segunda fase.
- **El filtro por comunidad no se aplica a los avisos de TED.** TED no expone ningún
  campo de región utilizable en su API (se probaron todos los `place-performance-*`),
  así que sus licitaciones aparecen sin comunidad. Para el resto de fuentes sí
  funciona.
- **Los datos post-adjudicación de los portales autonómicos.** Andalucía,
  C. Valenciana, Castilla y León, Asturias, Canarias y Aragón publican sus propios
  CSV/API, pero **no son licitaciones nuevas**: son registros de contratos ya
  formalizados. El de Castilla y León trae en cada fila un
  `enlace_de_publicacion` que apunta a `contrataciondelestado.es`, y la propia
  Generalitat Valenciana dice que publica sus licitaciones en PLACSP. Lo que sí
  aportarían es `adjudicatario`, `fecha_formalizacion` y `plazo_de_ejecucion_meses`,
  que es justo lo que le falta a la vista de Vencimientos. Pendiente como mejora de
  esa vista, no como fuente de licitaciones.
- **Avisos por email o Slack.** Solo bandeja: hay que entrar a mirar. No hay nada
  escrito de esto, ni medio empezado.
- **Una instancia compartida.** Cada persona tiene su base y su triaje.

Sobre el conector nativo de Euskadi: se investigó y **no hace falta**. Su API existe
(`api.euskadi.eus` responde) pero no publica el endpoint de contratación y todas las
rutas probadas devuelven 403 o 404. Al analizar el dataset de plataformas agregadas
resultó que ya cubre País Vasco, Navarra y Galicia con los campos completos, así que
activarlo salió gratis y con menos mantenimiento que escribir tres conectores.

Y sobre buscar más fuentes de licitaciones en general: **no hay dónde**. El artículo
347 de la LCSP obliga a publicar todo anuncio de licitación en PLACSP o en una
plataforma autonómica interconectada con ella, así que una licitación que no esté en
PLACSP no existe legalmente. Lo que se midió al comprobarlo: las plataformas
agregadas cubren Cataluña, Andalucía, País Vasco, Madrid, Galicia, Navarra y La
Rioja; **las otras diez comunidades llegan por `placsp:licitaciones`**, no por
agregadas. Si ves poco volumen de Valencia, Castilla y León, Aragón o Murcia, no
falta un conector: falta el histórico de `placsp:licitaciones`.

```bash
python3 radar.py ingest --fuente placsp:licitaciones --backfill 2024,2025,2026
```

---

## Qué esperar del filtro

Sobre un histórico de 2024–2026 el filtro deja pasar **medio punto porcentual de lo
que descarga**: 3.705 anuncios de 673.755, que agrupados por expediente son 2.716
licitaciones en la bandeja. En la muestra de 30 mejor puntuadas revisada a
mano, unas 20 eran directamente de concienciación o protección de correo, otras 8–9
eran contratos de ciberseguridad más amplios que a un vendedor de ciber le interesa
ver igualmente, y 1 o 2 no venían a cuento. Si te parece que hay demasiado ruido,
endurece `contexto_requerido` o sube `importe_minimo`.

Los perfiles cubren dos cosas distintas a propósito, y conviene saber cuál te
interesa: **«Concienciación y phishing»** es el nicho estricto, y **«Ciberseguridad y
seguridad de la información»** es la red amplia —oficinas de ciberseguridad, SOC,
adecuación al ENS, seguridad gestionada—, que trae bastante más volumen: aporta 3.060
de los 3.705 anuncios que pasan el filtro, cuatro de cada cinco. Si solo quieres el
nicho, quítale la marca **«activo»** en la pestaña «Términos de búsqueda» y guarda: sus
coincidencias salen de la bandeja en ese momento, y sus términos se quedan escritos en
el fichero por si quieres volver a activarlo. A mano es lo mismo: `"activo": false` en
`config/perfiles.json` y relanzar `match`.

Un ejemplo de lo que sí encuentra y que se perdería de otra forma: un contrato de
mantenimiento de hardware del Ayuntamiento de Viladecans cuyo **lote 10** era
«programa de conscienciació en CIBERSEGURETAT». Ni el título ni el CPV lo delatan;
aparece porque se indexa también el texto de los lotes.

Sobre las duraciones: se convierten respetando la unidad que declara la fuente. De
vez en cuando el propio comprador se equivoca y publica «36 años» donde quería decir
«36 meses». Se guarda tal cual viene en lugar de corregirlo por nuestra cuenta, así
que si ves una duración absurda en la vista de vencimientos, el error está en el
anuncio original.

---

## Si algo va mal

**Empieza por `python3 radar.py doctor`.** Tarda un segundo y comprueba de una vez lo
que hay debajo de casi todos los problemas: la versión de Python, que el almacén de
certificados siga vigente, el espacio libre, que la base se abra y esté al día, que los
términos de búsqueda sean válidos, que ninguna fuente haya fallado, que no haya un
cerrojo de una descarga muerta bloqueando el botón «Buscar ahora», que la caché no tenga
ZIP ilegibles y que la tarea de cada mañana esté cargada de verdad. Cada cosa que no
esté bien viene con el comando que la arregla.

No toca nada: abre la base en solo lectura y no crea ni migra nada. Dos comprobaciones
se piden aparte porque no son instantáneas:

```bash
python3 radar.py doctor --integridad   # ¿la base está dañada? lee los 3 GB: ~50 s
python3 radar.py doctor --con-red      # ¿hay una versión nueva publicada?
```

**`python3 radar.py estado`** dice cuándo se ejecutó cada fuente por última vez, qué
trajo y si falló. La bandeja avisa arriba en rojo cuando una fuente se rompe: sin ese
aviso, «esta semana no hay licitaciones» y «el conector está roto» se ven igual.

**Error de certificado / TLS al descargar de PLACSP.** El almacén de certificados de
macOS no incluye la raíz de la FNMT que firma PLACSP, así que el proyecto lleva su
propio `config/certs/ca-bundle.pem`. Si caduca:

```bash
pip install --upgrade certifi && python3 herramientas/regenerar_ca_bundle.py
```

Nunca se desactiva la verificación de certificados; el script aborta si el bundle
nuevo no trae las raíces españolas.

**He cambiado un perfil y no aparece lo que esperaba.** `match` solo reevalúa lo que
ya está descargado. Si el término nuevo hay que preguntárselo a TED o a Cataluña:

```bash
python3 radar.py ingest --reiniciar-cursor --dias 365
```

**Quiero empezar de cero.** Borra la carpeta `data/` y vuelve a lanzar `ingest`. El
triaje y las notas viven ahí, así que se pierden.

**La base ocupa mucho.** Con todo el histórico son unos 3 GB, porque son cientos de
miles de licitaciones. No se comparte al pasar la carpeta a un compañero:
`data/` está en el `.gitignore` a propósito y cada uno construye la suya, con su triaje
y sus notas. Si no te interesa el histórico, borra `data/` y haz una ingesta normal, sin
`--primera-carga`: te quedarás con la ventana de los últimos días.

Y los ZIP del histórico se guardan en `data/cache/` para no volver a descargarlos, que
son otros **5,3 GB**: entre las dos cosas, `data/` se planta en 8,5 GB. `python3
radar.py estado` te dice cuánto ocupan y `python3 radar.py estado --limpiar-cache` los
borra sin perder ningún dato —se volverán a bajar la próxima vez que pidas histórico—.
Ahí pueden aparecer también ficheros `.parcial`: son descargas cortadas a medias que se
guardan por si el servidor permitiera continuarlas. `--limpiar-cache` también se los
lleva, y borrarlos no pierde nada.

Los ZIP de años cerrados no se vuelven a pedir nunca, porque ya no cambian. El del año
en curso sí: PLACSP lo reescribe cada día, así que si el que tienes guardado pasa de un
día, el siguiente `--backfill` o `--primera-carga` lo refresca. Y si esa descarga falla,
se sigue usando el viejo con un aviso en el registro en lugar de quedarte sin nada.

**Venía de una versión anterior.** No hay que hacer nada: al arrancar se añaden las
columnas que falten y se recalculan las claves de agrupación sin volver a descargar,
conservando el triaje y las notas. La primera ingesta marcará muchas licitaciones
como «actualizadas» —es solo que ahora se guardan más campos— pero el historial no se
ensucia: solo anota versión cuando cambia el estado, el adjudicatario o el importe.

---

## Cómo está hecho

Python 3 con **cero dependencias externas** (solo biblioteca estándar) y un frontend
estático sin compilar. Es deliberado: cualquiera puede clonar la carpeta y arrancar
sin instalar nada.

```
radar.py              punto de entrada de la línea de comandos
radar/
  net.py              descargas con TLS verificado, reintentos y reanudación
  model.py            el modelo común al que traducen todas las fuentes
  db.py               SQLite: esquema, migraciones, dedup e historial
  matching.py         el motor de reglas
  consultas.py        las consultas de las vistas, la analítica y el CSV
  pipeline.py         orquesta la ingesta: qué fuentes, en qué orden, por etapas
  server.py           servidor local (solo 127.0.0.1)
  busqueda.py         lanza la ingesta en segundo plano y su cerrojo
  progreso.py         el indicador de la terminal y la instantánea que lee la app
  programar.py        la tarea diaria de macOS
  actualizacion.py    traer una versión nueva sin salir de la aplicación
  diagnostico.py      las comprobaciones de `radar.py doctor`
  sources/            un conector por fuente, independientes entre sí
config/perfiles.json  tus búsquedas guardadas — esto es lo que se edita (no se versiona)
config/perfiles.ejemplo.json  la plantilla genérica de la que se crea el anterior
web/                  la interfaz
tests/                361 pruebas, con datos reales de las fuentes como fixtures
data/radar.db         la base (se crea sola; aquí vive tu triaje)
data/cache/           los ZIP del histórico, para no volver a bajarlos
data/busqueda.log     lo que va contando la descarga lanzada desde la aplicación
```

Los conectores están aislados a propósito: si Cataluña cambia su esquema una mañana,
el resto de la ingesta sigue funcionando y la bandeja lo dice.

```bash
python3 -m unittest discover -s tests -t .
```

Se ejecutan también en cada push, en Python 3.9 —el mínimo que se declara arriba, y el
que se rompe sin que nadie lo note en un equipo con un Python nuevo— y en 3.13, en Linux
y en macOS. La receta está en `.github/workflows/tests.yml`.

Los tests incluyen doce licitaciones reales verificadas (entre ellas la oficina de
concienciación de LANTIK, 915.000 €, la oficina de ciberseguridad del Ministerio de
Cultura, 1.031.857 €, y una plataforma de phishing sin CPV) y quince falsos
positivos observados —concienciación medioambiental, seguridad vial, prevención de
riesgos laborales, «sistemas de información» que no es «formación»— que deben seguir
quedando fuera. Si tocas `matching.py` o los perfiles, esos tests te dicen si has
roto la precisión.

Uno de ellos merece atención especial:
`test_los_terminos_casan_a_principio_de_palabra_pero_siguen_siendo_raices` fija las
dos mitades de un contrato que se contrapesan. Si alguna vez te parece que el matcher
debería usar `\b` a los dos lados de cada término, ese test falla por la mitad de
abajo: cerrar el final rompe el diseño de raíces del que depende media configuración.
