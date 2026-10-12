"use strict";
// Jarvis web/celular. Sin dependencias. Todo el texto se inserta con textContent (nada de innerHTML con datos).
const $ = (s) => document.querySelector(s);
const guardado = {
  leer: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  poner: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};
const E = {
  nombre: "Jarvis", voz: guardado.leer("voz", "1") === "1", estado: "reposo", pasado: [], pos: 0, borrador: "",
  escuchando: false, dictadoServidor: false, instalador: null,
  maxArchivo: 15 * 1024 * 1024, vistos: null, adjuntos: [],
  modo: "nube", papelera: { tipo: "espacio", listar: true, restaurar: true },
};
const TEXTO_ESTADO = { reposo: "En reposo", escuchando: "Te escucho…", pensando: "Pensando…", hablando: "Hablando…" };

// ------------------------------------------------------------------ tema claro / oscuro
// Sin elección guardada sigue al sistema; con el botón ☀️/🌙 se fija y se recuerda en este navegador.
function temaActual() {
  return document.documentElement.dataset.tema || (matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "oscuro");
}
function pintarTema() {
  const t = temaActual();
  $("#tema-ico use").setAttribute("href", t === "claro" ? "#i-moon" : "#i-sun");
  const txt = t === "claro" ? "Modo oscuro" : "Modo claro";
  $("#btn-tema").title = txt; $("#btn-tema").setAttribute("aria-label", txt);
  for (const m of document.querySelectorAll('meta[name="theme-color"]')) { m.removeAttribute("media"); m.content = t === "claro" ? "#f5f7fa" : "#0e1520"; }
}
$("#btn-tema").addEventListener("click", () => {
  const nuevo = temaActual() === "claro" ? "oscuro" : "claro";
  document.documentElement.dataset.tema = nuevo; guardado.poner("tema", nuevo); pintarTema();
});
pintarTema();

// ------------------------------------------------------------------ red
async function api(ruta, cuerpo, opciones = {}) {
  const r = await fetch(ruta, {
    method: cuerpo === undefined ? "GET" : "POST", credentials: "same-origin",
    headers: cuerpo === undefined || opciones.crudo ? (opciones.cabeceras || {}) : { "Content-Type": "application/json" },
    body: cuerpo === undefined ? undefined : (opciones.crudo ? cuerpo : JSON.stringify(cuerpo)),
  });
  if (r.status === 401 && ruta !== "/api/login") { mostrarLogin(); throw new Error("sin sesión"); }
  if (!r.ok) {
    let msg = ""; try { msg = (await r.json()).detail; } catch {}
    const e = new Error(msg || `Error ${r.status}`); e.status = r.status; throw e;
  }
  return r.json();
}

// ------------------------------------------------------------------ estado visual
function setEstado(e) {
  E.estado = e;
  $("#avatar").dataset.estado = e;
  $("#avatar-img").src = `/static/img/avatar_${e}.gif`;
  $("#estado-txt").textContent = TEXTO_ESTADO[e] || "";
}

function pintarVoz() {
  const b = $("#btn-voz");
  b.setAttribute("aria-pressed", String(E.voz));
  $("#voz-txt").textContent = E.voz ? "Voz activada" : "Solo escritura";
  $("#voz-ico use").setAttribute("href", E.voz ? "#i-mic" : "#i-mic-off");
  $("#btn-mic").hidden = !E.voz;
  $("#texto").placeholder = "Escribe un mensaje";
  if (!E.voz) { detenerEscucha(); callar(); }
}

// ------------------------------------------------------------------ dibujo seguro de mensajes (DOM, nunca innerHTML)
const SVGNS = "http://www.w3.org/2000/svg";
function ico(id) {
  const s = document.createElementNS(SVGNS, "svg"); s.setAttribute("class", "ico");
  const u = document.createElementNS(SVGNS, "use"); u.setAttribute("href", `#i-${id}`); s.appendChild(u); return s;
}
function el(tag, clase, texto) { const e = document.createElement(tag); if (clase) e.className = clase; if (texto !== undefined) e.textContent = texto; return e; }

async function copiar(texto) {
  try { await navigator.clipboard.writeText(texto); return true; } catch {}
  try { const t = el("textarea"); t.value = texto; t.style.position = "fixed"; t.style.opacity = "0"; document.body.appendChild(t); t.select();
        const ok = document.execCommand("copy"); t.remove(); return ok; } catch { return false; }
}

function enlace(url, texto) {
  const a = el("a", "", texto); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; return a;
}

