"""Seguimiento del avance de los clientes (solo para los directores).

Qué hace: al terminar de validar una plantilla (o una conciliación), manda a Supabase un
RESUMEN (conteos y porcentajes) para que el panel de directores muestre el avance de cada
cliente. NUNCA envía valores de celdas, textos de error ni datos de terceros.

Reglas de diseño (no romper):
  * Apagado por defecto. Se enciende con  activo = true  en los Secrets de Streamlit:
        [seguimiento]
        activo = true
        url = "https://<proyecto>.supabase.co"
        clave_publica = "sb_publishable_..."
  * Nunca debe afectar la app: cualquier fallo se registra en el log y se ignora.
  * Cero cálculo cuando está apagado (solo se consulta un secret).
  * Solo envía cuando el resumen CAMBIÓ respecto a lo último enviado en esa sesión, y tras un
    fallo de red deja de intentar por unos minutos (la app no se vuelve lenta si Supabase cae).
  * La llave pública solo puede ejecutar registrar_avance() en la base: no puede leer nada.
"""
import hashlib
import json
import logging
import re
import time

VERSION = "seg-1.0"
SIN_IDENTIFICAR = "SIN-IDENTIFICAR"
TIMEOUT_SEG = 3                 # espera máxima por envío
PAUSA_TRAS_FALLO_SEG = 120      # tras un fallo, no se reintenta durante este tiempo
MAX_PENDIENTES = 20             # límite que también valida la base de datos
MAX_BYTES_PENDIENTES = 5500     # la base rechaza más de 6000

_log = logging.getLogger("seguimiento")


# ─────────────────────────────────────────────────────────────────────────────
# Identificación del cliente
# ─────────────────────────────────────────────────────────────────────────────
def dv_nit(base):
    """Dígito de verificación de un NIT colombiano (algoritmo de la DIAN)."""
    pesos = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
    digitos = [int(c) for c in str(base) if c.isdigit()][::-1]
    if not digitos or len(digitos) > len(pesos):
        return None
    residuo = sum(d * p for d, p in zip(digitos, pesos)) % 11
    return residuo if residuo in (0, 1) else 11 - residuo


def normalizar_nit(texto):
    """NIT sin puntos, comas ni dígito de verificación: '901,652,178 -8' -> '901652178'.

    Si no trae guion pero son 10 dígitos que empiezan por 8 o 9 y el último es el dígito de
    verificación correcto, se quita (el mismo cliente escrito como '9016521788').
    Devuelve '' si no parece un NIT (la base acepta de 5 a 12 dígitos)."""
    s = str(texto or "").strip()
    if not s:
        return ""
    tiene_guion = "-" in s
    digitos = re.sub(r"\D", "", s.split("-")[0])
    if (not tiene_guion and len(digitos) == 10 and digitos[0] in "89"
            and dv_nit(digitos[:9]) == int(digitos[-1])):
        digitos = digitos[:9]
    return digitos if 5 <= len(digitos) <= 12 else ""


# ─────────────────────────────────────────────────────────────────────────────
# Resumen a partir de los resultados de validación ya calculados (no revalida nada)
# ─────────────────────────────────────────────────────────────────────────────
def _categoria_publica(clave, titulos=None):
    """Nombre de la categoría de error SIN datos del cliente. Si el texto trae números o
    barras (ej. 'DOCDESC|CI|26050001|...') se reemplaza por un nombre genérico."""
    clave = str(clave or "").strip()
    if titulos:
        titulo = (titulos.get(clave) or {}).get("titulo")
        if titulo:
            return str(titulo)[:80]
    if clave.startswith("DOCDESC"):
        return "Documento descuadrado"
    if clave.startswith("Plantilla desbalanceada"):
        return "Plantilla desbalanceada"
    texto = clave.rstrip(".")
    if not texto or re.search(r"[0-9|]", texto) or len(texto) > 70:
        return "Otra inconsistencia"
    return texto


def _acotar_pendientes(pendientes):
    """Deja la lista dentro de los límites que exige la base (20 elementos, ~6 KB)."""
    pendientes = pendientes[:MAX_PENDIENTES]
    while pendientes and len(json.dumps(pendientes, ensure_ascii=False).encode("utf-8")) > MAX_BYTES_PENDIENTES:
        pendientes.pop()
    return pendientes


