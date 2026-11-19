"""Aceptación obligatoria del Aviso de Privacidad y de los términos de uso, y declaración del cliente antes de cargar información de terceros — Asistente y Validador de Migración · SINCO A&F.

Dos controles, los dos APAGADOS por defecto (se encienden en los Secrets de Streamlit; apagarlos es volver atrás)
-------------------------------------------------------------------------------------------------------------
1. PANTALLA DE INGRESO  ([consentimiento] activo = true). Sin aceptar no se llega a ninguna etapa (el código corre en el servidor; no se salta desde el navegador).
   Paso 1: el correo. Si ese correo ya aceptó la versión vigente del Aviso Y de los términos, entra directo. Si no, paso 2: nombre, empresa o NIT, las dos casillas (desmarcadas) —el Aviso de Privacidad y los
   términos de uso— y el botón ACEPTAR Y CONTINUAR (deshabilitado hasta marcar las dos). La evidencia (quién, cuándo, cada casilla, versión del aviso, versión de los términos y versión de la app) se guarda en
   Supabase con registrar_aceptacion(). Si no se puede guardar o verificar, NO se deja entrar: mensaje claro y botón de reintentar. Si cambia la versión del aviso o de los términos, se vuelve a pedir.
2. DECLARACIÓN DEL CLIENTE  ([consentimiento] declaracion_cliente = true, además de activo = true). UNA vez por etapa y por sesión, antes de la primera carga de información de terceros, hay que marcar la
   declaración (el cliente es Responsable, tiene la autorización de los titulares, instruye a SINCOSOFT como Encargado). Hasta marcarla, los cargadores de archivos con terceros o NIT quedan deshabilitados.
   Cada declaración se guarda en Supabase con registrar_declaracion_cliente() (correo, etapa, versión del texto y versión de la app); si no se puede guardar, no se habilitan los cargadores (reintentar).

Qué NO es: no es un inicio de sesión ni verifica que el correo sea de quien lo escribe; deja constancia de la aceptación asociada a un correo.

Configuración (Secrets de Streamlit; sin valores secretos aquí):
    [consentimiento]
    activo = true
    aviso_version = "1.0"                         # obligatoria (la define jurídica; el aviso trae la vigencia en blanco)
    aviso_fecha = "dd/mm/aaaa"                    # opcional: fecha de vigencia
    aviso_url = "https://..."                     # el enlace del aviso ... o  aviso_texto = \"\"\"...\"\"\"  ... o  aviso_archivo = "otro.md"
                                                  # Si no se pone ninguno, se usa el archivo aviso_privacidad.md que va junto a la app.
    terminos_version = "1.0"                      # obligatoria
    terminos_url = "https://..."                  # el enlace de los términos ... o  terminos_texto = \"\"\"...\"\"\"  (hace falta al menos uno)
    terminos_fecha = "dd/mm/aaaa"                 # opcional
    declaracion_cliente = true                    # opcional: enciende la declaración del cliente antes de cargar terceros
Supabase se toma de la sección [seguimiento] (url y clave_publica), la misma que usa el seguimiento.
"""
import hashlib
import html
import json
import os
import re

import streamlit as st

# ── Documentos ──
AVISO_TITULO = "Aviso de Privacidad y de Tratamiento de Datos Personales"
AVISO_PLATAFORMA = "PLATAFORMA DE PARAMETRIZACIÓN, MIGRACIÓN Y VALIDACIÓN DE INFORMACIÓN CONTABLE"
AVISO_ARCHIVO_POR_DEFECTO = "aviso_privacidad.md"          # el aviso de Andrea convertido de Word (va junto a la app)
POLITICA_URL = "https://www.sinco.co/pol%C3%ADtica-de-tratamiento-y-procedimiento-para-la-protecci%C3%B3n-de-datos-personales"       # solo informativa (el aviso la cita en su apartado 7)
POLITICA_NOMBRE = "Política de Tratamiento de Datos Personales de SINCOSOFT S.A.S."
POLITICA_VERSION_INFORMATIVA = "002 · 10/09/2025"            # según la tabla «Control de cambios» de la página; es informativa: NO forma parte de la evidencia
SITIO_URL = "https://www.sinco.co/"