const RE_INLINE = String.raw`(\`[^\`\n]+\`)|(\*\*[^*\n]+?\*\*)|(\*[^*\s][^*\n]*?\*)|(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))|(https?:\/\/[^\s<>]*[^\s<>.,;:!?)\]])`;
function inline(texto, padre) {
  const re = new RegExp(RE_INLINE, "g"); let ultimo = 0, m;
  while ((m = re.exec(texto))) {
    if (m.index > ultimo) padre.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
    let nodo;
    if (m[1]) nodo = el("code", "", m[1].slice(1, -1));
    else if (m[2]) { nodo = el("strong"); inline(m[2].slice(2, -2), nodo); }
    else if (m[3]) nodo = el("em", "", m[3].slice(1, -1));
    else if (m[4]) nodo = enlace(m[5], m[4].slice(1, m[4].indexOf("](")));
    else nodo = enlace(m[0], m[0]);
    padre.appendChild(nodo); ultimo = m.index + m[0].length;
  }
  if (ultimo < texto.length) padre.appendChild(document.createTextNode(texto.slice(ultimo)));
}

function bloqueCodigo(lang, codigo) {
  const caja = el("div", "codigo"), cab = el("div", "codigo-cab"), btn = el("button");
  btn.type = "button"; const rot = el("span", "", "Copiar"); btn.appendChild(ico("copy")); btn.appendChild(rot);
  btn.addEventListener("click", async () => { rot.textContent = (await copiar(codigo)) ? "Copiado" : "No se pudo copiar"; setTimeout(() => { rot.textContent = "Copiar"; }, 1600); });
  cab.appendChild(el("span", "", lang || "código")); cab.appendChild(btn);
  const pre = el("pre"); pre.appendChild(el("code", "", codigo)); caja.appendChild(cab); caja.appendChild(pre); return caja;
}

const ES_BLOQUE = /^\s*(```|#{1,4}\s|[-*\u2022]\s+|\d+[.)]\s+)/;
function dibujar(texto, cont) {      // mini-Markdown: párrafos, **negrita**, *cursiva*, `código`, bloques ```, listas, títulos, enlaces
  const ls = String(texto).replace(/\r\n/g, "\n").split("\n"); let i = 0;
  while (i < ls.length) {
    const l = ls[i], f = l.match(/^\s*```\s*([\w+#.-]*)\s*$/);
    if (f) { const c = []; i++; while (i < ls.length && !/^\s*```\s*$/.test(ls[i])) c.push(ls[i++]); i++; cont.appendChild(bloqueCodigo(f[1], c.join("\n"))); continue; }
    if (!l.trim()) { i++; continue; }
    const h = l.match(/^(#{1,4})\s+(.*)$/);
    if (h) { const t = el(h[1].length <= 2 ? "h3" : "h4"); inline(h[2], t); cont.appendChild(t); i++; continue; }
    const ul = /^\s*[-*\u2022]\s+/, ol = /^\s*\d+[.)]\s+/;
    if (ul.test(l) || ol.test(l)) {
      const re = ul.test(l) ? ul : ol, lista = el(re === ul ? "ul" : "ol");
      while (i < ls.length && re.test(ls[i])) { const li = el("li"); inline(ls[i].replace(re, ""), li); lista.appendChild(li); i++; }
      cont.appendChild(lista); continue;
    }
    const p = el("p"); let primera = true;
    while (i < ls.length && ls[i].trim() && (primera || !ES_BLOQUE.test(ls[i]))) { if (!primera) p.appendChild(el("br")); inline(ls[i], p); primera = false; i++; }
    cont.appendChild(p);
  }
}

function quitarInicio() { const x = $("#inicio"); if (x) x.remove(); $("#chat").classList.remove("vacio"); }
function mostrarInicio() {
  const chat = $("#chat"); if (chat.childElementCount) return;
  chat.classList.add("vacio");
  const d = el("div", "inicio"); d.id = "inicio";
  d.appendChild(el("h2", "", `Hola, soy ${E.nombre}`));
  d.appendChild(el("p", "", "Escríbeme, háblame o sube un archivo para que lo lea o lo edite."));
  const g = el("div", "sugerencias");
  const sug = [["Explícame qué es una inyección SQL y cómo se previene", () => enviar("Explícame qué es una inyección SQL y cómo se previene")],
               ["Crea un documento Word con un resumen de los ataques web más comunes", () => enviar("Crea un documento Word con un resumen de los ataques web más comunes")],
               ["Subir un archivo para leerlo o editarlo", () => $("#archivo").click()]];
  for (const [t, f] of sug) { const b = el("button", "", t); b.type = "button"; b.addEventListener("click", f); g.appendChild(b); }
  d.appendChild(g); chat.appendChild(d);
}

