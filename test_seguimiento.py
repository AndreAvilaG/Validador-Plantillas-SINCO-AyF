"""Pruebas del seguimiento del avance (seguimiento.py) y del código de acceso.

Cómo correrlas (desde la raíz del repositorio):
    pip install pytest
    pytest pruebas

Todos los datos son inventados: no se deben agregar archivos de clientes a este repositorio.

La prueba de punta a punta contra una base PostgreSQL se omite sola; para correrla hace falta una
base donde ya se ejecutó seguimiento_supabase_fase0.sql y definir la variable de entorno
SEGUIMIENTO_PG_DSN (por ejemplo "dbname=prueba_final user=postgres") y tener psycopg2 instalado.
"""
import ast
import http.server
import json
import os
import sys
import threading

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
import seguimiento as seg  # noqa: E402

PARAMETROS = {"p_nit", "p_nombre", "p_fuente", "p_etapa", "p_plantilla", "p_filas", "p_filas_error",
              "p_errores_globales", "p_advertencias", "p_cumplimiento", "p_estado", "p_pendientes", "p_version"}
CFG = {"activo": True, "url": "https://ejemplo.supabase.co", "clave_publica": "sb_publishable_ejemplo"}


# ───────────────────────── Identificación del cliente ─────────────────────────
@pytest.mark.parametrize("base,dv", [("901652178", 8), ("830063800", 7), ("900854881", 1),
                                     ("860522565", 1),   # regresión: calcular_dv() daba 0 cuando el residuo era 1
                                     ("900931936", 8)])
def test_digito_de_verificacion_nit(base, dv):
    assert seg.dv_nit(base) == dv


@pytest.mark.parametrize("entrada,esperado", [
    ("901,652,178 -8", "901652178"),       # así llega del encabezado de los informes
    ("901652178-8", "901652178"),
    ("900.123.456-7", "900123456"),
    ("901652178", "901652178"),            # sin dígito de verificación
    ("9016521788", "901652178"),           # dígito de verificación pegado y correcto: se quita
    ("9016521789", "9016521789"),          # el último dígito no es el de verificación: se deja
    ("", ""), (None, ""), ("abc", ""), ("123", ""), ("1234567890123", ""),
])
def test_normalizar_nit(entrada, esperado):
    assert seg.normalizar_nit(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("PROMOTORA BELONG S.A.S. -", "PROMOTORA BELONG S.A.S."),   # así llega del encabezado del informe
    ("  EMPRESA   DE  PRUEBA  S.A.S.  ", "EMPRESA DE PRUEBA S.A.S."),
    ("INVERSIONES MARFIL LTDA.", "INVERSIONES MARFIL LTDA."),     # el punto final del nombre se conserva
    ("EMPRESA X \u2013", "EMPRESA X"), ("", ""), (None, ""),
])
def test_limpiar_nombre(entrada, esperado):
    assert seg.limpiar_nombre(entrada) == esperado


def test_si_el_nombre_viene_vacio_se_usa_el_nit():
    r = seg.resumir_plantilla([], 10)
    assert seg._armar_parametros(2, "Saldos CxC", r, " - ", "901652178", "informe")["p_nombre"] == "NIT 901652178"


# ───────────────────────────── Resumen de resultados ─────────────────────────────
def test_plantilla_sin_errores_esta_completa():
    r = seg.resumir_plantilla([], 100)
    assert (r["estado"], r["cumplimiento"], r["filas_error"]) == ("completado", 100.0, 0)


def test_plantilla_vacia_no_se_sigue():
    assert seg.resumir_plantilla([], 0) is None


def test_cumplimiento_cuenta_filas_con_error_no_errores():
    # 3 errores pero solo en 2 filas distintas, de 10 filas: 80%
    errs = [(5, "NIT", "formato", "m", "Campo vacío."), (5, "Cuenta", "logica", "m", "Cuenta inválida."),
            (7, "NIT", "formato", "m", "Campo vacío.")]
    r = seg.resumir_plantilla(errs, 10)
    assert (r["filas_error"], r["cumplimiento"], r["estado"]) == (2, 80.0, "requiere_correcciones")


def test_nunca_llega_a_100_si_queda_un_error():
    r = seg.resumir_plantilla([(2, "NIT", "formato", "m", "x.")], 100000)
    assert r["cumplimiento"] == 99.0


