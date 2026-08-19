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
let kpiActivo = 'en_plazo';

// Cada contador de la cabecera y el filtro que aplica. Tiene que coincidir con lo
// que calcula consultas.resumen() o el número volvería a no cuadrar con la lista.
const KPIS = [
  { clave: 'en_plazo', etiqueta: 'abiertas', filtro: { vivas: '1' } },
  { clave: 'cierran_7_dias', etiqueta: 'cierran ≤7d', clase: 'urgente',
    filtro: { vivas: '1', cierran_en_dias: '7' } },
  { clave: 'sin_revisar', etiqueta: 'sin revisar', filtro: { vivas: '0', estado: 'nuevo' } },
  { clave: 'siguiendo', etiqueta: 'siguiendo', filtro: { vivas: '0', estado: 'siguiendo' } },
  { clave: 'coincidencias', etiqueta: 'coincidencias', filtro: { vivas: '0' } },
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
  };
}

function aplicarKpi(clave) {
  const kpi = KPIS.find((k) => k.clave === clave);
  if (!kpi) return;
  kpiActivo = clave;
  cierranEnDias = kpi.filtro.cierran_en_dias || '';
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
  soloNovedades = false;
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

  const sel = $('perfil');
  if (sel.options.length <= 1) {
    for (const p of d.por_perfil) {
      sel.add(new Option(`${p.perfil} (${p.total})`, p.perfil));
    }
  }
  const selC = $('ccaa');
  if (selC.options.length <= 1) {
    for (const c of d.ccaa) selC.add(new Option(`${c.ccaa} (${c.total})`, c.ccaa));
  }
  // El de la Analítica es otro control, no el mismo: el de arriba vive dentro de
  // #filtros, que se oculta en cualquier vista que no sea la bandeja.
  const selA = $('analitica-perfil');
  if (selA.options.length <= 1) {
    for (const p of d.por_perfil) selA.add(new Option(p.perfil, p.perfil));
  }

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

  $('salud').textContent = (d.fuentes || []).length
    ? 'Última ingesta — ' + d.fuentes.map((f) =>
        `${f.fuente}: ${f.ok ? `${f.vistos.toLocaleString('es-ES')} vistas, ${f.nuevos} nuevas` : 'error'}`
      ).join(' · ')
    : 'Sin ingestas todavía. Ejecuta: python3 radar.py ingest';
}

// --- Lista -----------------------------------------------------------------

function tarjeta(it) {
  const d = it.dias_restantes;
  let clase = '', etiqueta = '';
  if (d === null || d === undefined) {
    etiqueta = '<div class="dias"><small>sin plazo</small></div>';
  } else if (d < 0) {
    clase = 'vencido';
    etiqueta = `<div class="dias vencido">${d}<small>días</small></div>`;
  } else {
    clase = d <= 7 ? 'pronto' : '';
    etiqueta = `<div class="dias ${clase}">${d}<small>días</small></div>`;
  }

  const pills = [];
  // `perfil` puede traer varios separados por coma: una licitación de protección de
  // correo con formación casa con dos perfiles y antes salía duplicada en la lista.
  for (const p of (it.perfil || '').split(',').filter(Boolean)) {
    pills.push(`<span class="pill perfil">${p}</span>`);
  }
  pills.push(`<span class="pill importe">${fmtImporte(it.importe_referencia)}</span>`);
  if (it.fecha_limite_presentacion) {
    const c = d === null ? '' : d < 0 ? 'plazo-vencido' : d <= 7 ? 'plazo-pronto' : 'plazo-ok';
    pills.push(`<span class="pill ${c}">cierra ${fmtFecha(it.fecha_limite_presentacion)}</span>`);
  }
  if (it.ccaa) pills.push(`<span class="pill">${it.ccaa}</span>`);
  if (it.procedimiento) pills.push(`<span class="pill">${it.procedimiento}</span>`);
  pills.push(`<span class="pill">${it.fuente}</span>`);
  // Varios anuncios del mismo expediente colapsados en una fila.
  if ((it.anuncios || 1) > 1) {
    pills.push(`<span class="pill anuncios">${it.anuncios} anuncios</span>`);
  }
  if (it.adjudicatario) {
    pills.push(`<span class="pill incumbente">ganó ${it.adjudicatario.slice(0, 38)}</span>`);
  }
  if (it.estado_revision !== 'nuevo') pills.push(`<span class="pill">${it.estado_revision}</span>`);

  const el = document.createElement('article');
  el.className = `tarjeta rev-${it.estado_revision}`;
  el.dataset.id = it.id;
  el.innerHTML = `
    <div>
      <h3></h3>
      <div class="organo"></div>
    </div>
    <div class="derecha">${etiqueta}</div>
    <div class="meta">${pills.join('')}</div>`;
  // textContent para no inyectar HTML procedente de los pliegos.
  el.querySelector('h3').textContent = it.objeto || '(sin objeto)';
  el.querySelector('.organo').textContent = it.organo || '';
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
      : 'Sin coincidencias. Pulsa «Buscar ahora» para traer licitaciones.';
  }
  offset += d.items.length;
  $('mas').hidden = offset >= d.total;
  $('exportar').href = '/api/export.csv?' + query();
}

