import streamlit as st
import requests
import aiohttp
import asyncio
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh
import pydeck as pdk

CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]

@st.cache_data(ttl=300)
def get_token():
    url = "https://api.lufthansa.com/v1/oauth/token"
    r = requests.post(url, data={
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    })
    return r.json().get("access_token")

@st.cache_data(ttl=86400)
def get_airports(token):
    url = "https://api.lufthansa.com/v1/references/airports"
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(url, headers=headers, params={"limit": 1000, "lang": "en"})
    data = r.json()
    return {a["Names"]["Name"]["$"]: a["AirportCode"] for a in data["AirportResource"]["Airports"]["Airport"]}

async def get_flights(token, airport_code, date):
    url = f"https://api.lufthansa.com/v1/operations/flightstatus/departures/{airport_code}/{date}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("FlightStatusResource", {}).get("Flights", {}).get("Flight", [])
    return []

@st.cache_data(ttl=86400)
def get_coords():
    df = pd.read_csv("airports.csv")
    return dict(zip(df["IATA"], zip(df["Longitude"], df["Latitude"])))

def show_map(df):
    coords = get_coords()
    routes = []
    for _, row in df.iterrows():
        dep, arr = row["Départ"], row["Arrivée"]
        if dep in coords and arr in coords:
            routes.append({
                "from_lon": coords[dep][0],
                "from_lat": coords[dep][1],
                "to_lon": coords[arr][0],
                "to_lat": coords[arr][1],
                "flight": f"{row['Compagnie']} {row['Vol']}"
            })
    if not routes:
        st.warning("Aucune coordonnée trouvée pour les aéroports.")
        return

    layer = pdk.Layer(
        "LineLayer",
        routes,
        get_source_position=["from_lon", "from_lat"],
        get_target_position=["to_lon", "to_lat"],
        get_width=3,
        get_color=[255, 0, 0],
        pickable=True,
    )
    view_state = pdk.ViewState(latitude=20, longitude=0, zoom=2, pitch=0)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view_state, tooltip={"text": "{flight}"}))

def main():
    st.set_page_config(layout="wide")
    st.title("✈ Lufthansa Live Flights")
    st_autorefresh(interval=3 * 60 * 1000, key="refresh")

    token = get_token()
    if not token:
        st.error("Erreur OAuth Lufthansa")
        return

    airports = get_airports(token)
    airport_names = sorted(airports.keys())
    name = st.selectbox("Aéroport de départ", airport_names)
    code = airports[name]

    date = datetime.now().strftime("%Y-%m-%d")
    st.write(f"📍 {code} – {name}")

    if st.button("🔄 Rafraîchir les vols"):
        with st.spinner("Chargement..."):
            flights = asyncio.run(get_flights(token, code, date))
        if not flights:
            st.warning("Aucun vol trouvé.")
            return
        df = pd.json_normalize(flights)
        df = df[[
            "Departure.AirportCode", "Departure.ScheduledTimeLocal.DateTime",
            "Arrival.AirportCode", "Arrival.ScheduledTimeLocal.DateTime",
            "OperatingCarrier.AirlineID", "OperatingCarrier.FlightNumber",
            "FlightStatus.Status.Description"
        ]]
        df.columns = ["Départ", "Heure départ", "Arrivée", "Heure arrivée", "Compagnie", "Vol", "Statut"]
        st.dataframe(df, use_container_width=True)
        st.markdown("### 🗺 Carte des vols")
        show_map(df)
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("💾 Télécharger CSV", csv, "vols.csv", "text/csv")

if __name__ == "__main__":
    main()