def test_las_advertencias_no_cuentan_como_error():
    r = seg.resumir_plantilla([(2, "NIT", "advertencia", "m", "Recomendación.")], 10)
    assert (r["estado"], r["cumplimiento"], r["advertencias"]) == ("completado", 100.0, 1)


def test_error_sin_fila_cuenta_como_global_y_bloquea():
    r = seg.resumir_plantilla([(None, "Balance", "general", "m", "Plantilla desbalanceada. Diferencia: 5")], 50)
    assert (r["errores_globales"], r["filas_error"], r["estado"], r["cumplimiento"]) == (1, 0, "requiere_correcciones", 99.0)


def test_filas_con_error_nunca_superan_las_filas():
    errs = [(i, "NIT", "formato", "m", "x.") for i in range(1, 50)]
    assert seg.resumir_plantilla(errs, 10)["filas_error"] == 10


def test_conciliacion():
    r = seg.resumir_conciliacion(200, 50, {"🔴 Solo en el submódulo de Cuentas por Cobrar": 30, "🟠 Diferencia de valor": 20})
    assert (r["cumplimiento"], r["estado"]) == (75.0, "requiere_correcciones")
    assert [p["categoria"] for p in r["pendientes"]] == ["Solo en el submódulo de Cuentas por Cobrar", "Diferencia de valor"]
    assert seg.resumir_conciliacion(10, 0)["estado"] == "completado"
    assert seg.resumir_conciliacion(0, 0) is None


# ─────────────────────────────── Privacidad ───────────────────────────────
def test_no_se_envian_valores_ni_mensajes_de_error():
    secreto = "VALOR-SECRETO-900123456"
    errs = [(3, "NIT", "logica", f'El NIT "{secreto}" no existe', f"Tercero {secreto} no encontrado."),
            (None, "Balance", "general", f"Débitos {secreto}", f"DOCDESC|CI|26050001||2026-05-27||1,084,700,834.00|{secreto}|8,500,000.00")]
    r = seg.resumir_plantilla(errs, 20)
    params = seg._armar_parametros(3, "Saldos Iniciales Principal", r, "CLIENTE S.A.S.", "999000001", "informe")
    texto = json.dumps(params, ensure_ascii=False)
    assert secreto not in texto and "26050001" not in texto and "1,084,700,834" not in texto
    assert {p["categoria"] for p in r["pendientes"]} == {"Otra inconsistencia", "Documento descuadrado"}


def test_categorias_usan_el_titulo_amigable_si_existe():
    titulos = {"Campo vacío.": {"titulo": "Campos vacíos"}}
    r = seg.resumir_plantilla([(2, "Sucursal", "formato", "m", "Campo vacío.")], 10, titulos=titulos)
    assert r["pendientes"] == [{"categoria": "Campos vacíos", "columna": "Sucursal", "casos": 1}]


def test_pendientes_respetan_los_limites_de_la_base():
    errs = [(i, f"Col{i}", "formato", "m", f"Categoría número {chr(65 + i % 26)}{chr(97 + i % 20)}.") for i in range(1, 400)]
    r = seg.resumir_plantilla(errs, 1000)
    assert len(r["pendientes"]) <= 20
    assert len(json.dumps(r["pendientes"], ensure_ascii=False).encode("utf-8")) <= 6000


def test_parametros_completos_y_en_el_formato_de_la_funcion():
    r = seg.resumir_plantilla([], 10)
    con_nit = seg._armar_parametros(1, "Terceros", r, "Cliente", "901652178", "digitado")
    sin_nit = seg._armar_parametros(1, "Terceros", r, "Cliente", "", "digitado")
    assert set(con_nit) == PARAMETROS and set(sin_nit) == PARAMETROS      # la función de la base no tiene valores por defecto
    assert con_nit["p_nit"] == "901652178" and sin_nit["p_nit"] == seg.SIN_IDENTIFICAR
    assert sin_nit["p_nombre"] is None and sin_nit["p_cumplimiento"] is None
    assert len(seg._armar_parametros(1, "x" * 200, r, "n" * 500, "901652178", "informe")["p_plantilla"]) == 80