// --- Buscar ahora ----------------------------------------------------------

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
function fmtDuracion(segundos) {
  const s = Math.round(segundos || 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`;
}

// Aviso de que el histórico está entrando por detrás. Solo sale en la carga inicial:
// `detalle.etapas` es 0 en una búsqueda normal, que ya se cuenta en la cabecera y no
// merece ocupar media pantalla.
function pintarCarga(det) {
  const caja = $('carga');
  if (!det || !det.etapas) {
    caja.hidden = true;
    return;
  }
  caja.hidden = false;

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

async function lanzarBusqueda(opciones = {}) {
  const btn = $('buscar-ahora');
  const r = await fetch('/api/buscar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opciones),
  });
  const d = await r.json();
  if (!r.ok) {
    // 409 = ya hay una en marcha; no es un error, solo hay que esperarla. Pasa a
    // diario durante la carga inicial, que dura horas y tiene el cerrojo tomado.
    $('ultima-busqueda').textContent = r.status === 409
      ? 'ya se está descargando; espera a que termine'
      : (d.error || 'No se pudo lanzar la búsqueda.');
    if (r.status === 409) vigilarBusqueda();
    return;
  }
  btn.disabled = true;
  btn.textContent = 'Buscando…';
  vigilarBusqueda();
}

function vigilarBusqueda() {
  if (vigilando) return;
  const btn = $('buscar-ahora');
  seVioEnMarcha = false;
  ticsVigilando = 0;

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
      btn.disabled = true;
      btn.textContent = det && det.etapas
        ? `Carga inicial (${det.etapa}/${det.etapas})`
        : 'Buscando…';
      pintarCarga(det);
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
    btn.disabled = false;
    btn.textContent = 'Buscar ahora';
    if (seVioEnMarcha) {
      await cargarResumen();
      await cargarLista();
    }
  }, 1500);
}

// --- Vencimientos ----------------------------------------------------------

let mesesVencimiento = 6;

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
    el.querySelector('.organo').textContent = it.organo || '';
    el.querySelector('.incumbente').textContent =
      'incumbente: ' + (it.adjudicatario || 'no publicado');
    el.addEventListener('click', () => abrirPanel(it.id));
    cont.appendChild(el);
  }
}

// --- Adjudicatarios --------------------------------------------------------

async function cargarAdjudicatarios() {
  const carga = empezarCarga('lista-adjudicatarios');
  const cont = $('lista-adjudicatarios');
  let d;
  try {
    const r = await fetch('/api/adjudicatarios?limite=30');
    d = await r.json();
  } catch {
    if (carga.terminar()) {
      cont.innerHTML = '<p class="vacio">No se pudieron cargar los adjudicatarios.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;

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
    el.addEventListener('click', () => alternarContratos(el, e.empresa));
    cont.appendChild(el);
  }
}

async function alternarContratos(el, empresa) {
  const previo = el.querySelector('.contratos-empresa');
  if (previo) { previo.remove(); return; }
  const r = await fetch('/api/contratos-empresa?empresa=' + encodeURIComponent(empresa));
  const d = await r.json();
  const ul = document.createElement('ul');
  ul.className = 'contratos-empresa';
  for (const c of d.items) {
    const li = document.createElement('li');
    const fecha = c.fecha_adjudicacion ? fmtFecha(c.fecha_adjudicacion) : 's/f';
    li.textContent = `${fecha} · ${fmtImporte(c.importe)} · ${c.organo || ''} — `;
    const a = document.createElement('a');
    a.href = c.url_detalle || '#';
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = (c.objeto || '(sin objeto)').slice(0, 90);
    li.appendChild(a);
    ul.appendChild(li);
  }
  el.appendChild(ul);
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

function mostrarVista(vista) {
  for (const v of ['bandeja', 'vencimientos', 'adjudicatarios', 'analitica', 'ajustes']) {
    $('vista-' + v).hidden = v !== vista;
  }
  $('filtros').hidden = vista !== 'bandeja';
  for (const b of document.querySelectorAll('.tab[data-vista]')) {
    b.classList.toggle('activo', b.dataset.vista === vista);
  }
  if (vista === 'vencimientos') cargarVencimientos();
  if (vista === 'adjudicatarios') cargarAdjudicatarios();
  if (vista === 'analitica') cargarAnalitica();
  if (vista === 'ajustes') cargarAjustes();
}

// --- Panel de detalle ------------------------------------------------------

const ESTADOS = [
  ['nuevo', 'Sin revisar'],
  ['siguiendo', 'Seguir'],
  ['presentada', 'Presentada'],
  ['descartado', 'Descartar'],
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
  for (const [k, v] of campos) {
    cont.querySelector(`dd[data-c="${k}"]`).textContent = v;
  }
  $('p-motivo').textContent = d.motivo
    ? (d.perfil ? `${d.perfil.split(',').join(' · ')} — ${d.motivo}` : d.motivo)
    : 'Esta licitación está en la base pero no casa con ningún perfil activo.';
  if (d.descripcion) {
    const p = document.createElement('p');
    p.style.fontSize = '13px';
    p.style.color = 'var(--texto-sec)';
    p.textContent = d.descripcion;
    $('p-motivo').after(p);
  }

  // Acciones de triaje
  const actual = d.estado_revision || 'nuevo';
  $('p-acciones').innerHTML = ESTADOS.map(([v, t]) =>
    `<button class="boton-sec ${v === actual ? 'activo' : ''}" data-e="${v}">${t}</button>`
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
    vacio.style.color = 'var(--texto-sec)';
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

  $('panel').hidden = false;
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
      for (const b of $('kpis').querySelectorAll('button.kpi')) b.classList.remove('activo');
    }
    cargarLista();
  });
}
$('mas').addEventListener('click', () => cargarLista(false));
$('cerrar').addEventListener('click', () => ($('panel').hidden = true));
for (const b of document.querySelectorAll('.tab[data-vista]')) {
  b.addEventListener('click', () => mostrarVista(b.dataset.vista));
}
$('analitica-perfil').addEventListener('change', () => {
  perfilAnalitica = $('analitica-perfil').value;
  cargarAnalitica();
});
$('buscar-ahora').addEventListener('click', () => lanzarBusqueda());
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
  if (e.key === 'Escape') $('panel').hidden = true;
});

// --- Versión nueva ---------------------------------------------------------

// Solo se abre la boca si hay algo que hacer. Si no hay red, o el repositorio no tiene
// releases, se calla: un cartel de error permanente sobre algo que al usuario no le toca
// arreglar es peor que no decir nada.
async function comprobarVersion() {
  let d;
  try {
    d = await (await fetch('/api/actualizacion')).json();
  } catch {
    return;
  }
  if (!d.hay_nueva) return;

  const caja = $('aviso-version');
  caja.hidden = false;
  caja.innerHTML =
    `<p><strong>Hay una versión nueva (${d.version_nueva}).</strong> ` +
    `Tienes la ${d.version_actual}. ` +
    `<button id="actualizar-ya" class="boton-pri">Actualizar ahora</button> ` +
    `<span id="actualizar-estado" class="pista"></span></p>`;

  $('actualizar-ya').addEventListener('click', async () => {
    const btn = $('actualizar-ya');
    const estado = $('actualizar-estado');
    btn.disabled = true;
    estado.textContent = 'descargando y sustituyendo…';
    let r;
    try {
      r = await (await fetch('/api/actualizacion', { method: 'POST' })).json();
    } catch (e) {
      estado.textContent = 'no se ha podido completar; el programa sigue como estaba';
      btn.disabled = false;
      return;
    }
    // El mensaje lo redacta Python, que es quien sabe qué ha pasado de verdad y qué se
    // ha tocado. Aquí no se reinterpreta.
    estado.textContent = r.mensaje || '';
    if (r.ok && !r.sin_cambios) btn.remove();
    else btn.disabled = false;
  });
}

cargarResumen();
cargarLista();
// Al abrir puede haber ya una carga corriendo por detrás: start.command lanza las
// etapas caras en segundo plano y abre la aplicación acto seguido. Sin esto, el aviso
// no aparecería hasta que alguien pulsara «Buscar ahora».
vigilarBusqueda();
comprobarVersion();

// --- Analítica -------------------------------------------------------------
//
// Barras con divs y no con SVG: se adaptan solas a los dos temas, escalan sin JavaScript
// de redimensionado y llevan la cifra en texto al lado, que es lo que hace que el dato se
// pueda leer y no solo ver.
//
// Regla de pintado, la misma que en `tarjeta()`: el `innerHTML` solo lleva el andamio con
// huecos numéricos o de clase CSS; los nombres de órgano y los objetos de los pliegos van
// por `textContent`, porque vienen de fuentes que no controlamos.

const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                      'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

let rangoAnalitica = 'todo';
let perfilAnalitica = '';

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

function bloqueAnalitica(titulo, pregunta) {
  const el = document.createElement('section');
  el.className = 'bloque';
  el.innerHTML = '<h3></h3><p class="pregunta"></p>';
  el.querySelector('h3').textContent = titulo;
  el.querySelector('.pregunta').textContent = pregunta;
  return el;
}

// `pct` y `encima` son números y se interpolan; `etiqueta` y `texto` son texto y no.
function filaBarra(etiqueta, pct, texto, opciones = {}) {
  const fila = document.createElement('div');
  fila.className = opciones.apilada ? 'fila-barra apilada' : 'fila-barra';
  const clase = opciones.parcial ? 'barra-relleno barra-parcial' : 'barra-relleno';
  const encima = opciones.encima == null ? ''
    : `<div class="barra-encima" style="width:${Number(opciones.encima).toFixed(1)}%"></div>`;
  fila.innerHTML =
    `<span class="etiqueta"></span>` +
    `<div class="barra"><div class="${clase}" style="width:${Number(pct).toFixed(1)}%"></div>` +
    `${encima}</div><span class="valor"></span>`;
  fila.querySelector('.etiqueta').textContent = etiqueta;
  fila.querySelector('.valor').textContent = texto;
  return fila;
}

function nota(el, texto) {
  const p = document.createElement('p');
  p.className = 'nota';
  p.textContent = texto;
  el.appendChild(p);
  return p;
}

function tablaEscueta(el, filas) {
  // `filas` es [[texto, cifra], …]. Las dos celdas por textContent: la primera trae
  // nombres de órgano y objetos de pliegos.
  const tabla = document.createElement('table');
  tabla.className = 'tabla-escueta';
  for (const [texto, cifra, apagado] of filas) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td${apagado ? ' class="apagado"' : ''}></td><td class="num"></td>`;
    tr.children[0].textContent = texto;
    tr.children[1].textContent = cifra;
    tabla.appendChild(tr);
  }
  el.appendChild(tabla);
  return tabla;
}

