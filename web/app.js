'use strict';

const POR_PAGINA = 100;
let offset = 0;
let ultimoTotal = 0;

const $ = (id) => document.getElementById(id);

const eur = new Intl.NumberFormat('es-ES', {
  style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
});

function fmtImporte(v) {
  return (v === null || v === undefined) ? 'sin importe' : eur.format(v);
}

function fmtFecha(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso.slice(0, 10);
  return d.toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: 'numeric' });
}

// --- Aviso de carga --------------------------------------------------------

// Con histórico en la base, algunas consultas recorren cientos de miles de filas y
// la pestaña tarda en pintarse. Antes no se avisaba de nada y, peor, el contenedor
// se vaciaba DESPUÉS de recibir los datos: durante esos segundos seguía en pantalla
// el contenido de la pestaña anterior y la aplicación parecía congelada.
//
// Tres detalles son los que hacen que el aviso ayude en vez de estorbar:
//   - el contenedor se vacía ANTES de pedir los datos, no después;
//   - el aviso no se pinta hasta pasados 150 ms, para que una consulta rápida no
//     provoque un parpadeo;
//   - cada contenedor lleva número de pasada, y la respuesta que llega tarde
//     —porque ya se ha cambiado de pestaña o de ventana— se descarta en lugar de
//     pintarse encima de lo que se está mirando.
const RETARDO_CARGANDO = 150;
const pasadas = new Map();

function empezarCarga(idContenedor, texto = 'Cargando…') {
  const cont = $(idContenedor);
  const pasada = (pasadas.get(idContenedor) || 0) + 1;
  pasadas.set(idContenedor, pasada);

  cont.innerHTML = '';
  cont.setAttribute('aria-busy', 'true');
  const temporizador = setTimeout(() => {
    if (pasadas.get(idContenedor) === pasada) {
      cont.innerHTML = `<p class="cargando">${texto}</p>`;
    }
  }, RETARDO_CARGANDO);

  // `terminar()` devuelve false si esta carga ya está pisada por otra posterior:
  // quien llama tiene que abandonar sin pintar.
  return {
    terminar() {
      clearTimeout(temporizador);
      if (pasadas.get(idContenedor) !== pasada) return false;
      cont.removeAttribute('aria-busy');
      cont.innerHTML = '';
      return true;
    },
  };
}

let soloNovedades = false;
let cierranEnDias = '';
// El otro filtro que solo pone un contador: «coincidencias» deja fuera lo vencido.
let sinVencidas = '';
let kpiActivo = 'en_plazo';

// Cada contador de la cabecera y el filtro que aplica. Tiene que coincidir con lo
// que calcula consultas.resumen() o el número volvería a no cuadrar con la lista.
// «coincidencias» no cuenta lo de plazo vencido: con ello decía 412 donde quedaban 101 que
// todavía se podían mirar. Lo que sigues ya no tiene contador aquí: tiene su vista.
const KPIS = [
  { clave: 'en_plazo', etiqueta: 'abiertas', filtro: { vivas: '1' } },
  { clave: 'cierran_7_dias', etiqueta: 'cierran ≤7d', clase: 'urgente',
    filtro: { vivas: '1', cierran_en_dias: '7' } },
  { clave: 'coincidencias', etiqueta: 'coincidencias',
    filtro: { vivas: '0', sin_vencidas: '1' } },
  { clave: 'sin_revisar', etiqueta: 'sin revisar', filtro: { vivas: '0', estado: 'nuevo' } },
];

function fmtFechaHora(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return iso.slice(0, 16).replace('T', ' ');
  return d.toLocaleString('es-ES', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function filtros() {
  return {
    q: $('q').value.trim(),
    perfil: $('perfil').value,
    estado: $('estado').value,
    ccaa: $('ccaa').value,
    importe_min: $('importe_min').value,
    orden: $('orden').value,
    vivas: $('vivas').checked ? '1' : '0',
    novedades: soloNovedades ? '1' : '',
    cierran_en_dias: cierranEnDias,
    sin_vencidas: sinVencidas,
    con_plazo: $('con-plazo').checked ? '1' : '',
  };
}

function aplicarKpi(clave) {
  const kpi = KPIS.find((k) => k.clave === clave);
  if (!kpi) return;
  kpiActivo = clave;
  cierranEnDias = kpi.filtro.cierran_en_dias || '';
  sinVencidas = kpi.filtro.sin_vencidas || '';
  $('vivas').checked = kpi.filtro.vivas === '1';
  $('estado').value = kpi.filtro.estado || '';
  mostrarVista('bandeja');
  cargarLista();
  for (const b of $('kpis').querySelectorAll('button.kpi')) {
    b.classList.toggle('activo', b.dataset.kpi === clave);
  }
}

function limpiarFiltros() {
  kpiActivo = null;
  cierranEnDias = '';
  sinVencidas = '';
  soloNovedades = false;
  ponerConPlazo(false);
  $('q').value = '';
  $('perfil').value = '';
  $('estado').value = '';
  $('ccaa').value = '';
  $('importe_min').value = '';
  $('vivas').checked = false;
  for (const b of $('kpis').querySelectorAll('button.kpi')) b.classList.remove('activo');
  cargarLista();
}

// El desplegable de triaje y la casilla de plazo se combinan, y eso no se veía:
// se elegía "todo menos descartadas" y seguían saliendo solo 57 porque "solo
// abiertas" seguía marcada. Ahora los filtros activos se dicen en voz alta.
function describirFiltros() {
  const partes = [];
  if ($('vivas').checked) partes.push('solo abiertas (plazo sin vencer)');
  if (cierranEnDias) partes.push(`cierran en ${cierranEnDias} días`);
  if (sinVencidas) partes.push('sin las de plazo vencido');
  if ($('con-plazo').checked) partes.push('sin las que no publican plazo');
  const estado = $('estado');
  if (estado.value) partes.push(estado.options[estado.selectedIndex].text.toLowerCase());
  if ($('perfil').value) partes.push($('perfil').value);
  if ($('ccaa').value) partes.push($('ccaa').value);
  if ($('importe_min').value) {
    partes.push(`desde ${eur.format(Number($('importe_min').value))}`);
  }
  if (soloNovedades) partes.push('solo novedades');
  if ($('q').value.trim()) partes.push(`texto “${$('q').value.trim()}”`);
  return partes;
}

function query(extra = {}) {
  const p = new URLSearchParams();
  const f = { ...filtros(), ...extra };
  for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
  return p.toString();
}

// --- Resumen y cabecera ----------------------------------------------------

// --- Qué cubre y qué no ----------------------------------------------------
//
// Los límites de la herramienta, siempre a mano y plegados. Las cifras salen del dato y
// no escritas a mano —si TED empezara a publicar región, el número baja solo—; el resto
// es prosa fija porque no depende de la base. Ningún porcentaje cableado aquí: eso
// envejece en silencio y acaba mintiendo.
const COBERTURA_ABIERTA = 'cobertura-abierta';

function pintarCobertura(c) {
  if (!c) return;
  const caja = $('cobertura');
  const sinCom = c.sin_comunidad.toLocaleString('es-ES');
  const total = c.expedientes.toLocaleString('es-ES');
  $('cobertura-resumen').textContent =
    `Qué cubre y qué no este radar · ${sinCom} de ${total} expedientes sin comunidad`;

  const desde = {};
  for (const f of c.fuentes || []) desde[f.fuente] = f.desde;
  const placsp = desde['placsp:licitaciones'];
  const historico = [['PLACSP', placsp], ['TED', desde.ted], ['Cataluña', desde.catalunya]]
    .filter(([, d]) => d).map(([n, d]) => `${n} desde ${d}`).join(', ');

  const puntos = [
    [`TED no publica región.`,
     ` ${sinCom} de ${total} expedientes se quedan sin comunidad ` +
     `(${c.sin_comunidad_ted.toLocaleString('es-ES')} vienen de TED): no entran en el ` +
     `reparto por comunidad ni los encuentra el filtro territorial.`],
    ['La comunidad es la del órgano que contrata, no la del trabajo.',
     ' Las compras centralizadas del Estado se firman en Madrid, así que «Madrid» no es ' +
     'el mercado madrileño: es España comprando desde Madrid.'],
    ['El histórico es desigual.',
     historico ? ` ${historico}.` : ' Todavía no hay histórico descargado.'],
    ['No se busca dentro de los PDF.',
     ' Solo en el título, el objeto y la descripción de los lotes, así que un pliego que ' +
     'solo menciona tu producto por dentro no aparece.'],
    ['Los contratos menores están desactivados.',
     ' De 6.572 de muestra solo pasaban 2 el filtro, y uno traía el importe mal.'],
    ['En el reparto por comunidad, los contratos de más de 50 M€ salen de las barras.',
     ' No caben en la misma escala; van al pie de cada gráfico con su nombre y su importe.'],
  ];
  const lista = $('cobertura-lista');
  lista.textContent = '';
  for (const [fuerte, resto] of puntos) {
    const li = document.createElement('li');
    li.innerHTML = '<b></b><span></span>';
    li.querySelector('b').textContent = fuerte;
    li.querySelector('span').textContent = resto;
    lista.appendChild(li);
  }

  // Se pinta una vez y se recuerda cómo lo dejaste. El listener se pone solo la primera
  // vez: `cargarResumen()` corre cada 12 s durante una búsqueda y si no, se acumularían.
  if (!caja.dataset.listo) {
    try {
      caja.open = localStorage.getItem(COBERTURA_ABIERTA) === '1';
    } catch { /* sin almacén, plegado y ya está */ }
    caja.addEventListener('toggle', () => {
      try {
        localStorage.setItem(COBERTURA_ABIERTA, caja.open ? '1' : '0');
      } catch { /* nada que hacer: se plegará al recargar */ }
    });
    caja.dataset.listo = '1';
  }
}

// --- Avisos de salud de las fuentes ----------------------------------------
//
// Se pueden cerrar, y se quedan cerrados hasta que se vuelvan a consultar datos. Eso no
// necesita ningún temporizador ni ninguna fecha de caducidad: la clave del descarte
// lleva dentro el `iniciado_en` de la ingesta que provocó el aviso, así que en cuanto
// corre una ingesta nueva la clave deja de coincidir y el aviso vuelve a salir —solo si
// sigue habiendo motivo, claro—.
//
// Hay que guardarlo fuera del DOM porque `#avisos` se reescribe entero en cada
// `cargarResumen()`, y eso ocurre cada 12 s mientras hay una búsqueda en marcha: poner
// `hidden` al cerrar duraría hasta el refresco siguiente. Es el mismo motivo que ya
// documenta el comentario de `#aviso-version` en index.html.
const AVISOS_DESCARTADOS = 'avisos-descartados';

// El orden elegido en la bandeja. Se recuerda porque el de fábrica cambió en esta
// versión —de «cierran antes» a «publicación más reciente»— y cambiar el valor por
// defecto sin dar manera de fijar el propio es cambiárselo dos veces a quien prefería
// el anterior.
const ORDEN_BANDEJA = 'orden-bandeja';
// «Ocultar sin plazo», que también se recuerda: es una forma de mirar la Bandeja, como el
// orden, y no un filtro de un momento.
const CON_PLAZO = 'ocultar-sin-plazo';

function ponerConPlazo(activo) {
  $('con-plazo').checked = activo;
  try {
    localStorage.setItem(CON_PLAZO, activo ? '1' : '0');
  } catch { /* sin almacén, se olvidará al recargar */ }
}

function claveAviso(f) {
  return `${f.fuente}|${f.iniciado_en || ''}`;
}

function leerDescartados() {
  try {
    const guardado = JSON.parse(localStorage.getItem(AVISOS_DESCARTADOS) || '[]');
    return new Set(Array.isArray(guardado) ? guardado : []);
  } catch {
    // Un almacén deshabilitado, lleno o con basura de otra versión no puede dejar a
    // nadie sin avisos: se empieza de cero, que como mucho cuesta volver a cerrarlos.
    return new Set();
  }
}

function guardarDescartados(claves, vigentes) {
  // Se podan las claves que ya no corresponden a ninguna ingesta con aviso: si no, la
  // lista crecería una entrada por fuente y por ingesta para siempre.
  try {
    localStorage.setItem(AVISOS_DESCARTADOS,
                         JSON.stringify([...claves].filter((c) => vigentes.has(c))));
  } catch {
    // Sin sitio donde guardarlo el aviso reaparecerá al recargar. Es mejor eso que
    // dejar de pintarlo.
  }
}

// Igual que `tarjeta()`: el `innerHTML` solo lleva el andamio, y el texto va por
// `textContent` porque `error` es el mensaje crudo de una fuente que no controlamos.
function pintarAvisos(fuentes) {
  const conAviso = (fuentes || []).filter((f) => f.aviso);
  const vigentes = new Set(conAviso.map(claveAviso));
  const descartados = leerDescartados();
  const problemas = conAviso.filter((f) => !descartados.has(claveAviso(f)));

  const av = $('avisos');
  av.textContent = '';
  av.hidden = problemas.length === 0;
  for (const f of problemas) {
    const linea = document.createElement('p');
    linea.innerHTML = '<strong></strong><span></span>' +
      '<button class="cerrar" aria-label="Cerrar aviso" title="Cerrar aviso">×</button>';
    linea.querySelector('strong').textContent = f.fuente;
    linea.querySelector('span').textContent =
      `: ${f.aviso}${f.error ? ` — ${f.error.slice(0, 180)}` : ''}`;
    linea.querySelector('.cerrar').addEventListener('click', () => {
      descartados.add(claveAviso(f));
      guardarDescartados(descartados, vigentes);
      pintarAvisos(fuentes);
    });
    av.appendChild(linea);
  }
}

// Rellena un desplegable de filtro con lo que hay ahora mismo, conservando lo elegido.
//
// Antes esto se hacía una sola vez por carga de página («si solo tiene la opción de
// todos, llénalo»), y el resultado era que activar un perfil en «Términos de búsqueda»
// no lo ponía en el desplegable de la bandeja hasta recargar la ventana: la lista ya
// lo filtraba bien, el desplegable no lo ofrecía.
//
// Se compara antes de tocar nada porque `cargarResumen()` se llama cada doce segundos
// mientras hay una búsqueda en marcha, y rehacer las opciones de un <select> que está
// desplegado lo cierra en las narices de quien lo estaba mirando.
function llenarSelect(sel, opciones) {
  const firma = JSON.stringify(opciones);
  if (sel.dataset.firma === firma) return;
  sel.dataset.firma = firma;

  const elegido = sel.value;
  // La primera opción es el «todos», que la escribe el HTML y no se toca.
  while (sel.options.length > 1) sel.remove(1);
  for (const [valor, etiqueta] of opciones) sel.add(new Option(etiqueta, valor));
  // Si lo que estaba elegido ya no está —se ha desactivado ese perfil— se vuelve a
  // «todos», que es lo que la lista está enseñando de todas formas.
  sel.value = [...sel.options].some((o) => o.value === elegido) ? elegido : '';
}

async function cargarResumen() {
  const r = await fetch('/api/resumen');
  const d = await r.json();

  // Cada contador es un botón que aplica exactamente su propio filtro, y su cifra
  // sale de la misma función que alimenta la lista: al pulsarlo tienen que salir
  // esas licitaciones y no otras.
  $('kpis').innerHTML = KPIS.map(({ clave, etiqueta, clase }) =>
    `<button class="kpi ${clase || ''}" data-kpi="${clave}">
       <div class="n">${(d[clave] ?? 0).toLocaleString('es-ES')}</div>
       <div class="t">${etiqueta}</div>
     </button>`
  ).join('');
  for (const b of $('kpis').querySelectorAll('button.kpi')) {
    b.addEventListener('click', () => aplicarKpi(b.dataset.kpi));
    b.classList.toggle('activo', b.dataset.kpi === kpiActivo);
  }

  // Mientras hay una búsqueda en marcha ese hueco lo ocupa el progreso, y refrescar
  // las cifras cada pocos segundos lo borraría a intervalos.
  if (!vigilando) {
    $('ultima-busqueda').textContent = d.ultima_busqueda
      ? 'última búsqueda: ' + fmtFechaHora(d.ultima_busqueda)
      : 'todavía no se ha buscado nada';
  }

  llenarSelect($('perfil'),
               d.por_perfil.map((p) => [p.perfil, `${p.perfil} (${p.total})`]));
  llenarSelect($('ccaa'),
               d.ccaa.map((c) => [c.ccaa, `${c.ccaa} (${c.total})`]));
  // Los de Analítica y Adjudicatarios son otros controles, no el mismo: el de arriba
  // vive dentro de #filtros, que se oculta en cualquier vista que no sea la bandeja.
  ultimosPerfiles = d.por_perfil.map((p) => p.perfil);
  llenarAmbitos();

  // Salud de las fuentes: una fuente rota y una fuente sin novedades se ven
  // igual si no se avisa explícitamente.
  pintarAvisos(d.fuentes);
  pintarCobertura(d.cobertura);

  // Pestaña de novedades: solo aparece si hay algo nuevo desde la última visita.
  const tabN = $('tab-novedades');
  if (d.novedades > 0) {
    tabN.hidden = false;
    tabN.textContent = `${d.novedades} nuevas`;
  } else if (!soloNovedades) {
    tabN.hidden = true;
  }

  // En la barra lateral, en corto: cuántas fuentes van bien. El detalle de cada una, al
  // pasar el ratón, que es donde cabe; los fallos ya los cuenta en rojo `#avisos`.
  const fuentes = d.fuentes || [];
  const rotas = fuentes.filter((f) => !f.ok && !f.en_curso).length;
  $('salud').textContent = !fuentes.length ? 'Sin búsquedas todavía'
    : rotas ? `Fuentes: ${rotas} con error de ${fuentes.length}`
    : `Fuentes: las ${fuentes.length} al día`;
  $('salud').title = fuentes.map((f) =>
    `${f.fuente}: ${f.ok ? `${f.vistos.toLocaleString('es-ES')} vistas, ${f.nuevos} nuevas` : 'error'}`
  ).join('\n');
  $('cuenta-bandeja').textContent = d.sin_revisar ? d.sin_revisar.toLocaleString('es-ES') : '';
  $('cuenta-siguiendo').textContent =
    d.siguiendo_en_plazo ? d.siguiendo_en_plazo.toLocaleString('es-ES') : '';
  ultimoResumen = d;
  $('limpiar-abrir').disabled = !d.sin_revisar;
  if (!$('limpiar').hidden) pintarLimpiar();
}

// --- Limpiar lo sin revisar ---------------------------------------------------
//
// Cientos de «sin revisar» que nadie va a mirar una a una —en una base real, 410: 311 con
// el plazo vencido, 96 sin fecha y 3 en plazo— se pasan a «vista» de una vez. Siguen en la
// Bandeja; lo que sigues, has presentado o descartado no se toca, y se puede deshacer.

// Lo último que contestó /api/resumen: las cifras de las tres opciones salen de ahí.
let ultimoResumen = null;
// Los ids de la última limpieza, para «Deshacer».
let ultimaLimpieza = null;
let relojAvisoLote = null;

const CRITERIOS_LIMPIEZA = [
  { criterio: 'vencidas', cifra: (d) => d.sin_revisar_vencidas, texto: 'con el plazo vencido' },
  { criterio: 'sin_fecha', cifra: (d) => d.sin_revisar_sin_fecha, texto: 'sin fecha de cierre' },
  { criterio: 'todas', cifra: (d) => d.sin_revisar, texto: 'todas las sin revisar' },
];

function pintarLimpiar() {
  const cont = $('limpiar-opciones');
  cont.textContent = '';
  for (const c of CRITERIOS_LIMPIEZA) {
    const n = (ultimoResumen && c.cifra(ultimoResumen)) || 0;
    const b = crear('button', 'ventana');
    b.dataset.criterio = c.criterio;
    b.disabled = !n;
    b.appendChild(crear('div', 'n', n.toLocaleString('es-ES')));
    b.appendChild(crear('div', 't', c.texto));
    b.addEventListener('click', () => limpiarSinRevisar(c.criterio));
    cont.appendChild(b);
  }
}

function abrirLimpiar() {
  const abierto = !$('limpiar').hidden;
  $('limpiar').hidden = abierto;
  if (!abierto) pintarLimpiar();
}

async function limpiarSinRevisar(criterio) {
  for (const b of $('limpiar-opciones').querySelectorAll('button')) b.disabled = true;
  let d;
  try {
    d = await pedirJSON('/api/revision/lote', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ criterio }) });
  } catch {
    d = { error: 'No se ha podido hablar con el radar.' };
  }
  $('limpiar').hidden = true;
  if (d.error) {
    avisarLote(d.error, false);
    return;
  }
  ultimaLimpieza = d.ids;
  avisarLote(`${d.expedientes.toLocaleString('es-ES')} ` +
             `${d.expedientes === 1 ? 'marcada' : 'marcadas'} como vistas`, d.ids.length > 0);
  await cargarResumen();
  cargarLista();
}

async function deshacerLimpieza() {
  if (!ultimaLimpieza) return;
  const ids = ultimaLimpieza;
  ultimaLimpieza = null;
  $('lote-deshacer').disabled = true;
  try {
    await fetch('/api/revision/lote/deshacer', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) });
  } catch {
    avisarLote('No se ha podido deshacer: no hay conexión con el radar.', false);
    return;
  }
  avisarLote('Deshecho: vuelven a estar sin revisar.', false);
  await cargarResumen();
  cargarLista();
}

function avisarLote(texto, conDeshacer) {
  $('lote-aviso-txt').textContent = texto;
  $('lote-deshacer').hidden = !conDeshacer;
  $('lote-deshacer').disabled = false;
  $('lote-aviso').hidden = false;
  // Se va solo, pero con margen para pensárselo: deshacer es justo lo que se decide tarde,
  // después de echar un vistazo a la lista. Con 15 s se iba antes de haberla mirado.
  clearTimeout(relojAvisoLote);
  relojAvisoLote = setTimeout(() => { $('lote-aviso').hidden = true; }, 45000);
}

// --- Lista -----------------------------------------------------------------

// Un `<svg><use>` al sprite de `index.html`. Se crea como elemento y no como cadena
// porque todo lo que se monta en una tarjeta va por este camino: en cuanto una píldora
// se construye con `innerHTML`, el texto del pliego que lleva dentro se interpreta.
function icono(nombre) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'ico');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#' + nombre);
  svg.appendChild(use);
  return svg;
}

// Una píldora. `texto` SIEMPRE por `textContent`: viene de los pliegos.
//
// Antes se montaban con plantillas de cadena, y el comentario de aquí abajo decía —con
// razón— que el objeto y el órgano iban por `textContent`... pero el adjudicatario, la
// comunidad, el procedimiento y la fuente se interpolaban en el `innerHTML`. Son campos
// que llegan de PLACSP, de TED y de Cataluña; el riesgo práctico es bajo, pero la regla
// que el fichero se da a sí mismo no admite excepciones que nadie ha decidido.
function pildora(texto, { clase = '', ico = null, titulo = '' } = {}) {
  const el = document.createElement('span');
  el.className = clase ? `pill ${clase}` : 'pill';
  if (ico) el.appendChild(icono(ico));
  const t = document.createElement('span');
  t.textContent = texto;
  el.appendChild(t);
  if (titulo) el.title = titulo;
  return el;
}

