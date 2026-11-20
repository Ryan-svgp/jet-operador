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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
}

# =========================================================
# 6 REGIÕES COM POLÍGONOS
# Obs.: são aproximações melhores que os círculos.
# Se quiser, depois refinamos ponto por ponto.
# =========================================================
REGIOES = {
    "Asa Sul": [
        (-15.8398, -47.9135),
        (-15.8325, -47.9030),
        (-15.8270, -47.8950),
        (-15.8195, -47.8860),
        (-15.8115, -47.8765),
        (-15.8045, -47.8680),
        (-15.7995, -47.8615),
        (-15.7960, -47.8605),
        (-15.7938, -47.8640),
        (-15.7942, -47.8725),
        (-15.7988, -47.8820),
        (-15.8065, -47.8915),
        (-15.8145, -47.9005),
        (-15.8228, -47.9095),
        (-15.8308, -47.9162),
        (-15.8398, -47.9135),
    ],
    "Asa Norte": [
        (-15.7935, -47.8595),
        (-15.7890, -47.8590),
        (-15.7830, -47.8610),
        (-15.7755, -47.8630),
        (-15.7685, -47.8645),
        (-15.7610, -47.8665),
        (-15.7548, -47.8690),
        (-15.7495, -47.8735),
        (-15.7465, -47.8785),
        (-15.7460, -47.8838),
        (-15.7495, -47.8868),
        (-15.7568, -47.8875),
        (-15.7650, -47.8878),
        (-15.7730, -47.8875),
        (-15.7815, -47.8868),
        (-15.7890, -47.8850),
        (-15.7945, -47.8820),
        (-15.7960, -47.8740),
        (-15.7950, -47.8650),
        (-15.7935, -47.8595),
    ],
    "Sudoeste": [
        (-15.7948, -47.9418),
        (-15.7865, -47.9410),
        (-15.7775, -47.9395),
        (-15.7705, -47.9365),
        (-15.7685, -47.9295),
        (-15.7705, -47.9220),
        (-15.7765, -47.9185),
        (-15.7855, -47.9185),
        (-15.7935, -47.9205),
        (-15.7990, -47.9260),
        (-15.8005, -47.9335),
        (-15.7985, -47.9395),
        (-15.7948, -47.9418),
    ],
    "Esplanada": [
        (-15.8060, -47.8870),
        (-15.8040, -47.8600),
        (-15.7960, -47.8600),
        (-15.7930, -47.8870),
        (-15.8060, -47.8870),
    ],
    "Águas Claras": [
        (-15.8585, -48.0585),
        (-15.8470, -48.0535),
        (-15.8370, -48.0490),
        (-15.8295, -48.0440),
        (-15.8235, -48.0350),
        (-15.8215, -48.0250),
        (-15.8235, -48.0150),
        (-15.8290, -48.0075),
        (-15.8380, -48.0030),
        (-15.8470, -48.0050),
        (-15.8555, -48.0105),
        (-15.8610, -48.0200),
        (-15.8625, -48.0310),
        (-15.8605, -48.0430),
        (-15.8585, -48.0585),
    ],
    "Guará": [
        (-15.8728, -47.9805),
        (-15.8665, -47.9680),
        (-15.8600, -47.9565),
        (-15.8500, -47.9535),
        (-15.8445, -47.9495),
        (-15.8455, -47.9430),
        (-15.8535, -47.9415),
        (-15.8615, -47.9465),
        (-15.8690, -47.9545),
        (-15.8755, -47.9660),
        (-15.8775, -47.9775),
        (-15.8728, -47.9805),
    ],
}

# =========================================================
# FUNÇÕES GEOGRÁFICAS
# =========================================================
def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def ponto_no_poligono(lat, lon, poligono):
    dentro = False
    j = len(poligono) - 1

    for i in range(len(poligono)):
        yi, xi = poligono[i]
        yj, xj = poligono[j]

        cruza = ((yi > lat) != (yj > lat))
        if cruza:
            x_intersec = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_intersec:
                dentro = not dentro

        j = i

    return dentro


