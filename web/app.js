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
};
const TEXTO_ESTADO = { reposo: "En reposo", escuchando: "Te escucho…", pensando: "Pensando…", hablando: "Hablando…" };

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
  b.textContent = E.voz ? "🎙️ Voz: activada" : "🔇 Voz apagada · solo escritura";
  $("#btn-mic").hidden = !E.voz;
  $("#texto").placeholder = E.voz ? "Háblame, o escribe aquí…" : "Escribe aquí…";
  if (!E.voz) { detenerEscucha(); callar(); }
}

function agregar(quien, texto, fecha) {
  const p = document.createElement("p");
  if (quien === "aviso") {
    p.className = "msg aviso-msg"; p.textContent = texto;
  } else {
    p.className = `msg ${quien}`;
    const b = document.createElement("b"); b.textContent = quien === "tu" ? "Tú" : E.nombre;
    if (fecha) { const t = document.createElement("time"); t.textContent = fecha; b.appendChild(t); }
    p.appendChild(b); p.appendChild(document.createTextNode(texto));
  }
  const chat = $("#chat"); chat.appendChild(p); chat.scrollTop = chat.scrollHeight;
}

function separador(txt) {
  const p = document.createElement("p"); p.className = "sep"; p.textContent = txt; $("#chat").appendChild(p);
}

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
  if (!texto || ocupado) return;
  ocupado = true; desbloquearVoz();
  agregar("tu", texto); recordar(texto); $("#texto").value = "";
  setEstado("pensando");
  try {
    const r = await api("/api/chat", { texto });
    if (r.nombre && r.nombre !== E.nombre) { E.nombre = r.nombre; $("#nombre").textContent = r.nombre; }
    agregar(r.ok ? "ella" : "aviso", r.respuesta);
    if (r.ok && (E.voz || $("#leer").checked)) { setEstado("hablando"); await hablar(r.respuesta); }
  } catch (e) {
    if (e.message !== "sin sesión") agregar("aviso", `No pude responder: ${e.message}`);
  } finally {
    ocupado = false; setEstado("reposo");
  }
}

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

let temporizadorBusqueda = 0;
async function cargarLista() {
  const q = $("#hist-buscar").value.trim();
  try {
    const r = await api(`/api/prompts?q=${encodeURIComponent(q)}&limite=300`);
    $("#hist-info").textContent = `${r.total} pedidos${q ? " con ese texto" : ""} · toca uno para volver a usarlo`;
    const ul = $("#hist-lista"); ul.replaceChildren();
    for (const p of r.prompts) {
      const li = document.createElement("li"); li.textContent = p.texto;
      const s = document.createElement("small"); s.textContent = p.fecha; li.appendChild(s);
      li.addEventListener("click", () => { $("#texto").value = p.texto; $("#dlg-hist").close(); $("#texto").focus(); });
      ul.appendChild(li);
    }
  } catch (e) { if (e.message !== "sin sesión") $("#hist-info").textContent = `No pude cargar el historial: ${e.message}`; }
}
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
    if (ev.error === "not-allowed" || ev.error === "service-not-allowed") agregar("aviso", "Permite el micrófono para este sitio en los ajustes del navegador.");
    else if (ev.error === "network") agregar("aviso", "El dictado del navegador necesita internet.");
  };
  reconocedor.onend = () => { marcarMic(false); reconocedor = null; if (final.trim()) enviar(final); };
  marcarMic(true); reconocedor.start();
}

async function escucharConServidor() {   // navegadores sin dictado (iPhone en algunos casos, Firefox): graba y manda el audio
  if (!E.dictadoServidor) { agregar("aviso", "Este navegador no sabe dictar y el servidor no tiene transcripción. Usa el teclado (o Chrome)."); return; }
  try { flujo = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch { agregar("aviso", "Permite el micrófono para este sitio en los ajustes del navegador."); return; }
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
  E.nombre = est.nombre; E.dictadoServidor = est.dictado_servidor;
  document.title = est.nombre; $("#nombre").textContent = est.nombre;
  $("#login").hidden = true; $("#app").hidden = false;
  pintarVoz(); setEstado("reposo");
  const chat = $("#chat");
  if (!chat.childElementCount) {
    try {
      const h = await api("/api/historial?limite=120");
      if (h.mensajes.length) {
        separador(`— conversación anterior (${h.mensajes.length} mensajes; «📜 Historial» muestra todo lo que has pedido) —`);
        for (const m of h.mensajes) agregar(m.quien === "tu" ? "tu" : "ella", m.texto, m.fecha);
        separador("— ahora —");
      }
      const p = await api("/api/prompts?limite=500");
      E.pasado = p.prompts.map((x) => x.texto).reverse(); E.pos = E.pasado.length;
    } catch (e) { /* sin historial no pasa nada */ }
  }
}

// ------------------------------------------------------------------ instalar como app
window.addEventListener("beforeinstallprompt", (ev) => { ev.preventDefault(); E.instalador = ev; $("#btn-instalar").hidden = false; });
$("#btn-instalar").addEventListener("click", async () => {
  if (!E.instalador) return; E.instalador.prompt(); await E.instalador.userChoice; E.instalador = null; $("#btn-instalar").hidden = true;
});
window.addEventListener("appinstalled", () => { $("#btn-instalar").hidden = true; });
const esIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
const instalada = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
if (esIOS && !instalada) $("#ayuda-ios").hidden = false;

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});

iniciarApp().catch((e) => { if (e.message !== "sin sesión") { mostrarLogin(); $("#login-error").textContent = e.message; } });
