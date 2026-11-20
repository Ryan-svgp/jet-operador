
import html
from datetime import datetime
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(
    page_title="JET Baterias DF",
    page_icon="🔋",
    layout="wide"
)

API = "https://logistic.gojet.app/api/v0/urent"
CITY_ID = "6787b812c168def1b2c6d143"
FUSO = ZoneInfo("America/Sao_Paulo")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
}

# ==========================================
# ZONAS OPERACIONAIS DA JET
# Coordenadas obtidas do monitor do Victor.
# Cada linha contém latitude,longitude.
# ==========================================

REGIOES_TEXTO = {
    "Asa Sul": """
-15.8113725,-47.9407954
-15.8091044,-47.9542923
-15.8439492,-47.9592705
-15.8498924,-47.9320621
-15.8490678,-47.9188442
-15.8395725,-47.8982878
-15.8354027,-47.8911638
-15.8301374,-47.8870174
-15.8243787,-47.8816795
-15.8127763,-47.8607368
-15.8101337,-47.8664447
-15.8098395,-47.8702828
-15.8052587,-47.8841954
-15.8030315,-47.8875593
-15.7992946,-47.8932023
-15.7997253,-47.8934786
-15.7974051,-47.8966355
-15.7954164,-47.8954872
-15.7954165,-47.8972907
-15.8054500,-47.9069000
-15.8047502,-47.9094325
-15.8088795,-47.9144079
-15.8111170,-47.9146198
-15.8120951,-47.9163767
-15.8116770,-47.9189196
-15.8125390,-47.9206468
-15.8142448,-47.9228193
-15.8145738,-47.9254800
-15.8122655,-47.9272879
-15.8107324,-47.9266335
-15.8073259,-47.9287791
-15.8113725,-47.9407954
""",

    "Asa Norte": """
-15.7323869,-47.9085234
-15.7268348,-47.8885460
-15.7697881,-47.8463173
-15.7828381,-47.8579903
-15.7874219,-47.8561234
-15.7921297,-47.8559305
-15.7902717,-47.8588915
-15.7865962,-47.8737617
-15.7853727,-47.8738689
-15.7841492,-47.8739762
-15.7839835,-47.8791469
-15.7838177,-47.8843179
-15.7837355,-47.8868889
-15.7836531,-47.8894601
-15.7834885,-47.8946024
-15.7822110,-47.8950342
-15.7809331,-47.8954661
-15.7800170,-47.8974533
-15.7792812,-47.8994572
-15.7797406,-47.9026380
-15.7803548,-47.9046455
-15.7777120,-47.9037016
-15.7367409,-47.9080414
-15.7401319,-47.9189514
-15.7406681,-47.9195565
-15.7332857,-47.9199494
-15.7323869,-47.9085234
""",

    "Sudoeste": """
-15.7735853,-47.9430470
-15.8091044,-47.9542923
-15.8113725,-47.9407954
-15.8073259,-47.9287792
-15.8046005,-47.9210437
-15.7979523,-47.9122246
-15.7948861,-47.9099366
-15.7922898,-47.9095155
-15.7913040,-47.9092956
-15.7904263,-47.9088209
-15.7894248,-47.9076246
-15.7878659,-47.9071283
-15.7848306,-47.9166234
-15.7825468,-47.9157987
-15.7735853,-47.9430470
""",

    "Esplanada": """
-15.8101329,-47.8664475
-15.8127763,-47.8607369
-15.8030314,-47.8480339
-15.7972916,-47.8510380
-15.7921298,-47.8559303
-15.7902717,-47.8588915
-15.7865962,-47.8737617
-15.7841492,-47.8739762
-15.7834884,-47.8946024
-15.7809331,-47.8954661
-15.7800168,-47.8974536
-15.7792812,-47.8994572
-15.7797406,-47.9026382
-15.7803548,-47.9046455
-15.7832690,-47.9057591
-15.7822998,-47.9092782
-15.7843531,-47.9099285
-15.7825468,-47.9157987
-15.7848306,-47.9166233
-15.7878659,-47.9071284
-15.7902705,-47.9033179
-15.7905182,-47.9003573
-15.7912615,-47.8982549
-15.7934769,-47.8942913
-15.7938956,-47.8945494
-15.7940311,-47.8946329
-15.7941671,-47.8947168
-15.7944395,-47.8948844
-15.7946901,-47.8950394
-15.7948117,-47.8951142
-15.7949334,-47.8951892
-15.7951730,-47.8953370
-15.7952946,-47.8954119
-15.7954163,-47.8954871
-15.7959095,-47.8957718
-15.7964056,-47.8960583
-15.7964367,-47.8960762
-15.7964677,-47.8960942
-15.7965297,-47.8961300
-15.7966538,-47.8962016
-15.7969017,-47.8963448
-15.7971500,-47.8964878
-15.7972731,-47.8965592
-15.7973042,-47.8965772
-15.7973199,-47.8965863
-15.7973277,-47.8965908
-15.7973355,-47.8965953
-15.7973439,-47.8966001
-15.7973525,-47.8966051
-15.7973704,-47.8966154
-15.7973878,-47.8966255
-15.7973966,-47.8966306
-15.7974052,-47.8966356
-15.7975502,-47.8964380
-15.7976952,-47.8962407
-15.7979852,-47.8958462
-15.7985653,-47.8950570
-15.7997253,-47.8934786
-15.7992945,-47.8932023
-15.8030299,-47.8875439
-15.8052595,-47.8841971
-15.8098403,-47.8702818
-15.8101329,-47.8664475
""",

    "Águas Claras": """
-15.8395727,-48.0001688
-15.8131067,-48.0111980
-15.8168595,-48.0215836
-15.8256118,-48.0353165
-15.8332979,-48.0676736
-15.8750792,-48.0462174
-15.8791201,-48.0324412
-15.8792238,-48.0137086
-15.8513801,-48.0269694
-15.8395727,-48.0001688
""",

    "Guará": """
-15.8091044,-47.9542923
-15.8054677,-47.9579830
-15.8041463,-47.9674244
-15.8048070,-47.9917145
-15.8085233,-48.0020142
-15.8131041,-48.0111967
-15.8395726,-48.0001688
-15.8613704,-47.9918003
-15.8583981,-47.9606438
-15.8439491,-47.9592706
-15.8091044,-47.9542923
"""
}


