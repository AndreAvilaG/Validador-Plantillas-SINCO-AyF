"""Panel de seguimiento para directores — SINCO A&F.

Qué es: la pantalla para ver el avance de cada cliente en las cuatro etapas. Sigue el boceto y las reglas acordadas con Andrea:
  * Cada etapa promedia sus PLANTILLAS ESPERADAS (una esperada que no se ha cargado cuenta 0%).
  * Una etapa se marca «No aplica» AUTOMÁTICAMENTE si el cliente no la usó y avanzó a una posterior; si la usa después, vuelve a contar.
    Las Etapas 3 y 4 siempre aplican juntas. Nadie tiene que configurar nada.
  * Avance global = promedio (mismo peso) de las etapas que aplican.
  * Estados: Pendiente, En proceso, Requiere correcciones, Completado.

Se abre SOLO con el enlace especial ?panel=1 de la app y exige el código de directores.

Cómo protege los datos:
  * Las tablas de seguimiento siguen cerradas al público. El panel solo puede llamar a dos lecturas de la base (panel_resumen y
    panel_historial), y las dos comprueban el código DENTRO de la base; con 5 intentos fallidos se bloquean 10 minutos.
  * No se usa la llave secreta en ninguna parte: el panel usa la misma llave pública del seguimiento.
  * Solo se muestra lo que la base ya guarda (porcentajes, estados, conteos y el nombre y NIT de la empresa): nunca datos de las celdas.
  * Todo texto que escribió un usuario (nombre de empresa, plantillas, columnas) se escapa antes de dibujarlo.

El código de directores y las lecturas se crean con seguimiento_supabase_fase2_panel.sql y seguimiento_supabase_fase2b_definir_codigo.sql.
"""
import html as _html
import json
import math
import re
from datetime import datetime, timedelta, timezone

ZONA_COLOMBIA = timezone(timedelta(hours=-5))            # Colombia no tiene horario de verano: UTC−5 todo el año
TIMEOUT_SEG = 10
VENTANA_REBOTE_SEG = 60                                  # un cambio que se revierte en menos de un minuto no cuenta (regla elegida)
REFRESCO_AUTOMATICO_SEG = 300                            # si los datos tienen más de 5 minutos, se vuelven a pedir al interactuar
DIAS_SIN_ACTIVIDAD = 7                                   # «sin actividad» = más de 7 días sin uso
NOMBRES_ETAPA = {1: "Plantillas maestras", 2: "Saldos CxC / CxP", 3: "Saldos Iniciales y Movimientos", 4: "Conciliación"}
# Plantillas que se esperan de cada cliente por etapa (tabla acordada). Los libros Fiscal y NIF (Etapa 3) y el PUC Fiscal (Etapa 1) cuentan solo si el
# cliente los cargó; en la Etapa 4 se promedian los módulos que se hayan conciliado.
ESPERADAS = {1: ("PUC Principal", "Terceros", "Centros de Costos"),
             2: ("Saldos de Cuentas por Cobrar", "Saldos de Cuentas por Pagar"),
             3: ("Saldos Iniciales Principal", "Movimientos Principal"),
             4: ()}
ETIQUETA_CORTA = {"saldos de cuentas por cobrar": "CxC", "saldos de cuentas por pagar": "CxP",
                  "saldos iniciales principal": "Saldos Iniciales", "movimientos principal": "Movimientos"}
ESTADOS = {
    "pendiente": {"texto": "Pendiente", "fondo": "#E3EAF4", "color": "#33445E", "barra": "#A8B4C6"},
    "en_proceso": {"texto": "En proceso", "fondo": "#FCEFC7", "color": "#7A4504", "barra": "#E0A021"},
    "requiere_correcciones": {"texto": "Requiere correcciones", "fondo": "#FDE4E4", "color": "#A61B1B", "barra": "#D14343"},
    "completado": {"texto": "Completado", "fondo": "#DDF3E4", "color": "#14693A", "barra": "#2E9D5B"},
}
FILTROS = (("todos", "Todos"), ("requiere_correcciones", "Requieren correcciones"), ("en_proceso", "En proceso"),
           ("completado", "Completados"), ("inactivos", f"Sin actividad +{DIAS_SIN_ACTIVIDAD} días"))
ORDENES = (("ultima", "Última actividad"), ("avance_menor", "Avance global (menor primero)"),
           ("avance_mayor", "Avance global (mayor primero)"), ("nombre", "Nombre (A–Z)"))
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
# Fechas y números
# ─────────────────────────────────────────────────────────────────────────────
_MIN_FECHA = datetime.min.replace(tzinfo=timezone.utc)


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


def hace_texto(d, ahora):
    """«Hoy 10:42», «Ayer 16:20», «Hace 5 días». Los días se cuentan en hora de Colombia."""
    if not d:
        return "—"
    local, hoy = hora_colombia(d), hora_colombia(ahora).date()
    dias = (hoy - local.date()).days
    if dias <= 0:
        return f"Hoy {local:%H:%M}"
    return f"Ayer {local:%H:%M}" if dias == 1 else f"Hace {dias} días"


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _igual(a, b):
    a, b = _numero(a), _numero(b)
    return a is not None and b is not None and abs(a - b) < 0.005


def pct_visible(pct, estado):
    """Porcentaje entero para mostrar. Si no está completado nunca pasa de 99: un 99,6% no puede verse como 100%."""
    v = math.floor((_numero(pct) or 0.0) + 0.5)
    return v if estado == "completado" else min(v, 99)