function agregar(quien, texto, fecha, error = false, adj = []) {
  quitarInicio();
  const m = el("div", "msg");
  if (quien === "aviso") { m.appendChild(el("div", error ? "nota error-nota" : "nota", texto)); }
  else if (quien === "tu") {
    m.classList.add("tu");
    if (adj.length) {                                   // lo adjuntado se ve en el mensaje (la imagen, en miniatura)
      const f = el("div", "adj-fila");
      for (const a of adj) {
        if (a.imagen) { const i = el("img"); i.src = a.url; i.alt = a.nombre; f.appendChild(i); }
        else { const c = el("span", "archivo-chip"); c.append(ico("file"), el("span", "", a.nombre)); f.appendChild(c); }
      }
      m.appendChild(f);
    }
    m.appendChild(el("div", "burbuja", texto));
    if (fecha) m.appendChild(el("time", "hora", fecha));
  } else {
    m.classList.add("ella"); const c = el("div", "cuerpo"); dibujar(texto, c); m.appendChild(c);
    if (fecha) m.appendChild(el("time", "hora", fecha));
  }
  const chat = $("#chat"); chat.appendChild(m); chat.scrollTop = chat.scrollHeight; return m;
}

function escribiendo() {
  quitarInicio();
  const m = el("div", "msg ella"), c = el("div", "cuerpo"), p = el("div", "escribiendo");
  p.setAttribute("aria-label", "Escribiendo"); p.append(el("i"), el("i"), el("i")); c.appendChild(p); m.appendChild(c);
  const chat = $("#chat"); chat.appendChild(m); chat.scrollTop = chat.scrollHeight; return m;
}

function separador(txt) { quitarInicio(); $("#chat").appendChild(el("div", "sep", txt)); }

// ------------------------------------------------------------------ voz de salida (altavoz del teléfono)
let vozElegida = null;
function elegirVoz() {
  const voces = speechSynthesis.getVoices();
  vozElegida = voces.find((v) => /^es[-_]CL/i.test(v.lang)) || voces.find((v) => /^es[-_]/i.test(v.lang)) || null;
}
if ("speechSynthesis" in window) { elegirVoz(); speechSynthesis.onvoiceschanged = elegirVoz; }

function desbloquearVoz() {   // iOS/Android solo dejan hablar si antes hubo un toque del usuario
  if (!("speechSynthesis" in window)) return;
  try { const u = new SpeechSynthesisUtterance(" "); u.volume = 0; speechSynthesis.speak(u); } catch {}
}
function callar() { if ("speechSynthesis" in window) speechSynthesis.cancel(); }

function hablar(texto) {
  return new Promise((ok) => {
    if (!("speechSynthesis" in window) || !texto) return ok();
    callar();
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = (vozElegida && vozElegida.lang) || "es-CL"; if (vozElegida) u.voice = vozElegida;
    u.rate = 1.05; u.onend = u.onerror = () => ok();
    speechSynthesis.speak(u);
  });
}

// ------------------------------------------------------------------ enviar y recibir
let ocupado = false;
async function enviar(texto) {
  texto = (texto || "").trim();
  const adj = E.adjuntos.slice();
  if ((!texto && !adj.length) || ocupado) return;
  if (!texto) texto = adj.every((a) => a.imagen) ? "Describe y analiza esta imagen." : "Léelo y dime de qué trata.";
  ocupado = true; desbloquearVoz();
  const nota = adj.length ? `Archivo adjunto: ${adj.map((a) => `"${a.nombre}"`).join("; ")}. ` : "";
  agregar("tu", texto, "", false, adj); recordar(texto); $("#texto").value = "";
  E.adjuntos = []; pintarAdjuntos();
  setEstado("pensando"); const espera = escribiendo();
  try {
    const r = await api("/api/chat", { texto: nota + texto });
    if (r.nombre && r.nombre !== E.nombre) { E.nombre = r.nombre; $("#nombre").textContent = r.nombre; }
    espera.remove();
    agregar(r.ok ? "ella" : "aviso", r.respuesta, "", !r.ok);
    await avisarArchivosNuevos();
    if (r.ok && (E.voz || $("#leer").checked)) { setEstado("hablando"); await hablar(r.respuesta); }
  } catch (e) {
    espera.remove();
    if (e.message !== "sin sesión") agregar("aviso", `No pude responder: ${e.message}`, "", true);
  } finally {
    espera.remove(); ocupado = false; setEstado("reposo");
  }
}

