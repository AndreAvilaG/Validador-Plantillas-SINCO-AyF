"""Pruebas de los videos de ayuda de la Etapa 1 («Ya tengo mis plantillas»).

Qué se protege:
  * Los enlaces entregados están registrados tal cual y cada uno se embebe con su identificador y su clave de Vimeo.
  * La ayuda es VISIBLE: un banner con un botón grande «Ver videos» arriba y un botón junto a cada plantilla en el menú lateral (antes era un
    enlace de letra diminuta). Cada botón abre el visor en el video de esa plantilla; solo se ofrecen plantillas que ya tienen video.
  * Regresión: las funciones de video van definidas ANTES del menú lateral. Streamlit ejecuta el archivo de arriba hacia abajo: si el menú llama a
    una función que se define más abajo, la aplicación entera deja de abrir (NameError).

No se prueba la reproducción en sí (depende de Vimeo y de que cada video permita ser embebido en la aplicación): solo que cada opción apunte al
enlace correcto.

Cómo correrlas (desde la raíz del repositorio):  pip install pytest   y luego   pytest pruebas
"""
import html
import io
import os
import re
from types import SimpleNamespace

import pytest

from _cargador import cargar, ejecutar, llenar_empresa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Los enlaces entregados por Andrea (clave del video -> enlace tal cual) y el reproductor que debe resultar de cada uno
ENLACES = {
    "puc_principal": "https://vimeo.com/1221256875/42495809a1?share=copy&fl=sv&fe=ci",
    "multiples_libros": "https://vimeo.com/1235999252/6e1509c554?share=copy&fl=sv&fe=ci",
    "puc_fiscal": "https://vimeo.com/1234173711/346f1d0f54?share=copy",
    "terceros": "https://vimeo.com/1232466212/e4c974c8e8?share=copy&fl=sv&fe=ci",
}
REPRODUCTOR = {
    "puc_principal": "https://player.vimeo.com/video/1221256875?h=42495809a1",
    "multiples_libros": "https://player.vimeo.com/video/1235999252?h=6e1509c554",
    "puc_fiscal": "https://player.vimeo.com/video/1234173711?h=346f1d0f54",
    "terceros": "https://player.vimeo.com/video/1232466212?h=e4c974c8e8",
}
ETIQUETA = {"puc_principal": "PUC Principal (NIF)", "multiples_libros": "Múltiples libros", "puc_fiscal": "PUC Fiscal", "terceros": "Terceros", "centros_costos": "Centros de Costos"}
ORDEN = ["multiples_libros", "puc_principal", "puc_fiscal", "terceros"]          # el orden pedido: dentro del visor, en el banner y en el menú lateral
ORDEN_CUADRO = ORDEN + ["centros_costos"]                                          # el cuadro de la Etapa 1 también ofrece Centros de Costos (plantilla y ejemplo, sin video)
CON_PLANTILLA = {"puc_principal": ("Plantilla_PUC_Principal_NIF.xlsx", "Ejemplo_PUC_Principal_NIF.xlsx"), "puc_fiscal": ("Plantilla_PUC_Fiscal.xlsx", "Ejemplo_PUC_Fiscal.xlsx"),
                 "terceros": ("Plantilla_Terceros.xlsx", "Ejemplo_Terceros.xlsx"), "centros_costos": ("Plantilla_Centros_de_Costos.xlsx", "Ejemplo_Centros_de_Costos.xlsx")}
CON_PLANTILLA_E23 = {"saldos_cxc": ("Plantilla_Saldos_CxC.xlsx", "Ejemplo_Saldos_CxC.xlsx"), "saldos_cxp": ("Plantilla_Saldos_CxP.xlsx", "Ejemplo_Saldos_CxP.xlsx"),
                     "saldos_iniciales": ("Plantilla_Saldos_Iniciales.xlsx", "Ejemplo_Saldos_Iniciales.xlsx"), "movimientos": ("Plantilla_Movimientos.xlsx", "Ejemplo_Movimientos.xlsx")}