def centro_poligono(poligono):
    lat = sum(p[0] for p in poligono) / len(poligono)
    lon = sum(p[1] for p in poligono) / len(poligono)
    return [lat, lon]


def desenhar_poligono(mapa, poligono, nome):
    folium.Polygon(
        locations=poligono,
        color="cyan",
        weight=2,
        fill=True,
        fill_opacity=0.06,
        popup=nome
    ).add_to(mapa)


# =========================================================
# API
# =========================================================
@st.cache_data(ttl=60, show_spinner=False)
def buscar_bikes():
    all_entries = []
    page = 1

    while True:
        r = requests.get(
            f"{API}/bikes",
            params={
                "city_id": CITY_ID,
                "page": page,
                "limit": 1000
            },
            headers=HEADERS,
            timeout=20
        )

        if r.status_code != 200:
            cf = r.headers.get("cf-mitigated", "")
            if r.status_code == 403 and cf == "challenge":
                raise RuntimeError(
                    "403: Cloudflare está bloqueando a API neste momento."
                )
            raise RuntimeError(
                f"API retornou HTTP {r.status_code} na página {page}."
            )

        try:
            data = r.json()
        except ValueError:
            raise RuntimeError("A API não retornou JSON válido.")

        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise RuntimeError("Formato inesperado da API.")

        all_entries.extend(entries)

        total_pages = int(data.get("total_pages", 1))
        if page >= total_pages:
            break

        page += 1

    hora = datetime.now(FUSO).strftime("%d/%m/%Y %H:%M:%S")
    return all_entries, hora


def montar_df(bikes):
    linhas = []
    vistos = set()

    for b in bikes:
        try:
            bateria = float(b["battery_percent"]) * 100
            lat = float(b["location_lat"])
            lon = float(b["location_lng"])
        except (KeyError, TypeError, ValueError):
            continue

        if not (0 <= bateria <= 100):
            continue

        ident = (
            b.get("id")
            or b.get("_id")
            or b.get("identifier")
            or "Sem ID"
        )
        ident = str(ident)

        if ident in vistos:
            continue
        vistos.add(ident)

        status = str(b.get("status") or "").lower()
        state = str(b.get("state") or "").lower()

        indisponivel = (
            b.get("is_rented") is True
            or status in {"rented", "in_use", "maintenance"}
            or state in {"rented", "in_use", "maintenance"}
        )

        linhas.append({
            "Patinete": str(b.get("identifier") or ident),
            "Bateria (%)": round(bateria, 1),
            "Latitude": lat,
            "Longitude": lon,
            "Solto": not bool(b.get("parking_id")),
            "Indisponível": indisponivel
        })

    return pd.DataFrame(linhas)


# =========================================================
# INTERFACE
# =========================================================
st.title("🔋 JET — Baterias por Região")
st.caption("Agora usando 6 regiões separadas com polígonos, sem círculos.")

st.warning(
    "Os polígonos são aproximações manuais melhores que os círculos. "
    "Se quiser, depois refinamos cada região ainda mais."
)

col1, col2 = st.columns(2)
with col1:
    regiao = st.selectbox("📍 Região", list(REGIOES.keys()))
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
    incluir_soltos = st.checkbox("Incluir patinetes soltos", value=True)
with col4:
    excluir_indisponiveis = st.checkbox(
        "Excluir em uso/manutenção",
        value=True
    )

if st.button("🔄 Atualizar consulta", type="primary", use_container_width=True):
    buscar_bikes.clear()
    st.rerun()

try:
    with st.spinner("Consultando a API Jet..."):
        bikes, hora = buscar_bikes()
        df = montar_df(bikes)
except (requests.RequestException, RuntimeError) as e:
    st.error(str(e))
    st.stop()

if df.empty:
    st.warning("Nenhum patinete válido foi encontrado na API.")
    st.stop()