# ───────────────────── Cuándo envía y cuándo no (sin red) ─────────────────────
class Envios:
    def __init__(self, falla=False):
        self.llamadas, self.falla = [], falla

    def __call__(self, url, clave, parametros):
        self.llamadas.append(parametros)
        if self.falla:
            raise RuntimeError("sin conexión")


def _resumen(n_errores=0):
    return seg.resumir_plantilla([(i + 2, "NIT", "formato", "m", "x.") for i in range(n_errores)], 100)


@pytest.mark.parametrize("cfg", [None, {}, {"activo": False, "url": "u", "clave_publica": "k"},
                                 {"activo": True, "url": "", "clave_publica": "k"},
                                 {"activo": True, "url": "u", "clave_publica": ""}])
def test_apagado_no_envia_nada(cfg):
    envios = Envios()
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", {}, cfg, envios) == "apagado"
    assert envios.llamadas == []


@pytest.mark.parametrize("activo", ["false", "False", "FALSE", "no", "0", "off", "", " ", None, 0, False, 2, "talvez"])
def test_activo_escrito_entre_comillas_o_dudoso_no_enciende_el_seguimiento(activo):
    """Regresión: con activo = "false" (entre comillas) el seguimiento se encendía, porque en Python
    cualquier texto con contenido cuenta como verdadero."""
    envios = Envios()
    cfg = {"activo": activo, "url": "https://ejemplo.supabase.co", "clave_publica": "k"}
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", {}, cfg, envios) == "apagado"
    assert envios.llamadas == []


@pytest.mark.parametrize("activo", [True, "true", "True", "TRUE", " true ", 1, "si", "sí", "yes", "on"])
def test_activo_verdadero_si_enciende_el_seguimiento(activo):
    envios = Envios()
    cfg = {"activo": activo, "url": "https://ejemplo.supabase.co", "clave_publica": "k"}
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", {}, cfg, envios) == "enviado"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://ejemplo.com", "ejemplo.supabase.co", "//ejemplo.supabase.co", "javascript:alert(1)"])
def test_la_url_debe_ser_http_o_https(url):
    envios = Envios()
    cfg = {"activo": True, "url": url, "clave_publica": "k"}
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", {}, cfg, envios) == "apagado"
    assert envios.llamadas == []


def test_envia_una_vez_y_no_repite_si_no_cambia():
    estado, envios = {}, Envios()
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios) == "enviado"
    for _ in range(20):      # 20 repintados de la pantalla con el mismo resultado
        assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios) == "sin_cambios"
    assert len(envios.llamadas) == 1


def test_envia_de_nuevo_cuando_el_resultado_cambia():
    estado, envios = {}, Envios()
    seg.registrar(1, "Terceros", _resumen(5), "C", "901652178", "digitado", estado, CFG, envios)
    seg.registrar(1, "Terceros", _resumen(2), "C", "901652178", "digitado", estado, CFG, envios)
    assert [p["p_filas_error"] for p in envios.llamadas] == [5, 2]


def test_cada_plantilla_se_controla_por_separado():
    estado, envios = {}, Envios()
    seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios)
    seg.registrar(1, "Centros de Costos", _resumen(), "C", "901652178", "digitado", estado, CFG, envios)
    assert len(envios.llamadas) == 2


def test_cambiar_el_nit_vuelve_a_enviar():
    estado, envios = {}, Envios()
    seg.registrar(1, "Terceros", _resumen(), "C", "", "digitado", estado, CFG, envios)           # sin NIT
    seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios)  # ya lo digitó
    assert [p["p_nit"] for p in envios.llamadas] == [seg.SIN_IDENTIFICAR, "901652178"]


def test_un_fallo_de_red_no_tumba_la_app_y_pausa_los_reintentos():
    estado, envios = {}, Envios(falla=True)
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios, ahora=1000) == "error"
    for t in (1001, 1050, 1119):           # durante la pausa no se intenta de nuevo (la app no se vuelve lenta)
        assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios, ahora=t) == "pausado"
    assert len(envios.llamadas) == 1
    envios.falla = False                   # pasada la pausa vuelve a intentar y, si responde, queda enviado
    assert seg.registrar(1, "Terceros", _resumen(), "C", "901652178", "digitado", estado, CFG, envios, ahora=1121) == "enviado"
    assert "pausa_hasta" not in estado