ETIQUETA_E23 = {"saldos_cxc": "Saldos CxC", "saldos_cxp": "Saldos CxP", "saldos_iniciales": "Saldos iniciales", "movimientos": "Movimientos"}
ETAPAS_23 = {2: ("Etapa 2 — Saldos CxC / CxP", ["saldos_cxc", "saldos_cxp"]), 3: ("Etapa 3 — SI y Movimientos", ["saldos_iniciales", "movimientos"])}
LLAVES_LATERALES = {"puc_principal": "side_video_puc_principal", "puc_fiscal": "side_video_puc_fiscal", "multiples_libros": "side_video_multiples_libros",
                    "terceros": "side_video_terceros", "centros_costos": "side_video_centros_costos"}


# ───────────────────────── Los datos ─────────────────────────
def test_los_enlaces_entregados_estan_registrados_tal_cual():
    ns, *_ = cargar(["VIDEOS_AYUDA_ETAPA1"])
    for clave, enlace in ENLACES.items():
        assert ns["VIDEOS_AYUDA_ETAPA1"][clave]["url"] == enlace, clave


def test_el_video_de_centros_de_costos_sigue_sin_enlace():
    """No se entregó un video de Centros de Costos: no se inventa ninguno."""
    ns, *_ = cargar(["VIDEOS_AYUDA_ETAPA1"])
    assert ns["VIDEOS_AYUDA_ETAPA1"]["centros_costos"]["url"] == ""


@pytest.mark.parametrize("clave", list(ENLACES))
def test_cada_enlace_se_embebe_con_su_identificador_y_su_clave(clave):
    llamadas = []
    stub = SimpleNamespace(iframe=lambda src, height=None: llamadas.append(("iframe", src)), video=lambda url: llamadas.append(("video", url)))

    def correr(ns):
        ns["st"] = stub
        ns["_renderizar_video_ayuda"](ns["VIDEOS_AYUDA_ETAPA1"][clave]["url"])
    ejecutar(["_renderizar_video_ayuda", "VIDEOS_AYUDA_ETAPA1"], correr)
    assert llamadas == [("iframe", REPRODUCTOR[clave])]


def test_el_selector_ofrece_solo_los_videos_con_enlace_y_en_orden():
    def correr(ns):
        base = [k for k, _ in ns["_opciones_video_e1"]()]
        ns["VIDEOS_AYUDA_ETAPA1"]["centros_costos"]["url"] = "https://vimeo.com/111/abc"          # si algún día hay video, entra al final
        con_cc = [k for k, _ in ns["_opciones_video_e1"]()]
        ns["VIDEOS_AYUDA_ETAPA1"]["terceros"]["url"] = ""                                         # y uno sin enlace sale
        sin_terceros = [k for k, _ in ns["_opciones_video_e1"]()]
        return base, con_cc, sin_terceros
    base, con_cc, sin_terceros = ejecutar(["_opciones_video_e1", "VIDEOS_AYUDA_ETAPA1"], correr)
    assert base == ORDEN
    assert con_cc == base + ["centros_costos"]
    assert sin_terceros == ["multiples_libros", "puc_principal", "puc_fiscal", "centros_costos"]


def test_las_funciones_de_video_estan_definidas_antes_del_menu_lateral():
    """Regresión: definidas más abajo que el menú, la aplicación no abría (NameError en el menú lateral)."""
    src = open(os.path.join(RAIZ, "validador_sinco_ayf.py"), encoding="utf-8").read()
    menu = src.index("\nwith st.sidebar:")
    for definicion in ("VIDEOS_AYUDA_ETAPA1 = {", "def _renderizar_video_ayuda(", "def _modal_recursos(", "def _boton_video_lateral(",
                       "def _opciones_video_e1(", "def _modal_video_ayuda(", "_RECURSOS = {", "_ORDEN_RECURSOS = {", "def _opciones_recursos(", "def _archivo_recurso(", "def _bytes_recurso(",
                       "def _opciones_recursos_e1(", "def _carpeta_plantillas("):
        assert src.index(definicion) < menu, definicion