if not incluir_soltos:
    df = df[~df["Solto"]].copy()

if excluir_indisponiveis:
    df = df[~df["Indisponível"]].copy()

poligono = REGIOES[regiao]

df_regiao = df[
    df.apply(
        lambda row: ponto_no_poligono(
            row["Latitude"],
            row["Longitude"],
            poligono
        ),
        axis=1
    )
].copy()

df_filtrado = df_regiao[
    df_regiao["Bateria (%)"] <= limite
].copy()

df_filtrado = df_filtrado.sort_values("Bateria (%)")

m1, m2, m3 = st.columns(3)
m1.metric(f"Até {limite}%", len(df_filtrado))
m2.metric("Patinetes na região", len(df_regiao))
m3.metric("Soltos com bateria baixa", int(df_filtrado["Solto"].sum()))

st.caption(f"Última consulta: {hora} — horário de Brasília")

tabs = st.tabs(["🗺️ Mapa", "📋 Lista", "🏆 Ranking"])

# =========================================================
# MAPA
# =========================================================
with tabs[0]:
    mapa = folium.Map(
        location=centro_poligono(poligono),
        zoom_start=13,
        tiles="CartoDB dark_matter"
    )

    desenhar_poligono(mapa, poligono, regiao)

    for _, bike in df_filtrado.iterrows():
        lat = bike["Latitude"]
        lon = bike["Longitude"]
        bat = bike["Bateria (%)"]

        if bat <= 10:
            cor = "red"
        elif bat <= 20:
            cor = "orange"
        else:
            cor = "green"

        if bike["Solto"]:
            radius = 8
        else:
            radius = 6

        maps_link = (
            f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
        )

        popup = (
            f"<b>Patinete:</b> {bike['Patinete']}<br>"
            f"<b>Bateria:</b> {bat:.1f}%<br>"
            f"<b>Tipo:</b> {'Solto' if bike['Solto'] else 'Estacionado'}<br>"
            f"<a href='{maps_link}' target='_blank'>Abrir no Maps</a>"
        )

        folium.CircleMarker(
            location=[lat, lon],
            radius=radius,
            color=cor,
            fill=True,
            fill_color=cor,
            fill_opacity=0.85,
            popup=folium.Popup(popup, max_width=300)
        ).add_to(mapa)

    st_folium(
        mapa,
        height=540,
        use_container_width=True,
        returned_objects=[]
    )

    st.caption(
        "🔴 0–10% | 🟠 11–20% | 🟢 21–35% | "
        "Bola maior = patinete solto"
    )

# =========================================================
# LISTA
# =========================================================
with tabs[1]:
    if df_filtrado.empty:
        st.info("Nenhum patinete encontrado nesse filtro.")
    else:
        tabela = df_filtrado[
            ["Patinete", "Bateria (%)", "Solto", "Latitude", "Longitude"]
        ].copy()

        st.dataframe(
            tabela,
            hide_index=True,
            use_container_width=True
        )

        st.download_button(
            "⬇️ Baixar CSV",
            tabela.to_csv(index=False).encode("utf-8-sig"),
            file_name="jet_baterias_regiao.csv",
            mime="text/csv"
        )

# =========================================================
# RANKING
# =========================================================
with tabs[2]:
    ranking = []

    for nome, poly in REGIOES.items():
        temp = df[
            df.apply(
                lambda row: ponto_no_poligono(
                    row["Latitude"],
                    row["Longitude"],
                    poly
                ),
                axis=1
            )
        ].copy()

        temp = temp[temp["Bateria (%)"] <= limite]

        ranking.append({
            "Região": nome,
            "Quantidade": len(temp),
            "Soltos": int(temp["Solto"].sum())
        })

    ranking_df = pd.DataFrame(ranking).sort_values(
        "Quantidade",
        ascending=False
    )

    st.dataframe(
        ranking_df,
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "Como agora cada região tem polígono próprio, a separação ficou "
        "muito melhor que no modelo com círculos."
    )