function tarjeta(it) {
  const d = it.dias_restantes;

  const el = document.createElement('article');
  el.className = `tarjeta rev-${it.estado_revision}`;
  el.dataset.id = it.id;
  // El andamio, sin un solo dato dentro: los datos se meten abajo, uno a uno.
  el.innerHTML = `
    <div class="principal">
      <h3></h3>
      <div class="organo"></div>
    </div>
    <div class="derecha"></div>
    <div class="meta"></div>`;

  el.querySelector('h3').textContent = it.objeto || '(sin objeto)';
  const organo = el.querySelector('.organo');
  if (it.organo) {
    organo.appendChild(icono('ico-organo'));
    const n = document.createElement('span');
    n.textContent = it.organo;
    organo.appendChild(n);
  }

  // --- La columna de la derecha ---------------------------------------------
  //
  // La cifra grande sigue siendo los días al cierre, que es la que se decide mirando:
  // la antigüedad de la publicación ordena la lista, pero no dice qué hacer. Lo que se
  // añade debajo es esa antigüedad, en pequeño, porque desde que la bandeja abre por
  // «publicación más reciente» hace falta poder ver por qué una ficha está donde está.
  const derecha = el.querySelector('.derecha');
  const dias = document.createElement('div');
  if (d === null || d === undefined) {
    dias.className = 'dias';
    dias.innerHTML = '<small>sin plazo</small>';
  } else {
    dias.className = d < 0 ? 'dias vencido' : d <= 7 ? 'dias pronto' : 'dias';
    const n = document.createElement('span');
    n.textContent = String(d);
    dias.appendChild(n);
    const u = document.createElement('small');
    u.textContent = 'días';
    dias.appendChild(u);
  }
  derecha.appendChild(dias);

  const desde = it.dias_desde_publicacion;
  if (desde !== null && desde !== undefined) {
    const p = document.createElement('div');
    p.className = it.es_nueva ? 'publicada recien' : 'publicada';
    p.textContent = desde === 0 ? 'hoy'
      : desde === 1 ? 'hace 1 día'
      : `hace ${desde.toLocaleString('es-ES')} días`;
    p.title = 'primera publicación del expediente';
    derecha.appendChild(p);
  }

  // --- Las píldoras ---------------------------------------------------------
  //
  // Dos rangos, y el orden importa porque es el orden en que se leen. Primero las que
  // deciden —si es nueva, de qué perfil es, cuánto vale, cuándo cierra—, después las
  // descriptivas, que se reconocen de un vistazo y no se leen.
  const meta = el.querySelector('.meta');

  // Va la primera porque es lo único de la fila que caduca solo. `es_nueva` lo decide
  // el servidor sobre la PRIMERA publicación del expediente: una adjudicación de ayer
  // sobre un pliego de junio no es una oportunidad nueva, y marcarla como tal manda a
  // alguien a un contrato ya cerrado.
  if (it.es_nueva) {
    const cuando = desde === 0 ? 'publicada hoy'
      : `publicada hace ${desde} ${desde === 1 ? 'día' : 'días'}`;
    meta.appendChild(pildora('Nueva', { clase: 'nueva', ico: 'ico-destello', titulo: cuando }));
  }
  // `perfil` puede traer varios separados por coma: una licitación de protección de
  // correo con formación casa con dos perfiles y antes salía duplicada en la lista.
  for (const p of (it.perfil || '').split(',').filter(Boolean)) {
    meta.appendChild(pildora(p.trim(), { clase: 'perfil' }));
  }
  // Las fichas de «Otras licitaciones» no traen perfil y sí temáticas. «Resto» no se
  // pinta: no dice nada que no diga ya la falta de las demás.
  for (const c of (it.categorias || [])) {
    if (TEMAS.resto && c === TEMAS.resto.clave) continue;
    meta.appendChild(pildora(nombreTema(c), { clase: 'tema' }));
  }
  meta.appendChild(pildora(fmtImporte(it.importe_referencia), { clase: 'importe' }));
  // La fecha en la que salió, al lado de la del cierre. La cifra pequeña de la derecha
  // dice «hace 3 días», que es la antigüedad y sirve para ordenar; esto dice el día, que
  // es lo que se pregunta al mirar la lista («¿esto de cuándo es?») y lo que se copia al
  // correo. Se usa `primera_publicacion` —la del primer anuncio del expediente— y no la
  // del anuncio más reciente: es la misma con la que se decide «Nueva», así que la
  // píldora y la etiqueta no pueden contradecirse.
  const publicada = it.primera_publicacion || it.fecha_publicacion;
  if (publicada) {
    meta.appendChild(pildora(`publicada ${fmtFecha(publicada)}`,
                             { ico: 'ico-calendario',
                               titulo: 'primera publicación del expediente' }));
  }
  if (it.fecha_limite_presentacion) {
    const c = d === null ? '' : d < 0 ? 'plazo-vencido' : d <= 7 ? 'plazo-pronto' : 'plazo-ok';
    meta.appendChild(pildora(`cierra ${fmtFecha(it.fecha_limite_presentacion)}`,
                             { clase: c, ico: 'ico-reloj' }));
  }
  if (it.adjudicatario) {
    meta.appendChild(pildora(`ganó ${it.adjudicatario.slice(0, 38)}`, { clase: 'incumbente' }));
  }
  // Varios anuncios del mismo expediente colapsados en una fila.
  if ((it.anuncios || 1) > 1) {
    meta.appendChild(pildora(`${it.anuncios} anuncios`, { clase: 'anuncios' }));
  }
  if (it.ccaa) meta.appendChild(pildora(it.ccaa));
  if (it.procedimiento) meta.appendChild(pildora(it.procedimiento));
  meta.appendChild(pildora(it.fuente));
  if (it.estado_revision !== 'nuevo') meta.appendChild(pildora(it.estado_revision));

  el.addEventListener('click', () => abrirPanel(it.id));
  return el;
}

async function cargarLista(reset = true) {
  // Sin `reset` esto es «Cargar más»: añade al final, así que no se vacía nada ni se
  // avisa de carga; lo que hay en pantalla sigue siendo válido.
  const carga = reset ? empezarCarga('lista') : null;
  if (reset) offset = 0;

  let d;
  try {
    const r = await fetch('/api/bandeja?' + query({ limite: POR_PAGINA, offset }));
    d = await r.json();
  } catch {
    if (!carga || carga.terminar()) $('contador').textContent = 'No se pudo cargar la lista.';
    return;
  }
  if (carga && !carga.terminar()) return;

  if (d.error) {
    $('contador').textContent = d.error;
    $('mas').hidden = true;
    return;
  }

  ultimoTotal = d.total;
  const frag = document.createDocumentFragment();
  for (const it of d.items) frag.appendChild(tarjeta(it));
  $('lista').appendChild(frag);

  // "57 de 668 coincidencias" en lugar de "57 licitaciones": responde solo a la
  // pregunta de por qué no salen todas.
  const totalTxt = d.total.toLocaleString('es-ES');
  $('contador').textContent = d.total === d.total_sin_filtros
    ? `${totalTxt} ${d.total === 1 ? 'coincidencia' : 'coincidencias'}`
    : `${totalTxt} de ${d.total_sin_filtros.toLocaleString('es-ES')} coincidencias`;

  const activos = describirFiltros();
  const fa = $('filtros-activos');
  if (activos.length) {
    fa.hidden = false;
    fa.textContent = 'Filtrando por: ' + activos.join(' · ');
    const btn = document.createElement('button');
    btn.className = 'quitar';
    btn.textContent = 'ver todas';
    btn.addEventListener('click', limpiarFiltros);
    fa.appendChild(btn);
  } else {
    fa.hidden = true;
  }

  $('vacio').hidden = d.total !== 0;
  if (d.total === 0) {
    $('vacio').textContent = activos.length
      ? 'Nada con estos filtros.'
      : 'Sin coincidencias todavía. En «Términos de búsqueda» puedes forzar una búsqueda.';
  }
  offset += d.items.length;
  $('mas').hidden = offset >= d.total;
  $('exportar').href = '/api/export.csv?' + query();
}

// --- Otras licitaciones ----------------------------------------------------
//
// Lo que el radar descarga y no casa con ningún perfil. Es casi toda la base, así que
// arranca acotado —solo lo abierto— y se ordena por temáticas, que son chips de
// selección múltiple: ninguno elegido es «todas».

const TEMAS_OTRAS = 'temas-otras';
let otrasOffset = 0;
let otrasTemas = new Set();
try {
  otrasTemas = new Set(JSON.parse(localStorage.getItem(TEMAS_OTRAS) || '[]'));
} catch { /* sin almacén se abre con todas, que es lo de fábrica */ }

// Los chips se crean una vez y luego solo cambian su cifra y su estado. Rehacerlos en
// cada carga movería el foco de quien está navegando con el teclado.
function pintarChipsTemas() {
  const cont = $('otras-temas');
  const todos = [...TEMAS.categorias, ...(TEMAS.resto ? [TEMAS.resto] : [])];
  cont.textContent = '';
  for (const c of todos) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip-tema' + (c.clave === (TEMAS.resto || {}).clave ? ' resto' : '');
    b.dataset.tema = c.clave;
    b.setAttribute('aria-pressed', otrasTemas.has(c.clave) ? 'true' : 'false');
    const t = document.createElement('span');
    t.textContent = c.nombre;
    const n = document.createElement('span');
    n.className = 'n';
    b.append(t, n);
    b.addEventListener('click', () => {
      if (otrasTemas.has(c.clave)) otrasTemas.delete(c.clave);
      else otrasTemas.add(c.clave);
      b.setAttribute('aria-pressed', otrasTemas.has(c.clave) ? 'true' : 'false');
      try {
        localStorage.setItem(TEMAS_OTRAS, JSON.stringify([...otrasTemas]));
      } catch { /* sin almacén, la elección dura lo que la ventana */ }
      cargarOtras();
    });
    cont.appendChild(b);
  }
  // Quitar lo elegido que ya no existe: una temática renombrada en una versión nueva
  // dejaría un filtro invisible que nadie puede desmarcar.
  for (const clave of [...otrasTemas]) {
    if (!todos.some((c) => c.clave === clave)) otrasTemas.delete(clave);
  }
}

function cifrasChips(porCategoria) {
  for (const b of $('otras-temas').querySelectorAll('.chip-tema')) {
    const n = porCategoria ? (porCategoria[b.dataset.tema] || 0) : null;
    b.querySelector('.n').textContent = n === null ? '' : n.toLocaleString('es-ES');
  }
}

function queryOtras(extra = {}) {
  const p = new URLSearchParams({
    q: $('otras-q').value.trim(),
    categorias: [...otrasTemas].join(','),
    ccaa: $('otras-ccaa').value,
    tipo: $('otras-tipo').value,
    importe_min: $('otras-importe').value,
    orden: $('otras-orden').value,
    vivas: $('otras-vivas').checked ? '1' : '0',
    estado: $('otras-descartadas').checked ? 'descartado' : '',
    ...extra,
  });
  for (const [k, v] of [...p.entries()]) if (!v) p.delete(k);
  return p.toString();
}

async function cargarOtras(reset = true) {
  const carga = reset
    ? empezarCarga('otras-lista', $('otras-vivas').checked
        ? 'Cargando…'
        : 'Cargando… con las cerradas son cientos de miles y puede tardar unos segundos')
    : null;
  if (reset) otrasOffset = 0;

  let d;
  try {
    const r = await fetch('/api/otras?' + queryOtras({ limite: POR_PAGINA, offset: otrasOffset }));
    d = await r.json();
  } catch {
    if (!carga || carga.terminar()) $('otras-contador').textContent = 'No se pudo cargar la lista.';
    return;
  }
  if (carga && !carga.terminar()) return;

  if (d.error) {
    $('otras-contador').textContent = d.error;
    $('otras-mas').hidden = true;
    return;
  }

  // Sin cifra cuando el servidor no las ha calculado —con las cerradas y sin búsqueda
  // serían ocho segundos solo para esto—, en vez de enseñar ceros que no lo son.
  if (reset) cifrasChips(d.por_categoria);

  const aviso = $('otras-aviso');
  aviso.hidden = !d.clasificacion_pendiente;
  aviso.textContent = d.clasificacion_pendiente
    ? 'Las temáticas se están calculando por primera vez: se hace en la próxima ' +
      'búsqueda y tarda alrededor de un minuto. Hasta entonces, filtrar por temática ' +
      'puede no encontrar nada.'
    : '';

  const frag = document.createDocumentFragment();
  for (const it of d.items) frag.appendChild(tarjeta(it));
  $('otras-lista').appendChild(frag);

  const total = d.total.toLocaleString('es-ES');
  const partes = [];
  if (otrasTemas.size) partes.push([...otrasTemas].map(nombreTema).join(' + '));
  if ($('otras-vivas').checked) partes.push('solo abiertas');
  if ($('otras-descartadas').checked) partes.push('descartadas');
  $('otras-contador').textContent =
    `${total} ${d.total === 1 ? 'licitación' : 'licitaciones'} fuera de tus perfiles` +
    (partes.length ? ` · ${partes.join(' · ')}` : '');

  $('otras-vacio').hidden = d.total !== 0;
  if (d.total === 0) {
    $('otras-vacio').textContent = $('otras-vivas').checked
      ? 'Nada abierto con estos filtros. Prueba a quitar «Solo abiertas».'
      : 'Nada con estos filtros.';
  }
  otrasOffset += d.items.length;
  $('otras-mas').hidden = otrasOffset >= d.total;
}

// --- Buscar ahora ----------------------------------------------------------

// El texto del botón va en su propio <span>: el botón lleva dentro un <svg>, y
// asignarle `textContent` al botón entero se llevaba el icono por delante en cuanto
// empezaba la primera búsqueda.
function etiquetaBoton(texto) {
  $('buscar-ahora-txt').textContent = texto;
}

let vigilando = null;
let seVioEnMarcha = false;
let ticsVigilando = 0;

// 8 × 1,5 s: las cifras de la cabecera se refrescan cada 12 segundos mientras carga.
const TICS_POR_REFRESCO = 8;

function fmtBytes(n) {
  const mb = (n || 0) / (1024 * 1024);
  return mb >= 1024
    ? (mb / 1024).toFixed(1).replace('.', ',') + ' GB'
    : Math.round(mb) + ' MB';
}