def resumir_plantilla(errores, filas, advertencias_extra=0, titulos=None):
    """Resumen de una plantilla validada. errores: tuplas (fila, columna, tipo, mensaje, clave).

    Bloqueante = cualquier tipo distinto de 'advertencia' (misma regla que usa la app para decir
    "Listas para importar"). Cumplimiento = % de registros sin error bloqueante, con tope de 99
    mientras quede cualquier error (solo llega a 100 cuando la plantilla está lista).
    Devuelve None si la plantilla no tiene filas (no hay nada que seguir)."""
    filas = int(filas or 0)
    if filas <= 0:
        return None
    errores = list(errores or [])
    bloqueantes = [e for e in errores if e[2] != "advertencia"]
    advertencias = (len(errores) - len(bloqueantes)) + int(advertencias_extra or 0)
    filas_error = min(len({e[0] for e in bloqueantes if e[0] is not None}), filas)
    globales = sum(1 for e in bloqueantes if e[0] is None)

    cumplimiento = round(100.0 * (1 - filas_error / filas), 2)
    if bloqueantes:
        cumplimiento = min(cumplimiento, 99.0)

    grupos = {}
    for e in bloqueantes:
        k = (str(e[1] or "")[:60], _categoria_publica(e[4] if len(e) > 4 else "", titulos))
        grupos[k] = grupos.get(k, 0) + 1
    pendientes = [{"categoria": cat, "columna": col, "casos": n}
                  for (col, cat), n in sorted(grupos.items(), key=lambda x: -x[1])]
    return {
        "filas": filas, "filas_error": filas_error, "errores_globales": globales,
        "advertencias": advertencias, "cumplimiento": cumplimiento,
        "estado": "requiere_correcciones" if bloqueantes else "completado",
        "pendientes": _acotar_pendientes(pendientes),
    }


