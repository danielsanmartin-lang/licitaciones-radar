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

Doble clic en **`Radar de Licitaciones.app`**.

Se abre como cualquier programa del Mac: su ventana, su icono en el Dock, su menú. Por
dentro arranca el servidor de Python, espera a que conteste y enseña la bandeja; tarda
dos o tres segundos. No hay que dejar ninguna terminal abierta, y al salir con ⌘Q el
servidor se para con ella.

**La app se lleva el programa dentro** —`radar/`, `web/` y los certificados van en
`Contents/Resources`— así que es **un solo fichero de 1,7 MB** que se puede arrastrar a
Aplicaciones, comprimir y mandar por correo. Lo único que hace falta en el otro Mac es
Python 3.9 o superior.

Si no está, se monta en un segundo:

```bash
python3 herramientas/construir_app.py
```

**`start.command`** sigue ahí y hace lo mismo sin la ventana propia: descarga las
novedades y abre la bandeja en el navegador. Es el camino de siempre y el que conviene
si algo va raro, porque va contando lo que hace por la terminal.

> **La primera vez, macOS desconfía.** La app no está firmada con un certificado de
> Apple —eso cuesta 99 $ al año y no los vale para una herramienta de uso interno—, así
> que si te la has descargado de GitHub el sistema se negará a abrirla de un doble clic.
> Se resuelve una sola vez: **clic derecho sobre la app → Abrir**, y confirmar. Desde
> entonces se abre normal. Si prefieres la terminal:
>
> ```bash
> xattr -dr com.apple.quarantine "Radar de Licitaciones.app"
> ```
>
> Y si te la construyes tú con el comando de arriba, no pasa nada de esto.

La primera vez es distinta y merece su propio apartado, justo abajo.

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

### Pasársela a un compañero

Un fichero y una advertencia.

```bash
python3 herramientas/construir_app.py --zip
```

Deja un **«Radar de Licitaciones X.Y.Z.zip» de unos 1.000 KB**. Eso es todo lo que hay
que mandar: por correo, por Slack o por AirDrop. Tu compañero lo descomprime, arrastra la
app a Aplicaciones y la abre. No hay que copiar carpetas, ni respetar rutas, ni instalar
nada más allá de Python.

La advertencia: **esa copia lleva la plantilla genérica de términos de búsqueda, no los
tuyos.** Es a propósito —los términos afinados durante meses no viajan dentro de un
paquete que se reparte— pero significa que arrancaría con un filtro que no encuentra
nada. Si quieres que empiece con tu configuración, mándale aparte tu
`config/perfiles.json` y que lo deje en:

```
~/Library/Application Support/Radar de Licitaciones/config/perfiles.json
```

Lo que **no** viaja nunca dentro de la app, y conviene saberlo: tu base de datos, tu
triaje y tus notas. Hay un test que lo vigila (`tests/test_rutas.py`), porque mandar la
app a alguien no puede ser mandarle por accidente en qué oportunidades estás trabajando.

Y la primera vez, macOS desconfiará de la app igual que de cualquier programa sin firmar
descargado de internet: clic derecho → Abrir. Está explicado arriba.

### Dónde viven tus datos

Depende de cómo la uses, y la regla es explícita:

| | |
|---|---|
| App montada **dentro de la carpeta del proyecto** | `data/` y `config/` del proyecto, como siempre |
| App **en Aplicaciones** o recibida de alguien | `~/Library/Application Support/Radar de Licitaciones` |
| `RADAR_DATOS` en el entorno | donde diga esa variable, y manda sobre las otras dos |

Es decir: **si trabajas con el repositorio, nada cambia y tu base no se mueve de sitio.**
La app que montas ahí usa ese código y esa base. Si arrastras la app a Aplicaciones se
convierte en una instalación independiente y empezaría de cero, con su propia base
vacía; si quieres llevarte la que ya tienes, muévela una vez:

