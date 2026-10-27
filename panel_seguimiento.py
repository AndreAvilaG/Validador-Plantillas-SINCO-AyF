"""Panel de seguimiento para directores — SINCO A&F.

Qué es: una pantalla para ver el avance de cada empresa en las cuatro etapas. Se abre SOLO con el enlace especial ?panel=1 de la app
(en la app normal no hay ningún botón ni mención del panel) y exige el código de directores.

Cómo protege los datos:
  * Las tablas de seguimiento siguen cerradas al público. El panel solo puede llamar a dos lecturas de la base (panel_resumen y
    panel_historial), y las dos comprueban el código DENTRO de la base; con 5 intentos fallidos se bloquean 10 minutos.
  * No se usa la llave secreta en ninguna parte: el panel usa la misma llave pública del seguimiento.
  * Solo se muestra lo que la base ya guarda (porcentajes, estados, conteos y el nombre y NIT de la empresa): nunca datos de las celdas.

El código de directores y las lecturas se crean con seguimiento_supabase_fase2_panel.sql.
"""
import json
from datetime import datetime, timedelta, timezone

ZONA_COLOMBIA = timezone(timedelta(hours=-5))            # Colombia no tiene horario de verano: UTC−5 todo el año
TIMEOUT_SEG = 10
VENTANA_REBOTE_SEG = 60                                  # un cambio que se revierte en menos de un minuto no cuenta (regla elegida)
REFRESCO_AUTOMATICO_SEG = 300                            # si los datos tienen más de 5 minutos, se vuelven a pedir al interactuar
NOMBRES_ETAPA = {1: "Etapa 1 · Maestros", 2: "Etapa 2 · Saldos CxC/CxP", 3: "Etapa 3 · SI y Movimientos", 4: "Etapa 4 · Conciliación"}
LEYENDA_ETAPAS = ("**Etapa 1:** Maestros (PUC, Terceros, Centros de Costos) · **Etapa 2:** Saldos CxC/CxP · "
                  "**Etapa 3:** SI y Movimientos · **Etapa 4:** Conciliación")
MENSAJES_ERROR = {
    "codigo_incorrecto": "El código no es correcto.",
    "bloqueado": "Se superó el número de intentos. Espera 10 minutos e inténtalo de nuevo.",
    "sin_configurar": "El panel todavía no tiene un código de acceso. Avisa a quien administra el seguimiento.",
    "no_configurado": "El seguimiento no está configurado en esta aplicación.",
    "sin_conexion": "No se pudo consultar el seguimiento. Inténtalo de nuevo en unos minutos.",
    "nit_invalido": "No se pudo consultar el historial de esa empresa.",
}


class ErrorPanel(Exception):
    """Algo impidió mostrar los datos. `tipo` es una clave de MENSAJES_ERROR; `detalle` es técnico y no se muestra al usuario."""
    def __init__(self, tipo, detalle=""):
        super().__init__(f"{tipo}: {detalle}" if detalle else tipo)
        self.tipo = tipo
        self.detalle = detalle


# ─────────────────────────────────────────────────────────────────────────────
# Conexión con la base
# ─────────────────────────────────────────────────────────────────────────────
def leer_configuracion(secretos):
    """(url, llave) si en los Secrets hay una dirección http(s) y una llave; None en otro caso. No depende de 'activo'."""
    cfg = dict(secretos or {})
    url, clave = str(cfg.get("url") or "").strip(), str(cfg.get("clave_publica") or "").strip()
    if not clave or not url.lower().startswith(("https://", "http://")):
        return None
    return url, clave


def consultar(url, clave, funcion, parametros):
    """Llama a una lectura de la base y devuelve su respuesta (dict con ok=True). Lanza ErrorPanel si algo falla."""
    import urllib.error
    import urllib.request
    cabeceras = {"apikey": clave, "Content-Type": "application/json"}
    if clave.startswith("eyJ"):                          # llave antigua (JWT): también va como Bearer
        cabeceras["Authorization"] = f"Bearer {clave}"
    peticion = urllib.request.Request(url.rstrip("/") + "/rest/v1/rpc/" + funcion,
                                      data=json.dumps(parametros).encode("utf-8"), headers=cabeceras, method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEG) as r:
            cuerpo = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorPanel("sin_conexion", f"HTTP {e.code}") from None
    except Exception as e:                                # red caída, tiempo agotado, respuesta que no es JSON…
        raise ErrorPanel("sin_conexion", type(e).__name__) from None
    if not isinstance(cuerpo, dict):
        raise ErrorPanel("sin_conexion", "respuesta inesperada")
    if not cuerpo.get("ok"):
        raise ErrorPanel(str(cuerpo.get("error") or "sin_conexion"))
    return cuerpo


