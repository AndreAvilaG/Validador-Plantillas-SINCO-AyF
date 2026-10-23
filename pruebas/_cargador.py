"""Ayudante de las pruebas: carga funciones y constantes del validador (que es un script de Streamlit y no se puede importar) y
agrega, una a una, las dependencias que falten. Respeta el orden en que aparecen en el archivo, porque el código de nivel superior
(constantes que usan otras constantes) depende de ese orden."""
import ast
import os
import re
from functools import lru_cache

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache(maxsize=4)
def _definiciones(archivo):
    src = open(os.path.join(RAIZ, archivo), encoding="utf-8").read()
    defs, orden = {}, {}
    for n in ast.parse(src).body:
        if isinstance(n, ast.FunctionDef):
            n.decorator_list = []                      # sin el decorador de caché de Streamlit
            defs[n.name], orden[n.name] = ast.unparse(n), n.lineno
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defs[t.id], orden[t.id] = ast.get_source_segment(src, n), n.lineno
    return defs, orden


def cargar(nombres, archivo="validador_sinco_ayf.py", reemplazos=None):
    """Namespace con `nombres` y las dependencias que se hayan ido pidiendo. reemplazos: {nombre: [(viejo, nuevo), ...]}."""
    defs, orden = _definiciones(archivo)
    defs = dict(defs)
    for nombre, cambios in (reemplazos or {}).items():
        for viejo, nuevo in cambios:
            assert viejo in defs[nombre], (nombre, viejo)
            defs[nombre] = defs[nombre].replace(viejo, nuevo)
    pedidos = list(nombres)
    for _ in range(200):
        codigo = ("import re, zlib, base64, io, unicodedata\nimport pandas as pd\nfrom io import BytesIO\nfrom datetime import datetime\n\n"
                  + "\n\n".join(defs[n] for n in sorted((x for x in pedidos if x in defs), key=lambda x: orden[x])))
        ns = {}
        try:
            exec(codigo, ns)
            return ns, pedidos, defs, orden
        except NameError as e:
            falta = re.search(r"name '(\w+)' is not defined", str(e)).group(1)
            assert falta in defs and falta not in pedidos, falta
            pedidos.append(falta)
    raise RuntimeError("demasiadas dependencias")


def ejecutar(nombres, funcion, archivo="validador_sinco_ayf.py", reemplazos=None):
    """Llama funcion(ns) y, si le falta alguna dependencia al ejecutarse, la agrega y reintenta."""
    defs, orden = _definiciones(archivo)
    pedidos = list(nombres)
    for _ in range(200):
        ns, pedidos, _, _ = cargar(pedidos, archivo, reemplazos)
        try:
            return funcion(ns)
        except NameError as e:
            falta = re.search(r"name '(\w+)' is not defined", str(e)).group(1)
            assert falta in defs and falta not in pedidos, falta
            pedidos.append(falta)
    raise RuntimeError("demasiadas dependencias")