```bash
mkdir -p ~/Library/Application\ Support/Radar\ de\ Licitaciones
mv data ~/Library/Application\ Support/Radar\ de\ Licitaciones/
mkdir -p ~/Library/Application\ Support/Radar\ de\ Licitaciones/config
mv config/perfiles.json ~/Library/Application\ Support/Radar\ de\ Licitaciones/config/
```

Nunca se escribe dentro de la app. No es una preferencia: un `.app` puede estar en
`/Applications`, que no es tuyo; está firmado, y escribir dentro invalida la firma; y la
actualización lo sustituye entero, así que cualquier cosa guardada ahí se perdería en la
versión siguiente.

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
a la derecha, y debajo, en pequeño, cuánto lleva publicada —que es lo que explica por
qué está en ese sitio de la lista, ahora que la bandeja abre por lo último publicado—.
De cada licitación se ve el órgano, el importe, el plazo y los enlaces a los pliegos
oficiales.

**Lo que marcas como «siguiendo» o «presentada» no se va de la bandeja nunca**, aunque
dejes de tener un perfil que lo case. Es a propósito: marcar algo es una decisión tuya y
pesa más que el filtro automático. La ficha aparece sin píldora de perfil y su apartado
«Por qué ha entrado» dice que está en la base pero no casa con ningún perfil activo, que
es la verdad.

Lo aprendimos por las malas. Al estrechar los perfiles se fue de la bandeja un contrato
de 6,25 M€ de Canal de Isabel II que estaba en seguimiento, con 23 días de plazo: su
triaje y sus notas seguían en la base, intactos, pero no había manera de verlo —ni el
filtro de estado ni la búsqueda libre pasan por fuera de las coincidencias—, y el
contador de la cabecera decía 1 donde había 2. Ajustar los términos no puede esconderte
algo en lo que estás trabajando.

Lo **descartado** que deja de casar sí desaparece, y también a propósito: ahí el filtro y
tu decisión dicen lo mismo.

Las que llevan menos de una semana publicadas salen con la etiqueta **Nueva**, la única
rellena de la fila para que se vea sin leer. La semana se cuenta desde la **primera**
publicación del expediente, no desde el anuncio que se enseña: si una adjudicación de
ayer marcara como nuevo un pliego de junio, la etiqueta mandaría a alguien a un contrato
ya cerrado. Medido sobre la base real, ese criterio ingenuo marcaba 16 y cinco eran falsas.

El desplegable de orden ofrece **cierran antes**, **mejor encaje**, **publicación más
reciente**, **publicación más antigua** y **mayor importe**. Los dos de fecha usan también
la primera publicación del expediente, así que ordenar por «más reciente» deja justo
arriba las que llevan la etiqueta Nueva.

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

Las preguntas que no son «qué hay hoy». Catorce bloques, cada uno con una pregunta de
venta delante, en el orden en que se leen:

| Bloque | Contesta a |
|---|---|
| Cuándo sale el trabajo | en qué meses hay que estar preparado. Diciembre publica el doble que agosto, y eso se planifica en septiembre |
| Tamaño de los contratos | de qué tamaño son estas operaciones de verdad |
| Importe al que se están cerrando los contratos | cuánto por debajo del presupuesto se están cerrando |
| Cuánto tiempo tengo para presentar | cuántos días hay del anuncio al cierre del plazo: si lo veo hoy, si da tiempo a escribir la oferta |
| Top comunidades por adjudicaciones | dónde se ha repartido el dinero que ya está adjudicado |
| Top comunidades por número total de adjudicaciones | dónde se cierran más operaciones, cuesten lo que cuesten |
| Top comunidades por licitaciones activas | dónde queda dinero en juego, con el plazo todavía abierto |
| Top comunidades por número de licitaciones activas | dónde hay más pliegos abiertos ahora mismo |
| Quién compra | qué órganos de contratación repiten, y a quién merece la pena ir a ver |
| Qué compran exactamente | en qué CPV cae tu producto, con enlace para afinar los términos |
| Cómo se compra | por qué puerta se entra: abierto, simplificado, restringido o por invitación |
| Cuándo entra en el forecast | cuántos días pasan de la publicación a la adjudicación |
| A quién llamo antes del pliego | cuántos contratos se acaban en seis meses, con incumbente conocido |
| Qué tengo de verdad hoy | si esto es un pipeline o un archivo histórico |