# ───────────────────────── En pantalla ─────────────────────────
def _abrir_etapa1():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    next(b for b in app.button if b.label == "➡️ Iniciar validación").click().run()
    radio = app.radio[0]
    radio.set_value([o for o in radio.options if "Ya tengo mis plantillas" in o][0]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


def _texto(app):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", " ".join(m.value for m in app.markdown)))


def _visor(app):
    return next((r for r in app.radio if r.label == "Elige la plantilla"), None)


def test_la_etapa_1_abre_sin_errores_y_tiene_el_banner_con_un_boton_visible():
    app = _abrir_etapa1()
    boton = next(b for b in app.button if b.key == "btn_diligenciar_e1")
    assert boton.label == "📘 Ver videos y plantillas"
    texto = _texto(app)
    assert "Mira cómo diligenciar tus plantillas" in texto
    assert "Video, plantilla en blanco y ejemplo de:" in texto
    assert "Múltiples libros · PUC Principal (NIF) · PUC Fiscal · Terceros · Centros de Costos." in texto    # lista lo que ofrece el cuadro, en el orden pedido
    assert "Ver cómo diligenciar</" not in " ".join(m.value for m in app.markdown)           # ya no está el enlace diminuto de antes


def test_cada_plantilla_de_la_etapa_1_tiene_su_boton_en_el_menu_lateral():
    app = _abrir_etapa1()
    botones = {b.key: b.label for b in app.button if b.key and b.key.startswith("side_video_")}
    assert set(botones) == set(LLAVES_LATERALES.values())                                    # incluida Centros de Costos: tiene plantilla y ejemplo aunque no tenga video
    assert botones["side_video_multiples_libros"] == "🎬 Manejo de múltiples libros"        # este es solo un video
    assert all(botones[LLAVES_LATERALES[k]] == "📘 Video, plantilla y ejemplo" for k in CON_PLANTILLA)


@pytest.mark.parametrize("clave", list(LLAVES_LATERALES))
def test_el_boton_de_cada_plantilla_abre_el_visor_en_su_video(clave):
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == LLAVES_LATERALES[clave]).click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    visor = _visor(app)
    assert visor is not None and visor.value == ETIQUETA[clave]
    assert visor.options == [ETIQUETA[k] for k in ORDEN_CUADRO]                              # el selector trae las cinco opciones, en el orden pedido
    ns, *_ = cargar(["VIDEOS_AYUDA_ETAPA1"])
    texto = " ".join(m.value for m in app.markdown)
    assert "<b>Video explicativo</b>" in texto                                               # paso 1
    if ns["VIDEOS_AYUDA_ETAPA1"][clave].get("url"):
        assert html.escape(ns["VIDEOS_AYUDA_ETAPA1"][clave]["descripcion"]) in texto
    else:
        assert "Aún no hay video para esta plantilla" in texto
    if clave in CON_PLANTILLA:                                                               # pasos 2 y 3, con el nombre de cada archivo
        assert "Plantilla en blanco" in texto and "Archivo oficial para diligenciar" in texto and "Referencia para aprender" in texto
        assert all(nombre in texto for nombre in CON_PLANTILLA[clave])
    else:
        assert "Plantilla_" not in texto and "Ejemplo_" not in texto


def test_el_boton_del_banner_abre_el_visor_en_el_primer_video():
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == "btn_diligenciar_e1").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert _visor(app).value == "Múltiples libros"


def test_sin_abrir_ningun_boton_el_visor_no_aparece():
    assert _visor(_abrir_etapa1()) is None