# ── Textos dados por Andrea (el área jurídica debe revisarlos antes de publicar) ──
TEXTO_AVISO = ("He leído el Aviso de Privacidad de PLATAFORMA DE PARAMETRIZACIÓN, MIGRACIÓN Y VALIDACIÓN DE INFORMACIÓN CONTABLE y autorizo a SINCOSOFT S.A.S., NIT 830.021.894-9, "
               "para tratar mis datos personales como usuario de la plataforma, con las finalidades allí descritas. Conozco que puedo conocer, actualizar, rectificar y suprimir mis datos "
               "y revocar esta autorización a través de datos_personales@sinco.co.")
TEXTO_TERMINOS = "He leído y acepto los términos y condiciones de uso de la aplicación Asistente y Validador de Migración – SINCO A&F."
TEXTO_DECLARACION = ("Declaro, que la empresa a la que represento es Responsable del Tratamiento de los datos personales contenidos en este archivo, que cuenta con la autorización de sus titulares "
                     "o con una causal legal que la exime de obtenerla, y que instruye a SINCOSOFT S.A.S., como Encargado, para tratarlos únicamente con las finalidades de parametrización, "
                     "migración, carga de saldos y validación contable del sistema contratado.")
TIMEOUT_SEG = 5

_RE_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def version_declaracion():
    """La versión de la declaración es la huella de su texto: si el texto cambia, cambia sola (y queda en la evidencia)."""
    return hashlib.sha256(TEXTO_DECLARACION.encode("utf-8")).hexdigest()[:8]


# ───────────────────────── configuración ─────────────────────────
def _secreto(seccion):
    try:
        valor = st.secrets.get(seccion, {})
        return dict(valor) if valor else {}
    except Exception:
        return {}


def _verdadero(v):
    return str(v).strip().lower() in ("true", "1", "si", "sí", "yes")


def activo(cfg=None):
    """True si la pantalla de ingreso está encendida en los Secrets."""
    return _verdadero((_secreto("consentimiento") if cfg is None else cfg).get("activo"))


def declaracion_activa(cfg=None):
    """True si, además de la pantalla de ingreso, está encendida la declaración del cliente antes de cargar terceros."""
    cfg = _secreto("consentimiento") if cfg is None else cfg
    return _verdadero(cfg.get("activo")) and _verdadero(cfg.get("declaracion_cliente"))


def _leer_archivo_aviso(nombre):
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), nombre), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def configuracion(cfg=None, seg=None):
    """(datos, faltantes). 'datos' trae las versiones y los documentos vigentes; 'faltantes' dice qué falta configurar (lista vacía = todo listo)."""
    cfg = _secreto("consentimiento") if cfg is None else cfg
    seg = _secreto("seguimiento") if seg is None else seg
    faltantes = []
    url, clave = str(seg.get("url") or "").strip(), str(seg.get("clave_publica") or "").strip()
    if not url.lower().startswith(("https://", "http://")) or not clave:
        faltantes.append("la conexión a Supabase (url y clave_publica de la sección [seguimiento])")
    av_ver = str(cfg.get("aviso_version") or "").strip()
    av_url, av_txt = str(cfg.get("aviso_url") or "").strip(), str(cfg.get("aviso_texto") or "").strip()
    if not av_url and not av_txt:
        av_txt = _leer_archivo_aviso(str(cfg.get("aviso_archivo") or AVISO_ARCHIVO_POR_DEFECTO).strip())
    if not av_ver:
        faltantes.append("aviso_version")
    if not av_url and not av_txt:
        faltantes.append("el texto del aviso (aviso_url, aviso_texto o el archivo aviso_privacidad.md)")
    ter_ver = str(cfg.get("terminos_version") or "").strip()
    ter_url, ter_txt = str(cfg.get("terminos_url") or "").strip(), str(cfg.get("terminos_texto") or "").strip()
    if not ter_ver:
        faltantes.append("terminos_version")
    if not ter_url and not ter_txt:
        faltantes.append("terminos_url o terminos_texto")
    datos = {"url": url, "clave": clave,
             "aviso_version": av_ver, "aviso_fecha": str(cfg.get("aviso_fecha") or "").strip(), "aviso_url": av_url, "aviso_texto": av_txt,
             "terminos_version": ter_ver, "terminos_fecha": str(cfg.get("terminos_fecha") or "").strip(), "terminos_url": ter_url, "terminos_texto": ter_txt}
    return datos, faltantes