Se filtra por perfil y por uno de tres rangos (este año, últimos 24 meses, todo desde
2024). Los dos bloques que hablan de *ahora* —renovaciones y cartera— ignoran el rango a
propósito y lo dicen, porque un filtro que se ignora en silencio es peor que uno que falta.

Los cuatro bloques de comunidades van emparejados, dinero a la izquierda y número a la
derecha, porque **los dos órdenes casi nunca coinciden y ahí está la información**:
Cataluña es la 3.ª por euros y la **2.ª por operaciones**, País Vasco la 10.ª y la 6.ª. Un
mercado de muchos contratos pequeños y uno de pocos contratos grandes se trabajan distinto.

Tres cosas que conviene tener en la cabeza al leer el reparto territorial:

- **La comunidad es la del órgano que contrata, no la del trabajo.** Los órganos de compra
  centralizada del Estado están en Madrid, así que Madrid absorbe las compras nacionales:
  medido, el 67% de su dinero adjudicado son cuatro órganos estatales —Racionalización y
  Centralización (26%), Adquisiciones de Armamento (19,5%), Administración Digital (12,9%)
  e Infraestructura del MDE (8,3%)—, mientras que los órganos propios de la Comunidad de
  Madrid no llegan al 7%. «Madrid» aquí no es el mercado madrileño, y compararlo con el PIB
  regional es comparar cosas distintas.
- **El importe de un expediente suma sus lotes, no coge el mayor.** Cataluña publica una
  fila por lote y PLACSP una por licitación; con un máximo a secas se contaba el lote mayor
  y se tiraban los demás. Es la única comunidad que se veía afectada: 51,9 M€ contra los
  61,7 M€ reales, un 19% de menos, que la hacía caer del tercer puesto al cuarto.
- **Los gráficos de número no aplican el corte de 50 M€.** Un recuento no lo desequilibra un
  contrato grande, y apartarlo escondería licitaciones a las que sí se puede ir. Por eso una
  comunidad puede aparecer con más expedientes en el gráfico de número que junto a su barra
  de dinero, y el pie de cada gráfico lo dice.

Y hay tres cosas que esta pestaña **no** hace, todas por el mismo motivo:

- **No da cifras de dinero total, salvo en el reparto por comunidad.** La clave que agrupa
  los anuncios de un mismo expediente no cruza fuentes, así que 126 expedientes están
  repetidos entre PLACSP y TED y arrastran casi 1.000 M€ de aire: en el resto de los
  bloques solo hay medianas, tramos y recuentos. El reparto territorial es la excepción, y
  no por comodidad: TED no publica región, así que de cada pareja duplicada su copia cae
  en «sin comunidad» y no en el total de ninguna. Es el único corte de esta base que se
  puede sumar sin contar dos veces lo mismo, y hay una prueba que lo vigila.
- **Y aun ahí aparta los macro-contratos, pero los enseña.** Un sistema dinámico de
  adquisición de 2.646 M€ no es un contrato al que presentarse, y en la misma escala deja
  a diecisiete comunidades pintando una raya de un píxel. Los de más de 50 M€ salen de las
  barras y van al pie con su nombre, su importe y el total de verdad de su comunidad. En
  lo que está vivo son el 96% del dinero, y ése es justo el dato: hoy no hay un mercado
  repartido, hay cuatro plataformas de compra.
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