def converter_regiao(texto):
    pontos = []
    for linha in texto.strip().splitlines():
        lat, lon = linha.strip().split(",")
        pontos.append((float(lat), float(lon)))
    return pontos


REGIOES = {
    nome: converter_regiao(texto)
    for nome, texto in REGIOES_TEXTO.items()
}


# ==========================================
# IDENTIFICAR PATINETE DENTRO DA REGIÃO
# ==========================================

def ponto_no_poligono(lat, lon, pontos):
    dentro = False
    anterior = pontos[-1]

    for atual in pontos:
        y1, x1 = anterior
        y2, x2 = atual

        if (y1 > lat) != (y2 > lat):
            intersecao = (
                (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            )
            if lon < intersecao:
                dentro = not dentro

        anterior = atual

    return dentro


def identificar_regiao(row):
    # Se um ponto estiver em duas zonas,
    # atribui à primeira para não duplicar.
    for nome, pontos in REGIOES.items():
        if ponto_no_poligono(
            row["Latitude"],
            row["Longitude"],
            pontos
        ):
            return nome

    return None


# ==========================================
# CONSULTAR API
# ==========================================

@st.cache_data(ttl=60, show_spinner=False)
def consultar_api():
    registros = []
    pagina = 1

    while True:
        resposta = requests.get(
            f"{API}/bikes",
            params={
                "city_id": CITY_ID,
                "page": pagina,
                "limit": 1000
            },
            headers=HEADERS,
            timeout=20
        )

        if resposta.status_code != 200:
            challenge = (
                resposta.headers.get("cf-mitigated") == "challenge"
            )

            if challenge:
                raise RuntimeError(
                    "403 - Cloudflare bloqueou a consulta."
                )

            raise RuntimeError(
                f"HTTP {resposta.status_code} "
                f"na página {pagina}."
            )

        try:
            dados = resposta.json()
        except ValueError:
            raise RuntimeError(
                "A API não retornou JSON válido."
            )

        if not isinstance(dados, dict):
            raise RuntimeError(
                "Formato inesperado da API."
            )

        entradas = dados.get("entries")

        if not isinstance(entradas, list):
            raise RuntimeError(
                "A API não retornou a lista de patinetes."
            )

        registros.extend(entradas)

        total_paginas = int(
            dados.get("total_pages", 1)
        )

        if total_paginas < 1 or total_paginas > 1000:
            raise RuntimeError("Paginação inválida.")

        if pagina >= total_paginas:
            break

        pagina += 1

    atualizado = datetime.now(FUSO).strftime(
        "%d/%m/%Y %H:%M:%S"
    )

    return registros, atualizado


# ==========================================
# PROCESSAR BATERIAS
# ==========================================

def preparar_dados(registros):
    linhas = []
    vistos = set()

    for b in registros:
        try:
            bateria = float(
                b["battery_percent"]
            ) * 100

            lat = float(b["location_lat"])
            lon = float(b["location_lng"])

        except (KeyError, TypeError, ValueError):
            continue

        if not (
            0 <= bateria <= 100
            and -90 <= lat <= 90
            and -180 <= lon <= 180
        ):
            continue

        identidade = (
            b.get("id")
            or b.get("_id")
            or b.get("identifier")
        )

        if identidade is not None:
            identidade = str(identidade)

            if identidade in vistos:
                continue

            vistos.add(identidade)

        status = str(
            b.get("status") or ""
        ).lower()

        estado = str(
            b.get("state") or ""
        ).lower()

        indisponivel = (
            b.get("is_rented") is True
            or status in {
                "rented", "in_use", "maintenance"
            }
            or estado in {
                "rented", "in_use", "maintenance"
            }
        )

        linhas.append({
            "Patinete": str(
                b.get("identifier")
                or identidade
                or "Sem ID"
            ),
            "Bateria (%)": round(bateria, 2),
            "Latitude": lat,
            "Longitude": lon,
            "Solto": not bool(b.get("parking_id")),
            "Indisponivel": indisponivel
        })

    return pd.DataFrame(
        linhas,
        columns=[
            "Patinete",
            "Bateria (%)",
            "Latitude",
            "Longitude",
            "Solto",
            "Indisponivel"
        ]
    )


# ==========================================
# INTERFACE DO STREAMLIT
# ==========================================

st.title("🔋 JET - Baterias por Região")

st.caption(
    "Mapa com os contornos das seis zonas "
    "operacionais extraídos do monitor da Jet."
)

col1, col2 = st.columns(2)

with col1:
    regiao = st.selectbox(
        "📍 Escolha a região",
        list(REGIOES.keys())
    )

with col2:
    limite = st.slider(
        "🔋 Bateria máxima (%)",
        min_value=0,
        max_value=35,
        value=35,
        step=1
    )

col3, col4 = st.columns(2)

with col3:
    incluir_soltos = st.checkbox(
        "Incluir patinetes soltos",
        value=True
    )

with col4:
    excluir_indisponiveis = st.checkbox(
        "Excluir em uso/manutenção",
        value=True
    )

if st.button(
    "🔄 Atualizar dados",
    type="primary",
    use_container_width=True
):
    consultar_api.clear()
    st.rerun()


# ==========================================
# CARREGAMENTO
# ==========================================

try:
    with st.spinner("Consultando baterias..."):
        registros, atualizado = consultar_api()
        df = preparar_dados(registros)

except (requests.RequestException, RuntimeError) as erro:
    st.error(f"Falha na consulta: {erro}")
    st.warning(
        "A API não forneceu dados atualizados. "
        "Não é possível confirmar a contagem."
    )
    st.stop()

if df.empty:
    st.warning(
        "Nenhum registro válido de bateria "
        "e localização foi recebido."
    )
    st.stop()

if not incluir_soltos:
    df = df[~df["Solto"]].copy()

if excluir_indisponiveis:
    df = df[~df["Indisponivel"]].copy()

df["Região"] = df.apply(
    identificar_regiao,
    axis=1
)

df_regiao = df[
    df["Região"] == regiao
].copy()

df_filtrado = df_regiao[
    df_regiao["Bateria (%)"] <= limite
].sort_values("Bateria (%)").copy()


# ==========================================
# QUANTIDADES
# ==========================================

m1, m2, m3 = st.columns(3)

m1.metric(
    f"🔋 Baterias até {limite}%",
    len(df_filtrado)
)

m2.metric(
    "🛴 Patinetes na região",
    len(df_regiao)
)

m3.metric(
    "📍 Soltos até o limite",
    int(df_filtrado["Solto"].sum())
)

st.caption(
    f"Última consulta: {atualizado} "
    f"(Brasília) | Registros: {len(registros)}"
)

st.info(
    "A contagem representa patinetes com bateria "
    "baixa. Não garante tarefa de alimentação "
    "liberada no Jet Crew."
)


# ==========================================
# ABAS
# ==========================================

aba_mapa, aba_lista, aba_ranking = st.tabs([
    "🗺️ Mapa",
    "📋 Lista",
    "🏆 Ranking"
])


# ==========================================
# MAPA
# ==========================================

with aba_mapa:
    pontos = REGIOES[regiao]

    centro_lat = sum(
        p[0] for p in pontos
    ) / len(pontos)

    centro_lon = sum(
        p[1] for p in pontos
    ) / len(pontos)

    mapa = folium.Map(
        location=[centro_lat, centro_lon],
        zoom_start=13,
        tiles="CartoDB positron"
    )

    # Mostra as seis divisões.
    for nome, contorno in REGIOES.items():
        selecionada = nome == regiao

        folium.Polygon(
            locations=contorno,
            color=(
                "#0088CC"
                if selecionada
                else "#AAAAAA"
            ),
            weight=3 if selecionada else 1,
            fill=True,
            fill_opacity=(
                0.12 if selecionada else 0.02
            ),
            tooltip=nome
        ).add_to(mapa)

    # Mostra os patinetes filtrados.
    for _, bike in df_filtrado.iterrows():
        bat = bike["Bateria (%)"]
        lat = bike["Latitude"]
        lon = bike["Longitude"]

        if bat <= 10:
            cor = "red"
        elif bat <= 20:
            cor = "orange"
        else:
            cor = "green"

        tamanho = 8 if bike["Solto"] else 6

        link = (
            "https://www.google.com/maps/search/"
            f"?api=1&query={lat},{lon}"
        )

        identificador = html.escape(
            str(bike["Patinete"])
        )

        popup = (
            f"<b>Patinete:</b> {identificador}<br>"
            f"<b>Bateria:</b> {bat:.1f}%<br>"
            f"<b>Tipo:</b> "
            f"{'Solto' if bike['Solto'] else 'Estacionado'}<br>"
            f'<a href="{link}" target="_blank">'
            "Abrir no Maps</a>"
        )

        folium.CircleMarker(
            location=[lat, lon],
            radius=tamanho,
            color=cor,
            fill=True,
            fill_color=cor,
            fill_opacity=0.9,
            popup=folium.Popup(
                popup,
                max_width=280
            )
        ).add_to(mapa)

    # Enquadra a região no mapa.
    folium.FitBounds(pontos).add_to(mapa)

    st_folium(
        mapa,
        height=540,
        use_container_width=True,
        returned_objects=[]
    )

    st.caption(
        "🔴 0–10% | 🟠 11–20% | "
        "🟢 21–35% | Marcador maior = solto"
    )


# ==========================================
# LISTA DE PATINETES
# ==========================================

with aba_lista:
    if df_filtrado.empty:
        st.info(
            "Nenhum patinete encontrado "
            "com esse limite de bateria."
        )
    else:
        tabela = df_filtrado[[
            "Patinete",
            "Bateria (%)",
            "Solto",
            "Latitude",
            "Longitude"
        ]].copy()

        st.dataframe(
            tabela,
            hide_index=True,
            use_container_width=True
        )

        st.download_button(
            "⬇️ Exportar CSV",
            tabela.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name="jet_baterias.csv",
            mime="text/csv"
        )


# ==========================================
# RANKING POR REGIÃO
# ==========================================

with aba_ranking:
    filtrados = df[
        (df["Bateria (%)"] <= limite)
        & df["Região"].notna()
    ].copy()

    ranking = (
        filtrados.groupby("Região")
        .agg(
            Quantidade=("Patinete", "size"),
            Soltos=("Solto", "sum")
        )
        .reset_index()
    )

    ranking = pd.DataFrame({
        "Região": list(REGIOES.keys())
    }).merge(
        ranking,
        on="Região",
        how="left"
    )

    ranking = ranking.fillna({
        "Quantidade": 0,
        "Soltos": 0
    })

    ranking[["Quantidade", "Soltos"]] = (
        ranking[["Quantidade", "Soltos"]]
        .astype(int)
    )

    ranking = ranking.sort_values(
        "Quantidade",
        ascending=False
    )

    st.dataframe(
        ranking,
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "Cada patinete é associado a uma única "
        "região para evitar contagem duplicada."
    )