function insuficiente(el, minimo, que) {
  nota(el, `Todavía no hay ${que} para decir nada con sentido (hacen falta al menos ` +
           `${minimo}). Para tener histórico: python3 radar.py ingest --primera-carga`);
  return el;
}

function pintarCalendario(d) {
  const el = bloqueAnalitica('Cuándo sale el trabajo',
    '¿En qué meses tengo que estar preparado y en cuáles no pasa nada?');
  if (!d.suficiente) return insuficiente(el, `${d.minimo_meses} meses`, 'serie');

  const porMes = {};
  for (const m of d.meses) porMes[m.mes] = m.expedientes;
  const media = {};
  for (const m of d.media_por_mes) media[m.mes] = m.media;

  const hayMedia = d.media_por_mes.length > 0;
  const curso = {};
  if (d.anio_en_curso) {
    for (const m of d.meses) {
      if (m.mes.startsWith(d.anio_en_curso)) curso[m.mes.slice(5, 7)] = m.expedientes;
    }
  }
  const tope = Math.max(1, ...Object.values(media), ...Object.values(curso));

  for (let i = 1; i <= 12; i++) {
    const mm = String(i).padStart(2, '0');
    const enCurso = d.mes_en_curso && d.mes_en_curso.slice(5, 7) === mm;
    const valorMedia = hayMedia ? (media[mm] || 0) : (curso[mm] || 0);
    const valorCurso = hayMedia ? curso[mm] : undefined;
    const texto = valorCurso === undefined
      ? fmtDecimal(valorMedia)
      : `${fmtDecimal(valorMedia)} · ${valorCurso}`;
    el.appendChild(filaBarra(
      MESES_CORTOS[i - 1] + (enCurso ? ' *' : ''),
      100 * valorMedia / tope,
      texto,
      { parcial: enCurso,
        encima: valorCurso === undefined ? null : 100 * valorCurso / tope },
    ));
  }

  if (hayMedia) {
    const leyenda = document.createElement('p');
    leyenda.className = 'leyenda';
    leyenda.innerHTML = '<span class="muestra media"></span> media de ' +
      '<span id="anios-media"></span> · <span class="muestra curso"></span> ' +
      '<span id="anio-curso"></span>';
    leyenda.querySelector('#anios-media').textContent = d.anios_completos.join(' y ');
    leyenda.querySelector('#anio-curso').textContent = d.anio_en_curso || '';
    el.appendChild(leyenda);
  }
  if (!hayMedia) {
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
  return el;
}

function pintarImportes(d) {
  const el = bloqueAnalitica('Tamaño de los contratos',
    '¿De qué tamaño son estas operaciones, y qué me dejo fuera si filtro por importe?');
  el.classList.add('etiquetas-medias');
  const titular = document.createElement('p');
  titular.className = 'titular';
  titular.textContent = fmtImporte(d.mediana);
  const pie = document.createElement('small');
  pie.textContent = ` de mediana · ${d.con_importe.toLocaleString('es-ES')} con importe ` +
                    `de ${d.expedientes.toLocaleString('es-ES')}`;
  titular.appendChild(pie);
  el.appendChild(titular);

  const tope = Math.max(1, ...d.tramos.map((t) => t.expedientes));
  for (const t of d.tramos) {
    const etiqueta = t.hasta === null
      ? `más de ${fmtImporteCorto(t.desde)}`
      : (t.desde === 0 ? `hasta ${fmtImporteCorto(t.hasta)}`
                       : `${fmtImporteCorto(t.desde)}–${fmtImporteCorto(t.hasta)}`);
    el.appendChild(filaBarra(etiqueta, 100 * t.expedientes / tope,
                             t.expedientes.toLocaleString('es-ES')));
  }
  if (d.mayores.length) {
    nota(el, 'Los cinco mayores, con nombre, porque son la mitad del dinero y algunos ' +
             'están repetidos entre fuentes:');
    tablaEscueta(el, d.mayores.map((m) => [
      `${m.organo || '(sin órgano)'} — ${(m.objeto || '').slice(0, 70)}`,
      fmtImporteCorto(m.imp), true,
    ]));
  }
  nota(el, 'Se muestra el mayor importe publicado de cada expediente, y no hay media ni ' +
           'suma: cinco contratos son la mitad del total y la media saldría veinte veces ' +
           'por encima de la mediana.');
  return el;
}

function pintarBaja(d) {
  const el = bloqueAnalitica('Importe al que se están cerrando los contratos',
    '¿Cuánto por debajo del presupuesto se están cerrando estos contratos?');
  el.classList.add('etiquetas-medias');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_comparables} adjudicaciones comparables`, 'datos');
  }
  const titular = document.createElement('p');
  titular.className = 'titular';
  titular.textContent = `${fmtDecimal(d.mediana)} %`;
  const pie = document.createElement('small');
  pie.textContent = ` de baja mediana · sobre ${d.comparables.toLocaleString('es-ES')} ` +
                    `adjudicaciones comparables`;
  titular.appendChild(pie);
  el.appendChild(titular);

  const tope = Math.max(1, ...d.tramos.map((t) => t.expedientes));
  for (const t of d.tramos) {
    const etiqueta = t.hasta === null ? `más del ${t.desde}%`
      : (t.desde === 0 ? `hasta ${t.hasta}%` : `${t.desde}–${t.hasta}%`);
    el.appendChild(filaBarra(etiqueta, 100 * t.expedientes / tope,
                             t.expedientes.toLocaleString('es-ES')));
  }
  // Lo excluido se enseña, no se esconde en un asterisco: es casi la mitad de la muestra.
  nota(el, `De ${d.con_ambos_importes.toLocaleString('es-ES')} expedientes que publican ` +
           'presupuesto y adjudicación, se han dejado fuera:');
  tablaEscueta(el, d.excluidos.map((e) => [e.motivo, e.expedientes.toLocaleString('es-ES'), true]));
  nota(el, 'Se compara contra el presupuesto base de licitación, no contra el valor ' +
           'estimado, que incluye prórrogas y modificaciones e inflaría la baja.');
  return el;
}

function pintarCiclo(d) {
  const el = bloqueAnalitica('Cuándo entra en el forecast',
    '¿Si veo esto publicado hoy, cuándo se decide?');
  el.classList.add('etiquetas-medias');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_expedientes} expedientes con recorrido`, 'historial');
  }
  const titular = document.createElement('p');
  titular.className = 'titular';
  titular.textContent = `${d.mediana_dias} días`;
  const pie = document.createElement('small');
  pie.textContent = ` de la publicación a la adjudicación · mitad entre ${d.p25} y ${d.p75}`;
  titular.appendChild(pie);
  el.appendChild(titular);

  const tope = Math.max(1, ...d.tramos.map((t) => t.expedientes));
  for (const t of d.tramos) {
    const etiqueta = t.hasta === null ? `más de ${t.desde} d`
      : (t.desde === 0 ? `hasta ${t.hasta} d` : `${t.desde}–${t.hasta} d`);
    el.appendChild(filaBarra(etiqueta, 100 * t.expedientes / tope,
                             t.expedientes.toLocaleString('es-ES')));
  }
  nota(el, `Medido sobre ${d.expedientes.toLocaleString('es-ES')} expedientes que ` +
           'recorrieron los dos hitos con fecha publicada por la fuente.');
  return el;
}