Sustituye el código —`radar/`, `web/`, `radar.py`, `start.command`, `macos/` y los
certificados— y guarda lo anterior al lado como `.anterior` para poder volver atrás. **No
toca `data/`**, donde están tu base, tu triaje y tus notas, **ni `config/perfiles.json`**,
que son tus términos de búsqueda. Si hay una descarga en marcha, se niega: cambiar el
código por debajo de una carga que dura horas es pedir problemas.

Después hay que cerrar la aplicación y volver a abrirla, porque el proceso que está
corriendo ya tiene en memoria la versión vieja. Los cambios en la base de datos que traiga
la versión nueva se aplican solos en ese siguiente arranque.

Todo eso vale para una **copia de trabajo**, donde el código está en la carpeta y se
puede sustituir. `Radar de Licitaciones.app` no se toca: un programa no puede cambiarse a
sí mismo mientras corre. No hace falta, porque lo que sí se sustituye es de lo que está
hecha; al volver a abrirla se da cuenta de que su versión ya no coincide con la del código
y se ofrece a rehacerse. A mano es `python3 herramientas/construir_app.py --forzar`.

En una **app recibida de alguien**, que lleva el programa dentro, no hay ficheros que
sustituir y el botón hace otra cosa: dice que hay versión nueva y ofrece **descargarla**.
Se arrastra encima de la vieja, como cualquier programa de Mac. Los datos están fuera de
la app, así que no se pierde nada al reemplazarla.

### Publicar una versión

Lo que mira el actualizador es la **última release publicada en GitHub**, así que subir
código al repositorio no actualiza a nadie. Para publicar una:

1. Sube `__version__` en `radar/__init__.py`.
2. Reconstruye la app, deja el binario compilado en el repositorio y empaqueta el
   `.app` para adjuntarlo:

   ```bash
   python3 herramientas/construir_app.py --forzar --prefabricar --zip
   ```

   `--prefabricar` actualiza `macos/prefabricado/radar`, de donde saca la ventana nativa
   quien no tenga las herramientas de Apple. `--zip` deja un
   «Radar de Licitaciones X.Y.Z.zip» y te dice su SHA-256.
3. **Adjunta ese zip a la release.** Es lo que busca la app empaquetada cuando ofrece
   actualizarse; lo localiza por el nombre, así que basta con que lleve «Radar» y acabe
   en `.zip`. Si te lo olvidas, la app lleva al usuario a la página de la release en
   lugar de dejarlo sin salida, pero le toca buscar el fichero a mano.
4. Etiqueta la release con ese mismo número. Si no coinciden, el actualizador se niega a
   instalarla —que es lo que se quiere cuando el paquete no es lo que dice ser—.

```bash
gh release create v1.1.0 --title "v1.1.0 — …" --notes "…"
```

Lo que se descarga es el zip que GitHub genera del propio tag, no un fichero que haya que
subir. Y **el repositorio tiene que ser público**: si no, la comprobación de versión
recibe un 404 y el botón no aparece —eso ya lo explica el mensaje de error—.

Sobre el SHA-256, que tiene dos mitades y conviene no confundirlas.

Para la **copia de trabajo**, el actualizador busca un SHA en las notas y, si lo
encuentra, exige que cuadre. Suena bien y es una trampa, porque ese zip lo genera GitHub
al vuelo desde el tag y su suma puede cambiar sin que cambie el código; el día que pase,
nadie podría actualizar y el mensaje hablaría de un SHA que no le dice nada a quien lo
lee. La defensa real es HTTPS contra este repositorio, así que las notas van sin SHA.

Para el **zip del `.app`** es distinto: ese fichero lo subes tú y su hash es estable, así
que el que imprime `--zip` sí es una comprobación de verdad. Ponerlo en las notas de la
release es útil, y quien reciba la app por otro camino puede contrastarlo.

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

Sobre un histórico de 2024–2026 el filtro deja pasar **menos de una diezmilésima de lo
que descarga**: 519 anuncios de 686.302. Es un filtro deliberadamente estrecho, y esa es
la decisión de fondo: la bandeja está calibrada para lo que se vende —concienciación y
protección del correo— y no para la ciberseguridad en general.