// ------------------------------------------------------------------ archivos (subir, descargar, borrar)
const tamano = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`;
const urlDescarga = (ruta) => `/api/archivos/descargar?ruta=${encodeURIComponent(ruta)}`;

const esImagen = (n) => /\.(png|jpe?g|gif|webp|bmp)$/i.test(n);

async function subirUno(f) {            // devuelve {nombre, bytes} o null si falló
  if (f.size > E.maxArchivo) { agregar("aviso", `${f.name} pesa ${tamano(f.size)} y el máximo es ${tamano(E.maxArchivo)}.`, "", true); return null; }
  try {
    return await api(`/api/subir?nombre=${encodeURIComponent(f.name)}`, f, { crudo: true, cabeceras: { "Content-Type": "application/octet-stream" } });
  } catch (e) { if (e.message !== "sin sesión") agregar("aviso", `No se pudo subir ${f.name}: ${e.message}`, "", true); return null; }
}

// Vista previa de lo adjuntado, ENCIMA de la caja de texto (no dentro de ella). × lo quita (y borra la copia subida).
function pintarAdjuntos() {
  const cont = $("#adjuntos"); cont.replaceChildren(); cont.hidden = !E.adjuntos.length;
  for (const a of E.adjuntos) {
    const c = el("div", a.imagen ? "adj" : "adj doc");
    if (a.imagen) { const i = el("img"); i.src = a.url; i.alt = a.nombre; c.appendChild(i); }
    else { c.appendChild(ico("file")); c.appendChild(el("span", "", a.nombre)); }
    const x = el("button", "quitar", "×"); x.type = "button"; x.setAttribute("aria-label", `Quitar ${a.nombre}`);
    x.addEventListener("click", async () => {
      E.adjuntos = E.adjuntos.filter((y) => y !== a); pintarAdjuntos();
      try { await api("/api/archivos/borrar", { ruta: a.nombre, definitivo: true }); await avisarArchivosNuevos(true); } catch (e) { /* ya no estaba */ }
    });
    c.appendChild(x); cont.appendChild(c);
  }
}

async function subirArchivos(lista, comoAdjunto = true) {
  const files = [...lista]; if (!files.length) return;
  $("#btn-adj").disabled = true; let alguno = false;
  for (const f of files) {
    const r = await subirUno(f); if (!r) continue; alguno = true;
    if (comoAdjunto) E.adjuntos.push({ nombre: r.nombre, imagen: esImagen(r.nombre), url: esImagen(r.nombre) ? URL.createObjectURL(f) : "" });
    else agregar("aviso", `Subido: ${r.nombre} (${tamano(r.bytes)})`);
  }
  $("#btn-adj").disabled = false;
  if (alguno) {
    await avisarArchivosNuevos(true);
    if (comoAdjunto) pintarAdjuntos(); else agregar("aviso", "Listo. Dime qué quieres hacer: leerlo, resumirlo, editarlo o convertirlo.");
    $("#texto").focus();
  }
}

// Después de cada respuesta: si hay archivos nuevos o cambiados (creados por ella), muestra enlaces para descargarlos.
async function avisarArchivosNuevos(soloRegistrar = false) {
  try {
    const r = await api("/api/archivos");
    const ahora = new Map(r.archivos.map((a) => [a.ruta, a.mtime]));
    if (E.vistos && !soloRegistrar) {
      const nuevos = r.archivos.filter((a) => !E.vistos.has(a.ruta) || E.vistos.get(a.ruta) !== a.mtime);
      if (nuevos.length) {
        quitarInicio();
        const m = el("div", "msg"), fila = el("div", "archivos-listos");
        for (const f of nuevos.slice(0, 6)) {
          const l = el("a", "archivo-chip"); l.href = urlDescarga(f.ruta); l.setAttribute("download", f.ruta.split("/").pop());
          l.setAttribute("aria-label", `Descargar ${f.ruta}`); l.append(ico("file"), el("span", "", f.ruta), ico("download")); fila.appendChild(l);
        }
        m.appendChild(fila); $("#chat").appendChild(m); $("#chat").scrollTop = $("#chat").scrollHeight;
      }
    }
    E.vistos = ahora;
  } catch (e) { /* sin sesión o sin servidor: no pasa nada */ }
}

async function pintarArchivos() {
  try {
    const r = await api("/api/archivos");
    $("#arch-info").textContent = r.archivos.length
      ? `${r.archivos.length} archivo${r.archivos.length === 1 ? "" : "s"}, ${tamano(r.usado)} de ${tamano(r.maximo)}. Los más nuevos primero.`
      : "Todavía no hay archivos. Sube uno con el clip o pídeme que cree uno.";
    $("#arch-borrar-todo").hidden = !r.archivos.length;
    const ul = $("#arch-lista"); ul.replaceChildren();
    for (const a of r.archivos) {
      const li = el("li"), tipo = el("div", "tipo"), cuerpo = el("div", "texto", a.ruta);
      tipo.appendChild(ico("file")); cuerpo.appendChild(el("small", "", `${tamano(a.bytes)}, ${a.fecha}`));
      const d = el("a", "descargar"); d.href = urlDescarga(a.ruta); d.setAttribute("download", a.ruta.split("/").pop()); d.setAttribute("aria-label", `Descargar ${a.ruta}`); d.appendChild(ico("download"));
      const x = el("button", "borrar"); x.type = "button"; x.setAttribute("aria-label", `Borrar ${a.ruta}`); x.appendChild(ico("trash"));
      x.addEventListener("click", async () => {
        if (!confirm(`¿Mandar ${a.ruta} a la papelera? Podrás restaurarlo desde 🗑 Papelera.`)) return;
        try { await api("/api/archivos/borrar", { ruta: a.ruta }); await pintarArchivos(); await avisarArchivosNuevos(true); } catch (e) { if (e.message !== "sin sesión") $("#arch-info").textContent = `No se pudo borrar: ${e.message}`; }
      });
      li.append(tipo, cuerpo, d, x); ul.appendChild(li);
    }
  } catch (e) { if (e.message !== "sin sesión") $("#arch-info").textContent = `No se pudieron cargar los archivos: ${e.message}`; }
}

$("#btn-adj").addEventListener("click", () => $("#archivo").click());
$("#arch-subir").addEventListener("click", () => $("#archivo").click());
$("#archivo").addEventListener("change", async (ev) => {
  const l = [...ev.target.files]; ev.target.value = "";
  const enDialogo = $("#dlg-arch").open;            // desde la ventana «Archivos» solo se sube; con el clip se adjunta al mensaje
  await subirArchivos(l, !enDialogo); if (enDialogo) pintarArchivos();
});
$("#btn-arch").addEventListener("click", () => { $("#dlg-arch").showModal(); pintarArchivos(); });
$("#arch-borrar-todo").addEventListener("click", async () => {
  if (!confirm("¿Mandar TODOS los archivos a la papelera? Podrás restaurarlos desde 🗑 Papelera.")) return;
  try { await api("/api/archivos/borrar", { todo: true }); await pintarArchivos(); await avisarArchivosNuevos(true); } catch (e) { if (e.message !== "sin sesión") $("#arch-info").textContent = `No pude borrar: ${e.message}`; }
});
// arrastrar y soltar archivos (computador)
for (const ev of ["dragenter", "dragover"]) document.addEventListener(ev, (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) { e.preventDefault(); $("#chat").classList.add("arriba"); } });
for (const ev of ["dragleave", "drop"]) document.addEventListener(ev, () => $("#chat").classList.remove("arriba"));
document.addEventListener("drop", (e) => { if (e.dataTransfer?.files?.length) { e.preventDefault(); subirArchivos(e.dataTransfer.files); } });

// ------------------------------------------------------------------ historial de pedidos (↑ ↓ y ventana)
function recordar(t) { if (t && E.pasado[E.pasado.length - 1] !== t) E.pasado.push(t); E.pos = E.pasado.length; E.borrador = ""; }

$("#texto").addEventListener("keydown", (ev) => {
  const c = ev.currentTarget;
  if (ev.key === "ArrowUp" && E.pasado.length) {
    ev.preventDefault(); if (E.pos === E.pasado.length) E.borrador = c.value;
    E.pos = Math.max(0, E.pos - 1); c.value = E.pasado[E.pos];
  } else if (ev.key === "ArrowDown" && E.pos < E.pasado.length) {
    ev.preventDefault(); E.pos++; c.value = E.pos === E.pasado.length ? E.borrador : E.pasado[E.pos];
  }
});

// ------------------------------------------------------------------ papelera
async function pintarPapelera(aviso = "") {
  const info = $("#pap-info"), ul = $("#pap-lista");
  try {
    const r = await api("/api/papelera");
    E.papelera = { tipo: r.tipo, listar: r.listar, restaurar: r.restaurar };
    ul.replaceChildren(); $("#pap-vaciar").hidden = !r.items.length;
    const donde = r.tipo === "sistema" ? "la papelera de tu computador" : "la papelera de tu espacio de archivos";
    const base = r.mensaje ? r.mensaje
      : r.items.length ? `${r.total} elemento${r.total === 1 ? "" : "s"} (${tamano(r.bytes)}) en ${donde}. Lo más reciente primero.`
      : `Está vacía (${donde}).`;
    info.textContent = aviso ? `${aviso} ${base}` : base;
    for (const a of r.items) {
      const li = el("li"), tipo = el("div", "tipo"), cuerpo = el("div", "texto", a.nombre + (a.carpeta ? "/" : ""));
      tipo.appendChild(ico(a.carpeta ? "folder" : "file"));
      cuerpo.appendChild(el("small", "", [`${a.aprox ? "más de " : ""}${tamano(a.bytes)}`, a.fecha && `borrado ${a.fecha}`, a.origen && `estaba en ${a.origen}`].filter(Boolean).join(" · ")));
      li.append(tipo, cuerpo);
      if (r.restaurar) {
        const rs = el("button", "restaurar"); rs.type = "button"; rs.title = "Restaurar"; rs.setAttribute("aria-label", `Restaurar ${a.nombre}`); rs.appendChild(ico("undo"));
        rs.addEventListener("click", async () => {
          try {
            const x = await api("/api/papelera/restaurar", { ids: [a.id] });
            await pintarPapelera(x.restaurados ? `Restaurado «${a.nombre}».` : `No pude restaurarlo: ${(x.fallos || []).join("; ") || "error"}.`);
            await avisarArchivosNuevos(true); if ($("#dlg-arch").open) pintarArchivos();
          } catch (e) { if (e.message !== "sin sesión") info.textContent = `No pude restaurar: ${e.message}`; }
        });
        li.appendChild(rs);
      }
      const x = el("button", "borrar"); x.type = "button"; x.title = "Eliminar para siempre"; x.setAttribute("aria-label", `Eliminar ${a.nombre} para siempre`); x.appendChild(ico("trash"));
      x.addEventListener("click", async () => {
        if (!confirm(`¿Eliminar «${a.nombre}» PARA SIEMPRE? No se podrá recuperar.`)) return;
        try { await api("/api/papelera/borrar", { ids: [a.id] }); await pintarPapelera(`Eliminado «${a.nombre}».`); }
        catch (e) { if (e.message !== "sin sesión") info.textContent = `No pude eliminarlo: ${e.message}`; }
      });
      li.appendChild(x); ul.appendChild(li);
    }
  } catch (e) { if (e.message !== "sin sesión") info.textContent = `No pude cargar la papelera: ${e.message}`; }
}
$("#btn-pap").addEventListener("click", () => { $("#dlg-pap").showModal(); pintarPapelera(); });
$("#pap-vaciar").addEventListener("click", async () => {
  if (!confirm("¿Vaciar la papelera? Todo lo que hay en ella se eliminará PARA SIEMPRE.")) return;
  try { const x = await api("/api/papelera/borrar", { todo: true }); await pintarPapelera(`Eliminé ${x.borrados} elemento${x.borrados === 1 ? "" : "s"} para siempre.`); }
  catch (e) { if (e.message !== "sin sesión") $("#pap-info").textContent = `No pude vaciarla: ${e.message}`; }
});

// Limpiar pantalla: oculta la conversación anterior (el historial NO se borra: sigue en 🕘 y en la memoria).
$("#btn-limpiar").addEventListener("click", async () => {
  $("#chat").replaceChildren();
  try { await api("/api/pantalla/limpiar", {}); } catch (e) { /* sin sesión ya muestra el login; sin red, igual queda limpia */ }
  mostrarInicio();
});

let temporizadorBusqueda = 0;
async function recargarChat() {          // después de borrar: vuelve a pintar la conversación y la lista de ↑ ↓
  $("#chat").replaceChildren();
  try {
    const h = await api("/api/historial?limite=120");
    if (h.mensajes.length) {
      separador("Conversación anterior");
      for (const m of h.mensajes) agregar(m.quien === "tu" ? "tu" : "ella", m.texto, m.fecha);
      separador("Ahora");
    }
    const p = await api("/api/prompts?limite=500");
    E.pasado = p.prompts.map((x) => x.texto).reverse(); E.pos = E.pasado.length;
  } catch (e) { /* sin sesión: ya se muestra el login */ }
  mostrarInicio();
}

async function borrarPedidos(cuerpo, aviso) {
  if (!confirm(`${aviso}\n\nTambién se borra la respuesta que dio. No se puede deshacer.`)) return;
  try {
    await api("/api/prompts/borrar", cuerpo);
    await recargarChat(); await cargarLista();
  } catch (e) { if (e.message !== "sin sesión") $("#hist-info").textContent = `No pude borrar: ${e.message}`; }
}

async function cargarLista() {
  const q = $("#hist-buscar").value.trim();
  try {
    const r = await api(`/api/prompts?q=${encodeURIComponent(q)}&limite=300`);
    $("#hist-info").textContent = `${r.total} pedidos${q ? " con ese texto" : ""}. Toca uno para volver a usarlo.`;
    $("#hist-borrar-q").hidden = !q || r.total === 0;
    $("#hist-borrar-q").textContent = `Borrar los ${r.total} que coinciden`;
    $("#hist-borrar-todo").hidden = !!q && r.total === 0;
    const ul = $("#hist-lista"); ul.replaceChildren();
    for (const p of r.prompts) {
      const li = document.createElement("li");
      const cuerpo = document.createElement("div"); cuerpo.className = "texto"; cuerpo.textContent = p.texto;
      const s = document.createElement("small"); s.textContent = p.fecha; cuerpo.appendChild(s);
      cuerpo.addEventListener("click", () => { $("#texto").value = p.texto; $("#dlg-hist").close(); $("#texto").focus(); });
      const x = document.createElement("button"); x.className = "borrar"; x.type = "button"; x.appendChild(ico("trash")); x.setAttribute("aria-label", "Borrar este pedido");
      x.addEventListener("click", (ev) => { ev.stopPropagation(); borrarPedidos({ ids: [p.id] }, "¿Borrar este pedido?"); });
      li.appendChild(cuerpo); li.appendChild(x); ul.appendChild(li);
    }
  } catch (e) { if (e.message !== "sin sesión") $("#hist-info").textContent = `No pude cargar el historial: ${e.message}`; }
}
$("#hist-borrar-q").addEventListener("click", () => {
  const q = $("#hist-buscar").value.trim(); if (q) borrarPedidos({ q }, `¿Borrar todos los pedidos que coinciden con "${q}"?`);
});
$("#hist-borrar-todo").addEventListener("click", () => borrarPedidos({ todo: true }, "¿Borrar TODO el historial?"));
$("#btn-hist").addEventListener("click", () => { $("#hist-buscar").value = ""; $("#dlg-hist").showModal(); cargarLista(); });
$("#hist-buscar").addEventListener("input", () => { clearTimeout(temporizadorBusqueda); temporizadorBusqueda = setTimeout(cargarLista, 250); });

// ------------------------------------------------------------------ voz de entrada (micrófono)
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let reconocedor = null, grabador = null, flujo = null, trozos = [], paraAuto = 0;

function marcarMic(activo) { E.escuchando = activo; $("#btn-mic").classList.toggle("activo", activo); setEstado(activo ? "escuchando" : (ocupado ? "pensando" : "reposo")); }

function detenerEscucha() {
  try { if (reconocedor) reconocedor.stop(); } catch {}
  try { if (grabador && grabador.state !== "inactive") grabador.stop(); } catch {}
  clearTimeout(paraAuto);
}

function escucharConNavegador() {
  reconocedor = new SR(); reconocedor.lang = "es-CL"; reconocedor.interimResults = true; reconocedor.continuous = false;
  let final = "";
  reconocedor.onresult = (ev) => {
    let parcial = "";
    for (const r of ev.results) { if (r.isFinal) final += r[0].transcript; else parcial += r[0].transcript; }
    $("#texto").value = (final + parcial).trim();
  };
  reconocedor.onerror = (ev) => {
    if (ev.error === "not-allowed" || ev.error === "service-not-allowed") agregar("aviso", "Permite el micrófono para este sitio en los ajustes del navegador.", "", true);
    else if (ev.error === "network") agregar("aviso", "El dictado del navegador necesita internet.");
  };
  reconocedor.onend = () => { marcarMic(false); reconocedor = null; if (final.trim()) enviar(final); };
  marcarMic(true); reconocedor.start();
}

async function escucharConServidor() {   // navegadores sin dictado (iPhone en algunos casos, Firefox): graba y manda el audio
  if (!E.dictadoServidor) { agregar("aviso", "Este navegador no sabe dictar y el servidor no tiene transcripción. Usa el teclado (o Chrome)."); return; }
  try { flujo = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { agregar("aviso", "Permite el micrófono para este sitio en los ajustes del navegador.", "", true); return; }
  const tipo = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
  grabador = new MediaRecorder(flujo, tipo ? { mimeType: tipo } : undefined); trozos = [];
  grabador.ondataavailable = (ev) => { if (ev.data.size) trozos.push(ev.data); };
  grabador.onstop = async () => {
    flujo.getTracks().forEach((t) => t.stop()); marcarMic(false);
    const blob = new Blob(trozos, { type: grabador.mimeType || "audio/webm" });
    if (blob.size < 1500) return;
    setEstado("pensando");
    try {
      const r = await api("/api/transcribir", blob, { crudo: true, cabeceras: { "Content-Type": blob.type } });
      if (r.texto) await enviar(r.texto); else { setEstado("reposo"); agregar("aviso", "No te escuché bien."); }
    } catch (e) { setEstado("reposo"); if (e.message !== "sin sesión") agregar("aviso", e.message); }
  };
  marcarMic(true); grabador.start();
  paraAuto = setTimeout(detenerEscucha, 20000);        // tope de 20 s
}

function alternarEscucha() {
  if (ocupado) return;
  if (E.escuchando) { detenerEscucha(); return; }
  callar(); desbloquearVoz();
  if (SR) escucharConNavegador(); else escucharConServidor();
}
$("#btn-mic").addEventListener("click", alternarEscucha);
$("#avatar").addEventListener("click", () => { if (E.voz) alternarEscucha(); else $("#texto").focus(); });

// ------------------------------------------------------------------ interruptor de voz / escritura
$("#btn-voz").addEventListener("click", () => { E.voz = !E.voz; guardado.poner("voz", E.voz ? "1" : "0"); pintarVoz(); });
$("#leer").checked = guardado.leer("leer", "0") === "1";
$("#leer").addEventListener("change", (ev) => guardado.poner("leer", ev.target.checked ? "1" : "0"));
$("#form-chat").addEventListener("submit", (ev) => { ev.preventDefault(); enviar($("#texto").value); });

// ------------------------------------------------------------------ acceso
function mostrarLogin() { $("#app").hidden = true; $("#login").hidden = false; $("#clave").focus(); }
$("#form-login").addEventListener("submit", async (ev) => {
  ev.preventDefault(); $("#login-error").textContent = "";
  try { await api("/api/login", { clave: $("#clave").value }); $("#clave").value = ""; await iniciarApp(); }
  catch (e) { if (e.message !== "sin sesión") $("#login-error").textContent = e.message; }
});

async function iniciarApp() {
  const est = await api("/api/estado");
  E.nombre = est.nombre; E.dictadoServidor = est.dictado_servidor; if (est.max_archivo) E.maxArchivo = est.max_archivo;
  E.modo = est.modo || "nube"; if (est.papelera) E.papelera = est.papelera;
  $("#app").classList.toggle("modo-pc", E.modo === "pc");
  $("#btn-pap").title = E.papelera.tipo === "sistema" ? "Papelera del computador" : "Papelera";
  const ext = (est.extensiones || []).join(","); if (ext) $("#archivo").accept = ext;
  avisarArchivosNuevos(true);
  document.title = est.nombre; $("#nombre").textContent = est.nombre;
  $("#login").hidden = true; $("#app").hidden = false;
  pintarVoz(); setEstado("reposo");
  const chat = $("#chat");
  if (!chat.childElementCount) {
    try {
      const h = await api("/api/historial?limite=120");
      if (h.mensajes.length) {
        separador("Conversación anterior");
        for (const m of h.mensajes) agregar(m.quien === "tu" ? "tu" : "ella", m.texto, m.fecha);
        separador("Ahora");
      }
      const p = await api("/api/prompts?limite=500");
      E.pasado = p.prompts.map((x) => x.texto).reverse(); E.pos = E.pasado.length;
    } catch (e) { /* sin historial no pasa nada */ }
    mostrarInicio();
  }
  abrirAtajo();
}

// Atajos de la app instalada (mantener pulsado el icono): /?abrir=papelera | archivos | historial
function abrirAtajo() {
  const quien = new URLSearchParams(location.search).get("abrir"); if (!quien) return;
  history.replaceState(null, "", location.pathname);
  const id = { papelera: "#btn-pap", archivos: "#btn-arch", historial: "#btn-hist" }[quien]; if (id) $(id).click();
}

// ------------------------------------------------------------------ sin conexión
function pintarRed() { $("#aviso-red").hidden = navigator.onLine; }
window.addEventListener("online", pintarRed); window.addEventListener("offline", pintarRed); pintarRed();

// ------------------------------------------------------------------ instalar como app
// El botón vive en su propio banner (no en la barra de herramientas) y solo aparece si la app se puede instalar y aún no lo está.
const esIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const estaInstalada = () => matchMedia("(display-mode: standalone)").matches || matchMedia("(display-mode: window-controls-overlay)").matches || navigator.standalone === true;
function instaladoCerrado() { try { return sessionStorage.getItem("instalar-cerrado") === "1"; } catch (e) { return false; } }
function pintarInstalar() {
  $("#banner-instalar").hidden = estaInstalada() || instaladoCerrado() || !(E.instalador || esIOS);
}
window.addEventListener("beforeinstallprompt", (ev) => { ev.preventDefault(); E.instalador = ev; pintarInstalar(); });
window.addEventListener("appinstalled", () => { E.instalador = null; pintarInstalar(); });
$("#btn-instalar").addEventListener("click", async () => {
  if (E.instalador) {
    E.instalador.prompt();
    try { await E.instalador.userChoice; } catch (e) { /* cerrado sin elegir */ }
    E.instalador = null; pintarInstalar();
  } else if (esIOS) {                         // iPhone/iPad no tienen diálogo propio: se muestran los pasos
    $("#ayuda-ios").hidden = false; $("#ayuda-ios").scrollIntoView({ block: "nearest" });
  }
});
$("#btn-instalar-cerrar").addEventListener("click", () => {
  try { sessionStorage.setItem("instalar-cerrado", "1"); } catch (e) { /* sin almacenamiento */ }
  $("#ayuda-ios").hidden = true; pintarInstalar();
});
pintarInstalar();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

iniciarApp().catch((e) => { if (e.message !== "sin sesión") { mostrarLogin(); $("#login-error").textContent = e.message; } });