# ───────────────────────── Supabase ─────────────────────────
def _llamar_rpc(url, clave, funcion, parametros):
    """Llama a una función de Supabase y devuelve su resultado (JSON). Lanza excepción si algo falla. Es el punto que las pruebas sustituyen."""
    import urllib.error
    import urllib.request
    cabeceras = {"apikey": clave, "Content-Type": "application/json"}
    if clave.startswith("eyJ"):                 # llave antigua (JWT): también va como Bearer
        cabeceras["Authorization"] = f"Bearer {clave}"
    peticion = urllib.request.Request(url.rstrip("/") + "/rest/v1/rpc/" + funcion, data=json.dumps(parametros).encode("utf-8"), headers=cabeceras, method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEG) as r:
            cuerpo = r.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detalle}") from None
    return json.loads(cuerpo) if cuerpo else None


def ya_acepto(datos, correo):
    """True si ese correo ya aceptó las versiones VIGENTES del aviso y de los términos. Lanza excepción si no se puede consultar."""
    r = _llamar_rpc(datos["url"], datos["clave"], "consentimiento_ya_acepto",
                    {"p_correo": correo, "p_aviso_version": datos["aviso_version"], "p_terminos_version": datos["terminos_version"]})
    return r is True


def registrar(datos, nombre, correo, empresa, version_app=""):
    """Guarda la evidencia de la aceptación. Devuelve True solo si Supabase confirmó el registro. Lanza excepción si falla."""
    r = _llamar_rpc(datos["url"], datos["clave"], "registrar_aceptacion",
                    {"p_nombre": nombre, "p_correo": correo, "p_empresa": empresa, "p_aviso_version": datos["aviso_version"], "p_terminos_version": datos["terminos_version"],
                     "p_acepta_aviso": True, "p_acepta_terminos": True, "p_app_version": version_app or ""})
    return r in ("registrado", "ya_aceptado")


def registrar_declaracion(datos, correo, etapa, version_app=""):
    """Guarda la evidencia de la declaración del cliente (correo, etapa, versión del texto, versión de la app). True solo si Supabase confirmó. Lanza excepción si falla."""
    r = _llamar_rpc(datos["url"], datos["clave"], "registrar_declaracion_cliente",
                    {"p_correo": correo, "p_etapa": int(etapa), "p_texto_version": version_declaracion(), "p_app_version": version_app or ""})
    return r == "registrado"


# ───────────────────────── validaciones ─────────────────────────
def correo_valido(texto):
    return bool(_RE_CORREO.fullmatch(str(texto or "").strip())) and len(str(texto).strip()) <= 254


def nombre_valido(texto):
    t = str(texto or "").strip()
    return len(t) >= 3 and len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", t)) >= 3


def empresa_valida(texto):
    return len(str(texto or "").strip()) >= 3


# ───────────────────────── sesión ─────────────────────────
def autorizado(datos=None):
    """True si esta sesión ya aceptó las versiones vigentes (o si el control está apagado)."""
    if not activo():
        return True
    if datos is None:
        datos, faltantes = configuracion()
        if faltantes:
            return False
    ok = st.session_state.get("_consent_ok")
    return bool(ok) and ok.get("aviso") == datos["aviso_version"] and ok.get("terminos") == datos["terminos_version"]


def _dar_acceso(datos, correo):
    st.session_state["_consent_ok"] = {"correo": correo, "aviso": datos["aviso_version"], "terminos": datos["terminos_version"]}
    for k in ("_consent_error", "_consent_paso", "_consent_msgs"):
        st.session_state.pop(k, None)
    st.rerun()