function pintarRenovaciones(d) {
  const el = bloqueAnalitica('A quién llamo antes del pliego',
    '¿Quién tiene un contrato acabándose antes de que salga el pliego nuevo?');
  const titular = document.createElement('p');
  titular.className = 'titular';
  titular.textContent = d.expedientes.toLocaleString('es-ES');
  const pie = document.createElement('small');
  pie.textContent = ` contratos vencen en ${d.meses} meses · ${d.con_incumbente} con ` +
                    'incumbente identificado';
  titular.appendChild(pie);
  el.appendChild(titular);
  const enlace = document.createElement('button');
  enlace.className = 'boton-sec';
  enlace.textContent = 'Ver la lista en Vencimientos';
  enlace.addEventListener('click', () => mostrarVista('vencimientos'));
  el.appendChild(enlace);
  nota(el, 'Siempre a fecha de hoy: el rango de arriba no le afecta.');
  return el;
}

function pintarCpv(d) {
  const el = bloqueAnalitica('Qué compran exactamente',
    '¿En qué epígrafes cae mi producto, y merece la pena afinar el radar por ahí?');
  const tope = Math.max(1, ...d.divisiones.map((x) => x.expedientes));
  for (const x of d.divisiones) {
    // Apilada: «79 servicios para empresas y seguridad» pide 18,7 em medidos, y en una
    // columna de ese ancho no queda barra que mirar.
    el.appendChild(filaBarra(x.division, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES'), { apilada: true }));
    // El nombre de la división va aparte: no lo trae la etiqueta.
    el.lastChild.querySelector('.etiqueta').textContent = `${x.division} ${x.nombre}`;
  }
  nota(el, 'Los tres códigos que son literalmente tu producto:');
  tablaEscueta(el, d.del_producto.map((x) => [
    `${x.codigo} · ${x.nombre}`, x.expedientes.toLocaleString('es-ES'),
  ]));
  const boton = document.createElement('button');
  boton.className = 'boton-sec';
  boton.textContent = 'Afinar los términos de búsqueda';
  boton.addEventListener('click', () => mostrarVista('ajustes'));
  el.appendChild(boton);
  nota(el, `Un expediente tiene varios CPV, así que los recuentos no suman el total y no ` +
           `se pueden repartir en porcentajes. ${d.sin_cpv} expedientes no traen ninguno.`);
  return el;
}

// Los dos repartos territoriales comparten pintado porque son el mismo gráfico con dos
// preguntas distintas: dónde se ha repartido lo ya cerrado y dónde queda dinero en juego.
function pintarComunidades(d, titulo, pregunta) {
  const el = bloqueAnalitica(titulo, pregunta);
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

  // El total con los grandes dentro va al pie, no en un asterisco: en lo que está vivo
  // son el 96% del dinero, y callarlo dejaría un gráfico que dice que el mercado está
  // repartido cuando son cuatro plataformas de compra.
  if (d.excluidos.length) {
    const n = d.excluidos.length;
    const uno = n === 1;
    const pct = Math.round(100 * d.importe_excluido / d.importe_con_excluidos);
    nota(el, `Las barras suman ${fmtImporteCorto(d.importe_en_barras)}. Contando ` +
             `${uno ? 'el contrato' : `los ${n} contratos`} de más de ` +
             `${fmtImporteCorto(d.importe_maximo)} que se ${uno ? 'deja' : 'dejan'} ` +
             `fuera de la escala, el total es ` +
             `${fmtImporteCorto(d.importe_con_excluidos)}: el ${pct}% del dinero está ` +
             `${uno ? 'en ese contrato' : `en esos ${n}`}.`);
    tablaEscueta(el, d.excluidos.map((e) => [
      `${e.ccaa} · ${(e.objeto || '(sin objeto)').slice(0, 55)} — su comunidad suma en ` +
      `realidad ${fmtImporteCorto(e.total_de_su_comunidad)}`,
      fmtImporteCorto(e.importe), true,
    ]));
    nota(el, `Se ${uno ? 'aparta' : 'apartan'} de las barras porque no son contratos ` +
             'sino continentes —sistemas dinámicos y acuerdos marco de los que se gana ' +
             'un lote—: en la misma escala, el resto de comunidades pintaría una raya ' +
             'de un píxel.');
  } else {
    nota(el, `Total repartido: ${fmtImporteCorto(d.importe_con_excluidos)}. Ningún ` +
             `contrato pasa de ${fmtImporteCorto(d.importe_maximo)}, así que no se ha ` +
             'dejado nada fuera de la escala.');
  }

  nota(el, 'De cada expediente se toma su mayor importe publicado, no la suma de sus ' +
           'lotes.' + (d.sin_comunidad
             ? ` ${d.sin_comunidad.toLocaleString('es-ES')} expedientes no traen ` +
               'comunidad —TED no publica región— y no entran en el reparto.'
             : ''));
  return el;
}

// El hermano por número. Va aparte y no como una opción de `pintarComunidades` porque
// no comparte casi nada: no hay umbral, no hay tabla de apartados y el pie dice otra cosa.
function pintarComunidadesRecuento(d, titulo, pregunta) {
  const el = bloqueAnalitica(titulo, pregunta);
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
  if (d.excluidos.length) {
    const n = d.excluidos.length;
    const aparta = n === 1
      ? 'incluido el contrato que el gráfico de importe aparta'
      : `incluidos los ${n} contratos que el gráfico de importe aparta`;
    nota(el, `Aquí cuentan los ${d.expedientes_contados.toLocaleString('es-ES')} ` +
             `expedientes con comunidad, ${aparta} de su escala: un recuento no lo ` +
             'desequilibra un contrato grande, y dejarlo fuera escondería licitaciones ' +
             'a las que sí se puede ir.');
  }
  nota(el, d.sin_comunidad
    ? `${d.sin_comunidad.toLocaleString('es-ES')} expedientes no traen comunidad —TED no ` +
      'publica región— y no entran en el reparto.'
    : 'Todos los expedientes del periodo traen comunidad.');
  return el;
}

function pintarPlazo(d) {
  const el = bloqueAnalitica('Cuánto tiempo tengo para presentar',
    '¿Si lo veo publicado hoy, me da tiempo a preparar la oferta?');
  el.classList.add('etiquetas-medias');
  if (!d.suficiente) {
    return insuficiente(el, `${d.minimo_expedientes} expedientes con plazo`, 'datos');
  }
  const titular = document.createElement('p');
  titular.className = 'titular';
  titular.textContent = `${d.mediana_dias} días`;
  const pie = document.createElement('small');
  pie.textContent = ` de plazo mediano · la mitad entre ${d.p25} y ${d.p75}`;
  titular.appendChild(pie);
  el.appendChild(titular);

  const tope = Math.max(1, ...d.tramos.map((t) => t.expedientes));
  for (const t of d.tramos) {
    const etiqueta = t.hasta === null ? `más de ${t.desde} d`
      : (t.desde === 0 ? `hasta ${t.hasta} d` : `${t.desde}–${t.hasta} d`);
    el.appendChild(filaBarra(etiqueta, 100 * t.expedientes / tope,
                             t.expedientes.toLocaleString('es-ES')));
  }
  nota(el, `Medido sobre ${d.expedientes.toLocaleString('es-ES')} expedientes, con las ` +
           'dos fechas tomadas del mismo anuncio. De ' +
           `${d.con_ambas_fechas.toLocaleString('es-ES')} con ambas fechas se han ` +
           'dejado fuera:');
  tablaEscueta(el, d.excluidos.map((e) => [
    e.motivo, e.expedientes.toLocaleString('es-ES'), true,
  ]));
  return el;
}

function pintarProcedimiento(d) {
  const el = bloqueAnalitica('Cómo se compra',
    '¿Por qué puerta se entra, y en cuántos casos no se puede ni pujar?');
  el.classList.add('etiquetas-anchas');
  const tope = Math.max(1, ...d.procedimientos.map((x) => x.expedientes));
  for (const x of d.procedimientos) {
    el.appendChild(filaBarra(x.procedimiento, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES')));
  }
  nota(el, 'En un negociado sin publicidad no se puja: o te han invitado o no existes, ' +
           'así que esa barra no es mercado al que presentarse sino trabajo comercial ' +
           'de antes del pliego.');
  if (d.sin_dato) {
    nota(el, `${d.sin_dato.toLocaleString('es-ES')} expedientes no publican el ` +
             `procedimiento. Los nombres en catalán se cuentan con su equivalente en ` +
             'castellano.');
  }
  return el;
}

function pintarOrganos(d) {
  const el = bloqueAnalitica('Quién compra',
    '¿Qué compradores repiten, y a quién merece la pena ir a ver?');
  const tope = Math.max(1, ...d.organos.map((x) => x.expedientes));
  for (const x of d.organos) {
    el.appendChild(filaBarra(x.organo, 100 * x.expedientes / tope,
                             x.expedientes.toLocaleString('es-ES'), { apilada: true }));
  }
  nota(el, `${d.distintos.toLocaleString('es-ES')} órganos distintos han publicado algo ` +
           'que casa con el radar; aquí están los que más repiten.');
  // Se advierte en lugar de fusionar: una regla de «nombres parecidos» junta cosas que
  // no son la misma, y aquí el coste de equivocarse lo paga quien coja el teléfono.
  nota(el, 'La fuente publica el órgano que firma, no el organismo, así que una misma ' +
           'agencia puede aparecer varias veces con firmantes distintos.');
  return el;
}

function pintarCartera(d) {
  const el = bloqueAnalitica('Qué tengo de verdad hoy',
    '¿Esto es un pipeline o un archivo histórico?');
  const fila = document.createElement('div');
  fila.className = 'cifras-fila';
  const cifras = [
    ['coincidencias', d.expedientes, ''],
    [`puntúan más de ${fmtDecimal(d.puntuacion_lista_corta)}`, d.lista_corta, ''],
    ['con plazo abierto', d.con_plazo_abierto, 'ojo'],
    ['ya cerradas o adjudicadas', d.expedientes - d.con_plazo_abierto, ''],
  ];
  fila.innerHTML = cifras.map(([, , clase]) =>
    `<div class="${clase}"><b></b><span></span></div>`).join('');
  cifras.forEach(([etiqueta, valor], i) => {
    fila.children[i].querySelector('b').textContent = valor.toLocaleString('es-ES');
    fila.children[i].querySelector('span').textContent = etiqueta;
  });
  el.appendChild(fila);

  // La frase sale del dato: el día que esto sea un pipeline de verdad, dejará de decir
  // que es un archivo.
  nota(el, d.es_archivo_historico
    ? `De ${d.expedientes.toLocaleString('es-ES')} coincidencias, ${d.con_plazo_abierto} ` +
      'tienen el plazo abierto: esto es sobre todo un archivo histórico, y su valor está ' +
      'en los otros bloques, no en presentar ofertas hoy.'
    : `${d.con_plazo_abierto} coincidencias tienen el plazo abierto: hay pipeline vivo que ` +
      'trabajar en la bandeja.');
  if (d.consultas_previas_sin_importe) {
    nota(el, `${d.consultas_previas_sin_importe} son consultas previas al mercado sin ` +
             'importe publicado: son la puerta de entrada antes del pliego, no operaciones.');
  }
  tablaEscueta(el, d.estados.map((e) => [e.estado, e.expedientes.toLocaleString('es-ES'), true]));
  return el;
}

async function cargarAnalitica() {
  const rango = rangosAnalitica().find((r) => r.clave === rangoAnalitica);
  const perfil = perfilAnalitica;
  const carga = empezarCarga('analitica', 'Calculando sobre el histórico…');
  // Los adornos que viven fuera del contenedor gobernado se limpian a mano: son del
  // rango anterior y dejarlos mientras carga el nuevo es peor que no mostrar nada.
  $('analitica-resumen').textContent = '';

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

  const cont = $('analitica');
  let d;
  try {
    const p = new URLSearchParams({ desde: rango.desde });
    if (perfil) p.set('perfil', perfil);
    d = await (await fetch('/api/analitica?' + p)).json();
  } catch {
    if (carga.terminar()) {
      cont.innerHTML = '<p class="vacio">No se pudo cargar la analítica.</p>';
    }
    return;
  }
  if (!carga.terminar()) return;
  if (d.error) {
    cont.innerHTML = '<p class="vacio"></p>';
    cont.firstChild.textContent = d.error;
    return;
  }
  if (!d.generado_para.expedientes) {
    cont.innerHTML = `<p class="vacio">Sin coincidencias en este periodo.
      Para tener histórico: <code>python3 radar.py ingest --primera-carga</code></p>`;
    return;
  }

  const g = d.generado_para;
  $('analitica-resumen').innerHTML =
    `<strong>${g.expedientes.toLocaleString('es-ES')}</strong> expedientes ` +
    `(<span id="an-anuncios"></span> anuncios) desde <span id="an-desde"></span>` +
    `<span id="an-perfil"></span>.`;
  $('an-anuncios').textContent = g.anuncios.toLocaleString('es-ES');
  $('an-desde').textContent = g.desde || 'el principio';
  // Los perfiles no suman: un 9,5% de los expedientes casa con dos o más, así que si
  // alguien suma los filtros le sale más que el total.
  $('an-perfil').textContent = g.perfil
    ? ` · perfil «${g.perfil}» (algunos cuentan también en otros perfiles)`
    : '';

  // Las filas se escriben aquí y no las decide el CSS porque el emparejado no es
  // estético: cada fila junta dos bloques que se leen del mismo tirón, y el orden es el
  // de la venta —cuándo sale, cuánto vale, a qué precio, cuánto tiempo hay, dónde está,
  // quién compra, cómo— y no el del cálculo. `.pareja` reparte por igual los bloques que
  // le eches, así que la fila de tres no necesita ninguna clase nueva.
  const filas = [
    [pintarCalendario(d.calendario), pintarImportes(d.importes)],
    [pintarBaja(d.baja), pintarPlazo(d.plazo)],
    // Dinero a la izquierda y número a la derecha de la MISMA pregunta: el orden de las
    // dos listas casi nunca coincide —Cataluña es 3.ª en euros y 2.ª en operaciones, País
    // Vasco 10.ª y 6.ª— y ese desajuste es justo lo que hay que poder ver de un vistazo.
    [pintarComunidades(d.comunidades.adjudicadas,
                       'Top comunidades por adjudicaciones',
                       '¿Dónde se ha repartido el dinero que ya está adjudicado?'),
     pintarComunidadesRecuento(d.comunidades.adjudicadas,
                       'Top comunidades por número total de adjudicaciones',
                       '¿Dónde se cierran más operaciones, cuesten lo que cuesten?')],
    [pintarComunidades(d.comunidades.activas,
                       'Top comunidades por licitaciones activas',
                       '¿Dónde queda dinero en juego, con el plazo todavía abierto?'),
     pintarComunidadesRecuento(d.comunidades.activas,
                       'Top comunidades por número de licitaciones activas',
                       '¿Dónde hay más pliegos abiertos ahora mismo?')],
    [pintarOrganos(d.organos), pintarCpv(d.cpv)],
    [pintarProcedimiento(d.procedimiento), pintarCiclo(d.ciclo),
     pintarRenovaciones(d.renovaciones)],
  ];
  for (const fila of filas) {
    const caja = document.createElement('div');
    caja.className = 'pareja';
    fila.forEach((b) => caja.appendChild(b));
    cont.appendChild(caja);
  }
  // Va sola y a lo ancho, y la última: es la que dice si todo lo de arriba es un
  // pipeline o un archivo histórico.
  cont.appendChild(pintarCartera(d.cartera));
}
