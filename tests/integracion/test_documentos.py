"""C1 y C3 por HTTP: subir PDF, TXT y MD, fragmentos por página, PDF sin texto, duplicados y rechazos."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cotejo.documentos.extraccion import EXPLICACION_ESCANEADO
from cotejo.documentos.fragmentador import MAXIMO, RESTO_MINIMO
from cotejo.documentos.pdf_simple import pdf_de_texto, pdf_escaneado
from cotejo.modelos import Bitacora, Carga, CargaArchivo, Documento, Fragmento
from tests.apoyo.fabricas import crear_proveedor, crear_usuario

Entrar = Callable[[int], None]

PARRAFO = (
    "CLÁUSULA QUINTA. El cliente pagará cada factura dentro de los treinta días naturales siguientes a la "
    "recepción del comprobante fiscal, mediante transferencia electrónica a la cuenta del proveedor. "
)
PAGINA_1 = PARRAFO * 6 + "Marca de la primera página: ALFA."
PAGINA_2 = "CLÁUSULA SEXTA. La pena por mora es del 2% mensual sobre saldos insolutos. " * 8 + "Marca: BETA."


def _archivo(
    nombre: str, contenido: bytes, tipo: str = "application/octet-stream"
) -> tuple[str, tuple[str, bytes, str]]:
    return ("archivos", (nombre, contenido, tipo))


def test_subir_pdf_txt_y_md_los_indexa_por_pagina(cliente: TestClient, sesion: Session, entrar_como: Entrar) -> None:
    capturista = crear_usuario(sesion, rol="capturista")
    proveedor = crear_proveedor(sesion, nombre="Aceros Ficticios del Bajío SA de CV")
    entrar_como(capturista.id)
    r = cliente.post(
        "/api/documentos",
        files=[
            _archivo("contrato.pdf", pdf_de_texto([PAGINA_1, PAGINA_2]), "application/pdf"),
            _archivo("politica.md", "# Política de pagos\n\nLos pagos se programan los viernes.".encode()),
            _archivo("notas.txt", "Descuento por pronto pago del 2% a diez días.".encode()),
        ],
        data={"proveedor_id": str(proveedor.id)},
    )
    assert r.status_code == 200, r.text
    pdf, md, txt = r.json()
    assert pdf["resultado"] == "indexado" and pdf["paginas"] == 2 and pdf["fragmentos"] >= 3
    assert md["resultado"] == "indexado" and md["paginas"] == 1 and md["fragmentos"] == 1
    assert txt["resultado"] == "indexado" and txt["paginas"] == 1 and txt["motivos"] == []

    fragmentos = list(
        sesion.scalars(select(Fragmento).where(Fragmento.documento_id == pdf["documento_id"]).order_by(Fragmento.orden))
    )
    assert [f.orden for f in fragmentos] == list(range(1, len(fragmentos) + 1))
    assert {f.pagina for f in fragmentos} == {1, 2}
    # Ningún fragmento mezcla páginas: la cita es documento y página.
    for fragmento in fragmentos:
        assert not ("ALFA" in fragmento.texto and "BETA" in fragmento.texto)
        assert len(fragmento.texto) <= MAXIMO + RESTO_MINIMO
        assert fragmento.texto_normalizado == fragmento.texto_normalizado.lower()
        assert "á" not in fragmento.texto_normalizado
    pagina_1 = [f for f in fragmentos if f.pagina == 1]
    assert len(pagina_1) >= 2
    assert pagina_1[1].texto[:40] in pagina_1[0].texto, "fragmentos consecutivos de una página se traslapan"
    assert any("ALFA" in f.texto for f in pagina_1)
    # El índice de palabras se calculó en la base con la configuración de español (raíces sin acentos).
    con_raiz = sesion.scalar(
        select(func.count())
        .select_from(Fragmento)
        .where(
            Fragmento.documento_id == pdf["documento_id"],
            Fragmento.tsv.op("@@")(func.to_tsquery("spanish", "clausulas")),
        )
    )
    assert con_raiz == len(fragmentos)

    detalle = cliente.get(f"/api/documentos/{pdf['documento_id']}").json()
    assert detalle["paginas_con_texto"] == [1, 2]
    assert detalle["proveedor"] == {"id": proveedor.id, "rfc": proveedor.rfc, "nombre": proveedor.nombre}
    assert detalle["subido_por"] == {"id": capturista.id, "nombre": capturista.nombre, "rol": "capturista"}
    assert detalle["estado"] == "indexado" and detalle["fragmentos"] == len(fragmentos)

    lista = cliente.get("/api/documentos", params={"proveedor_id": proveedor.id}).json()
    assert lista["total"] == 3 and len(lista["elementos"]) == 3 and lista["pagina"] == 1


def test_pdf_sin_texto_queda_marcado_y_la_carga_responde_200(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    r = cliente.post("/api/documentos", files=[_archivo("escaneado.pdf", pdf_escaneado(), "application/pdf")])
    assert r.status_code == 200, r.text
    (resultado,) = r.json()
    assert resultado["resultado"] == "sin_texto"
    assert resultado["explicacion"] == EXPLICACION_ESCANEADO
    assert resultado["paginas"] == 1 and resultado["fragmentos"] == 0
    documento = sesion.get_one(Documento, resultado["documento_id"])
    assert documento.estado == "sin_texto" and documento.explicacion == EXPLICACION_ESCANEADO
    detalle = cliente.get(f"/api/documentos/{documento.id}").json()
    assert detalle["estado"] == "sin_texto" and detalle["paginas_con_texto"] == []


def test_un_archivo_malo_no_tumba_a_los_demas_y_el_mismo_archivo_no_se_duplica(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    usuario = crear_usuario(sesion, rol="capturista")
    entrar_como(usuario.id)
    bueno = b"Vigencia del contrato: doce meses a partir de la firma."
    r = cliente.post(
        "/api/documentos",
        files=[
            _archivo("bueno.txt", bueno),
            _archivo("programa.exe", b"MZ..."),
            _archivo("falso.pdf", b"no soy un pdf"),
            _archivo("roto.pdf", b"%PDF-1.4\nbasura sin estructura"),
            _archivo("latin.txt", "Política".encode("latin-1")),
            _archivo("copia.txt", bueno),
        ],
    )
    assert r.status_code == 200, r.text
    por_nombre = {x["nombre"]: x for x in r.json()}
    assert por_nombre["bueno.txt"]["resultado"] == "indexado"
    assert por_nombre["programa.exe"]["motivos"][0]["codigo"] == "EXTENSION_NO_PERMITIDA"
    assert por_nombre["falso.pdf"]["motivos"][0]["codigo"] == "FIRMA_INVALIDA"
    assert por_nombre["roto.pdf"]["motivos"][0]["codigo"] == "PDF_ILEGIBLE"
    assert por_nombre["latin.txt"]["motivos"][0]["codigo"] == "TEXTO_NO_UTF8"
    assert all(
        por_nombre[n]["resultado"] == "rechazado" for n in ("programa.exe", "falso.pdf", "roto.pdf", "latin.txt")
    )
    assert all(m["severidad"] == "rechazo" for x in r.json() for m in x["motivos"])
    assert por_nombre["copia.txt"]["resultado"] == "duplicado"
    assert por_nombre["copia.txt"]["documento_id"] == por_nombre["bueno.txt"]["documento_id"]
    assert sesion.scalar(select(func.count()).select_from(Documento)) == 1

    # D7: la carga queda en bitácora con quién y qué, y cada archivo leído queda ligado a la carga.
    registro = sesion.scalars(select(Bitacora).where(Bitacora.accion == "CARGA_DOCUMENTO")).one()
    assert registro.usuario_id == usuario.id and registro.entidad == "carga"
    archivos = registro.detalle["archivos"]
    assert isinstance(archivos, list) and len(archivos) == 6
    carga = sesion.get_one(Carga, int(registro.entidad_id or 0))
    assert carga.tipo == "documento"
    resultados = sesion.scalars(select(CargaArchivo.resultado).where(CargaArchivo.carga_id == carga.id)).all()
    assert sorted(resultados) == ["duplicada", "indexado", "rechazada", "rechazada"]


def test_el_fragmento_que_abre_una_cita_trae_documento_pagina_y_vecinos(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    (doc,) = cliente.post(
        "/api/documentos", files=[_archivo("contrato.pdf", pdf_de_texto([PAGINA_1, PAGINA_2]), "application/pdf")]
    ).json()
    ids = list(
        sesion.scalars(
            select(Fragmento.id).where(Fragmento.documento_id == doc["documento_id"]).order_by(Fragmento.orden)
        )
    )
    primero = cliente.get(f"/api/fragmentos/{ids[0]}").json()
    assert primero["documento"] == {"id": doc["documento_id"], "nombre": "contrato.pdf"}
    assert primero["pagina"] == 1 and primero["orden"] == 1
    assert primero["anterior_id"] is None and primero["siguiente_id"] == ids[1]
    ultimo = cliente.get(f"/api/fragmentos/{ids[-1]}").json()
    assert ultimo["pagina"] == 2 and ultimo["siguiente_id"] is None and ultimo["anterior_id"] == ids[-2]
    assert "BETA" in ultimo["texto"]
    faltante = cliente.get("/api/fragmentos/999999999")
    assert faltante.status_code == 404 and faltante.json()["error"]["codigo"] == "FRAGMENTO_NO_ENCONTRADO"
    assert cliente.get("/api/documentos/999999999").json()["error"]["codigo"] == "DOCUMENTO_NO_ENCONTRADO"


def test_solo_el_capturista_sube_y_el_proveedor_debe_existir(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    archivo = [_archivo("a.txt", b"texto de prueba suficiente")]
    assert cliente.post("/api/documentos", files=archivo).status_code == 401
    entrar_como(crear_usuario(sesion, rol="aprobador").id)
    r = cliente.post("/api/documentos", files=archivo)
    assert r.status_code == 403 and r.json()["error"]["codigo"] == "ROL_INSUFICIENTE"
    # Consultar documentos sí es para cualquier rol.
    assert cliente.get("/api/documentos").status_code == 200
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    r = cliente.post("/api/documentos", files=archivo, data={"proveedor_id": "987654321"})
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "PROVEEDOR_NO_ENCONTRADO"
    assert sesion.scalar(select(func.count()).select_from(Documento)) == 0
    muchos = [_archivo(f"d{i}.txt", f"documento número {i} con texto".encode()) for i in range(11)]
    r = cliente.post("/api/documentos", files=muchos)
    assert r.status_code == 422 and r.json()["error"]["codigo"] == "DEMASIADOS_ARCHIVOS"


def test_un_pdf_que_la_biblioteca_no_sabe_leer_se_rechaza_sin_tumbar_la_carga(
    cliente: TestClient, sesion: Session, entrar_como: Entrar
) -> None:
    entrar_como(crear_usuario(sesion, rol="capturista").id)
    # Mismo PDF con el nombre del filtro de compresión alterado: el lector falla con un error que no es "de PDF".
    alterado = pdf_de_texto([PAGINA_1]).replace(b"/FlateDecode", b"/FlateDecoWe")
    r = cliente.post(
        "/api/documentos",
        files=[
            _archivo("bueno.txt", b"Vigencia del contrato: doce meses a partir de la firma."),
            _archivo("alterado.pdf", alterado, "application/pdf"),
            _archivo("otro.md", b"# Anexo\n\nLas refacciones se surten en cuatro dias habiles."),
        ],
    )
    assert r.status_code == 200, r.text
    bueno, malo, otro = r.json()
    assert bueno["resultado"] == "indexado" and otro["resultado"] == "indexado"
    assert malo["resultado"] == "rechazado" and malo["motivos"][0]["codigo"] == "PDF_ILEGIBLE"
    assert sesion.scalar(select(func.count()).select_from(Documento)) == 2