# ───────────────────────── pantalla de ingreso ─────────────────────────
_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarNav"] { display: none !important; }
[data-testid="stAppSkeleton"] { display: none !important; }
.block-container { max-width: 720px !important; padding-top: 2.2rem !important; }
.cs-cab { background: #1B3A6B; color: #fff; border-radius: 12px; padding: 20px 16px; text-align: center; margin-bottom: 18px; }
.cs-cab .t1 { font-size: 1.45rem; font-weight: 800; }
.cs-cab .t2 { font-size: 1.05rem; font-weight: 700; margin-top: 4px; }
.cs-cab .t3 { font-size: .85rem; font-weight: 600; margin-top: 4px; opacity: .92; }
.cs-h { font-size: 1.15rem; font-weight: 700; color: #0F172A; margin: 4px 0 2px; }
.cs-p { font-size: .92rem; color: #334155; margin-bottom: 10px; }
.cs-doc { border: 1px solid #CBD5E1; border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; background: #FAFBFD; }
.cs-doc .n { font-weight: 700; color: #0F172A; font-size: .95rem; }
.cs-doc .d { font-size: .78rem; color: #64748B; margin: 2px 0 6px; }
.cs-doc .o { font-size: .78rem; color: #64748B; margin-top: 6px; }
.cs-doc a { font-size: .85rem; font-weight: 700; color: #1D6FD6 !important; text-decoration: none; }
.cs-doc .o a { font-size: .78rem; }
.cs-pie { background: #F1F5F9; border-radius: 10px; padding: 12px; text-align: center; margin-top: 16px; font-size: .88rem; color: #0F172A; }
.cs-pie a { font-weight: 700; color: #1D6FD6 !important; text-decoration: none; }
.cs-aviso { border: 1px solid #FCA5A5; background: #FEF2F2; color: #7F1D1D; border-radius: 10px; padding: 12px 14px; margin: 10px 0; font-size: .92rem; }
@media (max-width: 640px) { .block-container { padding-left: 1rem !important; padding-right: 1rem !important; } .cs-cab .t1 { font-size: 1.25rem; } }
</style>"""


def _cabecera():
    st.markdown(_CSS + '<div class="cs-cab"><div class="t1">SINCO A&amp;F</div><div class="t2">Bienvenido a nuestra plataforma</div><div class="t3">Asistente y Validador de Migración</div></div>', unsafe_allow_html=True)


def _pie():
    st.markdown(f'<div class="cs-pie">¿Quieres conocer más sobre nosotros? Visita nuestro sitio web.<br><a href="{SITIO_URL}" target="_blank" rel="noopener noreferrer">{SITIO_URL} ↗</a></div>', unsafe_allow_html=True)


def _documentos(datos):
    fecha_av = f' · {html.escape(datos["aviso_fecha"])}' if datos["aviso_fecha"] else ""
    enlace_av = (f'<a href="{html.escape(datos["aviso_url"])}" target="_blank" rel="noopener noreferrer">Abrir aviso ↗</a>' if datos["aviso_url"] else "")
    st.markdown(f'<div class="cs-doc"><div class="n">🔒 {html.escape(AVISO_TITULO)}</div>'
                f'<div class="d">{html.escape(AVISO_PLATAFORMA)} · Versión {html.escape(datos["aviso_version"])}{fecha_av}</div>{enlace_av}'
                f'<div class="o">Consulta también la <a href="{POLITICA_URL}" target="_blank" rel="noopener noreferrer">{html.escape(POLITICA_NOMBRE)} ↗</a> (versión vigente {html.escape(POLITICA_VERSION_INFORMATIVA)}).</div></div>', unsafe_allow_html=True)
    if datos["aviso_texto"]:
        with st.expander("Leer el Aviso de Privacidad"):
            st.markdown(datos["aviso_texto"])
    fecha = f' · {html.escape(datos["terminos_fecha"])}' if datos["terminos_fecha"] else ""
    enlace = (f'<a href="{html.escape(datos["terminos_url"])}" target="_blank" rel="noopener noreferrer">Consultar términos ↗</a>' if datos["terminos_url"] else "")
    st.markdown(f'<div class="cs-doc"><div class="n">📋 Términos y condiciones de uso</div>'
                f'<div class="d">Condiciones de uso de la plataforma · Versión {html.escape(datos["terminos_version"])}{fecha}</div>{enlace}</div>', unsafe_allow_html=True)
    if datos["terminos_texto"]:
        with st.expander("Leer los términos y condiciones"):
            st.markdown(datos["terminos_texto"])


def _aviso(texto):
    st.markdown(f'<div class="cs-aviso">{html.escape(texto)}</div>', unsafe_allow_html=True)


def _paso_correo(datos):
    _cabecera()
    st.markdown('<div class="cs-h">Antes de comenzar</div><div class="cs-p">Escribe tu correo electrónico. Si ya aceptaste el aviso y los términos vigentes, ingresas directo.</div>', unsafe_allow_html=True)
    correo = st.text_input("Correo electrónico", key="_consent_correo_in", placeholder="usuario@empresa.com")
    for m in st.session_state.get("_consent_msgs") or []:
        _aviso(m)
    hubo_fallo = bool(st.session_state.get("_consent_error"))
    if st.button("Reintentar" if hubo_fallo else "Continuar", key="_consent_btn_correo", type="primary", use_container_width=True):
        c = str(correo or "").strip().lower()
        st.session_state.pop("_consent_msgs", None)
        st.session_state.pop("_consent_error", None)
        if not correo_valido(c):
            st.session_state["_consent_msgs"] = ["Escribe un correo electrónico válido (por ejemplo, usuario@empresa.com)."]
            st.rerun()
        try:
            if ya_acepto(datos, c):
                _dar_acceso(datos, c)
            st.session_state["_consent_paso"], st.session_state["_consent_correo"] = "completo", c
        except Exception:
            st.session_state["_consent_error"] = True
            st.session_state["_consent_msgs"] = ["No pudimos verificar tu aceptación en este momento. Por favor inténtalo de nuevo."]
        st.rerun()
    _pie()


def _paso_completo(datos, version_app):
    correo = st.session_state.get("_consent_correo", "")
    _cabecera()
    st.markdown('<div class="cs-h">Antes de comenzar</div><div class="cs-p">Por favor, consulta los siguientes documentos y confirma tu aceptación para ingresar a la plataforma.</div>', unsafe_allow_html=True)
    _documentos(datos)
    st.text_input("Correo electrónico", value=correo, disabled=True, key="_consent_correo_fijo")
    nombre = st.text_input("Nombre completo", key="_consent_nombre")
    empresa = st.text_input("Empresa o NIT", key="_consent_empresa")
    acepta_aviso = st.checkbox(TEXTO_AVISO, key="_consent_chk_aviso", value=False)
    acepta_ter = st.checkbox(TEXTO_TERMINOS, key="_consent_chk_terminos", value=False)
    for m in st.session_state.get("_consent_msgs") or []:
        _aviso(m)
    hubo_fallo = bool(st.session_state.get("_consent_error"))
    if st.button("REINTENTAR" if hubo_fallo else "ACEPTAR Y CONTINUAR", key="_consent_btn_aceptar", type="primary", use_container_width=True, disabled=not (acepta_aviso and acepta_ter)):
        st.session_state.pop("_consent_msgs", None)
        st.session_state.pop("_consent_error", None)
        problemas = []
        if not nombre_valido(nombre):
            problemas.append("Escribe tu nombre completo.")
        if not empresa_valida(empresa):
            problemas.append("Escribe el nombre de tu empresa o su NIT.")
        if problemas:
            st.session_state["_consent_msgs"] = problemas
            st.rerun()
        try:
            if registrar(datos, str(nombre).strip(), correo, str(empresa).strip(), version_app):
                _dar_acceso(datos, correo)
            raise RuntimeError("Supabase no confirmó el registro")
        except Exception:
            st.session_state["_consent_error"] = True
            st.session_state["_consent_msgs"] = ["No pudimos guardar tu aceptación, por eso todavía no puedes ingresar. Verifica tu conexión e inténtalo de nuevo con el botón."]
        st.rerun()
    if st.button("← Cambiar correo", key="_consent_btn_cambiar"):
        for k in ("_consent_paso", "_consent_error", "_consent_msgs"):
            st.session_state.pop(k, None)
        st.rerun()
    st.caption("El acceso estará disponible después de aceptar ambas condiciones.")
    _pie()


def _pantalla_configuracion_incompleta(faltantes):
    _cabecera()
    _aviso("El control de aceptación está activado pero su configuración está incompleta, por eso la plataforma no puede abrirse. Falta: " + "; ".join(faltantes) + ". Avisa al administrador de la aplicación.")


def exigir(version_app=""):
    """Si el control está encendido y esta sesión no ha aceptado, muestra la pantalla y DETIENE la app (st.stop). Si está apagado o ya aceptó, no hace nada."""
    if not activo():
        return
    datos, faltantes = configuracion()
    if faltantes:
        _pantalla_configuracion_incompleta(faltantes)
        st.stop()
    if autorizado(datos):
        return
    if st.session_state.get("_consent_paso") == "completo":
        _paso_completo(datos, version_app)
    else:
        _paso_correo(datos)
    st.stop()


# ───────────────────────── declaración del cliente (una vez por etapa y sesión) ─────────────────────────
def _declarada(etapa):
    return (st.session_state.get("_decl_ok") or {}).get(int(etapa)) == version_declaracion()


def carga_bloqueada(etapa):
    """True si los cargadores de archivos con terceros de esa etapa deben estar DESHABILITADOS (declaración encendida y todavía sin marcar en esta sesión)."""
    return declaracion_activa() and not _declarada(etapa)


def mostrar_declaracion(etapa, version_app=""):
    """Muestra la declaración del cliente de esa etapa (casilla con el texto aprobado). Al marcarla guarda la evidencia en Supabase; si no se puede guardar, los cargadores siguen deshabilitados y se ofrece reintentar."""
    if not declaracion_activa():
        return
    datos, faltantes = configuracion()
    correo = (st.session_state.get("_consent_ok") or {}).get("correo", "")
    if faltantes or not correo:
        return                                          # sin configuración o sin ingreso aceptado no hay nada que registrar: los cargadores siguen bloqueados y la pantalla de ingreso ya avisa
    if _declarada(etapa):
        st.markdown('<div style="font-size:12px;color:#86EFAC;margin:4px 0 8px 0">✅ Declaración del cliente registrada para esta etapa.</div>', unsafe_allow_html=True)
        return
    marcada = st.checkbox(TEXTO_DECLARACION, key=f"_decl_chk_{int(etapa)}", value=False)
    clave_error = f"_decl_err_{int(etapa)}"
    if marcada and not st.session_state.get(clave_error):
        try:
            guardada = registrar_declaracion(datos, correo, etapa, version_app)
        except Exception:
            guardada = False
        if guardada:
            ok = dict(st.session_state.get("_decl_ok") or {})
            ok[int(etapa)] = version_declaracion()
            st.session_state["_decl_ok"] = ok
            st.rerun()
        st.session_state[clave_error] = True
    if marcada and st.session_state.get(clave_error):
        st.markdown('<div style="font-size:12px;color:#FCA5A5;margin:4px 0">No pudimos guardar tu declaración, por eso todavía no puedes cargar archivos con información de terceros. Inténtalo de nuevo.</div>', unsafe_allow_html=True)
        if st.button("Reintentar", key=f"_decl_btn_{int(etapa)}"):
            st.session_state.pop(clave_error, None)
            st.rerun()
    elif not marcada:
        st.session_state.pop(clave_error, None)
        st.markdown('<div style="font-size:11px;color:#FDE68A;margin:2px 0 6px 0">Marca la declaración para habilitar la carga de archivos con información de terceros.</div>', unsafe_allow_html=True)