# ─────────────────────────────────────────────────────────────────────────────
# Lógica de los datos (sin pantalla: se prueba aparte)
# ─────────────────────────────────────────────────────────────────────────────
def fecha_utc(texto):
    """datetime con zona horaria a partir del texto que entrega la base (ISO 8601); None si no se entiende."""
    try:
        d = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def hora_colombia(d):
    """La misma fecha vista en hora de Colombia, sin zona horaria (lista para mostrar); None si no hay fecha."""
    return d.astimezone(ZONA_COLOMBIA).replace(tzinfo=None) if d else None


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _promedio(valores):
    nums = [n for n in (_numero(v) for v in valores) if n is not None]
    return round(sum(nums) / len(nums), 1) if nums else None


def _igual(a, b):
    a, b = _numero(a), _numero(b)
    return a is not None and b is not None and abs(a - b) < 0.005


_MIN_FECHA = datetime.min.replace(tzinfo=timezone.utc)


def agrupar_empresas(avance):
    """Una fila por empresa (por NIT), de la más reciente a la más antigua.

    Cada etapa es el promedio de las plantillas YA validadas en esa etapa (None si ninguna). No hay un porcentaje general a
    propósito: no se sabe cuántas plantillas necesita cada empresa, así que uno solo engañaría. En cambio sí se indica si todo
    lo validado hasta ahora está completo ("al día") o si hay correcciones pendientes.
    """
    por_nit = {}
    for fila in avance or []:
        nit = str(fila.get("nit") or "").strip()
        if nit:
            por_nit.setdefault(nit, []).append(fila)
    empresas = []
    for nit, filas in por_nit.items():
        reciente = max(filas, key=lambda f: fecha_utc(f.get("actualizado_en")) or _MIN_FECHA)
        empresas.append({
            "nit": nit,
            "nombre": str(reciente.get("nombre_cliente") or f"NIT {nit}"),
            "etapas": {n: _promedio([f.get("cumplimiento") for f in filas if f.get("etapa") == n]) for n in NOMBRES_ETAPA},
            "al_dia": all(f.get("estado") == "completado" for f in filas),
            "plantillas": len(filas),
            "ultima": fecha_utc(reciente.get("actualizado_en")),
        })
    empresas.sort(key=lambda e: e["ultima"] or _MIN_FECHA, reverse=True)
    return empresas


def metricas(empresas, ahora):
    """Los cuatro números de arriba del panel. `ahora` es un datetime con zona horaria."""
    return {
        "empresas": len(empresas),
        "al_dia": sum(1 for e in empresas if e["al_dia"]),
        "con_correcciones": sum(1 for e in empresas if not e["al_dia"]),
        "activas_24h": sum(1 for e in empresas if e["ultima"] and ahora - e["ultima"] <= timedelta(hours=24)),
    }


def filtrar_empresas(empresas, texto):
    """Empresas cuyo nombre o NIT contiene el texto (sin importar mayúsculas ni puntos del NIT)."""
    t = str(texto or "").strip().casefold()
    if not t:
        return list(empresas)
    t_nit = "".join(c for c in t if c.isdigit())
    return [e for e in empresas if t in e["nombre"].casefold() or (t_nit and t_nit in e["nit"])]


def plantillas_de(avance, nit):
    """Las plantillas de una empresa, ordenadas por etapa y nombre."""
    return sorted((f for f in (avance or []) if str(f.get("nit") or "").strip() == nit),
                  key=lambda f: (f.get("etapa") or 0, str(f.get("plantilla") or "")))


def pendientes_de(plantillas):
    """Filas (plantilla, qué falta, columna, casos) con lo pendiente de cada plantilla, de más a menos casos."""
    filas = []
    for p in plantillas:
        for q in p.get("pendientes") or []:
            if isinstance(q, dict):
                filas.append({"plantilla": str(p.get("plantilla") or ""), "que_falta": str(q.get("categoria") or ""),
                              "columna": str(q.get("columna") or ""), "casos": int(_numero(q.get("casos")) or 0)})
    return sorted(filas, key=lambda f: -f["casos"])