def test_plantilla_sin_filas_con_nit_no_envia():
    envios = Envios()
    assert seg.registrar(1, "Terceros", None, "C", "901652178", "digitado", {}, CFG, envios) == "sin_resumen"
    assert envios.llamadas == []


def test_datos_malos_no_lanzan_excepciones():
    assert seg.registrar("no-es-numero", "Terceros", _resumen(), "C", "901652178", "digitado", {}, CFG, Envios()) == "error"


# ───────────────────── Envío HTTP real contra un servidor de prueba ─────────────────────
class _Servidor:
    def __init__(self, codigo=200, respuesta=b"true"):
        self.peticiones = []
        outer = self

        class Manejador(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                largo = int(self.headers.get("Content-Length", 0))
                outer.peticiones.append({"ruta": self.path, "cabeceras": dict(self.headers),
                                         "cuerpo": json.loads(self.rfile.read(largo) or b"{}")})
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(respuesta)

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def cerrar(self):
        self.httpd.shutdown()


@pytest.fixture
def servidor():
    s = _Servidor()
    yield s
    s.cerrar()


def test_http_ruta_cabeceras_y_cuerpo(servidor):
    params = seg._armar_parametros(1, "Terceros", _resumen(), "Cliente", "901652178", "digitado")
    seg._enviar_http(servidor.url, "sb_publishable_ejemplo", params)
    p = servidor.peticiones[0]
    cab = {k.lower(): v for k, v in p["cabeceras"].items()}       # los nombres de cabecera no distinguen mayúsculas (HTTP)
    assert p["ruta"] == "/rest/v1/rpc/registrar_avance"
    assert cab["apikey"] == "sb_publishable_ejemplo"
    assert "authorization" not in cab                             # la llave nueva no es un JWT: no va como Bearer
    assert set(p["cuerpo"]) == PARAMETROS


def test_http_llave_antigua_jwt_tambien_va_como_bearer(servidor):
    seg._enviar_http(servidor.url, "eyJhbGciOi.ejemplo.firma", seg._armar_parametros(1, "T", _resumen(), "C", "901652178", "digitado"))
    cab = {k.lower(): v for k, v in servidor.peticiones[0]["cabeceras"].items()}
    assert cab["authorization"] == "Bearer eyJhbGciOi.ejemplo.firma"


def test_http_error_del_servidor_se_reporta_y_la_app_sigue():
    s = _Servidor(codigo=500, respuesta=b'{"message":"boom"}')
    try:
        estado = {}
        cfg = {"activo": True, "url": s.url, "clave_publica": "k"}
        assert seg.registrar(1, "T", _resumen(), "C", "901652178", "digitado", estado, cfg) == "error"
        assert "pausa_hasta" in estado
    finally:
        s.cerrar()


def test_http_servidor_caido_responde_rapido_y_no_lanza():
    import time
    estado, cfg = {}, {"activo": True, "url": "http://127.0.0.1:9", "clave_publica": "k"}   # puerto cerrado
    t0 = time.perf_counter()
    assert seg.registrar(1, "T", _resumen(), "C", "901652178", "digitado", estado, cfg) == "error"
    assert time.perf_counter() - t0 < seg.TIMEOUT_SEG + 1


# ───────────────────── Código de acceso (corrección de mayúsculas) ─────────────────────
def _cargar_cambiar_etapa(sesion):
    src = open(os.path.join(RAIZ, "validador_sinco_ayf.py"), encoding="utf-8").read()
    nodo = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_cambiar_etapa")
    class St:                      # sustituto mínimo de streamlit
        session_state = sesion
    ns = {"st": St}
    exec(ast.get_source_segment(src, nodo), ns)
    return ns["_cambiar_etapa"]


@pytest.mark.parametrize("secret,escrito,entra", [
    ("CDGK6-YKK9N", "cdgk6-ykk9n", True),      # el usuario puede escribirlo en minúscula
    ("CDGK6-YKK9N", "  CDGK6-YKK9N ", True),   # y con espacios alrededor
    ("Migra-2026", "MIGRA-2026", True),        # regresión: un secret con minúsculas dejaba a todos fuera
    ("Migra-2026", "migra-2026", True),
    ("CDGK6-YKK9N", "SINCO2", False),          # el código anterior ya no sirve
    ("CDGK6-YKK9N", "", False),
])
def test_codigo_de_acceso(secret, escrito, entra):
    sesion = {"codigo_e2": escrito, "etapa_sel": None}
    _cargar_cambiar_etapa(sesion)("Etapa 2", "codigo_e2", secret)
    assert (sesion["etapa_sel"] == "Etapa 2") is entra


# ─────────────── Punta a punta contra la función real de la base (opcional) ───────────────
DSN = os.environ.get("SEGUIMIENTO_PG_DSN")


@pytest.mark.skipif(not DSN, reason="define SEGUIMIENTO_PG_DSN para probar contra una base PostgreSQL")
def test_punta_a_punta_contra_la_funcion_registrar_avance():
    psycopg2 = pytest.importorskip("psycopg2")
    from psycopg2.extras import Json
    conexion = psycopg2.connect(DSN)
    conexion.autocommit = True
    cur = conexion.cursor()
    cur.execute("delete from public.historial_validaciones where nit in ('999000777', %s)", (seg.SIN_IDENTIFICAR,))
    cur.execute("delete from public.avance_actual where nit = '999000777'")

    class Reenvia(http.server.BaseHTTPRequestHandler):      # imita a PostgREST: ejecuta la función como el rol público
        def do_POST(self):
            p = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            p["p_pendientes"] = Json(p["p_pendientes"]) if p["p_pendientes"] is not None else None
            c = conexion.cursor()
            c.execute("set role anon")
            try:
                c.execute("select public.registrar_avance(%(p_nit)s, %(p_nombre)s, %(p_fuente)s, %(p_etapa)s::smallint,"
                          " %(p_plantilla)s, %(p_filas)s, %(p_filas_error)s, %(p_errores_globales)s, %(p_advertencias)s,"
                          " %(p_cumplimiento)s, %(p_estado)s, %(p_pendientes)s::jsonb, %(p_version)s)", p)
                cuerpo, codigo = json.dumps(c.fetchone()[0]).encode(), 200
            except Exception as e:
                cuerpo, codigo = json.dumps({"message": str(e)}).encode(), 400
            finally:
                c.execute("reset role")
            self.send_response(codigo)
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Reenvia)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    cfg = {"activo": True, "url": f"http://127.0.0.1:{httpd.server_port}", "clave_publica": "sb_publishable_ejemplo"}
    estado = {}
    try:
        con_errores = seg.resumir_plantilla([(i, "NIT", "logica", "m", "Tercero no registrado.") for i in range(2, 22)], 100)
        assert seg.registrar(3, "Saldos Iniciales Principal", con_errores, "CLIENTE DE PRUEBA S.A.S.", "999000777", "informe", estado, cfg) == "enviado"
        arreglada = seg.resumir_plantilla([], 100)
        assert seg.registrar(3, "Saldos Iniciales Principal", arreglada, "CLIENTE DE PRUEBA S.A.S.", "999000777", "informe", estado, cfg) == "enviado"
        # Uso sin NIT: solo queda en el historial
        assert seg.registrar(1, "Terceros", arreglada, "", "", "digitado", estado, cfg) == "enviado"
    finally:
        httpd.shutdown()

    cur.execute("select cumplimiento, estado, filas_con_error, pendientes from public.avance_actual where nit='999000777'")
    cumplimiento, estado_db, filas_error, pendientes = cur.fetchone()
    assert (float(cumplimiento), estado_db, filas_error, pendientes) == (100.0, "completado", 0, [])
    cur.execute("select cumplimiento_antes, cumplimiento from public.historial_validaciones where nit='999000777' order by id")
    # 20 filas con error de 100 = 80%; la primera vez no había un valor anterior; la segunda ya queda en 100%
    assert [(a if a is None else float(a), float(b)) for a, b in cur.fetchall()] == [(None, 80.0), (80.0, 100.0)]
    cur.execute("select count(*) from public.historial_validaciones where nit=%s", (seg.SIN_IDENTIFICAR,))
    assert cur.fetchone()[0] == 1
    cur.execute("select count(*) from public.avance_actual where nit=%s", (seg.SIN_IDENTIFICAR,))
    assert cur.fetchone()[0] == 0                                  # sin NIT no se calcula avance
    cur.execute("delete from public.historial_validaciones where nit in ('999000777', %s)", (seg.SIN_IDENTIFICAR,))
    cur.execute("delete from public.avance_actual where nit = '999000777'")