def test_la_ayuda_junto_a_los_resultados_de_una_plantilla_es_un_boton_visible():
    """Al cargar una plantilla, en sus resultados sigue estando la ayuda; ahora es un botón con borde, no un enlace pequeño."""
    import openpyxl
    cols = ejecutar(["_COLS_PUC"], lambda ns: list(ns["_COLS_PUC"]))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(cols)
    ws.append(["1", "ACTIVO", "M"] + [None] * (len(cols) - 3))
    datos = io.BytesIO()
    wb.save(datos)
    app = _abrir_etapa1()
    llenar_empresa(app)
    next(f for f in app.file_uploader if f.key == "puc_principal" or f.key.startswith("puc_principal_")).set_value([("puc.xlsx", datos.getvalue(), XLSX)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    boton = next(b for b in app.button if b.key == "video_puc_principal")
    assert boton.label == "🎬 Ver video: cómo diligenciar esta plantilla"


def test_centros_de_costos_no_muestra_boton_de_video_porque_no_hay_video():
    """Regresión: tras cargar Centros de Costos aparecía un botón visible que llevaba a «Video próximamente disponible» (un callejón sin salida)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MIGRACION"
    ws.append(["Código", "Nombre"])
    ws.append(["1", "PRINCIPAL"])
    datos = io.BytesIO()
    wb.save(datos)
    app = _abrir_etapa1()
    llenar_empresa(app)
    next(f for f in app.file_uploader if f.key == "cc_e1" or f.key.startswith("cc_e1_")).set_value([("cc.xlsx", datos.getvalue(), XLSX)]).run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert not [b for b in app.button if b.key == "video_centros_costos"]


# ───────────────────────── El orden afuera (menú lateral) ─────────────────────────
def test_los_botones_del_menu_lateral_siguen_el_orden_pedido():
    """Múltiples libros primero (antes del PUC Principal), luego PUC Principal, PUC Fiscal, Terceros y Centros de Costos."""
    app = _abrir_etapa1()
    assert [b.key for b in app.button if b.key and b.key.startswith("side_video_")] == [LLAVES_LATERALES[k] for k in ORDEN_CUADRO]


# ───────────────────────── El diseño del cuadro de videos ─────────────────────────
def _css_del_cuadro():
    ns, *_ = cargar(["_CSS_MODAL_VIDEOS_E1"])
    return ns["_CSS_MODAL_VIDEOS_E1"]


def test_todo_el_estilo_del_cuadro_esta_limitado_a_ese_cuadro():
    """Ninguna regla puede afectar a otras ventanas (la guía rápida, el video individual) ni al resto de la aplicación: cada selector lleva la marca
    del contenedor «videos_e1»."""
    css = _css_del_cuadro()
    cuerpo = re.sub(r"</?style>", "", css)
    selectores = [s.strip() for s in re.findall(r"([^{}]+)\{", cuerpo) if not s.strip().startswith("@")]
    assert selectores, "no se encontraron reglas"
    for lista in selectores:
        for selector in lista.split(","):
            assert "st-key-videos_e1" in selector, selector


def test_el_css_no_anida_un_has_dentro_de_otro():
    """Regresión: «:has()» dentro de «:has()» es un selector inválido; el navegador ignoraba la regla completa y el panel exterior quedaba sin estilo."""
    css = _css_del_cuadro()
    for m in re.finditer(r":has\(", css):
        profundidad, k = 1, m.end()
        while profundidad and k < len(css):
            profundidad += {"(": 1, ")": -1}.get(css[k], 0)
            k += 1
        assert ":has(" not in css[m.end():k], css[m.start():k + 20]


def test_el_reproductor_mantiene_la_proporcion_y_no_tiene_altura_fija():
    css = _css_del_cuadro()
    assert "aspect-ratio:16/9" in css and "height:auto !important" in css
    assert "height:400px" not in css and "flex:0 0 auto" in css                               # sin la base de 400 px que dejaba el recuadro vacío


def test_el_estilo_incluye_selector_en_tarjetas_encabezado_con_icono_y_adaptacion_a_pantallas_pequenas():
    css = _css_del_cuadro()
    assert 'data-selected="true"' in css and ":hover" in css                                    # la opción elegida y el cursor encima se distinguen
    assert 'h2 p::before' in css and "#DBEAFE" in css                                           # ícono en un recuadro azul suave
    assert "@media (max-width:640px)" in css and "auto-fit" in css                              # se acomoda en pantallas pequeñas
    assert "border-bottom:1px solid" in css and "box-shadow" in css and "border-radius:18px" in css


def test_el_visor_aparece_dentro_del_contenedor_marcado_y_con_el_titulo_pedido():
    src = open(os.path.join(RAIZ, "validador_sinco_ayf.py"), encoding="utf-8").read()
    assert '@st.dialog("Cómo diligenciar tus plantillas", width="large")' in src
    assert 'st.container(key="videos_e1")' in src and 'st.container(key="videos_e1_player")' in src
    # las otras dos ventanas conservan su título y su forma
    assert '@st.dialog("🎬 Video tutorial", width="large")' in src and '@st.dialog("📖 Guía rápida", width="large")' in src


def test_el_estilo_viaja_con_el_cuadro_y_las_opciones_siguen_ahi():
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == "btn_diligenciar_e1").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert any("st-key-videos_e1" in m.value and "<style>" in m.value for m in app.markdown)
    assert _visor(app).options == [ETIQUETA[k] for k in ORDEN_CUADRO]


# ───────────────────────── El flujo: video, plantilla en blanco y ejemplo ─────────────────────────
def test_el_cuadro_ofrece_las_cinco_opciones_y_solo_multiples_libros_no_tiene_plantilla():
    ns, *_ = cargar(["_opciones_recursos_e1", "_opciones_recursos", "VIDEOS_AYUDA_ETAPA1", "_RECURSOS", "_ORDEN_RECURSOS"])
    assert [k for k, _ in ns["_opciones_recursos_e1"]()] == ORDEN_CUADRO
    assert {k: ns["_RECURSOS"][k] for k in CON_PLANTILLA} == CON_PLANTILLA                      # las de la Etapa 1, tal cual
    assert set(ns["_RECURSOS"]) == set(CON_PLANTILLA) | set(CON_PLANTILLA_E23)                  # y las de las Etapas 2 y 3 en la misma tabla
    assert {e: [k for k, _ in ns["_opciones_recursos"](e)] for e in (2, 3)} == {2: ["saldos_cxc", "saldos_cxp"], 3: ["saldos_iniciales", "movimientos"]}


@pytest.mark.parametrize("clave", list(CON_PLANTILLA) + list(CON_PLANTILLA_E23))
def test_los_archivos_de_cada_plantilla_existen_en_la_carpeta_del_repositorio(clave):
    ns, *_ = cargar(["_archivo_recurso", "_carpeta_plantillas", "_RECURSOS"])
    ns["_carpeta_plantillas"] = lambda: os.path.join(RAIZ, "plantillas")
    esperados = {**CON_PLANTILLA, **CON_PLANTILLA_E23}[clave]
    for indice in (0, 1):
        ruta = ns["_archivo_recurso"](clave, indice)
        assert ruta and os.path.isfile(ruta) and os.path.basename(ruta) == esperados[indice]


def test_si_falta_un_archivo_o_la_carpeta_no_se_rompe_nada(tmp_path):
    """Si alguien sube la app pero olvida la carpeta «plantillas», el cuadro avisa que el archivo no está disponible en vez de fallar."""
    ns, *_ = cargar(["_archivo_recurso", "_carpeta_plantillas", "_RECURSOS"])
    ns["_carpeta_plantillas"] = lambda: str(tmp_path / "no_existe")
    assert all(ns["_archivo_recurso"](clave, i) is None for clave in list(CON_PLANTILLA) + list(CON_PLANTILLA_E23) for i in (0, 1))
    assert ns["_archivo_recurso"]("multiples_libros", 0) is None and ns["_archivo_recurso"]("no_existe", 1) is None


def test_el_cuadro_no_falla_cuando_los_archivos_no_estan(monkeypatch, tmp_path):
    """La misma situación, pero con el cuadro completo: abre sin errores y dice que el archivo no está disponible."""
    from streamlit.testing.v1 import AppTest
    carpeta_real = os.path.join(RAIZ, "plantillas")
    oculta = carpeta_real + "_oculta_por_la_prueba"
    os.rename(carpeta_real, oculta)
    try:
        app = _abrir_etapa1()
        next(b for b in app.button if b.key == LLAVES_LATERALES["terceros"]).click().run()
        assert not app.exception, [str(e.value) for e in app.exception]
        assert "Este archivo no está disponible por ahora." in " ".join(m.value for m in app.markdown)
    finally:
        os.rename(oculta, carpeta_real)


def test_el_contenido_que_se_descarga_es_el_del_archivo_del_repositorio():
    ns, *_ = cargar(["_bytes_recurso"])
    ruta = os.path.join(RAIZ, "plantillas", CON_PLANTILLA["terceros"][0])
    assert ns["_bytes_recurso"](ruta) == open(ruta, "rb").read()


def test_multiples_libros_es_solo_un_video_y_lo_explica():
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == LLAVES_LATERALES["multiples_libros"]).click().run()
    texto = " ".join(m.value for m in app.markdown)
    assert "Plantilla_" not in texto and "Ejemplo_" not in texto and "Las plantillas se descargan desde PUC Principal y PUC Fiscal" in texto


# ───────────────────────── Etapas 2 y 3: el mismo flujo, con sus plantillas (los videos llegarán después) ─────────────────────────
def _abrir_etapa(etapa):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(os.path.join(RAIZ, "validador_sinco_ayf.py"), default_timeout=180)
    app.session_state["etapa_sel"] = etapa
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    return app


@pytest.mark.parametrize("n", [2, 3])
def test_cada_plantilla_de_las_etapas_2_y_3_tiene_su_boton_en_el_menu_lateral_en_el_orden_de_los_cargadores(n):
    etapa, claves = ETAPAS_23[n]
    app = _abrir_etapa(etapa)
    botones = [(b.key, b.label) for b in app.button if b.key and b.key.startswith("side_video_")]
    assert botones == [(f"side_video_{k}", "📘 Video, plantilla y ejemplo") for k in claves]


@pytest.mark.parametrize("n,clave", [(2, "saldos_cxc"), (2, "saldos_cxp"), (3, "saldos_iniciales"), (3, "movimientos")])
def test_el_boton_abre_el_cuadro_de_su_etapa_con_el_flujo_completo_y_sin_video_todavia(n, clave):
    etapa, claves = ETAPAS_23[n]
    app = _abrir_etapa(etapa)
    next(b for b in app.button if b.key == f"side_video_{clave}").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    visor = _visor(app)
    assert visor is not None and visor.value == ETIQUETA_E23[clave]
    assert visor.options == [ETIQUETA_E23[k] for k in claves]                             # solo las plantillas de esa etapa, en su orden
    texto = " ".join(m.value for m in app.markdown)
    assert "Aún no hay video para esta plantilla" in texto and "<b>Video explicativo</b>" in texto
    assert "Plantilla en blanco" in texto and "Referencia para aprender" in texto
    assert all(nombre in texto for nombre in CON_PLANTILLA_E23[clave])                    # los nombres de sus dos archivos


def test_las_etapas_2_y_3_no_muestran_los_botones_de_la_etapa_1_ni_al_reves():
    for n, (etapa, claves) in ETAPAS_23.items():
        llaves = {b.key for b in _abrir_etapa(etapa).button if b.key and b.key.startswith("side_video_")}
        assert llaves == {f"side_video_{k}" for k in claves}
    llaves_e1 = {b.key for b in _abrir_etapa_1().button if b.key and b.key.startswith("side_video_")}
    assert llaves_e1 == set(LLAVES_LATERALES.values())


def _abrir_etapa_1():
    return _abrir_etapa("Etapa 1 — Maestro de Cuentas, Terceros y C. Costos")


def test_cuando_exista_un_video_de_la_etapa_2_o_3_basta_con_pegar_su_enlace():
    """Los cuatro videos pendientes ya tienen su lugar en la tabla (con título, descripción y etiqueta) y su enlace vacío; al llenarlo, el cuadro de su
    etapa lo recoge solo (el cuadro dibuja el video cuando la ficha tiene «url»)."""
    ns, *_ = cargar(["VIDEOS_AYUDA_ETAPA1", "_opciones_recursos", "_RECURSOS", "_ORDEN_RECURSOS"])
    datos = ns["VIDEOS_AYUDA_ETAPA1"]
    for clave in CON_PLANTILLA_E23:
        assert datos[clave]["url"] == "" and datos[clave]["etiqueta"] == ETIQUETA_E23[clave] and datos[clave]["titulo"] and datos[clave]["descripcion"]
    assert not any(info.get("url") for _, info in ns["_opciones_recursos"](2) + ns["_opciones_recursos"](3))      # hoy ninguno tiene video
    datos["saldos_cxp"]["url"] = "https://vimeo.com/111/abc"
    assert dict(ns["_opciones_recursos"](2))["saldos_cxp"]["url"] == "https://vimeo.com/111/abc"                   # y al pegarlo, el cuadro lo ve
    src = open(os.path.join(RAIZ, "validador_sinco_ayf.py"), encoding="utf-8").read()
    assert "if info.get('url'):\n            with st.container(key=\"videos_e1_player\")" in src                       # y lo reproduce con el reproductor de siempre