// La misma cadena que `_ritmo()` en progreso.py, para que la terminal y la pantalla no
// digan cifras distintas. `fmtBytes` no sirve aquí: redondea a MB enteros y estas
// descargas van por debajo de 2 MB/s, así que saldrían todas como «1 MB».
function fmtVelocidad(bytesPorS) {
  return ((bytesPorS || 0) / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB/s';
}

// Mismo formato que la línea de la terminal: 45s, 12m, 1h 39m.
// Qué está pasando, en una frase. La compone `progreso._frase()` en Python y se usa
// tal cual en los tres sitios que lo cuentan —la terminal, la pantalla de arranque y el
// detalle del botón— para que no puedan discrepar. Lo único que se añade aquí es la
// etapa, que solo existe en la carga inicial.
function fraseProgreso(det) {
  if (!det) return 'Preguntando a las fuentes…';
  const etapa = det.etapas ? `Etapa ${det.etapa} de ${det.etapas}. ` : '';
  return etapa + (det.frase || det.resumen || 'Preparando la búsqueda…');
}

// Porcentaje solo cuando la fuente ha dicho cuánto pesa lo que manda. Si no, barra
// indeterminada: es más honesto que un porcentaje inventado, y al lado está la frase,
// que sí avanza.
function barraProgreso(barra, det) {
  if (det && (det.fase || '').startsWith('descargando') && det.bytes_total > 0) {
    barra.max = det.bytes_total;
    barra.value = det.bytes;
  } else {
    barra.removeAttribute('value');
  }
}

function fmtDuracion(segundos) {
  const s = Math.round(segundos || 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

// Aviso de que hay una búsqueda entrando por detrás. Dos formas:
//   - la carga inicial (`detalle.etapas` > 0), con sus etapas y lo que cuesta cada una;
//   - una búsqueda normal, en corto. Antes esta no salía —«ya se cuenta en la cabecera»—,
//     pero desde que la pantalla de arranque deja entrar sin esperar, alguien tiene que
//     decir que sigue buscando y que el resumen llegará al terminar. Mientras la pantalla
//     de arranque está delante no se pinta: lo cuenta ella.
function pintarCarga(det, explicacion) {
  const caja = $('carga');
  if (!det || enArranque) {
    caja.hidden = true;
    return;
  }
  caja.hidden = false;
  $('carga-etapa').closest('label').hidden = !det.etapas;
  if (!det.etapas) {
    $('carga-titulo').textContent = 'Sigue buscando licitaciones nuevas';
    $('carga-detalle').textContent = explicacion ||
      'Puedes trabajar mientras: al terminar te avisará aquí con el resumen de lo nuevo.';
    $('carga-latido').textContent =
      (det.frase || det.resumen || '') + (det.segundos ? ` Lleva ${fmtDuracion(det.segundos)}.` : '');
    pintarBarraTarea(det);
    return;
  }

  $('carga-titulo').textContent =
    `Se está trayendo el histórico · etapa ${det.etapa} de ${det.etapas}` +
    (det.etiqueta ? ` · ${det.etiqueta}` : '');
  // Qué cubre esta etapa y lo que va a tardar. Decir de antemano que son dos horas es
  // lo que evita que una espera normal se lea como un cuelgue.
  $('carga-detalle').textContent = [
    det.detalle_etapa ? det.detalle_etapa.charAt(0).toUpperCase() + det.detalle_etapa.slice(1) + '.' : '',
    det.coste ? `Esta etapa lleva ${det.coste}.` : '',
    'Puedes trabajar mientras: las licitaciones van apareciendo solas.',
  ].filter(Boolean).join(' ');
  // La frase la compone el indicador en Python, para que la terminal y esto cuenten lo
  // mismo. Aquí solo se le añade el reloj, que es lo que demuestra que avanza.
  $('carga-latido').textContent =
    (det.frase || det.resumen || '') + (det.segundos ? ` Lleva ${fmtDuracion(det.segundos)}.` : '');

  $('carga-etapa-txt').textContent = `etapa ${det.etapa} de ${det.etapas}`;
  const etapa = $('carga-etapa');
  etapa.max = det.etapas;
  etapa.value = Math.max(0, det.etapa - 1);
  pintarBarraTarea(det);
}

// La barra de lo que se está haciendo ahora mismo: bytes, ficheros del ZIP o nada.
function pintarBarraTarea(det) {
  const barra = $('carga-tarea');
  const txt = $('carga-tarea-txt');
  const quien = det.titulo || det.fuente || 'preparando';
  const descargando = (det.fase || '').startsWith('descargando');
  if (descargando && det.bytes_total > 0) {
    barra.max = det.bytes_total;
    barra.value = det.bytes;
    txt.textContent = `descargando ${fmtBytes(det.bytes)} de ${fmtBytes(det.bytes_total)}`;
  } else if (descargando) {
    // La descarga manda sobre el contador de ficheros aunque este traiga números: son
    // los del ZIP del año anterior, y dejarlos pintados es lo que hacía parecer que la
    // aplicación se había quedado clavada al 100%.
    barra.removeAttribute('value');
    txt.textContent =
      `descargando ${fmtBytes(det.bytes)}` +
      (det.bytes_por_s ? ` · ${fmtVelocidad(det.bytes_por_s)}` : '') +
      ' — el servidor no dice cuánto pesa, así que no hay porcentaje';
  } else if (det.subtareas > 0) {
    barra.max = det.subtareas;
    barra.value = det.subtarea;
    txt.textContent = `fichero ${det.subtarea} de ${det.subtareas} del ZIP`;
  } else {
    // Sin total conocido la barra se deja indeterminada: es más honesto que
    // inventarse un porcentaje que no significa nada.
    barra.removeAttribute('value');
    txt.textContent = quien;
  }
}

// Devuelve true si al salir hay una búsqueda corriendo, que es lo que necesita saber
// la pantalla de arranque para decidir si espera o entra directamente.
async function lanzarBusqueda(opciones = {}) {
  const btn = $('buscar-ahora');
  let r, d;
  try {
    r = await fetch('/api/buscar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opciones),
    });
    d = await r.json();
  } catch {
    $('ultima-busqueda').textContent = 'no se ha podido hablar con el radar';
    return false;
  }
  if (!r.ok) {
    // 409 = ya hay una en marcha; no es un error, solo hay que esperarla. Pasa a
    // diario durante la carga inicial, que dura horas y tiene el cerrojo tomado.
    $('ultima-busqueda').textContent = r.status === 409
      ? 'ya se está descargando; espera a que termine'
      : (d.error || 'No se pudo lanzar la búsqueda.');
    if (r.status === 409) {
      vigilarBusqueda();
      return true;
    }
    return false;
  }
  btn.disabled = true;
  etiquetaBoton('Buscando…');
  // Antes de que el vigilante dé su primera vuelta pasa segundo y medio, y un botón
  // que se apaga sin decir nada durante segundo y medio parece un botón roto.
  pintarProgresoBusqueda(null);
  vigilarBusqueda();
  return true;
}

// El detalle debajo del botón de «Términos de búsqueda». Se pinta siempre que hay algo
// en marcha, la haya lanzado el botón o no: si entras ahí mientras corre la carga
// inicial, tiene que decirte por qué el botón está desactivado.
function pintarProgresoBusqueda(det) {
  $('busqueda-progreso').hidden = false;
  $('busqueda-frase').textContent =
    fraseProgreso(det) + (det && det.segundos ? ` Lleva ${fmtDuracion(det.segundos)}.` : '');
  barraProgreso($('busqueda-barra'), det);
}

function ocultarProgresoBusqueda() {
  $('busqueda-progreso').hidden = true;
}

// Devuelve una promesa que se cumple cuando la búsqueda termina, con la bandeja ya
// recargada. La pantalla de arranque la espera; el botón no, que para eso tiene su
// propio detalle debajo. Si ya había un vigilante, se devuelve su misma promesa: dos
// intervalos sobre el mismo estado se pisarían el botón.
let vigilancia = null;

function vigilarBusqueda() {
  if (vigilancia) return vigilancia;
  let cumplir;
  vigilancia = new Promise((r) => { cumplir = r; });
  const btn = $('buscar-ahora');
  seVioEnMarcha = false;
  ticsVigilando = 0;
  // El aviso de la búsqueda anterior ya no vale: va a haber otro.
  $('busqueda-terminada').hidden = true;

  vigilando = setInterval(async () => {
    let d;
    try {
      d = await (await fetch('/api/busqueda-estado')).json();
    } catch {
      return;  // el servidor puede tardar un instante; se reintenta al siguiente tic
    }
    if (d.en_marcha) {
      seVioEnMarcha = true;
      const det = d.detalle;
      // La última línea del registro cuenta como señal de vida: al principio de una
      // búsqueda la instantánea todavía no existe, pero el registro ya escribe.
      senalDeVida('busqueda', huellaDetalle(det) + (d.progreso || []).slice(-1));
      btn.disabled = true;
      etiquetaBoton(det && det.etapas
        ? `Carga inicial (${det.etapa}/${det.etapas})`
        : 'Buscando…');
      pintarCarga(det, d.explicacion);
      pintarProgresoBusqueda(det);
      // De la carga inicial solo se espera aquí la etapa 1, la de unos minutos: sin ella
      // la bandeja de una instalación nueva está vacía. De la 2 en adelante son horas, y
      // esas no se esperan con la aplicación tapada: se entra y las cuenta el aviso de
      // la cabecera, que dice «puedes trabajar mientras». Si ya está a la vista el
      // resumen con «Continuar», no se toca nada: es quien ha lanzado esas etapas.
      if (enArranque && $('arranque-resumen').hidden) {
        const deHoras = Boolean(det && det.etapas && det.etapa > 1);
        if (cumplirEtapa1 && det && det.etapas) cumplirEtapa1(det);
        if (!deHoras) {
          pintarArranque(det);
          pintarLentitud(det, d.explicacion);
        } else if (!cumplirEtapa1) {
          cerrarArranque();
        }
      }
      // Durante la carga inicial toda la narración vive en el bloque de abajo. Aquí
      // solo el estado corto: antes se pintaba la última línea del log recortada a 90
      // caracteres, que decía lo mismo en jerga y cortada a mitad de palabra.
      if (det && det.etapas) {
        $('ultima-busqueda').textContent =
          `carga inicial en marcha · etapa ${det.etapa} de ${det.etapas}` +
          (det.segundos ? ` · ${fmtDuracion(det.segundos)}` : '');
      } else {
        const ultima = (d.progreso || []).filter((l) => !l.startsWith('Evaluando')).pop();
        $('ultima-busqueda').textContent = ultima ? ultima.slice(0, 90) : 'descargando…';
      }

      // Solo los contadores, y no la lista: cada etapa de la carga inicial reevalúa
      // los perfiles, así que las cifras van subiendo y es eso lo que hay que poder
      // ver sin recargar. Recargar la lista movería el sitio por donde se va leyendo.
      if (++ticsVigilando % TICS_POR_REFRESCO === 0) cargarResumen();
      return;
    }
    clearInterval(vigilando);
    vigilando = null;
    pintarCarga(null);
    ocultarProgresoBusqueda();
    btn.disabled = false;
    etiquetaBoton('Buscar ahora');
    if (seVioEnMarcha) {
      await cargarResumen();
      await cargarLista();
      // Si la pantalla de arranque ya no está —se entró sin esperar, o es la búsqueda
      // de «Buscar ahora»—, nadie más va a contar lo que ha traído.
      if (!enArranque) avisarBusquedaTerminada();
      if (vistaActual === 'resumen') cargarResumenVista();
    }
    // Lo último, y después de recargar: quien espera la promesa destapa la bandeja ya
    // con lo que se acaba de traer, no con lo de ayer rellenándose a la vista.
    vigilancia = null;
    cumplir();
    // Se entró sin esperar a la etapa 1 de la carga inicial: nadie más va a lanzar las
    // que faltan. Con la pantalla de arranque delante lo hace ella, después del resumen.
    if (!enArranque) seguirCargaInicial();
  }, 1500);
  return vigilancia;
}

// --- Pantalla de arranque --------------------------------------------------
//
// Al abrir la aplicación se hacen dos cosas, en este orden, y ninguna se puede saltar:
//
//   1. Instalar la versión nueva del programa, si la hay. Primero, porque la búsqueda
//      tiene que correr ya con el código nuevo, y porque instalar reinicia la
//      aplicación: buscar antes sería buscar para nada.
//   2. Traer lo publicado desde la última vez. Antes esto no lo hacía nadie y había que
//      acordarse de pulsar «Buscar ahora».
//
// Lo que se ve mientras tanto es el progreso de verdad —la misma frase que escribe la
// terminal—, no un «cargando» fijo.
//
// Hay dos salidas manuales, y las dos aparecen solo cuando hacen falta: cuando la
// búsqueda pasa de dos minutos —va lenta, se explica por qué y se recomienda esperar,
// ver `pintarLentitud()`— y cuando algo deja de dar señales de vida, ver
// `vigilarCuelgue()`. Hay además dos casos en los que no se espera, porque no son
// saltarse nada:
//   - la carga inicial de horas (de la etapa 2 en adelante) no se espera aquí: se entra
//     y la narra el aviso de la cabecera, que dice «puedes trabajar mientras». La etapa
//     1, la de unos minutos, sí: es la que llena una instalación nueva;
//   - si ya se buscó hace menos de diez minutos no se vuelve a buscar: la búsqueda ya
//     está hecha, y abrir y cerrar la ventana no debería costar un minuto cada vez.
//     La versión, en cambio, se comprueba siempre: es una sola pregunta a GitHub.

let enArranque = true;

// Cuánto vale una búsqueda antes de repetirla, en minutos. Lo que se publique en diez
// minutos no justifica esperar otro minuto delante de una pantalla de espera.
const MINUTOS_FRESCO = 10;

// Cuánto sin ninguna señal de vida antes de ofrecer la salida. Tres minutos y no
// menos: PLACSP se queda hasta dos minutos callado en cada intento de conexión antes
// de reintentar, y eso es lentitud, no un cuelgue. Por encima de eso, lo que no
// contesta no va a contestar.
const SIN_SENALES_MS = 3 * 60 * 1000;

let ultimaSenal = Date.now();
let ultimaHuella = '';

function cerrarArranque() {
  if (!enArranque) return;
  enArranque = false;
  $('arranque').hidden = true;
  // Se entra: lo que hay ahora pasa a ser «la última vez» para la próxima. Sin esperar
  // la respuesta, y sin quejarse si no llega: lo peor que pasa es que la próxima vez
  // «Desde la última vez» cuente un poco de más.
  fetch('/api/resumen/apertura', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  // Si la búsqueda sigue por detrás, que lo diga la cabecera desde ya y no al siguiente
  // tic del vigilante.
  if (vigilando) estadoBusqueda().then((d) => d && d.en_marcha && pintarCarga(d.detalle, d.explicacion));
}

// A partir de cuánto se dice que la búsqueda va lenta y se ofrece entrar. Dos minutos:
// una búsqueda normal con las fuentes contestando bien tarda alrededor de uno.
const LENTA_TRAS_S = 120;

function pintarLentitud(det, explicacion) {
  const lenta = Boolean(det && det.segundos >= LENTA_TRAS_S) && $('arranque-colgado').hidden;
  $('arranque-lenta').hidden = !lenta;
  if (lenta) {
    $('arranque-lenta-porque').textContent = explicacion ||
      'Las plataformas oficiales a veces responden muy despacio. Lo que ya ha llegado ' +
      'queda guardado.';
  }
}

// Algo ha cambiado en lo que se está esperando: bytes, fase, fichas, versión. Se
// compara la huella y no el hecho de haber contestado, porque un proceso atascado sigue
// dejando su última instantánea en disco y el servidor la sirve igual de bien.
function senalDeVida(quien, huella) {
  const nueva = `${quien}|${huella}`;
  if (nueva === ultimaHuella) return;
  ultimaHuella = nueva;
  ultimaSenal = Date.now();
  $('arranque-colgado').hidden = true;
}

// Sin `segundos`, que cambia en cada instantánea aunque no se mueva nada más: con él,
// una descarga clavada parecería viva para siempre.
function huellaDetalle(det) {
  if (!det) return '';
  return [det.etapa, det.fuente, det.tarea, det.fase, det.bytes, det.paginas,
          det.fichas, det.subtarea].join('·');
}

// Por reloj y no por los tics de ningún vigilante: si lo que falla es el propio
// servidor, las peticiones fallan sin contar nada y esto tiene que seguir mirando.
function vigilarCuelgue() {
  const reloj = setInterval(() => {
    if (!enArranque) {
      clearInterval(reloj);
      return;
    }
    const callado = Date.now() - ultimaSenal;
    if (callado < SIN_SENALES_MS) return;
    $('arranque-colgado-txt').textContent =
      `Lleva ${fmtDuracion(callado / 1000)} sin dar señales de vida: parece que se ha ` +
      'quedado colgado. Puedes entrar con lo que ya hay; se volverá a intentar la ' +
      'próxima vez que abras la aplicación.';
    $('arranque-colgado').hidden = false;
    // Una sola salida a la vista: dos botones de entrar con textos distintos confunden.
    $('arranque-lenta').hidden = true;
  }, 5000);
}

function pasoArranque(texto) {
  $('arranque-paso').textContent = texto;
}

function pintarArranque(det) {
  // En la primera vez, qué trae la etapa y lo que cuesta, con el texto de
  // `pipeline.ETAPAS_PRIMERA_CARGA`: es lo que convierte unos minutos de espera en algo
  // que se entiende.
  if (det && det.etapas && det.etiqueta && !$('arranque-explica').hidden) {
    $('arranque-explica-etapa').textContent =
      `Ahora: ${det.etiqueta.charAt(0).toLowerCase()}${det.etiqueta.slice(1)}, ` +
      `${det.coste || 'unos minutos'}.`;
  }
  $('arranque-frase').textContent = fraseProgreso(det);
  barraProgreso($('arranque-barra'), det);
  $('arranque-tiempo').textContent =
    det && det.segundos ? `Lleva ${fmtDuracion(det.segundos)}.` : '';
}

function buscadoHaceMenosDe(iso, minutos) {
  if (!iso) return false;
  const cuando = new Date(iso);
  if (isNaN(cuando)) return false;
  return (Date.now() - cuando.getTime()) < minutos * 60 * 1000;
}

const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

async function pedirJSON(url, opciones) {
  return (await fetch(url, opciones)).json();
}

async function estadoBusqueda() {
  try {
    return await pedirJSON('/api/busqueda-estado');
  } catch {
    return null;
  }
}

// --- Paso 1: la versión ------------------------------------------------------

// Las fases que no son descarga no tienen frase propia en `progreso._frase()`, que
// está pensado para las fuentes de datos. Para estas cuatro se dice aquí.
const FRASES_ACTUALIZACION = {
  comprobando: 'Preguntando a GitHub cuál es la última versión publicada.',
  verificando: 'Comprobando que lo descargado es lo que se ha publicado.',
  descomprimiendo: 'Descomprimiendo la aplicación nueva.',
  sustituyendo: 'Poniendo el programa nuevo en su sitio. Lo anterior se guarda al lado.',
};

function pintarInstalacion(det) {
  const propia = det && FRASES_ACTUALIZACION[det.fase];
  if (propia) {
    $('arranque-frase').textContent = propia;
    barraProgreso($('arranque-barra'), null);
  } else {
    pintarArranque(det);
    if (!det) $('arranque-frase').textContent = 'Preparando la instalación…';
  }
}

// El motivo va en la cabecera y no en un diálogo: no hay nada que decidir, solo que
// saber por qué se sigue en la versión de antes.
function avisarVersionNoInstalada(version, mensaje) {
  const caja = $('aviso-version');
  caja.hidden = false;
  caja.innerHTML = '<p><strong></strong> <span class="pista"></span></p>';
  caja.querySelector('strong').textContent =
    `No se ha podido instalar la versión ${version}.`;
  caja.querySelector('.pista').textContent =
    (mensaje || 'No ha dicho por qué.') +
    ' Se volverá a intentar la próxima vez que abras la aplicación.';
}

// Devuelve true si la aplicación se está reiniciando con la versión nueva: entonces no
// hay que seguir con nada más, esta página está a punto de desaparecer.
async function instalarVersionNueva() {
  pasoArranque('Paso 1 de 2 · versión del programa');
  $('arranque-titulo').textContent = 'Comprobando si hay una versión nueva';
  pintarInstalacion({ fase: 'comprobando' });

  let info;
  try {
    info = await pedirJSON('/api/actualizacion');
  } catch {
    return false;  // sin servidor no hay nada que instalar; lo dirá la bandeja
  }
  // Se guarda para el resumen del final, que dice en qué versión estás y si es la
  // última: es la misma pregunta a GitHub, no hace falta repetirla.
  infoVersion = info;
  // Sin red o sin releases no se puede instalar nada. No es saltarse el paso: es que
  // no ha habido respuesta, y quedarse aquí esperándola no la va a traer.
  if (!info.hay_nueva) return false;

  const version = info.version_nueva;
  versionAnterior = info.version_actual;
  const tienes = `Tienes la ${info.version_actual}.`;
  $('arranque-titulo').textContent = `Instalando la versión ${version}`;
  $('arranque-tiempo').textContent = tienes;
  let lanzada;
  try {
    lanzada = await pedirJSON('/api/actualizacion', { method: 'POST' });
  } catch {
    lanzada = { ok: false, mensaje: 'No se ha podido hablar con el radar.' };
  }
  if (!lanzada.ok) {
    avisarVersionNoInstalada(version, lanzada.mensaje);
    return false;
  }

  let resultado = null;
  while (enArranque) {
    await dormir(1000);
    let e;
    try {
      e = await pedirJSON('/api/actualizacion/estado');
    } catch {
      continue;  // un tic sin contestar no es un cuelgue; muchos seguidos, sí
    }
    senalDeVida('version', `${e.en_marcha}|${huellaDetalle(e.detalle)}`);
    if (e.en_marcha) {
      pintarInstalacion(e.detalle);
      if (!$('arranque-tiempo').textContent) $('arranque-tiempo').textContent = tienes;
      continue;
    }
    resultado = e.resultado;
    break;
  }
  if (!enArranque) return false;

  // `sin_cambios` es que otra ventana la instaló mientras tanto: no hay nada que
  // avisar, y el reinicio ya lo hará quien la instaló.
  if (!resultado || !resultado.ok || resultado.sin_cambios) {
    if (!resultado || !resultado.sin_cambios) {
      avisarVersionNoInstalada(version, resultado && resultado.mensaje);
    }
    return false;
  }

  $('arranque-titulo').textContent = `Reiniciando con la versión ${version}`;
  $('arranque-frase').textContent =
    'Instalada. La aplicación se vuelve a abrir sola; tu base de datos, tu triaje y ' +
    'tus términos de búsqueda no se han tocado.';
  barraProgreso($('arranque-barra'), null);
  $('arranque-tiempo').textContent = '';
  return reiniciarConVersion(version, resultado.app_nueva);
}

// El puente con la ventana de macOS, si la hay. En el navegador no existe.
function ventanaNativa() {
  return window.webkit && window.webkit.messageHandlers &&
    window.webkit.messageHandlers.radar;
}

async function reiniciarConVersion(version, appNueva) {
  const nativa = ventanaNativa();
  if (appNueva) {
    // La app empaquetada: el cambio de un bundle por otro solo lo puede hacer la
    // ventana, cerrándose. Si no hay ventana —no debería pasar: esa copia no tiene
    // start.command— se dice y se sigue.
    if (nativa) {
      nativa.postMessage({ accion: 'instalar-app', ruta: appNueva, version });
      return true;
    }
    avisarVersionNoInstalada(version,
      `Está descargada en ${appNueva}, pero solo la aplicación de macOS puede ponerla ` +
      'en su sitio.');
    return false;
  }
  if (nativa) {
    // Copia de trabajo dentro de la ventana: ella rehace el .app con el código nuevo y
    // se vuelve a abrir. Si no puede rehacerse, llama a `reiniciarServidorYRecargar()`.
    nativa.postMessage({ accion: 'reiniciar', version });
    return true;
  }
  await reiniciarServidorYRecargar();
  return true;
}

// La versión que ejecutaba el servidor antes de instalar. Es con lo que se sabe que el
// reinicio ha terminado: cuando el servidor deja de decir esta.
let versionAnterior = null;

// Reinicia el proceso de Python (mismo PID, código nuevo) y recarga esta página cuando
// el servidor ya es otro. Es el camino del navegador, y el de reserva de la ventana de
// macOS cuando no consigue rehacerse.
//
// Se espera a que deje de ser la versión vieja, no a que sea la nueva: la etiqueta
// puede llevar «v» delante o no, y una versión futura podría no tener siquiera este
// endpoint —un 404 también dice que ya no es el servidor de antes—.
async function reiniciarServidorYRecargar() {
  try {
    await fetch('/api/reiniciar', { method: 'POST' });
  } catch { /* si ya se está reiniciando, no contesta: es lo esperado */ }
  for (;;) {
    await dormir(1000);
    let r;
    try {
      r = await fetch('/api/actualizacion/estado');
    } catch {
      continue;  // todavía arrancando
    }
    if (r.status === 404) break;
    let e;
    try {
      e = await r.json();
    } catch {
      continue;
    }
    if (e.version !== versionAnterior) break;
  }
  location.reload();
}
window.reiniciarServidorYRecargar = reiniciarServidorYRecargar;

// --- Novedades tras actualizar ---------------------------------------------
//
// Cuando la aplicación se reabre con una versión nueva, la pantalla de arranque lo dice
// y enseña qué ha cambiado desde la que se tenía, mientras el paso 2 sigue buscando
// debajo. Al terminar no se cierra sola: espera a «Continuar», porque hay algo que leer
// y quitarlo de delante en mitad de una frase es peor que no haberlo puesto.

// Texto con `**negrita**` y `` `código` `` —lo que conservan las notas de la release—
// pintado con `textContent`, trozo a trozo. Las notas vienen de GitHub y no se
// interpretan como HTML.
function textoConFormato(el, texto) {
  for (const trozo of String(texto).split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
    if (!trozo) continue;
    let nodo;
    if (trozo.startsWith('**') && trozo.endsWith('**') && trozo.length > 4) {
      nodo = document.createElement('strong');
      nodo.textContent = trozo.slice(2, -2);
    } else if (trozo.startsWith('`') && trozo.endsWith('`') && trozo.length > 2) {
      nodo = document.createElement('code');
      nodo.textContent = trozo.slice(1, -1);
    } else {
      nodo = document.createTextNode(trozo);
    }
    el.appendChild(nodo);
  }
  return el;
}

function enlaceExterno(url, texto) {
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.textContent = texto;
  return a;
}

function subtituloNovedades(n, buscando) {
  if (n.bienvenida) {
    return 'Esto es lo que trae la versión con la que empiezas' +
      (buscando ? '; mientras lo lees, el radar prepara tu primera carga debajo.' : '.');
  }
  return (n.desde ? `Tenías la ${n.desde}. Esto es lo nuevo desde entonces` :
                    'Esto es lo nuevo de esta versión') +
    (buscando ? '; mientras lo lees, el radar sigue buscando licitaciones debajo.' : '.');
}

// Tras una actualización, o la primera vez que se abre (`bienvenida`): en las dos se
// cuenta qué trae la versión, y en las dos «Continuar» la da por vista.
function pintarNovedades(n) {
  $('arranque-caja').classList.add('con-novedades');
  $('arranque-novedades').hidden = false;
  $('novedades-titulo').textContent = n.bienvenida
    ? `Te damos la bienvenida al Radar · versión ${n.hasta}`
    : `Actualizado a la versión ${n.hasta}`;
  $('novedades-sub').textContent = subtituloNovedades(n, true);

  const lista = $('novedades-lista');
  lista.textContent = '';
  for (const v of n.versiones || []) {
    const sec = document.createElement('section');
    sec.className = 'novedades-version';
    const h = document.createElement('h3');
    const num = document.createElement('span');
    num.className = 'novedades-num';
    num.textContent = `v${v.version}`;
    h.appendChild(num);
    if (v.titulo) h.appendChild(document.createTextNode(' ' + v.titulo));
    sec.appendChild(h);
    if (v.fecha) {
      const f = document.createElement('p');
      f.className = 'novedades-fecha';
      f.textContent = 'publicada el ' + fmtFecha(v.fecha);
      sec.appendChild(f);
    }
    let ul = null;
    for (const b of v.bloques || []) {
      if (b.tipo === 'punto') {
        if (!ul) {
          ul = document.createElement('ul');
          sec.appendChild(ul);
        }
        ul.appendChild(textoConFormato(document.createElement('li'), b.texto));
        continue;
      }
      ul = null;
      const el = document.createElement(b.tipo === 'titulo' ? 'h4' : 'p');
      sec.appendChild(textoConFormato(el, b.texto));
    }
    lista.appendChild(sec);
  }

  // Sin red no hay notas, pero la actualización sí ha ocurrido: se dice y se enlaza.
  const pie = document.createElement('p');
  pie.className = 'pista novedades-pie';
  if (!(n.versiones || []).length) {
    pie.textContent = (n.error ? 'No se han podido traer las novedades ahora mismo. ' : '') +
      'Puedes leerlas en ';
    pie.appendChild(enlaceExterno(n.url, 'la página de versiones'));
    pie.appendChild(document.createTextNode('.'));
  } else if (n.mas_antiguas) {
    pie.textContent = `Y ${n.mas_antiguas} ${n.mas_antiguas === 1 ? 'versión' : 'versiones'} ` +
      'más antiguas, en ';
    pie.appendChild(enlaceExterno(n.url, 'la página de versiones'));
    pie.appendChild(document.createTextNode('.'));
  }
  if (pie.textContent) lista.appendChild(pie);
}

// Las dos cosas han terminado: se dice qué ha traído la búsqueda y en qué versión
// estás, y se espera a «Continuar». Antes esto solo pasaba tras una actualización y el
// resto de las veces la pantalla se iba sola: se entraba sin saber si había algo nuevo.
//
// `conLicitaciones` es false cuando no hay búsqueda que resumir (la carga inicial, o
// sin servidor): entonces solo sale si hay novedades de versión que leer.
async function mostrarResumenArranque(n, conLicitaciones) {
  pasoArranque('Paso 1 y paso 2 terminados');
  if (n && n.actualizada) $('novedades-sub').textContent = subtituloNovedades(n, false);
  $('arranque-titulo').textContent = primeraVez ? 'Tu radar ya tiene su primera carga' : 'Todo listo';
  // Fuera lo que era del progreso: dejarlo vacío seguiría ocupando su hueco.
  for (const id of ['arranque-frase', 'arranque-barra', 'arranque-tiempo', 'arranque-explica']) {
    $(id).hidden = true;
  }
  $('arranque-colgado').hidden = true;
  $('arranque-lenta').hidden = true;

  const cuerpo = $('arranque-resumen-cuerpo');
  cuerpo.textContent = '';
  if (conLicitaciones) {
    let r = null;
    try {
      r = await pedirJSON('/api/resumen-novedades?periodo=busqueda');
    } catch { /* sin resumen se entra igual: la bandeja ya está al día */ }
    if (r && !r.error) cuerpo.appendChild(bloqueResumen(r, { compacto: true }));
  }
  if (primeraVez) {
    // Lo lanza `seguirCargaInicial()` en cuanto esta pantalla está a la vista: se dice
    // ya, para que al entrar el aviso de la cabecera no pille por sorpresa.
    const p = document.createElement('p');
    p.className = 'pista';
    p.textContent = 'Ahora sigue por detrás con el resto del histórico: la Plataforma del ' +
      'Estado, unos 5 GB, y lo publicado desde entonces. Según tu conexión puede ir de ' +
      'unos minutos a un par de horas. Puedes trabajar mientras: las licitaciones van ' +
      'apareciendo solas y arriba verás cómo va.';
    cuerpo.appendChild(p);
  }
  if (!enArranque) return;  // se ha entrado mientras se pedía el resumen
  $('arranque-version').textContent = textoVersion(n);
  $('arranque-resumen').hidden = false;
  $('arranque-continuar').focus();
}

// Solo es la versión la que se marca como vista al pulsarlo; quien cierra la aplicación
// antes vuelve a ver las novedades la próxima vez.
async function continuarArranque() {
  $('arranque-continuar').disabled = true;
  // Sin esperar la respuesta. Apuntarlo es una escritura, y la primera vez se pulsa con
  // la etapa 2 de la carga inicial ya escribiendo por detrás: medido, «Continuar» se
  // quedaba varios segundos sin hacer nada esperando su turno. Si no llega a apuntarse,
  // las novedades se vuelven a enseñar la próxima vez: no pasa nada.
  if (novedadesArranque && novedadesArranque.actualizada) {
    fetch('/api/novedades/vistas', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
  }
  cerrarArranque();
}

// --- Paso 2: las licitaciones ------------------------------------------------
//
// En una instalación nueva el paso 2 es la carga inicial, la misma que hace
// `start.command`: la etapa 1 aquí delante, y la 2, la 3 y la 4 por detrás al entrar.
// Antes la aplicación hacía una búsqueda normal, que en una base vacía trae una página
// de PLACSP y los últimos 30 días de TED y Cataluña, y en cuanto escribe el cursor ya no
// mira atrás: quien la descargaba de GitHub se quedaba con unas decenas de licitaciones
// para siempre. Qué falta lo dice `etapas_pendientes`, que apunta la propia carga.

// Que esta apertura está haciendo la carga inicial: cambia los títulos y el resumen.
let primeraVez = false;
// Las etapas que esta sesión ya ha lanzado. Una que falla sigue pendiente, y sin esto se
// relanzaría en bucle; así se reintenta la próxima vez que se abra la aplicación.
const etapasLanzadas = new Set();
// Se lo pasa el vigilante a cada tic de la carga inicial, para ver cuándo pasa de la
// etapa 1 a la 2 en el mismo proceso: es lo que hace `--primera-carga` lanzado a mano
// sin `--etapas`. Solo cuenta si antes se ha visto la 1, para que la instantánea que
// dejó una carga anterior no dé la etapa por terminada antes de empezar.
let cumplirEtapa1 = null;

function esperarEtapa1() {
  let vista = false;
  const pasa = new Promise((r) => {
    cumplirEtapa1 = (det) => {
      if (det.etapa === 1) vista = true;
      else if (vista) r();
    };
  });
  return Promise.race([vigilarBusqueda(), pasa]).finally(() => { cumplirEtapa1 = null; });
}

function pintarPrimeraVez() {
  primeraVez = true;
  pasoArranque('Paso 2 de 2 · tu primera carga');
  $('arranque-titulo').textContent = 'Primera vez: preparando tu radar';
  $('arranque-explica').hidden = false;
}

// Devuelve true si hay una búsqueda que resumir al terminar: la que se acaba de hacer,
// la que ya estaba en marcha, o una de hace menos de diez minutos que se reutiliza.
async function buscarLoNuevo() {
  pasoArranque('Paso 2 de 2 · licitaciones nuevas');
  $('arranque-tiempo').textContent = '';
  let d = await estadoBusqueda();
  if (!d) return false;  // sin servidor no hay nada que esperar; que lo cuente la bandeja

  if (d.en_marcha && d.detalle && d.detalle.etapas) {
    if (d.detalle.etapa > 1) return false;  // la carga inicial de horas: no se espera
    pintarPrimeraVez();
    etapasLanzadas.add(1);
    await esperarEtapa1();
    return true;
  }

  // Ya hay una corriendo: la tarea programada de la mañana, un `start.command`, u otra
  // ventana. Se espera a esa en lugar de pedir otra, que el cerrojo rechazaría.
  if (d.en_marcha) {
    $('arranque-titulo').textContent = 'Terminando la búsqueda que ya estaba en marcha';
    await vigilarBusqueda();
    return true;
  }

  const pendientes = d.etapas_pendientes || [];
  if (pendientes.includes(1) && !etapasLanzadas.has(1)) {
    pintarPrimeraVez();
    pintarArranque(null);
    etapasLanzadas.add(1);
    if (!(await lanzarBusqueda({ primera_carga: true, etapas: [1] }))) return false;
    await esperarEtapa1();
    return true;
  }
  if (buscadoHaceMenosDe(d.ultima_busqueda, MINUTOS_FRESCO)) return true;
  // Quedaron etapas de una vez anterior (se cerró la aplicación a medias): se terminan
  // por detrás al entrar, con `seguirCargaInicial()`, en lugar de una búsqueda normal.
  // La etapa 4 ya es una búsqueda de todas las fuentes, y una normal escribiría el
  // cursor de PLACSP dejando un hueco entre el último ZIP y hoy.
  if (pendientes.length) return false;

  $('arranque-titulo').textContent = 'Buscando licitaciones nuevas';
  pintarArranque(null);
  if (await lanzarBusqueda()) {
    await vigilarBusqueda();
    return true;
  }
  return false;
}

// Lo que contestó /api/novedades al abrir: si la versión es nueva y desde cuál se venía.
let novedadesArranque = null;

async function arrancar() {
  vigilarCuelgue();

  // En paralelo y sin esperarla: si la versión es nueva, sus novedades se pintan en
  // cuanto llegan, mientras los dos pasos siguen su curso.
  const novedades = pedirJSON('/api/novedades').catch(() => null);
  novedades.then((n) => {
    novedadesArranque = n;
    if (n && n.actualizada && enArranque) pintarNovedades(n);
  });

  // Una búsqueda que ya venía corriendo se deja terminar antes de instalar: el
  // actualizador se niega a cambiar el código por debajo de una ingesta, y con razón.
  // La carga inicial no, que son horas: esa se engancha directamente y la versión
  // nueva se instalará la próxima vez.
  const d = await estadoBusqueda();
  if (!d) {
    cerrarArranque();
    return;
  }
  // La etapa 1 sí se espera, en el paso 2: es la que llena una instalación nueva.
  const cargaInicial = d.en_marcha && d.detalle && d.detalle.etapas && d.detalle.etapa > 1;
  if (cargaInicial) {
    vigilarBusqueda();
    cerrarArranque();
    return;
  }
  if (d.en_marcha && !(d.detalle && d.detalle.etapas)) {
    pasoArranque('Antes de nada');
    $('arranque-titulo').textContent = 'Terminando la búsqueda que ya estaba en marcha';
    await vigilarBusqueda();
  }

  if (enArranque && await instalarVersionNueva()) return;
  const hayBusqueda = enArranque ? await buscarLoNuevo() : false;
  const n = await novedades;
  // Se ha entrado sin esperar, o la carga inicial ya ha destapado la aplicación: el
  // resumen lo dará el aviso de la cabecera cuando la búsqueda termine.
  if (!enArranque) return;
  // No se cierra sola: se enseña qué ha traído la búsqueda y la versión, y se espera a
  // «Continuar». Sin búsqueda que resumir, solo si hay novedades de versión que leer.
  if (hayBusqueda || (n && n.actualizada)) await mostrarResumenArranque(n, hayBusqueda);
  else cerrarArranque();
  await seguirCargaInicial();
}

// Lanza por detrás las etapas de la carga inicial que falten, si no hay nada en marcha.
// Se llama al terminar el arranque —con el resumen ya a la vista, para que el vigilante
// no lo cierre— y al terminar una búsqueda que corría por detrás.
async function seguirCargaInicial() {
  const d = await estadoBusqueda();
  if (!d || d.en_marcha) return;
  const resto = (d.etapas_pendientes || []).filter((e) => !etapasLanzadas.has(e));
  if (!resto.length) return;
  resto.forEach((e) => etapasLanzadas.add(e));
  await lanzarBusqueda({ primera_carga: true, etapas: resto });
}

// --- Resumen de lo nuevo ------------------------------------------------------
//
// Lo mismo en tres sitios —la pantalla de arranque, el aviso de la cabecera cuando una
// búsqueda termina por detrás y la pestaña «Resumen»— y con la misma consulta
// (`consultas.resumen_novedades`), para que no puedan dar cifras distintas.

// Los dos primeros cuentan lo que ha ENTRADO en el radar; los tres de calendario, lo
// PUBLICADO en ese plazo. La etiqueta larga es la que lo dice.
const PERIODOS = [
  { clave: 'busqueda', etiqueta: 'Última búsqueda' },
  { clave: 'visita', etiqueta: 'Desde la última vez' },
  { clave: 'semana', etiqueta: 'Última semana' },
  { clave: 'mes', etiqueta: 'Último mes' },
  { clave: 'trimestre', etiqueta: 'Último trimestre' },
];
let periodoResumen = 'busqueda';

// Lo que contestó GitHub en el paso 1 del arranque. La pestaña lo reutiliza para su pie
// en lugar de volver a preguntar.
let infoVersion = null;

function cuantas(n) {
  return n === 1 ? '1 licitación nueva' : `${n.toLocaleString('es-ES')} licitaciones nuevas`;
}

function sinV(version) {
  return String(version || '').replace(/^v/i, '');
}

// En qué versión estás y si es la última. `n` es lo de /api/novedades al abrir (puede no
// estar); `infoVersion`, lo que dijo GitHub.
function textoVersion(n) {
  const actual = sinV((infoVersion && infoVersion.version_actual) ||
                      (n && (n.hasta || n.version)));
  if (!actual) return '';
  // La que corre es más nueva que la última de GitHub: una versión montada desde la copia
  // de trabajo antes de publicarla. Decir «es la última publicada» sería mentir.
  const publicada = infoVersion && !infoVersion.error && sinV(infoVersion.version_nueva);
  if (publicada && publicada !== actual && !infoVersion.hay_nueva) {
    return `Versión ${actual}, todavía sin publicar en GitHub (allí la última es la ${publicada}).`;
  }
  if (n && n.actualizada) return `Versión ${actual}: recién instalada, es la última publicada.`;
  if (!infoVersion) return `Versión ${actual}.`;
  if (infoVersion.error) {
    return `Versión ${actual}. No se ha podido comprobar si hay otra más nueva: ` +
      `${infoVersion.error}`;
  }
  if (infoVersion.hay_nueva) {
    return `Versión ${actual}. Hay una más nueva, la ${sinV(infoVersion.version_nueva)}, ` +
      'que no se ha podido instalar; se volverá a intentar la próxima vez que abras la ' +
      'aplicación.';
  }
  return `Versión ${actual} · es la última publicada (comprobado en GitHub).`;
}

// De cuándo es lo que se cuenta, en una línea.
function cuandoResumen(r) {
  if (r.periodo === 'busqueda') {
    if (!r.busqueda) return '';
    const que = r.busqueda.primera_carga ? 'en la carga del histórico' : 'en la búsqueda';
    return `${que} que terminó el ${fmtFechaHora(r.busqueda.terminada)}`;
  }
  if (r.periodo === 'visita') {
    return r.desde ? `desde que entraste el ${fmtFechaHora(r.desde)}` : 'desde la última vez';
  }
  return `publicadas desde el ${fmtFecha(r.desde)}`;
}

function textoFallos(r) {
  const fallos = (r.busqueda && r.busqueda.fallos) || [];
  if (!fallos.length) return '';
  const cortadas = fallos.filter((f) => (f.error || '').startsWith('atascada'));
  const nombres = [...new Set(fallos.map((f) => f.fuente))].join(', ');
  return (cortadas.length
    ? `Se ha cortado alguna fuente por llevar demasiado sin avanzar (${nombres}).`
    : `Alguna fuente no ha respondido bien (${nombres}).`) +
    ' Lo que falte se pedirá en la próxima búsqueda.';
}

// El bloque con las cifras. `compacto` es para la pantalla de arranque, donde no cabe
// más que lo esencial; la pestaña añade debajo la lista de expedientes.
function bloqueResumen(r, { compacto = false } = {}) {
  const caja = document.createElement('div');
  caja.className = compacto ? 'resumen compacto' : 'resumen';

  const total = document.createElement('p');
  total.className = 'resumen-total';
  if (r.sin_datos) {
    total.textContent = r.periodo === 'busqueda'
      ? 'Todavía no hay ninguna búsqueda apuntada.'
      : 'Todavía no hay una visita anterior apuntada.';
    caja.appendChild(total);
    const p = document.createElement('p');
    p.className = 'pista';
    p.textContent = r.periodo === 'busqueda'
      ? 'Aparecerá aquí en cuanto termine la próxima.'
      : 'Desde la próxima vez que abras el radar, aquí verás lo que ha entrado entretanto.';
    caja.appendChild(p);
    return caja;
  }
  const n = document.createElement('strong');
  n.textContent = r.total ? cuantas(r.total) : 'Ninguna licitación nueva';
  total.appendChild(n);
  caja.appendChild(total);

  const cuando = cuandoResumen(r);
  if (cuando) {
    const p = document.createElement('p');
    p.className = 'pista resumen-cuando';
    p.textContent = cuando + (r.total ? ', en tu bandeja:' : '.');
    caja.appendChild(p);
  }

  if (r.total) {
    const ul = document.createElement('ul');
    ul.className = 'resumen-perfiles';
    for (const pf of r.por_perfil) {
      const li = document.createElement('li');
      if (!pf.total) li.className = 'cero';
      const nom = document.createElement('span');
      nom.textContent = pf.perfil;
      const cif = document.createElement('strong');
      cif.textContent = pf.total.toLocaleString('es-ES');
      li.append(nom, cif);
      ul.appendChild(li);
    }
    caja.appendChild(ul);
  }

  const temas = (r.por_tematica || []).filter((t) => t.total);
  const pt = document.createElement('p');
  pt.className = 'pista resumen-temas';
  pt.textContent = temas.length
    ? 'En «Otras licitaciones»: ' +
      temas.map((t) => `${t.nombre} ${t.total.toLocaleString('es-ES')}`).join(' · ')
    : 'Nada nuevo en las temáticas IT de «Otras licitaciones».';
  caja.appendChild(pt);

  const fallos = textoFallos(r);
  if (fallos) {
    const pf = document.createElement('p');
    pf.className = 'resumen-fallos';
    pf.textContent = fallos;
    caja.appendChild(pf);
  }
  return caja;
}

// La búsqueda ha terminado con la aplicación abierta: se dice arriba qué ha traído.
async function avisarBusquedaTerminada() {
  let r;
  try {
    r = await pedirJSON('/api/resumen-novedades?periodo=busqueda');
  } catch {
    return;
  }
  if (!r || r.error || r.sin_datos) return;
  $('terminada-titulo').textContent = r.total
    ? `Búsqueda terminada: ${cuantas(r.total)}`
    : 'Búsqueda terminada: no hay licitaciones nuevas en tu bandeja';
  const perfiles = r.por_perfil.filter((p) => p.total)
    .map((p) => `${p.perfil} ${p.total.toLocaleString('es-ES')}`).join(' · ');
  const temas = (r.por_tematica || []).some((t) => t.total);
  let detalle = perfiles;
  if (temas) {
    detalle += (detalle ? '; también hay novedades' : 'Hay novedades') +
      ' en «Otras licitaciones»';
  }
  if (detalle) detalle += '.';
  $('terminada-detalle').textContent = [detalle, textoFallos(r)].filter(Boolean).join(' ');
  $('busqueda-terminada').hidden = false;
}

function pintarPeriodos() {
  const cont = $('resumen-periodos');
  cont.textContent = '';
  for (const per of PERIODOS) {
    const b = document.createElement('button');
    b.className = 'ventana' + (per.clave === periodoResumen ? ' activa' : '');
    const t = document.createElement('div');
    t.className = 't';
    t.textContent = per.etiqueta;
    b.appendChild(t);
    b.addEventListener('click', () => {
      periodoResumen = per.clave;
      cargarResumenVista();
    });
    cont.appendChild(b);
  }
}

async function cargarResumenVista() {
  pintarPeriodos();
  $('resumen-lista').textContent = '';
  const carga = empezarCarga('resumen-cuerpo');
  let r;
  try {
    r = await pedirJSON('/api/resumen-novedades?periodo=' + periodoResumen);
  } catch {
    if (carga.terminar()) {
      $('resumen-cuerpo').innerHTML = '<p class="vacio">No se ha podido cargar el resumen.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;
  if (r.error) {
    const p = document.createElement('p');
    p.className = 'vacio';
    p.textContent = r.error;
    $('resumen-cuerpo').appendChild(p);
    return;
  }
  $('resumen-cuerpo').appendChild(bloqueResumen(r));

  const frag = document.createDocumentFragment();
  for (const it of r.items || []) frag.appendChild(tarjeta(it));
  $('resumen-lista').appendChild(frag);
  if (r.total > (r.items || []).length) {
    const p = document.createElement('p');
    p.className = 'pista';
    p.textContent = `Se enseñan las ${r.items.length} más recientes de ${r.total.toLocaleString('es-ES')}; ` +
      'el resto, en la Bandeja.';
    $('resumen-lista').appendChild(p);
  }
  pintarVersionPie();
}

// La versión, también aquí: es lo otro que se enseña al abrir, y quien entró sin esperar
// no lo ha visto. Una sola pregunta a GitHub por sesión.
async function pintarVersionPie() {
  if (!infoVersion) {
    try {
      infoVersion = await pedirJSON('/api/actualizacion');
    } catch { /* sin respuesta se dice solo la versión */ }
  }
  $('resumen-version').textContent = textoVersion(novedadesArranque);
}

// --- Vencimientos ----------------------------------------------------------

let mesesVencimiento = 6;

// --- Siguiendo -----------------------------------------------------------------
//
// Lo que sigues y lo presentado, en dos grupos. Las tarjetas son las de la Bandeja: abren
// la misma ficha, y «ganó X» ya sale cuando el expediente está adjudicado.
async function cargarSiguiendo() {
  const carga = empezarCarga('siguiendo-en-plazo');
  $('siguiendo-vencidas').textContent = '';
  $('siguiendo-n-plazo').textContent = '';
  $('siguiendo-n-vencidas').textContent = '';
  let d;
  try {
    d = await pedirJSON('/api/siguiendo');
  } catch {
    if (carga.terminar()) {
      $('siguiendo-en-plazo').innerHTML = '<p class="vacio">No se ha podido cargar.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;
  pintarGrupoSiguiendo('siguiendo-en-plazo', 'siguiendo-n-plazo', d.en_plazo,
    'Nada de lo que sigues está en plazo ahora mismo.', false);
  pintarGrupoSiguiendo('siguiendo-vencidas', 'siguiendo-n-vencidas', d.vencidas,
    'Todavía no se ha cerrado nada de lo que sigues.', true);
}

function pintarGrupoSiguiendo(idLista, idCifra, items, vacio, cerradas) {
  $(idCifra).textContent = items.length ? items.length.toLocaleString('es-ES') : '';
  const cont = $(idLista);
  if (!items.length) {
    cont.appendChild(crear('p', 'vacio', vacio));
    return;
  }
  for (const it of items) {
    const el = tarjeta(it);
    // De lo cerrado, lo que se quiere saber es quién se lo llevó y por cuánto. «ganó X»
    // ya lo pinta la tarjeta; aquí se le añade el importe, o se dice que todavía no se
    // sabe, en el mismo sitio: detrás del plazo.
    const ganador = el.querySelector('.pill.incumbente');
    if (ganador && it.importe_adjudicacion) {
      ganador.lastChild.textContent += ` · ${fmtImporte(it.importe_adjudicacion)}`;
    } else if (cerradas && !it.adjudicatario) {
      const pendiente = pildora('adjudicación pendiente');
      const plazo = el.querySelector('.pill.plazo-vencido, .pill.plazo-pronto, .pill.plazo-ok');
      if (plazo) plazo.after(pendiente);
      else el.querySelector('.meta').appendChild(pendiente);
    }
    cont.appendChild(el);
  }
}

async function cargarVencimientos() {
  const meses = mesesVencimiento;
  const carga = empezarCarga('lista-vencimientos');
  // Los botones de ventana y el total se borran también: son del plazo anterior y
  // dejarlos mientras carga el nuevo es peor que no mostrar nada.
  $('ventanas').innerHTML = '';
  $('total-ventana').textContent = '';

  const cont = $('lista-vencimientos');
  let d;
  try {
    const r = await fetch('/api/vencimientos?meses=' + meses);
    d = await r.json();
  } catch {
    if (carga.terminar()) {
      cont.innerHTML = '<p class="vacio">No se pudieron cargar los vencimientos.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;

  // Botones de ventana con su recuento e importe, para comparar de un vistazo.
  $('ventanas').innerHTML = (d.por_ventana || []).map((v) =>
    `<button class="ventana ${v.meses === meses ? 'activa' : ''}" data-meses="${v.meses}">
       <div class="n">${v.total.toLocaleString('es-ES')}</div>
       <div class="t">${v.meses} meses</div>
       <div class="imp">${fmtImporte(v.importe)}</div>
     </button>`
  ).join('');
  for (const b of $('ventanas').querySelectorAll('.ventana')) {
    b.addEventListener('click', () => {
      mesesVencimiento = Number(b.dataset.meses);
      cargarVencimientos();
    });
  }

  const plural = d.total === 1 ? 'contrato vence' : 'contratos vencen';
  $('total-ventana').innerHTML =
    `<strong>${d.total.toLocaleString('es-ES')}</strong> ${plural} en los próximos ` +
    `${meses} meses, por <strong>${fmtImporte(d.importe_total)}</strong> en total.`;

  if (!d.items.length) {
    cont.innerHTML = `<p class="vacio">Nada vence en los próximos ${meses} meses.
      Para verlo hace falta histórico de adjudicaciones:
      <code>python3 radar.py ingest --primera-carga</code></p>`;
    return;
  }

  for (const it of d.items) {
    const el = document.createElement('article');
    el.className = 'tarjeta';
    el.dataset.id = it.id;
    const meses_txt = it.duracion_meses
      ? `contrato de ${Math.round(it.duracion_meses)} meses` : '';
    el.innerHTML = `
      <div>
        <h3></h3>
        <div class="organo"></div>
        <div class="meta">
          <span class="pill incumbente"></span>
          <span class="pill importe">${fmtImporte(it.importe)}</span>
          <span class="pill">vence ${fmtFecha(it.fecha_fin_prevista)}</span>
          ${meses_txt ? `<span class="pill">${meses_txt}</span>` : ''}
          ${it.ccaa ? `<span class="pill">${it.ccaa}</span>` : ''}
        </div>
      </div>
      <div class="derecha">
        <div class="dias ${it.dias_para_vencer <= 90 ? 'pronto' : ''}">${it.dias_para_vencer}<small>días</small></div>
      </div>`;
    el.querySelector('h3').textContent = it.objeto || '(sin objeto)';
    if (it.organo) el.querySelector('.organo').appendChild(enlaceFicha(it.organo, 'organismo', it.organo));
    const incumbente = el.querySelector('.incumbente');
    incumbente.textContent = 'incumbente: ';
    if (it.adjudicatario) {
      incumbente.appendChild(enlaceFicha(it.adjudicatario, 'competidor', it.adjudicatario));
    } else {
      incumbente.appendChild(document.createTextNode('no publicado'));
    }
    el.addEventListener('click', () => abrirPanel(it.id));
    cont.appendChild(el);
  }
}

// --- Adjudicatarios --------------------------------------------------------

// --- Ámbito: perfiles o temática del mercado --------------------------------
//
// Analítica y Adjudicatarios se pueden mirar sobre lo que traen tus perfiles —lo de
// siempre— o sobre una temática entera del mercado, case o no con ellos. El valor del
// desplegable lleva el tipo delante («perfil:…», «categoria:…») porque un perfil se
// puede llamar como una temática y son dos preguntas distintas.

// Las temáticas las dice el servidor (`/api/categorias`), no este fichero: viven en
// `radar/categorias.py`, y una lista copiada aquí acabaría desfasada.
let TEMAS = { categorias: [], resto: null, toda_la_it: null, ccaa: [] };
let ultimosPerfiles = [];

function nombreTema(clave) {
  if (TEMAS.resto && clave === TEMAS.resto.clave) return TEMAS.resto.nombre;
  if (TEMAS.toda_la_it && clave === TEMAS.toda_la_it.clave) return TEMAS.toda_la_it.nombre;
  const c = TEMAS.categorias.find((x) => x.clave === clave);
  return c ? c.nombre : clave;
}

async function cargarTemas() {
  try {
    TEMAS = await (await fetch('/api/categorias')).json();
  } catch { /* sin temáticas, los selectores ofrecen solo los perfiles */ }
  llenarAmbitos();
  pintarChipsTemas();
  llenarSelect($('otras-ccaa'), TEMAS.ccaa.map((c) => [c, c]));
}

// Los dos desplegables de ámbito, con dos grupos. Se construyen con `Option` y no con
// cadenas: el nombre de un perfil lo escribe quien usa la herramienta.
function llenarAmbitos() {
  for (const sel of [$('analitica-perfil'), $('adjudicatarios-ambito'), $('organismos-ambito'),
                     $('organismo-ambito'), $('competidor-ambito')]) {
    const firma = JSON.stringify([ultimosPerfiles, TEMAS.categorias]);
    if (sel.dataset.firma === firma) continue;
    sel.dataset.firma = firma;
    const elegido = sel.value;
    sel.textContent = '';
    const perfiles = document.createElement('optgroup');
    perfiles.label = 'Tus perfiles';
    perfiles.appendChild(new Option('Todos los perfiles', ''));
    for (const p of ultimosPerfiles) perfiles.appendChild(new Option(p, 'perfil:' + p));
    sel.appendChild(perfiles);
    if (TEMAS.categorias.length) {
      // «Resto» no se ofrece: son 600.000 fichas de obras y limpieza, la primera
      // vez tardaría decenas de segundos y no dice nada del mercado IT.
      const mercado = document.createElement('optgroup');
      mercado.label = 'Mercado por temática';
      if (TEMAS.toda_la_it) {
        mercado.appendChild(new Option(TEMAS.toda_la_it.nombre,
                                       'categoria:' + TEMAS.toda_la_it.clave));
      }
      for (const c of TEMAS.categorias) {
        mercado.appendChild(new Option(c.nombre, 'categoria:' + c.clave));
      }
      sel.appendChild(mercado);
    }
    sel.value = [...sel.options].some((o) => o.value === elegido) ? elegido : '';
  }
}

// «perfil:X» → perfil=X, «categoria:Y» → categoria=Y, «» → nada (todos los perfiles).
function ponerAmbito(params, valor) {
  const i = (valor || '').indexOf(':');
  if (i > 0) params.set(valor.slice(0, i), valor.slice(i + 1));
  return params;
}

const esMercado = (valor) => (valor || '').startsWith('categoria:');

let ambitoAdjudicatarios = '';

async function cargarAdjudicatarios() {
  const carga = empezarCarga('lista-adjudicatarios');
  const cont = $('lista-adjudicatarios');
  let d;
  try {
    const p = ponerAmbito(new URLSearchParams({ limite: 30 }), ambitoAdjudicatarios);
    const r = await fetch('/api/adjudicatarios?' + p);
    d = await r.json();
  } catch {
    if (carga.terminar()) {
      cont.innerHTML = '<p class="vacio">No se pudieron cargar los adjudicatarios.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;

  if (d.error) {
    cont.innerHTML = '<p class="vacio"></p>';
    cont.firstChild.textContent = d.error;
    return;
  }
  if (!d.items.length) {
    cont.innerHTML = `<p class="vacio">Aún no hay adjudicaciones en la base.
      Prueba: <code>python3 radar.py ingest --primera-carga</code></p>`;
    return;
  }

  for (const e of d.items) {
    const el = document.createElement('article');
    el.className = 'tarjeta fila-empresa';
    el.innerHTML = `
      <div>
        <h3></h3>
        <div class="organo">${e.organos} organismo${e.organos === 1 ? '' : 's'} distinto${e.organos === 1 ? '' : 's'}</div>
      </div>
      <div class="cifras">
        <span><b>${e.contratos}</b> contratos</span>
        <span><b>${fmtImporte(e.importe)}</b></span>
      </div>`;
    el.querySelector('h3').textContent = e.empresa;
    // Con el mismo ámbito que el ranking: si no, la ficha de una empresa de cloud
    // enseñaría solo lo que casa con los perfiles y no cuadraría con su cifra.
    el.addEventListener('click', () => abrirFicha('competidor', e.empresa, ambitoAdjudicatarios));
    cont.appendChild(el);
  }
}

// --- Organismos -------------------------------------------------------------------

let ambitoOrganismos = '';

async function cargarOrganismos() {
  const carga = empezarCarga('lista-organismos', esMercado(ambitoOrganismos)
    ? 'Cargando… con una temática, la primera vez tarda unos segundos' : 'Cargando…');
  const cont = $('lista-organismos');
  $('organismos-contador').textContent = '';
  let d;
  try {
    const p = ponerAmbito(new URLSearchParams(), ambitoOrganismos);
    const q = $('organismos-q').value.trim();
    if (q) p.set('q', q);
    d = await pedirJSON('/api/organismos?' + p);
  } catch {
    if (carga.terminar()) cont.appendChild(crear('p', 'vacio', 'No se pudieron cargar.'));
    return;
  }
  if (!carga.terminar()) return;
  if (d.error) {
    cont.appendChild(crear('p', 'vacio', d.error));
    return;
  }
  $('organismos-contador').textContent = d.total === d.distintos
    ? `${d.total.toLocaleString('es-ES')} organismos`
    : `${d.total.toLocaleString('es-ES')} de ${d.distintos.toLocaleString('es-ES')} organismos`;
  if (!d.items.length) {
    cont.appendChild(crear('p', 'vacio', 'Ningún organismo con ese nombre en este ámbito.'));
    return;
  }
  for (const o of d.items) {
    const el = crear('article', 'tarjeta fila-organismo');
    const izq = crear('div');
    izq.appendChild(crear('h3', '', o.organo));
    izq.appendChild(crear('div', 'organo', o.ultimo
      ? `último expediente: ${fmtFecha(o.ultimo)}` : ''));
    el.appendChild(izq);
    const cifras = crear('div', 'cifras');
    for (const [n, t] of [[o.expedientes, 'expedientes'], [o.abiertos, 'abiertos'],
                          [o.adjudicados, 'adjudicados']]) {
      const span = crear('span');
      span.appendChild(crear('b', '', n.toLocaleString('es-ES')));
      span.appendChild(document.createTextNode(' ' + t));
      cifras.appendChild(span);
    }
    el.appendChild(cifras);
    el.addEventListener('click', () => abrirFicha('organismo', o.organo, ambitoOrganismos));
    cont.appendChild(el);
  }
}

// --- Fichas de organismo y de competidor ---------------------------------------------
//
// Las mismas piezas que la Analítica, sobre un solo órgano o una sola empresa: las cifras
// en fila, columnas para lo que tiene orden y barras para los rankings. Todo nombre de
// órgano o de empresa lleva a su propia ficha, y «Volver» deshace el camino.

let pasadaFicha = 0;

async function cargarFicha() {
  const f = fichaActual;
  if (!f) return;
  const pasada = ++pasadaFicha;
  const id = `ficha-${f.tipo}`;
  $(`${f.tipo}-ambito`).value = f.ambito;
  $('vista-titulo').textContent = f.nombre;
  $('vista-sub').textContent = '';
  const carga = empezarCarga(id, esMercado(f.ambito)
    ? 'Calculando… con una temática, la primera vez tarda unos segundos' : 'Calculando…');
  let d;
  try {
    const p = ponerAmbito(new URLSearchParams(
      f.tipo === 'organismo' ? { nombre: f.nombre } : { empresa: f.nombre }), f.ambito);
    d = await pedirJSON(`/api/${f.tipo}?` + p);
  } catch {
    if (carga.terminar()) $(id).appendChild(crear('p', 'vacio', 'No se ha podido cargar la ficha.'));
    return;
  }
  if (pasada !== pasadaFicha || !carga.terminar()) return;
  tooltip().hidden = true;
  const cont = $(id);
  if (d.error) {
    cont.appendChild(crear('p', 'vacio', `${d.error} Prueba con otro ámbito en el desplegable.`));
    return;
  }
  if (f.tipo === 'organismo') pintarFichaOrganismo(cont, d, f.ambito);
  else pintarFichaCompetidor(cont, d, f.ambito);
}

function filaCifras(cifras) {
  const fila = crear('div', 'cifras-clave');
  for (const [etiqueta, valor, pie] of cifras.filter(Boolean)) {
    const c = crear('div', 'cifra-clave fija');
    c.appendChild(crear('span', 't', etiqueta));
    c.appendChild(crear('span', 'n', valor));
    if (pie) c.appendChild(crear('span', 's', pie));
    fila.appendChild(c);
  }
  return fila;
}

// Una mediana de dos casos no es una mediana: por debajo de tres no se enseña.
const MINIMO_MEDIANA_FICHA = 3;

function parejas(cont, filas) {
  for (const fila of filas) {
    const caja = crear('div', 'pareja');
    fila.filter(Boolean).forEach((b) => caja.appendChild(b));
    cont.appendChild(caja);
  }
}

// Los contratos que vencen: con el incumbente enlazado, que es la llamada que se hace.
// `conOrgano` en la del competidor: allí cada contrato es de un organismo distinto.
function bloqueVencen(d, ambito, pregunta, conOrgano = false) {
  const el = bloqueAnalitica('Qué vence', pregunta);
  if (!d.vencen.length) {
    nota(el, `Nada con fecha de fin en los próximos ${d.meses_vencen} meses.`);
    return el;
  }
  titular(el, d.vencen.length.toLocaleString('es-ES'), `en ${d.meses_vencen} meses`);
  const lista = crear('div', 'lista-ficha');
  for (const v of d.vencen.slice(0, 20)) {
    const fila = crear('div', 'fila-ficha');
    fila.appendChild(enlaceTexto(v.objeto || '(sin objeto)', v.id));
    fila.appendChild(crear('span', 'cifra', `vence ${fmtFecha(v.fecha_fin_prevista)}`));
    const det = crear('span', 'detalle');
    det.appendChild(document.createTextNode(`${fmtImporte(v.importe)} · `));
    det.appendChild(enlaceFicha(v.adjudicatario, 'competidor', v.adjudicatario, ambito));
    if (conOrgano && v.organo) {
      det.appendChild(document.createTextNode(' · '));
      det.appendChild(enlaceFicha(v.organo, 'organismo', v.organo, ambito));
    }
    fila.appendChild(det);
    lista.appendChild(fila);
  }
  el.appendChild(lista);
  if (d.vencen.length > 20) nota(el, `Y ${d.vencen.length - 20} más.`);
  return el;
}

// El objeto de un contrato, que abre la ficha de la licitación.
function enlaceTexto(texto, id) {
  const b = crear('button', 'enlace-ficha objeto', texto);
  b.addEventListener('click', () => abrirPanel(id));
  return b;
}

function bloqueTarjetas(titulo, pregunta, items, vacio, resto = 0) {
  const el = bloqueAnalitica(titulo, pregunta);
  if (!items.length) {
    nota(el, vacio);
    return el;
  }
  const lista = crear('div', 'lista');
  for (const it of items) lista.appendChild(tarjeta(it));
  el.appendChild(lista);
  if (resto > 0) nota(el, `Y ${resto.toLocaleString('es-ES')} más, los más antiguos.`);
  return el;
}

function pintarFichaOrganismo(cont, d, ambito) {
  $('vista-sub').textContent = [
    d.nifs.length ? `NIF ${d.nifs.join(', ')}` : '',
    d.comunidades.join(', '),
    `ámbito: ${d.ambito}`,
  ].filter(Boolean).join(' · ');
  const c = d.cifras;
  cont.appendChild(filaCifras([
    ['Expedientes', fmtEntero(c.expedientes),
     `${fmtEntero(c.abiertos)} ${c.abiertos === 1 ? 'abierto' : 'abiertos'} ahora`],
    ['Importe mediano', fmtImporteCorto(c.importe_mediano), 'el mayor publicado de cada uno'],
    c.baja_comparables >= MINIMO_MEDIANA_FICHA &&
      ['Baja mediana', `${fmtDecimal(c.baja_mediana)} %`,
       `de ${fmtEntero(c.baja_comparables)} adjudicaciones comparables`],
    c.plazo_expedientes >= MINIMO_MEDIANA_FICHA &&
      ['Plazo para presentar', `${c.plazo_mediano} días`, 'de mediana'],
    ['Adjudicados', fmtEntero(c.adjudicados), 'con empresa publicada'],
  ]));

  const meses = bloqueAnalitica('Cuándo publica',
    `¿En qué meses saca sus expedientes? Por mes de primera publicación` +
    (d.desde ? `, ${d.desde === d.hasta ? d.desde : `de ${d.desde} a ${d.hasta}`}.` : '.'));
  meses.appendChild(columnas(d.meses.map((m) => ({
    etiqueta: MESES_CORTOS[m.mes - 1], valor: m.expedientes,
  })), { serie: 'expedientes', etiquetarTodo: true }));

  const gana = bloqueAnalitica('Quién gana aquí', '¿A quién le adjudica, y cuántas veces?');
  const empresas = d.adjudicatarios.empresas;
  if (!empresas.length) {
    nota(gana, 'Ningún expediente adjudicado con empresa publicada.');
  } else {
    const tope = Math.max(1, ...empresas.map((e) => e.contratos));
    for (const e of empresas) {
      gana.appendChild(filaBarra(e.empresa, 100 * e.contratos / tope,
        `${fmtEntero(e.contratos)} · ${fmtImporteCorto(e.importe)}`,
        { apilada: true, alPulsar: () => abrirFicha('competidor', e.empresa, ambito) }));
    }
    if (d.adjudicatarios.distintas > empresas.length) {
      nota(gana, `${fmtEntero(d.adjudicatarios.distintas)} empresas distintas en total.`);
    }
  }
  const m = metodo(gana);
  nota(m, 'El órgano es el que firma, tal como lo publica la fuente: una misma agencia ' +
          'puede tener varias fichas, una por firmante.');

  parejas(cont, [
    [meses, gana],
    [bloqueVencen(d, ambito, '¿Qué contratos suyos se acaban y quién los tiene ahora?')],
  ]);
  cont.appendChild(bloqueTarjetas('Qué tiene abierto', '¿Qué se le puede presentar hoy?',
    d.abiertos, 'Nada abierto ahora mismo.'));
  cont.appendChild(bloqueTarjetas('Sus expedientes', 'Lo que ya no está en plazo, de lo más reciente a lo más antiguo.',
    d.anteriores, 'Todavía no hay expedientes cerrados.',
    d.anteriores_total - d.anteriores.length));
}

function pintarFichaCompetidor(cont, d, ambito) {
  $('vista-titulo').textContent = d.empresa;
  $('vista-sub').textContent = `ámbito: ${d.ambito}`;
  const c = d.cifras;
  cont.appendChild(filaCifras([
    ['Expedientes ganados', fmtEntero(c.ganados), `en ${fmtEntero(c.organismos)} organismos`],
    ['Importe adjudicado', fmtImporteCorto(c.importe), 'el mayor publicado de cada uno'],
    c.baja_comparables >= MINIMO_MEDIANA_FICHA &&
      ['Baja mediana', `${fmtDecimal(c.baja_mediana)} %`,
       `de ${fmtEntero(c.baja_comparables)} adjudicaciones comparables`],
    ['Comunidades', fmtEntero(c.comunidades), 'donde ha ganado algo'],
  ]));

  const anios = bloqueAnalitica('Año a año', '¿Gana más o menos que antes?');
  anios.appendChild(columnas(d.por_anio.map((a) => ({
    etiqueta: a.anio, valor: a.expedientes,
    titulo: `${a.anio} · ${fmtImporteCorto(a.importe)}`,
  })), { serie: 'expedientes ganados', etiquetarTodo: true }));
  nota(anios, 'Por el año de adjudicación; si no se publicó, el de la primera publicación.');

  const donde = bloqueAnalitica('Dónde gana', '¿En qué comunidades se lleva los contratos?');
  if (!d.comunidades.length) {
    nota(donde, 'Ninguna adjudicación con comunidad publicada (TED no la publica).');
  } else {
    const tope = Math.max(1, ...d.comunidades.map((x) => x.expedientes));
    for (const x of d.comunidades) {
      donde.appendChild(filaBarra(x.ccaa, 100 * x.expedientes / tope,
        `${fmtEntero(x.expedientes)} · ${fmtImporteCorto(x.importe)}`, { apilada: true }));
    }
  }

  const clientes = bloqueAnalitica('A quién le vende', '¿Qué organismos le adjudican más?');
  const tope = Math.max(1, ...d.organismos.map((x) => x.expedientes));
  for (const x of d.organismos) {
    clientes.appendChild(filaBarra(x.organo, 100 * x.expedientes / tope,
      `${fmtEntero(x.expedientes)} · ${fmtImporteCorto(x.importe)}`,
      { apilada: true, alPulsar: () => abrirFicha('organismo', x.organo, ambito) }));
  }
  if (c.organismos > d.organismos.length) {
    nota(clientes, `${fmtEntero(c.organismos)} organismos distintos en total.`);
  }

  const contratos = bloqueAnalitica('Sus adjudicaciones', 'De la más reciente a la más antigua.');
  const lista = crear('div', 'lista-ficha');
  for (const x of d.contratos) {
    const fila = crear('div', 'fila-ficha');
    fila.appendChild(enlaceTexto(x.objeto || '(sin objeto)', x.id));
    fila.appendChild(crear('span', 'cifra', fmtImporte(x.importe)));
    const det = crear('span', 'detalle');
    det.appendChild(document.createTextNode(
      (x.fecha_adjudicacion ? fmtFecha(x.fecha_adjudicacion) : 'sin fecha') + ' · '));
    det.appendChild(enlaceFicha(x.organo || '(sin órgano)', 'organismo', x.organo, ambito));
    fila.appendChild(det);
    lista.appendChild(fila);
  }
  contratos.appendChild(lista);
  if (d.contratos_total > d.contratos.length) {
    nota(contratos, `Y ${fmtEntero(d.contratos_total - d.contratos.length)} más, las más antiguas.`);
  }
  if (d.variantes.length > 1) {
    const m = metodo(contratos, 'Razones sociales juntadas');
    nota(m, d.variantes.join(' · '));
  }

  parejas(cont, [
    [anios, donde],
    [clientes, bloqueVencen(d, ambito,
      '¿Qué contratos suyos se acaban? Es la ocasión de quitárselos.', true)],
    [contratos],
  ]);
}

// --- Términos de búsqueda --------------------------------------------------

// Las listas de términos se editan como texto, una por línea: es lo más simple sin
// saber JSON, y el orden no importa.
const CAMPOS_TERMINOS = [
  ['terminos_fuertes', 'Términos fuertes',
   'se bastan solos para que una licitación entre (phishing, DMARC…)'],
  ['terminos_debiles', 'Términos ambiguos',
   'solo entran si además aparece algo del contexto (concienci, formacion…)'],
  ['contexto_requerido', 'Contexto requerido',
   'lo que confirma que va de seguridad (ciberseguridad, malware…)'],
  ['excluir', 'Exclusiones',
   'manda sobre todo lo demás (seguridad vial, riesgos laborales…)'],
  ['terminos_consulta', 'Qué se pregunta a TED y Cataluña',
   'filtran en su servidor; no metas palabras genéricas aquí'],
  ['cpv_prefijos', 'Códigos CPV',
   'suman puntos pero nunca aceptan por sí solos'],
];

let perfilesOriginales = null;

async function cargarAjustes() {
  const carga = empezarCarga('lista-perfiles');
  let d;
  try {
    d = await (await fetch('/api/perfiles')).json();
  } catch {
    if (carga.terminar()) {
      $('lista-perfiles').innerHTML =
        '<p class="vacio">No se pudieron cargar los términos de búsqueda.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;

  perfilesOriginales = JSON.parse(JSON.stringify(d.perfiles));

  $('consejos').innerHTML = '<ul>' + [
    '<b>Usa raíces, no palabras completas.</b> «conscienci» cubre conscienciar, conscienciació y concienciación.',
    '<b>Deja las erratas.</b> «phising» con una sola s aparece tal cual en pliegos publicados.',
    '<b>Los textos de Cataluña están en catalán.</b> Incluye ciberseguridad y ciberseguretat. Los acentos son indiferentes.',
    '<b>Los espacios cuentan.</b> «ens » con espacio final busca la sigla suelta; sin él casaría dentro de «ensayo» o «enseñanza».',
    '<b>Pulsa «Ver qué cambiaría» antes de guardar.</b> Te dice cuántas licitaciones entran y salen con los términos nuevos.',
  ].map((t) => `<li>${t}</li>`).join('') + '</ul>';

  const cont = $('lista-perfiles');
  cont.innerHTML = '';
  d.perfiles.forEach((p, i) => {
    const caja = document.createElement('section');
    caja.className = 'perfil-caja';
    caja.dataset.indice = i;
    caja.innerHTML = `
      <header>
        <h3></h3>
        <label class="check"><input type="checkbox" data-campo="activo" ${p.activo ? 'checked' : ''}> activo</label>
        <span class="campo-num">importe mínimo
          <input type="number" data-campo="importe_minimo" min="0" step="1000"
                 value="${p.importe_minimo ?? ''}" placeholder="sin mínimo"> €</span>
      </header>
      <div class="campos">
        ${CAMPOS_TERMINOS.map(([clave, titulo, ayuda]) => `
          <div class="campo-term">
            <label><b>${titulo}</b><br>${ayuda}</label>
            <textarea data-campo="${clave}" spellcheck="false">${(p[clave] || []).join('\n')}</textarea>
          </div>`).join('')}
      </div>`;
    caja.querySelector('h3').textContent = p.nombre;
    cont.appendChild(caja);
  });
  $('previsualizacion').hidden = true;
  $('ajustes-aviso').textContent = '';
}

function leerAjustes() {
  // Los espacios de los extremos NO se recortan: hay términos que los llevan a
  // propósito para casar una palabra suelta. «ens » con espacio busca la sigla ENS;
  // recortado a «ens» casa dentro de "ensayo" o "enseñanza" y mete licitaciones de más.
  // (En "defensa" o "bienes" no, porque el matcher ancla a principio de palabra: ver
  // `patron()`.) Solo se descartan las líneas vacías y el retorno de carro.
  const lineas = (t) => t
    .split('\n')
    .map((s) => s.replace(/\r/g, ''))
    .filter((s) => s.trim() !== '');
  return [...$('lista-perfiles').querySelectorAll('.perfil-caja')].map((caja) => {
    const original = perfilesOriginales[Number(caja.dataset.indice)];
    // Se parte del original para no perder campos que la pantalla no muestra
    // (fuentes, ccaa) en lugar de reescribir el perfil desde cero.
    const p = { ...original };
    p.activo = caja.querySelector('[data-campo="activo"]').checked;
    const imp = caja.querySelector('[data-campo="importe_minimo"]').value.trim();
    p.importe_minimo = imp === '' ? null : Number(imp);
    for (const [clave] of CAMPOS_TERMINOS) {
      p[clave] = lineas(caja.querySelector(`[data-campo="${clave}"]`).value);
    }
    return p;
  });
}

function avisoDeAlcance(perfiles) {
  // TED y Cataluña filtran en su servidor: un término nuevo en terminos_consulta o
  // un CPV nuevo no aparece hasta volver a preguntarles.
  const cambiado = perfiles.some((p, i) => {
    const o = perfilesOriginales[i] || {};
    return JSON.stringify(p.terminos_consulta || []) !== JSON.stringify(o.terminos_consulta || [])
        || JSON.stringify(p.cpv_prefijos || []) !== JSON.stringify(o.cpv_prefijos || []);
  });
  return cambiado;
}

async function previsualizarAjustes() {
  const perfiles = leerAjustes();
  const caja = $('previsualizacion');
  const btn = $('previsualizar');
  // Recorrer todo lo descargado tarda un par de segundos: sin este aviso parece
  // que el botón no ha hecho nada.
  caja.hidden = false;
  caja.textContent = 'Calculando sobre todo lo descargado…';
  btn.disabled = true;
  let r, d;
  try {
    r = await fetch('/api/perfiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ perfiles, previsualizar: true }),
    });
    d = await r.json();
  } finally {
    btn.disabled = false;
  }
  if (!r.ok) {
    caja.innerHTML = `<strong>No se puede guardar:</strong> ${d.error}`;
    return;
  }
  const lista = (titulo, items) => items.length
    ? `<h4>${titulo}</h4><ul>${items.map((x) =>
        `<li>${(x.objeto || '').slice(0, 95)} — ${x.organo || ''}</li>`).join('')}</ul>`
    : '';
  const avisos = (d.avisos || []).length
    ? `<h4>Cosas a tener en cuenta</h4><ul>${
        d.avisos.map((a) => `<li>${a}</li>`).join('')}</ul>`
    : '';
  caja.innerHTML =
    `Pasarías de <strong>${d.antes.toLocaleString('es-ES')}</strong> a ` +
    `<strong>${d.despues.toLocaleString('es-ES')}</strong> coincidencias ` +
    `(${d.entran} entran, ${d.salen} salen).` +
    avisos +
    lista('Ejemplos de lo que entraría', d.muestra_entran) +
    lista('Ejemplos de lo que saldría', d.muestra_salen);
}

async function guardarAjustes() {
  const perfiles = leerAjustes();
  const hayQueRebuscar = avisoDeAlcance(perfiles);
  const r = await fetch('/api/perfiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ perfiles }),
  });
  const d = await r.json();
  if (!r.ok) {
    $('ajustes-aviso').textContent = d.error;
    return;
  }
  $('ajustes-aviso').textContent =
    `Guardado · ${d.coincidencias.toLocaleString('es-ES')} coincidencias`;
  perfilesOriginales = JSON.parse(JSON.stringify(perfiles));
  await cargarResumen();
  // Y la lista, no solo los contadores: «Guardar y aplicar» acaba de reevaluar todo lo
  // descargado, así que la bandeja de detrás es la de los términos viejos. Antes había
  // que cambiar de pestaña y tocar un filtro para verla al día.
  await cargarLista();

  if (hayQueRebuscar) {
    const caja = $('previsualizacion');
    caja.hidden = false;
    caja.innerHTML =
      '<strong>Has cambiado lo que se pregunta a TED y Cataluña.</strong> Esas dos ' +
      'fuentes filtran en su servidor, así que los términos nuevos no traerán nada ' +
      'hasta volver a preguntarles. Tarda más que una búsqueda normal.';
    const btn = document.createElement('button');
    btn.className = 'boton-pri';
    btn.style.marginTop = '10px';
    btn.textContent = 'Volver a preguntar a las fuentes';
    btn.addEventListener('click', () => {
      caja.hidden = true;
      mostrarVista('bandeja');
      lanzarBusqueda({ reiniciar_cursor: true, dias: 365 });
    });
    caja.appendChild(btn);
  }
}

// --- Cambio de vista -------------------------------------------------------

// El panel y su fondo se abren y se cierran juntos. Antes había tres sitios distintos
// poniendo `$('panel').hidden` a mano, y con el fondo serían seis.
// La ficha es la tercera columna cuando cabe al lado de la lista, como el panel de
// detalle de Zepo Desk, y flota encima cuando no. El corte es el mismo que el de la
// consulta `@media (max-width: 1239px)` de styles.css: si cambia uno, el otro.
const FICHA_FLOTANTE = window.matchMedia('(max-width: 1239px)');

function fichaFlotante() {
  return FICHA_FLOTANTE.matches;
}

function abrirCajon() {
  // El fondo oscurecido solo cuando flota: fija, la ficha no tapa nada que haya que
  // apartar, y oscurecer la lista que se sigue leyendo al lado no tendría sentido.
  $('panel-fondo').hidden = !fichaFlotante();
  $('panel').hidden = false;
}

// La fila de la ficha abierta se queda marcada, como en Zepo Desk: con la ficha al lado,
// es lo que dice de cuál de las cien es lo que se está leyendo.
function marcarSeleccionada(id) {
  for (const el of document.querySelectorAll('.tarjeta.seleccionada')) {
    el.classList.remove('seleccionada');
  }
  if (id == null) return;
  for (const el of document.querySelectorAll(`.tarjeta[data-id="${Number(id)}"]`)) {
    el.classList.add('seleccionada');
  }
}

// Si la ventana cambia de ancho con la ficha abierta, el fondo tiene que aparecer o irse:
// si no, una ficha que pasa a flotar se quedaría sin dónde pulsar para cerrarla.
FICHA_FLOTANTE.addEventListener('change', () => {
  if (!$('panel').hidden) $('panel-fondo').hidden = !fichaFlotante();
});

function cerrarCajon() {
  $('panel').hidden = true;
  $('panel-fondo').hidden = true;
  marcarSeleccionada(null);
}

let vistaActual = 'bandeja';

// El orden de la barra lateral, que es también el de los atajos ⌘1…⌘9.
const VISTAS = ['bandeja', 'resumen', 'otras', 'siguiendo', 'vencimientos', 'adjudicatarios',
                'organismos', 'analitica', 'ajustes'];
// Las fichas: vistas sin entrada en la barra lateral, a las que se llega desde un nombre.
// Mientras se mira una, la barra lateral resalta la lista de la que es.
const VISTAS_DETALLE = { organismo: 'organismos', competidor: 'adjudicatarios' };

// Lo que hay que deshacer al pulsar «Volver»: de dónde se vino y por dónde se iba. Se
// vacía al elegir una vista en la barra lateral, que es empezar de nuevo.
let pilaVolver = [];
// La ficha que se está mirando: `{ tipo, nombre, ambito }`.
let fichaActual = null;

function abrirFicha(tipo, nombre, ambito = '') {
  if (!nombre) return;
  pilaVolver.push({ vista: vistaActual, ficha: fichaActual, scroll: $('cuerpo').scrollTop });
  fichaActual = { tipo, nombre, ambito };
  mostrarVista(tipo, { conservarPila: true });
}

async function volver() {
  const v = pilaVolver.pop();
  if (!v) {
    mostrarVista(VISTAS_DETALLE[vistaActual] || 'bandeja');
    return;
  }
  fichaActual = v.ficha;
  // Se espera a que la vista se pinte para devolver el scroll: hasta entonces no hay
  // por dónde bajar.
  await mostrarVista(v.vista, { conservarPila: true });
  $('cuerpo').scrollTop = v.scroll;
}

// Un nombre que lleva a su ficha. Para dentro de una tarjeta, que ya abre la licitación
// al pulsarla: el clic en el nombre se queda en el nombre.
function enlaceFicha(texto, tipo, nombre, ambito = '') {
  const b = crear('button', 'enlace-ficha', texto);
  b.title = tipo === 'organismo' ? 'Ver la ficha del organismo' : 'Ver la ficha de la empresa';
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    abrirFicha(tipo, nombre, ambito);
  });
  return b;
}

// La cabecera de la vista sale de su propia sección: `data-titulo`, `data-icono`,
// `data-tono` y el párrafo `.intro`. Es marcado estático de `index.html`, nunca texto de un
// pliego, y por eso puede ir por `innerHTML` (lleva algún `<strong>`).
function pintarCabecera(vista) {
  const sec = $('vista-' + vista);
  $('vista-titulo').textContent = sec.dataset.titulo || '';
  const intro = sec.querySelector(':scope > .intro');
  $('vista-sub').innerHTML = intro ? intro.innerHTML : '';
  $('vista-icono').className = `vista-icono tono-${sec.dataset.tono || 'acento'}`;
  $('vista-icono-uso').setAttribute('href', '#' + (sec.dataset.icono || 'ico-bandeja'));
  document.title = vista === 'bandeja' ? 'Radar de Licitaciones'
    : `${sec.dataset.titulo} · Radar de Licitaciones`;
}

// Devuelve la carga de la vista, para quien necesite esperarla (`volver()`).
function mostrarVista(vista, { conservarPila = false } = {}) {
  if (!conservarPila) {
    pilaVolver = [];
    fichaActual = null;
  }
  vistaActual = vista;
  for (const v of [...VISTAS, ...Object.keys(VISTAS_DETALLE)]) {
    $('vista-' + v).hidden = v !== vista;
  }
  $('filtros').hidden = vista !== 'bandeja';
  pintarCabecera(vista);
  // Cada vista empieza arriba: el scroll vive en `.cuerpo`, que es el mismo para todas, y
  // sin esto se heredaba la posición de la anterior.
  $('cuerpo').scrollTop = 0;
  const resaltada = VISTAS_DETALLE[vista] || vista;
  for (const b of document.querySelectorAll('.tab[data-vista]')) {
    const activa = b.dataset.vista === resaltada;
    b.classList.toggle('activo', activa);
    // La clase es para el ojo; `aria-selected` para quien no lo usa. Alternar solo la
    // primera dejaba a un lector de pantalla seis pestañas sin ninguna seleccionada.
    b.setAttribute('aria-selected', activa ? 'true' : 'false');
  }
  const cargas = {
    resumen: cargarResumenVista,
    otras: cargarOtras,
    siguiendo: cargarSiguiendo,
    vencimientos: cargarVencimientos,
    adjudicatarios: cargarAdjudicatarios,
    organismos: cargarOrganismos,
    organismo: cargarFicha,
    competidor: cargarFicha,
    analitica: cargarAnalitica,
    ajustes: cargarAjustes,
  };
  return cargas[vista] ? cargas[vista]() : Promise.resolve();
}

// --- Panel de detalle ------------------------------------------------------

// Estado, etiqueta e icono. El icono importa aquí más que en ningún otro sitio: son
// cuatro botones idénticos en fila y el único que se pulsa por error es el de descartar.
const ESTADOS = [
  ['nuevo', 'Sin revisar', 'ico-punto'],
  ['vista', 'Vista', 'ico-leida'],
  ['siguiendo', 'Seguir', 'ico-ojo'],
  ['presentada', 'Presentada', 'ico-visto'],
  ['descartado', 'Descartar', 'ico-cruz'],
];

// Debe coincidir con db.MOTIVOS_DESCARTE; el servidor rechaza cualquier otro.
const MOTIVOS = [
  'fuera de nicho', 'importe bajo', 'incumbente atado',
  'fuera de plazo', 'ya presentada por otro', 'otro',
];

function pedirMotivoDescarte() {
  return new Promise((resolve) => {
    const cont = $('p-acciones');
    const caja = document.createElement('div');
    caja.className = 'acciones';
    caja.style.marginTop = '8px';
    caja.innerHTML = '<span style="font-size:12px;color:var(--texto-sec);width:100%">¿Por qué se descarta?</span>' +
      MOTIVOS.map((m) => `<button class="boton-sec" data-m="${m}">${m}</button>`).join('') +
      '<button class="boton-sec" data-m="">cancelar</button>';
    cont.after(caja);
    for (const b of caja.querySelectorAll('button')) {
      b.addEventListener('click', () => {
        caja.remove();
        resolve(b.dataset.m || null);
      });
    }
  });
}

async function abrirPanel(id) {
  const r = await fetch('/api/licitacion/' + id);
  const d = await r.json();
  if (d.error) return;
  marcarSeleccionada(id);

  const campos = [
    ['Órgano', d.organo],
    ['Expediente', d.expediente],
    ['Importe', fmtImporte(d.importe_referencia)],
    ['Fin de plazo', fmtFecha(d.fecha_limite_presentacion)],
    ['Publicada', fmtFecha(d.fecha_publicacion)],
    ['Estado', d.estado],
    ['Procedimiento', d.procedimiento],
    ['Tipo', d.tipo_contrato],
    ['Lugar', [d.lugar, d.ccaa].filter(Boolean).join(' · ')],
    ['CPV', (d.cpv || []).join(', ')],
    ['Temática', (d.categorias || []).map(nombreTema).join(' · ')],
    ['Fuente', d.fuente],
    ['Adjudicatario', d.adjudicatario],
  ].filter(([, v]) => v);

  const cont = $('panel-contenido');
  cont.innerHTML = `
    <h2></h2>
    <dl>${campos.map(([k]) => `<div class="campo"><dt>${k}</dt><dd data-c="${k}"></dd></div>`).join('')}</dl>
    <h4>Por qué ha entrado</h4>
    <div class="motivo" id="p-motivo"></div>
    <h4>Triaje</h4>
    <div class="acciones" id="p-acciones"></div>
    <textarea id="p-notas" placeholder="Notas: con quién hablar, qué preguntar, decisión tomada…"></textarea>
    <div><button class="boton-sec" id="p-guardar">Guardar notas</button><span id="p-ok" class="guardado"></span></div>
    <h4>Enlaces</h4>
    <div class="enlaces" id="p-enlaces"></div>
    <h4>Historial</h4>
    <ul class="hist" id="p-hist"></ul>`;

  cont.querySelector('h2').textContent = d.objeto || '(sin objeto)';
  const ambitoFicha = d.perfil || !TEMAS.toda_la_it ? '' : 'categoria:' + TEMAS.toda_la_it.clave;
  for (const [k, v] of campos) {
    const dd = cont.querySelector(`dd[data-c="${k}"]`);
    // El órgano y el adjudicatario llevan a su ficha. Con tus perfiles si la licitación
    // casa con alguno; si no —viene de «Otras»—, con toda la IT, que es donde la ficha
    // tiene algo que contar. Desde la ficha se puede cambiar.
    if (k === 'Órgano') dd.appendChild(enlaceFicha(v, 'organismo', v, ambitoFicha));
    else if (k === 'Adjudicatario') dd.appendChild(enlaceFicha(v, 'competidor', v, ambitoFicha));
    else dd.textContent = v;
  }
  const temas = (d.categorias || []).filter((c) => !TEMAS.resto || c !== TEMAS.resto.clave);
  $('p-motivo').textContent = d.motivo
    ? (d.perfil ? `${d.perfil.split(',').join(' · ')} — ${d.motivo}` : d.motivo)
    : temas.length
      ? 'No casa con ningún perfil activo: está en «Otras licitaciones» por su ' +
        `temática (${temas.map(nombreTema).join(' · ')}).`
      : 'Esta licitación está en la base pero no casa con ningún perfil activo.';
  if (d.descripcion) {
    const p = document.createElement('p');
    p.className = 'descripcion';
    p.textContent = d.descripcion;
    $('p-motivo').after(p);
  }

  // Acciones de triaje
  const actual = d.estado_revision || 'nuevo';
  $('p-acciones').innerHTML = ESTADOS.map(([v, t, ico]) =>
    `<button class="boton-sec ${v === actual ? 'activo' : ''}" data-e="${v}">` +
    `<svg class="ico" aria-hidden="true"><use href="#${ico}"/></svg>${t}</button>`
  ).join('');
  for (const b of $('p-acciones').querySelectorAll('button')) {
    b.addEventListener('click', async () => {
      const cambios = { estado: b.dataset.e };
      // Al descartar se pregunta por qué: es lo que permite afinar los perfiles
      // con datos en vez de a ojo.
      if (b.dataset.e === 'descartado') {
        const motivo = await pedirMotivoDescarte();
        if (motivo === null) return;
        cambios.motivo_descarte = motivo;
      }
      await guardar(id, cambios);
      abrirPanel(id);
      cargarLista();
      cargarResumen();
      // Desde «Otras», seguir o descartar saca la ficha de esa lista —seguirla la pasa a
      // la Bandeja—, así que hay que rehacerla también. Y en «Siguiendo», dejar de
      // seguirla la saca de allí.
      if (vistaActual === 'otras') cargarOtras();
      if (vistaActual === 'siguiendo') cargarSiguiendo();
    });
  }

  $('p-notas').value = d.notas || '';
  $('p-guardar').addEventListener('click', async () => {
    await guardar(id, { notas: $('p-notas').value });
    $('p-ok').textContent = 'guardado';
    setTimeout(() => ($('p-ok').textContent = ''), 1800);
  });

  const enlaces = [];
  if (d.url_detalle) enlaces.push([d.url_detalle, 'Ficha en la plataforma oficial']);
  (d.urls_pliegos || []).forEach((u, i) => enlaces.push([u, `Pliego / documento ${i + 1}`]));
  // Los enlaces se construyen por DOM y la URL se asigna TAL CUAL, como ya se hace en
  // `alternarContratos`. Aquí había un `encodeURI(u)` y rompía todos los enlaces de
  // PLACSP: sus URLs ya vienen percent-encoded del feed, y `encodeURI` no respeta el
  // `%`, así que `%3D` se volvía `%253D`. Con el `idEvl` doblemente codificado el portal
  // no resuelve el deeplink y suelta al usuario en la portada; con el `cifrado` del
  // servlet de documentos, el pliego no se descarga. La URL correcta ya está en la base:
  // lo único que hacía falta era no tocarla.
  const caja = $('p-enlaces');
  caja.textContent = '';
  if (enlaces.length) {
    for (const [u, t] of enlaces) {
      const a = document.createElement('a');
      a.href = u;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = t;
      caja.appendChild(a);
    }
  } else {
    const vacio = document.createElement('span');
    vacio.className = 'pista';
    vacio.textContent = 'Sin enlaces publicados.';
    caja.appendChild(vacio);
  }

  // La fecha del cambio es la que publica la fuente. Cuando no hay ninguna —fichas
  // guardadas antes de que se empezara a registrar— se dice que la fecha es la del día
  // en que la vio el radar, en gris, en vez de hacerla pasar por fecha oficial.
  $('p-hist').innerHTML = (d.historial || []).map((h) =>
    `<li>${h.fecha_cambio
        ? fmtFecha(h.fecha_cambio)
        : `<span style="color:var(--texto-sec)">visto el ${fmtFecha(h.detectado_en)}</span>`
      } — ${h.estado_anterior ? `${h.estado_anterior} → ` : ''}${h.estado}` +
    `${h.adjudicatario ? ` · adjudicada a ${h.adjudicatario}` : ''}</li>`
  ).join('') || '<li>Solo se ha visto una versión.</li>';

  abrirCajon();
}

async function guardar(id, cambios) {
  await fetch('/api/revision', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ licitacion_id: id, ...cambios }),
  });
}

// --- Eventos ---------------------------------------------------------------

let debounce;
$('q').addEventListener('input', () => {
  clearTimeout(debounce);
  debounce = setTimeout(() => cargarLista(), 300);
});
for (const id of ['perfil', 'estado', 'ccaa', 'importe_min', 'orden', 'vivas']) {
  $(id).addEventListener('change', () => {
    // Tocar un filtro a mano deja de corresponder a ningún contador de la cabecera.
    if (id !== 'orden') {
      kpiActivo = null;
      cierranEnDias = '';
      sinVencidas = '';
      for (const b of $('kpis').querySelectorAll('button.kpi')) b.classList.remove('activo');
    } else {
      try {
        localStorage.setItem(ORDEN_BANDEJA, $('orden').value);
      } catch { /* sin almacén, volverá al de fábrica al recargar */ }
    }
    cargarLista();
  });
}
// No quita el contador activo: ocultar lo que no tiene plazo se suma a cualquiera de ellos.
$('con-plazo').addEventListener('change', () => {
  ponerConPlazo($('con-plazo').checked);
  cargarLista();
});
$('limpiar-abrir').addEventListener('click', abrirLimpiar);
$('limpiar-cancelar').addEventListener('click', () => { $('limpiar').hidden = true; });
$('lote-deshacer').addEventListener('click', deshacerLimpieza);
$('lote-cerrar').addEventListener('click', () => { $('lote-aviso').hidden = true; });
$('mas').addEventListener('click', () => cargarLista(false));
$('cerrar').addEventListener('click', cerrarCajon);
$('panel-fondo').addEventListener('click', cerrarCajon);
for (const b of document.querySelectorAll('.tab[data-vista]')) {
  b.addEventListener('click', () => mostrarVista(b.dataset.vista));
}
$('analitica-perfil').addEventListener('change', () => {
  ambitoAnalitica = $('analitica-perfil').value;
  cargarAnalitica();
});
$('adjudicatarios-ambito').addEventListener('change', () => {
  ambitoAdjudicatarios = $('adjudicatarios-ambito').value;
  cargarAdjudicatarios();
});
$('organismos-ambito').addEventListener('change', () => {
  ambitoOrganismos = $('organismos-ambito').value;
  cargarOrganismos();
});
let debounceOrganismos;
$('organismos-q').addEventListener('input', () => {
  clearTimeout(debounceOrganismos);
  debounceOrganismos = setTimeout(() => cargarOrganismos(), 250);
});
// Cambiar el ámbito de una ficha es mirar la misma con otros ojos, no ir a otra: no se
// apila en «Volver».
for (const tipo of Object.keys(VISTAS_DETALLE)) {
  $(`${tipo}-ambito`).addEventListener('change', () => {
    if (!fichaActual) return;
    fichaActual = { ...fichaActual, ambito: $(`${tipo}-ambito`).value };
    cargarFicha();
  });
}
for (const b of document.querySelectorAll('[data-volver]')) b.addEventListener('click', volver);
let debounceOtras;
$('otras-q').addEventListener('input', () => {
  clearTimeout(debounceOtras);
  debounceOtras = setTimeout(() => cargarOtras(), 300);
});
for (const id of ['otras-ccaa', 'otras-tipo', 'otras-importe', 'otras-orden', 'otras-vivas',
                  'otras-descartadas']) {
  $(id).addEventListener('change', () => cargarOtras());
}
$('otras-mas').addEventListener('click', () => cargarOtras(false));
$('buscar-ahora').addEventListener('click', () => lanzarBusqueda());
$('arranque-entrar').addEventListener('click', cerrarArranque);
$('arranque-sin-esperar').addEventListener('click', cerrarArranque);
$('arranque-continuar').addEventListener('click', continuarArranque);
$('terminada-ver').addEventListener('click', () => {
  $('busqueda-terminada').hidden = true;
  periodoResumen = 'busqueda';
  mostrarVista('resumen');
});
$('terminada-cerrar').addEventListener('click', () => { $('busqueda-terminada').hidden = true; });
$('previsualizar').addEventListener('click', () => previsualizarAjustes());
$('guardar-perfiles').addEventListener('click', () => guardarAjustes());
$('tab-novedades').addEventListener('click', async () => {
  soloNovedades = !soloNovedades;
  $('tab-novedades').classList.toggle('activo', soloNovedades);
  mostrarVista('bandeja');
  await cargarLista();
  if (!soloNovedades) {
    // Al salir del filtro se marca la visita: lo visto deja de ser novedad.
    await fetch('/api/visita', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    cargarResumen();
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') cerrarCajon();
  // ⌘1…⌘9 cambian de vista en el orden de la barra lateral, como en Zepo Desk. Con la
  // pantalla de arranque delante no: todavía no hay nada a lo que ir.
  if ((e.metaKey || e.ctrlKey) && /^[1-9]$/.test(e.key) && !enArranque) {
    e.preventDefault();
    mostrarVista(VISTAS[Number(e.key) - 1]);
  }
});

try {
  $('con-plazo').checked = localStorage.getItem(CON_PLAZO) === '1';
} catch { /* sin almacén, se enseña todo, que es lo de fábrica */ }
try {
  const guardado = localStorage.getItem(ORDEN_BANDEJA);
  if (guardado && [...$('orden').options].some((o) => o.value === guardado)) {
    $('orden').value = guardado;
  }
} catch { /* sin almacén se abre con el de fábrica, que es lo correcto */ }

// Dentro de la app de macOS la barra de título va integrada: la clase deja libre la franja
// de arriba, que es la que la ventana usa para arrastrarse (ver `html.nativa` en styles.css).
if (ventanaNativa()) document.documentElement.classList.add('nativa');
pintarCabecera('bandeja');
// La versión, al pie de la barra lateral. No sale a internet: es la que ejecuta el servidor.
pedirJSON('/api/actualizacion/estado')
  .then((e) => { if (e && e.version) $('version-app').textContent = `Versión ${e.version}`; })
  .catch(() => {});

// La bandeja se pinta por detrás de la pantalla de arranque, con lo que ya haya en la
// base, para que al destaparla no haya que esperar a nada más.
cargarResumen();
cargarLista();
cargarTemas();
// Y `arrancar()` decide qué pasa delante: instalar la versión nueva si la hay, y
// después buscar lo nuevo y esperarlo, engancharse a la carga que ya venía de antes
// —start.command lanza las etapas caras en segundo plano y abre la aplicación acto
// seguido— o entrar directamente.
arrancar();

// --- Analítica -------------------------------------------------------------
//
// Una fila de cifras clave arriba y, debajo, una tarjeta por pregunta, cada una con la
// gráfica que pide su dato: columnas para lo que tiene orden (meses, tramos), barras para
// los rankings de nombres largos y una barra partida para el reparto de la cartera. Las
// piezas están en «Piezas de gráfica», más abajo.
//
// Regla de pintado, la misma que en `tarjeta()`: el `innerHTML` solo lleva el andamio con
// huecos numéricos o de clase CSS; los nombres de órgano y los objetos de los pliegos van
// por `textContent`, porque vienen de fuentes que no controlamos.

const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                      'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

let rangoAnalitica = 'todo';
// '' (todos los perfiles), 'perfil:…' o 'categoria:…'. Ver `ponerAmbito`.
let ambitoAnalitica = '';

// Los tres rangos. No hay selector libre de fechas a propósito: un comercial quiere «lo de
// este año», y pedir 2019 devolvería una serie de un expediente al mes que se lee como si
// el mercado se hubiera hundido. El corte en 2024 es donde el histórico deja de ser
// residual (2023 son 203 expedientes contra 931 de 2024).
function rangosAnalitica() {
  const hoy = new Date();
  const anio = hoy.getFullYear();
  const hace24 = new Date(hoy.getFullYear(), hoy.getMonth() - 23, 1);
  const mes = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  return [
    { clave: 'anio', etiqueta: String(anio), desde: `${anio}-01` },
    { clave: '24m', etiqueta: 'últimos 24 meses', desde: mes(hace24) },
    { clave: 'todo', etiqueta: 'todo desde 2024', desde: '2024-01' },
  ];
}

// `String(42.5)` da «42.5». El resto del fichero resuelve esto con
// `.toFixed(1).replace('.', ',')`; aquí se hace una vez y se reutiliza.
function fmtDecimal(v, decimales = 1) {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(decimales).replace('.', ',');
}

function fmtImporteCorto(v) {
  if (v === null || v === undefined) return 'sin dato';
  // Con separador de millar: el reparto por comunidades llega a «3.402,0 M€», y sin él
  // ese número se lee como 340 o como 34.020 según a quién se le pregunte.
  if (Math.abs(v) >= 1e6) {
    return (v / 1e6).toLocaleString('es-ES', { minimumFractionDigits: 1,
                                               maximumFractionDigits: 1 }) + ' M€';
  }
  if (Math.abs(v) >= 1000) return Math.round(v / 1000).toLocaleString('es-ES') + 'k €';
  return eur.format(v);
}

// --- Piezas de gráfica --------------------------------------------------------
//
// Cuatro piezas para toda la pestaña, con las reglas de la guía de visualización que usa
// también Zepo Desk: marcas finas (columnas de 24 px como mucho, barras de 10), esquinas
// de 4 px solo en el extremo del dato, rejilla en hilo de 1 px, el color de la serie solo
// en la marca —las cifras y las etiquetas van siempre en color de texto— y un tooltip que
// amplía pero nunca es la única forma de leer un dato: lo que dice también está escrito
// en la gráfica o en «Ver los datos».
//
// Siguen siendo `div` y no SVG, salvo la línea del año en curso: así el texto no se escala
// con la tarjeta y los dos temas salen de las variables CSS sin hacer nada.

function crear(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

const fmtEntero = (v) => Math.round(v || 0).toLocaleString('es-ES');

// Las marcas del eje: números redondos (0, 25, 50…) y no el máximo de los datos partido en
// tres, que daría rayas en 36,7 y 73,3 que nadie sabe leer.
function escalaBonita(maximo, marcas = 3) {
  if (!(maximo > 0)) return { tope: 1, paso: 1 };
  const bruto = maximo / marcas;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const paso = [1, 2, 2.5, 5, 10].map((m) => m * potencia).find((p) => p >= bruto);
  return { tope: paso * Math.ceil(maximo / paso), paso };
}

// Un solo tooltip para toda la pestaña. Va el valor primero y en grande: quien pasa el
// ratón ya sabe de qué serie es y lo que busca es el número.
let tooltipGrafica = null;

function tooltip() {
  if (!tooltipGrafica) {
    tooltipGrafica = crear('div', 'tt');
    tooltipGrafica.setAttribute('role', 'tooltip');
    tooltipGrafica.hidden = true;
    document.body.appendChild(tooltipGrafica);
    // Va fijo sobre la ventana: si la página se mueve debajo, se quedaría flotando
    // encima de otra gráfica diciendo la cifra de la de antes.
    $('cuerpo').addEventListener('scroll', () => { tooltipGrafica.hidden = true; },
                                 { passive: true });
  }
  return tooltipGrafica;
}

// `filas` es [{ valor, nombre, clase }]: la clase pinta el trazo que identifica la serie.
// Todo por `textContent`: los nombres de órgano y de empresa vienen de las fuentes.
function conTooltip(marca, titulo, filas) {
  const mostrar = () => {
    const tt = tooltip();
    tt.textContent = '';
    tt.appendChild(crear('div', 'tt-titulo', titulo));
    for (const f of filas) {
      const fila = crear('div', 'tt-fila');
      if (f.clase) fila.appendChild(crear('span', `tt-clave ${f.clase}`));
      fila.appendChild(crear('strong', '', f.valor));
      if (f.nombre) fila.appendChild(crear('span', 'tt-nombre', f.nombre));
      tt.appendChild(fila);
    }
    tt.hidden = false;
    const caja = marca.getBoundingClientRect();
    const ancho = tt.offsetWidth;
    const alto = tt.offsetHeight;
    const x = Math.min(Math.max(8, caja.left + caja.width / 2 - ancho / 2),
                       window.innerWidth - ancho - 8);
    const arriba = caja.top - alto - 8;
    tt.style.left = `${x}px`;
    tt.style.top = `${arriba > 8 ? arriba : caja.bottom + 8}px`;
  };
  const ocultar = () => { tooltip().hidden = true; };
  marca.addEventListener('pointerenter', mostrar);
  marca.addEventListener('pointerleave', ocultar);
  marca.addEventListener('focus', mostrar);
  marca.addEventListener('blur', ocultar);
  // El mismo contenido para quien no ve el tooltip.
  marca.setAttribute('aria-label',
    [titulo, ...filas.map((f) => [f.nombre, f.valor].filter(Boolean).join(': '))].join('. '));
}

// Columnas sobre una rejilla, para lo que tiene orden: los meses y los tramos. `serie2`
// es una segunda serie de la MISMA unidad que va encima como línea con puntos; nunca un
// segundo eje.
//
// `puntos`: [{ etiqueta, valor, valor2?, parcial?, titulo? }]
function columnas(puntos, { formato = fmtEntero, serie = '', serie2 = '',
                            etiquetarTodo = false } = {}) {
  const maximo = Math.max(0, ...puntos.map((p) => p.valor || 0),
                          ...puntos.map((p) => p.valor2 ?? 0));
  const { tope, paso } = escalaBonita(maximo);
  const pct = (v) => (100 * (v || 0) / tope).toFixed(2);

  const fig = crear('div', 'columnas');
  const area = crear('div', 'col-area');
  for (let v = 0; v <= tope + paso / 1000; v += paso) {
    const guia = crear('div', v === 0 ? 'col-guia base' : 'col-guia');
    guia.style.bottom = `${pct(v)}%`;
    guia.appendChild(crear('span', 'col-marca', formato(v)));
    area.appendChild(guia);
  }

  const n = puntos.length;
  const plot = crear('div', 'col-plot');
  plot.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  const capaPuntos = crear('div', 'col-plot col-puntos');
  capaPuntos.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  const linea = [];

  puntos.forEach((p, i) => {
    const col = crear('div', 'col');
    col.tabIndex = 0;
    const barra = crear('div', p.parcial ? 'col-barra parcial' : 'col-barra');
    barra.style.height = `${pct(p.valor)}%`;
    col.appendChild(barra);
    if (etiquetarTodo) {
      const cifra = crear('span', 'col-valor', formato(p.valor));
      cifra.style.bottom = `calc(${pct(p.valor)}% + 4px)`;
      col.appendChild(cifra);
    }
    plot.appendChild(col);

    const hueco = crear('div', 'col-hueco');
    if (p.valor2 !== undefined && p.valor2 !== null) {
      // El del mes en curso, hueco: su dato está a medias y no se lee como los demás.
      const punto = crear('span', p.parcial2 ? 'col-punto parcial' : 'col-punto');
      punto.style.bottom = `${pct(p.valor2)}%`;
      hueco.appendChild(punto);
      linea.push(`${i + 0.5},${(100 - pct(p.valor2)).toFixed(2)}`);
    }
    capaPuntos.appendChild(hueco);

    const filas = [{ valor: formato(p.valor), nombre: serie, clase: 'serie-1' }];
    if (p.valor2 !== undefined && p.valor2 !== null) {
      filas.push({ valor: formato(p.valor2), nombre: serie2, clase: 'serie-2' });
    }
    conTooltip(col, p.titulo || p.etiqueta, filas);
  });

  area.appendChild(plot);
  if (linea.length > 1) {
    // La única pieza en SVG: una línea que une columnas no se puede hacer con cajas. Se
    // estira con la tarjeta (`preserveAspectRatio="none"`) y el trazo no, porque
    // `vector-effect` lo deja en 2 px pase lo que pase con la escala.
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'col-linea');
    svg.setAttribute('viewBox', `0 0 ${n} 100`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('aria-hidden', 'true');
    const poli = document.createElementNS(ns, 'polyline');
    poli.setAttribute('points', linea.join(' '));
    poli.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.appendChild(poli);
    area.appendChild(svg);
  }
  if (linea.length) area.appendChild(capaPuntos);
  fig.appendChild(area);

  const ejes = crear('div', 'col-ejes');
  ejes.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  for (const p of puntos) ejes.appendChild(crear('span', '', p.etiqueta));
  fig.appendChild(ejes);
  return fig;
}

// La leyenda imita a la marca: un cuadrado para las columnas, un trazo para la línea.
function leyenda(series) {
  const caja = crear('div', 'leyenda');
  for (const s of series) {
    const item = crear('span', 'leyenda-item');
    item.appendChild(crear('span', `muestra ${s.forma || 'rect'} ${s.clase}`));
    item.appendChild(crear('span', '', s.nombre));
    caja.appendChild(item);
  }
  return caja;
}

// Una barra horizontal por fila, para los rankings: nombres largos que no caben debajo de
// una columna. `pct` es sobre el mayor de la lista y la cifra va escrita al final.
function filaBarra(etiqueta, pct, texto, opciones = {}) {
  const fila = crear('div', opciones.apilada ? 'fila-barra apilada' : 'fila-barra');
  fila.appendChild(crear('span', 'etiqueta', etiqueta));
  const carril = crear('div', 'barra');
  const relleno = crear('div', opciones.parcial ? 'barra-relleno barra-parcial' : 'barra-relleno');
  relleno.style.width = `${Math.max(0, Number(pct)).toFixed(1)}%`;
  carril.appendChild(relleno);
  fila.appendChild(carril);
  fila.appendChild(crear('span', 'valor', texto));
  conTooltip(fila, etiqueta, [{ valor: texto }]);
  // Las de órganos y empresas llevan a su ficha.
  if (opciones.alPulsar) {
    fila.classList.add('pulsable');
    fila.tabIndex = 0;
    fila.setAttribute('role', 'button');
    fila.addEventListener('click', opciones.alPulsar);
    fila.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        opciones.alPulsar();
      }
    });
  }
  return fila;
}

// Un todo partido en sus partes, con 2 px de fondo entre segmento y segmento en lugar de
// un borde. Debajo, la leyenda con la cifra y el porcentaje: el aqua sobre blanco no llega
// a 3:1 de contraste, y el número escrito es lo que lo hace legible igual.
//
// `partes`: [{ nombre, valor, clase }]
function barraApilada(partes) {
  const total = partes.reduce((s, p) => s + p.valor, 0) || 1;
  const caja = crear('div', 'apilada');
  const barra = crear('div', 'apilada-barra');
  const lista = crear('ul', 'apilada-leyenda');
  for (const p of partes) {
    if (!p.valor) continue;
    const porcentaje = `${Math.round(100 * p.valor / total)} %`;
    const seg = crear('span', `apilada-seg ${p.clase}`);
    seg.style.flexGrow = String(p.valor);
    seg.tabIndex = 0;
    conTooltip(seg, p.nombre, [{ valor: fmtEntero(p.valor), nombre: porcentaje }]);
    barra.appendChild(seg);

    const li = crear('li');
    li.appendChild(crear('span', `muestra rect ${p.clase}`));
    li.appendChild(crear('span', 'apilada-nombre', p.nombre));
    li.appendChild(crear('strong', '', fmtEntero(p.valor)));
    li.appendChild(crear('span', 'apilada-pct', porcentaje));
    lista.appendChild(li);
  }
  caja.appendChild(barra);
  caja.appendChild(lista);
  return caja;
}

// La cabecera de cada tarjeta: título, la pregunta que responde y, si la hay, la cifra que
// la responde en grande.
function bloqueAnalitica(titulo, pregunta, ancla) {
  const el = crear('section', 'bloque');
  if (ancla) el.id = `bloque-${ancla}`;
  const cab = crear('header', 'bloque-cab');
  cab.appendChild(crear('h3', '', titulo));
  cab.appendChild(crear('p', 'pregunta', pregunta));
  el.appendChild(cab);
  return el;
}

function titular(el, valor, pie) {
  const t = crear('div', 'titular');
  t.appendChild(crear('span', 'titular-valor', valor));
  if (pie) t.appendChild(crear('span', 'titular-pie', pie));
  el.appendChild(t);
  return t;
}

// Lo que se ve siempre: avisos que cambian cómo leer la gráfica.
function nota(el, texto) {
  const p = crear('p', 'nota', texto);
  el.appendChild(p);
  return p;
}

// Y lo que explica cómo se ha calculado, plegado. Antes iba todo a la vista y cada tarjeta
// eran tres párrafos de letra pequeña debajo de la gráfica: lo que quedaba era un muro de
// texto. La explicación sigue ahí para quien la busque, a un clic.
function metodo(el, titulo = 'Cómo se calcula') {
  const caja = crear('details', 'metodo');
  caja.appendChild(crear('summary', '', titulo));
  el.appendChild(caja);
  return caja;
}

function tablaEscueta(el, filas) {
  // `filas` es [[texto, cifra, apagado], …]. Las dos celdas por textContent: la primera
  // trae nombres de órgano y objetos de pliegos.
  const tabla = crear('table', 'tabla-escueta');
  for (const [texto, cifra, apagado] of filas) {
    const tr = crear('tr');
    tr.appendChild(crear('td', apagado ? 'apagado' : '', texto));
    tr.appendChild(crear('td', 'num', cifra));
    tabla.appendChild(tr);
  }
  el.appendChild(tabla);
  return tabla;
}

function insuficiente(el, minimo, que) {
  const vacio = crear('div', 'bloque-vacio');
  vacio.appendChild(crear('strong', '', `Todavía no hay ${que} suficiente`));
  vacio.appendChild(crear('span', '',
    `Hacen falta al menos ${minimo}. Para tener histórico: ` +
    'python3 radar.py ingest --primera-carga'));
  el.appendChild(vacio);
  return el;
}

// Los tramos (de importe, de baja, de días) son ordinales: columnas, y con la cifra en
// cada una, que son cinco y caben.
function etiquetaTramo(t, unidad) {
  if (t.hasta === null) return `+${unidad(t.desde)}`;
  if (t.desde === 0) return `<${unidad(t.hasta)}`;
  return `${unidad(t.desde)}–${unidad(t.hasta)}`;
}

function tituloTramo(t, unidad, prefijo = '') {
  if (t.hasta === null) return `${prefijo}más de ${unidad(t.desde)}`;
  if (t.desde === 0) return `${prefijo}hasta ${unidad(t.hasta)}`;
  return `${prefijo}entre ${unidad(t.desde)} y ${unidad(t.hasta)}`;
}

function columnasDeTramos(tramos, unidad, serie) {
  return columnas(tramos.map((t) => ({
    etiqueta: etiquetaTramo(t, unidad),
    titulo: tituloTramo(t, unidad),
    valor: t.expedientes,
  })), { serie, etiquetarTodo: true });
}

// --- Los bloques ------------------------------------------------------------------

function pintarCalendario(d) {
  const el = bloqueAnalitica('Cuándo sale el trabajo',
    '¿En qué meses tengo que estar preparado y en cuáles no pasa nada?', 'calendario');
  if (!d.suficiente) return insuficiente(el, `${d.minimo_meses} meses`, 'serie');

  const media = {};
  for (const m of d.media_por_mes) media[m.mes] = m.media;
  const hayMedia = d.media_por_mes.length > 0;
  const curso = {};
  if (d.anio_en_curso) {
    for (const m of d.meses) {
      if (m.mes.startsWith(d.anio_en_curso)) curso[m.mes.slice(5, 7)] = m.expedientes;
    }
  }
  const nombreMedia = hayMedia ? `media de ${d.anios_completos.join(' y ')}` : '';
  const nombreCurso = d.anio_en_curso || '';

  // Sin años completos la columna es el propio año en curso: no hay con qué comparar.
  const puntos = MESES_CORTOS.map((mes, i) => {
    const mm = String(i + 1).padStart(2, '0');
    const enCurso = d.mes_en_curso && d.mes_en_curso.slice(5, 7) === mm;
    return {
      etiqueta: mes + (enCurso ? '*' : ''),
      titulo: mes + (enCurso ? ' (en curso)' : ''),
      valor: hayMedia ? (media[mm] || 0) : (curso[mm] || 0),
      valor2: hayMedia ? curso[mm] : undefined,
      parcial: enCurso && !hayMedia,
      parcial2: enCurso && hayMedia,
    };
  });
  const formato = (v) => fmtDecimal(v, Number.isInteger(v) ? 0 : 1);
  el.appendChild(columnas(puntos, {
    formato,
    serie: hayMedia ? nombreMedia : nombreCurso,
    serie2: nombreCurso,
  }));
  if (hayMedia) {
    el.appendChild(leyenda([
      { nombre: nombreMedia, clase: 'serie-1' },
      { nombre: nombreCurso, clase: 'serie-2', forma: 'linea' },
    ]));
  } else {
    nota(el, 'Todavía no hay ningún año natural completo, así que lo que se ve es el año ' +
             'en curso: no hay con qué comparar.');
  }
  // El corte sale del último dato descargado, no de hoy: si nadie ingesta en una semana,
  // este número baja solo.
  if (d.mes_en_curso) {
    nota(el, `* ${MESES_CORTOS[Number(d.mes_en_curso.slice(5, 7)) - 1]} está en curso: ` +
             `datos hasta el ${fmtFecha(d.corte)} (${d.dias_con_datos} de ` +
             `${d.dias_del_mes} días), así que no entra en la media.`);
  }
  // La tabla de la gráfica, para quien no quiera ir mes a mes con el ratón.
  const datos = metodo(el, 'Ver los datos');
  tablaEscueta(datos, puntos.map((p) => [
    p.titulo,
    p.valor2 === undefined ? formato(p.valor)
      : `${formato(p.valor)} de media · ${p.valor2 ?? '—'} en ${nombreCurso}`,
  ]));
  return el;
}

function pintarImportes(d) {
  const el = bloqueAnalitica('Tamaño de los contratos',
    '¿De qué tamaño son estas operaciones, y qué me dejo fuera si filtro por importe?',
    'importes');
  titular(el, fmtImporteCorto(d.mediana),
          `de mediana · la mitad entre ${fmtImporteCorto(d.p25)} y ${fmtImporteCorto(d.p75)}`);
  el.appendChild(columnasDeTramos(d.tramos, fmtImporteCorto, 'expedientes'));
  if (d.mayores.length) {
    const mayores = crear('div', 'bloque-lista');
    mayores.appendChild(crear('h4', '', 'Los cinco mayores'));
    tablaEscueta(mayores, d.mayores.map((m) => [
      `${m.organo || '(sin órgano)'} — ${(m.objeto || '').slice(0, 70)}`,
      fmtImporteCorto(m.imp), true,
    ]));
    el.appendChild(mayores);
  }
  const m = metodo(el);
  nota(m, `${d.con_importe.toLocaleString('es-ES')} de ` +
          `${d.expedientes.toLocaleString('es-ES')} expedientes publican importe. Se toma el ` +
          'mayor importe publicado de cada uno, y no hay media ni suma: cinco contratos son ' +
          'la mitad del total y la media saldría veinte veces por encima de la mediana. Los ' +
          'cinco mayores van con nombre porque algunos están repetidos entre fuentes.');
  return el;
}

function pintarBaja(d) {
  const el = bloqueAnalitica('Importe al que se están cerrando los contratos',
    '¿Cuánto por debajo del presupuesto se están cerrando estos contratos?', 'baja');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_comparables} adjudicaciones comparables`, 'datos');
  }
  titular(el, `${fmtDecimal(d.mediana)} %`,
          `de baja mediana · sobre ${d.comparables.toLocaleString('es-ES')} adjudicaciones`);
  el.appendChild(columnasDeTramos(d.tramos, (v) => `${v} %`, 'expedientes'));
  // Lo excluido se enseña, no se esconde: es casi la mitad de la muestra.
  const m = metodo(el);
  nota(m, `De ${d.con_ambos_importes.toLocaleString('es-ES')} expedientes que publican ` +
          'presupuesto y adjudicación, se han dejado fuera:');
  tablaEscueta(m, d.excluidos.map((e) => [e.motivo, e.expedientes.toLocaleString('es-ES'), true]));
  nota(m, 'Se compara contra el presupuesto base de licitación, no contra el valor ' +
          'estimado, que incluye prórrogas y modificaciones e inflaría la baja.');
  return el;
}

function pintarPlazo(d) {
  const el = bloqueAnalitica('Cuánto tiempo tengo para presentar',
    '¿Si lo veo publicado hoy, me da tiempo a preparar la oferta?', 'plazo');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_expedientes} expedientes con plazo`, 'datos');
  }
  titular(el, `${d.mediana_dias} días`,
          `de plazo mediano · la mitad entre ${d.p25} y ${d.p75}`);
  el.appendChild(columnasDeTramos(d.tramos, (v) => `${v} d`, 'expedientes'));
  const m = metodo(el);
  nota(m, `Medido sobre ${d.expedientes.toLocaleString('es-ES')} expedientes, con las ` +
          'dos fechas tomadas del mismo anuncio. De ' +
          `${d.con_ambas_fechas.toLocaleString('es-ES')} con ambas fechas se han ` +
          'dejado fuera:');
  tablaEscueta(m, d.excluidos.map((e) => [e.motivo, e.expedientes.toLocaleString('es-ES'), true]));
  return el;
}

function pintarCiclo(d) {
  const el = bloqueAnalitica('Cuándo entra en el forecast',
    '¿Si veo esto publicado hoy, cuándo se decide?', 'ciclo');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_expedientes} expedientes con recorrido`, 'historial');
  }
  titular(el, `${d.mediana_dias} días`,
          `de la publicación a la adjudicación · la mitad entre ${d.p25} y ${d.p75}`);
  el.appendChild(columnasDeTramos(d.tramos, (v) => `${v} d`, 'expedientes'));
  const m = metodo(el);
  nota(m, `Medido sobre ${d.expedientes.toLocaleString('es-ES')} expedientes que ` +
          'recorrieron los dos hitos con fecha publicada por la fuente.');
  return el;
}

function pintarRenovaciones(d, mercado) {
  const el = bloqueAnalitica('A quién llamo antes del pliego',
    '¿Quién tiene un contrato acabándose antes de que salga el pliego nuevo?', 'renovaciones');
  titular(el, d.expedientes.toLocaleString('es-ES'),
          `contratos vencen en ${d.meses} meses · ${d.con_incumbente} con incumbente identificado`);
  // Vencimientos solo lista lo de tus perfiles: mandar ahí desde una temática del
  // mercado llevaría a una lista que no cuadra con esta cifra.
  if (!mercado) {
    const enlace = crear('button', 'boton-sec', 'Ver la lista en Vencimientos');
    enlace.addEventListener('click', () => mostrarVista('vencimientos'));
    el.appendChild(enlace);
  }
  nota(el, 'Siempre a fecha de hoy: el rango de arriba no le afecta.' +
           (mercado ? ' La pestaña Vencimientos lista solo lo de tus perfiles.' : ''));
  return el;
}

function pintarCpv(d) {
  const el = bloqueAnalitica('Qué compran exactamente',
    '¿En qué epígrafes cae mi producto, y merece la pena afinar el radar por ahí?', 'cpv');
  const tope = Math.max(1, ...d.divisiones.map((x) => x.expedientes));
  for (const x of d.divisiones) {
    // Apilada: «79 servicios para empresas y seguridad» no cabe en una columna de etiqueta.
    el.appendChild(filaBarra(`${x.division} ${x.nombre}`, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES'), { apilada: true }));
  }
  // En una temática del mercado no hay «tu producto»: el servidor manda la lista vacía.
  if (d.del_producto.length) {
    const lista = crear('div', 'bloque-lista');
    lista.appendChild(crear('h4', '', 'Los códigos que son tu producto'));
    tablaEscueta(lista, d.del_producto.map((x) => [
      `${x.codigo} · ${x.nombre}`, x.expedientes.toLocaleString('es-ES'),
    ]));
    el.appendChild(lista);
    const boton = crear('button', 'boton-sec', 'Afinar los términos de búsqueda');
    boton.addEventListener('click', () => mostrarVista('ajustes'));
    el.appendChild(boton);
  }
  const m = metodo(el);
  nota(m, 'Un expediente tiene varios CPV, así que los recuentos no suman el total y no ' +
          `se pueden repartir en porcentajes. ${d.sin_cpv} expedientes no traen ninguno.`);
  return el;
}

// Los dos repartos territoriales comparten pintado porque son el mismo gráfico con dos
// preguntas distintas: dónde se ha repartido lo ya cerrado y dónde queda dinero en juego.
function pintarComunidades(d, titulo, pregunta, ancla) {
  const el = bloqueAnalitica(titulo, pregunta, ancla);
  el.classList.add('etiquetas-anchas');
  if (!d.comunidades.length) {
    nota(el, 'No hay ningún expediente con comunidad e importe en este periodo.');
    return el;
  }
  const tope = Math.max(1, ...d.comunidades.map((c) => c.importe));
  for (const c of d.comunidades) {
    el.appendChild(filaBarra(c.ccaa, 100 * c.importe / tope,
                             `${fmtImporteCorto(c.importe)} · ${c.expedientes}`));
  }

  // Cuánto se ha quedado fuera de la escala, a la vista y en una línea: en lo que está vivo
  // son el 96 % del dinero, y callarlo dejaría un gráfico que dice que el mercado está
  // repartido cuando son cuatro plataformas de compra.
  const m = metodo(el);
  if (d.excluidos.length) {
    const n = d.excluidos.length;
    const uno = n === 1;
    const pct = Math.round(100 * d.importe_excluido / d.importe_con_excluidos);
    nota(el, `Fuera de la escala, ${uno ? 'un contrato' : `${n} contratos`} de más de ` +
             `${fmtImporteCorto(d.importe_maximo)}: con ${uno ? 'él' : 'ellos'} el total es ` +
             `${fmtImporteCorto(d.importe_con_excluidos)}, y el ${pct} % del dinero ` +
             `está ${uno ? 'en ese contrato' : `en esos ${n}`}.`);
    tablaEscueta(m, d.excluidos.map((e) => [
      `${e.ccaa} · ${(e.objeto || '(sin objeto)').slice(0, 55)} — su comunidad suma en ` +
      `realidad ${fmtImporteCorto(e.total_de_su_comunidad)}`,
      fmtImporteCorto(e.importe), true,
    ]));
    nota(m, `Se ${uno ? 'aparta' : 'apartan'} de las barras porque no son contratos sino ` +
            'continentes —sistemas dinámicos y acuerdos marco de los que se gana un lote—: ' +
            'en la misma escala, el resto de comunidades pintaría una raya de un píxel. ' +
            `Las barras suman ${fmtImporteCorto(d.importe_en_barras)}.`);
  } else {
    nota(m, `Total repartido: ${fmtImporteCorto(d.importe_con_excluidos)}. Ningún ` +
            `contrato pasa de ${fmtImporteCorto(d.importe_maximo)}, así que no se ha ` +
            'dejado nada fuera de la escala.');
  }
  nota(m, 'Cada barra es el importe y, detrás, el número de expedientes. De cada ' +
          'expediente se toma su mayor importe publicado, no la suma de sus lotes.' +
          (d.sin_comunidad
            ? ` ${d.sin_comunidad.toLocaleString('es-ES')} expedientes no traen comunidad ` +
              '—TED no publica región— y no entran en el reparto.'
            : ''));
  return el;
}

// El hermano por número. Va aparte y no como una opción de `pintarComunidades` porque
// no comparte casi nada: no hay umbral, no hay tabla de apartados y el pie dice otra cosa.
function pintarComunidadesRecuento(d, titulo, pregunta, ancla) {
  const el = bloqueAnalitica(titulo, pregunta, ancla);
  el.classList.add('etiquetas-anchas');
  if (!d.recuento.length) {
    nota(el, 'No hay ningún expediente con comunidad en este periodo.');
    return el;
  }
  const tope = Math.max(1, ...d.recuento.map((c) => c.expedientes));
  for (const c of d.recuento) {
    el.appendChild(filaBarra(c.ccaa, 100 * c.expedientes / tope,
                             c.expedientes.toLocaleString('es-ES')));
  }
  // Dos tarjetas contiguas con cifras distintas para la misma comunidad parecen un
  // fallo, así que se dice por qué no lo son.
  const m = metodo(el);
  if (d.excluidos.length) {
    const n = d.excluidos.length;
    const aparta = n === 1
      ? 'incluido el contrato que el gráfico de importe aparta'
      : `incluidos los ${n} contratos que el gráfico de importe aparta`;
    nota(m, `Aquí cuentan los ${d.expedientes_contados.toLocaleString('es-ES')} ` +
            `expedientes con comunidad, ${aparta} de su escala: un recuento no lo ` +
            'desequilibra un contrato grande, y dejarlo fuera escondería licitaciones ' +
            'a las que sí se puede ir.');
  }
  nota(m, d.sin_comunidad
    ? `${d.sin_comunidad.toLocaleString('es-ES')} expedientes no traen comunidad —TED no ` +
      'publica región— y no entran en el reparto.'
    : 'Todos los expedientes del periodo traen comunidad.');
  return el;
}

function pintarProcedimiento(d) {
  const el = bloqueAnalitica('Cómo se compra',
    '¿Por qué puerta se entra, y en cuántos casos no se puede ni pujar?', 'procedimiento');
  el.classList.add('etiquetas-anchas');
  const tope = Math.max(1, ...d.procedimientos.map((x) => x.expedientes));
  for (const x of d.procedimientos) {
    el.appendChild(filaBarra(x.procedimiento, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES')));
  }
  nota(el, 'En un negociado sin publicidad no se puja: o te han invitado o no existes. Esa ' +
           'barra es trabajo comercial de antes del pliego, no mercado al que presentarse.');
  if (d.sin_dato) {
    const m = metodo(el);
    nota(m, `${d.sin_dato.toLocaleString('es-ES')} expedientes no publican el ` +
            'procedimiento. Los nombres en catalán se cuentan con su equivalente en ' +
            'castellano.');
  }
  return el;
}

function pintarOrganos(d, mercado) {
  const el = bloqueAnalitica('Quién compra',
    '¿Qué compradores repiten, y a quién merece la pena ir a ver?', 'organos');
  const tope = Math.max(1, ...d.organos.map((x) => x.expedientes));
  for (const x of d.organos) {
    el.appendChild(filaBarra(x.organo, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES'),
                             { apilada: true,
                               alPulsar: () => abrirFicha('organismo', x.organo, ambitoAnalitica) }));
  }
  const m = metodo(el);
  nota(m, `${d.distintos.toLocaleString('es-ES')} órganos distintos han publicado algo ` +
          (mercado ? 'de esta temática' : 'que casa con el radar') +
          '; aquí están los que más repiten.');
  // Se advierte en lugar de fusionar: una regla de «nombres parecidos» junta cosas que
  // no son la misma, y aquí el coste de equivocarse lo paga quien coja el teléfono.
  nota(m, 'La fuente publica el órgano que firma, no el organismo, así que una misma ' +
          'agencia puede aparecer varias veces con firmantes distintos.');
  return el;
}

function pintarAdjudicatarios(d) {
  const el = bloqueAnalitica('Quién gana',
    '¿Qué empresas se llevan estos contratos, y contra quién voy a competir?',
    'adjudicatarios');
  if (!d.empresas.length) {
    nota(el, 'No hay ningún expediente adjudicado con empresa publicada en este periodo.');
    return el;
  }
  const tope = Math.max(1, ...d.empresas.map((x) => x.expedientes));
  for (const x of d.empresas) {
    el.appendChild(filaBarra(x.empresa, 100 * x.expedientes / tope,
                             `${x.expedientes.toLocaleString('es-ES')} · ` +
                             fmtImporteCorto(x.importe),
                             { apilada: true,
                               alPulsar: () => abrirFicha('competidor', x.empresa, ambitoAnalitica) }));
  }
  const boton = crear('button', 'boton-sec', 'Ver el ranking completo');
  boton.addEventListener('click', () => {
    // El mismo ámbito en la pestaña, para que la lista empiece por estas empresas.
    ambitoAdjudicatarios = ambitoAnalitica;
    $('adjudicatarios-ambito').value = ambitoAnalitica;
    mostrarVista('adjudicatarios');
  });
  el.appendChild(boton);
  const m = metodo(el);
  nota(m, `${d.distintas.toLocaleString('es-ES')} empresas distintas se han repartido ` +
          `${d.expedientes_adjudicados.toLocaleString('es-ES')} expedientes adjudicados. ` +
          'Cada barra es el número de expedientes y, detrás, su importe. Se cuentan ' +
          'expedientes, no anuncios, se juntan las variantes de la misma razón social y el ' +
          'importe es el mayor publicado de cada expediente.');
  return el;
}

// Los estados de la fuente, juntados en cuatro momentos de la vida de un expediente. El
// color sigue al momento y no al puesto: lo abierto es siempre el azul, aunque sea lo que
// menos haya, y lo cerrado va en gris porque es lo que menos se puede trabajar.
const MOMENTOS = [
  { clave: 'abiertas', nombre: 'Abiertas o por salir', clase: 'serie-1',
    estados: ['publicada', 'previo'] },
  { clave: 'evaluacion', nombre: 'En evaluación', clase: 'serie-2', estados: ['evaluacion'] },
  { clave: 'cerradas', nombre: 'Adjudicadas o cerradas', clase: 'serie-gris',
    estados: ['adjudicada', 'formalizada', 'resuelta'] },
  { clave: 'otras', nombre: 'Anuladas o sin estado', clase: 'serie-gris-2', estados: [] },
];

function pintarCartera(d) {
  const el = bloqueAnalitica('Qué tengo de verdad hoy',
    '¿Esto es un pipeline o un archivo histórico?', 'cartera');
  const fila = crear('div', 'cifras-fila');
  const cifras = [
    ['coincidencias', d.expedientes, ''],
    [`puntúan más de ${fmtDecimal(d.puntuacion_lista_corta)}`, d.lista_corta, ''],
    ['con plazo abierto', d.con_plazo_abierto, 'ojo'],
    ['ya cerradas o adjudicadas', d.expedientes - d.con_plazo_abierto, ''],
  ];
  for (const [etiqueta, valor, clase] of cifras) {
    const c = crear('div', clase);
    c.appendChild(crear('span', '', etiqueta));
    c.appendChild(crear('b', '', valor.toLocaleString('es-ES')));
    fila.appendChild(c);
  }
  el.appendChild(fila);

  const porMomento = Object.fromEntries(MOMENTOS.map((m) => [m.clave, 0]));
  for (const e of d.estados) {
    const momento = MOMENTOS.find((m) => m.estados.includes(e.estado)) || MOMENTOS[3];
    porMomento[momento.clave] += e.expedientes;
  }
  el.appendChild(barraApilada(MOMENTOS.map((m) => ({
    nombre: m.nombre, valor: porMomento[m.clave], clase: m.clase,
  }))));

  // La frase sale del dato: el día que esto sea un pipeline de verdad, dejará de decir
  // que es un archivo.
  nota(el, d.es_archivo_historico
    ? `De ${d.expedientes.toLocaleString('es-ES')} coincidencias, ${d.con_plazo_abierto} ` +
      'tienen el plazo abierto: esto es sobre todo un archivo histórico, y su valor está ' +
      'en los otros bloques, no en presentar ofertas hoy.'
    : `${d.con_plazo_abierto} coincidencias tienen el plazo abierto: hay pipeline vivo que ` +
      'trabajar en la bandeja.');
  const m = metodo(el, 'Ver cada estado');
  if (d.consultas_previas_sin_importe) {
    nota(m, `${d.consultas_previas_sin_importe} son consultas previas al mercado sin ` +
            'importe publicado: son la puerta de entrada antes del pliego, no operaciones.');
  }
  tablaEscueta(m, d.estados.map((e) => [e.estado, e.expedientes.toLocaleString('es-ES'), true]));
  return el;
}

// Lo que se lee primero: las cifras que responden a cada tarjeta, en una fila. Cada una
// lleva a su tarjeta, que es donde está el porqué.
function pintarCifrasClave(d) {
  const fila = crear('div', 'cifras-clave');
  // El salto es directo y no suave: medido, el desplazamiento suave de `.cuerpo` no avanza
  // en el WebKit de la app y el clic parecía no hacer nada. A cambio, la tarjeta de destino
  // se ilumina un momento, que es lo que dice adónde se ha llegado.
  const ir = (ancla) => () => {
    const destino = $(`bloque-${ancla}`);
    if (!destino) return;
    const cuerpo = $('cuerpo');
    const salto = destino.getBoundingClientRect().top - cuerpo.getBoundingClientRect().top;
    cuerpo.scrollTop += salto - 16;
    destino.classList.remove('destacado');
    void destino.offsetWidth;  // para que la animación vuelva a empezar si se repite el clic
    destino.classList.add('destacado');
  };
  const cifras = [
    ['Expedientes', d.generado_para.expedientes.toLocaleString('es-ES'),
     `${d.generado_para.anuncios.toLocaleString('es-ES')} anuncios`, 'calendario'],
    ['Importe mediano', fmtImporteCorto(d.importes.mediana),
     `la mitad entre ${fmtImporteCorto(d.importes.p25)} y ${fmtImporteCorto(d.importes.p75)}`,
     'importes'],
    d.baja.suficiente && ['Baja mediana', `${fmtDecimal(d.baja.mediana)} %`,
     'sobre el presupuesto', 'baja'],
    d.plazo.suficiente && ['Plazo para presentar', `${d.plazo.mediana_dias} días`,
     'de mediana', 'plazo'],
    d.ciclo.suficiente && ['Hasta adjudicar', `${d.ciclo.mediana_dias} días`,
     'desde la publicación', 'ciclo'],
    ['Vencen pronto', d.renovaciones.expedientes.toLocaleString('es-ES'),
     `en ${d.renovaciones.meses} meses`, 'renovaciones'],
  ].filter(Boolean);
  for (const [etiqueta, valor, pie, ancla] of cifras) {
    const b = crear('button', 'cifra-clave');
    b.appendChild(crear('span', 't', etiqueta));
    b.appendChild(crear('span', 'n', valor));
    b.appendChild(crear('span', 's', pie));
    b.addEventListener('click', ir(ancla));
    fila.appendChild(b);
  }
  return fila;
}

// Mientras llega el rango nuevo se deja el anterior a la vista, apagado, en lugar de
// vaciar la pestaña: así no salta nada de sitio y se ve qué es lo que va a cambiar.
let pasadaAnalitica = 0;

async function cargarAnalitica() {
  const pasada = ++pasadaAnalitica;
  const rango = rangosAnalitica().find((r) => r.clave === rangoAnalitica);
  const ambito = ambitoAnalitica;
  const cont = $('analitica');
  const habia = cont.querySelector('.bloque') !== null;
  const carga = habia ? null : empezarCarga('analitica', esMercado(ambito)
    ? 'Calculando sobre el histórico… la primera vez que se mira una temática tarda unos segundos'
    : 'Calculando sobre el histórico…');
  if (habia) cont.classList.add('recargando');

  $('analitica-rango').innerHTML = rangosAnalitica().map((r) =>
    `<button class="ventana ${r.clave === rangoAnalitica ? 'activa' : ''}"
             data-rango="${r.clave}"><div class="t"></div></button>`).join('');
  [...$('analitica-rango').querySelectorAll('.ventana')].forEach((b, i) => {
    b.querySelector('.t').textContent = rangosAnalitica()[i].etiqueta;
    b.addEventListener('click', () => {
      rangoAnalitica = b.dataset.rango;
      cargarAnalitica();
    });
  });

  let d;
  try {
    const p = ponerAmbito(new URLSearchParams({ desde: rango.desde }), ambito);
    d = await (await fetch('/api/analitica?' + p)).json();
  } catch {
    d = { error: 'No se pudo cargar la analítica.' };
  }
  // Si mientras tanto se ha pedido otro rango, esta respuesta ya no es la que se mira.
  if (pasada !== pasadaAnalitica) return;
  if (carga && !carga.terminar()) return;
  cont.classList.remove('recargando');
  cont.textContent = '';
  tooltip().hidden = true;
  $('analitica-resumen').textContent = '';

  if (d.error) {
    cont.appendChild(crear('p', 'vacio', d.error));
    return;
  }
  const g = d.generado_para;
  if (!g.expedientes) {
    cont.innerHTML = g.mercado
      ? `<p class="vacio">Nada de esta temática en este periodo. Si acabas de actualizar,
         las temáticas se calculan en la próxima búsqueda.</p>`
      : `<p class="vacio">Sin coincidencias en este periodo.
         Para tener histórico: <code>python3 radar.py ingest --primera-carga</code></p>`;
    return;
  }

  $('analitica-resumen').innerHTML =
    `<strong>${g.expedientes.toLocaleString('es-ES')}</strong> expedientes ` +
    `(<span id="an-anuncios"></span> anuncios) desde <span id="an-desde"></span>` +
    `<span id="an-perfil"></span>.`;
  $('an-anuncios').textContent = g.anuncios.toLocaleString('es-ES');
  $('an-desde').textContent = g.desde || 'el principio';
  // Los perfiles no suman: un 9,5 % de los expedientes casa con dos o más, así que si
  // alguien suma los filtros le sale más que el total.
  $('an-perfil').textContent = g.mercado
    ? ` · temática «${g.ambito}»: todo el mercado, case o no con tus perfiles`
    : g.perfil
      ? ` · perfil «${g.perfil}» (algunos cuentan también en otros perfiles)`
      : '';

  cont.appendChild(pintarCifrasClave(d));

  // Las filas se escriben aquí y no las decide el CSS porque el emparejado no es
  // estético: cada fila junta dos bloques que se leen del mismo tirón, y el orden es el
  // de la venta —cuándo sale, cuánto vale, a qué precio, cuánto tiempo hay, dónde está,
  // quién compra, cómo— y no el del cálculo. El calendario va solo y a lo ancho: son doce
  // meses y dos series, y en media tarjeta las columnas se quedaban en palitos.
  const filas = [
    [pintarCalendario(d.calendario)],
    [pintarImportes(d.importes), pintarBaja(d.baja)],
    [pintarPlazo(d.plazo), pintarCiclo(d.ciclo)],
    // Dinero a la izquierda y número a la derecha de la MISMA pregunta: el orden de las
    // dos listas casi nunca coincide —Cataluña es 3.ª en euros y 2.ª en operaciones, País
    // Vasco 10.ª y 6.ª— y ese desajuste es justo lo que hay que poder ver de un vistazo.
    [pintarComunidades(d.comunidades.adjudicadas,
                       'Comunidades por importe adjudicado',
                       '¿Dónde se ha repartido el dinero que ya está adjudicado?',
                       'comunidades-adjudicadas'),
     pintarComunidadesRecuento(d.comunidades.adjudicadas,
                       'Comunidades por número de adjudicaciones',
                       '¿Dónde se cierran más operaciones, cuesten lo que cuesten?')],
    [pintarComunidades(d.comunidades.activas,
                       'Comunidades por importe en juego',
                       '¿Dónde queda dinero en juego, con el plazo todavía abierto?',
                       'comunidades-activas'),
     pintarComunidadesRecuento(d.comunidades.activas,
                       'Comunidades por licitaciones abiertas',
                       '¿Dónde hay más pliegos abiertos ahora mismo?')],
    // Quién compra y quién gana, juntos: son las dos llamadas que salen de esta pestaña.
    [pintarOrganos(d.organos, g.mercado), pintarAdjudicatarios(d.adjudicatarios)],
    [pintarCpv(d.cpv), pintarProcedimiento(d.procedimiento)],
    // La cartera, con tu triaje y tus puntuaciones, solo existe para tus perfiles: con
    // una temática el servidor la manda vacía y las renovaciones se quedan solas.
    d.cartera ? [pintarRenovaciones(d.renovaciones, g.mercado), pintarCartera(d.cartera)]
              : [pintarRenovaciones(d.renovaciones, g.mercado)],
  ];
  for (const fila of filas) {
    const caja = crear('div', 'pareja');
    fila.forEach((b) => caja.appendChild(b));
    cont.appendChild(caja);
  }
}