def colapsar_rebotes(historial, segundos=VENTANA_REBOTE_SEG):
    """Quita del historial los cambios que se revierten en menos de `segundos`.

    Ejemplo real: 91,67 → 16,67 y, 8 segundos después, 16,67 → 91,67. Alguien quitó y volvió a poner un archivo: el trabajo no
    retrocedió, así que esas dos filas no cuentan. Se compara cada fila con la anterior de la MISMA plantilla.
    Devuelve (filas visibles de la más reciente a la más antigua, cantidad de filas ocultas).
    """
    filas = sorted((f for f in (historial or []) if fecha_utc(f.get("registrado_en"))), key=lambda f: fecha_utc(f["registrado_en"]))
    pilas, ocultas = {}, 0
    for f in filas:
        pila = pilas.setdefault((f.get("etapa"), f.get("plantilla")), [])
        if pila:
            previa = pila[-1]
            segundos_entre = (fecha_utc(f["registrado_en"]) - fecha_utc(previa["registrado_en"])).total_seconds()
            if (segundos_entre < segundos and _igual(f.get("cumplimiento_antes"), previa.get("cumplimiento"))
                    and _igual(f.get("cumplimiento"), previa.get("cumplimiento_antes"))):
                pila.pop()
                ocultas += 2
                continue
        pila.append(f)
    visibles = sorted((f for pila in pilas.values() for f in pila), key=lambda f: fecha_utc(f["registrado_en"]), reverse=True)
    return visibles, ocultas


def porcentaje_texto(valor):
    """91.67 -> '91.7%'; sin valor (por ejemplo el «antes» de la primera validación) -> '—'."""
    n = _numero(valor)
    return "—" if n is None else f"{n:.1f}%"


