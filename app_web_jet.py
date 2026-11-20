
import math
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

# Mesma configuração HTTP do código antigo
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
}

# Áreas aproximadas, baseadas no projeto anterior
AREAS = {
    "Asa Sul": ("circle", -15.8293, -47.8927, 4.13),
    "Asa Norte": ("circle", -15.7602, -47.8758, 3.87),
    "Sudoeste": ("circle", -15.7871, -47.9318, 2.57),
    "Esplanada": ("box", -15.806, -15.785, -47.886, -47.860),
    "Águas Claras": ("box", -15.8633, -15.8155, -48.0619, -48.0036),
    "Guará": ("box", -15.8534, -15.8041, -47.9993, -47.9579),
}


def haversine(lat1, lon1, lat2, lon2):
    raio = 6371.0
    a = math.sin(math.radians(lat2-lat1)/2)**2
    a += (
        math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(math.radians(lon2-lon1)/2)**2
    )
    return 2 * raio * math.asin(min(1, math.sqrt(a)))


def dentro(lat, lon, area):
    if area[0] == "circle":
        _, cy, cx, km = area
        return haversine(lat, lon, cy, cx) <= km

    _, lat_min, lat_max, lon_min, lon_max = area
    return (
        lat_min <= lat <= lat_max
        and lon_min <= lon <= lon_max
    )


def centro(area):
    if area[0] == "circle":
        return [area[1], area[2]]
    return [
        (area[1] + area[2]) / 2,
        (area[3] + area[4]) / 2
    ]


def desenhar_limites(mapa, area):
    if area[0] == "circle":
        folium.Circle(
            [area[1], area[2]],
            radius=area[3] * 1000,
            color="blue",
            fill=True,
            fill_opacity=0.04
        ).add_to(mapa)
    else:
        folium.Rectangle(
            [[area[1], area[3]], [area[2], area[4]]],
            color="blue",
            fill=True,
            fill_opacity=0.04
        ).add_to(mapa)


@st.cache_data(ttl=60, show_spinner=False)
def buscar_baterias():
    todos = []
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
            cf = resposta.headers.get("cf-mitigated", "")
            if resposta.status_code == 403 and cf == "challenge":
                raise RuntimeError(
                    "403: Cloudflare exige verificação. "
                    "A API não forneceu os dados."
                )
            raise RuntimeError(
                f"API retornou HTTP {resposta.status_code} "
                f"na página {pagina}."
            )

        try:
            dados = resposta.json()
        except ValueError:
            raise RuntimeError("A API não retornou JSON válido.")

        if not isinstance(dados, dict):
            raise RuntimeError("Formato de resposta inesperado.")

        entradas = dados.get("entries")
        if not isinstance(entradas, list):
            raise RuntimeError("Campo 'entries' não encontrado.")

        todos.extend(entradas)

        total = int(dados.get("total_pages", 1))
        if total < 1 or total > 1000:
            raise RuntimeError("Paginação inválida.")

        if pagina >= total:
            break

        pagina += 1

    hora = datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")
    return todos, hora


