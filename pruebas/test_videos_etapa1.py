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
ETIQUETA = {"puc_principal": "PUC Principal (NIF)", "multiples_libros": "Múltiples libros", "puc_fiscal": "PUC Fiscal", "terceros": "Terceros"}
ORDEN = ["multiples_libros", "puc_principal", "puc_fiscal", "terceros"]          # el orden pedido: dentro del visor, en el banner y en el menú lateral
LLAVES_LATERALES = {"puc_principal": "side_video_puc_principal", "puc_fiscal": "side_video_puc_fiscal", "multiples_libros": "side_video_multiples_libros",
                    "terceros": "side_video_terceros"}


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
    for definicion in ("VIDEOS_AYUDA_ETAPA1 = {", "def _renderizar_video_ayuda(", "def _modal_videos_e1(", "def _boton_video_lateral(",
                       "def _opciones_video_e1(", "def _modal_video_ayuda("):
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
    return next((r for r in app.radio if r.label == "Elige el video"), None)


def test_la_etapa_1_abre_sin_errores_y_tiene_el_banner_con_un_boton_visible():
    app = _abrir_etapa1()
    boton = next(b for b in app.button if b.key == "btn_diligenciar_e1")
    assert boton.label == "🎬 Ver videos"
    texto = _texto(app)
    assert "Mira cómo diligenciar tus plantillas" in texto
    assert "Múltiples libros · PUC Principal (NIF) · PUC Fiscal · Terceros." in texto      # lista los videos disponibles en el orden pedido, sin Centros de Costos
    assert "Ver cómo diligenciar</" not in " ".join(m.value for m in app.markdown)           # ya no está el enlace diminuto de antes


def test_cada_plantilla_con_video_tiene_su_boton_en_el_menu_lateral_y_centros_de_costos_no():
    app = _abrir_etapa1()
    llaves = {b.key for b in app.button if b.key and b.key.startswith("side_video_")}
    assert llaves == set(LLAVES_LATERALES.values())                                          # sin video de Centros de Costos, no hay botón


@pytest.mark.parametrize("clave", list(LLAVES_LATERALES))
def test_el_boton_de_cada_plantilla_abre_el_visor_en_su_video(clave):
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == LLAVES_LATERALES[clave]).click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    visor = _visor(app)
    assert visor is not None and visor.value == ETIQUETA[clave]
    assert visor.options == [ETIQUETA[k] for k in ORDEN]                                     # el selector trae los cuatro videos, en el orden pedido
    ns, *_ = cargar(["VIDEOS_AYUDA_ETAPA1"])
    titulo = html.escape(ns["VIDEOS_AYUDA_ETAPA1"][clave]["titulo"])
    assert f'<div class="v1-titulo">{titulo}</div>' in " ".join(m.value for m in app.markdown)
    assert f"VIDEO {ORDEN.index(clave) + 1} DE 4" in " ".join(m.value for m in app.markdown)


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
    """Múltiples libros primero (antes del PUC Principal), luego PUC Principal, PUC Fiscal y Terceros."""
    app = _abrir_etapa1()
    assert [b.key for b in app.button if b.key and b.key.startswith("side_video_")] == [LLAVES_LATERALES[k] for k in ORDEN]


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
    assert '@st.dialog("Videos: cómo diligenciar tus plantillas", width="large")' in src
    assert 'st.container(key="videos_e1")' in src and 'st.container(key="videos_e1_player")' in src
    # las otras dos ventanas conservan su título y su forma
    assert '@st.dialog("🎬 Video tutorial", width="large")' in src and '@st.dialog("📖 Guía rápida", width="large")' in src


def test_el_estilo_viaja_con_el_cuadro_y_las_cuatro_opciones_siguen_ahi():
    app = _abrir_etapa1()
    next(b for b in app.button if b.key == "btn_diligenciar_e1").click().run()
    assert not app.exception, [str(e.value) for e in app.exception]
    assert any("st-key-videos_e1" in m.value and "<style>" in m.value for m in app.markdown)
    assert _visor(app).options == [ETIQUETA[k] for k in ORDEN]