La configuración de referencia trae cuatro perfiles y **solo tres activos**:

| Perfil | Anuncios | |
|---|---|---|
| Concienciación y phishing | 412 | el nicho: simulaciones, formación, cultura de seguridad |
| Protección del correo electrónico | 107 | DMARC, pasarelas, antiphishing, antispam |
| Consultas previas al mercado | 0 hoy | vigilancia: avisa cuando salga una consulta preliminar del nicho |
| ~~Ciberseguridad y seguridad de la información~~ | desactivado | SOC, ENS, pentesting, seguridad gestionada |

El cuarto está **desactivado a propósito**, y merece la pena saber por qué: aportaba
3.123 de las 3.780 coincidencias que había antes, cuatro de cada cinco fichas de la
bandeja, y ninguna era presentable. Si algún día el catálogo se amplía a servicios de
ciberseguridad más generales, se reactiva marcando **«activo»** en la pestaña «Términos
de búsqueda»: sus 41 términos siguen escritos en el fichero. A mano es lo mismo,
`"activo": true` en `config/perfiles.json` y relanzar `match`.

El de **consultas previas** está en cero y también es a propósito. Son las consultas
preliminares al mercado, el único momento en que todavía se puede influir en un pliego
antes de que se escriba, así que vale la pena tener el canal abierto aunque hoy no pase
nada por él. Estuvo dando catorce fichas hasta que se miraron una por una: boletines
oficiales, remolques carrozados, recambios de SAI y transporte de datos IP. Nueve de las
catorce entraban solo porque el órgano que las publicaba se llama «Agència de
Digitalització, **Ciberseguretat** i Telecomunicacions».

Lo cual lleva a la otra cosa que se arregló midiendo, y que conviene no volver a
romper: **el nombre del organismo no entra en las reglas**. Lo que se indexa para la
caja de búsqueda sí lo lleva —buscar «Viladecans» tiene que funcionar— pero lo que se
evalúa son objeto, descripción y lotes, y nada más. Con el nombre dentro, «Instituto
Nacional de **Ciberseguridad**», «Departament d'Educació i **Formació** Professional» o
«**Ens** d'Abastament d'Aigua Ter-Llobregat» regalaban el término ambiguo, el contexto
requerido, o los dos: eran 125 de las 535 coincidencias del perfil de concienciación, el
23 %, entre ellas «Formación en Gestión de Proyectos Europeos y soft-skills» del INCIBE
y unas obras de un módulo prefabricado. Ninguna de las 125 llevaba un término fuerte, así
que quitar el órgano no costó ni un verdadero positivo. Está en
`Licitacion.texto_reglas`, con los tests en `tests/test_reevaluacion.py`.

Si te sigue pareciendo que hay ruido, endurece `contexto_requerido` o sube
`importe_minimo`.

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

**La app se queda en «Arrancando el radar…».** Significa que el servidor de Python no
ha llegado a contestar. Para ver por qué, arranca el binario desde la terminal en lugar
de con doble clic: escribe por la salida de error lo que va encontrando —la carpeta del
proyecto, qué Python ha elegido, si ha podido lanzar el servidor—.

```bash
"./Radar de Licitaciones.app/Contents/MacOS/radar"
```

La causa habitual es que no haya un Python 3.9+ instalado; la app no lo empaqueta y
macOS ya no lo trae de serie. La otra es una copia de la app montada a medias, sin el
programa dentro: se arregla volviéndola a montar. Mientras tanto, `start.command` sigue
funcionando.

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

Con una excepción, que conviene decir clara: la ventana nativa de macOS es un programa
de Swift compilado, y su binario **sí está en el repositorio** (`macos/prefabricado/`).
No es una dependencia —nada de Python lo necesita, y `start.command` funciona igual sin
él— pero es el único trozo de este proyecto que no se puede leer antes de ejecutarlo. Se
comprometió porque el zip de una release de GitHub solo lleva fuentes, y un compañero sin
las herramientas de Apple instaladas no podría compilarlo. El fuente está al lado, en
`macos/Radar.swift`, y se reconstruye con `python3 herramientas/construir_app.py`.