def montar_dataframe(bikes):
    linhas = []
    vistos = set()

    for bike in bikes:
        try:
            porcentagem = float(bike["battery_percent"]) * 100
            lat = float(bike["location_lat"])
            lon = float(bike["location_lng"])

            if not (
                0 <= porcentagem <= 100
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                continue
        except (KeyError, TypeError, ValueError):
            continue

        identificador = (
            bike.get("id")
            or bike.get("_id")
            or bike.get("identifier")
        )

        if identificador is not None:
            identificador = str(identificador)
            if identificador in vistos:
                continue
            vistos.add(identificador)

        status = str(bike.get("status") or "").lower()
        state = str(bike.get("state") or "").lower()

        indisponivel = (
            bike.get("is_rented") is True
            or status in {"rented", "in_use", "maintenance"}
            or state in {"rented", "in_use", "maintenance"}
        )

        linhas.append({
            "Patinete": str(
                bike.get("identifier")
                or identificador
                or "Sem ID"
            ),
            "Bateria (%)": round(porcentagem, 2),
            "Latitude": lat,
            "Longitude": lon,
            "Solto": not bool(bike.get("parking_id")),
            "Indisponível": indisponivel
        })

    return pd.DataFrame(
        linhas,
        columns=[
            "Patinete", "Bateria (%)", "Latitude",
            "Longitude", "Solto", "Indisponível"
        ]
    )


st.title("🔋 JET — Baterias por Área")
st.caption("Porcentagem atual recebida da API, sem simulação.")

col1, col2 = st.columns(2)

with col1:
    regiao = st.selectbox(
        "📍 Região",
        list(AREAS.keys())
    )

with col2:
    limite = st.slider(
        "🔋 Bateria máxima",
        min_value=0,
        max_value=35,
        value=35,
        step=1,
        format="%d%%"
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

if st.button("🔄 Atualizar consulta", type="primary"):
    buscar_baterias.clear()
    st.rerun()

try:
    with st.spinner("Consultando a API Jet..."):
        bikes, hora = buscar_baterias()
        df = montar_dataframe(bikes)

except (requests.RequestException, RuntimeError) as erro:
    st.error(str(erro))
    st.warning(
        "Consulta indisponível. Não é possível confirmar "
        "a quantidade de baterias neste momento."
    )
    st.stop()

if df.empty:
    st.warning(
        "A consulta foi concluída, mas nenhum registro "
        "válido de bateria e localização foi encontrado."
    )
    st.stop()

if not incluir_soltos:
    df = df[~df["Solto"]].copy()

if excluir_indisponiveis:
    df = df[~df["Indisponível"]].copy()

area = AREAS[regiao]

df_regiao = df[
    df.apply(
        lambda x: dentro(
            x["Latitude"],
            x["Longitude"],
            area
        ),
        axis=1
    )
].copy()

resultado = df_regiao[
    df_regiao["Bateria (%)"] <= limite
].copy()

resultado = resultado.sort_values("Bateria (%)")

c1, c2, c3 = st.columns(3)

c1.metric(f"Até {limite}%", len(resultado))
c2.metric("Total na região", len(df_regiao))
c3.metric(
    "Soltos até o limite",
    int(resultado["Solto"].sum())
)

st.caption(f"Última consulta: {hora} — Brasília")

st.info(
    "A contagem inclui patinetes com bateria baixa. "
    "Isso não garante que estejam liberados para alimentação."
)

tab_mapa, tab_lista, tab_ranking = st.tabs([
    "🗺️ Mapa",
    "📋 Lista",
    "🏆 Ranking"
])

with tab_mapa:
    mapa = folium.Map(
        location=centro(area),
        zoom_start=13
    )

    desenhar_limites(mapa, area)

    for _, bike in resultado.iterrows():
        lat = bike["Latitude"]
        lon = bike["Longitude"]
        pct = bike["Bateria (%)"]

        if pct <= 10:
            cor = "red"
        elif pct <= 20:
            cor = "orange"
        else:
            cor = "green"

        link = (
            "https://www.google.com/maps/search/"
            f"?api=1&query={lat},{lon}"
        )

        popup = (
            f"Patinete: {bike['Patinete']}<br>"
            f"Bateria: {pct:.1f}%<br>"
            f"<a href='{link}' target='_blank'>"
            "Abrir no Maps</a>"
        )

        folium.CircleMarker(
            [lat, lon],
            radius=6,
            color=cor,
            fill=True,
            fill_opacity=0.8,
            popup=popup
        ).add_to(mapa)

    st_folium(
        mapa,
        height=500,
        use_container_width=True,
        returned_objects=[]
    )

with tab_lista:
    st.dataframe(
        resultado,
        hide_index=True,
        use_container_width=True
    )

    st.download_button(
        "⬇️ Exportar CSV",
        resultado.to_csv(index=False).encode("utf-8-sig"),
        file_name="baterias_jet.csv",
        mime="text/csv"
    )

with tab_ranking:
    dados = []

    for nome, configuracao in AREAS.items():
        filtrado = df[
            df.apply(
                lambda x: dentro(
                    x["Latitude"],
                    x["Longitude"],
                    configuracao
                ),
                axis=1
            )
        ]

        filtrado = filtrado[
            filtrado["Bateria (%)"] <= limite
        ]

        dados.append({
            "Região": nome,
            "Quantidade": len(filtrado),
            "Soltos": int(filtrado["Solto"].sum())
        })

    ranking = pd.DataFrame(dados).sort_values(
        "Quantidade",
        ascending=False
    )

    st.dataframe(
        ranking,
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "Regiões aproximadas podem se sobrepor. "
        "Não some os totais do ranking."
    )