def miles(n):
    """7822 -> '7.822' (punto de miles, como se escribe en Colombia)."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


# ─────────────────────────────────────────────────────────────────────────────
# Pantalla
# ─────────────────────────────────────────────────────────────────────────────
def _estilo(st):
    st.markdown("""<style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display: none !important; }
    .block-container { max-width: 1250px !important; padding-top: 4.5rem !important; }
    .panel-banner { background: linear-gradient(135deg,#1B3A6B,#4A7FB5); border-radius: 14px; padding: 18px 26px; margin-bottom: 18px; color: white; }
    .panel-banner h2 { color: white; margin: 0; font-size: 1.5rem; }
    .panel-banner p { color: #DCE8F7; margin: 4px 0 0 0; font-size: 0.9rem; }
    </style>""", unsafe_allow_html=True)


def _banner(st, subtitulo):
    st.markdown(f'<div class="panel-banner"><h2>📊 Seguimiento de migraciones — SINCO A&amp;F</h2><p>{subtitulo}</p></div>',
                unsafe_allow_html=True)


def _salir(st):
    for k in ("_panel_codigo", "_panel_datos", "_panel_cargado", "_panel_historial"):
        st.session_state.pop(k, None)


def _pedir_resumen(st, cfg):
    cuerpo = consultar(cfg[0], cfg[1], "panel_resumen", {"p_codigo": st.session_state["_panel_codigo"]})
    st.session_state["_panel_datos"] = cuerpo
    st.session_state["_panel_cargado"] = datetime.now(timezone.utc)
    st.session_state["_panel_historial"] = {}


def _pantalla_de_acceso(st, cfg):
    _banner(st, "Acceso para directores")
    with st.form("panel_acceso"):
        codigo = st.text_input("Código de directores", type="password", key="panel_codigo")
        entrar = st.form_submit_button("Entrar", use_container_width=True)
    if not entrar:
        return
    if not codigo.strip():
        st.error("Escribe el código de directores.")
        return
    st.session_state["_panel_codigo"] = codigo.strip()
    try:
        with st.spinner("Verificando…"):
            _pedir_resumen(st, cfg)
    except ErrorPanel as e:
        _salir(st)
        st.error(MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"]))
        return
    st.rerun()


def _tabla_empresas(st, pd, empresas):
    columnas_etapa = {n: f"Etapa {n}" for n in NOMBRES_ETAPA}
    st.dataframe(
        pd.DataFrame([{
            "Empresa": e["nombre"], "NIT": e["nit"], "Estado": "🟢 Al día" if e["al_dia"] else "🟠 Con correcciones",
            "Última actividad": hora_colombia(e["ultima"]),
            **{columnas_etapa[n]: e["etapas"][n] for n in NOMBRES_ETAPA},
        } for e in empresas]),
        hide_index=True, use_container_width=True,
        column_config={
            "NIT": st.column_config.TextColumn("NIT", width="small"),
            "Última actividad": st.column_config.DatetimeColumn("Última actividad", format="DD/MM/YY HH:mm"),
            **{columnas_etapa[n]: st.column_config.ProgressColumn(columnas_etapa[n], min_value=0, max_value=100, format="%.1f%%", color="auto", width="small")
               for n in NOMBRES_ETAPA},
        })
    st.caption(LEYENDA_ETAPAS)


def _detalle_empresa(st, pd, cfg, avance, empresa):
    plantillas = plantillas_de(avance, empresa["nit"])
    st.dataframe(pd.DataFrame([{
        "Etapa": f"Etapa {p.get('etapa')}", "Plantilla": str(p.get("plantilla") or ""),
        "Avance": _numero(p.get("cumplimiento")),
        "Estado": "✅ Completado" if p.get("estado") == "completado" else "🔧 Requiere correcciones",
        "Filas con error": f"{miles(p.get('filas_con_error'))} de {miles(p.get('filas_evaluadas'))}",
        "Advertencias": int(_numero(p.get("advertencias")) or 0),
        "Actualizado": hora_colombia(fecha_utc(p.get("actualizado_en"))),
    } for p in plantillas]), hide_index=True, use_container_width=True, column_config={
        "Plantilla": st.column_config.TextColumn("Plantilla", width="large"),
        "Avance": st.column_config.ProgressColumn("Avance", min_value=0, max_value=100, format="%.1f%%", color="auto"),
        "Actualizado": st.column_config.DatetimeColumn("Actualizado", format="DD/MM/YY HH:mm")})

    pendientes = pendientes_de(plantillas)
    if pendientes:
        st.markdown("**Lo que falta corregir**")
        st.dataframe(pd.DataFrame([{"Plantilla": f["plantilla"], "Qué falta": f["que_falta"], "Columna": f["columna"], "Casos": f["casos"]}
                                   for f in pendientes]), hide_index=True, use_container_width=True)

    hist = st.session_state.setdefault("_panel_historial", {})
    if empresa["nit"] not in hist:
        try:
            hist[empresa["nit"]] = consultar(cfg[0], cfg[1], "panel_historial",
                                             {"p_codigo": st.session_state["_panel_codigo"], "p_nit": empresa["nit"]}).get("historial") or []
        except ErrorPanel as e:
            st.warning(MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"]))
            return
    visibles, ocultas = colapsar_rebotes(hist[empresa["nit"]])
    st.markdown("**Historial de avance**")
    if not visibles:
        st.caption("Todavía no hay movimientos para esta empresa.")
        return
    st.dataframe(pd.DataFrame([{
        "Fecha": hora_colombia(fecha_utc(f.get("registrado_en"))), "Plantilla": str(f.get("plantilla") or ""),
        "Antes": porcentaje_texto(f.get("cumplimiento_antes")), "Ahora": porcentaje_texto(f.get("cumplimiento")),
        "Estado": {"completado": "✅ Completado", "requiere_correcciones": "🔧 Requiere correcciones"}.get(f.get("estado"), "—"),
    } for f in visibles[:60]]), hide_index=True, use_container_width=True, column_config={
        "Fecha": st.column_config.DatetimeColumn("Fecha", format="DD/MM/YYYY HH:mm"),
        "Plantilla": st.column_config.TextColumn("Plantilla", width="large")})
    if ocultas:
        st.caption(f"Se ocultaron {ocultas} movimientos que se revirtieron en menos de un minuto (alguien cambió un archivo y lo volvió a poner).")


def _pantalla_de_datos(st, pd, cfg):
    ahora = datetime.now(timezone.utc)
    if (ahora - st.session_state.get("_panel_cargado", ahora)).total_seconds() > REFRESCO_AUTOMATICO_SEG:
        try:
            _pedir_resumen(st, cfg)
        except ErrorPanel as e:                           # el código cambió o la base no responde: se pide entrar de nuevo
            _salir(st)
            st.session_state["_panel_aviso"] = MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"])
            st.rerun()
    datos = st.session_state["_panel_datos"]
    avance = datos.get("avance") or []
    cargado = hora_colombia(st.session_state["_panel_cargado"])
    _banner(st, f"Actualizado el {cargado:%d/%m/%Y a las %H:%M} (hora de Colombia)")

    c1, c2, _ = st.columns([1, 1, 6])
    if c1.button("🔄 Actualizar", use_container_width=True):
        try:
            _pedir_resumen(st, cfg)
        except ErrorPanel as e:
            _salir(st)
            st.session_state["_panel_aviso"] = MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"])
        st.rerun()
    if c2.button("Salir", use_container_width=True):
        _salir(st)
        st.rerun()

    empresas = agrupar_empresas(avance)
    if not empresas:
        st.info("Todavía no hay empresas con avance registrado.")
    else:
        m = metricas(empresas, datetime.now(timezone.utc))
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Empresas con actividad", m["empresas"])
        k2.metric("Al día (todo completado)", m["al_dia"])
        k3.metric("Con correcciones pendientes", m["con_correcciones"])
        k4.metric("Actividad en las últimas 24 h", m["activas_24h"])

        st.markdown("### Empresas")
        texto = st.text_input("Buscar por nombre o NIT", key="panel_buscar", placeholder="Escribe parte del nombre o el NIT")
        visibles = filtrar_empresas(empresas, texto)
        if not visibles:
            st.caption("Ninguna empresa coincide con la búsqueda.")
        else:
            _tabla_empresas(st, pd, visibles)
            st.markdown("### Detalle de una empresa")
            opciones = {f"{e['nombre']} — NIT {e['nit']}": e for e in visibles}
            elegida = st.selectbox("Empresa", list(opciones), key="panel_empresa")
            _detalle_empresa(st, pd, cfg, avance, opciones[elegida])

    sin = datos.get("sin_identificar") or []
    if sin:
        with st.expander("Usos sin empresa identificada"):
            st.caption("Veces que se validó una plantilla sin que se pudiera saber de qué empresa era. No cuentan en el avance.")
            st.dataframe(pd.DataFrame([{"Etapa": f"Etapa {s.get('etapa')}", "Plantilla": str(s.get("plantilla") or ""),
                                        "Veces": int(_numero(s.get("usos")) or 0), "Último uso": hora_colombia(fecha_utc(s.get("ultimo_uso")))}
                                       for s in sin]), hide_index=True, use_container_width=True,
                         column_config={"Último uso": st.column_config.DatetimeColumn("Último uso", format="DD/MM/YYYY HH:mm")})

    with st.expander("¿Cómo se mide el avance?"):
        st.markdown("- **Etapas 1 a 3:** porcentaje de filas de la plantilla **sin errores**. Las advertencias no cuentan.\n"
                    "- **Etapa 4:** porcentaje de registros **conciliados** (sin diferencias).\n"
                    "- **100%** significa completado. Cada columna promedia las plantillas que la empresa ya validó en esa etapa.\n"
                    "- **Al día** quiere decir que todo lo validado hasta ahora está completo; no indica cuántas plantillas faltan por validar.\n"
                    "- En el historial se ignoran los cambios que se revierten en menos de un minuto.")


def render_panel():
    """Dibuja el panel (acceso o datos). La app lo llama cuando la dirección trae ?panel=1."""
    import pandas as pd
    import streamlit as st
    _estilo(st)
    try:
        cfg = leer_configuracion(st.secrets.get("seguimiento", {}))
    except Exception:
        cfg = None
    if cfg is None:
        _banner(st, "Panel de directores")
        st.error(MENSAJES_ERROR["no_configurado"])
        return
    aviso = st.session_state.pop("_panel_aviso", None)
    if st.session_state.get("_panel_codigo") and st.session_state.get("_panel_datos"):
        _pantalla_de_datos(st, pd, cfg)
    else:
        _pantalla_de_acceso(st, cfg)
        if aviso:
            st.warning(aviso)
