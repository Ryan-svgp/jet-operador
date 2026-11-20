
from datetime import datetime
from math import radians, sin, cos, asin, sqrt
from zoneinfo import ZoneInfo

import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(
    page_title="JET - Baterias DF",
    page_icon="🔋",
    layout="wide"
)

API = "https://logistic.gojet.app/api/v0/urent"
CITY_ID = "6787b812c168def1b2c6d143"

# Limites aproximados das regiões, não oficiais.
AREAS = {
    "Asa Sul": ("circle", -15.8293, -47.8927, 4.13),
    "Asa Norte": ("circle", -15.7602, -47.8758, 3.87),
    "Sudoeste": ("circle", -15.7871, -47.9318, 2.57),
    "Esplanada": ("polygon", [
        (-15.7930, -47.8840),
        (-15.7892, -47.8730),
        (-15.7918, -47.8610),
        (-15.8025, -47.8610),
        (-15.8032, -47.8735),
        (-15.7998, -47.8840)
    ]),
    "Águas Claras": (
        "box", -15.8633, -15.8155, -48.0619, -48.0036
    ),
    "Guará": (
        "box", -15.8534, -15.8041, -47.9993, -47.9579
    )
}


def distancia(lat1, lon1, lat2, lon2):
    r = 6371.0088
    a = sin(radians(lat2-lat1)/2)**2
    a += (
        cos(radians(lat1)) *
        cos(radians(lat2)) *
        sin(radians(lon2-lon1)/2)**2
    )
    return 2*r*asin(min(1, sqrt(a)))


def dentro_poligono(lat, lon, pontos):
    dentro = False
    j = len(pontos)-1

    for i in range(len(pontos)):
        yi, xi = pontos[i]
        yj, xj = pontos[j]

        if ((yi > lat) != (yj > lat)):
            limite = (
                (xj-xi)*(lat-yi)/(yj-yi)+xi
            )
            if lon < limite:
                dentro = not dentro

        j = i

    return dentro


def dentro_area(lat, lon, area):
    tipo = area[0]

    if tipo == "circle":
        _, cy, cx, raio = area
        return distancia(lat, lon, cy, cx) <= raio

    if tipo == "box":
        _, ymin, ymax, xmin, xmax = area
        return ymin <= lat <= ymax and xmin <= lon <= xmax

    if tipo == "polygon":
        return dentro_poligono(lat, lon, area[1])

    return False


def centro_area(area):
    if area[0] == "circle":
        return [area[1], area[2]]

    if area[0] == "box":
        return [
            (area[1]+area[2])/2,
            (area[3]+area[4])/2
        ]

    pontos = area[1]
    return [
        sum(p[0] for p in pontos)/len(pontos),
        sum(p[1] for p in pontos)/len(pontos)
    ]


def desenhar_area(mapa, area):
    tipo = area[0]

    if tipo == "circle":
        folium.Circle(
            [area[1], area[2]],
            radius=area[3]*1000,
            color="blue",
            fill=True,
            fill_opacity=0.05
        ).add_to(mapa)

    elif tipo == "box":
        folium.Rectangle(
            [[area[1], area[3]], [area[2], area[4]]],
            color="blue",
            fill=True,
            fill_opacity=0.05
        ).add_to(mapa)

    else:
        folium.Polygon(
            area[1],
            color="blue",
            fill=True,
            fill_opacity=0.05
        ).add_to(mapa)


@st.cache_data(ttl=45)
def buscar_bikes():
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
            headers={"Accept": "application/json"},
            timeout=20
        )

        resposta.raise_for_status()
        dados = resposta.json()

        if not isinstance(dados.get("entries"), list):
            raise ValueError("Formato inesperado da API")

        todos.extend(dados["entries"])

        total_paginas = int(dados.get("total_pages", 1))
        if total_paginas < 1 or total_paginas > 1000:
            raise ValueError("Paginação inválida")

        if pagina >= total_paginas:
            break

        pagina += 1

    return todos, datetime.now(
        ZoneInfo("America/Sao_Paulo")
    ).strftime("%d/%m/%Y %H:%M:%S")