def resumir_conciliacion(total, no_conciliados, categorias=None):
    """Resumen de una conciliación: total de registros y cuántos quedaron con diferencia.
    categorias: {texto_del_tipo_de_diferencia: cantidad}."""
    total = int(total or 0)
    if total <= 0:
        return None
    no_conciliados = max(0, min(int(no_conciliados or 0), total))
    pendientes = []
    for texto, n in sorted((categorias or {}).items(), key=lambda x: -x[1]):
        limpio = re.sub(r"^[^A-Za-zÁÉÍÓÚÑáéíóúñ]+", "", str(texto)).strip()   # quita el emoji del inicio
        pendientes.append({"categoria": _categoria_publica(limpio), "columna": "Conciliación", "casos": int(n)})
    return {
        "filas": total, "filas_error": no_conciliados, "errores_globales": 0, "advertencias": 0,
        "cumplimiento": round(100.0 * (1 - no_conciliados / total), 2),
        "estado": "completado" if no_conciliados == 0 else "requiere_correcciones",
        "pendientes": _acotar_pendientes(pendientes),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Configuración (Secrets)
# ─────────────────────────────────────────────────────────────────────────────
def _es_verdadero(valor):
    """True solo si 'activo' está encendido DE VERDAD. Un texto como "false" o "no" escrito entre comillas
    NO enciende el seguimiento (en Python cualquier texto con contenido cuenta como verdadero)."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor == 1
    return str(valor or "").strip().lower() in ("true", "1", "si", "sí", "yes", "on")


def _configuracion(cfg):
    """(url, llave) si el seguimiento está encendido y bien configurado; None en cualquier otro caso."""
    cfg = cfg or {}
    if not _es_verdadero(cfg.get("activo")):
        return None
    url, clave = str(cfg.get("url") or "").strip(), str(cfg.get("clave_publica") or "").strip()
    if not clave or not url.lower().startswith(("https://", "http://")):    # solo http(s): nada de file:// ni ftp://
        return None
    return url, clave


# ─────────────────────────────────────────────────────────────────────────────
# Envío
# ─────────────────────────────────────────────────────────────────────────────
def limpiar_nombre(texto):
    """Nombre de la empresa sin espacios ni separadores sobrantes al final. El encabezado de los informes
    trae 'PROMOTORA BELONG S.A.S. -' (el guion es del formato, no del nombre). El punto de 'S.A.S.' se conserva."""
    return re.sub(r"[\s\-\u2013\u2014,:;]+$", "", re.sub(r"\s+", " ", str(texto or "")).strip())


def _armar_parametros(etapa, plantilla, resumen, nombre, nit_normalizado, fuente):
    """Los 13 parámetros de registrar_avance() (la función de la base no tiene valores por
    defecto, así que SIEMPRE se envían todos)."""
    if nit_normalizado:
        return {
            "p_nit": nit_normalizado,
            "p_nombre": (limpiar_nombre(nombre) or f"NIT {nit_normalizado}")[:160],
            "p_fuente": fuente, "p_etapa": int(etapa), "p_plantilla": str(plantilla)[:80],
            "p_filas": resumen["filas"], "p_filas_error": resumen["filas_error"],
            "p_errores_globales": resumen["errores_globales"], "p_advertencias": resumen["advertencias"],
            "p_cumplimiento": resumen["cumplimiento"], "p_estado": resumen["estado"],
            "p_pendientes": resumen["pendientes"], "p_version": VERSION,
        }
    # Sin NIT: la base solo anota que hubo uso (etapa y plantilla), sin calcular avance.
    return {
        "p_nit": SIN_IDENTIFICAR, "p_nombre": None, "p_fuente": None, "p_etapa": int(etapa),
        "p_plantilla": str(plantilla)[:80], "p_filas": None, "p_filas_error": None,
        "p_errores_globales": None, "p_advertencias": None, "p_cumplimiento": None,
        "p_estado": None, "p_pendientes": None, "p_version": VERSION,
    }


def _enviar_http(url, clave, parametros):
    """Llama a la función registrar_avance() de Supabase. Lanza excepción si algo falla."""
    import urllib.error                     # aquí y no arriba: cargarlos pesa y solo hacen falta al enviar
    import urllib.request
    cabeceras = {"apikey": clave, "Content-Type": "application/json"}
    if clave.startswith("eyJ"):                 # llave antigua (JWT): también va como Bearer
        cabeceras["Authorization"] = f"Bearer {clave}"
    peticion = urllib.request.Request(
        url.rstrip("/") + "/rest/v1/rpc/registrar_avance",
        data=json.dumps(parametros).encode("utf-8"), headers=cabeceras, method="POST")
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_SEG) as r:
            r.read()
    except urllib.error.HTTPError as e:
        detalle = ""
        try:
            detalle = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {detalle}") from None


def registrar(etapa, plantilla, resumen, nombre, nit, fuente, estado, cfg, enviar=None, ahora=None):
    """Envía el resumen si cambió. Nunca lanza excepciones.

    estado: diccionario de la sesión (guarda lo ya enviado y la pausa tras un fallo).
    cfg: la sección [seguimiento] de los Secrets.
    Devuelve: 'apagado' | 'sin_resumen' | 'sin_cambios' | 'pausado' | 'enviado' | 'error'."""
    try:
        configuracion = _configuracion(cfg)
        if configuracion is None:
            return "apagado"
        url, clave = configuracion
        nit_n = normalizar_nit(nit)
        if nit_n and resumen is None:
            return "sin_resumen"
        parametros = _armar_parametros(etapa, plantilla, resumen, nombre, nit_n, fuente)
        firma = hashlib.sha1(json.dumps(parametros, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        firmas = estado.setdefault("firmas", {})
        clave_firma = f"{etapa}|{plantilla}"
        if firmas.get(clave_firma) == firma:
            return "sin_cambios"
        ahora = time.time() if ahora is None else ahora
        if ahora < estado.get("pausa_hasta", 0):
            return "pausado"
        try:
            (enviar or _enviar_http)(url, clave, parametros)
        except Exception as e:
            estado["pausa_hasta"] = ahora + PAUSA_TRAS_FALLO_SEG
            _log.warning("No se pudo registrar el avance (se reintenta en %s s): %s", PAUSA_TRAS_FALLO_SEG, e)
            return "error"
        firmas[clave_firma] = firma
        estado.pop("pausa_hasta", None)
        return "enviado"
    except Exception as e:                              # nada de esto debe tumbar la app
        _log.warning("Error inesperado en el seguimiento: %s", e)
        return "error"


# ─────────────────────────────────────────────────────────────────────────────
# Puntos de entrada para la app (usan los Secrets y la sesión de Streamlit)
# ─────────────────────────────────────────────────────────────────────────────
def _contexto():
    import streamlit as st
    try:
        cfg = dict(st.secrets.get("seguimiento", {}) or {})
    except Exception:
        cfg = {}
    return cfg, st.session_state.setdefault("_seg_estado", {})


def activo():
    """True si el seguimiento está encendido. Es lo único que se evalúa cuando está apagado."""
    try:
        cfg, _ = _contexto()
        return _configuracion(cfg) is not None
    except Exception:
        return False


def seguir_plantilla(etapa, plantilla, errores, filas, nombre, nit, fuente, advertencias_extra=0, titulos=None):
    """Registra el resultado de validar una plantilla (Etapas 1, 2 y 3)."""
    cfg, estado = _contexto()
    if _configuracion(cfg) is None:
        return "apagado"
    resumen = resumir_plantilla(errores, filas, advertencias_extra, titulos)
    return registrar(etapa, plantilla, resumen, nombre, nit, fuente, estado, cfg)


def seguir_conciliacion(tipo_label, total, no_conciliados, categorias, nombre, nit):
    """Registra el resultado de una conciliación (Etapa 4)."""
    cfg, estado = _contexto()
    if _configuracion(cfg) is None:
        return "apagado"
    resumen = resumir_conciliacion(total, no_conciliados, categorias)
    return registrar(4, f"Conciliación {tipo_label}", resumen, nombre, nit, "informe", estado, cfg)