def miles(n):
    """7822 -> '7.822' (punto de miles, como se escribe en Colombia)."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def porcentaje_texto(valor):
    """91.67 -> '91.7%'; sin valor (por ejemplo el «antes» de la primera validación) -> '—'."""
    n = _numero(valor)
    return "—" if n is None else f"{n:.1f}%"


def porcentaje_entero(valor):
    """91.67 -> '92%'; sin valor -> '—'."""
    n = _numero(valor)
    return "—" if n is None else f"{math.floor(n + 0.5)}%"


def nit_con_puntos(nit):
    """901652178 -> '901.652.178'."""
    return miles(nit) if str(nit).isdigit() else str(nit)


def _e(texto):
    """Escapa texto escrito por un usuario antes de ponerlo dentro de HTML."""
    return _html.escape(str(texto if texto is not None else ""), quote=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo del avance (reglas acordadas)
# ─────────────────────────────────────────────────────────────────────────────
def normalizar_nombre(nombre):
    """Para comparar nombres de plantilla: sin mayúsculas, sin guiones largos y con espacios simples."""
    return " ".join(re.sub(r"[—–\-]+", " ", str(nombre or "")).casefold().split())


def etiqueta_corta(nombre):
    return ETIQUETA_CORTA.get(normalizar_nombre(nombre), str(nombre))


def nombre_visible(nombre):
    """«Saldos Iniciales Principal» -> «Saldos Iniciales — Principal» (como en el boceto); el resto igual."""
    m = re.match(r"^(Saldos Iniciales|Movimientos)\s+(?!—)(.+)$", str(nombre or ""))
    return f"{m.group(1)} — {m.group(2)}" if m else str(nombre or "")


def calcular_etapa(n, filas):
    """Avance de una etapa para un cliente, a partir de sus filas de avance_actual.

    Cada plantilla ESPERADA cuenta con su porcentaje, o con 0 si aún no se ha cargado; las plantillas extra que haya cargado (PUC Fiscal, libros
    Fiscal o NIF) también cuentan. Estado: Pendiente (nada cargado), Requiere correcciones (alguna con errores), En proceso (sin errores pero faltan
    esperadas) o Completado (todas las esperadas cargadas y sin errores; en la Etapa 4, todo conciliado).
    """
    cargadas = [f for f in filas or [] if f.get("etapa") == n]
    por_nombre = {normalizar_nombre(f.get("plantilla")): f for f in cargadas}
    esperadas = ESPERADAS.get(n, ())
    faltantes, valores = [], []
    for nombre in esperadas:
        f = por_nombre.get(normalizar_nombre(nombre))
        if f is None:
            faltantes.append(nombre)
            valores.append(0.0)
        else:
            valores.append(_numero(f.get("cumplimiento")) or 0.0)
    esperadas_norm = {normalizar_nombre(x) for x in esperadas}
    extras = [f for k, f in por_nombre.items() if k not in esperadas_norm]
    valores += [(_numero(f.get("cumplimiento")) or 0.0) for f in extras]
    con_errores = [f for f in cargadas if f.get("estado") != "completado"]
    if not cargadas:
        estado = "pendiente"
    elif con_errores:
        estado = "requiere_correcciones"
    elif faltantes:
        estado = "en_proceso"
    else:
        estado = "completado"
    return {"etapa": n, "estado": estado, "pct": (sum(valores) / len(valores)) if valores else 0.0, "faltantes": faltantes,
            "esperadas": len(esperadas), "cargadas_esperadas": len(esperadas) - len(faltantes),
            "cargadas": sorted(cargadas, key=lambda f: str(f.get("plantilla") or "")),
            "con_errores": sorted(con_errores, key=lambda f: str(f.get("plantilla") or ""))}


def analizar_cliente(filas):
    """Las cuatro etapas de un cliente, cuáles aplican, el avance global y el estado general."""
    etapas = {n: calcular_etapa(n, filas) for n in NOMBRES_ETAPA}
    con_datos = {n for n, e in etapas.items() if e["cargadas"]}
    for n, e in etapas.items():
        # No aplica: etapa 1 o 2 que el cliente no usó y que quedó atrás porque avanzó a una posterior. Las etapas 3 y 4 siempre aplican.
        e["aplica"] = n in (3, 4) or n in con_datos or not any(m > n for m in con_datos)
    aplicables = [e for e in etapas.values() if e["aplica"]]
    estados = [e["estado"] for e in aplicables]
    if "requiere_correcciones" in estados:
        estado = "requiere_correcciones"
    elif all(s == "completado" for s in estados):
        estado = "completado"
    elif all(s == "pendiente" for s in estados):
        estado = "pendiente"
    else:
        estado = "en_proceso"
    return {"etapas": etapas, "estado": estado, "pct": sum(e["pct"] for e in aplicables) / len(aplicables),
            "n_aplican": len(aplicables), "primera_etapa": min(con_datos) if con_datos else None}


def requiere_atencion(analisis):
    """Qué hay que mirar primero de un cliente, en una frase corta («—» si no hay nada pendiente)."""
    etapas = analisis["etapas"]
    for n in sorted(etapas):
        e = etapas[n]
        if not e["aplica"] or e["estado"] == "completado":
            continue
        if e["estado"] == "requiere_correcciones":
            if n == 4:
                return f"Etapa 4: {100 - pct_visible(e['pct'], e['estado'])}% sin conciliar"
            con = e["con_errores"]
            if len(con) == 1:
                return f"Etapa {n}: errores en {etiqueta_corta(con[0].get('plantilla'))}"
            return f"Etapa {n}: errores en {len(con)} plantillas"
        if e["estado"] == "en_proceso":
            falta = [etiqueta_corta(x) for x in e["faltantes"]]
            return f"Etapa {n}: falta cargar {falta[0]}" if len(falta) == 1 else f"Etapa {n}: faltan {', '.join(falta[:-1])} y {falta[-1]}"
        return f"Etapa {n}: sin iniciar"
    return "—"


def agrupar_clientes(avance):
    """Un cliente por NIT con su análisis, de la actividad más reciente a la más antigua."""
    por_nit = {}
    for fila in avance or []:
        nit = str(fila.get("nit") or "").strip()
        if nit:
            por_nit.setdefault(nit, []).append(fila)
    clientes = []
    for nit, filas in por_nit.items():
        reciente = max(filas, key=lambda f: fecha_utc(f.get("actualizado_en")) or _MIN_FECHA)
        clientes.append({"nit": nit, "nombre": str(reciente.get("nombre_cliente") or f"NIT {nit}"), "fuente_nit": reciente.get("fuente_nit"),
                         "filas": filas, "analisis": analizar_cliente(filas), "ultima": fecha_utc(reciente.get("actualizado_en"))})
    clientes.sort(key=lambda c: c["ultima"] or _MIN_FECHA, reverse=True)
    return clientes


def inactivo(cliente, ahora):
    return bool(cliente["ultima"]) and ahora - cliente["ultima"] > timedelta(days=DIAS_SIN_ACTIVIDAD)


def resumen_general(clientes, ahora):
    """Los cinco números de arriba del panel."""
    def cuenta(estado):
        return sum(1 for c in clientes if c["analisis"]["estado"] == estado)
    return {"registrados": len(clientes), "completados": cuenta("completado"), "requieren": cuenta("requiere_correcciones"),
            "en_proceso": cuenta("en_proceso"), "inactivos": sum(1 for c in clientes if inactivo(c, ahora))}


def contar_filtros(clientes, ahora):
    r = resumen_general(clientes, ahora)
    return {"todos": r["registrados"], "requiere_correcciones": r["requieren"], "en_proceso": r["en_proceso"],
            "completado": r["completados"], "inactivos": r["inactivos"]}


def filtrar_clientes(clientes, filtro, texto, ahora):
    """Por estado (o inactividad) y por texto: nombre o NIT, sin importar mayúsculas ni puntos del NIT."""
    if filtro == "inactivos":
        clientes = [c for c in clientes if inactivo(c, ahora)]
    elif filtro and filtro != "todos":
        clientes = [c for c in clientes if c["analisis"]["estado"] == filtro]
    t = str(texto or "").strip().casefold()
    if t:
        t_nit = "".join(ch for ch in t if ch.isdigit())
        clientes = [c for c in clientes if t in c["nombre"].casefold() or (t_nit and t_nit in c["nit"])]
    return list(clientes)


def ordenar_clientes(clientes, criterio):
    if criterio == "avance_menor":
        return sorted(clientes, key=lambda c: c["analisis"]["pct"])
    if criterio == "avance_mayor":
        return sorted(clientes, key=lambda c: -c["analisis"]["pct"])
    if criterio == "nombre":
        return sorted(clientes, key=lambda c: c["nombre"].casefold())
    return sorted(clientes, key=lambda c: c["ultima"] or _MIN_FECHA, reverse=True)


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


def serie_global_por_dia(historial):
    """[(fecha, avance global)] al cierre de cada día con actividad, reconstruido del historial: para cada día se toma el último valor conocido
    de cada plantilla y se aplican las mismas reglas del panel. Las fechas son de Colombia."""
    filas = sorted((f for f in (historial or []) if fecha_utc(f.get("registrado_en")) and _numero(f.get("cumplimiento")) is not None),
                   key=lambda f: fecha_utc(f["registrado_en"]))
    dias = sorted({hora_colombia(fecha_utc(f["registrado_en"])).date() for f in filas})
    serie = []
    for dia in dias:
        ultimo = {}
        for f in filas:
            if hora_colombia(fecha_utc(f["registrado_en"])).date() <= dia:
                ultimo[(f.get("etapa"), normalizar_nombre(f.get("plantilla")))] = {
                    "etapa": f.get("etapa"), "plantilla": f.get("plantilla"), "cumplimiento": f.get("cumplimiento"),
                    "estado": f.get("estado") or "requiere_correcciones"}
        a = analizar_cliente(list(ultimo.values()))
        serie.append((dia, pct_visible(a["pct"], a["estado"])))
    return serie


# ─────────────────────────────────────────────────────────────────────────────
# HTML (el diseño del boceto; todo texto de usuario pasa por _e)
# ─────────────────────────────────────────────────────────────────────────────
def _barra(pct, color, alto=6):
    return (f'<div style="height:{alto}px;background:#E3EAF4;border-radius:{alto // 2}px;margin-top:4px">'
            f'<div style="height:{alto}px;width:{max(0, min(100, pct))}%;background:{color};border-radius:{alto // 2}px"></div></div>')


def _chip(estado):
    s = ESTADOS[estado]
    return (f'<span style="display:inline-block;padding:4px 10px;border-radius:999px;font-size:13px;font-weight:600;background:{s["fondo"]};'
            f'color:{s["color"]};white-space:nowrap">{s["texto"]}</span>')


def html_encabezado(titulo, derecha=""):
    """Banda azul de arriba. `titulo` y `derecha` ya vienen escapados (los textos de usuario se escapan antes de llegar aquí)."""
    return (f'<header style="background:#1B3A6B;color:#FFFFFF;padding:22px 32px;border-radius:12px;margin-bottom:16px">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap"><div>'
            f'<div style="font-size:14px;color:#C9D8EE;font-weight:600">Asistente y Validador de Migración — SINCO A&amp;F</div>'
            f'<h1 style="margin:2px 0 0;font-size:30px;font-weight:700;color:#FFFFFF;padding:0">{titulo}</h1></div>'
            f'<div style="font-size:14px;color:#C9D8EE">{derecha}</div></div></header>')


def html_tarjetas_resumen(r):
    def tarjeta(etiqueta, valor, punto=None):
        marca = f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{punto};margin-right:8px"></span>' if punto else ""
        return (f'<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:16px 18px">'
                f'<div style="font-size:14px;color:#506078;font-weight:600">{marca}{etiqueta}</div>'
                f'<div style="font-size:36px;font-weight:700;line-height:1.1;margin-top:4px;color:#0F1E36">{valor}</div></div>')
    return ('<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px;margin-bottom:8px">'
            + tarjeta("Clientes registrados", r["registrados"]) + tarjeta("Completados", r["completados"], "#2E9D5B")
            + tarjeta("Requieren correcciones", r["requieren"], "#D14343") + tarjeta("En proceso", r["en_proceso"], "#E0A021")
            + tarjeta(f"Sin actividad hace más de {DIAS_SIN_ACTIVIDAD} días", r["inactivos"], "#7B8BA3") + '</section>')


def _celda_etapa(e):
    if not e["aplica"]:
        return '<td style="padding:14px 10px;vertical-align:middle"><div style="font-size:14px;font-weight:600;color:#506078">No aplica</div></td>'
    s = ESTADOS[e["estado"]]
    v = pct_visible(e["pct"], e["estado"])
    color_texto = "#506078" if e["estado"] == "pendiente" else "#0F1E36"
    return (f'<td style="padding:14px 10px;vertical-align:middle"><div style="font-size:15px;font-weight:600;color:{color_texto}">{v}%</div>'
            f'{_barra(v, s["barra"])}</td>')


def html_tabla_clientes(clientes, sin_identificar, ahora):
    cabecera = "".join(f'<th scope="col" style="padding:12px 12px;font-size:13px;font-weight:700;color:#33445E;text-align:left">{t}</th>'
                       for t in ("Cliente", "Avance global", "Estado", "Etapa 1", "Etapa 2", "Etapa 3", "Etapa 4", "Requiere atención", "Última actividad"))
    filas = []
    for c in clientes:
        a = c["analisis"]
        v = pct_visible(a["pct"], a["estado"])
        ultima = hace_texto(c["ultima"], ahora)
        celda_ultima = f'<span style="color:#7A4504;font-weight:700">● {ultima}</span>' if inactivo(c, ahora) else ultima
        filas.append(
            '<tr style="border-top:1px solid #E3EAF4">'
            f'<td style="padding:14px 12px;vertical-align:middle"><div style="font-weight:700;color:#0F1E36">{_e(c["nombre"])}</div>'
            f'<div style="font-size:13px;color:#506078">NIT {_e(nit_con_puntos(c["nit"]))}</div></td>'
            f'<td style="padding:14px 12px;vertical-align:middle"><div style="font-weight:700;font-size:18px;color:#0F1E36">{v}%</div>'
            f'{_barra(v, ESTADOS[a["estado"]]["barra"], 8)}</td>'
            f'<td style="padding:14px 12px;vertical-align:middle">{_chip(a["estado"])}</td>'
            + "".join(_celda_etapa(a["etapas"][n]) for n in (1, 2, 3, 4))
            + f'<td style="padding:14px 12px;vertical-align:middle;font-size:14px;color:#33445E">{_e(requiere_atencion(a))}</td>'
            f'<td style="padding:14px 12px;vertical-align:middle;font-size:14px;color:#33445E">{celda_ultima}</td></tr>')
    recientes = [s for s in sin_identificar or [] if (_numero(s.get("usos_14_dias")) or 0) > 0]
    if recientes:
        usos = sum(int(_numero(s.get("usos_14_dias")) or 0) for s in recientes)
        etapa = min(int(_numero(s.get("etapa")) or 0) for s in recientes) or 1
        ultimo = max((fecha_utc(s.get("ultimo_uso")) for s in recientes if fecha_utc(s.get("ultimo_uso"))), default=None)
        filas.append(
            '<tr style="border-top:1px solid #E3EAF4">'
            '<td style="padding:14px 12px;vertical-align:middle"><div style="font-weight:700;color:#0F1E36">Sin identificar</div>'
            '<div style="font-size:13px;color:#506078">Uso sin NIT</div></td>'
            f'<td colspan="6" style="padding:14px 12px;vertical-align:middle;font-size:14px;color:#33445E">{usos} validaciones sin NIT en las últimas 2 semanas. '
            'No se puede calcular el avance de un cliente sin identificar.</td>'
            f'<td style="padding:14px 12px;vertical-align:middle;font-size:14px;color:#33445E">Etapa {etapa}: falta el NIT</td>'
            f'<td style="padding:14px 12px;vertical-align:middle;font-size:14px;color:#33445E">{hace_texto(ultimo, ahora)}</td></tr>')
    return ('<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;overflow-x:auto;margin-top:8px">'
            '<table style="width:100%;border-collapse:collapse;min-width:980px"><thead><tr style="background:#EAF0F8">' + cabecera + '</tr></thead><tbody>'
            + "".join(filas) + '</tbody></table></div>')


def html_leyenda():
    chips = "".join(_chip(k) for k in ("pendiente", "en_proceso", "requiere_correcciones", "completado"))
    return (f'<div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-top:14px"><div style="display:flex;gap:8px;flex-wrap:wrap">{chips}</div>'
            '<div style="font-size:13px;color:#506078;max-width:640px;line-height:1.4">Avance global = promedio de las etapas que aplican a cada cliente; las que dicen '
            '"No aplica" no cuentan. Una etapa queda Completada solo cuando todas sus plantillas esperadas están cargadas y sin errores bloqueantes '
            '(Etapa 4: 100% conciliado).</div></div>')


_ORIGEN_NIT = {"informe": "Informes del sistema", "digitado": "Digitado por el usuario"}


def html_resumen_detalle(c, historial_visible, ahora):
    a = c["analisis"]
    v = pct_visible(a["pct"], a["estado"])
    fechas = [fecha_utc(f.get("registrado_en")) for f in historial_visible if fecha_utc(f.get("registrado_en"))]
    primera = hora_colombia(min(fechas)).strftime("%d/%m/%Y") if fechas else "—"
    ultima = hora_colombia(c["ultima"]).strftime("%d/%m/%Y · %H:%M") if c["ultima"] else "—"
    n_val = f"{len(historial_visible)}" if len(historial_visible) < 500 else "500+"

    def dato(etiqueta, valor):
        return (f'<div><div style="font-size:13px;color:#506078;font-weight:600">{etiqueta}</div>'
                f'<div style="font-size:18px;font-weight:700;color:#0F1E36;margin-top:2px">{valor}</div></div>')
    return (f'<div style="display:grid;grid-template-columns:minmax(260px,1fr) 2fr;gap:16px;margin-bottom:16px">'
            f'<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:18px 20px"><div style="font-size:14px;color:#506078;font-weight:600">Avance global</div>'
            f'<div style="display:flex;align-items:center;gap:12px;margin-top:4px"><div style="font-size:44px;font-weight:700;color:#0F1E36;line-height:1.1">{v}%</div>{_chip(a["estado"])}</div>'
            f'{_barra(v, ESTADOS[a["estado"]]["barra"], 10)}'
            f'<div style="font-size:13px;color:#506078;margin-top:8px">Promedio de las {a["n_aplican"]} etapas que aplican a este cliente</div></div>'
            f'<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:18px 20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;align-content:center">'
            + dato("Primera actividad", primera) + dato("Última actividad", ultima) + dato("Validaciones realizadas", n_val)
            + (dato("Etapas que aplican", f'{a["n_aplican"]} de 4') if a["n_aplican"] < 4         # como en el boceto: reemplaza al origen del NIT, que
               else dato("Origen del NIT", _e(_ORIGEN_NIT.get(c.get("fuente_nit"), "—")))) + '</div></div>')                  # ya está en la banda azul


def _detalle_texto_etapa(e, etapas):
    n = e["etapa"]
    if n == 4:
        if not e["cargadas"]:
            return "Se habilita al aprobar la Etapa 3" if etapas[3]["estado"] != "completado" else "Falta ejecutar la conciliación"
        if e["con_errores"]:
            return f'{100 - pct_visible(e["pct"], e["estado"])}% de los registros sin conciliar'
        return "Todo conciliado"
    base = f'{e["cargadas_esperadas"]} de {e["esperadas"]} plantillas esperadas'
    if e["con_errores"]:
        return f'{base} · {len(e["con_errores"])} con errores'
    if e["faltantes"]:
        return f'{base} · falta {", ".join(etiqueta_corta(x) for x in e["faltantes"])}'
    return f"{base} · sin errores"


def html_tarjetas_etapas(c):
    a = c["analisis"]
    tarjetas = []
    for n in sorted(a["etapas"]):
        e = a["etapas"][n]
        if not e["aplica"]:
            motivo = (f'el cliente empezó en la Etapa {a["primera_etapa"]}.' if a["primera_etapa"] and n < a["primera_etapa"]
                      else "el cliente avanzó a una etapa posterior sin usarla.")
            cuerpo = ('<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px"><div style="font-size:30px;font-weight:700;color:#506078">No aplica</div>'
                      '<span style="display:inline-block;padding:4px 10px;border-radius:999px;font-size:13px;font-weight:600;background:#E3EAF4;color:#33445E;white-space:nowrap">No aplica</span></div>'
                      f'<div style="font-size:13px;color:#506078;margin-top:10px;line-height:1.4">Se omitió: {motivo} '
                      'No cuenta en el promedio; si la usa después, vuelve a contar.</div>')
        else:
            s = ESTADOS[e["estado"]]
            v = pct_visible(e["pct"], e["estado"])
            color = "#506078" if e["estado"] == "pendiente" else "#0F1E36"
            cuerpo = (f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:6px"><div style="font-size:34px;font-weight:700;color:{color}">{v}%</div>{_chip(e["estado"])}</div>'
                      f'{_barra(v, s["barra"], 8)}<div style="font-size:13px;color:#506078;margin-top:8px;line-height:1.4">{_e(_detalle_texto_etapa(e, a["etapas"]))}</div>')
        fondo = "#FFFFFF" if e["aplica"] else "#F7F9FC"
        tarjetas.append(f'<div style="background:{fondo};border:1px solid #D9E2EF;border-radius:10px;padding:16px 18px"><div style="font-size:13px;color:#506078;font-weight:700">Etapa {n}</div>'
                        f'<div style="font-size:18px;font-weight:700;color:#0F1E36;margin-top:2px">{NOMBRES_ETAPA[n]}</div>{cuerpo}</div>')
    explicacion = ('<p style="margin:0 0 16px;font-size:14px;color:#506078;max-width:820px;line-height:1.5">Se marca "No aplica" automáticamente a toda etapa que el cliente no usó y '
                   'que quedó atrás porque avanzó a una posterior. Si la usa más adelante, vuelve a contar en el promedio. Las Etapas 3 y 4 siempre aplican juntas, porque el '
                   'cliente puede ir y volver entre ellas. Los directores no tienen que configurar nada.</p>') if a["n_aplican"] < 4 else ""
    return ('<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:16px">' + "".join(tarjetas) + '</section>' + explicacion)


def html_pendientes(c):
    """Una sección «Pendientes de la Etapa N» por cada etapa que requiere correcciones: cumplimiento por plantilla y qué falta."""
    secciones = []
    for n, e in sorted(c["analisis"]["etapas"].items()):
        if e["estado"] != "requiere_correcciones":
            continue
        barras = []
        for f in e["cargadas"]:
            v = pct_visible(f.get("cumplimiento"), f.get("estado"))
            total, errores = int(_numero(f.get("filas_evaluadas")) or 0), int(_numero(f.get("filas_con_error")) or 0)
            color = ESTADOS["completado" if f.get("estado") == "completado" else "requiere_correcciones"]["barra"]
            barras.append(f'<div style="flex:1;min-width:210px"><div style="display:flex;justify-content:space-between;gap:8px;font-size:15px;font-weight:700;color:#0F1E36">'
                          f'<span>{_e(nombre_visible(f.get("plantilla")))}</span><span>{v}%</span></div>{_barra(v, color, 8)}'
                          f'<div style="font-size:13px;color:#506078;margin-top:4px">{miles(total - errores)} de {miles(total)} registros sin error</div></div>')
        filas = "".join(f'<tr style="border-top:1px solid #E3EAF4"><td style="padding:10px 12px;font-size:14px;color:#33445E">{_e(nombre_visible(p["plantilla"]))}</td>'
                        f'<td style="padding:10px 12px;font-size:14px;font-weight:700;color:#0F1E36">{_e(p["que_falta"])}</td>'
                        f'<td style="padding:10px 12px;font-size:14px;color:#33445E">{_e(p["columna"])}</td>'
                        f'<td style="padding:10px 12px;font-size:14px;font-weight:700;color:#0F1E36;text-align:right">{miles(p["casos"])}</td></tr>'
                        for p in pendientes_de(e["cargadas"]))
        encabezados = "".join(f'<th scope="col" style="padding:10px 12px;font-size:13px;font-weight:700;color:#33445E;text-align:{al}">{t}</th>'
                              for t, al in (("Plantilla", "left"), ("Qué falta", "left"), ("Columna", "left"), ("Casos", "right")))
        tabla = (f'<div style="border:1px solid #D9E2EF;border-radius:8px;overflow-x:auto;margin-top:14px"><table style="width:100%;border-collapse:collapse">'
                 f'<thead><tr style="background:#EAF0F8">{encabezados}</tr></thead><tbody>{filas}</tbody></table></div>') if filas else ""
        secciones.append(f'<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:18px 20px;margin-bottom:16px">'
                         f'<div style="font-size:20px;font-weight:700;color:#0F1E36">Pendientes de la Etapa {n}</div>'
                         f'<div style="font-size:14px;color:#506078;margin:2px 0 12px">Cumplimiento por plantilla y qué falta resolver</div>'
                         f'<div style="display:flex;gap:24px;flex-wrap:wrap">{"".join(barras)}</div>{tabla}'
                         f'<div style="font-size:13px;color:#506078;margin-top:12px">Solo se registran la categoría del error, la columna y la cantidad de casos. '
                         f'No se guardan valores de celdas ni datos de terceros.</div></div>')
    if not secciones:
        return ('<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:18px 20px;margin-bottom:16px;font-size:15px;color:#33445E">'
                'Este cliente no tiene errores pendientes en las plantillas que ha cargado.</div>')
    return "".join(secciones)


def serie_para_grafica(historial, analisis):
    """La serie del historial, con la última marca igual al avance global ACTUAL: así la gráfica y la tarjeta «Avance global» nunca muestran dos
    números distintos (el historial trae como máximo 500 movimientos y podría no tener todo)."""
    serie = serie_global_por_dia(historial)
    if serie:
        serie[-1] = (serie[-1][0], pct_visible(analisis["pct"], analisis["estado"]))
    return serie


def html_grafica(serie):
    """Línea del avance global al cierre de cada día (SVG sin librerías). Con menos de 2 días no hay línea que dibujar."""
    if len(serie) < 2:
        return '<div style="font-size:14px;color:#506078;padding:14px 0">Todavía no hay suficientes días de actividad para mostrar la evolución.</div>'
    ancho, alto, izq, der, arr, aba = 380, 170, 42, 22, 26, 30

    def x(i):
        return izq + (ancho - izq - der) * i / (len(serie) - 1)

    def y(p):
        return arr + (alto - arr - aba) * (1 - p / 100)
    puntos = [(x(i), y(p)) for i, (_, p) in enumerate(serie)]
    guias = "".join(f'<line x1="{izq}" x2="{ancho - der}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="#E3EAF4"/>'
                    f'<text x="{izq - 6}" y="{y(p) + 4:.1f}" font-size="11" fill="#506078" text-anchor="end">{p}%</text>' for p in (0, 50, 100))
    paso = max(1, len(serie) // 5)
    etiquetas = "".join(f'<text x="{x(i):.1f}" y="{alto - 8}" font-size="11" fill="#506078" text-anchor="middle">{d:%d/%m}</text>'
                        for i, (d, _) in enumerate(serie) if i % paso == 0 or i == len(serie) - 1)
    linea = " ".join(f"{px:.1f},{py:.1f}" for px, py in puntos)
    marcas = "".join(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{5 if i == len(puntos) - 1 else 3.5}" fill="#2B5A9B"/>' for i, (px, py) in enumerate(puntos))
    ultimo = f'<text x="{puntos[-1][0]:.1f}" y="{puntos[-1][1] - 10:.1f}" font-size="13" font-weight="700" fill="#0F1E36" text-anchor="middle">{serie[-1][1]}%</text>'
    return (f'<svg viewBox="0 0 {ancho} {alto}" width="100%" role="img" aria-label="Avance global al cierre de cada día">{guias}'
            f'<polyline points="{linea}" fill="none" stroke="#2B5A9B" stroke-width="2.5"/>{marcas}{ultimo}{etiquetas}</svg>')


def _antes(fila):
    n = _numero(fila.get("cumplimiento_antes"))
    return "Primera carga" if n is None else porcentaje_entero(n)


def html_historial(serie, recientes):
    filas = "".join(
        f'<div style="display:flex;gap:12px;align-items:center;justify-content:space-between;padding:10px 0;border-top:1px solid #E3EAF4">'
        f'<div style="font-size:12px;color:#506078;min-width:48px">{hora_colombia(fecha_utc(f.get("registrado_en"))):%d/%m}<br>{hora_colombia(fecha_utc(f.get("registrado_en"))):%H:%M}</div>'
        f'<div style="flex:1;font-size:14px;font-weight:700;color:#0F1E36">{_e(nombre_visible(f.get("plantilla")))}'
        f'<div style="font-size:13px;font-weight:400;color:#506078">Etapa {_e(f.get("etapa"))}</div></div>'
        f'<div style="font-size:14px;font-weight:700;color:#0F1E36;white-space:nowrap">{_antes(f)} → {porcentaje_entero(f.get("cumplimiento"))}</div></div>'
        for f in recientes)
    return ('<div style="background:#FFFFFF;border:1px solid #D9E2EF;border-radius:10px;padding:18px 20px"><div style="font-size:20px;font-weight:700;color:#0F1E36">Historial de uso</div>'
            '<div style="font-size:14px;color:#506078;margin:2px 0 8px">Avance global al cierre de cada día</div>' + html_grafica(serie)
            + (filas or '<div style="font-size:14px;color:#506078;padding:10px 0">Todavía no hay movimientos.</div>') + '</div>')


# ─────────────────────────────────────────────────────────────────────────────
# Pantalla
# ─────────────────────────────────────────────────────────────────────────────
def _estilo(st):
    st.markdown("""<style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display: none !important; }
    .stApp { background: #F3F6FB !important; }
    .block-container { max-width: 1360px !important; padding-top: 3.2rem !important; padding-left: 2rem !important; padding-right: 2rem !important; }
    </style>""", unsafe_allow_html=True)


def _salir(st):
    for k in ("_panel_codigo", "_panel_datos", "_panel_cargado", "_panel_historial", "_panel_vista"):
        st.session_state.pop(k, None)


def _pedir_resumen(st, cfg):
    cuerpo = consultar(cfg[0], cfg[1], "panel_resumen", {"p_codigo": st.session_state["_panel_codigo"]})
    st.session_state["_panel_datos"] = cuerpo
    st.session_state["_panel_cargado"] = datetime.now(timezone.utc)
    st.session_state["_panel_historial"] = {}


def _pantalla_de_acceso(st, cfg):
    st.markdown(html_encabezado("Panel de seguimiento", "Acceso para directores"), unsafe_allow_html=True)
    with st.form("panel_acceso"):
        codigo = st.text_input("Código de directores", type="password", key="panel_codigo")
        entrar = st.form_submit_button("Entrar", width="stretch")
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


def _con_aviso_si_falla(st, cfg):
    """Pide los datos de nuevo; si falla (el código cambió o la base no responde), se vuelve a pedir el código con el motivo."""
    try:
        _pedir_resumen(st, cfg)
        return True
    except ErrorPanel as e:
        _salir(st)
        st.session_state["_panel_aviso"] = MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"])
        return False


def _pantalla_general(st, cfg, clientes, datos, ahora):
    hora = hora_colombia(st.session_state["_panel_cargado"])
    hoy = hora_colombia(ahora).date()
    st.markdown(html_encabezado("Panel de seguimiento", f"Actualizado hoy {hora:%H:%M}" if hora.date() == hoy
                                else f"Actualizado el {hora:%d/%m/%Y} a las {hora:%H:%M}"), unsafe_allow_html=True)
    c1, c2, _ = st.columns([1, 1, 6])
    if c1.button("🔄 Actualizar", width="stretch"):
        _con_aviso_si_falla(st, cfg)
        st.rerun()
    if c2.button("Salir", width="stretch"):
        _salir(st)
        st.rerun()
    if not clientes:
        st.info("Todavía no hay clientes con avance registrado.")
        return
    st.markdown(html_tarjetas_resumen(resumen_general(clientes, ahora)), unsafe_allow_html=True)

    cuentas = contar_filtros(clientes, ahora)
    etiquetas = {k: f"{t} ({cuentas[k]})" for k, t in FILTROS}
    b1, b2 = st.columns([2, 3])
    texto = b1.text_input("Buscar por nombre o NIT", key="panel_buscar", placeholder="Escribe parte del nombre o el NIT")
    filtro = b2.radio("Filtrar por estado", [k for k, _ in FILTROS], format_func=lambda k: etiquetas[k], horizontal=True, key="panel_filtro")
    elegido_orden = st.selectbox("Ordenar por", [t for _, t in ORDENES], key="panel_orden")
    orden = next(k for k, t in ORDENES if t == elegido_orden)
    visibles = ordenar_clientes(filtrar_clientes(clientes, filtro, texto, ahora), orden)
    if visibles or filtro == "todos":
        st.markdown(html_tabla_clientes(visibles, datos.get("sin_identificar"), ahora), unsafe_allow_html=True)
    if not visibles:
        st.caption("Ningún cliente coincide con la búsqueda o el filtro.")
    else:
        opciones = {f"{c['nombre']} — NIT {nit_con_puntos(c['nit'])}": c["nit"] for c in visibles}
        d1, d2 = st.columns([4, 1])
        elegido = d1.selectbox("Ver el detalle de un cliente", list(opciones), key="panel_empresa")
        d2.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        if d2.button("Abrir detalle →", width="stretch", key="panel_abrir"):
            st.session_state["_panel_vista"] = opciones[elegido]
            st.rerun()
    st.markdown(html_leyenda(), unsafe_allow_html=True)


def _pantalla_detalle(st, pd, cfg, cliente, ahora):
    if st.button("← Volver al panel", key="panel_volver"):
        st.session_state.pop("_panel_vista", None)
        st.rerun()
    hist = st.session_state.setdefault("_panel_historial", {})
    aviso = None
    if cliente["nit"] not in hist:
        try:
            hist[cliente["nit"]] = consultar(cfg[0], cfg[1], "panel_historial",
                                             {"p_codigo": st.session_state["_panel_codigo"], "p_nit": cliente["nit"]}).get("historial") or []
        except ErrorPanel as e:
            aviso = MENSAJES_ERROR.get(e.tipo, MENSAJES_ERROR["sin_conexion"])
    visibles, ocultas = colapsar_rebotes(hist.get(cliente["nit"], []))
    origen = _ORIGEN_NIT.get(cliente.get("fuente_nit"))
    nit_linea = f'NIT {_e(nit_con_puntos(cliente["nit"]))}' + (f' · Identificado a partir de: {_e(origen)}' if origen else "")
    st.markdown(html_encabezado(_e(cliente["nombre"]), nit_linea), unsafe_allow_html=True)
    st.markdown(html_resumen_detalle(cliente, visibles, ahora), unsafe_allow_html=True)
    st.markdown(html_tarjetas_etapas(cliente), unsafe_allow_html=True)
    izq, der = st.columns([3, 2])
    with izq:
        st.markdown(html_pendientes(cliente), unsafe_allow_html=True)
    with der:
        st.markdown(html_historial(serie_para_grafica(hist.get(cliente["nit"], []), cliente["analisis"]), visibles[:5]), unsafe_allow_html=True)
        if aviso:
            st.warning(aviso)
        if len(visibles) > 5:
            with st.expander(f"Ver las {len(visibles)} validaciones"):
                st.dataframe(pd.DataFrame([{"Fecha": hora_colombia(fecha_utc(f.get("registrado_en"))), "Plantilla": nombre_visible(f.get("plantilla")),
                                            "Etapa": f"Etapa {f.get('etapa')}", "Antes": porcentaje_texto(f.get("cumplimiento_antes")),
                                            "Ahora": porcentaje_texto(f.get("cumplimiento"))} for f in visibles]),
                             hide_index=True, width="stretch",
                             column_config={"Fecha": st.column_config.DatetimeColumn("Fecha", format="DD/MM/YYYY HH:mm")})
        if ocultas:
            st.caption(f"Se ocultaron {ocultas} movimientos que se revirtieron en menos de un minuto (alguien cambió un archivo y lo volvió a poner).")


def render_panel():
    """Dibuja el panel (acceso, vista general o detalle de un cliente). La app lo llama cuando la dirección trae ?panel=1."""
    import pandas as pd
    import streamlit as st
    _estilo(st)
    try:
        cfg = leer_configuracion(st.secrets.get("seguimiento", {}))
    except Exception:
        cfg = None
    if cfg is None:
        st.markdown(html_encabezado("Panel de seguimiento", "Panel de directores"), unsafe_allow_html=True)
        st.error(MENSAJES_ERROR["no_configurado"])
        return
    aviso = st.session_state.pop("_panel_aviso", None)
    if not (st.session_state.get("_panel_codigo") and st.session_state.get("_panel_datos")):
        _pantalla_de_acceso(st, cfg)
        if aviso:
            st.warning(aviso)
        return
    ahora = datetime.now(timezone.utc)
    if (ahora - st.session_state.get("_panel_cargado", ahora)).total_seconds() > REFRESCO_AUTOMATICO_SEG:
        if not _con_aviso_si_falla(st, cfg):
            st.rerun()
    datos = st.session_state["_panel_datos"]
    clientes = agrupar_clientes(datos.get("avance"))
    vista = st.session_state.get("_panel_vista")
    cliente = next((c for c in clientes if c["nit"] == vista), None)
    if cliente is not None:
        _pantalla_detalle(st, pd, cfg, cliente, ahora)
    else:
        st.session_state.pop("_panel_vista", None)
        _pantalla_general(st, cfg, clientes, datos, ahora)