def processar(bikes):
    registros = []
    vistos = set()
    invalidos = 0

    for b in bikes:
        try:
            bat = float(b["battery_percent"])*100
            lat = float(b["location_lat"])
            lon = float(b["location_lng"])

            if not (
                0 <= bat <= 100
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                invalidos += 1
                continue

        except (KeyError, TypeError, ValueError):
            invalidos += 1
            continue

        ident = (
            b.get("id")
            or b.get("_id")
            or b.get("identifier")
        )

        if ident is not None:
            if str(ident) in vistos:
                continue
            vistos.add(str(ident))

        status = str(b.get("status") or "").lower()
        state = str(b.get("state") or "").lower()

        indisponivel = (
            b.get("is_rented") is True
            or status in {"in_use", "rented", "maintenance"}
            or state in {"in_use", "rented", "maintenance"}
        )

        registros.append({
            "Patinete": str(
                b.get("identifier") or ident or "Sem ID"
            ),
            "Bateria": round(bat, 2),
            "Latitude": lat,
            "Longitude": lon,
            "Solto": not bool(b.get("parking_id")),
            "Indisponivel": indisponivel
        })

    return pd.DataFrame(registros), invalidos


# ======================================
# INTERFACE
# ======================================

st.title("🔋 JET - Baterias por Região")
st.caption(
    "Consulta da porcentagem atual de bateria, "
    "sem previsão ou simulação."
)

st.info(
    "Os limites das regiões são aproximados "
    "e podem se sobrepor."
)

col1, col2 = st.columns([2, 1])

with col1:
    regiao = st.selectbox(
        "📍 Escolha a região",
        list(AREAS.keys())
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
    buscar_bikes.clear()

try:
    with st.spinner("Buscando baterias..."):
        bikes, atualizado = buscar_bikes()
        df, invalidos = processar(bikes)

except (requests.RequestException, ValueError) as erro:
    st.error(f"Erro ao consultar a API: {erro}")
    st.warning(
        "Não foi possível obter a contagem. "
        "Erro de acesso não significa zero baterias."
    )
    st.stop()

if df.empty:
    st.warning(
        "A API não retornou patinetes com "
        "bateria e localização válidas."
    )
    st.stop()

if not incluir_soltos:
    df = df[~df["Solto"]]

if excluir_indisponiveis:
    df = df[~df["Indisponivel"]]

area = AREAS[regiao]

df_area = df[
    df.apply(
        lambda r: dentro_area(
            r["Latitude"],
            r["Longitude"],
            area
        ),
        axis=1
    )
].copy()

df_filtrado = df_area[
    df_area["Bateria"] <= limite
].sort_values("Bateria").copy()

# ======================================
# RESULTADOS
# ======================================

a, b, c = st.columns(3)

a.metric(
    f"🔋 Baterias até {limite}%",
    len(df_filtrado)
)

b.metric(
    "🛴 Patinetes na área",
    len(df_area)
)

c.metric(
    "📍 Soltos com bateria baixa",
    int(df_filtrado["Solto"].sum())
)

st.caption(
    f"Atualizado: {atualizado} (Brasília) | "
    f"Registros da API: {len(bikes)} | "
    f"Registros inválidos: {invalidos}"
)

st.warning(
    "A contagem representa patinetes com bateria "
    "baixa, não necessariamente tarefas de "
    "alimentação liberadas no Jet Crew."
)

aba1, aba2, aba3 = st.tabs([
    "🗺️ Mapa",
    "📋 Patinetes",
    "🏆 Ranking"
])

# ======================================
# MAPA
# ======================================

with aba1:
    mapa = folium.Map(
        location=centro_area(area),
        zoom_start=13
    )

    desenhar_area(mapa, area)

    for _, r in df_filtrado.iterrows():
        pct = r["Bateria"]
        lat = r["Latitude"]
        lon = r["Longitude"]

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
            f"Patinete: {r['Patinete']}"
            f"<br>Bateria: {pct:.1f}%"
            f"<br>{'Solto' if r['Solto'] else 'Estacionado'}"
            f'<br><a href="{link}" target="_blank">'
            "Abrir no Google Maps</a>"
        )

        folium.CircleMarker(
            [lat, lon],
            radius=7,
            color=cor,
            fill=True,
            fill_opacity=0.85,
            popup=folium.Popup(popup, max_width=280)
        ).add_to(mapa)

    st_folium(
        mapa,
        height=520,
        use_container_width=True,
        returned_objects=[]
    )

    st.caption(
        "🔴 0-10% | 🟠 11-20% | 🟢 21-35%"
    )

# ======================================
# LISTA
# ======================================

with aba2:
    if df_filtrado.empty:
        st.info("Nenhuma bateria encontrada nesse filtro.")
    else:
        tabela = df_filtrado[[
            "Patinete",
            "Bateria",
            "Solto",
            "Latitude",
            "Longitude"
        ]]

        st.dataframe(
            tabela,
            hide_index=True,
            use_container_width=True
        )

        st.download_button(
            "⬇️ Baixar lista CSV",
            tabela.to_csv(index=False).encode("utf-8-sig"),
            file_name="jet_baterias.csv",
            mime="text/csv"
        )

# ======================================
# RANKING
# ======================================

with aba3:
    ranking = []

    for nome, config in AREAS.items():
        dados_area = df[
            df.apply(
                lambda r: dentro_area(
                    r["Latitude"],
                    r["Longitude"],
                    config
                ),
                axis=1
            )
        ]

        encontrados = dados_area[
            dados_area["Bateria"] <= limite
        ]

        ranking.append({
            "Região": nome,
            "Baterias": len(encontrados),
            "Soltos": int(encontrados["Solto"].sum())
        })

    ranking_df = pd.DataFrame(ranking)

    ranking_df = ranking_df.sort_values(
        "Baterias",
        ascending=False
    )

    st.dataframe(
        ranking_df,
        hide_index=True,
        use_container_width=True
    )

    st.caption(
        "As áreas podem se sobrepor. "
        "Não some os totais do ranking."
    )