```
radar.py              punto de entrada de la línea de comandos
radar/
  rutas.py            dónde está el código y dónde se escriben los datos
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
macos/Radar.swift     la ventana nativa: arranca el servidor y lo enseña
macos/icono.svg       el icono, en texto; se rasteriza al montar la app
macos/prefabricado/   el binario ya compilado, para quien no tenga las herramientas
herramientas/construir_app.py  monta «Radar de Licitaciones.app»
tests/                442 pruebas, con datos reales de las fuentes como fixtures
data/radar.db         la base (se crea sola; aquí vive tu triaje)
data/cache/           los ZIP del histórico, para no volver a bajarlos
data/busqueda.log     lo que va contando la descarga lanzada desde la aplicación
```

Los conectores están aislados a propósito: si Cataluña cambia su esquema una mañana,
el resto de la ingesta sigue funcionando y la bandeja lo dice.

**`radar/rutas.py` merece un párrafo**, porque es lo que permite repartir el programa en
un solo fichero. Durante mucho tiempo todo colgaba de la carpeta del proyecto: ahí vivían
`radar/` y también `data/radar.db`. Para una copia clonada del repositorio eso está bien
y sigue siendo lo que pasa. Lo que no permitía era meter el código dentro de un `.app`,
porque ahí no se puede escribir. Así que hay dos raíces y no una: `CODIGO`, de donde se
lee —`web/`, los certificados, la plantilla de perfiles—, y `DATOS`, donde se escribe
—la base, la caché, el `perfiles.json` de cada uno—. La regla que las separa está en el
docstring del módulo y se resume en la tabla de «Dónde viven tus datos», más arriba.

Si algún día hay que añadir un fichero que el programa escriba, va en `DATOS`. Si es algo
que solo se lee, en `CODIGO`. Ponerlo en el sitio equivocado no falla en una copia de
trabajo —las dos raíces son la misma— y falla en la app empaquetada, que es el peor sitio
donde enterarse.

```bash
python3 -m unittest discover -s tests -t .
```

Se ejecutan también en cada push, en Python 3.9 —el mínimo que se declara arriba, y el
que se rompe sin que nadie lo note en un equipo con un Python nuevo— y en 3.13, en Linux
y en macOS. La receta está en `.github/workflows/tests.yml`.

Los tests incluyen licitaciones reales verificadas (entre ellas la oficina de
concienciación de LANTIK, 915.000 €, y una plataforma de phishing sin CPV ni más pista
que la errata «phising») y una colección de falsos positivos observados
—concienciación medioambiental, seguridad vial, prevención de riesgos laborales,
«sistemas de información» que no es «formación», crema solar con SPF 50— que deben
seguir quedando fuera. Si tocas `matching.py` o los perfiles, esos tests te dicen si
has roto la precisión.

Y hay un grupo que está en el bando de los que NO deben entrar aunque sean contratos de
ciberseguridad de verdad: la oficina de ciberseguridad del Ministerio de Cultura
(1.031.857 €), la seguridad de la información de la Seguridad Social (22,9 M€) y una
asistencia de ENS y SOC. Entraban, y entraban bien; lo que cambió no fue el matcher sino
el catálogo. Están ahí para avisar si alguien reactiva el perfil amplio sin querer.

Uno de ellos merece atención especial:
`test_los_terminos_casan_a_principio_de_palabra_pero_siguen_siendo_raices` fija las
dos mitades de un contrato que se contrapesan. Si alguna vez te parece que el matcher
debería usar `\b` a los dos lados de cada término, ese test falla por la mitad de
abajo: cerrar el final rompe el diseño de raíces del que depende media configuración.
